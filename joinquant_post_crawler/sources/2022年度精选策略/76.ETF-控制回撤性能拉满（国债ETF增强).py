# 克隆自聚宽文章：https://www.joinquant.com/post/36060
# 标题：ETF-控制回撤性能拉满（国债ETF增强）
# 作者：晒太阳的猫

from jqdata import *
import pandas as pd
import numpy as np
import talib

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
    
    g.max_net = context.portfolio.total_value
    g.drawback_status = 0
    g.bad_sign = 0
    
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    
    
    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
      # 开盘时运行
    run_daily(market_open, time='9:30', reference_security='000300.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')


## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    
    g.stock = ['510300.XSHG','510220.XSHG','513500.XSHG','513100.XSHG']
    g.debt = ['511010.XSHG']
    
    # 分配资金
    cash_management(context)
    # 给微信发送消息（添加模拟交易，并绑定微信生效）
    # send_message('美好的一天~')

    # 要操作的股票：平安银行（g.为全局变量）
    # g.security = '000001.XSHE'
def cash_management(context):
    
    HS300_data = get_bars('000300.XSHG', count=60, unit='1d', fields=['close'])
    HS300_MA0_20 = HS300_data['close'][-20:-1].mean()
    HS300_MA20_40 = HS300_data['close'][-40:-21].mean()
    HS300_MA40_60 = HS300_data['close'][-60:-41].mean()
    HS300_price = HS300_data['close'][-1]
    HS300_10_max = HS300_data['close'][-10:-1].max()
    HS300_20_max = HS300_data['close'][-20:-1].max()
    
    
    if HS300_MA0_20<HS300_MA20_40 and HS300_MA20_40<HS300_MA40_60 :
        g.bad_sign = 1
    elif HS300_price < 0.92*HS300_10_max:
        g.bad_sign = 1
    elif HS300_price < 0.85*HS300_20_max:
        g.bad_sign = 1
    else:
        g.bad_sign = 0
    
    if g.drawback_status ==0:
        if context.portfolio.total_value < g.max_net*0.95:
            g.drawback_status=2
        elif context.portfolio.total_value < g.max_net*0.975:
            g.drawback_status=1
    if g.drawback_status ==1:
        if context.portfolio.total_value > g.max_net*0.99:
            g.drawback_status=0
        elif context.portfolio.total_value < g.max_net*0.95:
            g.drawback_status=2
    if g.drawback_status ==2:
        if context.portfolio.total_value > g.max_net*0.99:
            g.drawback_status=0
        elif context.portfolio.total_value > g.max_net*0.975:
            g.drawback_status=1
    
    if g.drawback_status == 0:
        context.stock_cash = 0.3 * context.portfolio.total_value
        context.debt_cash = 0.7 * context.portfolio.total_value
    if g.drawback_status == 1:
        context.stock_cash = 0.4 * context.portfolio.total_value
        context.debt_cash = 0.6 * context.portfolio.total_value
    if g.drawback_status == 2:
        context.stock_cash = 0.5 * context.portfolio.total_value
        context.debt_cash = 0.5 * context.portfolio.total_value
        
    if g.bad_sign ==1:
        context.stock_cash = 0 * context.portfolio.total_value
        context.debt_cash = 1 * context.portfolio.total_value

def order_stock(context):
    pass
    
def order_debt(context):
    pass

def mad(factor):
    me=np.median(factor)
    mad=np.median(abs(factor-me))
    mad_e=1.4826*mad
    up=me+3*mad_e
    down=me-3*mad_e
    
    factor=np.where(factor>up,up,factor)
    factor=np.where(factor<down,down,factor)
    return factor
    

## 开盘时运行函数
def market_open(context):
    # log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    
    # 下订单
    
    for stock in g.debt:
        order_target_value(stock,context.debt_cash/len(g.debt))
    
    
    for stock in g.stock:
        order_target_value(stock,context.stock_cash/len(g.stock))


## 收盘后运行函数
def after_market_close(context):
    
    if context.portfolio.total_value > g.max_net:
        g.max_net = context.portfolio.total_value
        
    log.info("最高资产：",g.max_net)    
    log.info("总资产：",context.portfolio.total_value)
    log.info("可用资产：",context.portfolio.available_cash)
    log.info("股票资金：",context.stock_cash)
    log.info("债券资产：",context.debt_cash)
    log.info("回撤信号：",g.drawback_status)
    log.info("回撤信号：",g.bad_sign)
   
    
    # log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    # #得到当天所有成交记录
    # trades = get_trades()
    # for _trade in trades.values():
    #     log.info('成交记录：'+str(_trade))
    log.info('一天结束')
    log.info('##############################################################')
