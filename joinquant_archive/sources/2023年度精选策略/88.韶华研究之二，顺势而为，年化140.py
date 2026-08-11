# 克隆自聚宽文章：https://www.joinquant.com/post/32130
# 标题：韶华研究之二，顺势而为，年化140
# 作者：韶华不负

# 导入函数库
from jqdata import *
from six import BytesIO
from jqlib.technical_analysis import *
import pandas as pd
import os

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    g.benchmark = '000300.XSHG'
    set_benchmark(g.benchmark)

    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    
    #18-20年数据回测后所得行业白名单
    g.indus_list = ['801010','801080','801120','801140','801150','801210','801710','801750','801760','801780','801790','801880']
    g.buylist=[]
    g.selllist=[]
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
      # 开盘时运行
    run_daily(market_open, time='open', reference_security='000300.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')
    ##盘后运行-CCI brain
    run_daily(after_close_brain, time='21:00')
    
## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    today_date = context.current_dt.date()
    lastd_date = get_trade_days(end_date=today_date, count=2)[0]
    
    g.buylist=[]
    g.selllist=[]

    #第一步，先读入brain文件中昨日信息
    df_list = pd.read_csv(BytesIO(read_file('follow_brain.csv')))
    df_list['date'] = pd.to_datetime(df_list['date']).dt.date
    df_list= df_list[df_list['date'] == lastd_date]
    df_list= df_list.sort_values(['data'], ascending = False) #按'data'-波动率降序排序
    
    #纳入到四个全局列表中
    for i in range(len(df_list)):
        stockcode = df_list['code'].values[i]
        if df_list['signal'].values[i] == 'buy':
            if stockcode not in g.buylist:
                g.buylist.append(stockcode)
        elif df_list['signal'].values[i] == 'sell':
            if stockcode not in g.selllist:
                g.selllist.append(stockcode)

## 开盘时运行函数
def market_open(context):
    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    current_data = get_current_data()
    today_date = context.current_dt.date()
    lastd_date = get_trade_days(end_date=today_date, count=2)[0]
    
    ##先是卖的操作，止盈，止损，卖信
    for stockcode in context.portfolio.positions:
        if current_data[stockcode].paused == True:
            continue
        cost = context.portfolio.positions[stockcode].avg_cost
        price = current_data[stockcode].last_price
        value = context.portfolio.positions[stockcode].value
        intime= context.portfolio.positions[stockcode].init_time
        ret = price/cost - 1
        duration=len(get_trade_days(intime,today_date))
        rise_ratio = ret/duration
        
        #创板股提高盈速要求
        if (stockcode[0:3] == '688' or stockcode[0:3] == '300') and today_date >= datetime.date(2020,9,1):
            rise_ratio = rise_ratio/2
            ret = ret/2

        if ret > 1:
            if order_target(stockcode,0) != None:
                write_file('follow_log.csv', str('%s,开盘止盈,%s,周期:%s,盈利:%s\n' % (context.current_dt.time(),stockcode,duration,ret)),append = True)
                continue
        if stockcode in g.selllist:
            if order_target(stockcode,0) != None:
                write_file('follow_log.csv', str('%s,开盘清仓,%s,周期:%s,盈利:%s\n' % (context.current_dt.time(),stockcode,duration,ret)),append = True)
                continue

    ##接着买的操作
    if context.portfolio.available_cash <10000: #钱不够了
        return
    
    #分配资金，全仓只持两只
    if context.portfolio.available_cash == context.portfolio.total_value:
        cash_perstk = context.portfolio.available_cash/2
    else:
        cash_perstk = context.portfolio.available_cash
            
    for stockcode in g.buylist:
        if current_data[stockcode].paused == True:
            continue
        if context.portfolio.available_cash <10000: #钱不够了
            continue
        if current_data[stockcode].paused != True:
            if order_target_value(stockcode,cash_perstk) != None:
                write_file('follow_log.csv', str('%s,开盘买入,%s,%s\n' % (context.current_dt.time(),stockcode,current_data[stockcode].last_price)),append = True)
                
## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    today_date = context.current_dt.date()
    
    for stk in context.portfolio.positions:
        cost = context.portfolio.positions[stk].avg_cost
        price = context.portfolio.positions[stk].price
        value = context.portfolio.positions[stk].value
        intime= context.portfolio.positions[stk].init_time
        ret = price/cost - 1
        duration=len(get_trade_days(intime,today_date))
        
        print('股票(%s)共有:%s,入时:%s,周期:%s,成本:%s,现价:%s,收益:%s' % (stk,value,intime,duration,cost,price,ret))
        write_file('follow_log.csv', str('股票:%s,共有:%s,入时:%s,周期:%s,成本:%s,现价:%s,收益:%s\n' % (stk,value,intime,duration,cost,price,ret)),append = True)
        
    print('总资产:%s,持仓:%s' %(context.portfolio.total_value,context.portfolio.positions_value))
    write_file('follow_log.csv', str('%s,总资产:%s,持仓:%s\n' %(context.current_dt.date(),context.portfolio.total_value,context.portfolio.positions_value)),append = True)
    
## 收盘后运行函数,判断买卖信号
def after_close_brain(context):
    log.info(str('函数运行时间(after_close_brain):'+str(context.current_dt.time())))
    ##0，预设阶段
    #得到今天的日期和数据
    today_date = context.current_dt.date()
    lastd_date = get_trade_days(end_date=today_date, count=2)[0]
    all_data = get_current_data()
    
    ##1，收集bench指数的股票列表，三除，按市值排序
    stocklist = get_index_stocks(g.benchmark)
    stocklist = [stockcode for stockcode in stocklist if not all_data[stockcode].paused]
    stocklist = [stockcode for stockcode in stocklist if not all_data[stockcode].is_st]
    stocklist = [stockcode for stockcode in stocklist if'退' not in all_data[stockcode].name]
    
    df_bench_price = get_price(g.benchmark, count = 2, end_date=today_date, frequency='daily', fields=['close'])
    rise_bench_today = (df_bench_price['close'].values[-1] - df_bench_price['close'].values[-2])/df_bench_price['close'].values[-2]
    
    ##2，循环遍历指数列表，去除百日次新，通用条件过滤，行业条件过滤后形成买入信号，直接记录到brain和log中
    for stockcode in stocklist:
        if (today_date - get_security_info(stockcode).start_date).days <= 100:
            continue
        stock_name = get_security_info(stockcode).display_name
        dict_indus = get_industry(stockcode, date=None)
        indus_code = dict_indus[stockcode]['sw_l1']['industry_code']
        #不在行业白名单中的去除
        if indus_code not in g.indus_list:
            continue
        #在舱内的去除
        if stockcode in context.portfolio.positions:
            continue
        CCI_today = CCI(stockcode, today_date, N=14, unit = '1d', include_now = True, fq_ref_date = None)
        CCI_lastd = CCI(stockcode, lastd_date, N=14, unit = '1d', include_now = True, fq_ref_date = None)
        cci_value = CCI_today[stockcode]
        if CCI_today[stockcode] >= -100 or CCI_lastd[stockcode] <= -100:    #去除CCI非下探-100的形态
            continue
        
        df_price = get_price(stockcode,count=100,end_date=today_date, frequency='daily', fields=['high','low','close']) #先老后新
        df_value = get_valuation(stockcode, count=1, end_date=today_date, fields=['circulating_market_cap','pe_ratio','pb_ratio','turnover_ratio'])#先新后老
        price_T = df_price['close'].values[-1]
        rise_100 = price_T/df_price['close'].values[0]
        volatility_100 = df_price['high'].values.max()/df_price['low'].values.min()
        cir_m = df_value['circulating_market_cap'].values[0]
        pe_ratio = df_value['pe_ratio'].values[0]
        pb_ratio = df_value['pb_ratio'].values[0]
        
        #通用过滤条件--个股基本面
        if price_T >=300:   #价格过高去除
            continue
        if pe_ratio <0 or pb_ratio<1:   #亏损和破净的去除
            continue
        
        #通用过滤条件--个股形态面
        if rise_100 <0.73:
            continue
        
        df_valutaion=finance.run_query(query(finance.SW1_DAILY_PRICE.date,finance.SW1_DAILY_PRICE.code,finance.SW1_DAILY_PRICE.high,finance.SW1_DAILY_PRICE.low
        ).filter(finance.SW1_DAILY_PRICE.code==indus_code,finance.SW1_DAILY_PRICE.date <= today_date).order_by(finance.SW1_DAILY_PRICE.date.desc()).limit(100))
        
        volat_indus_100 = df_valutaion['high'].values.max()/df_valutaion['low'].values.min()
        volat_StockvsIndus = volatility_100/volat_indus_100
        if volat_indus_100 <1.2 or volat_StockvsIndus <1.1: #行业波澜不兴，和不突出于行业均值的去除
            continue
        
        CYF_code = CYF(stockcode, check_date=today_date, N = 10, unit = '1d', include_now = True)
        popularity = CYF_code[stockcode]
        #行业过滤条件
        if indus_code == '801010':
            if volat_StockvsIndus <1.3:
                continue
            if popularity <50 or popularity >82:
                continue
        elif indus_code == '801080':
            if volat_StockvsIndus <1.42:
                continue
            if popularity <50 or popularity >82:
                continue
        elif indus_code == '801120':
            if volatility_100 <1.99:
                continue
        elif indus_code == '801140':
            if volat_StockvsIndus <1.23:
                continue
            if popularity <50 or popularity >82:
                continue
        elif indus_code == '801150':
            if volat_StockvsIndus <1.28 or volat_StockvsIndus >1.6:
                continue
            if popularity <50 or popularity >82:
                continue
        elif indus_code == '801210':
            if volatility_100 <1.53:
                continue
        elif indus_code == '801710':
            if volat_StockvsIndus <1.2:
                continue
            if popularity <40 or popularity >70:
                continue
        elif indus_code == '801750':
            if volatility_100 <1.68 or volatility_100 >2:
                continue
            if popularity <58 or popularity >86:
                continue
        elif indus_code == '801760':
            if volat_StockvsIndus <1.27:
                continue
            if popularity <40 or popularity >70:
                continue
        elif indus_code == '801780':
            if volatility_100 <1.5 or volatility_100 >1.8:
                continue
            if popularity >93:
                continue
        elif indus_code == '801790':
            if volatility_100 <1.88 or volatility_100 >2.25:
                continue
            if popularity >93:
                continue
        elif indus_code == '801880':
            if volatility_100 <1.66 or volatility_100 >2:
                continue
        
        #多番过滤后的信号即为买入信号，记录到文件中
        write_file('follow_brain.csv', str('%s,buy,%s,%s\n' % (today_date,stockcode,volatility_100)),append = True)
        write_file('follow_log.csv', str('%s,买入信号,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' % (today_date,stockcode,stock_name,indus_code,price_T,rise_100,volatility_100,volat_indus_100,volat_StockvsIndus,
        cir_m,pe_ratio,pb_ratio,popularity)),append = True)
        
    #大盘暴跌卧倒
    if rise_bench_today < -0.07:
        return
    ##3，遍历持仓，给出卖信号
    for stockcode in context.portfolio.positions:
        cost = context.portfolio.positions[stockcode].avg_cost
        price = context.portfolio.positions[stockcode].price
        value = context.portfolio.positions[stockcode].value
        intime= context.portfolio.positions[stockcode].init_time
        ret = price/cost - 1
        duration=len(get_trade_days(intime,today_date))
        rise_ratio = ret/duration
    
        #创板股提高盈速要求
        if (stockcode[0:3] == '688' or stockcode[0:3] == '300') and today_date >= datetime.date(2020,9,1):
            rise_ratio = rise_ratio/2
            ret = ret/2

        if ret < -0.1:
            write_file('follow_brain.csv',str('%s,sell,%s,ZS\n' % (today_date,stockcode)),append = True) #记录在任务清单中，方便明日盘前载入四大list执行
            write_file('follow_log.csv', str('%s,止损信号,%s,周期:%s,盈利:%s\n' % (today_date,stockcode,duration,ret)),append = True)
            continue
        elif ret > 1:
            write_file('follow_brain.csv',str('%s,sell,%s,ZY\n' % (today_date,stockcode)),append = True) #记录在任务清单中，方便明日盘前载入四大list执行
            write_file('follow_log.csv', str('%s,止盈信号,%s,周期:%s,盈利:%s\n' % (today_date,stockcode,duration,ret)),append = True)
            continue
        
        CCI_today = CCI(stockcode, today_date, N=14, unit = '1d', include_now = True, fq_ref_date = None)
        CCI_lastd = CCI(stockcode, lastd_date, N=14, unit = '1d', include_now = True, fq_ref_date = None)
        cci_value = CCI_today[stockcode]
        if CCI_today[stockcode] > 100:
            if rise_ratio >0.025:    #上升态势豁免
                continue
            else:
                write_file('follow_brain.csv',str('%s,sell,%s,CCI\n' % (today_date,stockcode)),append = True) #记录在任务清单中，方便明日盘前载入四大list执行
                write_file('follow_log.csv', str('%s,势高信号,%s,周期:%s,盈利:%s\n' % (today_date,stockcode,duration,ret)),append = True)
                continue
            
        df_price = get_price(stockcode, count = 10, end_date=today_date, frequency='daily', fields=['close'])
        close_max = df_price['close'].max()
        last_price = df_price['close'].values[-1]
        if last_price/close_max < 0.9 and duration >8:
            write_file('follow_brain.csv',str('%s,sell,%s,DS\n' % (today_date,stockcode)),append = True) #记录在任务清单中，方便明日盘前载入四大list执行
            write_file('follow_log.csv', str('%s,动损信号,%s,周期:%s,盈利:%s\n' % (today_date,stockcode,duration,ret)),append = True)
            continue
        
        if duration >=5 and ret <0:
            if df_price['close'].values[-1]> df_price['close'].values[-2]:  #当天收阳过
                continue
            write_file('follow_brain.csv',str('%s,sell,%s,DK\n' % (today_date,stockcode)),append = True) #记录在任务清单中，方便明日盘前载入四大list执行
            write_file('follow_log.csv', str('%s,短亏信号,%s,周期:%s,盈利:%s\n' % (today_date,stockcode,duration,ret)),append = True)
            continue
        
        if duration >=10 and rise_ratio <0.0085:
            write_file('follow_brain.csv',str('%s,sell,%s,DQ\n' % (today_date,stockcode)),append = True) #记录在任务清单中，方便明日盘前载入四大list执行
            write_file('follow_log.csv', str('%s,到期信号,%s,周期:%s,盈利:%s\n' % (today_date,stockcode,duration,ret)),append = True)
            continue
        
    return    

    

        
    
    
