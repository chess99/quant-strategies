# 克隆自聚宽文章：https://www.joinquant.com/post/36328
# 标题：期货日内策略三价均线结合ATR指标
# 作者：PokerTrader

# 导入函数库
from jqdata import *
import talib as ta
import numpy as np
import pandas as pd

## 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')

    ### 期货相关设定 ###
    # 设定账户为金融账户
    set_subportfolios([SubPortfolioConfig(cash=context.portfolio.starting_cash, type='index_futures')])
    # 期货类每笔交易时的手续费是：买入时万分之0.23,卖出时万分之0.23,平今仓为万分之4
    set_order_cost(OrderCost(open_commission=0.000023, close_commission=0.00009,close_today_commission=0.0000), type='index_futures')
    # 设定保证金比例
    set_option('futures_margin_rate', 0.15)

    # 设置期货交易的滑点
    set_slippage(StepRelatedSlippage(2))
    # 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'IF8888.CCFX'或'IH1602.CCFX'是一样的）
    # 注意：before_open/open/close/after_close等相对时间不可用于有夜盘的交易品种，有夜盘的交易品种请指定绝对时间（如9：30）
    g.security = 'IF9999.CCFX'
    g.main_symbol = get_dominant_future('IF')
    g.atr_length= 14
    g.ma_length= 20
    g.ma_short_length = 5
    g.ma_up = False
    g.ma_down = False
    g.is_position = False
    g.ma=[]
    g.ma_short = []
    g.signal_long = False
      # 开盘前运行
    run_daily( before_market_open, time='09:00', reference_security='IF8888.CCFX')
      # 开盘时运行
    run_daily( market_open, time='every_bar', reference_security='IF8888.CCFX')
      # 收盘后运行
    run_daily( after_market_close, time='15:30', reference_security='IF8888.CCFX')


## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    g.main_symbol = get_dominant_future('IF')
    momentumAverage = get_momentumAverage(g.main_symbol,2,context.previous_date)
    
    if momentumAverage>0: g.signal_long=True
    else: g.signal_long = False
   

## 开盘时运行函数
def market_open(context):

    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    dt = context.current_dt
    dt_lastMinute = dt-datetime.timedelta(minutes=1)
    if dt.hour ==9 :return # 每天开盘后10点交易
    #最后一分钟不交易，有持仓则卖出，不隔夜
    if dt.hour==14 and dt.minute ==59 :
        if g.is_position:
            if g.signal_long:
                order_target(g.main_symbol, 0)
            else:
                order_target(g.main_symbol, 0,side = 'short')
            g.is_position = False
        return
    
    
    g.ma = get_ma(g.main_symbol, g.ma_length, 4, dt_lastMinute)
    g.ma_short = get_ma(g.main_symbol, g.ma_short_length, 4, dt_lastMinute)
    atr =  get_atr(g.main_symbol,g.atr_length,4,dt_lastMinute)
    g.tr = atr['tr'][-1]
    g.atr = atr['atr'][-1]
    
    g.ma_up = is_ma_up(g.ma)
    g.ma_down = is_ma_down(g.ma)

    log.info('atr:',atr)
    if g.signal_long:
        if  g.ma_up and g.ma_short[-2]<g.ma[-2] and g.ma_short[-1]>g.ma[-1] and (not g.is_position) :#and g.tr<g.atr:
            order_value(g.main_symbol,context.portfolio.available_cash)
            g.is_position = True
        elif g.is_position and ((g.ma_short[-2]>g.ma[-2] and g.ma_short[-1]<g.ma[-1]) or g.ma_short[-1]-g.ma[-1]>3*g.atr ):
            order_target(g.main_symbol, 0)
            g.is_position = False
    else:
        if  g.ma_down and g.ma_short[-2]>g.ma[-2] and g.ma_short[-1]<g.ma[-1] and (not g.is_position) :#and g.tr<g.atr:
            order_value(g.main_symbol,context.portfolio.available_cash,side = 'short')
            g.is_position = True
        elif g.is_position and ((g.ma_short[-2]<g.ma[-2] and g.ma_short[-1]>g.ma[-1]) or g.ma[-1]-g.ma_short[-1]>3*g.atr ):
            order_target(g.main_symbol, 0,side='short')
            g.is_position = False
        
    
   
## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    # 得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    log.info('一天结束')
    log.info('##############################################################')
        

def get_ma(stock, sma_length, duration, end_date):
    #log.info("ma end date {}".format(end_date))
    hist = get_price(stock, count = sma_length + duration, end_date=end_date, frequency='1m', fields=['high','low','close'])
    average = (hist['high']+hist['low']+hist['close'])/3
    ma = ta.MA(average,sma_length)
    log.info('三价均线:',ma[-1])
    
    return ma[sma_length:]

def get_atr(stock,atr_length,duration,end_date):
    data = get_price(stock, count = atr_length+duration, end_date=end_date, frequency='1m', fields=['high', 'low','close'])
    data['yes_close'] = data['close'].shift(1)
    data.dropna(inplace=True)
    data['high_low']=data['high']-data['low']
    data['high_close']=abs(data['high']-data['yes_close'])
    data['low_close']=abs(data['low']-data['yes_close'])
    data['tr']= data[['high_low','high_close','low_close']].max(axis=1)
    data['atr']=ta.MA(data['tr'],atr_length)
    return data[['tr','atr']]
    
    
    
# 判断均线趋势向上
def is_ma_up(ma_day):
    log.info("ma up => {}", ma_day)
    n = 1
    for i in range(len(ma_day) - 1):
        if ma_day[i] <= ma_day[i + 1]: n = n+1
    return n == len(ma_day)
    
# 判断均线趋势向下
def is_ma_down(ma_day):
    log.info("ma down => {}", ma_day)
    n = 1
    for i in range(len(ma_day) - 1):
        if ma_day[i] >= ma_day[i + 1]: n = n+1
    return n == len(ma_day)

    
    
def get_rsi(stock,timePeriod,end_date):
    df = get_price(stock, count = timePeriod+1, end_date=end_date, frequency='daily', fields=['close'])
    close = df['close'].values
    df['RSI']=ta.RSI(close, timeperiod=timePeriod)
    rsi = df['RSI'][-1]
    log.info("RSI",df['RSI'])
    return rsi    
    
def get_momentumAverage(stock,period,end_date):
    df = get_price(stock, count = period+1, end_date=end_date, frequency='daily', fields=['close'])
    df['ret']=df['close'].diff(1)
    df['momentumAverage'] = df['ret'].rolling(period).mean()
    log.info("momentumAverage",df)
    return df['momentumAverage'][-1]
    
    
    

########################## 获取期货合约信息，请保留 #################################
# 获取金融期货合约到期日
def get_CCFX_end_date(future_code):
    # 获取金融期货合约到期日
    return get_security_info(future_code).end_date


########################## 自动移仓换月函数 #################################
def position_auto_switch(context,pindex=0,switch_func=None, callback=None):
    """
    期货自动移仓换月。默认使用市价单进行开平仓。
    :param context: 上下文对象
    :param pindex: 子仓对象
    :param switch_func: 用户自定义的移仓换月函数.
        函数原型必须满足：func(context, pindex, previous_dominant_future_position, current_dominant_future_symbol)
    :param callback: 移仓换月完成后的回调函数。
        函数原型必须满足：func(context, pindex, previous_dominant_future_position, current_dominant_future_symbol)
    :return: 发生移仓换月的标的。类型为列表。
    """
    import re
    subportfolio = context.subportfolios[pindex]
    symbols = set(subportfolio.long_positions.keys()) | set(subportfolio.short_positions.keys())
    switch_result = []
    for symbol in symbols:
        match = re.match(r"(?P<underlying_symbol>[A-Z]{1,})", symbol)
        if not match:
            raise ValueError("未知期货标的：{}".format(symbol))
        else:
            dominant = get_dominant_future(match.groupdict()["underlying_symbol"])
            cur = get_current_data()
            symbol_last_price = cur[symbol].last_price
            dominant_last_price = cur[dominant].last_price
            if dominant > symbol:
                for p in (subportfolio.long_positions.get(symbol, None), subportfolio.short_positions.get(symbol, None)):
                    if p is None:
                        continue
                    if switch_func is not None:
                        switch_func(context, pindex, p, dominant)
                    else:
                        amount = p.total_amount
                        # 跌停不能开空和平多，涨停不能开多和平空。
                        if p.side == "long":
                            symbol_low_limit = cur[symbol].low_limit
                            dominant_high_limit = cur[dominant].high_limit
                            if symbol_last_price <= symbol_low_limit:
                                log.warning("标的{}跌停，无法平仓。移仓换月取消。".format(symbol))
                                continue
                            elif dominant_last_price >= dominant_high_limit:
                                log.warning("标的{}涨停，无法开仓。移仓换月取消。".format(symbol))
                                continue
                            else:
                                log.info("进行移仓换月：({0},long) -> ({1},long)".format(symbol, dominant))
                                order_target(symbol,0,side='long')
                                order_target(dominant,amount,side='long')
                                switch_result.append({"before": symbol, "after":dominant, "side": "long"})
                            if callback:
                                callback(context, pindex, p, dominant)
                        if p.side == "short":
                            symbol_high_limit = cur[symbol].high_limit
                            dominant_low_limit = cur[dominant].low_limit
                            if symbol_last_price >= symbol_high_limit:
                                log.warning("标的{}涨停，无法平仓。移仓换月取消。".format(symbol))
                                continue
                            elif dominant_last_price <= dominant_low_limit:
                                log.warning("标的{}跌停，无法开仓。移仓换月取消。".format(symbol))
                                continue
                            else:
                                log.info("进行移仓换月：({0},short) -> ({1},short)".format(symbol, dominant))
                                order_target(symbol,0,side='short')
                                order_target(dominant,amount,side='short')
                                switch_result.append({"before": symbol, "after": dominant, "side": "short"})
                                if callback:
                                    callback(context, pindex, p, dominant)
    return switch_result
