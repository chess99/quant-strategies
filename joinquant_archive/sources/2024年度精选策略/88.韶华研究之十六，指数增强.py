# 克隆自聚宽文章：https://www.joinquant.com/post/39897
# 标题：韶华研究之十六，指数增强
# 作者：韶华不负

##策略介绍
##
# 导入函数库
from jqdata import *
from kuanke.wizard import * #不能和technical_analysis共存
from six import BytesIO
from jqlib.technical_analysis  import *
from sklearn.linear_model import LinearRegression
from scipy.stats import linregress
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
      # 开盘时运行
    run_daily(market_open, time='09:30')    
      # 收盘时运行
    #run_daily(market_close, time='14:55')
      # 收盘后运行
    #run_daily(after_market_close, time='20:00')
          # 收盘后运行
    #run_daily(after_market_analysis, time='21:00')

#1 设置策略参数
def set_params():
    ##0-设置全局参数，以及票池基准
    g.index ='000905.XSHG'  #all-zz(8&10的合集)-300-500-1000
    
    ##1-票池的辅助过滤
    g.pool_filter = 'R'    #R-过滤周期内上涨过大的
    g.indus_level = 'None' #对应I，sw_l1--申万一级；sw_l2--申万二级
    g.drop_line = 0      #针对过滤D，回调线0.75-0.8
    g.drop_days = 0       #针对过滤D，回调周期10-20
    g.rise_uplimit = 1.5    #针对过滤R，2-1.5-1.2
    
    ##2-票池的主要筛选策略
    g.strategy = 'T'       #T-Trend，采用斜线拟合斜率，
    g.fields_name = 'close'     #源数据取close/avg或其他
    g.short_duration = 20   #趋势和涨幅过滤周期
    
    #趋势策略的斜率上下限
    g.trend_up = 999
    g.trend_down = 0
    
    ##3-个股的损失控制部分
    g.lostcontrol = 2      #对持仓标的是否做卖出判断，0-不做，1-净损，2-回调，3-趋势止损，4-均线止损，5-RSI；6-MACD死叉止损；7-BOLL中轨止损；10-系统止损
    g.drop_line = 0.75      #针对损控1-止损，0.9/0.85、0.8;损控2-回调，0.8/0.75/0.7
    g.drop_ma_days = 20     #针对损控2/4/5/7/8，10-20-30
    g.drop_trend_dura = 0  #针对损控3-趋势止损，10-20
    g.drop_rsi_value = 50    #针对损控5的RSI阈值，35-40-45-50-55
    
#2 设置中间变量
def set_variables():
    #暂时未用，测试用全池
    g.stocknum = 5             #持仓数，0-代表全取
    g.poolnum = 0.3    #参考池数,小于1代表着取总池的百分比
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
    set_option("avoid_future_data", True)
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
    induslist =[]
    g.poollist=[]
    g.buylist =[]
    g.selllist=[]
    
    #止损控制
    if g.lostcontrol !=0:
        holdlist = list(context.portfolio.positions)
        g.selllist = lost_control(context, holdlist, today_date)
        log.info('%s损控-%s卖出:' % (today_date,g.lostcontrol))
        log.info(g.selllist)
        
        #此处用于每日筛选时，满仓无损跳过
        """
        if (len(holdlist)-len(g.selllist))>=g.stocknum:
            log.info('满仓无损，不用选后备')
            return
        """
    
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
    
    num1,num2,num3,num4=0,0,0,0    #用于过程追踪

    
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
    print('Step1,基准%s,原始%d只,四去后共%d只,构建耗时:%.1f 秒' % (g.index,num1,num2,end_time-start_time))
    
    #2，筛选出主策略周期内符合要求的候选标的
    start_time = time.time()
    if g.strategy == 'T':
        stocklist = get_trend_filter(context,stocklist,lastd_date,g.short_duration,'1d',g.trend_up,g.trend_down)
        
    num3 = len(stocklist)
    end_time = time.time()
    print('Step2,主策略%s,筛选出%d只标的,构建耗时:%.1f 秒' % (g.strategy,num3,end_time-start_time))
    
    if 'R' in g.pool_filter:
        start_time = time.time()
        stocklist = get_rise_filter(context,stocklist,g.index,g.short_duration,g.rise_uplimit)
        #stocklist = get_rise_filter(context,stocklist,g.mid_duration,3)
        #stocklist = get_rise_filter(context,stocklist,g.long_duration,4)
        num4 = len(stocklist)
        end_time = time.time()
        print('Step2-R,涨幅过滤出共%d只,构建耗时:%.1f 秒' % (len(stocklist),end_time-start_time))
    #根据预设的持仓数和池数进行标的的选择        
    if g.stocknum ==0 or len(stocklist) <= g.stocknum:
        g.poollist = stocklist
        g.buylist = stocklist
    else:
        
        if g.poolnum >=g.stocknum:
            g.poollist =stocklist[:g.poolnum]
        else:   #小于即比例关系
            g.poollist = stocklist[:int(g.poolnum*len(stocklist))]
        
        #g.poollist =stocklist
        g.buylist = stocklist[:g.stocknum]
        
    log.info('今日票池:')
    log.info(g.poollist)
    
    log.info('今日买信:')
    log.info(g.buylist)
    
    log.info('今日卖信:')
    log.info(g.selllist)
    
    outlist = [stockcode for stockcode in holdlist if not stockcode in g.poollist]
    log.info('今日待出:')
    log.info(outlist)
    
## 开盘时运行函数
def market_open(context):
    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    today_date = context.current_dt.date()
    current_data = get_current_data()
    
    #1，先卖，分为lost_control和定期换仓
    #止损卖信
    if (g.lostcontrol !=0) and (len(g.selllist) != 0):
        #log.info('大风来袭,全部撤退')   #for 全卖
        log.info('大风来袭,逐个撤退')   #for 单卖
        for stockcode in context.portfolio.positions:
            if current_data[stockcode].paused == True:
                continue
            #此处有两种控损模式，一种是第一次出现卖出即清仓，另一种则是逐个卖出
            if stockcode in g.selllist:
                sell_stock(context, stockcode,0)

    #0,判断是否换仓日
    if g.adjustpositions ==False:
        log.info('今天是持仓日')
        return
    if len(g.poollist) ==0:
        log.info('今天无信')
        return
    #1，持仓不在池的卖出
    #因为定期选出的票池数目不固定，全部清出后再重新分配资金买入，以便分析
    for stockcode in context.portfolio.positions:
        stockname = get_security_info(stockcode).display_name
        if current_data[stockcode].paused == True:
            continue
        if stockcode in g.poollist: #只取前stocknum的
            continue
        #非停不在买单则清仓
        sell_stock(context,stockcode,0)

    #2，判断持股数，平均分配买信
    if (len(context.portfolio.positions) >= g.stocknum):# and (context.portfolio.available_cash < 0.1*context.portfolio.total_value):
        return
    else:
        cash = context.portfolio.total_value/g.stocknum
        for stockcode in g.buylist:
            stockname = get_security_info(stockcode).display_name

            if current_data[stockcode].paused == True:
                continue
            #不光新买，旧仓也做平衡均分
            buy_stock(context,stockcode,cash)
            
            if (len(context.portfolio.positions) >= g.stocknum):
                return
    
## 收盘时运行函数
def market_close(context):
    log.info('函数运行时间(market_close):'+str(context.current_dt.time()))
            
## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))

    
"""
---------------------------------函数定义-主要策略-----------------------------------------------
"""
#趋势过滤，根据周期，上下限
#8.25 添加趋势通道中发现coef系数和股价大小有正相关，因此除以周期均值去除相关性
def get_trend_filter(context,stocklist,check_date,trend_duration,trend_unit,trend_up,trend_down):
    poollist =[]
    
    #取周期20/60的close
    #df_price = history(trend_duration,'1d',field=g.fields_name,security_list=stocklist,df=True,skip_paused=True,fq='pre')
    df_price = get_price(stocklist, count=trend_duration, end_date=check_date, frequency=trend_unit, fields=[g.fields_name])[g.fields_name]
    df_price = df_price.T
    df_price.fillna(method='ffill',inplace=True)
    #log.info(df_price)
    #获取回归系数，并递减排序
    df_price['coef'] = [fit_linear_nor(df_price.iloc[i][:]) for i in range(len(df_price))]
    df_price['mean'] = [df_price.iloc[i][:].mean() for i in range(len(df_price))]
    df_price['coef'] = df_price['coef']/df_price['mean'] #光coef系数和股价大小有很大关系，所以除以均值
    #x = np.arange(trend_duration)
    #df_price['coef'] = [linregress(x,df_price.iloc[i][:])[0] for i in range(len(df_price))]

    if (trend_up + trend_down >=0):
        df_price=df_price[(df_price.coef <trend_up)&(df_price.coef >trend_down)]   
        df_price.sort_values('coef',ascending=False,inplace=True)
    else:
        df_price=df_price[(df_price.coef >trend_down)&(df_price.coef <trend_up)]   
        df_price.sort_values('coef',ascending=True,inplace=True)
        
    #log.info(df_price.coef)
    coef_mean = df_price.coef.values.mean()
    poollist = df_price.index.tolist()
    #write_file('test.csv', str('%s,%s,%s\n' % (check_date,len(poollist),coef_mean)),append = True)
    return poollist
    
# 直线拟合--列表斜率
def fit_linear_nor(lis):
    model = LinearRegression()
    x_train = np.arange(0, len(lis)).reshape(-1, 1)
    y_train = np.array(lis).reshape(-1, 1)
    model.fit(x_train, y_train)
    m = model.coef_
    m1 = round(float(m), 3)
    return m1

#对持仓个股进行止损判断，是则列入卖信
def lost_control(context, stocklist, check_date):
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    poollist =[]
    
    if g.lostcontrol !=3:
        for stockcode in context.portfolio.positions:
            cost = context.portfolio.positions[stockcode].avg_cost
            price = context.portfolio.positions[stockcode].price
            value = context.portfolio.positions[stockcode].value
            intime= context.portfolio.positions[stockcode].init_time
            ret = price/cost
            duration=len(get_trade_days(intime,today_date))
            
            #1-静态止损，止损线可调，-0.1-0.2
            if g.lostcontrol ==1 or g.lostcontrol == 10:
                if ret < g.drop_line:
                    poollist.append(stockcode)
                    continue
            #2-动态止损，回落线可调，0.7-0.9
            elif g.lostcontrol ==2 or g.lostcontrol == 10:
                df_price = get_price(stockcode, count = g.drop_ma_days, end_date=lastd_date, frequency='daily', fields=['high','close'])
                high_max = df_price['high'].max()
                last_price = df_price['close'].values[-1]
                if last_price/high_max <g.drop_line:
                    poollist.append(stockcode)
                    continue
            #3-均线止损,均线可调，10-20-60-120
            elif g.lostcontrol ==4:
                MA_x = MA(stockcode, check_date=lastd_date, timeperiod=g.drop_ma_days)
                if price < MA_x[stockcode]:
                    poollist.append(stockcode)
                    continue
            #5-RSI止损，日期可调10-20-60，界线可调33-50-66
            elif g.lostcontrol ==5 or g.lostcontrol == 10:
                RSI_x = RSI(stockcode, check_date=lastd_date, N1=g.drop_ma_days)
                if RSI_x[stockcode] <g.drop_rsi_value:
                    poollist.append(stockcode)
                    continue
            #6-MACD死叉止损
            elif g.lostcontrol ==6:
                dif,dea,macd = MACD(stockcode, check_date=lastd_date, SHORT = 12, LONG = 26, MID = 9, unit='1d', include_now = True, fq_ref_date = None)
                if dif[stockcode] < dea[stockcode]:
                    poollist.append(stockcode)
                    continue
            #7-BOLL中轨止损
            elif g.lostcontrol ==7:
                upperband, middleband, lowerband = Bollinger_Bands(stockcode, check_date=lastd_date, timeperiod=g.drop_ma_days, nbdevup=2, nbdevdn=2)
                if price < middleband[stockcode]:
                    poollist.append(stockcode)
                    continue
            #8-SAR止损
            elif g.lostcontrol ==8:
                h = attribute_history(stockcode,120,'1d',['high','low','close'])
                h['sar'] = np.round(SAR(h['high'].values, h['low'].values, N=g.drop_ma_days),3)
                if h['close'][-1] <= h['sar'][-1]:
                    poollist.append(stockcode)
                    continue
    #3-趋势止损，趋势周期可调，0.5-2*trenddays
    else:
        #取10/20/60/120为测量周期
        df_price = history(g.drop_trend_dura,'1d',field='close',security_list=stocklist,df=True,skip_paused=True,fq='pre')
        df_price = df_price.T
        df_price.fillna(method='ffill',inplace=True)
        #获取回归系数，并递减排序
        df_price['coef'] = [fit_linear_nor(df_price.iloc[i][:]) for i in range(len(df_price))]
    
        df_price=df_price[df_price.coef <0]    
        poollist = df_price.index.tolist()    
        
    return poollist
"""
---------------------------------函数定义-次要过滤-----------------------------------------------
"""
#去掉周期内涨幅过大的
def get_rise_filter(context,stocklist,bench_index,duration,rise_level):
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    all_data = get_current_data()
    poollist =[]
    
    #根据基准指数涨幅动态调整
    if rise_level =='D':
        df_idx_price = get_price(bench_index,end_date=lastd_date,frequency='daily',fields=['close'],count=duration)
        idx_rise = df_idx_price.close[-1]/df_idx_price.close[0]
        if idx_rise <1:
            rise_level = 1
        else:
            rise_level = 1.2*idx_rise
            
    for stockcode in stocklist:
        df_price = get_price(stockcode,end_date=lastd_date,frequency='daily',fields=['close'],count=duration)
        if df_price.close.max()/df_price.close.min() >rise_level:
            continue
        poollist.append(stockcode)
    return poollist

#对输入的标的进行动态回调，
def get_drop_filter(context, stocklist, check_date):
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    all_data = get_current_data()
    poollist =[]
    
    for stockcode in stocklist:
        df_price = get_price(stockcode, count = g.drop_days, end_date=lastd_date, frequency='daily', fields=['high','close'])
        high_max = df_price['high'].max()
        last_price = df_price['close'].values[-1]
        if last_price/high_max >g.drop_line:
            poollist.append(stockcode)
            continue
        
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


"""
根据欧奈尔的统计，从20世纪50年代早期到2008年，表现最好的股票在其股票大涨前的平均RS值为87。
因此，欧奈尔认为：PRS值为80或90以上，是买入一只股票前的必要筛选条件。
https://xueqiu.com/1652627245/119664320
"""
        
