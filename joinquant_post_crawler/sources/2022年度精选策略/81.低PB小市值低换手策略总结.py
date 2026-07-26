# 克隆自聚宽文章：https://www.joinquant.com/post/35317
# 标题：低PB小市值低换手策略总结
# 作者：QuantYY

from jqdata import *
import pandas as pd
import numpy as np
import statsmodels.api as sm

def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 检查未来数据， 编译时间会长很多
    #set_option('avoid_future_data',True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003,
                             close_commission=0.0003, min_commission=5), type='stock')
    # 初始化各类全局变量
    initial_config()
    
    # 设置交易时间，每月执行一次
    run_monthly(trade, monthday=1, time='09:30', reference_security='000300.XSHG')


def initial_config():
    log.set_level('order', 'error')

def trade(context):
    stocks = get_stock_pool(context)
    sell_all(context)
    buy_stocks(context, stocks)


def buy_stocks(context, stocks):
    cash = context.portfolio.available_cash
    stock_num = len(stocks)
    for stock in stocks:
        order_target_value(stock, 1 / stock_num * cash)


def sell_all(context):
    stock_hold = set(context.portfolio.positions.keys())
    for stock in stock_hold:
        order_target_value(stock, 0)

#####################################################################################

# 过滤 ST,停牌，开盘涨停的股票
def can_buy(day, stock):
    ext = get_extras('is_st', [stock], start_date=day, end_date=day, df=False)
    #if ext[stock][0] is True :
    if ext[stock][0] == True :
        return False
        
    data = get_price(stock, start_date=day, end_date=day, frequency='daily', fields=['open', 'high_limit', 'paused'], skip_paused=False, fq='pre', count=None, panel=True, fill_paused=False)
    if data is None or len(data) == 0 or data['paused'][0] == 1:
        return False

    return data['open'][0] < data['high_limit'][0]


# 封装选股条件
def filter(conditions, today, data, result=[]) :
    cond0_data = data.sort_values(by=conditions[0]['by'], ascending=conditions[0]['asc'])
    cond1_data = cond0_data[:conditions[0]['count']].sort_values(by=conditions[1]['by'], ascending=conditions[1]['asc'])
    code_list = cond1_data[:conditions[1]['count']].code.tolist()
    
    for code in code_list :
        if code in result :
            continue
        
        if can_buy(today, code) :
            result.append(code)


# 获取所需数据
def get_data(context):
    q = query(
        valuation.market_cap,
        valuation.pb_ratio,
        valuation.code,
        valuation.turnover_ratio
      )
    return get_fundamentals(q, date=context.previous_date)
    
    
def get_stock_pool(context):

    data = get_data(context)
    
    result = []
    
    #低PB，低换手
    filter([{'by':'pb_ratio', 'asc':True, 'count':70}, {'by':'turnover_ratio', 'asc':True, 'count':35}], context.current_dt, data, result)
    #小市值，低换手
    filter([{'by':'market_cap', 'asc':True, 'count':70}, {'by':'turnover_ratio', 'asc':True, 'count':35}], context.current_dt, data, result)

    return result
