# 克隆自聚宽文章：https://www.joinquant.com/post/29573
# 标题：【复现】北向资金交易能力一定强吗
# 作者：Hugo2046

'''
Author: Hugo
Date: 2020-09-28 21:52:43
LastEditTime: 2020-09-28 22:10:35
LastEditors: Hugo
Description: 根据最优参数进行择时回测,注意北流数据2014年11月才有数据

关键函数解释：
    distributed_query 用于若干数据查询限制
    query_northmoney 用于查询北向资金数据
    get_net_north_flow 用于计算北向资金净流量
    get_north_factor 是否开仓 大于阈值开仓 小于阈值平仓
'''


from jqdata import *

import numpy as np
import pandas as pd


enable_profile()  # 开启性能分析


def initialize(context):
    set_params()
    set_variables()
    set_backtest()


def set_params():

    g.target_etf = '510300.XSHG'  # 标的为HS300

    # 设置参数
    g.params = {'threshold_h': -0.4991838749623957,
                'threshold_l': -0.15982912319375642,
                'long_period': 71,
                'short_period': 6}


def set_variables():

    pass


def set_backtest():

    set_option("avoid_future_data", True)  # 避免数据
    set_option("use_real_price", True)  # 真实价格交易
    set_benchmark('000300.XSHG')  # 设置基准
    #log.set_level("order", "debuge")
    log.set_level('order', 'error')


# 每日盘前运行
def before_trading_start(context):

    set_slip_fee(context)


# 设置不同时期手续费


def set_slip_fee(context):
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 根据不同的时间段设置手续费
    dt = context.current_dt

    if dt > datetime.datetime(2013, 1, 1):
        set_commission(PerTrade(buy_cost=0.0003, sell_cost=0.0013, min_cost=5))

    elif dt > datetime.datetime(2011, 1, 1):
        set_commission(PerTrade(buy_cost=0.001, sell_cost=0.002, min_cost=5))

    elif dt > datetime.datetime(2009, 1, 1):
        set_commission(PerTrade(buy_cost=0.002, sell_cost=0.003, min_cost=5))

    else:
        set_commission(PerTrade(buy_cost=0.003, sell_cost=0.004, min_cost=5))


########################################### 数据获取 ####################################################

def distributed_query(query_func_name, start: str, end: str, limit=3000, **kwargs) -> pd.DataFrame:
    '''用于绕过最大条数限制'''

    days = get_trade_days(start, end)

    n_days = len(days)

    if len(days) > limit:

        n = n_days // limit

        df_list = []

        i = 0

        pos1, pos2 = n * i, n * (i + 1) - 1

        while pos2 < n_days:

            df = query_func_name(
                start=days[pos1],
                end=days[pos2],
                **kwargs)

            df_list.append(df)

            i += 1

            pos1, pos2 = n * i, n * (i + 1) - 1

            if pos1 < n_days:

                df = query_func_name(
                    start=days[pos1],
                    end=days[-1],
                    **kwargs)

                df_list.append(df)

            df = pd.concat(df_list, axis=0)

    else:

        df = query_func_name(
            start=start, end=end, **kwargs)

    return df


def query_northmoney(start: str, end: str, fields: list) -> pd.DataFrame:
    '''北向资金成交查询'''

    select_type = ['沪股通', '深股通']

    select_fields = ','.join([f"finance.STK_ML_QUOTA.%s" % i for i in fields])

    df_list = []
    for types in select_type:

        q = query(select_fields).filter(finance.STK_ML_QUOTA.day >= start,
                                        finance.STK_ML_QUOTA.day <= end,
                                        finance.STK_ML_QUOTA.link_name == types)
        df_list.append(finance.run_query(q))

    return pd.concat(df_list)


# 构造北流净值
def get_net_north_flow(watch_date: str, N: int) -> pd.Series:

    begin = get_trade_days(end_date=watch_date, count=N)[
        0].strftime('%Y-%m-%d')

    # 获取北流相关数据
    fields = ['day', 'link_name', 'buy_amount', 'sell_amount', 'sum_amount']
    north_money = distributed_query(
        query_northmoney, begin, watch_date, fields=fields)

    # 日度合计各项指标
    daily_northmoney = north_money.groupby('day').sum()

    daily_northmoney.index = pd.to_datetime(daily_northmoney.index)

    # 计算净流
    return daily_northmoney['buy_amount'] - daily_northmoney['sell_amount']

# 信号构造
def get_north_factor(north_flow: pd.Series, params: dict) -> bool:

    l = north_flow.ewm(span=params['long_period'], adjust=False).mean()

    s = north_flow.ewm(span=params['short_period'], adjust=False).mean()

    north_factor = (s - l) / north_flow.rolling(params['long_period']).std()

    record(north_factor=north_factor.iloc[-1],
           h=params['threshold_h'], l=params['threshold_l'])

    if north_factor.iloc[-1] > params['threshold_h']:
        log.info('需要开仓,信号:%.4f,阈值:%.4f' %
                 (north_factor.iloc[-1], params['threshold_h']))
        return True

    elif north_factor.iloc[-1] < params['threshold_l']:
        log.info('需要平仓,信号:%.4f,阈值:%.4f' %
                 (north_factor.iloc[-1], params['threshold_h']))
        return False

    else:
        log.info('不做操作,信号:%.4f,阈值:%.4f' %
                 (north_factor.iloc[-1], params['threshold_h']))
        return True

########################################### 交易 ####################################################


def handle_data(context, data):

    bar_time = context.previous_date.strftime('%Y-%m-%d')

    north_flow = get_net_north_flow(bar_time, 300)

    is_trade = get_north_factor(north_flow, g.params)
    if is_trade and len(context.portfolio.long_positions) == 0:
        log.info('执行开仓操作')
        order_target_value(g.target_etf, context.portfolio.total_value)

    if not is_trade and len(context.portfolio.long_positions) != 0:

        log.info('执行平仓操作')
        order_target(g.target_etf, 0)
