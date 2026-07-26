# 克隆自聚宽文章：https://www.joinquant.com/post/34248
# 标题：低风险高收益的期货策略
# 作者：威航

from jqdata import *
import talib
import pandas as pd
import numpy as np

## 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')
    # 输出内容到日志 log.info()
    # log.info('初始函数开始运行且全局只运行一次')
    
    # 设定全局函数
    # 数据获取周期
    context.LONGPERIOD = 45
    
    # 交易日数统计
    context.day=0
    
    # 初始资金2百万
    context.ori_cash=2000000

    ### 期货相关设定 ###
    # 设定账户为金融账户
    set_subportfolios([SubPortfolioConfig(cash=context.portfolio.starting_cash, type='futures')])
    # 期货类每笔交易时的手续费是：买入时万分之0.23,卖出时万分之0.23,平今仓为万分之23
    set_order_cost(OrderCost(open_commission=0.0001, close_commission=0.0001,close_today_commission=0.0023), type='index_futures')
    # 设定保证金比例
    set_option('futures_margin_rate', 0.15)

    # 设置期货交易的滑点
    set_slippage(StepRelatedSlippage(2))
    # 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'IF8888.CCFX'或'IH1602.CCFX'是一样的）
    # 注意：before_open/open/close/after_close等相对时间不可用于有夜盘的交易品种，有夜盘的交易品种请指定绝对时间（如9：30）
    
      # 开盘前运行
    run_daily( before_market_open, time='8:30', reference_security='FG8888.XZCE')
      # 开盘时运行
    run_daily( market_open, time='9:30', reference_security='FG8888.XZCE')
  

## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    # log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))

    # 给微信发送消息（添加模拟交易，并绑定微信生效）
    # send_message('美好的一天~')

    ## 获取要操作的股票(g.为全局变量)
    # 获取当月指数期货合约
    g.AP = get_dominant_future('AP')
    g.BU = get_dominant_future('BU')
    g.FG = get_dominant_future('FG')
    g.RB = get_dominant_future('RB')
    g.Y = get_dominant_future('Y')
    g.ZC = get_dominant_future('ZC')
    g.AG = get_dominant_future('AG')
    g.P = get_dominant_future('P')
    g.TA = get_dominant_future('TA')
    
    g.AU = get_dominant_future('AU')
    g.CU = get_dominant_future('CU')
    g.RU = get_dominant_future('RU')
    g.J = get_dominant_future('J')
   
    #   设置交易天数时钟，持续统计交易天数
    context.day=context.day+1
    
    # 设置目标年收益率，后续单个期货合约的保证金上限需使用该数据
    context.inc=0.35
    
## 开盘时运行函数
def market_open(context):
    # log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    
    # 2018-2021测试
    # future_list={g.AP,g.BU,g.FG,g.RB,g.Y,g.ZC,g.P,g.TA}
    # future_list={g.BU,g.RB,g.Y,g.P,g.FG,g.TA}
    # future_list={g.FG}
    
    future_list={g.BU,g.RB,g.FG,g.TA,g.J,g.P,g.AG}
    
    # future_list={g.Y}
    # 获取合约数量
    context.num=len(future_list)
    
    # future_list={g.CF}
    # 主力合约切换以后不主动平仓，如主动平仓，使用下面的代码
    # 通过以下，发现现象，贴近合约到期月份，不主动平仓，收益是增加的。这一条是否高可能性需要进一步确认。
    # for future in context.portfolio.short_positions.keys():
    #     if future not in future_list:
    #         order_target_value(future, 0, side='short')
    # for future in context.portfolio.long_positions.keys():
    #     if future not in future_list:
    #         order_target_value(future, 0, side='long')
    # 主力合约切换以后不主动平仓，如主动平仓，使用上面的代码
    # 通过以下，发现现象，贴近合约到期月份，不主动平仓，收益是增加的。这一条是否高可能性需要进一步确认。
   
    
    for future in future_list:
        deal(context,future)
   
    
def deal(context,future_code):
    
    # 当月合约
    current_f = future_code
    
    # 查看空单仓位情况，与成本情况
    if  current_f in context.portfolio.short_positions.keys():
        cur_short =1
        cost_s=context.portfolio.short_positions[current_f].avg_cost
    else:
        cur_short =0
        
    # 查看多单仓位情况    
    if  current_f in context.portfolio.long_positions.keys():
        cur_long =1
        cost_l=context.portfolio.long_positions[current_f].avg_cost
    else:
        cur_long =0
    
    # 获取当前合约历史数据
    num=20
    df=attribute_history(current_f,num)
    
    # 设定多空参数
    duo=0
    kong=0
    
    # 计算20日最高价，最低价，均价与昨日收盘价
    # 海龟法则，判定多空
    h_20=df['high'][-18:-1].max()
    h_10=df['high'][-11:-1].max()
    l_20=df['low'][-18:-1].min()
    l_10=df['low'][-11:-1].min()
    avg_20=df['close'][-21:-1].mean()
    price_now=df['close'][-1]
    
    if price_now>=h_20 :
        duo=duo+0.5
    if price_now>=h_10 and price_now<h_20 :
        duo=duo+0.2
    if price_now<=l_20 :
        kong=kong+0.5
    if price_now<=l_10 and price_now>l_20:
        kong=kong+0.2
    
    # 计算回测区间开盘上涨天数占比，与收盘上涨天数占比
    # 计算3天内收盘上涨或者下跌幅度
    # 开仓：区间上涨天数超过n天&上涨幅度》特定值，多单。
    # 开仓：下跌天数超过n天&下跌幅度超过特定值，空单。
    up_d=0
    dn_d=0
    upvsdn=0
    for i in range(19):
        if df['open'][num-i-1]>df['open'][num-i-2]:
            up_d=up_d+1
        else:
            dn_d=dn_d+1
        if df['close'][num-i-1]>df['close'][num-i-2]:
            up_d=up_d+1
        else:
            dn_d=dn_d+1
    upvsdn=up_d/(up_d+dn_d)
    upvsdn_a=df['close'][-1]/df['close'][-4]
    
    
        
    # 计算MA20 
    ma20=df['close'][-21:-1].mean()
    ma20_1=df['close'][-22:-2].mean()
    
    
    value=(1.1/context.num)*context.ori_cash*(1+context.inc*int(context.day/200))
    
   
    # 合并
    chg_r=0.02
    clr_r=0.03
    db_r=0.08
    
    if price_now>=h_20 and upvsdn>0.6 and upvsdn_a>1.015 and cur_long==0:
        order_target_value(current_f, value, side='long')
    if cur_long>0:
        if upvsdn<0.45 or price_now<=cost_l*(1-clr_r) or price_now>=cost_l*1.15 or price_now<=l_20 or price_now<=h_20*(1-db_r):
            order_target_value(current_f, 0, side='long')
    
    # if price_now<=l_20 and upvsdn<0.4 and upvsdn_a<0.985 and cur_short==0:
    #     order_target_value(current_f, value, side='short')
    # if cur_short>0:
    #     if upvsdn>0.55 or price_now>=cost_s*(1+clr_r) or price_now<=cost_s*0.85 or price_now>=h_20 or price_now>=l_20*(1+db_r):
    #         order_target_value(current_f, 0, side='short') 
    
