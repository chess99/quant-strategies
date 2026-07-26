# 克隆自聚宽文章：https://www.joinquant.com/post/29295
# 标题：股指期货套利，这段时间都没有交易分享给大家
# 作者：节点量化

# 导入函数库
from jqdata import *
import datetime as dt
import numpy as np
import datetime

## 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    #交易量设置  开仓量不超过当前25%
    set_option('order_volume_ratio', 0.25)
    #开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')
    ### 期货相关设定 ###
    # 设定账户为金融账户
    set_subportfolios([SubPortfolioConfig(cash=context.portfolio.starting_cash, type='index_futures')])
    # 开盘前运行
    run_daily( before_market_open, time='before_open', reference_security='000300.XSHG')
    # 开盘时运行
    run_daily( market_open, time='every_bar')
'''
================================================================================
每天开盘前
================================================================================
'''
#每天开盘前要做的事情
def before_market_open(context):
    #设置股票交易手续费
    set_slip_fee(context)

    #获得当前时间
    date = datetime.date.today()
    now = datetime.datetime.now()
    ye = context.current_dt.date().year
    mo = context.current_dt.date().month
    da = context.current_dt.date().day
    if mo==1:
        ye1=ye
        ye2=ye
        mo1=3
        mo2=6
        mon1 = str(mo1)
        mon2 = str(mo2)
        yea1=str(ye1)[2:4]
        yea2=str(ye2)[2:4]
        g.code1="IF"+yea1+"0"+mon1+".CCFX"
        g.code2="IF"+yea2+"0"+mon2+".CCFX"
    elif mo<=4:
        ye1=ye
        ye2=ye
        mo1=6
        mo2=9
        mon1 = str(mo1)
        mon2 = str(mo2)
        yea1=str(ye1)[2:4]
        yea2=str(ye2)[2:4]
        g.code1="IF"+yea1+"0"+mon1+".CCFX"
        g.code2="IF"+yea2+"0"+mon2+".CCFX"
    elif mo<=7:
        ye1=ye
        ye2=ye
        mo1=9
        mo2=12
        mon1 = str(mo1)
        mon2 = str(mo2)
        yea1=str(ye1)[2:4]
        yea2=str(ye2)[2:4]
        g.code1="IF"+yea1+"0"+mon1+".CCFX"
        g.code2="IF"+yea2+mon2+".CCFX"
    elif mo<=10:
        ye1=ye
        ye2=ye+1
        mo1=12
        mo2=3
        mon1 = str(mo1)
        mon2 = str(mo2)
        yea1=str(ye1)[2:4]
        yea2=str(ye2)[2:4]
        g.code1="IF"+yea1+mon1+".CCFX"
        g.code2="IF"+yea2+"0"+mon2+".CCFX"
    elif mo<=12:
        ye1=ye+1
        ye2=ye+1
        mo1=3
        mo2=6
        mon1 = str(mo1)
        mon2 = str(mo2)
        yea1=str(ye1)[2:4]
        yea2=str(ye2)[2:4]
        g.code1="IF"+yea1+"0"+mon1+".CCFX"
        g.code2="IF"+yea2+"0"+mon2+".CCFX"

#根据不同的时间段设置滑点与手续费
def set_slip_fee(context):
    # 设置期货交易的滑点
    # set_slippage(StepRelatedSlippage(0))
    set_slippage(StepRelatedSlippage(2),type='futures',ref = 'IF') 
    # 根据不同的时间段设置手续费
    today=context.current_dt
    # 设置期货合约保证金和手续费
    #2017-2-17调整平今仓位万分之9.2,2017-9-18起，调整为万分之6.9，2018-12-3起，万分之4.6,2019-4-22起，万分之3.45.买入时万分之0.23,卖出时万分之0.23,
    if today<dt.datetime(2017,9,18):
        set_order_cost(OrderCost(open_commission=0.000023, close_commission=0.000023,close_today_commission=0.00092), type='index_futures')
        g.futures_margin_rate=0.2
    elif today<dt.datetime(2018,12,3):
        set_order_cost(OrderCost(open_commission=0.000023, close_commission=0.000023,close_today_commission=0.00069), type='index_futures')
        g.futures_margin_rate=0.15
    elif today<dt.datetime(2019,4,22):
        set_order_cost(OrderCost(open_commission=0.000023, close_commission=0.000023,close_today_commission=0.00046), type='index_futures')
        g.futures_margin_rate=0.1
    else:
        set_order_cost(OrderCost(open_commission=0.000023, close_commission=0.000023,close_today_commission=0.000345), type='index_futures')
        g.futures_margin_rate=0.1
    set_option('futures_margin_rate', g.futures_margin_rate)


## 开盘时运行函数
def market_open(context):
    #获取时间
    mo0 = context.current_dt.date().month
    da = context.current_dt.date().day
    ho=context.current_dt.hour
    mi=context.current_dt.minute
    #获取历史收盘价
    IF1 = attribute_history(g.code1, 300, unit='1m',
            fields=['close'],df=True)['close']#
    IF2=attribute_history(g.code2, 300, unit='1m',
            fields=['close'],df=True)['close']#
    gap=IF1-IF2
    IF1_now=IF1[-1]
    IF2_now=IF2[-1]
    gap_now=IF1_now-IF2_now
    #计算开仓手数，预留20%现金
    cash = context.portfolio.available_cash
    ss=cash/(IF1_now+IF2_now)/300/g.futures_margin_rate/1.2
    if np.isnan(ss):
        ss=0
    s=int(ss)
    code3=""
    code4=""
    tt = ho+mi/60
    #开盘前几分钟跳动太快不开平仓
    if tt>=9.55:
        #计算开仓条件并开仓
        if context.portfolio.positions_value==0:
            if gap.quantile(0.9)>=0 and gap_now>gap.quantile(0.9)*1.1:
                order_target(g.code1, s, side='short',close_today = False)
                order_target(g.code2, s, side='long',close_today = False)
            elif gap.quantile(0.9) < 0 and gap_now>gap.quantile(0.9)*0.9:
                order_target(g.code1, s, side='short',close_today = False)
                order_target(g.code2, s, side='long',close_today = False)
        #计算平仓条件并平仓
        elif gap_now<gap.quantile(0.3):
            for LastFuture in context.portfolio.long_positions.keys():
                code3=LastFuture
            order_target(code3, 0,side='long',close_today = False)
            for LastFuture in context.portfolio.short_positions.keys():
                code4=LastFuture
            order_target(code4, 0,side='short')
