# 克隆自聚宽文章：https://www.joinquant.com/post/30481
# 标题：7年40倍，模拟超过两年，年化高回撤低
# 作者：quakecat

from __future__ import division
from bwlist import *
import math

def set_param():
    # 交易设置
    g.stocknum = 4 # 理想持股数量
    g.bearpercent = 0.3 # 熊市仓位
    g.bearposition = True # 熊市是否持仓
    g.sellrank = 10 # 排名多少位之后(不含)卖出
    g.buyrank = 9 # 排名多少位之前(含)可以买入

    # 初始筛选
    g.tradeday = 300 # 上市天数
    g.increase1d = 0.087 # 前一日涨幅
    g.tradevaluemin = 0.01 # 最小流通市值 单位（亿）
    g.tradevaluemax = 1000 # 最大流通市值 单位（亿）
    g.pbmin = 0.01 # 最小市净率
    g.pbmax = 30 # 最大市净率

    # 排名条件及权重，正数代表从小到大，负数表示从大到小
    # 各因子权重：总市值，流通市值，最新价格，5日平均成交量，60日涨幅
    g.weights = [5,5,8,4,10]
    
    # 配置择时
    g.MA = ['000001.XSHG', 10] # 均线择时
    g.choose_time_signal = True # 启用择时信号
    g.threshold = 0.003 # 牛熊切换阈值
    g.buyagain = 5 # 再次买入的间隔时间

# 获取股票n日以来涨幅，根据当前价计算
# n 默认20日
def get_growth_rate(security, n=20):
    lc = get_close_price(security, n)
    c = get_close_price(security, 1, '1m')
    
    if not isnan(lc) and not isnan(c) and lc != 0:
        return (c - lc) / lc
    else:
        log.error("数据非法, security: %s, %d日收盘价: %f, 当前价: %f" %(security, n, lc, c))
        return 0
        
def get_growth_rate60(security):
    price60d = attribute_history(security, 60, '1d', 'close', False)['close'][0]
    pricenow = get_close_price(security, 1, '1m')
    if not isnan(pricenow) and not isnan(price60d) and price60d != 0:
        return pricenow / price60d
    else:
        return 100

# 过滤涨停的股票
def filter_limitup_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    
    # 已存在于持仓的股票即使涨停也不过滤，避免此股票再次可买，但因被过滤而导致选择别的股票
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys() 
        or last_prices[stock][-1] < current_data[stock].high_limit]

# 获取前n个单位时间当时的收盘价
def get_close_price(security, n, unit='1d'):
    return attribute_history(security, n, unit, 'close')['close'][0]

# 平仓，卖出指定持仓
def close_position(security):
    order = order_target_value(security, 0) # 可能会因停牌或跌停失败
    if order != None and order.status == OrderStatus.held:
        g.sold_stock[security] = 0

# 清空卖出所有持仓
def clear_position(context):
    if context.portfolio.positions:
        log.info("==> 清仓，卖出所有股票")
        for stock in context.portfolio.positions.keys():
            close_position(stock)

# 过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]

# 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list 
        if not current_data[stock].is_st 
        and 'ST' not in current_data[stock].name 
        and '*' not in current_data[stock].name 
        and '退' not in current_data[stock].name]
        
# 过滤创业版股票
def filter_gem_stock(context, stock_list):
    return [stock for stock in stock_list if stock[0:3] != '300']

# 过滤次新股
def filter_new_stock(context, stock_list):
    return [stock for stock in stock_list if (context.previous_date - datetime.timedelta(days=g.tradeday)) > get_security_info(stock).start_date]

# 过滤昨日涨幅过高的股票
def filter_increase1d(stock_list):
    return [stock for stock in stock_list if get_close_price(stock, 1) / get_close_price(stock, 2) < (1 + g.increase1d)]

# 过滤卖出不足buyagain日的股票
def filter_buyagain(stock_list):
    return [stock for stock in stock_list if stock not in g.sold_stock.keys()]

def get_stock_list(context):
    df = get_fundamentals(query(valuation.code).filter(valuation.pb_ratio.between(g.pbmin, g.pbmax)
        ).order_by(valuation.circulating_market_cap.asc()).limit(1000)).dropna()
    stock_list = list(df['code'])
    
    # 过滤创业板、ST、停牌、当日涨停、次新股、昨日涨幅过高
    stock_list = filter_gem_stock(context, stock_list)
    stock_list = filter_st_stock(stock_list)
    stock_list = filter_paused_stock(stock_list)
    stock_list = filter_limitup_stock(context, stock_list)
    stock_list = filter_new_stock(context, stock_list)
    stock_list = filter_increase1d(stock_list)
    stock_list = filter_buyagain(stock_list)
    return stock_list

def get_stock_rank_m_m(stock_list):
    rank_stock_list = get_fundamentals(query(
        valuation.code, valuation.market_cap, valuation.circulating_market_cap
        ).filter(valuation.code.in_(stock_list)
        ).order_by(valuation.circulating_market_cap.asc()).limit(100))
    volume5d = [attribute_history(stock, 1200, '1m', 'volume', df=False)['volume'].sum() for stock in rank_stock_list['code']]
    increase60d = [get_growth_rate60(stock) for stock in rank_stock_list['code']]
    current_price = [get_close_price(stock, 1, '1m') for stock in rank_stock_list['code']]

    min_price = min(current_price)
    min_increase60d = min(increase60d)
    min_circulating_market_cap = min(rank_stock_list['circulating_market_cap'])
    min_market_cap = min(rank_stock_list['market_cap'])
    min_volume = min(volume5d)

    totalcount = [[i, math.log(min_volume / volume5d[i]) * g.weights[3] + math.log(min_price / current_price[i]) * g.weights[2] + math.log(min_circulating_market_cap / rank_stock_list['circulating_market_cap'][i]) * g.weights[1] + math.log(min_market_cap / rank_stock_list['market_cap'][i]) * g.weights[0] + math.log(min_increase60d / increase60d[i]) * g.weights[4]] for i in rank_stock_list.index]
    totalcount.sort(key=lambda x:x[1])
    return [rank_stock_list['code'][totalcount[-1-i][0]] for i in range(min(g.sellrank, len(rank_stock_list)))]

# 调仓策略：控制在设置的仓位比例附近，如果过多或过少则调整
# 熊市时按设置的总仓位比例控制
def my_adjust_position(context, hold_stocks):
    if g.choose_time_signal and (not g.isbull):
        free_value = context.portfolio.total_value * g.bearpercent
        maxpercent = 1.3 / g.stocknum * g.bearpercent
    else:
        free_value = context.portfolio.total_value
        maxpercent = 1.3 / g.stocknum
    buycash = free_value / g.stocknum

    for stock in context.portfolio.positions.keys():
        current_data = get_current_data()
        price1d = get_close_price(stock, 1)
        nosell_1 = context.portfolio.positions[stock].price >= current_data[stock].high_limit
        sell_2 = stock not in hold_stocks
        if sell_2 and not nosell_1:
            close_position(stock)
        else:
            current_percent = context.portfolio.positions[stock].value / context.portfolio.total_value
            if current_percent > maxpercent:order_target_value(stock, buycash)

def mybuy(context):
    if not g.nohold:
        # 避免卖出的股票马上买入
        hold_stocks = filter_buyagain(g.chosen_stock_list)
        log.info("待买股票列表：%s" %(hold_stocks))
        if g.choose_time_signal and (not g.isbull):
            free_value = context.portfolio.total_value * g.bearpercent
            minpercent = 0.7 / g.stocknum * g.bearpercent
        else:
            free_value = context.portfolio.total_value
            minpercent = 0.7 / g.stocknum
        buycash = free_value / g.stocknum
    
        for i in range(min(g.buyrank, len(hold_stocks))):
            free_cash = free_value - context.portfolio.positions_value
            if hold_stocks[i] not in get_blacklist() and free_cash > context.portfolio.total_value / (g.stocknum * 10): # 黑名单里的股票不买
                if hold_stocks[i] in context.portfolio.positions.keys():
                    log.info("已经持有股票：[%s]" %(hold_stocks[i]))
                    current_percent = context.portfolio.positions[hold_stocks[i]].value / context.portfolio.total_value
                    if  current_percent >= minpercent:continue
                    tobuy = min(free_cash, buycash - context.portfolio.positions[hold_stocks[i]].value)
                else:
                    tobuy = min(buycash, free_cash)
                order_value(hold_stocks[i], tobuy)

def get_bull_bear_signal_minute():
    nowindex = get_close_price(g.MA[0], 1, '1m')
    MAold = (attribute_history(g.MA[0], g.MA[1] - 1, '1d', 'close', True)['close'].sum() + nowindex) / g.MA[1]
    if g.isbull:
        if nowindex * (1 + g.threshold) <= MAold:
            g.isbull = False
    else:
        if nowindex > MAold * (1 + g.threshold):
            g.isbull = True

def before_trading_start(context):
    for stock in g.sold_stock.keys():
        if g.sold_stock[stock] >= g.buyagain - 1:
            del g.sold_stock[stock]
        else:
            g.sold_stock[stock] += 1
    g.chosen_stock_list = get_stock_list(context)

def myscheduler():
    set_param()
    unschedule_all()
    run_daily(gogogo, '14:50')
    run_daily(mybuy, '14:55')
    
def after_code_changed(context):
    myscheduler()

def initialize(context):
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    myscheduler()
    g.isbull = False # 是否牛市
    g.chosen_stock_list = [] # 存储选出来的股票
    g.nohold = True # 空仓专用信号
    g.sold_stock = {} # 近期卖出的股票及卖出天数

def gogogo(context):
    get_bull_bear_signal_minute()
    if g.isbull:
        log.info("当前市场判断为：牛市")
    else:
        log.info("当前市场判断为：熊市")
    if g.choose_time_signal and (not g.isbull) and (not g.bearposition) or len(g.chosen_stock_list) < 10:
        clear_position(context)
        g.nohold = True
    else:
        g.chosen_stock_list = get_stock_rank_m_m(g.chosen_stock_list)
        log.info(g.chosen_stock_list)
        my_adjust_position(context, g.chosen_stock_list)
        g.nohold = False
