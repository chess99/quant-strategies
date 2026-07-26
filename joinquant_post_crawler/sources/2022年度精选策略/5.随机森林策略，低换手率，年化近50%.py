# 克隆自聚宽文章：https://www.joinquant.com/post/35566
# 标题：随机森林策略，低换手率，年化近50%
# 作者：寒芳

from jqdata import *
import pandas as pd
import numpy as np
import pickle
import datetime
import math
from six import BytesIO

'''
========================================================================
# 初始化函数，设定基准等等
========================================================================
'''
def initialize(context):
    # 设定上证指数作为基准
    set_default_params(context) #初始化系统参数
    set_benchmark(g.security) ### 股票相关设定 ###
    #load file
    g.df_dic = {}
    tmp_df_dic = pickle.loads(read_file('test_predict_300_q.pkl'))
    for dd, df in tmp_df_dic.items():
        if len(df) == 0:
            continue
        g.df_dic[dd.rsplit('-', 1)[0]] = df.sort_values(by='score', ascending=False)
            
    run_daily(before_market_open, time='before_open')
    run_daily(market_open, time='open', reference_security=g.security)

def set_default_params(context):
    g.security = '000300.XSHG' #BENCHMARK

    g.quantile = (0, 10)
    g.if_trade = False

    set_option('use_real_price', True)
    set_slippage(FixedSlippage(0))
    

def shift_trading_day(date,shift):
    # 获取所有的交易日，返回一个包含所有交易日的 list,元素值为 datetime.date 类型.
    tradingday = get_all_trade_days()
    # 得到date之后shift天那一天在列表中的行标号 返回一个数
    shiftday_index = list(tradingday).index(date)+shift
    # 根据行号返回该日日期 为datetime.date类型
    return tradingday[shiftday_index]

def before_market_open(context):
    # 获得当前日期
    rebalance_day = context.current_dt.date()
    next_day = shift_trading_day(rebalance_day, 1)
    if next_day.month != rebalance_day.month:
        if next_day.day < rebalance_day.day:
            log.info(f'############## trade day：{str(rebalance_day)} ##############')
            g.if_trade = True 

def market_open(context):
    tar_mon = context.current_dt.date().strftime('%Y-%m')
    if g.if_trade is True:
        if tar_mon in g.df_dic:
            log.info(f'############## tar mon：{str(tar_mon)} today: {str(context.current_dt.date())} ##############')
            stock_df = g.df_dic[tar_mon]
            rebalance(context, stock_df)

            for _trade in get_trades().values():
                #log.info(f'############## records：{str(_trade)} ##############')
                pass
        g.if_trade = False

def rebalance(context, stock_df):
    # 每只股票购买金额
    total_value = context.portfolio.total_value
    stock_list = stock_df['name'][int(len(stock_df) * g.quantile[0]/100) : int(len(stock_df) * g.quantile[1]/100)].tolist()
    tar_pos = total_value / len(stock_list)
    #get name
    name_list = []
    for it in stock_list:
        name_list.append(get_security_info(it).display_name)
    log.info(f'############## len: {len(stock_list)}, \n tar_pos: {tar_pos}, \n stock list：{str(stock_list)} \n name list: {str(name_list)} ##############')

    for k1 in context.portfolio.positions.keys():
        if k1 not in stock_list:
            order_target_value(k1, 0)
    for k in stock_list:
        order_target_value(k, tar_pos)
        order_target_value(k, tar_pos)
