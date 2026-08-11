# 克隆自聚宽文章：https://www.joinquant.com/post/38332
# 标题：【复现】特征分布建模择时
# 作者：Hugo2046

from typing import (List,Tuple,Dict,Callable,Union)

import datetime as dt
import numpy as np
import pandas as pd
from six import BytesIO  # 文件读取
from jqdata import *

enable_profile()  # 开启性能分析

def initialize(context):

    set_backtest()
    set_params()
    set_variables()
    before_trading_start(context)

    # prepar_billboard_data(context)
    
    run_daily(get_signal,'9:00',reference_security='000300.XSHG')
    run_daily(trade,'open',reference_security='000300.XSHG')
    
def set_params():
    
    g.fast_period = 30
    g.slow_period = 100
    g.target_benchmark = '000300.XSHG'
    g.target_etf = '510300.XSHG'
    g.to_buy = False
    # g.is_first = True
    
def set_variables():
    
    g.orders_frame = pd.read_csv(BytesIO(read_file('trade_list.csv')),
                          index_col=[0],
                          parse_dates=['datein','dateout'])
    
    g.orders_frame['datein'] = g.orders_frame['datein'].dt.date
    g.orders_frame['dateout'] = g.orders_frame['dateout'].dt.date
    
# def prepar_billboard_data(context):
#     """提前准备数据"""
#     print("初始化前期数据....")
#     # if g.is_first:
#     trade_dt = context.previous_date
#     prev_trade_dt = get_trade_days(end_date=trade_dt,count=1)[0]
#     if prev_trade_dt == trade_dt:
#         prev_trade_dt = get_trade_days(end_date=trade_dt,count=2)[0]
    
#     nums = np.arange(0,101,10)
#     periods = get_trade_days(end_date=trade_dt,count=100)
#     i = 0
#     dfs = []
#     for s,e in zip(nums[:-1],nums[1:]):
#         if i == 0:
#             df = get_billboard_list(start_date=periods[s],end_date=periods[e])
#         elif e == 100:
#             df = get_billboard_list(start_date=periods[s],end_date=periods[e-1])
       
#         else:
#             df = get_billboard_list(start_date=periods[s+1],end_date=periods[e])
          
#         ser = calc_netbuy(df)
#         dfs.append(ser)
#         i+=1
#     ser = pd.concat(dfs).sort_index()
    
#     g.previous_netbuy = ser
    
#     # g.is_first=False
        
#     print('初始化数据准备完毕!')
    
def set_backtest():
    '''回测所需设置'''

    set_option("avoid_future_data", True)  # 避免数据
    set_option("use_real_price", True)  # 真实价格交易
    set_option('order_volume_ratio', 1)  # 根据实际行情限制每个订单的成交量
    set_benchmark('000300.XSHG')  # 设置基准
    #log.set_level("order", "debuge")
    log.set_level('order', 'error')


# 每日盘前运行 设置不同区间手续费
def before_trading_start(context):

    # 手续费设置
    # 将滑点设置为0.002
    set_slippage(FixedSlippage(0.002))

    # 根据不同的时间段设置手续费
    c_dt = context.current_dt

    if c_dt > dt.datetime(2013, 1, 1):
        set_commission(PerTrade(buy_cost=0.0003, sell_cost=0.0013, min_cost=5))

    elif c_dt > dt.datetime(2011, 1, 1):
        set_commission(PerTrade(buy_cost=0.001, sell_cost=0.002, min_cost=5))

    elif c_dt > dt.datetime(2009, 1, 1):
        set_commission(PerTrade(buy_cost=0.002, sell_cost=0.003, min_cost=5))

    else:
        set_commission(PerTrade(buy_cost=0.003, sell_cost=0.004, min_cost=5))
        
# 计算netbuy
def calc_netbuy(billboard:pd.DataFrame)->pd.Series:
    
    def _calc_func(df:pd.DataFrame):
        
        return billboard.query('sales_depart_name=="机构专用"').groupby('day').apply(_calc_func)
        
    return billboard.groupby('day').apply(_calc_func)
    
# 构造HMA
def HMA(price: pd.Series, window: int) -> pd.Series:
    """HMA均线

    Args:
        price (pd.Series): 价格数据. index-date values
        window (int): 计算窗口

    Raises:
        ValueError: 必须为pd.Series

    Returns:
        pd.Series: index-date values
    """
    if not isinstance(price, pd.Series):

        raise ValueError('price必须为pd.Series')

    hma = talib.WMA(
        2 * talib.WMA(price, int(window * 0.5)) - talib.WMA(price, window),
        int(np.sqrt(window)))

    return hma

def get_signal(context):
    """计算开仓信号"""
    

    trade_dt = context.current_dt.date()

    if trade_dt in g.orders_frame['datein'].tolist():
      
        g.to_buy = True
        
    if trade_dt in g.orders_frame['dateout'].tolist():
        
        g.to_buy = False
    
    
    # df = get_billboard_list(end_date=trade_dt, count=1)
    # net_buy = calc_netbuy(df)
    # g.previous_netbuy = g.previous_netbuy.append(net_buy)
    # g.previous_netbuy = g.previous_netbuy.iloc[1:]
    
    # netbuy_s = g.previous_netbuy / get_price(g.set_benchmark,end_date=trade_dt,count=len(g.previous_netbuy),fields='amount')['amount']
    
    # netbuy_s_s = HMA(netbuy_s,g.fast_period)
    # netbuy_s_l = HMA(netbuy_s,g.slow_period)
    
    # # 大幅相对净流入
    # to_buy1: pd.Series = (netbuy_s_s > netbuy_s_l) & (netbuy_s_s > 0) & (netbuy_s_l > 0)
    # # 大幅相对净流出
    # to_buy2: pd.Series = (netbuy_s_s < netbuy_s_l) & (netbuy_s_s < 0) & (netbuy_s_l < 0)
    # entries = (to_buy1 | to_buy2)
    # g.buy = entries.iloc[-1]
    
def trade(context):
    """交易"""
    if g.to_buy:
        
        if not context.portfolio.long_positions:
            print('Buy')
            order_target_value(g.target_etf,context.portfolio.total_value)
            
    else:
        
        if context.portfolio.long_positions:
            print('Sell')
            order_target(g.target_etf,0)
            
            
    
