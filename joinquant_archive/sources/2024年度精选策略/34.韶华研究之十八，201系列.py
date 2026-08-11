# 克隆自聚宽文章：https://www.joinquant.com/post/44907
# 标题：韶华研究之十八，201系列
# 作者：韶华不负

##策略介绍
##思路，采取N天M涨停，结合人气前排，和2N天涨幅限制，再观察低开高开的收益区分
##2.10，信号收集分析后，采取201，5-2/3两种类型的优化过滤，按20日涨幅升序排序，取竞价低开的
##竞价符合条件后买入，次日开盘如果收益大于1.05卖出，否则等尾盘非停即出
##2.11 对比尾卖/五刻卖/分钟卖，尾卖最好，因为图的是再板的超额利益

##2.12，信号收集分析后，采取201，低开低涨类型，半仓轮动
##2.12，采用201低位首板低开上，次日尾盘不板卖的策略，并发布
##23/3/18,加入放量倍量过滤，回测显示20天5倍量胜率相对高效果更好，发布
##23/7/22，卖出加入量能控制，回测显示120D0.9V效果最好，发布
# 导入函数库
from jqdata import *
from kuanke.wizard import * #不能和technical_analysis共存
from six import BytesIO
from jqlib.technical_analysis  import *
from jqfactor import get_factor_values
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
    run_daily(before_market_open, time='7:00')
      # 竞价时运行
    run_daily(call_auction, time='09:26')
      # 开盘时运行
    #run_daily(market_run, time='09:30')
    #run_daily(market_run, time='10:30')
    #run_daily(market_run, time='13:30')
    run_daily(market_run, time='14:55')
      # 收盘后运行
    #run_daily(after_market_close, time='20:00')
          # 收盘后运行
    #run_daily(after_market_analysis, time='21:00')

#1 设置策略参数
def set_params():
    #设置全局参数
    g.index ='all'          #all-zz-300-500-1000
    g.auction_open_highlimit = 0.985  #竞价开盘上限
    g.auction_open_lowlimit = 0.945 #竞价开盘下限
    g.profit_line = 1.05    #盘中的止盈门槛
    
    #买前量能过滤参数
    g.volume_control = 2    #0-默认不控制，1-周期放量控制,2-周期倍量控制,3,倍量控制(相对昨日),4-放量(240-0.9)加倍量(20-5)的最佳回测叠加
    g.volume_period = 20   #放量控制周期，240-120-90-60
    g.volume_ratio = 5    #放量控制和周期最高量的比值，0.9/0.8
    
    #持仓量能过滤参数
    g.sell_mode = 0     #0-默认尾盘非板卖，11-T日天量(240),12-T日倍量(相对周期)，13-T日倍量(相对D日)
    g.sell_vol_period = 120   #放量控制周期，240-120-90-60
    g.sell_vol_ratio = 0.9    #放量控制和周期最高量的比值，0.9/0.8
#2 设置中间变量
def set_variables():
    #暂时未用，测试用全池
    g.stocknum = 0              #持仓数，0-代表全取
    g.poolnum = 1*g.stocknum    #参考池数

    
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
    befor_date = get_trade_days(end_date=today_date, count=3)[0]
    all_data = get_current_data()
    g.poolist = []
    g.sell_list =[]
    
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
    stocklist = [stockcode for stockcode in stocklist if stockcode[0:3] != '688']
    stocklist = [stockcode for stockcode in stocklist if (today_date-get_security_info(stockcode).start_date).days>365]
    num2 = len(stocklist)
    
    end_time = time.time()
    print('Step0,基准%s,原始%d只,四去后共%d只,构建耗时:%.1f 秒' % (g.index,num1,num2,end_time-start_time))
    
    #N天M次涨停过滤，20-1，5-2，5-3，5-4，5-5
    start_time = time.time()
    poollist = get_up_filter_jiang(context,stocklist,lastd_date,1,1,0)
    list_201 = get_up_filter_jiang(context,poollist,lastd_date,20,1,0)
    
    g.poollist = optimize_filter(context,list_201,'L')
    
    end_time = time.time()
    print('Step0,N天M次涨停过滤共%d只,板型过滤共%d只,构建耗时:%.1f 秒' % (len(list_201),len(g.poollist),end_time-start_time))
    log.info(g.poollist)
    
    #增加天量/爆量过滤
    if g.volume_control !=0:
        g.poollist = get_highvolume_filter(context,g.poollist,g.volume_control,g.volume_period,g.volume_ratio)
        log.info(g.poollist)    
    #stock_analysis(context,list_201)
    
    #增加持仓股的量能卖出控制
    if g.sell_mode !=0 and len(context.portfolio.positions) !=0:
        stocklist = list(context.portfolio.positions)
        g.sell_list = get_highvolume_filter(context,stocklist,g.sell_mode,g.sell_vol_period,g.sell_vol_ratio)
        log.info('今日早盘卖出:')
        log.info(g.sell_list)
    
def call_auction(context):
    log.info('函数运行时间(Call_auction)：'+str(context.current_dt.time()))
    current_data = get_current_data()
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    buy_list=[]

    df_auction = get_call_auction(g.poollist,start_date=today_date,end_date=today_date,fields=['time','current','volume','money'])

    if len(g.sell_list) ==0:
        log.info('今日早盘无卖信')
    else:
        for stockcode in context.portfolio.positions:
            if current_data[stockcode].paused == True:
                continue
            if (stockcode in g.sell_list):# and (stockcode not in g.buylist):
                sell_stock(context, stockcode,0)
    
    for i in range(len(df_auction)):
        stockcode = df_auction.code.values[i]
        price = df_auction.current.values[i]
        df_price = get_price(stockcode,end_date=lastd_date,frequency='daily',fields=['close'],count=5)
        if price/df_price.close[-1] <g.auction_open_highlimit and  price/df_price.close[-1] >g.auction_open_lowlimit:
            buy_list.append(stockcode)
    
    if len(buy_list) ==0:
        log.info('今日无买信')
        return
    else:
        log.info('今日买信共%d只:' % len(buy_list))
        log.info(buy_list)

    total_value = context.portfolio.total_value
    buy_cash = 0.5*total_value/len(buy_list)
    for stockcode in buy_list:
        if stockcode in list(context.portfolio.positions.keys()):
            continue
        buy_stock(context,stockcode,buy_cash)
    
    return
"""        
#按bar运行        
def handle_data(context,data):
    #log.info('函数运行时间(market_open_bar):'+str(context.current_dt.time()))
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    current_data = get_current_data()
    
    #判断票池和仓位，全为空则轮空
    if len(context.portfolio.positions) ==0:
        log.info('空仓，今天休息')
        return
    
    #判断仓位，若持仓则挂卖单
    for stockcode in context.portfolio.positions:
        if current_data[stockcode].paused == True:
            continue
        if context.portfolio.positions[stockcode].closeable_amount ==0:
            continue
        #止盈出
        cost = context.portfolio.positions[stockcode].avg_cost
        price = current_data[stockcode].last_price
        
        if price/cost > g.profit_line:
            log.info('止盈即出%s' % stockcode)
            sell_stock(context,stockcode,0)
    
    #14：55执行平仓
    hour = context.current_dt.hour
    minute = context.current_dt.minute
    if hour == 14 and minute == 55:
        for stockcode in context.portfolio.positions:
            if current_data[stockcode].paused == True:
                continue
            if context.portfolio.positions[stockcode].closeable_amount ==0:
                continue
            log.info('尾盘平出%s' % stockcode)
            sell_stock(context,stockcode,0)
"""
## 收盘时运行函数
def market_run(context):
    log.info('函数运行时间(market_close):'+str(context.current_dt.time()))
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    current_data = get_current_data()
    
    #尾盘只卖
    hour = context.current_dt.hour
    minute = context.current_dt.minute
    
    for stockcode in context.portfolio.positions:
        if current_data[stockcode].paused == True:
            continue
        if context.portfolio.positions[stockcode].closeable_amount ==0:
            continue
        """
        #止盈出
        cost = context.portfolio.positions[stockcode].avg_cost
        price = current_data[stockcode].last_price
        
        if price/cost > g.profit_line and hour !=14:
            log.info('止盈即出%s' % stockcode)
            sell_stock(context,stockcode,0)
        elif hour == 14:
            log.info('尾盘即出%s' % stockcode)
            sell_stock(context,stockcode,0)
        else:
            log.info('%s留到尾盘' % stockcode)
            
        """
        #非停出
        if current_data[stockcode].last_price != current_data[stockcode].high_limit:
            log.info('非涨停即出%s' % stockcode)
            sell_stock(context,stockcode,0)
            continue
        
## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    today_date = context.current_dt.date()
    last_date = context.previous_date

"""
---------------------------------函数定义-主要策略-----------------------------------------------
"""
#蒋的方法，N天M涨停过滤
def get_up_filter_jiang(context,stocklist,check_date,check_duration,up_num,direction):
    # 输出运行时间
    log.info('函数运行时间(get_up_filter_jiang)：'+str(context.current_dt.time()))
    #0，预置，今天是D日
    all_data = get_current_data()
    poollist=[]
    
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
    log.info('---%d天(%s--%s)%d次涨停过滤出%d只标的,构建耗时:%.1f 秒' % (check_duration,back_date,check_date,up_num,len(poollist),end_time-start_time))        
    #log.info(poollist)

    return poollist

#对1-m板后的形态过滤，1和m是针对20-22年的过滤方案，l-是针对18-22年的一板过滤方案
#去除T日是一字/T字/尾盘封板弱
def optimize_filter(context,stocklist,filt_type):
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    all_data = get_current_data()
    poollist =[]
    
    #其他条件,在循环中过滤
    for stockcode in stocklist:
        #过滤掉一字板，T字板;
        df_lastd = get_price(stockcode,end_date=lastd_date,frequency='daily',fields=['open','close','high','high_limit','low_limit'],count=1)
        if (df_lastd['open'][0] == df_lastd['high_limit'][0] and df_lastd['close'][0] == df_lastd['high_limit'][0]):
            continue
        #过滤掉尾盘封板弱的;
        df_last30 = get_bars(stockcode, count=60, unit='1m', fields=['open','close','high','low'],include_now=True,df=True)
        if (df_last30['low'][:].min() != df_lastd['high_limit'][0]) & (df_last30['high'][:].max() == df_lastd['high_limit'][0]):
            continue
        
        df_value = get_valuation(stockcode, end_date=lastd_date, count=1, fields=['circulating_market_cap']) #先新后老
        cirm_cap = df_value['circulating_market_cap'].values[0]
        
        df_price = get_price(stockcode,end_date=lastd_date,frequency='1d',fields=['open','close','high','low','paused','volume'],skip_paused=False,fq='pre',count=20,panel=False,fill_paused=True)
        change_5 = df_price['close'][-1]/df_price['close'][-5]
        change_20 = df_price['close'][-1]/df_price['close'].values.min()
        vol_lvs20 = df_price['volume'][-1]/df_price['volume'].values.mean()
        
        if filt_type == 1:
            if all_data[stockcode].last_price >8 and change_20 <1.3 and vol_lvs20 <4:
                poollist.append(stockcode)
        elif filt_type =='M':
            if all_data[stockcode].last_price >15 and cirm_cap <50:
                poollist.append(stockcode)
        elif filt_type =='L':
            if change_5 <1.1:
                poollist.append(stockcode)
            
    return poollist

##过滤N天内M倍最高量，X-买入前量能过滤，1X-为持仓的量能过滤
def get_highvolume_filter(context,stocklist,control_mode,check_dura,volume_ratio):
    lastd_date = context.previous_date
    poollist =[]
    
    for stockcode in stocklist:
        if control_mode ==1:
            df_price = get_price(stockcode,end_date=lastd_date,frequency='daily',fields=['volume'],count=check_dura)
            if df_price['volume'][-1] > volume_ratio*df_price['volume'].max():
                continue
            poollist.append(stockcode)
        elif control_mode ==2:
            df_price = get_price(stockcode,end_date=lastd_date,frequency='daily',fields=['volume'],count=check_dura)
            if df_price['volume'][-1] > volume_ratio*df_price['volume'].mean():
                continue
            poollist.append(stockcode)
        elif control_mode ==3:
            df_price = get_price(stockcode,end_date=lastd_date,frequency='daily',fields=['volume'],count=check_dura)
            if df_price['volume'][-1] > volume_ratio*df_price['volume'][-2]:
                continue
            poollist.append(stockcode)
        elif control_mode ==4:
            df_price = get_price(stockcode,end_date=lastd_date,frequency='daily',fields=['volume'],count=240)
            if df_price['volume'][-1] > 0.9*df_price['volume'].max():
                continue
            if df_price['volume'][-1] > 5*df_price['volume'][-20:].mean():
                continue
            poollist.append(stockcode)
        elif control_mode ==11:
            df_price = get_price(stockcode,end_date=lastd_date,frequency='daily',fields=['volume'],count=check_dura)
            if df_price['volume'][-1] < volume_ratio*df_price['volume'].max():
                continue
            poollist.append(stockcode)
        elif control_mode ==12:
            df_price = get_price(stockcode,end_date=lastd_date,frequency='daily',fields=['volume'],count=check_dura)
            if df_price['volume'][-1] < volume_ratio*df_price['volume'].mean():
                continue
            poollist.append(stockcode)
        elif control_mode ==13:
            df_price = get_price(stockcode,end_date=lastd_date,frequency='daily',fields=['volume'],count=check_dura)
            if df_price['volume'][-1] < volume_ratio*df_price['volume'][-2]:
                continue
            poollist.append(stockcode)
        elif control_mode ==14:
            df_price = get_price(stockcode,end_date=lastd_date,frequency='daily',fields=['volume'],count=240)
            if df_price['volume'][-1] < 0.9*df_price['volume'].max():
                continue
            if df_price['volume'][-1] < 5*df_price['volume'][-20:].mean():
                continue
            poollist.append(stockcode)
    
    print('---量能控制%d-%d天放%.1f量过滤后共%d只' % (control_mode,check_dura,volume_ratio,len(poollist)))
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

##个股盘中分析信后的未来走势，带未来
def stock_analysis(context,stocklist):
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    all_data = get_current_data()
    
    #pop = CYF(stocklist, check_date=lastd_date, N=20)
    for stockcode in stocklist:
        stockname = get_security_info(stockcode).display_name
        
        df_value = get_valuation(stockcode, end_date=lastd_date, count=1, fields=['circulating_market_cap']) #先新后老
        cirm_cap = df_value['circulating_market_cap'].values[0]
        
        df_price = get_price(stockcode,end_date=lastd_date,frequency='1d',fields=['open','close','high','low','paused','volume'],skip_paused=False,fq='pre',count=20,panel=False,fill_paused=True)
        change_5 = df_price['close'][-1]/df_price['close'][-5]
        change_20 = df_price['close'][-1]/df_price['close'][0]
        change_5v20 = change_5/change_20
        
        vol_lvs5 = df_price['volume'][-1]/df_price['volume'][-5:].mean()
        vol_5vs20 = df_price['volume'][-5:].mean()/df_price['volume'].values.mean()
        
        df_money = get_money_flow(stockcode, end_date=lastd_date, count=2, fields=['net_amount_main'])  #先新后老
        #存在昨日负流入或为零的状况
        net_main_lbvsb = (df_money['net_amount_main'].values[0]-df_money['net_amount_main'].values[-1])/df_money['net_amount_main'].values[0]
        
        #看未来1-5日的涨跌幅
        fut_date_list = get_trade_days(start_date = today_date,end_date = '2022-02-11')
        if len(fut_date_list) >=5:
            fut5_date = get_trade_days(start_date= today_date)[4]
            next_date = get_trade_days(start_date= today_date)[1]
        else:
            fut5_date = get_trade_days(start_date= today_date)[-1]
            next_date = get_trade_days(start_date= today_date)[1]
    
        future5_price = get_price(stockcode, start_date=today_date, end_date=fut5_date, frequency='daily', fields=['open','close','high','low'])
        next_price = get_price(stockcode, start_date=today_date, end_date=next_date, frequency='daily', fields=['pre_close','open','close','high','low','avg'])
        
        price_D = next_price['open'].values[0]  #今天9:30买入
        catch = price_D/next_price['pre_close'].values[0]
        d2_open = next_price['open'].values[-1]/price_D
        d2_avg = next_price['avg'].values[-1]/next_price['avg'].values[0]
        d2_close = next_price['close'].values[-1]/price_D
        d5_close = future5_price['close'].values[-1]/price_D

        write_file('201.csv', str('%s,%s,%s,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.3f,%.2f,%.2f,%.2f,%.2f\n' % (today_date,stockcode,stockname,cirm_cap,change_5
        ,change_20,change_5v20,vol_lvs5,vol_5vs20,net_main_lbvsb,price_D,catch,d2_open,d2_close,d2_avg,d5_close)),append = True)
