# 克隆自聚宽文章：https://www.joinquant.com/post/34286
# 标题：龙头底分型战法-两年23倍
# 作者：游资小码哥

# 导入函数库
from jqdata import *
help_stock = []
# 初始化函数，设定基准等等
#需要注意的点，1.最高点前不能连续涨停 2.最高点要高过前面一年
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
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
    run_daily(market_open, time='every_bar', reference_security='000300.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')
## 开盘时运行函数
def market_open(context):
    time_buy = context.current_dt.strftime('%H:%M:%S')
    date_now =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")#'2021-01-15'#datetime.datetime.now()
    ten_day = datetime.datetime.strptime('09:35:00', '%H:%M:%S').strftime('%H:%M:%S')
    cash = context.portfolio.available_cash
    if len(help_stock) > 0:
        for stock in help_stock:
            if cash > 5000 :
                day_open_price = get_current_data()[stock].day_open
                current_price = get_current_data()[stock].last_price
                pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
                df_panel = get_price(stock, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','low',])
                pre_low_price =df_panel['low'].values
                pre_close_price =df_panel['close'].values
                if current_price > day_open_price * 1.02 and current_price > pre_close_price and day_open_price < pre_close_price * 1.05 and day_open_price > pre_close_price * 0.99:
                    print("1."+stock+"买入金额"+str(cash))
                    order_value(stock, cash)
                    help_stock.remove(stock)
                elif day_open_price > pre_close_price * 1.05 and current_price > pre_close_price * 1.03 and time_buy > ten_day:
                    print("2."+stock+"买入金额"+str(cash))
                    order_value(stock, cash)
                    help_stock.remove(stock)
                    
    time_sell = context.current_dt.strftime('%H:%M:%S')
    cday = datetime.datetime.strptime('14:40:00', '%H:%M:%S').strftime('%H:%M:%S')
    ten_day = datetime.datetime.strptime('10:15:00', '%H:%M:%S').strftime('%H:%M:%S')
    now = context.current_dt
    zeroToday = now - datetime.timedelta(hours=now.hour, minutes=now.minute, seconds=now.second,microseconds=now.microsecond)
    lastToday = zeroToday + datetime.timedelta(hours=9, minutes=31, seconds=00)
    stock_owner = context.portfolio.positions
    if time_sell > cday:
        if len(stock_owner) > 0:
            for stock_two in stock_owner:
                if context.portfolio.positions[stock_two].closeable_amount > 0:
                    current_price_list = get_ticks(stock_two,start_dt=None, end_dt=context.current_dt, count=1, fields=['time', 'current', 'high', 'low', 'volume', 'money'])
                    current_price = current_price_list['current'][0]
                    day_open_price = get_current_data()[stock_two].day_open
                    day_high_limit = get_current_data()[stock_two].high_limit 
                    
                    pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
                    df_panel = get_price(stock_two, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','low','pre_close'])
                    pre_low_price =df_panel['low'].values
                    pre_close_price =df_panel['close'].values
                    pre_pre_close =df_panel['pre_close'].values
                    
                    df_panel_allday = get_price(stock_two, start_date=lastToday, end_date=context.current_dt, frequency='minute', fields=['high','low','close','high_limit','money'])
                    low_allday = df_panel_allday.loc[:,"low"].min()
                    high_allday = df_panel_allday.loc[:,"high"].max()
                    current_price = context.portfolio.positions[stock_two].price #持仓股票的当前价 
                    cost = context.portfolio.positions[stock_two].avg_cost
                    close_data = attribute_history(stock_two, 20, '1d', ['close'])
                    MA20 = close_data['close'].mean()
                    
                    pre_date_init =  (context.portfolio.positions[stock_two].init_time + timedelta(days = 30)).strftime("%Y-%m-%d")
    
                    if current_price < cost * 0.95:
                        print("#1.卖出股票：亏5个点")
                        order_target(stock_two, 0)
                    elif current_price <  day_open_price * 0.95 and current_price > cost * 1.4:
                        print("#3.卖出股票：放量大阴线")
                        order_target(stock_two, 0)
                    #高位十字星
                    elif current_price <  high_allday * 0.97 and day_open_price > low_allday * 1.05 and day_open_price < high_allday * 0.95 and current_price > cost * 1.4:
                        print("#3.卖出股票：放量大阴线")
                        order_target(stock_two, 0)
    else:
        for stock_two in stock_owner:
            if context.portfolio.positions[stock_two].closeable_amount > 0:
                current_price_list = get_ticks(stock_two,start_dt=None, end_dt=context.current_dt, count=1, fields=['time', 'current', 'high', 'low', 'volume', 'money'])
                current_price = current_price_list['current'][0]
                day_open_price = get_current_data()[stock_two].day_open
                day_high_limit = get_current_data()[stock_two].high_limit 
                
                pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
                df_panel = get_price(stock_two, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','low','pre_close'])
                pre_low_price =df_panel['low'].values
                pre_close_price =df_panel['close'].values
                pre_pre_close =df_panel['pre_close'].values
                
                df_panel_3 = get_price(stock_two, count = 3,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','low','pre_close'])
                sum_limit_num_three= (df_panel_3.loc[:,'close'] == df_panel_3.loc[:,'high_limit']).sum()
                
                pre_date_12 =  (context.current_dt + timedelta(days = -12)).strftime("%Y-%m-%d")#'2021-01-15'#datetime.datetime.now()
                df_panel_60 = get_price(stock_two, count = 60,end_date=pre_date_12, frequency='daily', fields=['open', 'high', 'close','low', 'high_limit','money'])
                df_max_high_60 = df_panel_60["close"].max()
                
                df_panel_allday = get_price(stock_two, start_date=lastToday, end_date=context.current_dt, frequency='minute', fields=['high','low','close','high_limit','money'])
                low_allday = df_panel_allday.loc[:,"low"].min()
                high_allday = df_panel_allday.loc[:,"high"].max()
                current_price = context.portfolio.positions[stock_two].price #持仓股票的当前价 
                cost = context.portfolio.positions[stock_two].avg_cost
                close_data = attribute_history(stock_two, 5, '1d', ['close'])
                MA5 = close_data['close'].mean()
                
                pre_date_init =  (context.portfolio.positions[stock_two].init_time + timedelta(days = 30)).strftime("%Y-%m-%d")

                if current_price < cost * 0.95:
                    print("1.卖出股票：亏5个点")
                    order_target(stock_two, 0)
                elif sum_limit_num_three == 3 and day_open_price < pre_close_price and current_price < pre_close_price * 0.97:
                    print("2.卖出股票:三个连扳之后的")
                    order_target(stock_two, 0)
                elif current_price <  day_open_price * 0.93 and current_price < df_max_high_60 and current_price > cost * 1.3:
                    print("4.卖出股票：放量大阴线")
                    order_target(stock_two, 0)
                elif current_price > cost * 1.4 and current_price < MA5:
                    print("6.卖出股票：放量大阴线")
                    order_target(stock_two, 0)
                elif current_price < low_allday * 0.97:
                    print("7.卖出股票：小于最低价的3%")
                    order_target(stock_two, 0)
                elif day_open_price < low_allday:
                    print("8.卖出股票：开盘价小于最低价")
                    order_target(stock_two, 0)
 

    if time_sell > cday and len(help_stock) > 0:
        instead_stock = help_stock
        for stock_remove in instead_stock:
            help_stock.remove(stock_remove)

## 开盘前运行函数
def before_market_open(context):
    date_now =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")#'2021-01-15'#datetime.datetime.now()
    yesterday = (context.current_dt + timedelta(days = -31)).strftime("%Y-%m-%d")
    trade_date = get_trade_days(start_date=yesterday, end_date=date_now, count=None)
    yes_date_one = trade_date[trade_date.size-1]
    stocks = list(get_all_securities(['stock']).index)
    pick_high_list = pick_high_limit(stocks,yes_date_one)
    codelist = filter_st(pick_high_list)
    filter_paused_list =filter_paused_stock(codelist)
    templist = filter_stock_by_days(context, filter_paused_list, 1080)
    for stock in templist:
        high_continous(stock,trade_date,date_now,context)
    print("------今天要扫描的股票------")
    print(help_stock)
    
#查询最近最高点的位置，之前是不是连续涨
def high_continous(stock,trade_date,date_now,context):
    df_panel = get_price(stock, count = 40,end_date=date_now, frequency='daily', fields=['open', 'high', 'close','low', 'high_limit','money'])
    sum_plus_num_40= (df_panel.loc[:,'open'] > df_panel.loc[:,'close'] * 1.14).sum()
    time_high = df_panel['high'].idxmax()
    df_max_high = df_panel["close"].max()
    
    df_panel_40 = get_price(stock, count = 12,end_date=time_high, frequency='daily', fields=['open', 'high', 'close','low', 'high_limit','money'])
    df_max_high_40 = df_panel_40["close"].max()
    df_min_low_40 = df_panel_40["close"].min()
    rate_40 = (df_max_high_40 - df_min_low_40) / df_min_low_40
    
    df_panel_80 = get_price(stock, count = 80,end_date=time_high, frequency='daily', fields=['open', 'high', 'close','low', 'high_limit','money'])
    df_max_high_80 = df_panel_80["high"].max()
    df_min_low_80 = df_panel_80["close"].min()
    rate_80 = (df_max_high_80 - df_min_low_80) / df_min_low_80
    
    
    # print("stock="+stock)
    # print(time_high)
    
    pre_date =  (time_high + timedelta(days = -1)).strftime("%Y-%m-%d")#'2021-01-15'#datetime.datetime.now()
    df_panel_eight = get_price(stock, count = 8,end_date=pre_date, frequency='daily', fields=['open', 'high', 'close','low', 'high_limit','money'])
    #查询涨停板有没有四个
    sum_plus_two = df_panel_eight.loc[:,'high'] - df_panel_eight.loc[:,'high_limit']
    sum_plus_num_two= (df_panel_eight.loc[:,'high'] == df_panel_eight.loc[:,'high_limit']).sum()
    df_max_high = df_panel_eight["high"].max()
    df_min_low = df_panel_eight["low"].min()
    
    yes_date_two = trade_date[trade_date.size-2]
    df_panel_five = get_price(stock, count = 6,end_date=yes_date_two, frequency='daily', fields=['open', 'high', 'close','low', 'high_limit','money','pre_close'])
    sum_limit_num_five= (df_panel_five.loc[:,'close'] > df_panel_five.loc[:,'high_limit'] * 0.95).sum()
    
    #查询是不是有6天是低于前一天的
    yes_date_two = trade_date[trade_date.size-2]
    df_panel_10 = get_price(stock, count = 10,end_date=yes_date_two, frequency='daily', fields=['open', 'high', 'close','low', 'high_limit','money','pre_close'])
    sum_close_low_pre_close= (df_panel_10.loc[:,'close'] <= df_panel_10.loc[:,'pre_close']).sum()
    
    sum_down= (df_panel_eight.loc[:,'close'] < df_panel_eight.loc[:,'open']).sum()
    
    pre_date_20 =  (time_high + timedelta(days = -30)).strftime("%Y-%m-%d")
    df_panel_500 = get_price(stock, count = 500,end_date=pre_date_20, frequency='daily', fields=['open', 'high', 'close','low', 'high_limit','money','pre_close'])
    df_max_high_500 = df_panel_500["close"].max()

    if stock == '600776.XSHG':
        print("sum_plus_num_two="+str(sum_plus_num_two))
        print("sum_down="+str(sum_down))
        print("rate_40="+str(rate_40))
        print("sum_close_low_pre_close="+str(sum_close_low_pre_close))
        print("df_max_high_40="+str(df_max_high_40))
        print("df_min_low_40="+str(df_min_low_40))
        print("df_max_high="+str(df_max_high))
        print("rate_80="+str(rate_80))
        print("rate_80="+str(rate_80))
        print("rate_80="+str(rate_80))
    if sum_plus_num_two >= 3 and sum_down <=3 and sum_plus_num_40 == 0 and df_max_high > df_max_high_500 and rate_40 >= 0.55 and rate_80 < 3.8 and sum_close_low_pre_close >= 5 and sum_limit_num_five == 0:
    #if sum_plus_num_two >= 3 and sum_down <=3 and sum_down >= 0 and rate_40 > 0.95 and sum_close_low_pre_close > 6 and sum_limit_num_five == 0:
        pre_date_high = time_high.strftime("%Y-%m-%d")
        pre_date_seven = (context.current_dt + timedelta(days = -7)).strftime("%Y-%m-%d")
        #并且昨天是涨停板的情况
        pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
        df_panel_three = get_price(stock, count = 3,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','low','high'])
        df_close_one = df_panel_three['close'].iloc[0]
        df_open_one = df_panel_three['open'].iloc[0]
        df_high_one = df_panel_three['high'].iloc[0]
        
        
        df_close_two = df_panel_three['close'].iloc[1]
        df_open_two = df_panel_three['open'].iloc[1]
        
        df_high_two = df_panel_three['high'].iloc[1]
        df_low_two = df_panel_three['low'].iloc[1]
        #是不是底部十字星
        rate_two = abs(df_close_two-df_open_two)/((df_close_two+df_open_two)/2)
        #十字星最大最小差值小于0.08
        rate_two_high = abs(df_high_two-df_low_two)/((df_high_two+df_low_two)/2)
        df_close_three = df_panel_three['close'].iloc[2]
        df_high_limit_three = df_panel_three['high_limit'].iloc[2]
        
        bool_result = check_first_valley(trade_date,stock)
        if stock == '600211.XSHG':
            print("-------------------------------------")
            print("df_close_three="+str(df_close_three))
            print("df_high_limit_three="+str(df_high_limit_three))
            print("df_open_one="+str(df_open_one))
            print("df_close_two="+str(df_close_two))
            print("df_close_three="+str(df_close_three))
            print("df_high_one="+str(df_high_one))
            print("rate_two="+str(rate_two))
            print("rate_two_high="+str(rate_two_high))
            print("bool_result="+str(bool_result))
        #要在60日均线之上
        df_panel_60 = get_price(stock, count = 60,end_date=yes_date_two, frequency='daily', fields=['open', 'close','high_limit','money'])
        df_close_mean_60 = df_panel_60['close'].mean()
        #底分型
        if df_close_three == df_high_limit_three and df_close_two > df_close_mean_60 and rate_two < 0.025 and rate_two_high < 0.08 and df_open_one > df_close_two * 1.02 and df_open_one > df_open_two * 1.02 and df_close_three > df_close_two * 1.07 and df_close_three > df_open_one:
            
            help_stock.append(stock)

##选出打板的股票
def pick_high_limit(stocks,end_date):
    df_panel = get_price(stocks, count = 1,end_date=end_date, frequency='daily', fields=['open', 'close','high_limit','money','pre_close'])
    df_close = df_panel['close']
    df_open = df_panel['open']
    df_high_limit = df_panel['high_limit']
    df_pre_close = df_panel['pre_close']
    high_limit_stock = []
    for stock in (stocks):
        _high_limit = (df_high_limit[stock].values)
        _close = (df_close[stock].values)
        _open =  (df_open[stock].values)
        _pre_close = (df_pre_close[stock].values)
        if(stock[0:3] == '300' or stock[0:3] == '688'):
            continue

        if _high_limit == _close and _close > _pre_close * 1.05:
            high_limit_stock.append(stock)
    return high_limit_stock 
    
def check_first_valley(trade_date,stock):
    int_count = 2
    for stock_day in trade_date:
        df_panel = get_price(stock, count = 1,end_date=trade_date[trade_date.size-int_count], frequency='daily', fields=['open', 'close','high_limit','money'])
        pre_close_price =df_panel['close'].values
        df_panel_5 = get_price(stock, count = 5,end_date=trade_date[trade_date.size-int_count], frequency='daily', fields=['open', 'close','high_limit','money'])
        df_close_mean_5 = df_panel_5['close'].mean()
        int_count = int_count +1
        if pre_close_price > df_close_mean_5:
            return False
        if int_count > 8:
            return True
        
    
##过滤上市时间不满1080天的股票
def filter_stock_by_days(context, stock_list, days):
    tmpList = []
    for stock in stock_list :
        days_public=(context.current_dt.date() - get_security_info(stock).start_date).days
        if days_public > days:
            tmpList.append(stock)
    return tmpList

##去除st的股票
def filter_st(codelist):
    current_data = get_current_data()
    codelist = [code for code in codelist if not current_data[code].is_st]
    return codelist

def filter_paused_stock(stock_list):
    current_data = get_current_data()
    stock_list = [stock for stock in stock_list if not current_data[stock].paused]
    return stock_list
    

## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    for stock_remove in help_stock:
            help_stock.remove(stock_remove)
    log.info('一天结束')
    log.info('##############################################################')
