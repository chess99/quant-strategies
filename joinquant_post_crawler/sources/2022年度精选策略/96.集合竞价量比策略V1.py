# 克隆自聚宽文章：https://www.joinquant.com/post/38663
# 标题：集合竞价量比策略V1
# 作者：欧阳1991

# https://www.joinquant.com/research?target=research&url=/user/36908795925/notebooks/%E8%87%AA%E5%AE%9A%E4%B9%89-%E9%87%8F%E6%AF%94API%E7%A0%94%E7%A9%B6.ipynb
# 导入函数库
import pandas as pd
import numpy as np
import talib  ## 使用talib计算MACD的参数
import time
import sys
import json
from jqdata import *
from jqlib.technical_analysis import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')
    g.buy_num = 3
    g.stock_list = []
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(auction, time='9:26', reference_security='000300.XSHG')
    
    run_daily(open_position, time='9:27')
    
    run_daily(sell_norm, time = '14:45')
    
def sell_norm(context):
    curr_data = get_current_data()
    for stock in context.portfolio.positions:
        if curr_data[stock].last_price < curr_data[stock].high_limit:
            order_target_value(stock, 0)

def open_position(context):
    print(list(g.stock_list))
    if len(g.stock_list) > 0 and len(context.portfolio.positions) < g.buy_num :
        hold_num = len(context.portfolio.positions)
        share_ops = g.buy_num - hold_num
        if share_ops > len(g.stock_list):
            share_ops = len(g.stock_list)
        if share_ops > 0:
            share_money = context.portfolio.available_cash / share_ops
            for i in range(share_ops):
                print(str(i)+"_------------------")
                stock = g.stock_list[i]
                order_target_value(stock, share_money)
                

## 开盘前运行函数
def auction(context):
    # 输出运行时间
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    prev_date = context.previous_date;
    now = context.current_dt
    # security_list = get_index_stocks('000852.XSHG', date=now)
    security_list = list(get_all_securities().index)
    
    security_list = filter_688(context, security_list)
    security_list = st_filter(context, security_list)
    security_list = paused_filter(context, security_list)
    # 过滤上市时间小于180天的票
    security_list = filter_new_stock(context, security_list, 180)
    # 获取量比
    lbd = LB(security_list, check_date=now, N=5)
    lbl =  sorted(lbd.items(), key=lambda x: x[1], reverse=True)
    # 获取量比最大的前10名
    lbl = lbl[:10]
    
    ttt = [lb[0] for lb in lbl]
    
    # 获取市值数据  用于计算换手
    val = get_valuation(ttt, end_date=prev_date, fields=['circulating_market_cap'], count=1)
    val = val.set_index('code', drop=True, inplace=False)
    
    # 获取集合竞价数据
    ttt1 = get_ticks(ttt, now, count=1, fields=['time', 'current', 'volume','money','a1_p'], skip=True, df=True)
    ttt1 = ttt1.reset_index(level=1, drop=True)
    ttt1['code'] = ttt1.index
    ttt1 = ttt1.set_index('code', drop=True, inplace=False)
    
    ttt2 = pd.concat([val, ttt1], axis=1, join='inner')
    
    # 计算换手率  成交额 / (流通市值(单位为亿元) * 100万)
    ttt2['ratio'] = ttt2['money'] / (ttt2['circulating_market_cap'] * 1000000)
    
    res_list = ttt2[ttt2['ratio'] > 0.3]
    res_list = res_list.sort_values(by='ratio', axis=0, ascending=False)
    res_list = res_list.index.values
    print(res_list)
    if res_list is not None and len(res_list) > 0:
        g.stock_list = list(res_list)
    else:
        g.stock_list = []
    
    
    
    
    
def filter_688(context,security_list):
    return [stock for stock in security_list if not stock.startswith('688')]
    

## 是否可重复买入
def holded_filter(context,security_list):
    security_list = [stock for stock in security_list if stock not in context.portfolio.positions.keys()]
    # 返回结果
    return security_list

## 过滤停牌股票
def paused_filter(context, security_list):
    current_data = get_current_data()
    security_list = [stock for stock in security_list if not current_data[stock].paused]
    # 返回结果
    return security_list

## 过滤退市股票
def delisted_filter(context, security_list):
    current_data = get_current_data()
    security_list = [stock for stock in security_list if not (('退' in current_data[stock].name) or ('*' in current_data[stock].name))]
    # 返回结果
    return security_list


## 过滤ST股票
def st_filter(context, security_list):
    current_data = get_current_data()
    security_list = [stock for stock in security_list if not current_data[stock].is_st]
    # 返回结果
    return security_list

# 过滤涨停股票
def high_limit_filter(context, security_list):
    current_data = get_current_data()
    security_list = [stock for stock in security_list if not (current_data[stock].day_open >= current_data[stock].high_limit)]
    # 返回结果
    return security_list
    
# 过滤次新股
def filter_new_stock(context, stock_list, open_days=180):
    return [stock for stock in stock_list if (context.previous_date - datetime.timedelta(days=open_days)) > get_security_info(stock).start_date]

# 获取股票股票池
def get_security_universe(context, security_universe_index, security_universe_user_securities):
    temp_index = []
    for s in security_universe_index:
        if s == 'all_a_securities':
            temp_index += list(get_all_securities(['stock'], context.current_dt.date()).index)
        else:
            temp_index += get_index_stocks(s)
    for x in security_universe_user_securities:
        temp_index += x
    return  sorted(list(set(temp_index)))

# 行业过滤
def industry_filter(context, security_list, industry_list):
    if len(industry_list) == 0:
        # 返回股票列表
        return security_list
    else:
        securities = []
        for s in industry_list:
            temp_securities = get_industry_stocks(s)
            securities += temp_securities
        security_list = [stock for stock in security_list if stock in securities]
        # 返回股票列表
        return security_list

# 概念过滤
def concept_filter(context, security_list, concept_list):
    if len(concept_list) == 0:
        return security_list
    else:
        securities = []
        for s in concept_list:
            temp_securities = get_concept_stocks(s)
            securities += temp_securities
        security_list = [stock for stock in security_list if stock in securities]
        # 返回股票列表
        return security_list
    
    
    
    
    
    

