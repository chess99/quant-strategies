# 克隆自聚宽文章：https://www.joinquant.com/post/29336
# 标题：大盘一路向上时，追总龙头2个月3倍
# 作者：叶松

import csv
import os
import xlrd
import math
import jqdata
import numpy as np 
import pandas as pd
from six import BytesIO
from jqlib.alpha101 import *
from pandas import DataFrame,Series

# 初始化程序, 整个回测只运行一次
def initialize(context):
    g.index_security = '000300.XSHG'
    # 设定沪深300作为基准
    set_benchmark(g.index_security)
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')
    before_market_open(context)
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    
    run_monthly(before_market_open,1,time='before_open', reference_security=g.index_security) 

    
 


def before_trading_start(context):
    count = 11
    # 每天买入股票数量
    g.daily_buy_count  = 1
    g.today_bought_stocks = set() 
    
    #--------------取20日涨停价，收盘价，最低价-----------------
    g.high_limit = history(count,'1d','high_limit',g.stocks_exsit)
    g.close = history(count,'1d','close',g.stocks_exsit)
    g.low = history(count,'1d','low',g.stocks_exsit)
    #--------------------------------------------
    g.x1 = history(1,'1d','high_limit',g.stocks_exsit)##用来存今日涨停价，后面会重新赋值
    for security in (g.stocks_exsit):
        stock_data = get_price(security, end_date=context.current_dt.date(), frequency='daily', fields=['high_limit'],skip_paused=False,fq='pre', count=1)
        g.x1[security][0] = stock_data['high_limit'][0]
    #----------------------------------------
    stocks_zt={}
    
    for security in (g.stocks_exsit):
        if(g.close[security][-1] == g.high_limit[security][-1]\
        and g.low[security][-1] < g.high_limit[security][-1]):
            stocks_zt[security] = 1#昨日非一字板涨停
    for security in (stocks_zt):
        for i in range(0,count-1):
            if(g.close[security][count-2-i] == g.high_limit[security][count-2-i]\
            and g.low[security][count-2-i] < g.high_limit[security][count-2-i]):
                stocks_zt[security] += 1#非一字连板天数
            else:
                break
    #涨停最多天数
    g.max_zt_days = 0
    for key in  stocks_zt:
        if(stocks_zt[key] > g.max_zt_days):
            g.max_zt_days = stocks_zt[key]
    
    g.buy_list = []
    for key in  stocks_zt:
        if(stocks_zt[key] == g.max_zt_days):
            g.buy_list.append(key)
    if len(g.buy_list):
        log.info('___'*10)
        log.info('股票池：%d 最高板：%d'%(len(g.buy_list),g.max_zt_days))
        log.info(g.buy_list)
    


# 在每分钟的第一秒运行, data 是上一分钟的切片数据
def handle_data(context, data):
    
    current = get_current_data()
    hour = context.current_dt.hour
    minute = context.current_dt.minute
    
    #------------------处理卖出-------------------
    for security in context.portfolio.positions:
        closeable_amount = context.portfolio.positions[security].closeable_amount
        if (minute>50 and hour==14 and data[security].close<current[security].high_limit) and closeable_amount:#尾盘未涨停
            # 卖出
            order_target(security, 0)
            # 记录这次卖出
            log.info("卖出： %s %s" % (current[security].name,security))
    # 每天只买这么多个
    if len(g.today_bought_stocks) >= g.daily_buy_count:
        return
    #涨停板数量>3
    if not(fit_linear(context,3)>0 and g.max_zt_days>3): 
        return
    if (hour<11 and  len(g.today_bought_stocks) < g.daily_buy_count):#冲天炮龙头
        for security in g.buy_list:
            if((security in context.portfolio.positions)==0):#排除重复买
                # 得到当前资金余额
                cash = context.portfolio.available_cash
        
                # 计算今天还需要买入的股票数量
                need_count = g.daily_buy_count - len(g.today_bought_stocks)
                buy_cash = context.portfolio.available_cash
                if need_count:
                    buy_cash = context.portfolio.available_cash / need_count
                
                if buy_cash>(data[security].close*500):
                    # 买入这么多现金的股票
                    result = order_value(security, buy_cash)
                    if not result==None:
                        g.today_bought_stocks.add(security)
                        log.info("买入： %s %s" % (current[security].name,security))
#直线拟合
def fit_linear(context,count):
    '''
    count:拟合天数
    '''
    from sklearn.linear_model import LinearRegression
    security = '000001.XSHG'
    df = history(count=count, unit='1d', field='close', security_list=security, df=True, skip_paused=False, fq='pre')
    model = LinearRegression()
    x_train = np.arange(0,len(df[security])).reshape(-1,1)
    y_train = df[security].values.reshape(-1,1)
    # print(x_train,y_train)
    
    model.fit(x_train,y_train)
    
    # # 计算出拟合的最小二乘法方程
    # # y = mx + c 
    c = model.intercept_
    m = model.coef_
    c1 = round(float(c),2)
    m1 = round(float(m),2)
    # print("最小二乘法方程 : y = {} + {}x".format(c1,m1))
    return m1

def before_market_open(context):
    
    g.stocks_exsit = get_industry_stocks('HY001') + get_industry_stocks('HY002') \
            + get_industry_stocks('HY003') + get_industry_stocks('HY004') \
            + get_industry_stocks('HY005') + get_industry_stocks('HY006') \
            + get_industry_stocks('HY007') + get_industry_stocks('HY008') \
            + get_industry_stocks('HY009') + get_industry_stocks('HY010') \
            + get_industry_stocks('HY011') 
    g.stocks_exsit = set(filter_special(context,g.stocks_exsit)) #当天上市的所有股票，过滤了ST等
    # g.stocks_exsit =get_stock_list(context)
###------------------------------------------------------------------------------            
def filter_special(context,stock_list):# 过滤器，过滤停牌，ST，科创，新股
    curr_data = get_current_data()

    stock_list=[stock for stock in stock_list if stock[0:3] != '688'] #过滤科创板'688' 
    stock_list = [stock for stock in stock_list if not curr_data[stock].is_st]
    stock_list = [stock for stock in stock_list if not curr_data[stock].paused] 
    # stock_list = [stock for stock in stock_list if 'ST' not in curr_data[stock].name]
    # stock_list = [stock for stock in stock_list if '*'  not in curr_data[stock].name]
    stock_list = [stock for stock in stock_list if '退' not in curr_data[stock].name]
    # stock_list = [stock for stock in stock_list if  curr_data[stock].day_open>1]
    stock_list = [stock for stock in stock_list if  (context.current_dt.date()-get_security_info(stock).start_date).days>150]

    return   stock_list 
