# 克隆自聚宽文章：https://www.joinquant.com/post/47897
# 标题：韶华研究之二十，竞价异动
# 作者：韶华不负

"""
策略介绍-竞价异动
昨日涨停票，跟踪9:24和9:25两个时间的tick，对比找出多空两头
应和蒋的战绩分析
3.28差，智莱科技，20D已涨回调，昨日非板，今日竞价量3倍上0.7KW，价微升0.004，开0.058
3.29，建新股份，20D上涨1.5，昨日20CM好板，今日竞价量1.8倍上2.5KW，价微降0.004，开0.066
4.1，海泰科，20D上涨1.5，昨日20CMT字板，今日竞价量3倍上1.6KW，价微升0.001，开0.08
4.3差，七彩化学，昨日20CM好板，今日竞价量2倍上3KW，价降0.025，开0.0587
4.8，宜通世纪，20D慢涨无板，昨日非板，今日竞价量6倍上0.5KW，价微升0.005，开0.053
4.9差，豪恩气电，20D上涨1.2，昨日20CM好板，今日竞价量3倍上3KW，价微升0.013，开0.057
4.10，德福科技，20D上涨1.5，昨日20CM好板，今日竞价量3倍上3KW，价降0.015，开0.063
4.12差，曼卡龙，20D上涨1.2无板，昨日非板，今日竞价量4倍上2KW，价微降0.002，开0.079
4.15，中信海直，20D上涨1.5，昨日非板，今日竞价量2倍上3KW，价升0.02，开0.013
4.24，蓝海华腾，20D振荡，昨日20CM好板，今日竞价量3倍上3KW，价微降0.004，开0.0063
"""
# 导入函数库
from jqdata import *
from jqlib.technical_analysis  import *
from sklearn.linear_model import LinearRegression
from jqfactor import get_factor_values
import numpy as np
import pandas as pd 
import time
import gc

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
    run_daily(before_market_open, time='7:00')
      # 开盘时运行
    run_daily(call_auction, time='09:26')

    #测试不同时间买入
    run_daily(market_open, time='9:30')
    #run_daily(market_run, time='9:30')
    run_daily(market_run, time='14:55')
      # 收盘时运行
    #run_daily(market_close, time='9:30')
      # 收盘后运行
    #run_daily(after_market_close, time='20:00')


#1 设置策略参数
def set_params():
    #设置全局参数
    g.index ='all'          #all-zz-300-500-1000，single-个股信号诊断
    
    g.begin_times = ' 09:24:00'
    g.end_times =  ' 09:25:10'


#2 设置中间变量
def set_variables():
    #暂时未用，测试用全池
    g.stocknum = 0              #单日买入数，0-代表全取,

    
#3 设置回测条件
def set_backtest():
    ## 设定g.index作为基准
    if g.index == 'all':
        set_benchmark('000001.XSHG')
    else:
        set_benchmark(g.index)
        
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    #显示所有列
    pd.set_option('display.max_columns', None)
    #显示所有行
    pd.set_option('display.max_rows', None)
    log.set_level('order', 'error')    # 设置报错等级
    
## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    log.info('------------------------美好的一天开始了------------------------')
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    #0，预置全局参数
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    all_data = get_current_data()
    g.poollist = []
    g.sell_list =[]
        
    num1,num2,num3,num4,num5,num6=0,0,0,0,0,0    #用于过程追踪

    #0，构建基准指数票池，三去+去新
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
    stocklist = [stockcode for stockcode in stocklist if (today_date-get_security_info(stockcode).start_date).days>30]
    stocklist = [stockcode for stockcode in stocklist if stockcode[0] == '3' or stockcode[:2] == '68' or stockcode[:2] == '69']
    num2 = len(stocklist)

    end_time = time.time()
    print('Step0,基准%s,原始%d只,四去后共%d只,构建耗时:%.1f 秒' % (g.index,num1,num2,end_time-start_time))
    
    #1,昨日涨停票
    start_time = time.time()
    g.poollist = get_up_filter_jiang(context,stocklist,lastd_date,1,0,1)
    
    end_time = time.time()
    print('Step1,周期内有涨停共%d只,构建耗时:%.1f 秒' % (len(g.poollist),end_time-start_time))
    #log.info(g.poollist)

def call_auction(context):
    log.info('函数运行时间(Call_auction)：'+str(context.current_dt.time()))
    current_data = get_current_data()
    lastd_date = context.previous_date
    date_time = context.current_dt.strftime("%Y-%m-%d")
    begin = date_time + g.begin_times
    end = date_time + g.end_times
    g.auct_list=[]
    df_pool= pd.DataFrame(columns=['code','p_ratio','v_ratio','money','open_close','open_high'])
    
    if len(g.poollist) ==0:
        log.info('今日无信')
        return
    else:
        start_time = time.time()
        
        for stockcode in g.poollist:
            df_ticks = get_ticks(stockcode,end,begin,None,['time','current','volume','money','a1_p','a1_v','b1_v'],skip=False,df=True)
            df_price = get_price(stockcode,end_date=lastd_date,frequency='daily',fields=['close','high'],count=1)
            #log.info(df_ticks)
            if df_ticks['current'].values[-1] ==0:  #沪市竞价数据每20秒更新一次，很多实例出现9:25整缺少最后一笔tick
                p_ratio = df_ticks['a1_p'].values[-1]/df_ticks['a1_p'].values[0]
                v_ratio = df_ticks['a1_v'].values[-1]/df_ticks['a1_v'].values[0]
                open_close = df_ticks['a1_p'].values[-1]/df_price['close'].values[-1]
                open_high = df_ticks['a1_p'].values[-1]/df_price['high'].values[-1]
            else:
                p_ratio = df_ticks['current'].values[-1]/df_ticks['a1_p'].values[0]
                v_ratio = df_ticks['volume'].values[-1]/df_ticks['a1_v'].values[0]
                open_close = df_ticks['current'].values[-1]/df_price['close'].values[-1]
                open_high = df_ticks['current'].values[-1]/df_price['high'].values[-1]
                
            auc_money = df_ticks['money'].values[-1]
            df_pool = df_pool.append({'code': stockcode,'p_ratio': p_ratio,'v_ratio': v_ratio,'money': auc_money
                ,'open_close':open_close, 'open_high':open_high}, ignore_index=True)
            df_ticks = None #释放内存
            
        #df_pool.sort_values(by='money', ascending=True, inplace=True)
        log.info(df_pool)
        df_abn = df_pool[(df_pool.money > 1e7) & (df_pool.v_ratio >2.5) & (df_pool.p_ratio >0.94) & (df_pool.open_close >1.05)]
        end_time = time.time()
        print('Step2,竞价数据获取并筛选共%d只,构建耗时:%.1f 秒' % (len(df_abn),end_time-start_time))
        g.auct_list = list(df_abn.code)
    
    df_pool = None
    df_abn = None
    gc.collect()
        
## 早盘时运行函数
def market_open(context):
    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    
    if len(g.auct_list) ==0:
        log.info('今日无买信')
        return
    else:
        log.info('*****今日买信共%d只*****:' % len(g.auct_list))
        log.info(g.auct_list)

    total_value = context.portfolio.total_value
    buy_cash = 0.5*total_value/len(g.auct_list)
    for stockcode in g.auct_list:
        if stockcode in list(context.portfolio.positions.keys()):
            continue
        buy_stock(context,stockcode,buy_cash)
    
    return

## 收盘时运行函数
def market_run(context):
    log.info('函数运行时间(market_run):'+str(context.current_dt.time()))
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    current_data = get_current_data()
    
    for stockcode in context.portfolio.positions:
        if current_data[stockcode].paused == True:
            continue
        if context.portfolio.positions[stockcode].closeable_amount ==0:
            continue

        #非停出
        if current_data[stockcode].last_price != current_data[stockcode].high_limit:
            log.info('非涨停即出%s' % stockcode)
            sell_stock(context,stockcode,0)
            continue
        

## 收盘时运行函数
def market_close(context):
    log.info('函数运行时间(market_close):'+str(context.current_dt.time()))

        
## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))


"""
---------------------------------函数定义-主要策略-----------------------------------------------
"""
#蒋的方法，N天M涨停过滤
def get_up_filter_jiang(context,stocklist,check_date,check_duration,up_num,direction):
    # 输出运行时间
    log.info('-函数运行时间(get_up_filter_jiang)：'+str(context.current_dt.time()))
    #0，预置，今天是D日
    all_data = get_current_data()
    poollist=[]
    
    if len(stocklist)==0:
        log.info("输入为空")
        return poollist
    
    # 交易日历
    trd_days = get_trade_days(end_date=check_date, count=check_duration)  # array[datetime.date]
    s_trd_days = pd.Series(range(len(trd_days)), index=trd_days)  # Series[index:交易日期，value:第几个交易日]
    back_date = trd_days[0]
    
    #2，形态过滤，一月内两次以上涨停(盘中过10%也算)
    start_time = time.time()
    # 取数
    df_price = get_price(stocklist,end_date=check_date,frequency='1d',fields=['pre_close','open','close','high','high_limit','low_limit','paused']
    ,skip_paused=False,fq='pre',count=check_duration,panel=False,fill_paused=True)
    
    # 过滤出涨停的股票，按time索引
    df_up = df_price[(df_price.close == df_price.high_limit) & (df_price.paused == 0)].set_index('time')
    # 标注出df_up中的time对应的是第几个交易日(ith)
    df_up['ith'] = s_trd_days
    
    code_set = set(df_up.code.values)
    if direction ==1:
        poollist =[stockcode for stockcode in code_set if ((len(df_up[df_up.code ==stockcode]) > up_num))]
    elif direction ==-1:
        poollist =[stockcode for stockcode in code_set if ((len(df_up[df_up.code ==stockcode]) < up_num))]
    else:
        poollist =[stockcode for stockcode in code_set if ((len(df_up[df_up.code ==stockcode]) == up_num))]
    
    end_time = time.time()
    #log.info('---%d天(%s--%s)%d次涨停过滤出%d只标的,构建耗时:%.1f 秒' % (check_duration,back_date,check_date,up_num,len(poollist),end_time-start_time))        
    #log.info(poollist)

    return poollist
    

"""
---------------------------------函数定义-次要过滤-----------------------------------------------
"""

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


    
