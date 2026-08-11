# 克隆自聚宽文章：https://www.joinquant.com/post/32797
# 标题：韶华研究之六，简单不一样的发现趋势，3年6倍
# 作者：韶华不负

# 导入函数库
from jqdata import *
from six import BytesIO
from jqlib.technical_analysis  import *
from sklearn.linear_model import LinearRegression
import numpy as np
import pandas as pd 
import time

# 初始化函数，设定基准等等
def after_code_changed(context):
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    unschedule_all()
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')
    set_params()    #1 设置策略参数
    set_variables() #2 设置中间变量
    set_backtest()  #3 设置回测条件

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    #run_daily(before_market_open_daily, time='07:00')
    #run_weekly(before_market_open_timely,weekday=1,time='07:00')
    run_monthly(before_market_open_timely,monthday=1,time='07:00')
      # 开盘时运行
    run_monthly(market_open_timely,monthday=1,time='09:30')
    #run_weekly(market_open_timely,weekday=1,time='09:30')
    run_daily(market_open_daily, time='09:30')
      # 收盘时运行
    #run_daily(market_close, time='14:55')
      # 收盘后运行
    #run_daily(after_market_close, time='20:00')
          # 收盘后运行
    #run_daily(after_market_analysis, time='21:00')

#1 设置策略参数
def set_params():
    #设置全局参数，主要策略参数
    g.index ='000300.XSHG'
    g.up_unit = '1M'    #查询静态：按月-1M/周-1w；动态：按月-20d/周-5d
    g.up_num =3         #连阳的个数要求，默认3
    g.up_limit = 1.05      #连阳的下限,1代表平
    
    #次要过滤函数的参数设置
    g.sub_filter = 'E'      #对标的进行二次过滤，默认是None，C-circulating_market_cap流通市值；B-PB当时的市净率；E-PE当时的市盈率；R-roe当时的ROE值；T-trend,周期内的上升趋势
    g.sub_direction = 0     #排序方向是从大到小(市值，PB，PE，ROE)，从高到底(趋势)；0-则相反方向
    
    #止盈止损的参数设置
    g.lostcontrol = 2           #0-无止损；1-静止损；2-动态止损-高点回落；3-趋势止损，正趋进，负趋出；4-均线止损，小于MA出；5-RSI止损；6-RSRS止损
    g.position_balance = 0      #清损后是否动态补仓，默认0-不补，1-现有仓位平衡补满
    g.trend_duration =20        #趋势过滤的周期，10/20/60
    g.ma_duration =20           #均线过滤的周期，10/20/60
    g.rsi_duration =20          #RSI过滤的周期，10/20/60
    g.rsi_down =40              #RSI过滤的下限，33/40/60
    
#2 设置中间变量
def set_variables():
    #暂时未用，测试用全池
    g.stocknum = 5              #持仓数，0-代表全取
    g.poolnum = 1*g.stocknum    #参考池数
    #换仓间隔，也可用weekly或monthly，暂时没启用
    g.shiftdays = 1            #换仓周期，5-周，20-月，60-季，120-半年
    g.day_count = 0             #换仓日期计数器
    
#3 设置回测条件
def set_backtest():
    ## 设定g.index作为基准
    if g.index == 'all':
        set_benchmark('000985.XSHG')
    else:
        set_benchmark(g.index)
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    log.set_level('order', 'error')    # 设置报错等级
    
## 开盘前运行函数
def before_market_open_timely(context):
    # 输出运行时间
    log.info('函数运行时间(before_market_open_timely)：'+str(context.current_dt.time()))
    #0,全局参数预置
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    all_data = get_current_data()
    g.poollist=[]
    
    print('='*60)
    #1,构建票池
    num1,num2,num3,num4,num5=0,0,0,0,0   #用于过程追踪
    
    start_time = time.time()
    if g.index =='all':
        stocklist = list(get_all_securities(['stock']).index)   #取all
    else:
        stocklist = get_index_stocks(g.index, date = None)
    
    num1 = len(stocklist)    
    stocklist = [stockcode for stockcode in stocklist if not all_data[stockcode].paused]
    stocklist = [stockcode for stockcode in stocklist if not all_data[stockcode].is_st]
    stocklist = [stockcode for stockcode in stocklist if'退' not in all_data[stockcode].name]
    stocklist = [stockcode for stockcode in stocklist if (today_date-get_security_info(stockcode).start_date).days>365]
    num2 = len(stocklist)

    end_time = time.time()
    print('Step1,基准%s,原始%d只,四去后共%d只,构建耗时:%.1f 秒' % (g.index,num1,num2,end_time-start_time))
    
    #2，筛选出三阳标的
    start_time = time.time()
    g.poollist =continuous_yangs_filter(context,stocklist,g.up_unit,g.up_num,g.up_limit)
    num3 = len(g.poollist)
    
    end_time = time.time()
    print('Step2,连阳过滤单元%s,个数%s,下限%s,共%d只,构建耗时:%.1f 秒' % (g.up_unit,g.up_num,g.up_limit,num3,end_time-start_time))
    #log.info(g.poollist)
    
    #次要策略过滤
    if g.sub_filter != 'None' and len(g.poollist) !=0:
        g.poollist = second_filter(context, g.poollist, today_date)
        
    #根据预设的持仓数和池数进行标的的选择        
    if g.stocknum ==0 or len(g.poollist) <= g.stocknum:
        g.buylist = g.poollist
    else:
        g.buylist = g.poollist[:g.stocknum]
    
    num4 = len(g.buylist)
    print('选股，基准%s的票池共%d只，连阳过滤出%d只，%s-%s过滤出%d只' % (g.index,num1,num3,g.sub_filter,g.sub_direction,num4))
    
    """
    #3,分析标的的未来走势
    start_time = time.time()
    stock_analysis(context,g.poollist)
    end_time = time.time()
    print('Step3,连阳标的的未来信号走势,构建耗时:%.1f 秒' % (end_time-start_time))
    """
    print('='*60)
    
#适用于daily运行的盘前函数
def before_market_open_daily(context):
    # 输出运行时间
    log.info('函数运行时间(before_market_open_daily)：'+str(context.current_dt.time()))

    
## 开盘时运行函数
def market_open_daily(context): 
    log.info('函数运行时间(market_open_daily):'+str(context.current_dt.time()))
    today_date = context.current_dt.date()
    all_data = get_current_data()
    g.selllist=[]
    
    #止损控制
    if g.lostcontrol ==0:
        return
    else:
        stocklist = list(context.portfolio.positions)
        g.selllist = lost_control(context, stocklist, today_date)
        
        if len(g.selllist) ==0:
            log.info('无控损标的')
            return
        else:
            #先卖出止损
            for stockcode in g.selllist:
                if order_target(stockcode,0) != None:
                    log.info('%s,损控%d卖出' % (stockcode,g.lostcontrol))
            
            if g.position_balance ==0:
                return
            else:
            #然后剩余资金补仓均摊
                buylist = list(context.portfolio.positions)
                cash = context.portfolio.total_value/len(buylist)
                for stockcode in buylist:
                    if all_data[stockcode].paused == True:
                        continue
                    #不光新买，旧仓也做平衡均分
                    if order_target_value(stockcode, cash) != None:
                        log.info('均分补仓%s' % stockcode)
            
## 开盘时运行函数
def market_open_timely(context):
    log.info('函数运行时间(market_open_timely):'+str(context.current_dt.time()))
    today_date = context.current_dt.date()
    all_data = get_current_data()
          
    #1，持仓不在池的卖出
    #因为定期选出的票池数目不固定，全部清出后再重新分配资金买入，以便分析
    for stockcode in context.portfolio.positions:
        if all_data[stockcode].paused == True:
            continue
        if stockcode in g.buylist: #取池内的
            continue
        #非停不在买单则清仓
        if order_target(stockcode,0) != None:
            log.info('%s池外卖出' % stockcode)
    
    #根据票池，平均配重买入
    if len(g.buylist) ==0:
        log.info('无合适标的，关仓')
        return
    
    if (len(context.portfolio.positions) >= len(g.buylist)) and (context.portfolio.available_cash < 0.1*context.portfolio.total_value):
        return
    else:
        cash = context.portfolio.total_value/len(g.buylist)
        for stockcode in g.buylist:
            if all_data[stockcode].paused == True:
                continue
            #不光新买，旧仓也做平衡均分
            if order_target_value(stockcode, cash) != None:
                log.info('%s池内买入' % stockcode)
                
## 收盘时运行函数
def market_close_daily(context):
    log.info('函数运行时间(market_close_daily):'+str(context.current_dt.time()))
                
## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))

    
"""
---------------------------------函数定义-主要策略-----------------------------------------------
"""
#静态的，按周期去检查输入标的是否符合连阳，
def continuous_yangs_filter(context,stocklist,check_unit,check_num,check_limit):
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    all_data = get_current_data()
    poollist=[]
    
    df_price = get_bars(stocklist,unit=check_unit,fields=['open','close','volume'],count=check_num,df=True)
    #write_file('test.csv', df_price.to_csv(), append = True)
    #log.info(df_price)
    
    df_up = df_price[df_price.close >check_limit*df_price.open]
    #log.info(df_up)
    #write_file('test.csv', df_up.to_csv(), append = True)
    index_set =set(df_up.index.get_level_values(0))

    poollist =[stockcode for stockcode in index_set if len(df_up.loc[stockcode,:]) >= check_num]
    
    if check_limit <1:
        if check_unit == '1M':
            #num=3，则对应60d;num=5,则对应100d
            #check_limit为0.95，3连是1.1，5连是1.2
            df_price = get_price(poollist,end_date=lastd_date,frequency='100d',fields=['open','close','volume'],count=1,panel=False)
            poollist = df_price[df_price.close >1.2*df_price.open].code.values.tolist()
        elif check_unit =='1w':
            df_price = get_price(poollist,end_date=lastd_date,frequency='15d',fields=['open','close','volume'],count=1,panel=False)
            poollist = df_price[df_price.close >1.05*df_price.open].code.values.tolist()
    
    return poollist
    
"""
---------------------------------函数定义-次要过滤-----------------------------------------------
"""
#对输入标的进行简单因子的排序和过滤
def second_filter(context, stocklist, check_date):
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    poollist =[]
    
    df_value = get_fundamentals(query(valuation.code,valuation.pe_ratio).filter(valuation.code.in_(stocklist)),lastd_date).dropna()
    
    if g.sub_filter =='C':
        pass
    elif g.sub_filter =='B':    #先去除负值
        pass
    elif g.sub_filter =='E':    #先去除负值
        df_value = df_value[df_value.pe_ratio >0]
        if g.sub_direction ==1: 
            df_value = df_value.sort_values(['pe_ratio'],ascending = False)
        else:
            df_value = df_value.sort_values(['pe_ratio'],ascending = True)
        
        poollist = df_value.code.tolist()
        
    elif g.sub_filter =='R':
        pass
    elif g.sub_filter =='T':
        pass
    
    return poollist
    
#对持仓个股进行止损判断，是则列入卖信
def lost_control(context, stocklist, check_date):
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    all_data = get_current_data()
    poollist =[]
    
    if g.lostcontrol !=3:
        for stockcode in context.portfolio.positions:
            cost = context.portfolio.positions[stockcode].avg_cost
            price = context.portfolio.positions[stockcode].price
            value = context.portfolio.positions[stockcode].value
            intime= context.portfolio.positions[stockcode].init_time
            ret = price/cost - 1
            duration=len(get_trade_days(intime,today_date))
            
            #1-静态止损，止损线可调，-0.1-0.2
            if g.lostcontrol ==1:
                if ret <-0.15:
                    poollist.append(stockcode)
                    continue
            #2-动态止损，回落线可调，0.7-0.9
            elif g.lostcontrol ==2:
                df_price = get_price(stockcode, count = 10, end_date=lastd_date, frequency='daily', fields=['high','close'])
                high_max = df_price['high'].max()
                last_price = df_price['close'].values[-1]
                if last_price/high_max <0.8:
                    poollist.append(stockcode)
                    continue
            #3-均线止损,均线可调，10-20-60-120
            elif g.lostcontrol ==4:
                pass
            #5-RSI止损，日期可调10-20-60，界线可调33-50-66
            elif g.lostcontrol ==5:
                pass
    #3-趋势止损，趋势周期可调，0.5-2*trenddays
    else:
        pass  
        
    return poollist
"""
---------------------------------函数定义-辅助函数-----------------------------------------------
"""

###策略主体思路：取周线或月线三阳(-5-0)的票上车，分动态和静态，或辅以静损15/动损20的止损
###周换/月换，当中止损不补票，票池按300/500/1000
