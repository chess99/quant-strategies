# 克隆自聚宽文章：https://www.joinquant.com/post/31496
# 标题：跟着基金报团！！！174%  回撤  7.33%
# 作者：仓又加错了啊

from jqdata import *
import random
import pandas as pd
import numpy as np
import datetime as dt
from jqlib.technical_analysis import *
import requests
import re
import time
import talib
import math
import requests
import statsmodels.api as sm



# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
#   开盘前运行
    run_monthly(before_market_open, 1,time='before_open', reference_security='000300.XSHG')
#   开盘时运行
    run_daily(market_open, time='open', reference_security='000300.XSHG')
#   收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')
    g.stocknum=10
    g.N = 18
    #统计样本长度
    g.M = 480 ##600 1100
    # 买入阈值
    g.buy = 0.70     ##1.0  1.1  0.95  0.95  0.8      0.8
    g.sell = -0.70   ##-0.6 -0.6 -0.6  -0.55  -0.8    -0.6
                    ##19    15   19     16    15      16
    #用于记录回归后的beta值，即斜率
    g.ans = []
    #用于计算被决定系数加权修正后的贝塔值
    g.ans_rightdev= []
    run_daily(market_openrss, time='9:00', reference_security='000300.XSHG')
    g.signalrss=0
    ##止损
    #run_weekly(stop_loss,3,time='open', reference_security='000300.XSHG')

#----------------------------------------------------------------------------
def market_openrss(context):
    # 填入各个日期的RSRS斜率值
    beta=0
    r2=0
    
    #RSRS斜率指标定义
    prices = attribute_history('000300.XSHG', g.N, '1d', ['high', 'low'])
    highs = prices.high
    lows = prices.low
    X = sm.add_constant(lows)
    model = sm.OLS(highs, X)
    beta = model.fit().params[1]
    g.ans.append(beta)
    #计算r2
    r2=model.fit().rsquared
    g.ans_rightdev.append(r2)
    
    # 计算标准化的RSRS指标
    # 计算均值序列    
    section = g.ans[-g.M:]
    # 计算均值序列
    mu = np.mean(section)
    # 计算标准化RSRS指标序列
    sigma = np.std(section)
    zscore = (section[-1]-mu)/sigma  
    #计算右偏RSRS标准分
    zscore_rightdev= zscore*beta*r2
    
    # 如果上一时间点的RSRS斜率大于买入阈值, 则全仓买入
    record(zs=zscore_rightdev,by=g.buy,sl=g.sell)
    
    #log.info(zscore_rightdev)
    current_data = get_current_data()
    if zscore_rightdev > g.buy:
        # 记录这次买入
        log.info("市场风险在合理范围")
        #满足条件运行交易
        g.signalrss=1    # 如果上一时间点的RSRS斜率小于卖出阈值, 则空仓卖出
    elif zscore_rightdev < g.sell:
        g.signalrss=0
        log.info("市场有风险")
        


    
## 开盘前运行函数
def before_market_open(context):
    g.north=0
    # 输出运行时间
    # log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    time = datetime.datetime.strftime(context.current_dt, "%Y%m%d")
    year = time[:4]
    trade_day_1 = get_trade_days(end_date=year + '0131', count=1)[0]
    trade_day_1 = datetime.datetime.strftime(trade_day_1, "%Y%m%d")
    trade_day_2 = get_trade_days(end_date=year + '0430', count=1)[0]
    trade_day_2 = datetime.datetime.strftime(trade_day_2, "%Y%m%d")
    trade_day_3 = get_trade_days(end_date=year + '0731', count=1)[0]
    trade_day_3 = datetime.datetime.strftime(trade_day_3, "%Y%m%d")
    trade_day_4 = get_trade_days(end_date=year + '1031', count=1)[0]
    trade_day_4 = datetime.datetime.strftime(trade_day_4, "%Y%m%d")
    g.trade_day_list = [trade_day_1, trade_day_2, trade_day_3, trade_day_4]
    g.judge_date = datetime.datetime.strftime(context.current_dt, "%Y%m%d")

 
    today_date = context.current_dt
    # 给微信发送消息（添加模拟交易，并绑定微信生效）
    # send_message('美好的一天~')
    dt_end = today_date
    dt_start = today_date - datetime.timedelta(180)
    today = context.current_dt
    
    index = '000300.XSHG'
    stocks = get_index_stocks(index)


    fportfolio = pd.Series()
    for s in stocks:
        code = s[:6]
        df = finance.run_query(query(
            finance.FUND_PORTFOLIO_STOCK
            ).filter(
            finance.FUND_PORTFOLIO_STOCK.symbol==code,
            finance.FUND_PORTFOLIO_STOCK.pub_date > dt_start,
            finance.FUND_PORTFOLIO_STOCK.pub_date <=context.previous_date,
            ))
        total_value = 1e-8*df.market_cap.sum()
        fportfolio[s] = total_value   
    fweight = 100 * fportfolio / fportfolio.sum()
    index_weight = get_index_weights(index, dt_end)

    fdelta = pd.Series()
    for s in index_weight.index:
        if s in fweight.index:
            fdelta[s] = d = fweight[s] - index_weight.weight[s]
    print(fdelta)


    fdelta.sort('delta',ascending=False)
    print(fdelta)
    the_best_list = fdelta.index.tolist()

    g.buy_list = the_best_list[:g.stocknum]
    print(g.buy_list)

## 开盘时运行函数
def market_open(context):
    days = get_trade_days(end_date=context.current_dt.date(), count=5)
    yesterday = days[-2]
    before_yesterday = days[-3]
    # log.info('函数运行时间(market_open):'+str(context.current_dt.time()))

    security_all = g.buy_list    


        
    
    final = list(security_all)
    need_buy=[]
    need_sell=[]
    need_buyok=[]
    current_hold_funds_set = set(context.portfolio.positions.keys())
    if set(final) != current_hold_funds_set:
        need_buy= set(final).difference(current_hold_funds_set)
        need_sell= current_hold_funds_set.difference(final)
        for fund in need_sell:
            if fund != '511880.XSHG':
                order_target(fund, 0)
    if len(need_buy)>0 and  g.signalrss  ==1:
        order_target_value('511880.XSHG',0)    
        cash_per_fund=context.portfolio.available_cash/len(need_buy)
        for fund in need_buy:
            order_target_value(fund,cash_per_fund)

    if g.signalrss == 0:
        for s in context.portfolio.positions.keys():
            order_target(s, 0)        
        order_value('511880.XSHG',1000000)                
              


## 收盘后运行函数
def after_market_close(context):
    # log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    if g.judge_date not in g.trade_day_list:
        return
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    log.info('一天结束')
    log.info('##############################################################')







