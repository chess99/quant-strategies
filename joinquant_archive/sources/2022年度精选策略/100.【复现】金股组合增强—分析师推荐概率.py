# 克隆自聚宽文章：https://www.joinquant.com/post/39135
# 标题：【复现】金股组合增强—分析师推荐概率
# 作者：Hugo2046

from jqdata import *
from jqlib.optimizer import *

import pandas as pd
import numpy as np
from dateutil.parser import parse
from typing import (Tuple, List)
from six import BytesIO  # 文件读取

enable_profile()  # 开启性能分析


def initialize(context):

    set_params()
    set_variables()
    set_backtest()
    
    
    #run_monthly(TradeFunc,1, time='10:30', reference_security='000300.XSHG')
    run_daily(TradeFunc, time='10:30',reference_security='000300.XSHG')


def set_params():

    g.csv_file = 'trade.csv'
    g.month_end = get_month_end_day().dt.date.values

def set_variables():

    g.target_df = pd.read_csv(BytesIO(read_file(g.csv_file)),
                              index_col=['trade_date'],parse_dates=['trade_date'],encoding='gbk')

    g.target_df['asset'] = g.target_df['sec_code'].apply(normalize_code) # 标准化股票代码
    print(g.target_df.head())
    
def set_backtest():

    set_option("avoid_future_data", True)  # 避免数据
    set_option("use_real_price", True)  # 真实价格交易
    set_benchmark('000300.XSHG')  # 设置基准
    #log.set_level("order", "debuge")
    log.set_level('order', 'error')


# 每日盘前运行
def before_trading_start(context):

    # 手续费设置
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
        
def get_month_end_day():
    
    days = pd.to_datetime(get_all_trade_days()).to_frame()
    days.columns = ['trade']
    return days.groupby(pd.Grouper(level=0,freq='M'))['trade'].last()
    
def TradeFunc(context):
    
    
    watch_date = context.previous_date
    
    
    if watch_date in g.target_df.index:
        
        df = g.target_df.loc[watch_date]
        if isinstance(df,pd.DataFrame):

                target_code = df['asset'].unique().tolist()
                
        else:
            
            target_code = [df['asset'][0]]
            
        if target_code:
            print('选股日期:%s,目标个数:%s'%(watch_date,len(target_code)))
            df2order(context,target_code)
        
        record(持仓数量 = len(context.portfolio.long_positions),目标数量=len(target_code))
    
    # if watch_date in g.month_end:
    #     print(f'{watch_date}月末平仓')
    #     if context.portfolio.long_positions:
    #         for sell_code in context.portfolio.long_positions:
    #             order_target(sell_code,0)
    
    
def df2order(context,target:list):
    
    if target:
        for sell_code in context.portfolio.long_positions:
            if sell_code not in target:
                order_target(sell_code,0)
        
        everystock = context.portfolio.total_value / len(target)
        
        for buy_code in target:
            
           
                
            order_target_value(buy_code,everystock)
                

    
            
