# 克隆自聚宽文章：https://www.joinquant.com/post/36016
# 标题：【复现】高频价量相关性，意想不到的选股因子
# 作者：Hugo2046

from jqdata import *
from jqlib.optimizer import *

import pandas as pd
import numpy as np
from dateutil.parser import parse
from typing import (Tuple, List)
from six import BytesIO  # 文件读取
from sklearn.decomposition import PCA

enable_profile()  # 开启性能分析


def initialize(context):

    set_params(context)
    set_variables()
    set_backtest()

    run_daily(TradeFunc, time='10:30', reference_security='000300.XSHG')


def set_params(context):

    g.hold_num = 200  # 持仓数量

    # pca_pv,pv_corr_avg,pv_corr_std,pv_corr
    # pv_corr_trend,pv_corr_deret20,CPV
    g.factor_name = 'pv_corr'  # 选择因子
    g.is_in_index = None  # 选择指数成分股 None或者对应指数


def set_variables():

    g.factor_df = pd.read_csv(BytesIO(read_file('cpv.csv')),
                              index_col=[0, 1],
                              parse_dates=['date'])


def set_backtest():

    set_redeem_latency(day=2, type='open_fund')  # 设置赎回到账时间
    set_option("avoid_future_data", True)  # 避免数据
    set_option("use_real_price", True)  # 真实价格交易
    set_benchmark('000300.XSHG')  # 设置基准
    #log.set_level("order", "debuge")
    log.set_level('order', 'error')


# 每日盘前运行
def before_trading_start(context):

    # 手续费设置
    # 将滑点设置为千2
    set_slippage(FixedSlippage(0.002))

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


def TradeFunc(context):

    trade_date = context.previous_date

    if trade_date in g.factor_df.index.levels[0]:

        if g.factor_name == 'pca_pv':
            
            pca = PCA(n_components=1)
            
            v = g.factor_df.loc[trade_date].fillna(0).values
            
            pca_v = pca.fit_transform(v)
            
            pca_pv = pd.DataFrame(pca_v,
                                  index=g.factor_df.loc[trade_date].index,
                                  columns=['pca_pv'])
                                  
            frame = -pca_pv['pca_pv']  # 取相反，pca_pv低5组最好
            
        else:
            
            frame = g.factor_df.loc[trade_date, g.factor_name]

        if g.is_in_index is None:

            target_code = frame.nsmallest(g.hold_num).index.tolist()

        else:
            
            cons_symbol = get_index_stocks(g.is_in_index)
            
            target_code = frame.reindex(cons_symbol).nsmallest(
                g.hold_num).index.tolist()

        for hold in context.portfolio.long_positions:
            
            if hold not in target_code:
                
                order_target(hold, 0)

        every_stock = context.portfolio.total_value / len(target_code)

        for stock in target_code:
            
            order_target_value(stock, every_stock)
