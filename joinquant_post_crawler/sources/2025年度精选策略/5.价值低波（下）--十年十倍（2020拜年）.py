# 克隆自聚宽文章：https://www.joinquant.com/post/25183
# 标题：价值低波（下）--十年十倍（2020拜年）
# 作者：Gyro

# author:liaojhchina
# date:20220225
# 1）P/E在A股是很有效的。强调一点，既然用了市盈率，ROE要基本达标，10%，另外，PE< 20，反过来则是收益率E/P>5％，5%也是基本要求。
# 2）低波部分更简单，波动率加权。
# 3）战术级风控，账户市值下跌10％，则降低股票占比50%，剩下的空间由国债填。还可以更细致一些，回撤5%、15%、20%等等，资金曲线回撤是最管用的。
# 4）战略级风控，只在指数（沪深300）多头的时候买股，空头只卖不买。

# 导入函数库
import datetime
import numpy as np
import pandas as pd
import time
from jqdata import *
from pandas import Series, DataFrame

'''
================================================================================
总体回测前
================================================================================
'''

# 初始化函数，设定基准等等
def initialize(context):
    #设置策参数
    set_params()  
    # 设置中间变量
    set_variables() 
    # 设置回测条件
    set_backtest()
    # 运行函数
    # 开盘前运行
    run_daily(before_market_open, time='09:00', reference_security='000300.XSHG') 
    # 开盘时运行
    run_daily(market_open, time='09:30', reference_security='000300.XSHG')
    # 收盘后运行
    run_daily(after_market_close, time='15:30', reference_security='000300.XSHG')
    # 市值峰值
    g.inv_value_max = context.portfolio.total_value

def set_params():
    # 投资组合
    g.weight = pd.Series()
    # 沪深300
    g.index = '000300.XSHG'
    # 国债指数
    g.treasury = '000012.XSHG'
    # 最大持股数量
    g.stocks_num = 10
    
'''
000001.XSHG
上证指数
1991-07-15
SZZS
全部上市A股和B股
000002.XSHG
A股指数
1992-02-21
AGZS
全部上证A股
000003.XSHG
B股指数
1992-08-17
BGZS
全部上市B股
'''

def set_variables():
    pass

def set_backtest():
    # 设定基准
    set_benchmark('000300.XSHG')
    # 避免未来数据模式
    set_option('avoid_future_data', True)
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')
    # 关闭系统日志因positions不存在产生的日志
    log.set_level('system', 'error')
    # 调用history系列API(history/attribute_history/get_price)产生的log
    log.set_level('history', 'error')

'''
================================================================================
每天开盘前
================================================================================
'''
def before_market_open(context):
    set_slip_fee(context)
    # 获取高价值股票
    stocks = high_value(context, g.index, g.stocks_num)
    # 波动率加权,241天差不多就是股票一年交易的天数
    g.weight = volatility_weight(stocks, 241)
    # 风险控制
    risk_controller(context)
    
# 获取高价值可投资股票基本信息
def high_value(context, index, stocks_num):
    stocks = get_index_stocks(index)
    df = get_fundamentals(query(
            valuation.code,
            valuation.pb_ratio,
            valuation.pe_ratio
        ).filter(
            valuation.code.in_(stocks),
            valuation.pb_ratio > 0,
            valuation.pe_ratio > 0,
            valuation.pe_ratio < 20,
            valuation.pb_ratio / valuation.pe_ratio > 0.1,
        ).order_by(
            valuation.pe_ratio.asc()
        ).limit(stocks_num)
        ).dropna()
    return list(df.code)
    
# 波动率加权
def volatility_weight(stocks, days):
    # 历史数据
    h = history(days, '1d', 'close', stocks, df = True)
    # 第一天没有涨跌幅过滤
    r = h.pct_change()[1:]
    # 波动率加权
    w = 1.0 / r.std()
    weight = w / w.sum()
    return weight
    
# 风险控制
def risk_controller(context):
    # 风险控制
    inv_stock = True
    h = history(61, '1d', 'close', [g.index], df = True)
    p = h[g.index]
    if p[-1] < p.mean():
        # 指数空头，停止买进
        inv_stock = False
    # 风险控制-回撤
    inv_stock_ratio = 1.0
    # 账户市值下跌10％，则降低股票占比50%
    if context.portfolio.total_value < 0.9 * g.inv_value_max:
        inv_stock_ratio = 0.5
    # 调整投资组合
    weight = pd.Series()
    for stock in g.weight.index:
        if inv_stock or stock in context.portfolio.positions:
            weight[stock] = inv_stock_ratio * g.weight[stock]
    weight[g.treasury] = 1.0 - weight.sum()
    g.weight = weight.sort_values(ascending = True)

# 过滤停牌、退市、ST股票
# def filter(security_list):  
#     current_data = get_current_data()  
#     security_list = [stock for stock in security_list  
#         if not current_data[stock].paused   
#         and not '退' in current_data[stock].name   
#         and not current_data[stock].is_st]
#     return security_list

# 滑点设置和手续费   
def set_slip_fee(context):
    # 将滑点设置为0.02,上下浮动0.01
    set_slippage(FixedSlippage(0.02))
    # 根据不同的时间段设置手续费
    dt = context.current_dt
    
    # 根据不同时间设计手续费
    if dt > datetime.datetime(2013,1,1):
        set_order_cost(OrderCost(
            open_tax=0.0003, close_tax=0.0013, open_commission=0, 
            close_commission=0, close_today_commission=0, 
            min_commission=5), type='stock')
    elif dt > datetime.datetime(2011,1,1):
        set_order_cost(OrderCost(
            open_tax=0.001, close_tax=0.002, open_commission=0, 
            close_commission=0, close_today_commission=0, 
            min_commission=5), type='stock')
    elif dt > datetime.datetime(2009,1,1):
        set_order_cost(OrderCost(
            open_tax=0.002, close_tax=0.003, open_commission=0, 
            close_commission=0, close_today_commission=0, 
            min_commission=5), type='stock')
    else:
        set_order_cost(OrderCost(
            open_tax=0.003, close_tax=0.004, open_commission=0, 
            close_commission=0, close_today_commission=0, 
            min_commission=5), type='stock')
            

'''
================================================================================
每天交易时
================================================================================
'''
def market_open(context):
    cur_data = get_current_data()
    # 卖出空出资金
    for stock in context.portfolio.positions:
        # 不在投资组合且未停牌
        if stock not in g.weight.index and \
            not cur_data[stock].paused:
            order_target(stock, 0)
    # 买入
    for stock in g.weight.index:
        position = g.weight[stock] * context.portfolio.total_value
        if stock not in context.portfolio.positions:
            delta = position
        else:
            delta = position - context.portfolio.positions[stock].value
        
        if context.portfolio.available_cash > delta and \
            not cur_data[stock].paused:
            order_value(stock, delta)

'''
================================================================================
每天收盘后
================================================================================
'''
def after_market_close(context):
    # 收盘结束用于记录数据
    g.inv_value_max = max(g.inv_value_max, context.portfolio.total_value)
    log.info('after_market_close:',context.current_dt.strftime("%Y-%m-%d"))
        #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+ str(_trade))
    log.info('一天结束')
