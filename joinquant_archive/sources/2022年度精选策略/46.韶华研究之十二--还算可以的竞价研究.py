# 克隆自聚宽文章：https://www.joinquant.com/post/36331
# 标题：韶华研究之十二--还算可以的竞价研究
# 作者：韶华不负

#RPS一进二策略V1.1
# 导入函数库
from jqdata import *
from kuanke.wizard import * #不能和technical_analysis共存
from six import BytesIO
from jqlib.technical_analysis  import *
from sklearn.linear_model import LinearRegression
import numpy as np
import pandas as pd
import time

# 初始化函数，设定基准等等
def initialize(context):
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
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
    run_daily(before_market_open, time='7:00')
      # 开盘时运行
    run_daily(call_auction, time='09:27')
    run_daily(market_open, time='09:30')   
      # 收盘时运行
    run_daily(market_close, time='14:55')
      # 收盘后运行
    #run_daily(after_market_close, time='20:00')
          # 收盘后运行
    #run_daily(after_market_analysis, time='21:00')

#1 设置策略参数
def set_params():
    #设置全局参数
    g.index ='all'          #all-zz-300-500-1000
    g.long_dura = 88
    g.medium_dura = 44
    g.short_dura = 22
    g.rps_ratio = 0.1
   
#2 设置中间变量
def set_variables():
    #暂时未用，测试用全池
    g.stocknum = 4             #持仓数，0-代表全取
    g.poolnum = 1*g.stocknum    #参考池数
    #换仓间隔，也可用weekly或monthly，暂时没启用
    g.shiftdays = 1            #换仓周期，5-周，20-月，60-季，120-半年
    g.day_count = 0             #换仓日期计数器
   
#3 设置回测条件
def set_backtest():
    ## 设定g.index作为基准
    if g.index == 'all':
        set_benchmark('000001.XSHG')
    else:
        set_benchmark(g.index)
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    #set_option("avoid_future_data", True)
    #显示所有列
    pd.set_option('display.max_columns', None)
    #显示所有行
    pd.set_option('display.max_rows', None)
    log.set_level('order', 'error')    # 设置报错等级
   
## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    #0，预置全局参数
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    all_data = get_current_data()
    g.list_classA = []
    g.list_classB = []
    g.list_classC = []
       
    #0，判断计数器是否开仓
    if (g.day_count % g.shiftdays ==0):
        log.info('今天是换仓日，开仓')
        g.adjustpositions = True
        g.day_count += 1
    else:
        log.info('今天是旁观日，持仓')
        g.day_count += 1
        g.adjustpositions = False
        return
   
    num1,num2,num3,num4,num5,num6=0,0,0,0,0,0    #用于过程追踪

    #1，构建基准指数票池，三去+去新
    start_time = time.time()
    if g.index =='all':
        stocklist = list(get_all_securities(['stock']).index)   #取all
    elif g.index == 'zz':
        stocklist = get_index_stocks('000300.XSHG', date = None) + get_index_stocks('000905.XSHG', date = None) + get_index_stocks('000852.XSHG', date = None)
    else:
        stocklist = get_index_stocks(g.index, date = None)
   
    num1 = len(stocklist)   
    stocklist = [stockcode for stockcode in stocklist if not all_data[stockcode].paused]
    stocklist = [stockcode for stockcode in stocklist if not all_data[stockcode].is_st]
    stocklist = [stockcode for stockcode in stocklist if'退' not in all_data[stockcode].name]
    stocklist = [stockcode for stockcode in stocklist if (today_date-get_security_info(stockcode).start_date).days>365]
    num2 = len(stocklist)

    end_time = time.time()
    print('Step0,基准%s,原始%d只,四去后共%d只,构建耗时:%.1f 秒' % (g.index,num1,num2,end_time-start_time))

    start_time = time.time()
    list_rps_s = get_rps_filter(context,stocklist,lastd_date,g.short_dura,0.1)
    list_rps_m = get_rps_filter(context,stocklist,lastd_date,g.medium_dura,0.1)
    list_rps_l = get_rps_filter(context,stocklist,lastd_date,g.long_dura,0.1)
    g.list_A = list(set(list_rps_s).intersection(list_rps_m,list_rps_l))
   
    end_time = time.time()
    print('Step1,组建RPS多周期%d-%d-%d,三线全红-%s的票池共%d只,构建耗时:%.1f 秒' % (g.short_dura,g.medium_dura,g.long_dura,g.rps_ratio,len(g.list_A),end_time-start_time))

    start_time = time.time()
    g.list_B = get_pre_filter(context,g.list_A,lastd_date)
    end_time = time.time()
    print('Step2,对A池进行初步过滤得B池%d只,构建耗时:%.1f 秒' % (len(g.list_B),end_time-start_time))
    log.info(g.list_B)
  
def call_auction(context):
    log.info('函数运行时间(Call_auction)：'+str(context.current_dt.time()))
    current_data = get_current_data()
    today_date = context.current_dt.date()
    lastd_date = context.previous_date

    start_time = time.time()
    g.list_B = get_auction_filter(context,g.list_B,1000000)    #默认 10000000
   
    end_time = time.time()
    print('Step2,竞价过滤,B池剩下%d只,构建耗时:%.1f 秒' % (len(g.list_B),end_time-start_time))
    log.info(g.list_B)
   
    g.buy_list = list(get_score_filter(context,g.list_B).keys())[:g.stocknum]
   
    if len(g.buy_list) ==0:
        log.info('今日无合适标的')
        return

## 开盘时运行函数
def market_open(context):
    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    current_data = get_current_data()
   
    #早盘只买
    if len(g.buy_list) ==0:
        log.info('今日无买信')
        return
    else:
        cash = context.portfolio.total_value/g.stocknum
        for stockcode in g.buy_list:
            buy_stock(context,stockcode,cash)
           
            if len(context.portfolio.positions) >= (g.stocknum-1):
                log.info('今日已满仓')
                return
       
## 收盘时运行函数
def market_close(context):
    log.info('函数运行时间(market_close):'+str(context.current_dt.time()))
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    current_data = get_current_data()
    #尾盘只卖
    for stockcode in context.portfolio.positions:
        if current_data[stockcode].paused == True:
            continue
       
        #非停出
        if current_data[stockcode].last_price != current_data[stockcode].high_limit:
            log.info('非停即出%s' % stockcode)
            sell_stock(context,stockcode,0)
            continue
   
         
## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))


"""
---------------------------------函数定义-主要策略-----------------------------------------------
"""
def get_rps_filter(context,stocklist,check_date,duration,ratio):
    poollist=[]
    df_price=get_price(stocklist, count=duration, end_date=check_date, skip_paused=True, panel=False)
    df_rps =df_price.groupby("code").apply(lambda x:x.iloc[-1].close/x.iloc[0].close)
    df_rps =df_rps.sort_values(ascending=False)#.head(int(df_price.shape[0]*ratio))
    df_rps =df_rps.dropna()
    poollist = df_rps.index.tolist()
    poollist = poollist[:int(len(stocklist)*ratio)]
    return poollist

def get_pre_filter(context,stocklist,check_date):
    poollist =[]

    stocklist = get_up_filter(context,stocklist,250,1)
    stocklist = get_down_filter(context,stocklist,250,0)
    stocklist = get_reds_filter(context,stocklist,60,31) 
   
    for stockcode in stocklist:
        df_price = get_price(stockcode,end_date=check_date,frequency='daily',fields=['pre_close','open','high_limit','high','low','close'],count=2)
        if (df_price.close.values[0] == df_price.high_limit.values[0]) or (df_price.high.values[-1] != df_price.high_limit.values[-1]):
            continue
       
        df_price = get_price(stockcode,end_date=check_date,frequency='daily',fields=['pre_close','open','high_limit','high','low','close','volume'],count=41)
        df_late40 = pd.DataFrame(columns=['lb','yby_c','yby_o'])
        df_late40.lb = df_price.volume/df_price.volume.shift(1)
        df_late40.yby_c = df_price.close/df_price.open.shift(1)
        df_late40.yby_o = df_price.open/df_price.close.shift(1)
        df_late40 = pd.concat([df_price,df_late40],axis=1)

        if len(df_late40[(df_late40.close > df_late40.pre_close) & (df_late40.lb >1)]) <3:
            continue

        df_late10 = df_late40.iloc[-10:,:]
        if len(df_late10[(df_late10.close < df_late10.open) & (df_late10.yby_c <1) & (df_late10.yby_o >1) &(df_late10.lb >1)]) !=0:
            continue
        poollist.append(stockcode)
   
    return poollist

def get_auction_filter(context,stocklist,money_limit):
    current_data = get_current_data()
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    poollist =[]
   
    #针对A类的再次筛选
    df_auction = get_call_auction(stocklist,start_date=today_date,end_date=today_date,fields=['time','current','volume','money'])
    df_auction = df_auction[df_auction.money>money_limit].sort_values(['money'],ascending = False)
    for i in range(len(df_auction)):
        stockcode = df_auction.code.values[i]
        price = df_auction.current.values[i]
        df_price = get_price(stockcode,end_date=lastd_date,frequency='daily',fields=['close'],count=7)
        close_max = df_price.close.values.max()

        if price < close_max:
            continue
        poollist.append(stockcode)
       
    return poollist

def get_score_filter(context,stocklist):
    current_data = get_current_data()
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    back10_date = get_trade_days(end_date=lastd_date,count=10)[9] #用于检查多头排列
    back5_date = get_trade_days(end_date=lastd_date,count=6)[5]
    back20_date = get_trade_days(end_date=lastd_date,count=21)[20]
    score_sets ={}
   
    for stockcode in stocklist:
        score = 0
       
        #均线加分项
        MA10_last = MA(stockcode, check_date=lastd_date, timeperiod=10)
        MA20_last = MA(stocklist, check_date=lastd_date, timeperiod=20)
        MA30_last = MA(stocklist, check_date=lastd_date, timeperiod=30)
       
        MA10_back = MA(stockcode, check_date=back10_date, timeperiod=10)
        MA20_back = MA(stocklist, check_date=back10_date, timeperiod=20)
        MA30_back = MA(stocklist, check_date=back10_date, timeperiod=30)
       
        if (MA10_back[stockcode]/MA20_back[stockcode] < MA10_last[stockcode]/MA20_last[stockcode]) and (MA10_back[stockcode]/MA20_back[stockcode] >1
        ) and (MA20_back[stockcode]/MA30_back[stockcode] < MA20_last[stockcode]/MA30_last[stockcode]) and (MA20_back[stockcode]/MA30_back[stockcode] >1):
            score +=10
        elif ((MA10_back[stockcode]/MA20_back[stockcode] < MA10_last[stockcode]/MA20_last[stockcode]) and (MA10_back[stockcode]/MA20_back[stockcode] >1
        )) or ((MA20_back[stockcode]/MA30_back[stockcode] < MA20_last[stockcode]/MA30_last[stockcode]) and (MA20_back[stockcode]/MA30_back[stockcode] >1)):
            score +=5
       
        #跳空加分项
        df_price = get_price(stockcode,end_date=lastd_date,frequency='daily',fields=['pre_close','high_limit','low_limit','high','low','close'],count=60)
        df_late5 = df_price.iloc[-5:,:]
        if len(df_late5[df_late5.low > df_late5.pre_close]):
            score +=10
        df_late20 = df_price.iloc[-20:-6,:]
        if len(df_late20[df_late20.low > df_late20.pre_close]):
            score +=20
        df_late60 = df_price.iloc[:-21,:]
        if len(df_late60[df_late60.low > df_late60.pre_close]):
            score +=30
           
        #一字板和跌停扣分项
        df_d20 = df_price.iloc[-20:,:]
        if len(df_d20[df_d20.low == df_d20.high_limit]) !=0:
            score -= 20
        if len(df_price[df_price.close == df_price.low_limit]) !=0:
            score -= 20
       
        score_sets[stockcode] = score
   
    log.info(score_sets)
    return score_sets
   
"""
---------------------------------函数定义-次要过滤-----------------------------------------------
"""
def get_reds_filter(context,stocklist,check_duration,reds_num):
    # 输出运行时间
    log.info('函数运行时间(get_reds_filter)：'+str(context.current_dt.time()))
    #0，预置，今天是D日
    all_data = get_current_data()
    today_date = context.current_dt.date()
    lastd_date = context.previous_date  #昨天
    poollist=[]
   
    # 交易日历
    trd_days = get_trade_days(end_date=lastd_date, count=check_duration)  # array[datetime.date]
    s_trd_days = pd.Series(range(len(trd_days)), index=trd_days)  # Series[index:交易日期，value:第几个交易日]
    back_date = trd_days[0]

    start_time = time.time()
    # 取数
    df_price = get_price(stocklist,end_date=lastd_date,frequency='1d',fields=['pre_close','open','close','high','high_limit','low_limit','paused']
    ,skip_paused=False,fq='pre',count=check_duration,panel=False,fill_paused=True)
   
    df_reds = df_price[(df_price.close > df_price.pre_close) & (df_price.paused == 0)].set_index('time')
    # 标注出df_up中的time对应的是第几个交易日(ith)
    df_reds['ith'] = s_trd_days
   
    code_set = set(df_reds.code.values)
    poollist =[stockcode for stockcode in code_set if ((len(df_reds[df_reds.code ==stockcode]) >= reds_num))]
   
    end_time = time.time()
    log.info('--%d天(%s--%s)%d次以上红K线过滤出%d只标的,构建耗时:%.1f 秒' % (check_duration,back_date,lastd_date,reds_num,len(poollist),end_time-start_time))       
    #log.info(poollist)

    return poollist

def get_down_filter(context,stocklist,check_duration,down_num):
    # 输出运行时间
    log.info('函数运行时间(get_down_filter)：'+str(context.current_dt.time()))
    #0，预置，今天是D日
    all_data = get_current_data()
    today_date = context.current_dt.date()
    lastd_date = context.previous_date  #昨天
    poollist=[]
   
    # 交易日历
    trd_days = get_trade_days(end_date=lastd_date, count=check_duration)  # array[datetime.date]
    s_trd_days = pd.Series(range(len(trd_days)), index=trd_days)  # Series[index:交易日期，value:第几个交易日]
    back_date = trd_days[0]

    start_time = time.time()
    # 取数
    df_price = get_price(stocklist,end_date=lastd_date,frequency='1d',fields=['pre_close','open','close','high','high_limit','low_limit','paused']
    ,skip_paused=False,fq='pre',count=check_duration,panel=False,fill_paused=True)

    df_down = df_price[(df_price.close == df_price.low_limit) & (df_price.paused == 0)].set_index('time')
    # 标注出df_up中的time对应的是第几个交易日(ith)
    df_down['ith'] = s_trd_days
   
    code_set = set(df_down.code.values)
    downlist =[stockcode for stockcode in code_set if ((len(df_down[df_down.code ==stockcode]) > down_num))]
    poollist = list(set(stocklist).difference(set(downlist)))
   
    end_time = time.time()
    log.info('--%d天(%s--%s)%d次以下跌停过滤出%d只标的,构建耗时:%.1f 秒' % (check_duration,back_date,lastd_date,down_num,len(poollist),end_time-start_time))       
    #log.info(poollist)

    return poollist

def get_up_filter(context,stocklist,check_duration,up_num):
    # 输出运行时间
    log.info('函数运行时间(get_up_filter)：'+str(context.current_dt.time()))
    #0，预置，今天是D日
    all_data = get_current_data()
    today_date = context.current_dt.date()
    lastd_date = context.previous_date  #昨天
    poollist=[]
   
    # 交易日历
    trd_days = get_trade_days(end_date=lastd_date, count=check_duration)  # array[datetime.date]
    s_trd_days = pd.Series(range(len(trd_days)), index=trd_days)  # Series[index:交易日期，value:第几个交易日]
    back_date = trd_days[0]
   
    start_time = time.time()
    # 取数
    df_price = get_price(stocklist,end_date=lastd_date,frequency='1d',fields=['pre_close','open','close','high','high_limit','low_limit','paused']
    ,skip_paused=False,fq='pre',count=check_duration,panel=False,fill_paused=True)
   
    df_up = df_price[(df_price.close == df_price.high_limit) & (df_price.paused == 0)].set_index('time')
    # 标注出df_up中的time对应的是第几个交易日(ith)
    df_up['ith'] = s_trd_days
   
    code_set = set(df_up.code.values)
    poollist =[stockcode for stockcode in code_set if ((len(df_up[df_up.code ==stockcode]) >= up_num))]
   
    end_time = time.time()
    log.info('--%d天(%s--%s)%d次以上涨停过滤出%d只标的,构建耗时:%.1f 秒' % (check_duration,back_date,lastd_date,up_num,len(poollist),end_time-start_time))        
    #log.info(poollist)

    return poollist
"""
---------------------------------函数定义-辅助函数-----------------------------------------------
"""
##买入函数
def buy_stock(context,stockcode,cash):
    today_date = context.current_dt.date()
    current_data = get_current_data()
   
    if stockcode[0:3] == '688':
        last_price = current_data[stockcode].last_price
        if order_target_value(stockcode,cash,MarketOrderStyle(1.1*last_price)) != None: #科创板需要设定限值
            log.info('%s买入%s' % (today_date,stockcode))
    else:
        if order_target_value(stockcode, cash) != None:
            log.info('%s买入%s' % (today_date,stockcode))
           
##卖出函数
def sell_stock(context,stockcode,cash):
    today_date = context.current_dt.date()
    current_data = get_current_data()
   
    if stockcode[0:3] == '688':
        last_price = current_data[stockcode].last_price
        if order_target_value(stockcode,cash,MarketOrderStyle(0.9*last_price)) != None: #科创板需要设定限值
            log.info('%s卖出%s' % (today_date,stockcode))
    else:
        if order_target_value(stockcode,cash) != None:
            log.info('%s卖出%s' % (today_date,stockcode))


