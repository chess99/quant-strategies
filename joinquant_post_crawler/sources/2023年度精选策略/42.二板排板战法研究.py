# 克隆自聚宽文章：https://www.joinquant.com/post/34011
# 标题：二板排板战法研究
# 作者：游资小码哥

# 导入函数库
from jqdata import *

help_stock = []
# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')
    # g 内置全局变量
    g.my_security = '510300.XSHG'
    set_universe([g.my_security])

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
      # 开盘时运行
    run_daily(market_run, time='every_bar', reference_security='000300.XSHG')
    #run_daily(market_run_sell, time='every_bar', reference_security='000300.XSHG')

      # 收盘后运行before_open
    #run_daily(before_market_open, time='after_close', reference_security='000300.XSHG')

buy_bool = False
## 开盘时运行函数  
def market_run(context):
    time_buy = context.current_dt.strftime('%H:%M:%S')
    aday = datetime.datetime.strptime('10:30:00', '%H:%M:%S').strftime('%H:%M:%S')
    now = context.current_dt
    zeroToday = now - datetime.timedelta(hours=now.hour, minutes=now.minute, seconds=now.second,microseconds=now.microsecond)
    lastToday = zeroToday + datetime.timedelta(hours=9, minutes=31, seconds=00)
    if len(help_stock) > 0:
        for stock in help_stock:
            #log.info("当前时间 %s" % (context.current_dt))
            #log.info("股票 %s 的最新价: %f" % (stock, get_current_data()[stock].last_price))
            cash = context.portfolio.available_cash
            #print(cash)
            current_price = get_current_data()[stock].last_price
            day_open_price = get_current_data()[stock].day_open
            day_high_limit = get_current_data()[stock].high_limit 
            pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
            df_panel = get_price(stock, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'high', 'close','low', 'high_limit','money','pre_close'])
            pre_high = df_panel['high'].values
            pre_close = df_panel['close'].values
            df_panel_all = get_price(stock, start_date=lastToday, end_date=context.current_dt, frequency='minute', fields=['high','low','close','high_limit','money'])
            df_min_low_all = df_panel_all.loc[:,"close"].min()
            df_max_high_all = df_panel_all.loc[:,"close"].max()
            count_max = (df_panel_all.loc[:,'close'] == df_panel_all.loc[:,'high_limit']).sum()

            if cash > 5000 and count_max > 3:
                if  current_price > pre_close * 1.07 and current_price < day_high_limit and day_open_price < day_high_limit * 0.98:
                    #open_cash = cash / len(help_stock)
                    print(stock+"1.买入金额"+str(cash))
                    order_value(stock, cash)
                    help_stock.remove(stock)
                    
    time_sell = context.current_dt.strftime('%H:%M:%S')
    cday = datetime.datetime.strptime('14:40:00', '%H:%M:%S').strftime('%H:%M:%S')
    dday = datetime.datetime.strptime('10:30:00', '%H:%M:%S').strftime('%H:%M:%S')
    now = context.current_dt
    zeroToday = now - datetime.timedelta(hours=now.hour, minutes=now.minute, seconds=now.second,microseconds=now.microsecond)
    lastToday = zeroToday + datetime.timedelta(hours=9, minutes=30, seconds=00)
    if time_sell > cday:
        stock_owner = context.portfolio.positions
        if len(stock_owner) > 0:
            for stock_two in stock_owner:
                current_price_list = get_ticks(stock_two,start_dt=None, end_dt=context.current_dt, count=1, fields=['time', 'current', 'high', 'low', 'volume', 'money'])
                current_price = current_price_list['current'][0]
                day_open_price = get_current_data()[stock_two].day_open
                day_high_limit = get_current_data()[stock_two].high_limit 
                day_low_limit = get_current_data()[stock_two].low_limit 
                
                #查询当天的最高价
                df_panel_allday = get_price(stock_two, start_date=lastToday, end_date=context.current_dt, frequency='minute', fields=['high','low','close','high_limit','money'])
                low_allday = df_panel_allday.loc[:,"low"].min()
                high_allday = df_panel_allday.loc[:,"high"].max()
                ##获取前一天的收盘价
                pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
                df_panel = get_price(stock_two, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','low',])
                pre_low_price =df_panel['low'].values
                pre_close_price =df_panel['close'].values
                num_limit_stock = count_limit_num_all(stock_two,context)
                #平均持仓成本
                cost = context.portfolio.positions[stock_two].avg_cost
                # print("----------------------------------")
                # print("current_price="+str(current_price))
                # print("day_open_price="+str(day_open_price))
                # print("pre_close_price="+str(pre_close_price))
                # print("df_max_high="+str(df_max_high))
                # print("=====================================")
                if current_price < high_allday * 0.97 and current_price > day_low_limit:
                    print("1.卖出股票：小于最高价0.97倍"+str(num_limit_stock))
                    order_target(stock_two, 0)
                elif current_price < cost * 0.93 and current_price < day_open_price and current_price >day_low_limit:
                    print("卖出股票：比开盘价低7个点"+str(num_limit_stock))
                    order_target(stock_two, 0)
    elif time_sell > dday:
        stock_owner = context.portfolio.positions
        if len(stock_owner) > 0:
            for stock_two in stock_owner:
                current_price_list = get_ticks(stock_two,start_dt=None, end_dt=context.current_dt, count=1, fields=['time', 'current', 'high', 'low', 'volume', 'money'])
                current_price = current_price_list['current'][0]
                day_open_price = get_current_data()[stock_two].day_open
                day_high_limit = get_current_data()[stock_two].high_limit 
                day_low_limit = get_current_data()[stock_two].low_limit 
                
                #查询当天的最高价
                df_panel_allday = get_price(stock_two, start_date=lastToday, end_date=context.current_dt, frequency='minute', fields=['high','low','close','high_limit','money'])
                low_allday = df_panel_allday.loc[:,"low"].min()
                high_allday = df_panel_allday.loc[:,"high"].max()
                ##获取前一天的收盘价
                pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
                df_panel = get_price(stock_two, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','low',])
                pre_low_price =df_panel['low'].values
                pre_close_price =df_panel['close'].values
                num_limit_stock = count_limit_num_all(stock_two,context)
                #平均持仓成本
                cost = context.portfolio.positions[stock_two].avg_cost
                # print("----------------------------------")
                # print("current_price="+str(current_price))
                # print("day_open_price="+str(day_open_price))
                # print("pre_close_price="+str(pre_close_price))
                # print("df_max_high="+str(df_max_high))
                # print("=====================================")
                if current_price < pre_close_price * 1.03 and current_price > day_low_limit:
                    print("1.卖出股票：小于最高价0.97倍"+str(num_limit_stock))
                    order_target(stock_two, 0)
                    
    time_sell = context.current_dt.strftime('%H:%M:%S')
    cday = datetime.datetime.strptime('14:45:00', '%H:%M:%S').strftime('%H:%M:%S')
    if time_sell > cday and len(help_stock) > 0:
        instead_stock = help_stock
        for stock_remove in instead_stock:
            help_stock.remove(stock_remove)

## 开盘前运行函数 选择二板放量股  并且横盘震荡
def before_market_open(context):
    date_now =  (context.current_dt+ timedelta(days = -1)).strftime("%Y-%m-%d")#'2021-01-15'#datetime.datetime.now()
    yesterday = (context.current_dt + timedelta(days = -30)).strftime("%Y-%m-%d")
    trade_date = get_trade_days(start_date=yesterday, end_date=date_now, count=None)

    ##查询所有股票的当天的涨停板
    stocks = list(get_all_securities(['stock']).index)
    end_date=trade_date[trade_date.size-1]
    high_limit_stock = pick_high_limit(stocks,end_date)
    
    ##去除st的连板股票
    tmpList_st = filter_st(high_limit_stock)
    pre_date=trade_date[trade_date.size-2]
    tmpList = filter_one_limit(tmpList_st,pre_date)
    ##筛选上市时间大于1080天的股票
    #tmpList = filter_stock_by_days(context,continuous_price_limit_two,1080)
    
    ##查看股票前期是否平整，并且股票第一个板要高过一年的最高收盘价
    for stock_flat in tmpList:
        bool_result = filter_flat_stock(stock_flat,end_date,pre_date)
        if bool_result == True :
            help_stock.append(stock_flat)
    
    print("----------------最后被选出的股票-----------")
    print(help_stock)
    
##选出打板的股票
def pick_high_limit(stocks,end_date):
    df_panel = get_price(stocks, count = 1,end_date=end_date, frequency='daily', fields=['open', 'close','high_limit','money','pre_close'])
    df_close = df_panel['close']
    df_open = df_panel['open']
    df_high_limit = df_panel['high_limit']
    df_money = df_panel['money']
    df_pre_close = df_panel['pre_close']
    high_limit_stock = []
    for stock in (stocks):
        _high = (df_high_limit[stock].values)
        _close = (df_close[stock].values)
        _open =  (df_open[stock].values)
        _pre_close = (df_pre_close[stock].values)
        if(stock[0:3] == '300'):
            continue
        if(_high == _close and _high > _pre_close * 1.05 and _close > _open * 1.05):
            high_limit_stock.append(stock)
    return high_limit_stock
    
##去除st的股票
def filter_st(codelist):
    current_data = get_current_data()
    codelist = [code for code in codelist if not current_data[code].is_st]
    return codelist
    
##选出只有一板的股票
def filter_one_limit(stocks,end_date):
    print(end_date)
    df_panel = get_price(stocks, count = 1,end_date=end_date, frequency='daily', fields=['open', 'close','high_limit','money'])
    df_close = df_panel['close']
    df_high_limit = df_panel['high_limit']
    df_money = df_panel['money']
    high_limit_stock = []
    for stock in (stocks):

        _high = (df_high_limit[stock].values)
        _close = (df_close[stock].values)
        _money = (df_money[stock].values)
        _high_imit = df_high_limit[stock].values
        ##剔除创业板的股票
        if(stock[0:3] == '300'):
            continue
        if _high_imit !=  _close :
            high_limit_stock.append(stock)
    return high_limit_stock

##查看股票前期是否平整 且两板的最高点是否超过其他的最高点
def filter_flat_stock(stock,end_date,pre_date):
    
    #查询昨天的涨停价格
    df_panel = get_price(stock, count = 1,end_date=end_date, frequency='daily', fields=['open', 'close','high_limit','money'])
    df_close = df_panel['close'].values
    df_open = df_panel['open'].values
    df_high_limit = df_panel['high_limit'].values
    df_money = df_panel['money'].values
   
    #20天的波动率
    df_panel_10 = get_price(stock, count = 10,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','high','low'])
    sum_plus_num_two = (df_panel_10.loc[:,'high'] == df_panel_10.loc[:,'high_limit']).sum()
    df_max_high = df_panel_10["high"].max()
    df_min_low = df_panel_10["low"].min()
    abs_sum_10 = (df_panel_10.loc[:,'close'] - df_panel_10.loc[:,'open']).abs() / ((df_panel_10.loc[:,'open']+df_panel_10.loc[:,'close']) / 2)
    abs_sum_num_1030 = (abs_sum_10 < 0.03).sum()
    abs_sum_num_1015 = (abs_sum_10 < 0.015).sum()
    abs_sum_num_1055 = (abs_sum_10 < 0.055).sum()
    
    df_panel_20 = get_price(stock, count = 20,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','high','low'])
    sum_shipan_num = ((df_panel_20.loc[:,'high_limit'] == df_panel_20.loc[:,'high']) * (df_panel_20.loc[:,'close'] <= df_panel_20.loc[:,'high_limit'] * 0.97)).sum()
    df_max_high_20 = df_panel_20["high"].max()
    sum_plus_num_20 = (df_panel_20.loc[:,'high'] == df_panel_20.loc[:,'high_limit']).sum()
    abs_sum_20 = (df_panel_20.loc[:,'close'] - df_panel_20.loc[:,'open']).abs() / ((df_panel_20.loc[:,'open']+df_panel_20.loc[:,'close']) / 2)
    abs_sum_num_2030 = (abs_sum_20 < 0.03).sum()
    abs_sum_num_2015 = (abs_sum_20 < 0.015).sum()
    abs_sum_num_2055 = (abs_sum_20 < 0.055).sum()
    
    df_panel_30 = get_price(stock, count = 30,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','high','low'])
    df_max_high_30 = df_panel_30["high"].max()
    df_min_low_30 = df_panel_30["low"].min()
    rate_30 = (df_max_high_30 - df_min_low_30) / df_min_low_30

    
    rate_10 = (df_max_high - df_min_low) / df_min_low
    
    #print(stock+"收盘价的方差为："+str(std_allday))
    #12天的波动率
    df_panel_60 = get_price(stock, count = 60,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','high','low'])
    high_allday_60 = df_panel_60.loc[:,"high"].max()
    low_allday_60 = df_panel_60.loc[:,"low"].min()
    close_allday_60 = df_panel_60.loc[:,"close"].max()
    percent_rate_60 = low_allday_60 / high_allday_60
    sum_close_num_60 = (df_panel_60.loc[:,'close'] <= df_panel_60.loc[:,'open']).sum()
    abs_sum_60 = (df_panel_60.loc[:,'close'] - df_panel_60.loc[:,'open']).abs() / df_panel_60.loc[:,'open']
    abs_sum_num_6015 = (abs_sum_60 < 0.015).sum()
    abs_sum_num_6030 = (abs_sum_60 < 0.03).sum()
    abs_sum_num_6055 = (abs_sum_60 < 0.055).sum()
    sum_plus_num_60 = (df_panel_60.loc[:,'high'] > df_panel_60.loc[:,'high_limit'] * 0.99).sum()
    
    df_panel_100 = get_price(stock, count = 100,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','high','low'])
    df_max_close_100 = df_panel_100["close"].max()
    
    #150天的波动率
    df_panel_150 = get_price(stock, count = 150,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','high','low','pre_close'])
    sum_plus_num_150 = (df_panel_150.loc[:,'close'] > df_panel_150.loc[:,'pre_close'] * 1.09).sum()
    df_max_close_150 = df_panel_150["close"].max()
    df_max_open_150 = df_panel_150["open"].max()
    df_min_low_150 = df_panel_150["low"].min()
    abs_sum_150 = (df_panel_150.loc[:,'close'] - df_panel_150.loc[:,'open']).abs() / ((df_panel_150.loc[:,'open']+df_panel_150.loc[:,'close']) / 2)
    abs_sum_num_1503 = (abs_sum_150 < 0.03).sum()
    abs_sum_num_1515 = (abs_sum_150 < 0.015).sum()
    abs_sum_num_15555 = (abs_sum_150 < 0.055).sum()
    
    rate_150 = (df_max_close_150 - df_min_low_150) / df_min_low_150
    

    # df_panel_30 = get_price(stock, count = 30,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','high','low'])
    # close_allday_30 = df_panel_30.loc[:,"close"].max()
    # sum_close_num_two = (df_panel_two.loc[:,'close'] <= df_panel_two.loc[:,'open']).sum()
    if stock == '603518.XSHG':
        print(df_close)
        print(close_allday_60)
        print("-------20days--------")
        print(abs_sum_num_2030)
        print(abs_sum_num_2015)
        print(abs_sum_num_2055)
        print("-------60days--------")
        print(abs_sum_num_6015)
        print(abs_sum_num_6030)
        print(abs_sum_num_6055)
        print("------------150days--------------")
        print(abs_sum_num_1503) 
        print(abs_sum_num_1515) 
        print(abs_sum_num_15555) 
    if df_close * 1.1 > close_allday_60 and abs_sum_num_2030 > 15 and abs_sum_num_2015 > 7 and abs_sum_num_2055 >= 18:
        if abs_sum_num_6015 >=28 and abs_sum_num_6030 > 45 and abs_sum_num_6055 > 50:
                return True
##过滤上市时间不满1080天的股票
def filter_stock_by_days(context, stock_list, days):
    tmpList = []
    for stock in stock_list :
        #days_public=(context.current_dt.date() - get_security_info(stock).start_date).days days_public > days and 
        market_cap = get_circulating_market_cap(stock)
        market_cap_num = market_cap['circulating_market_cap'].values
        if market_cap_num >10 and market_cap_num < 150:
            tmpList.append(stock)
    return tmpList
    
##查看他总的涨停数
def count_limit_num_all(stock,context):
    date_now =  (context.current_dt+ timedelta(days = -1)).strftime("%Y-%m-%d")#'2021-01-15'#datetime.datetime.now()
    yesterday = (context.current_dt + timedelta(days = -30)).strftime("%Y-%m-%d")
    trade_date = get_trade_days(start_date=yesterday, end_date=date_now, count=None)
    limit_num = 0
    for datenum in trade_date:
        df_panel = get_price(stock, count = 1,end_date=datenum, frequency='daily', fields=['open', 'close','high_limit','money'])
        df_close = df_panel['close'].values
        df_high_limit = df_panel['high_limit'].values
        if df_close == df_high_limit:
            limit_num = limit_num + 1
    return limit_num
    
##获取个股流通市值数据
def get_circulating_market_cap(stock_list):
    query_list = [stock_list]
    q = query(valuation.code,valuation.circulating_market_cap).filter(valuation.code.in_(query_list))
    market_cap = get_fundamentals(q)
    market_cap.set_index('code', inplace=True)
    return market_cap

def count_limit_num(stock,context):
    date_now =  (context.current_dt+ timedelta(days = -1)).strftime("%Y-%m-%d")#'2021-01-15'#datetime.datetime.now()
    yesterday = (context.current_dt + timedelta(days = -20)).strftime("%Y-%m-%d")
    trade_date = get_trade_days(start_date=yesterday, end_date=date_now, count=None)
    limit_num = 0
    for datenum in trade_date:
        df_panel = get_price(stock, count = 1,end_date=datenum, frequency='daily', fields=['open', 'close','high_limit','money'])
        df_close = df_panel['close'].values
        df_high_limit = df_panel['high_limit'].values
        if df_close == df_high_limit:
            limit_num = limit_num + 1
    #print("涨停板天数："+str(limit_num))
    return limit_num
    
        
## 收盘后运行函数
def after_market_close(context):
    log.info(str('除当天的股票数据-----函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #消除当天的股票数据
    help_stock = []
    #print(help_stock)
