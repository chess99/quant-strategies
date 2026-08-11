# 克隆自聚宽文章：https://www.joinquant.com/post/35377
# 标题：【超跌反弹v1.0】3年2.3倍的超跌反弹小牛股
# 作者：_查尔斯葱_

# 标题：连续下跌突破MA55反转
# 作者：查尔斯葱

# 导入聚宽函数库
from jqdata import *
import talib

# 初始化代码
def initialize(context):
    set_option("avoid_future_data", True)
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')
    
    # 中小板股票池
    # g.security_universe_index = '399101.XSHE'
    # 沪深300
    # g.security_universe_index = '000300.XSHG'
    # 股票类交易手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, \
                             open_commission=0.0003, close_commission=0.0003,\
                             close_today_commission=0, min_commission=5), type='stock')
    # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
      # 盘间运行
    run_daily(market_open_buy, time='9:30', reference_security='000300.XSHG')
    run_daily(market_open_sell, time='14:55', reference_security='000300.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')
    g.stock_list = []
    g.buy_stock_num = 5
    
## 开盘前运行函数
def before_market_open(context):
    g.stock_list = get_stocks(context)
    
def get_stocks(context):
    # stocks = get_index_stocks(g.security_universe_index)
    
    stocklist = list(get_all_securities(['stock']).index)
    
    stocklist = filter_st_stock(stocklist)
    stocklist = filter_paused_stock(stocklist)
    stocklist = filter_kcb_stock(context, stocklist)
    stocklist = filter_stock_by_days(context, stocklist, 250)
    
    stocklist = buy_point_filter(context, stocklist)
    
    # 通过ROE倒序排列
    q = query(valuation.code
             ).filter(valuation.code.in_(stocklist),
                    valuation.circulating_market_cap>50, # 流通市值>50
                    indicator.roe>0
             ).order_by(indicator.roe.desc()
             ).limit(10)
    stocklist = list(get_fundamentals(q).code)
    
    print(f'选出{len(stocklist)}只股票：{stocklist}')
    
    return stocklist

# 买入函数
def market_open_buy(context):
    if len(context.portfolio.positions) < g.buy_stock_num:
        new_buy_stock_num = g.buy_stock_num - len(context.portfolio.positions)
        buy_cash = context.portfolio.available_cash / new_buy_stock_num
        for s in g.stock_list[:new_buy_stock_num]:
            if s not in context.portfolio.positions and\
                context.portfolio.available_cash >= buy_cash >= 100 * get_current_data()[s].last_price:
                order_target_value(s, buy_cash)
                print(f'买入股票：{s}')
                send_message(f'买入股票：{s}')

# 卖出函数
def market_open_sell(context):
    sells = list(context.portfolio.positions)
    for s in sells:
        loss = context.portfolio.positions[s].price / context.portfolio.positions[s].avg_cost
        s_sell, sell_msg = check_sell_point(context, s)
        if s_sell or loss < 0.95:
            if context.portfolio.positions[s].closeable_amount>0:
                order_target_value(s, 0)
                print(f'卖出股票：{s}, sell_msg={sell_msg}')
                send_message(f'卖出股票：{s}, sell_msg={sell_msg}')

def buy_point_filter(context, stocks):
    final_stocks = []
    for stock in stocks:
        s_buy = check_buy_point(context, stock)
        if s_buy == True:
            final_stocks.append(stock)
    
    return final_stocks
    
def check_buy_point(context, stock):
    s_buy = False
    close_data = attribute_history(stock, 120, '1d', ['close', 'high'])
    
    closes = close_data['close'].values
    
    # 取得过去五天的平均价格
    ma55_list = list(np.zeros(120))
    for i in range(54, 120):
        ma55_list[i] = closes[i-54:i+1].mean()
    
    # 近40天内，共有<5天大于ma55，且近3天有大于ma55的
    over_55_in_40_days = np.array(closes[-40:]) > np.array(ma55_list[-40:])
    
    num_over_55_40_days = sum(over_55_in_40_days)
    ever_upcross_ma55 = sum(over_55_in_40_days[:20])
    nowadays_upcross_ma55 = sum(over_55_in_40_days[-3:])
    yesterday_over_ma55 = over_55_in_40_days[-1]
    
    current_price = get_current_data()[stock].last_price
    current_ma55 = (np.sum(closes[-54:]) + current_price)/55
    
    now_over_ma55 = current_price > current_ma55
    
    ten_days_lowest = min(closes[-10:]) == min(closes[-60:])
    
    # if '002425' in stock:
    #     print(f'stock={stock}')
    #     print(f'current_price={current_price}')
    #     print(f'current_ma55={current_ma55}')
    #     print(f'ever_upcross_ma55={ever_upcross_ma55}')
    #     print(f'nowadays_upcross_ma55={nowadays_upcross_ma55}')
    #     print(f'yesterday_over_ma55={yesterday_over_ma55}')
    #     print(f'now_over_ma55={now_over_ma55}')
    
    if 1 <= ever_upcross_ma55 <= 3 and\
        nowadays_upcross_ma55 >= 1 and\
        now_over_ma55 and\
        ten_days_lowest:
        s_buy = True
    
    return s_buy

def check_sell_point(context, stock):
    s_sell = False
    
    #持仓股票的当前价
    current_price = get_current_data()[stock].last_price
    # == context.portfolio.positions[stock].price 
    # 按天交易，【尾盘】跌破MA5或日内高点回撤5个点即撤
    bars = get_bars(stock, 60, '1d', ['high', 'close'], include_now=True)
    closes = bars['close']
    highs = bars['high']
    
    closes[-1] = current_price
    # ma3 & ma5
    ma3 = closes[-3:].mean()
    ma5 = closes[-5:].mean()
    ma55 = closes[-55:].mean()
    ma55_ = closes[-56:-1].mean()
    
    loss = current_price / context.portfolio.positions[stock].avg_cost
    
    high_allday = highs[-1]
    # 跌破MA5 / 下跌3% / 高点回撤3% / 成本损失5%
    signal1 = 0
    signal2 = current_price / closes[-2] < 0.95
    signal3 = current_price / high_allday < 0.95
    signal4 = loss < 0.95
    signal5 = current_price < ma55 * 0.98
    if signal1 or signal2 or signal3 or signal4 or signal5:
        s_sell = True
    msg = []
    if signal1:
        msg.append('跌破MA5')
    if signal2:
        msg.append('下跌5%')
    if signal3:
        msg.append('高点回撤5%')
    if signal4:
        msg.append('总亏损5%')
    if signal5:
        msg.append('跌破MA55')
    
    return s_sell, msg

## 收盘后运行函数
def after_market_close(context):
    log.info('现持有：{}；帐户收益：{}%'.format(list(context.portfolio.positions),round(100*context.portfolio.returns,1)))
    log.info('---------------------------------------------------------------------')
			
##过滤上市时间不满1080天的股票
def filter_stock_by_days(context, stock_list, days):
    tmpList = []
    for stock in stock_list :
        days_public=(context.current_dt.date() - get_security_info(stock).start_date).days
        if days_public > days:
            tmpList.append(stock)
    return tmpList

def filter_paused_stock(stock_list):
	current_data = get_current_data()
	return [stock for stock in stock_list if not current_data[stock].paused]

def filter_st_stock(stock_list):
	current_data = get_current_data()
	return [stock for stock in stock_list
			if not current_data[stock].is_st
			and 'ST' not in current_data[stock].name
			and '*' not in current_data[stock].name
			and '退' not in current_data[stock].name]

# 过滤科创板
def filter_kcb_stock(context, stock_list):
    return [stock for stock in stock_list if stock[0:3] != '688']
