# 克隆自聚宽文章：https://www.joinquant.com/post/26397
# 标题：日内交易策略R-breaker - 300346.XSHE
# 作者：Pole

# 导入函数库
from jqdata import *
import numpy as np
import pandas as pd
from pandas import DataFrame as df
import datetime
import time

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    
    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='09:30', reference_security='000300.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='15:30', reference_security='000300.XSHG')

def judge(tick_data, context, limit):
    
    break_price = g.break_price
    security = g.security
    
    if tick_data.current > break_price['R3'].values and context.portfolio.available_cash > limit:
        order_value(security, limit, style=None, side='long', pindex=0, close_today=False)
        
    if tick_data.high > break_price['R2'].values and tick_data.current < break_price['R1'].values and context.portfolio.total_value > 0:
        position = context.portfolio.long_positions[security]
        
        if position.closeable_amount > (100*np.floor(limit/(tick_data.current*100))):
            order_value(security, -1*limit, style=None, side='long', pindex=0, close_today=False)
        
        
    if tick_data.low < break_price['S2'].values and tick_data.current > break_price['S1'].values and context.portfolio.available_cash > limit:
        order_value(security, limit, style=None, side='long', pindex=0, close_today=False)

        
    if tick_data.current < break_price['S3'].values and context.portfolio.total_value > 0:
        position = context.portfolio.long_positions[security]
        
        if position.closeable_amount > (100*np.floor(limit/(tick_data.current*100))):
            order_value(security, -1*limit, style=None, side='long', pindex=0, close_today=False)





## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    
    # 给微信发送消息（添加模拟交易，并绑定微信生效）
    g.security = '300346.XSHE'
    security = g.security
    # 要操作的股票：南大广电（g.为全局变量）
    g.limits = context.portfolio.starting_cash/10
    
    subscribe(security, 'tick')
    
    
    daily_ND = get_price(security, start_date=None, end_date=context.previous_date, frequency='daily', 
         fields=['open', 'close', 'high', 'low'], skip_paused=False, fq='pre', count=1, panel=True)
    # g.limits: 每次买入卖出限制
    break_price = df(columns = ['R3', 'R2', 'R1', 'S1', 'S2', 'S3'])
    break_price['R2'] = daily_ND['high'] + 0.35*(daily_ND['close'] - daily_ND['low'])
    break_price['S2'] = daily_ND['low'] - 0.35*(daily_ND['high'] - daily_ND['close'])

    break_price['R1'] = 1.07/2*(daily_ND['high'] + daily_ND['low']) -0.07*daily_ND['low']
    break_price['S1'] = 1.07/2*(daily_ND['high'] + daily_ND['low']) -0.07*daily_ND['high']

    break_price['R3'] = break_price['R2'] + 0.25*(break_price['R2'] - break_price['S2'])
    break_price['S3'] = break_price['S2'] - 0.25*(break_price['R2'] - break_price['S2'])
    
    break_price.index = [context.current_dt]
    
    g.break_price = break_price
    # g.break_price: R-breaker 突破边界

## 开盘时运行函数
def handle_tick(context, tick):

    break_price = g.break_price
    

    security = g.security
    limits = g.limits
    tick_data = get_current_tick(security, dt=None, df=False)
    
    judge(tick_data, context, limits)
    
    
    
        

    
    
## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
        
    unsubscribe_all()
    log.info('一天结束')
    log.info('##############################################################')
