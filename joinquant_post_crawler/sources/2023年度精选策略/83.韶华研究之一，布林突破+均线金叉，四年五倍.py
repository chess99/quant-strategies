# 克隆自聚宽文章：https://www.joinquant.com/post/32129
# 标题：韶华研究之一，布林突破+均线金叉，四年五倍
# 作者：韶华不负

# 导入函数库
from jqdata import *
from six import BytesIO
from jqlib.technical_analysis import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000852.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')
    
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    
    g.buylist=[]
    g.selllist=[]
    
    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行--读取brain文件，载入list，供盘中使用
    run_daily(before_market_open, time='before_open')
      # 开盘时运行，开盘、14：05，14：55、收盘--上帝之手的运行部分
    run_daily(market_open, time='open')
    #run_daily(market_run, time ='9:45')
    #run_daily(market_run, time ='14:05')
    run_daily(market_close, time ='14:55')
      # 收盘后运行--总结
    run_daily(after_market_close, time='20:00')
      # 收盘后运行--小强之眼，逐日抓取符合BOLL通道要求的信号，并保存在eye文件中
    run_daily(after_close_eye, time='21:00')
      # 收盘后运行--小强之脑，读取eye文件，抓取之前5日信号，逐条判断金叉信号，分buy和focus,sell，并保存在brain文件中
    run_daily(after_close_brain, time='22:00')
    
## 开盘前运行函数     
def before_market_open(context):
    log.info(str('函数运行时间(before_market_open):'+str(context.current_dt.time())))
    today_date = context.current_dt.date()
    lastd_date = get_trade_days(end_date=today_date, count=2)[0]
    
    g.buylist=[]
    g.selllist=[]

    #第一步，先读入brain文件中昨日信息
    df_list = pd.read_csv(BytesIO(read_file('bug_brain.csv')))
    df_list['date'] = pd.to_datetime(df_list['date']).dt.date
    df_list= df_list[df_list['date'] == lastd_date]
    
    #纳入到四个全局列表中
    for i in range(len(df_list)):
        stockcode = df_list.iloc[i,2]
        if df_list.iloc[i,1] == 'buy':
            if stockcode not in g.buylist:
                g.buylist.append(stockcode)
        elif df_list.iloc[i,1] == 'sell':
            if stockcode not in g.selllist:
                g.selllist.append(stockcode)
    
## 开盘时运行函数
def market_open(context):
    log.info(str('函数运行时间(market_open):'+str(context.current_dt.time())))
    current_data = get_current_data()
    today_date = context.current_dt.date()
    
    ##先是卖的操作
    #1，9：30，根据卖出清单执行
    for key in g.selllist:
        cost = context.portfolio.positions[key].avg_cost
        price = context.portfolio.positions[key].price
        value = context.portfolio.positions[key].value
        intime= context.portfolio.positions[key].init_time
        ret = price/cost - 1
        duration=len(get_trade_days(intime,today_date))
        
        if current_data[key].paused != True:
            if order_target(key,0) != None:
                write_file('bug_log.csv', str('%s,开盘清仓,%s,周期:%s,盈利:%s\n' % (context.current_dt.time(),key,duration,ret)),append = True)
                print('%s开场清仓' % key)
    ##接着买的操作
    if context.portfolio.available_cash <10000: #钱不够了
        return
    
    #资金分配，一只全买，两只以上只买两只
    buy_num =len(g.buylist)
    all_cash = context.portfolio.available_cash
    if buy_num == 0:
        return
    elif buy_num == 1:
        cash_perstk = all_cash
    else:
        cash_perstk = all_cash/2

    for key in g.buylist:
        if context.portfolio.available_cash <10000: #钱不够了
            return
        if current_data[key].paused != True:
            if order_target_value(key,cash_perstk) != None:
                write_file('bug_log.csv', str('%s,开场买入,%s\n' % (context.current_dt.time(),key)),append = True)
                print('%s开场买入%s' % (key,cash_perstk))
    
    #清理buylist，以免盘中混乱        
    for key in g.buylist:
        if key in context.portfolio.positions:
            g.buylist.remove(key)

## 收盘时运行函数
def market_close(context):
    log.info('函数运行时间(market_close):'+str(context.current_dt.time()))
    
    today_date = context.current_dt.date()
    today_time = context.current_dt.time()
    lastd_date = get_trade_days(end_date=today_date, count=2)[0]
    current_data = get_current_data()
    
    buy_num = len(g.buylist)        
    ##先是卖的操作
    #2，根据持仓个股，实时判断盈利率/止损率是否需要清仓
    #盘中清仓条件适当放大，有波动
    for key in context.portfolio.positions:
        cost = context.portfolio.positions[key].avg_cost
        price = context.portfolio.positions[key].price
        value = context.portfolio.positions[key].value
        intime= context.portfolio.positions[key].init_time
        ret = price/cost - 1
        duration=len(get_trade_days(intime,today_date))
        #两种盈速计算方式：起价和低价
        rise_ratio = ret/duration
        
        #df_price = get_price(key, count = duration-1, end_date=lastd_date, frequency='daily', fields=['close'])
        #close_min = df_price['close'].min()
        #rise_ratio = (price/close_min-1)/duration
        
        #创板股提高盈速要求
        if key[0:3] == '688' or key[0:3] == '300':
            if today_date >= datetime.date(2020,9,1):
                rise_ratio = rise_ratio/2
                
        #BOLL蛰伏，优质筛选后可以不用考虑跌停控制
        """
        df_price = get_price(key, count = 3, end_date=lastd_date, frequency='daily', fields=['low_limit', 'high_limit', 'close']) #先老后新  
        if current_data[key].last_price < 1.01*current_data[key].low_limit:
            if order_target(key,0) != None:
                write_file('bug_log.csv', str('%s,收盘跌停卖出,%s,周期:%s,盈利:%s\n' % (today_time,key,duration,ret)),append = True)
                continue
        """
        if ret < -0.1:
            if order_target(key,0) != None:
                write_file('bug_log.csv', str('%s,收盘止损卖出,%s,周期:%s,盈利:%s\n' % (today_time,key,duration,ret)),append = True)
                continue
        elif ret > 0.5:
            if order_target(key,0) != None:
                write_file('bug_log.csv', str('%s,收盘超盈卖出,%s,周期:%s,盈利:%s\n' % (today_time,key,duration,ret)),append = True)
                continue
          
        if duration > 3 and ret < -0.05:
            if order_target(key,0) != None:
                write_file('bug_log.csv', str('%s,收盘长损卖出,%s,周期:%s,盈利:%s\n' % (today_time,key,duration,ret)),append = True)
                continue

        if rise_ratio < 0.015:
            if buy_num == 0:
                continue
            else:
                if duration < 6 and ret > -0.01:
                    continue
                if order_target(key,0) != None:
                    write_file('bug_log.csv', str('%s,收盘后慢处理,%s,周期:%s,盈利:%s\n' % (today_time,key,duration,ret)),append = True)
                    continue


    ##接着买的操作
    #2，先根据买入买入，再监测关注清单，实时判断个股是否站上MA5/10均线，站上即买
    if context.portfolio.available_cash <10000: #钱不够了
        return
    
    for key in g.buylist:
        if key in context.portfolio.positions or current_data[key].paused == True:
            continue
        all_cash = context.portfolio.available_cash
        if buy_num == 1:
            if current_data[key].paused != True:
                if order_target_value(key,all_cash) != None:
                    write_file('bug_log.csv', str('%s,收盘买入,%s\n' % (context.current_dt.time(),key)),append = True)
                    print('%s收盘买入%s' % (key,all_cash))
        else:
            if all_cash > 50000:
                if current_data[key].paused != True:
                    if order_target_value(key,50000) != None:
                        write_file('bug_log.csv', str('%s,收盘买入,%s\n' % (context.current_dt.time(),key)),append = True)
                        print('%s收盘买入%s' % (key,all_cash))
            else:
                if current_data[key].paused != True:
                    if order_target_value(key,all_cash) != None:
                        write_file('bug_log.csv', str('%s,收盘买入,%s\n' % (context.current_dt.time(),key)),append = True)
                        print('%s收盘买入%s' % (key,all_cash))
        
        if context.portfolio.available_cash <10000: #钱不够了
            return
                     
## 收盘后运行函数  
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #总结当日持仓情况
        #盘后遍历持仓，最后每日总结
    today_date = context.current_dt.date()
    
    for stk in context.portfolio.positions:
        cost = context.portfolio.positions[stk].avg_cost
        price = context.portfolio.positions[stk].price
        value = context.portfolio.positions[stk].value
        intime= context.portfolio.positions[stk].init_time
        ret = price/cost - 1
        duration=len(get_trade_days(intime,today_date))
        
        print('股票(%s)共有:%s,入时:%s,成本:%s,现价:%s,收益:%s' % (stk,value,intime,cost,price,ret))
        write_file('bug_log.csv', str('股票:%s,共有:%s,入时:%s,成本:%s,现价:%s,收益:%s\n' % (stk,value,intime,cost,price,ret)),append = True)
        
    print('总资产:%s,持仓:%s' %(context.portfolio.total_value,context.portfolio.positions_value))
    write_file('bug_log.csv', str('%s,总资产:%s,持仓:%s\n' %(context.current_dt.date(),context.portfolio.total_value,context.portfolio.positions_value)),append = True)

## 收盘后运行眼函数
def after_close_eye(context):
    log.info(str('函数运行时间(after_close_eye):'+str(context.current_dt.time())))
    #得到今天的日期和数据
    today_date = context.current_dt.date()
    back_date = get_trade_days(end_date=today_date, count=10)[0]
    rep_back_date = get_trade_days(end_date=today_date, count=60)[0]#eye文件读取的截止日
    all_data = get_current_data()
    
    #1，抓取所有股票列表，过滤ST，退市
    ##排除暂停、ST、退，得到三小特征票
    stockcode_list = list(get_all_securities(['stock']).index)
    stockcode_list = [stockcode for stockcode in stockcode_list if not all_data[stockcode].paused]
    stockcode_list = [stockcode for stockcode in stockcode_list if not all_data[stockcode].is_st]
    stockcode_list = [stockcode for stockcode in stockcode_list if'退' not in all_data[stockcode].name]
    s1_num = len(stockcode_list)
    
    #1，读入eye文件中指定日期段(当前日期往前10天)，用于表内排除
    df_waiting = pd.read_csv(BytesIO(read_file('bug_eye.csv')))
    df_waiting['date'] = pd.to_datetime(df_waiting['date']).dt.date
    df_waiting= df_waiting[(df_waiting['date'] <= today_date) & (df_waiting['date'] >= back_date)]
    wait_list = df_waiting['code'].values.tolist()

    s2_num = 0
    s3_num = 0
    s4_num = 0
    #2，循环小强股，依次过滤仓内的、次新的，十天前已在eye文件中出现的，非boll通道相关特征（狭窄+突破上轨）
    for stockcode in stockcode_list:
        #在仓内、三年内、表内去除
        if stockcode in context.portfolio.positions:
            continue
        if (today_date - get_security_info(stockcode).start_date).days <= 600:
            continue
        s2_num = s2_num+1
        if stockcode in wait_list:
            continue
        
        #排除非BOLL通道收窄+未突破上轨
        upperband, middleband, lowerband = Bollinger_Bands(stockcode, check_date=today_date, timeperiod=60, nbdevup=2, nbdevdn=2)
        if (upperband[stockcode] - lowerband[stockcode])/middleband[stockcode] > 0.1:
            continue
        if all_data[stockcode].last_price < upperband[stockcode]:
            continue
        s3_num = s3_num+1
        
        Trix_signal,MACD_signal,EMV_signal,KD_signal= Technical_signal(stockcode,today_date)
        if Trix_signal ==1 or MACD_signal ==1:
            print('%s中标' % stockcode)
            s4_num = s4_num+1
            
            df_value = get_valuation(stockcode, end_date=today_date, count=1, fields=['circulating_market_cap', 'pe_ratio','pb_ratio'])
            q_f10=query(finance.STK_SHAREHOLDER_FLOATING_TOP10).filter(finance.STK_SHAREHOLDER_FLOATING_TOP10.code==stockcode,finance.STK_SHAREHOLDER_FLOATING_TOP10.pub_date>rep_back_date).limit(10)
            df_f10=finance.run_query(q_f10)
            sum_f10 = df_f10['share_ratio'].sum()
            CYF_code = CYF(stockcode, check_date=today_date, N = 10, unit = '1d', include_now = True)
            write_file('bug_eye.csv',str('%s,%s,%s,%s,%s,%s,%s\n' % (today_date,stockcode,df_value.iloc[0,2],df_value.iloc[0,3],df_value.iloc[0,4],CYF_code[stockcode],sum_f10)),append = True)
    
    print('原始:%s,去新:%s,龟头:%s,金叉:%s' % (s1_num,s2_num,s3_num,s4_num))
    
## 收盘后运行脑函数
def after_close_brain(context):
    log.info(str('函数运行时间(after_close_brain):'+str(context.current_dt.time())))
    #预设全局数据,观察周期为往前追溯10天
    today_date = context.current_dt.date()
    all_data = get_current_data()
    benchcode_titan = '000300.XSHG'
    benchcode_bug = '000852.XSHG'
    g.buylist = []
    g.selllist = []
    
    #1，读取eye文件，得到今日信号
    df_waiting = pd.read_csv(BytesIO(read_file('bug_eye.csv')))
    df_waiting['date'] = pd.to_datetime(df_waiting['date']).dt.date
    df_waiting = df_waiting[(df_waiting['date'] == today_date)]
    df_waiting = df_waiting.sort_values(['cir_m'], ascending = True) #按市值大小递减排序，以便多个信号时按市值取需
    
    #判断大小基准的30日涨幅动量，然后用1000-300，为正表示小>大，为负表示小<大
    #计算大小基准的当日涨幅
    df_titan_price = get_price(benchcode_titan, count = 30, end_date=today_date, frequency='daily', fields=['close'])
    df_bug_price = get_price(benchcode_bug, count = 30, end_date=today_date, frequency='daily', fields=['close'])
    
    rise_titan = (df_titan_price['close'].values[-1] - df_titan_price['close'].values[0])/df_titan_price['close'].values[0]
    rise_bug = (df_bug_price['close'].values[-1] - df_bug_price['close'].values[0])/df_bug_price['close'].values[0]
    rise_gap = rise_bug - rise_titan

    rise_titan_last = (df_titan_price['close'].values[-1] - df_titan_price['close'].values[-2])/df_titan_price['close'].values[-2]
    rise_bug_last = (df_bug_price['close'].values[-1] - df_bug_price['close'].values[-2])/df_bug_price['close'].values[-2]
    rise_gap_last = rise_bug_last - rise_titan_last
    
    #根据小盘指数30日状态，分阶段分因子提取出各阶段买信号
    for i in range(len(df_waiting)):
        stockcode = df_waiting.iloc[i,1]
        cir_m = df_waiting.iloc[i,2]
        last_price = all_data[stockcode].last_price
        pe_ratio = df_waiting.iloc[i,3]
        cyf = df_waiting.iloc[i,5]
        f10 = df_waiting.iloc[i,6]
        
        if stockcode in context.portfolio.positions:
            continue
        
        #通用过滤，PE太大，或人气太热，或股价过低(资源股，近ST)去除
        if pe_ratio >200 or cyf >66 or last_price < 3:
            continue
        
        if rise_bug < -0.05:
            if rise_bug_last > 0:
                if cir_m >56 and pe_ratio >20 and cyf >20:
                    g.buylist.append(stockcode)
                    write_file('bug_brain.csv',str('%s,buy,%s\n' % (today_date,stockcode)),append = True) #记录在任务清单中，方便明日盘前载入list执行
                    write_file('bug_log.csv', str('%s,买入信号,%s,%s,%s,%s,%s\n' % (today_date,stockcode,cir_m,pe_ratio,cyf,f10)),append = True)
                    continue
            else:
                continue
        elif rise_bug <=0:
            if cir_m <160 and cyf >24 and f10 >45:
                if pe_ratio >0 and pe_ratio <22:
                    g.buylist.append(stockcode)
                    write_file('bug_brain.csv',str('%s,buy,%s\n' % (today_date,stockcode)),append = True) #记录在任务清单中，方便明日盘前载入list执行
                    write_file('bug_log.csv', str('%s,买入信号,%s,%s,%s,%s,%s\n' % (today_date,stockcode,cir_m,pe_ratio,cyf,f10)),append = True)
                    continue
            else:
                continue
        elif rise_bug <= 0.07:
            if rise_gap > -0.01:
                if cyf >31 and f10 >22:
                    if pe_ratio >0 and pe_ratio <44:
                        g.buylist.append(stockcode)
                        write_file('bug_brain.csv',str('%s,buy,%s\n' % (today_date,stockcode)),append = True) #记录在任务清单中，方便明日盘前载入list执行
                        write_file('bug_log.csv', str('%s,买入信号,%s,%s,%s,%s,%s\n' % (today_date,stockcode,cir_m,pe_ratio,cyf,f10)),append = True)
                        continue
            else:
                continue
        else:
            if cir_m <170 and last_price >9 and cyf>24:
                g.buylist.append(stockcode)
                write_file('bug_brain.csv',str('%s,buy,%s\n' % (today_date,stockcode)),append = True) #记录在任务清单中，方便明日盘前载入list执行
                write_file('bug_log.csv', str('%s,买入信号,%s,%s,%s,%s,%s\n' % (today_date,stockcode,cir_m,pe_ratio,cyf,f10)),append = True)
                continue
    
    #判断仓内各股的卖信号，止损/止盈/回撤止损/盈速止盈
    buy_num = len(g.buylist)
    for stockcode in context.portfolio.positions:
        cost = context.portfolio.positions[stockcode].avg_cost
        price = context.portfolio.positions[stockcode].price
        value = context.portfolio.positions[stockcode].value
        intime= context.portfolio.positions[stockcode].init_time
        ret = price/cost - 1
        duration=len(get_trade_days(intime,today_date))
        #两种盈速计算方式：起价和低价
        rise_ratio = ret/duration
        
        #df_price = get_price(stockcode, count = duration, end_date=today_date, frequency='daily', fields=['close'])
        #close_min = df_price['close'].min()
        #rise_ratio = (price/close_min-1)/duration

        #创板股提高盈速要求
        if (stockcode[0:3] == '688' or stockcode[0:3] == '300') and today_date >= datetime.date(2020,9,1):
            rise_ratio = rise_ratio/2

        #今日跌停即加入卖出清单,然后止盈止损，盈速判断
        #BOLL蛰伏，优质筛选后可以不用考虑跌停控制
        """
        df_price = get_price(stockcode, count = 1, end_date=today_date, frequency='daily', fields=['low_limit', 'high_limit', 'close']) #先老后新
        if all_data[stockcode].paused != True and df_price.iloc[-1,2] <= df_price.iloc[-1,0]:
            #g.selllist.append(stockcode)
            write_file('bug_brain.csv',str('%s,sell,%s\n' % (today_date,stockcode)),append = True) #记录在任务清单中，方便明日盘前载入四大list执行
            write_file('bug_log.csv', str('%s,跌停信号,%s,周期:%s,盈利:%s\n' % (today_date,stockcode,duration,ret)),append = True)
            continue
        """
        
        if ret < -0.1:
            #g.selllist.append(stockcode)
            write_file('bug_brain.csv',str('%s,sell,%s\n' % (today_date,stockcode)),append = True) #记录在任务清单中，方便明日盘前载入四大list执行
            write_file('bug_log.csv', str('%s,止损信号,%s,周期:%s,盈利:%s\n' % (today_date,stockcode,duration,ret)),append = True)
            continue
        elif ret > 0.5:
            #g.selllist.append(stockcode)
            write_file('bug_brain.csv',str('%s,sell,%s\n' % (today_date,stockcode)),append = True) #记录在任务清单中，方便明日盘前载入四大list执行
            write_file('bug_log.csv', str('%s,超盈信号,%s,周期:%s,盈利:%s\n' % (today_date,stockcode,duration,ret)),append = True)
            continue
        
        if duration > 3:
            if ret < -0.05:
                #g.selllist.append(stockcode)
                write_file('bug_brain.csv',str('%s,sell,%s\n' % (today_date,stockcode)),append = True) #记录在任务清单中，方便明日盘前载入四大list执行
                write_file('bug_log.csv', str('%s,长损信号,%s,周期:%s,盈利:%s\n' % (today_date,stockcode,duration,ret)),append = True)
                continue
            elif ret < -0.03:
                Trix_signal,MACD_signal,EMV_signal,KD_signal= Technical_signal(stockcode,today_date)
                if buy_num == 0:
                    continue
                
                if Trix_signal == -1 or MACD_signal == -1:
                    #g.selllist.append(stockcode)
                    write_file('bug_brain.csv',str('%s,sell,%s\n' % (today_date,stockcode)),append = True) #记录在任务清单中，方便明日盘前载入四大list执行
                    write_file('bug_log.csv', str('%s,死叉信号,%s,周期:%s,盈利:%s\n' % (today_date,stockcode,duration,ret)),append = True)
                    continue                    
            else:
                df_price = get_price(stockcode, count = 10, end_date=today_date, frequency='daily', fields=['close'])
                close_max = df_price['close'].max()
                last_price = df_price['close'].values[-1]

                if last_price/close_max < 0.9:
                    if buy_num == 0 and ret < 0.2:  #没有新信号，不杀高，有盈利空间继续拿着
                        continue
                    
                    write_file('bug_brain.csv',str('%s,sell,%s\n' % (today_date,stockcode)),append = True) #记录在任务清单中，方便明日盘前载入四大list执行
                    write_file('bug_log.csv', str('%s,跟损信号,%s,周期:%s,盈利:%s\n' % (today_date,stockcode,duration,ret)),append = True)
                    continue

                df_value = get_valuation(stockcode, count = 10, end_date=today_date, fields=['turnover_ratio'])
                turnover_mean = df_value['turnover_ratio'].mean()
                turnover_last = df_value['turnover_ratio'].values[0]
                if  turnover_last > 3 and (turnover_last > 2.5*turnover_mean):
                    if ret < 0.05:  #抬高高换的触发门槛
                        continue
                        
                    write_file('bug_brain.csv',str('%s,sell,%s\n' % (today_date,stockcode)),append = True) #记录在任务清单中，方便明日盘前载入四大list执行
                    write_file('bug_log.csv', str('%s,高换信号,%s,周期:%s,盈利:%s\n' % (today_date,stockcode,duration,ret)),append = True)
                    continue

        if rise_ratio < 0.015:
            if buy_num == 0:
                continue
            else:
                if duration < 2 and ret > -0.04:
                    continue
                if duration < 3 and ret > -0.02:
                    continue
                if duration < 6 and ret > -0.01:
                    continue
                #g.selllist.append(stockcode)
                write_file('bug_brain.csv',str('%s,sell,%s\n' % (today_date,stockcode)),append = True) #记录在任务清单中，方便明日盘前载入四大list执行
                write_file('bug_log.csv', str('%s,后慢信号,%s,周期:%s,盈利:%s\n' % (today_date,stockcode,duration,ret)),append = True)
    
#技术面交叉信号
def Technical_signal(stockcode,today_date):
    oneday=datetime.timedelta(days=1) 
    yeday_date = today_date - oneday
    Trix_signal = 0
    MACD_signal = 0
    EMV_signal = 0
    KD_signal = 0
    
    TRIX_t,MATRIX_t = TRIX(stockcode,check_date=today_date, N = 12, M = 9)
    TRIX_y,MATRIX_y = TRIX(stockcode,check_date=yeday_date, N = 12, M = 9)
    TrixDelta_t = MATRIX_t[stockcode] - TRIX_t[stockcode]
    TrixDelta_y = MATRIX_y[stockcode] - TRIX_y[stockcode]
    
    if (TRIX_t[stockcode] <= MATRIX_t[stockcode]) and (TrixDelta_t < TrixDelta_y) and (TrixDelta_t <= -0.03):
        Trix_signal = 1 #金叉将成
    elif (TRIX_t[stockcode] >= MATRIX_t[stockcode]) and (TRIX_y[stockcode] <= MATRIX_y[stockcode]):
        Trix_signal = 1 #金叉已成
    elif (TRIX_t[stockcode] <= MATRIX_t[stockcode]) and (TRIX_y[stockcode] >= MATRIX_y[stockcode]):
        Trix_signal = -1 ##死叉已成
    
    DIF_t,DEA_t,MACD_t = MACD(stockcode,check_date=today_date, SHORT = 12, LONG = 26, MID = 9)
    DIF_y,DEA_y,MACD_y = MACD(stockcode,check_date=yeday_date, SHORT = 12, LONG = 26, MID = 9)
    MacdDelta_t = DEA_t[stockcode] - DIF_t[stockcode]
    MacdDelta_y = DEA_y[stockcode] - DIF_y[stockcode]
    
    if (DIF_t[stockcode] <= DEA_t[stockcode]) and (MacdDelta_t < MacdDelta_y) and (MacdDelta_t <= 0.05):
        MACD_signal = 1 #金叉将成
    elif (DIF_t[stockcode] >= DEA_t[stockcode]) and (DIF_y[stockcode] <= DEA_y[stockcode]):
        MACD_signal = 1 #金叉已成
    elif (DIF_t[stockcode] <= DEA_t[stockcode]) and (DIF_y[stockcode] >= DEA_y[stockcode]):
        MACD_signal = -1 #死叉已成
        
    EMV_t,MAEMV_t = EMV(stockcode,check_date=today_date, N = 14, M = 9)
    EMV_y,MAEMV_y = EMV(stockcode,check_date=yeday_date, N = 14, M = 9)
    
    #EMV和KD信号太频繁，只算已成
    if (EMV_t[stockcode] >= MAEMV_t[stockcode]) and (EMV_y[stockcode] <= MAEMV_y[stockcode]):
        EMV_signal = 1 #金叉已成
    elif (EMV_t[stockcode] <= MAEMV_t[stockcode]) and (EMV_y[stockcode] >= MAEMV_y[stockcode]):
        EMV_signal = -1 #死叉已成
        
    K_t, D_t = KD(stockcode, check_date = today_date, N = 9, M1 = 3, M2 = 3)
    K_y, D_y = KD(stockcode, check_date = yeday_date, N = 9, M1 = 3, M2 = 3)
    
    if (K_t[stockcode] >= D_t[stockcode]) and (K_y[stockcode] <= D_y[stockcode]):
        KD_signal = 1 #金叉已成
    elif (K_t[stockcode] <= D_t[stockcode]) and (K_y[stockcode] >= D_y[stockcode]):
        KD_signal = -1 #死叉已成
        
    return Trix_signal,MACD_signal,EMV_signal,KD_signal
