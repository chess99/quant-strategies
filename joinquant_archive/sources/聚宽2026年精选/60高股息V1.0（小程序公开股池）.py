# 克隆自聚宽文章：https://www.joinquant.com/post/48151
# 标题：高股息V1.0（小程序公开股池）
# 作者：MarioC

from jqdata import *
from jqfactor import *
import numpy as np
import pandas as pd
import pickle
import talib
import warnings
import pandas as pd
from jqdata import *
from jqlib.technical_analysis import *

warnings.filterwarnings("ignore")
# 初始化函数
def initialize(context):
    # 设定基准
    set_benchmark('000985.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0.02))
    # 设置交易成本万分之三，不同滑点影响可在归因分析中查看
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    # 初始化全局变量
    g.no_trading_today_signal = False
    g.stock_num = 5
    g.hold_list = []  # 当前持仓的全部股票
    g.yesterday_HL_list = []  # 记录持仓中昨日涨停的股票
    # 设置交易运行时间
    run_daily(prepare_stock_list, '9:05')

    run_monthly(weekly_adjustment, 1, '9:30')

    run_daily(check_limit_up, '14:00')  # 检查持仓中的涨停股是否需要卖出
    run_daily(close_account, '14:30')

def Stop_Loss(context):
    for stock in context.portfolio.positions.keys():
        order_target_value(stock, 0)
        
def sell_stocks(context):
    for stock in context.portfolio.positions.keys():
        # 股票盈利大于等于10%则卖出
        if context.portfolio.positions[stock].price >= context.portfolio.positions[stock].avg_cost * 1.40:
            order_target_value(stock, 0)
            log.debug("Selling out %s" % (stock))
        # 股票亏损大于等于-5%则卖出
        elif context.portfolio.positions[stock].price < context.portfolio.positions[stock].avg_cost * 0.97:
            order_target_value(stock, 0)
            log.debug("Selling out %s" % (stock))


def filter_roic(context,stock_list):
    yesterday = context.previous_date
    list=[]
    for stock in stock_list:
        roic=get_factor_values(stock, 'roic_ttm', end_date=yesterday,count=1)['roic_ttm'].iloc[0,0]
        if roic>0.08:
            list.append(stock)
            
    return list
    
# 1-1 准备股票池
def prepare_stock_list(context):
    # 获取已持有列表
    g.hold_list = []
    for position in list(context.portfolio.positions.values()):
        stock = position.security
        g.hold_list.append(stock)
    # 获取昨日涨停列表
    if g.hold_list != []:
        df = get_price(g.hold_list, end_date=context.previous_date, frequency='daily', fields=['close', 'high_limit'],
                       count=1, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        g.yesterday_HL_list = list(df.code)
    else:
        g.yesterday_HL_list = []

def get_dividend_ratio_filter_list(context, stock_list, sort, p1, p2):
    time1 = context.previous_date
    time0 = time1 - datetime.timedelta(days=365*3)#最近3年分红
    #获取分红数据，由于finance.run_query最多返回4000行，以防未来数据超限，最好把stock_list拆分后查询再组合
    interval = 1000 #某只股票可能一年内多次分红，导致其所占行数大于1，所以interval不要取满4000
    list_len = len(stock_list)
    #截取不超过interval的列表并查询
    q = query(finance.STK_XR_XD.code, finance.STK_XR_XD.a_registration_date, finance.STK_XR_XD.bonus_amount_rmb
    ).filter(
        finance.STK_XR_XD.a_registration_date >= time0,
        finance.STK_XR_XD.a_registration_date <= time1,
        finance.STK_XR_XD.code.in_(stock_list[:min(list_len, interval)]))
    df = finance.run_query(q)
    #对interval的部分分别查询并拼接
    if list_len > interval:
        df_num = list_len // interval
        for i in range(df_num):
            q = query(finance.STK_XR_XD.code, finance.STK_XR_XD.a_registration_date,  finance.STK_XR_XD.bonus_amount_rmb
            ).filter(
                finance.STK_XR_XD.a_registration_date >= time0,
                finance.STK_XR_XD.a_registration_date <= time1,
                finance.STK_XR_XD.code.in_(stock_list[interval*(i+1):min(list_len,interval*(i+2))]))
            temp_df = finance.run_query(q)
            df = df.append(temp_df)
    dividend = df.fillna(0)#df.fillna() 是一个 Pandas 数据处理库中的函数，它可以用来填充数据框中的空值
    dividend = dividend.groupby('code').sum()
    temp_list = list(dividend.index) #query查询不到无分红信息的股票，所以temp_list长度会小于stock_list
    # #获取市值相关数据
    q = query(valuation.code,valuation.market_cap).filter(valuation.code.in_(temp_list))
    cap = get_fundamentals(q, date=time1)
    cap = cap.set_index('code')
    # #计算股息率
    cap['dividend_ratio']=(dividend['bonus_amount_rmb']/10000)/cap['market_cap']
    # #排序并筛选
    cap = cap.sort_values(by=['dividend_ratio'], ascending=sort)
    final_list = list(cap.index)[int(p1*len(cap)):int(p2*len(cap))]
    print("近3年累计分红率排名前{0:.2%}的股有{1}只".format(p2,len(final_list)))
    return final_list

    
def choice_try_A(context,stocks):
    stocks = get_dividend_ratio_filter_list(context, stocks, False, 0, 0.2)    #股息率排序

    stocks = filter_roic(context,stocks)
    
    yesterday = context.previous_date
    # df = get_factor_values(stocks, 'roic_ttm', end_date=yesterday, count=1)['roic_ttm']
    df = get_factor_values(stocks, 'accounts_payable_turnover_days', end_date=yesterday, count=1)['accounts_payable_turnover_days']
    stocks = df.iloc[0].nlargest(g.stock_num).index.tolist()

    print("分红比率筛选后的股票有：{}".format(len(stocks)))

    return stocks

# 1-2 选股模块
def get_stock_list(context):
    # 指定日期防止未来数据
    yesterday = context.previous_date
    today = context.current_dt
    initial_list = get_all_securities('stock', today).index.tolist()
    # initial_list = get_stock(yesterday)
    stocks = filter_kcbj_stock(initial_list)
    choice = filter_st_stock(stocks)
    choice = filter_paused_stock(choice)
    choice = filter_new_stock(context, choice)
    choice = filter_limitup_stock(context,choice)
    initial_list = filter_limitdown_stock(context,choice)
    stocks = choice_try_A(context,initial_list)

    return stocks
# 1-3 整体调整持仓
def weekly_adjustment(context):
    if g.no_trading_today_signal == False:
        # 获取应买入列表
        target_list = get_stock_list(context)
        # 调仓卖出
        for stock in g.hold_list:
            if (stock not in target_list) and (stock not in g.yesterday_HL_list):
                log.info("卖出[%s]" % (stock))
                position = context.portfolio.positions[stock]
                close_position(position)
            else:
                log.info("已持有[%s]" % (stock))
        # 调仓买入
        position_count = len(context.portfolio.positions)
        print(position_count)
        target_num = len(target_list)
        print(target_num)
        if target_num > position_count:
            print(context.portfolio.cash)
            
            value = context.portfolio.cash / (target_num - position_count)
            for stock in target_list:
                if context.portfolio.positions[stock].total_amount == 0:
                    if open_position(stock, value):
                        if len(context.portfolio.positions) == target_num:
                            break



# 1-4 调整昨日涨停股票
def check_limit_up(context):
    now_time = context.current_dt
    if g.yesterday_HL_list != []:
        # 对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
        for stock in g.yesterday_HL_list:
            current_data = get_price(stock, end_date=now_time, frequency='1m', fields=['close', 'high_limit'],
                                     skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True)
            if current_data.iloc[0, 0] < current_data.iloc[0, 1]:
                log.info("[%s]涨停打开，卖出" % (stock))
                position = context.portfolio.positions[stock]
                close_position(position)
            else:
                log.info("[%s]涨停，继续持有" % (stock))

# 3-1 交易模块-自定义下单
def order_target_value_(security, value):
    if value == 0:
        log.debug("Selling out %s" % (security))
    else:
        log.debug("Order %s to value %f" % (security, value))
    return order_target_value(security, value)


# 3-2 交易模块-开仓
def open_position(security, value):
    order = order_target_value_(security, value)
    if order != None and order.filled > 0:
        return True
    return False


# 3-3 交易模块-平仓
def close_position(position):
    security = position.security
    order = order_target_value_(security, 0)  # 可能会因停牌失败
    if order != None:
        if order.status == OrderStatus.held and order.filled == order.amount:
            return True
    return False


# 4-2 清仓后次日资金可转
def close_account(context):
    if g.no_trading_today_signal == True:
        if len(g.hold_list) != 0:
            for stock in g.hold_list:
                position = context.portfolio.positions[stock]
                close_position(position)
                log.info("卖出[%s]" % (stock))

# 2-1 过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]


# 2-2 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list
            if not current_data[stock].is_st
            and 'ST' not in current_data[stock].name
            and '*' not in current_data[stock].name
            and '退' not in current_data[stock].name]


# 2-3 过滤科创北交股票
def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68' or stock[0] == '3':
            stock_list.remove(stock)
    return stock_list


# 2-4 过滤涨停的股票
def filter_limitup_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] < current_data[stock].high_limit]


# 2-5 过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] > current_data[stock].low_limit]


# 2-6 过滤次新股
def filter_new_stock(context, stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if
            not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=375)]


