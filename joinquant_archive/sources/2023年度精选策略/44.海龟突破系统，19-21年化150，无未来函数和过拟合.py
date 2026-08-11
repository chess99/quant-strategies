# 克隆自聚宽文章：https://www.joinquant.com/post/33654
# 标题：海龟突破系统，19-21年化150，无未来函数和过拟合
# 作者：Trading Robot

#管道突破系统
#1.选股。选取沪深300的股票，突破55日最高价买入，突破21日最低价卖出
#2.仓位控制 买入当前仓位的0.25

# 导入函数库
from jqdata import *
import pandas as pd
# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    #set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    g.security=get_index_stocks('000300.XSHG')
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    g.p55=81
    
    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    # run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    #   # 开盘时运行
    run_daily(chicang,time='09:31')
    run_daily(chicang,time='10:21')
    run_daily(chicang,time='11:11')
    # run_daily(chicang,time='11:00')
    # run_daily(chicang,time='11:25')
    run_daily(chicang,time='13:01')
    run_daily(chicang,time='13:51')
    run_daily(chicang,time='14:41')
    # run_daily(chicang,time='14:35')
    # run_daily(chicang,time='14:53')

    #   # 收盘后运行
    # run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')

## 开盘前运行函数
def chicang(context):
    if len(context.portfolio.positions)<1:
        print('当前不持仓，开始选股')
        choice_stock(context)
    if len(context.portfolio.positions) !=0:
        for stock in context.portfolio.positions:
            print('当前持仓总数%s,代码%s'%(len(context.portfolio.positions),stock))
            p=get_current_data()[stock].last_price#当前股价
            day_open=get_current_data()[stock].day_open
            cost=context.portfolio.positions[stock].avg_cost#当前持仓成本
            df5=attribute_history(stock,3)
            df5['bf']=(df5['high']-df5['low'])/df5['low']
            bf_p=df5['bf'].max()
            stop_p1=cost*(1-abs(bf_p))
            stop_p2=cost*(1+abs(bf_p*2))
            if p <=stop_p1:
                print('止损卖出，然后选股')
                order_target(stock, 0)
                choice_stock(context)
            if p>=stop_p2:
                order_target(stock, 0)
                print('止盈卖出，然后选股')
                choice_stock(context)
            else:
                continue
## 开盘时运行函数
def choice_stock(context):
    up_today=context.previous_date    # 昨天日期
    today = context.current_dt
    list_stock=[]
    for stock in g.security[0:]:
        if '300'  in str(stock)[0:3] or '900'  in str(stock)[0:3] or '688'  in str(stock)[0:3] or '200'  in str(stock)[0:3]:
            continue
        p=get_current_data()[stock].last_price #当前股价
        up_today_p=get_price(stock, start_date=up_today, end_date=up_today, frequency='daily', fields=None, skip_paused=False, fq='pre', panel=True, fill_paused=True)['close'][0]
        #print('当前股价',cost)
        df55=attribute_history(stock,g.p55)
        df1=attribute_history(stock,9)
        zdf = (df1['close'][-1] - df1['close'][0]) / df1['close'][0]
        p_max=df55['high'].max()
        if p>p_max and zdf<0:
            list_stock.append(stock)
    if len(list_stock) !=0:
        df_pe = get_valuation(list_stock, end_date=up_today, count=1, fields=['pe_ratio', 'pb_ratio','market_cap'])
        df_pe.sort_values(by='pe_ratio',ascending=False,inplace=True)
        list_pe=list(df_pe['code'])
        for stock in list_pe[0:1]:
            print('买入股票',stock)
            order_target_value(stock,context.portfolio.available_cash)
            print('当前持仓%s'%context.portfolio.long_positions)
        
        
        
        
        
