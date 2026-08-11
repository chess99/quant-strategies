# 克隆自聚宽文章：https://www.joinquant.com/post/35141
# 标题：多策略融合-80倍-无未来函数
# 作者：游资小码哥

# 导入函数库
from jqdata import *
from jqlib.technical_analysis import *

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
    
    g.help_stock_four = []
    g.help_stock_four_sell = []
    
    g.help_stock_five = []
    g.help_stock_five_sell = []
    
    g.help_stock_seven = []
    g.help_stock_seven_sell = []
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open_all, time='before_open', reference_security='000300.XSHG')
      # 开盘时运行
    run_daily(market_open, time='every_bar', reference_security='000300.XSHG')
    #run_daily(market_run_sell, time='every_bar', reference_security='000300.XSHG')
    
    #收盘后运行before_open
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')
    

def before_market_open_all(context):
    before_market_open_four(context)
    before_market_open_five(context)
    before_market_open_seven(context)
    
    help_stock_msg = "今日选出股票："
    help_stock_msg_four = "--连扳分歧战法："
    help_stock_msg_five = "--龙头底分型战法："
    help_stock_msg_seven = "--缩量分歧反包战法："

    if len(g.help_stock_four) > 0:
        for stock in g.help_stock_four:
            help_stock_msg_four = help_stock_msg_four + stock + "; "
        help_stock_msg = help_stock_msg + help_stock_msg_four

    if len(g.help_stock_five) > 0:
        for stock in g.help_stock_five:
            help_stock_msg_five = help_stock_msg_five + stock + "; "
        help_stock_msg = help_stock_msg + help_stock_msg_five
        
    if len(g.help_stock_seven) > 0:
        for stock in g.help_stock_seven:
            help_stock_msg_seven = help_stock_msg_seven + stock + "; "
        help_stock_msg = help_stock_msg + help_stock_msg_seven
            
    # sell类型     
    help_stock_msg_sell = "#今日持仓的股票："
    help_stock_msg_four_sell = "--连扳分歧战法："
    help_stock_msg_five_sell = "--龙头底分型战法："
    help_stock_msg_seven_sell = "--三阳三阴战法："

    if len(g.help_stock_four_sell) > 0:
        for stock in g.help_stock_four_sell:
            help_stock_msg_four_sell = help_stock_msg_four_sell + stock + "; "
        help_stock_msg_sell = help_stock_msg_sell + help_stock_msg_four_sell

    if len(g.help_stock_five_sell) > 0:
        for stock in g.help_stock_five_sell:
            help_stock_msg_five_sell = help_stock_msg_five_sell + stock + "; "
        help_stock_msg_sell = help_stock_msg_sell + help_stock_msg_five_sell
        
    
    if len(g.help_stock_seven_sell) > 0:
        for stock in g.help_stock_seven_sell:
            help_stock_msg_seven_sell = help_stock_msg_seven_sell + stock + "; "
        help_stock_msg_sell = help_stock_msg_sell + help_stock_msg_seven_sell
        
    ##每日买卖持仓
    print(help_stock_msg)
    print(help_stock_msg_sell)


## 开盘时运行函数
def market_open(context):
    
    #三虎 三板确定性买入法
    market_open_four(context)
    
    #四虎 龙头底分型
    market_open_five(context)
    
    #七龙珠 缩量分歧反包战法
    market_open_seven(context)


##三虎 三板确定性买入法
## 开盘时运行函数
def market_open_four(context):
    time_buy = context.current_dt.strftime('%H:%M:%S')
    aday = datetime.datetime.strptime('13:00:00', '%H:%M:%S').strftime('%H:%M:%S')
    if len(g.help_stock_four) > 0 :
        for stock in g.help_stock_four:
            #log.info("当前时间 %s" % (context.current_dt))
            #log.info("股票 %s 的最新价: %f" % (stock, get_current_data()[stock].last_price))
            cash = context.portfolio.available_cash
            #print(cash)
            day_open_price = get_current_data()[stock].day_open
            current_price = get_current_data()[stock].last_price
            high_limit_price = get_current_data()[stock].high_limit
            pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
            df_panel = get_price(stock, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'high', 'close','low', 'high_limit','money','pre_close'])
            pre_high_limit = df_panel['high_limit'].values
            pre_close = df_panel['close'].values
            pre_open = df_panel['open'].values
            pre_high = df_panel['high'].values
            pre_low = df_panel['low'].values
            pre_pre_close = df_panel['pre_close'].values
            
            now = context.current_dt
            zeroToday = now - datetime.timedelta(hours=now.hour, minutes=now.minute, seconds=now.second,microseconds=now.microsecond)
            lastToday = zeroToday + datetime.timedelta(hours=9, minutes=31, seconds=00)
            df_panel_allday = get_price(stock, start_date=lastToday, end_date=context.current_dt, frequency='minute', fields=['close','high_limit'])
            low_allday = df_panel_allday.loc[:,"close"].min()
            high_allday = df_panel_allday.loc[:,"close"].max()
            sum_plus_num_two = (df_panel_allday.loc[:,'close'] == df_panel_allday.loc[:,'high_limit']).sum()
            
            pre_date_two =  (context.current_dt + timedelta(days = -10)).strftime("%Y-%m-%d")
            df_panel_150 = get_price(stock, count = 150,end_date=pre_date_two, frequency='daily', fields=['open', 'close','high_limit','money','low','high','pre_close'])
            df_max_high_150 = df_panel_150["close"].max()
            ##当前持仓有哪些股票
            if cash > 20000 :

                if sum_plus_num_two > 10 and current_price < high_limit_price and current_price > pre_close * 1.08:
                    print("1."+stock+"买入金额"+str(cash))
                    orders = order_value(stock, cash)
                    if str(orders.status) == 'held':
                        g.help_stock_four.remove(stock)
                        g.help_stock_four_sell.append(stock)
                elif day_open_price > pre_close * 1.05 and current_price > day_open_price * 1.02 and current_price > df_max_high_150 and current_price < high_limit_price:
                    print("2."+stock+"买入金额"+str(cash))
                    orders = order_value(stock, cash)
                    if str(orders.status) == 'held':
                        g.help_stock_four.remove(stock)
                        g.help_stock_four_sell.append(stock)

    time_sell = context.current_dt.strftime('%H:%M:%S')
    cday = datetime.datetime.strptime('14:40:00', '%H:%M:%S').strftime('%H:%M:%S')
    sell_day = datetime.datetime.strptime('11:10:00', '%H:%M:%S').strftime('%H:%M:%S')
    sell_day_10 = datetime.datetime.strptime('13:30:00', '%H:%M:%S').strftime('%H:%M:%S')
    
    if time_sell > cday:
        stock_owner = context.portfolio.positions
        if len(stock_owner) > 0 and len(g.help_stock_four_sell) > 0:
            for stock_two in stock_owner:
                if context.portfolio.positions[stock_two].closeable_amount > 0:
                    current_price = get_current_data()[stock_two].last_price
                    day_open_price = get_current_data()[stock_two].day_open
                    day_high_limit = get_current_data()[stock_two].high_limit 
                    
                    now = context.current_dt
                    zeroToday = now - datetime.timedelta(hours=now.hour, minutes=now.minute, seconds=now.second,microseconds=now.microsecond)
                    lastToday = zeroToday + datetime.timedelta(hours=9, minutes=31, seconds=00)
                    df_panel_allday = get_price(stock_two, start_date=lastToday, end_date=context.current_dt, frequency='minute', fields=['close','high_limit'])
                    low_allday = df_panel_allday.loc[:,"close"].min()
                    high_allday = df_panel_allday.loc[:,"close"].max()
                    sum_plus_num_two = (df_panel_allday.loc[:,'close'] == df_panel_allday.loc[:,'high_limit']).sum()
                    
                    ##获取前一天的收盘价
                    pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
                    df_panel = get_price(stock_two, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','low',])
                    pre_low_price =df_panel['low'].values
                    pre_close_price =df_panel['close'].values
                    
                    #平均持仓成本
                    cost = context.portfolio.positions[stock_two].avg_cost
                    if current_price < high_allday * 0.92 and day_open_price > pre_close_price:
                        print("1.卖出股票：小于最高价0.869倍"+str(stock_two))
                        orders =order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_four_sell.remove(stock_two)
                    elif current_price > cost * 1.3 and sum_plus_num_two < 80:
                        print("2.卖出股票：亏8个点"+str(stock_two))
                        orders =order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_four_sell.remove(stock_two)
                    elif day_open_price < pre_close_price * 0.98 and current_price < pre_close_price * 0.93:
                        print("3.卖出股票：1.3以下"+str(stock_two))
                        orders =order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_four_sell.remove(stock_two)
    else:
        stock_owner = context.portfolio.positions
        if len(stock_owner) > 0 and len(g.help_stock_four_sell) > 0:
            for stock_two in stock_owner:
                if context.portfolio.positions[stock_two].closeable_amount > 0:
                    current_price = get_current_data()[stock_two].last_price
                    day_open_price = get_current_data()[stock_two].day_open
                    day_high_limit = get_current_data()[stock_two].high_limit 
                    
                    ##获取前一天的收盘价
                    pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
                    df_panel = get_price(stock_two, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','low',])
                    pre_low_price =df_panel['low'].values
                    pre_close_price =df_panel['close'].values
                    pre_high_limit =df_panel['high_limit'].values
                    now = context.current_dt
                    zeroToday = now - datetime.timedelta(hours=now.hour, minutes=now.minute, seconds=now.second,microseconds=now.microsecond)
                    lastToday = zeroToday + datetime.timedelta(hours=9, minutes=31, seconds=00)
                    df_panel_allday = get_price(stock_two, start_date=lastToday, end_date=context.current_dt, frequency='minute', fields=['close','high_limit'])
                    low_allday = df_panel_allday.loc[:,"close"].min()
                    high_allday = df_panel_allday.loc[:,"close"].max()
                    sum_plus_num_two = (df_panel_allday.loc[:,'close'] == df_panel_allday.loc[:,'high_limit']).sum()
                    
                    current_price = context.portfolio.positions[stock_two].price #持仓股票的当前价 
                    cost = context.portfolio.positions[stock_two].avg_cost
                    
                    if current_price < cost * 0.91:
                        print("6.卖出股票：亏5个点"+str(stock_two))
                        orders =order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_four_sell.remove(stock_two)
                    elif current_price < pre_close_price and time_sell > sell_day and current_price > cost:
                        print("7.高位放量，请走！"+str(day_open_price))
                        orders =order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_four_sell.remove(stock_two)
                    elif day_open_price < pre_close_price * 0.95 and current_price > pre_close_price * 0.97:
                        print("add.高位放量，请走！"+str(day_open_price))
                        orders =order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_four_sell.remove(stock_two)
                    elif high_allday > pre_close_price * 1.09 and current_price < day_open_price and day_open_price < day_high_limit * 0.95 and current_price < cost * 1.2:
                        print("8.高位放量，请走！"+str(day_open_price))
                        orders =order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_four_sell.remove(stock_two)
                    elif current_price > cost * 1.25 and current_price < day_high_limit * 0.95 and time_sell > sell_day:
                        print("9.挣够25%，高位放量，请走！"+str(day_open_price))
                        orders =order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_four_sell.remove(stock_two)
                    elif day_open_price < pre_close_price * 0.98 and current_price < high_allday * 0.95 and high_allday > pre_close_price * 1.05:
                        print("10.挣够25%，高位放量，请走！"+str(day_open_price))
                        orders =order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_four_sell.remove(stock_two)
                    elif current_price < high_allday * 0.93 and high_allday > pre_close_price * 1.06 and time_sell > sell_day_10:
                        print("11.挣够25%，高位放量，请走！"+str(day_open_price))
                        orders =order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_four_sell.remove(stock_two)
                    elif day_open_price < pre_close_price * 0.97 and current_price > pre_close_price:
                        print("10.挣够25%，高位放量，请走！"+str(day_open_price))
                        orders =order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_four_sell.remove(stock_two)

## 选出连续涨停超过3天的，最近一天是阴板的
def before_market_open_four(context):
    date_now =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")#'2021-01-15'#datetime.datetime.now()
    yesterday = (context.current_dt + timedelta(days = -90)).strftime("%Y-%m-%d")
    trade_date = get_trade_days(start_date=yesterday, end_date=date_now, count=None)
    stocks = list(get_all_securities(['stock']).index)
    end_date = trade_date[trade_date.size-1]
    pre_date = trade_date[trade_date.size-3]
    #选出昨天是涨停板的个股
    continuous_price_limit = pick_high_limit_four(stocks,end_date,pre_date)

    filter_st_stock = filter_st(continuous_price_limit)
    templist = filter_stock_by_days(context,filter_st_stock,150)
    for stock in templist:
        ##查询昨天的股票是否阴板
        stock_date=trade_date[trade_date.size-2]
        df_panel = get_price(stock, count = 1,end_date=stock_date, frequency='daily', fields=['open', 'close','high_limit','money','low','high','pre_close'])
        df_close = df_panel['close'].values
        df_high = df_panel['high'].values
        df_low = df_panel['low'].values
        df_open = df_panel['open'].values
        df_pre_close = df_panel['pre_close'].values
        df_high_limit = df_panel['high_limit'].values
        #查询昨天的close价格
        df_panel_yes = get_price(stock, count = 1,end_date=end_date, frequency='daily', fields=['open', 'close','high_limit','money','low','high','pre_close'])
        df_close_yes = df_panel_yes['close'].values
        count_limit = count_limit_num_all_four(stock,context)
        # if stock == '002400.XSHE':
        #     print(df_open)
        #     print(df_close)
        #     print(df_high)
        #     print(count_limit)
        pre_date_two = trade_date[trade_date.size-8]
        if df_open >= df_close and df_open < df_high and count_limit <= 5 and df_close_yes > df_high:
            df_panel_80 = get_price(stock, count = 45,end_date=pre_date_two, frequency='daily', fields=['open', 'close','high_limit','money','low','high','pre_close'])
            df_max_high_80 = df_panel_80["close"].max()
            df_min_low_80 = df_panel_80["close"].min()
            abs_sum_80 = (df_panel_80.loc[:,'close'] - df_panel_80.loc[:,'open']).abs() / ((df_panel_80.loc[:,'open']+df_panel_80.loc[:,'close']) / 2)
            abs_sum_num_803 = (abs_sum_80 < 0.03).sum()
            sum_plus_num_80 = (df_panel_80.loc[:,'close'] == df_panel_80.loc[:,'high_limit']).sum()
            rate_80 = (df_max_high_80 - df_min_low_80) / df_min_low_80
            # if stock == '002996.XSHE':
            #     print(df_close)
            #     print(df_max_high_80)
            #     print(rate_80)
            #     print(abs_sum_num_803)
            if rate_80 < 0.8 and abs_sum_num_803 > 25 and sum_plus_num_80 <= 7 and df_close_yes > df_max_high_80:
                g.help_stock_four.append(stock)
    # print("三板确定性反包-选出的股票为:")
    # print(g.help_stock_four)            
            
##选出打板的股票
def pick_high_limit_four(stocks,end_date,pre_date):
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
        if(stock[0:3] == '300'):
            continue
        if _high_limit == _close and _close > _pre_close * 1.02:
            df_panel_2 = get_price(stock, count = 2,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','pre_close'])
            sum_plus_num_2 = (df_panel_2.loc[:,'close'] == df_panel_2.loc[:,'high_limit']).sum()
            # if stock == '002996.XSHE':
            #     print(sum_plus_num_2)
            if sum_plus_num_2 == 2:
                high_limit_stock.append(stock)
    return high_limit_stock
    
##查看他总的涨停数
def count_limit_num_all_four(stock,context):
    date_now =  (context.current_dt+ timedelta(days = -1)).strftime("%Y-%m-%d")#'2021-01-15'#datetime.datetime.now()
    yesterday = (context.current_dt + timedelta(days = -30)).strftime("%Y-%m-%d")
    trade_date = get_trade_days(start_date=yesterday, end_date=date_now, count=None)
    limit_num = 0
    for datenum in trade_date:
        df_panel = get_price(stock, count = 1,end_date=datenum, frequency='daily', fields=['open', 'close','high_limit','money','pre_close'])
        df_close = df_panel['close'].values
        df_high_limit = df_panel['high_limit'].values
        df_pre_close = df_panel['pre_close'].values
        if df_close == df_high_limit and df_close > df_pre_close:
            limit_num = limit_num + 1
    return limit_num
    
    
#五虎底分型
def market_open_five(context):
    time_buy = context.current_dt.strftime('%H:%M:%S')
    date_now =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")#'2021-01-15'#datetime.datetime.now()
    ten_day = datetime.datetime.strptime('09:35:00', '%H:%M:%S').strftime('%H:%M:%S')
    cash = context.portfolio.available_cash
    if len(g.help_stock_five) > 0:
        for stock in g.help_stock_five:
            if cash > 5000 :
                day_open_price = get_current_data()[stock].day_open
                current_price = get_current_data()[stock].last_price
                day_high_limit = get_current_data()[stock].high_limit 
                pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
                df_panel = get_price(stock, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','low',])
                pre_low_price =df_panel['low'].values
                pre_close_price =df_panel['close'].values
                if current_price > day_open_price * 1.02 and current_price > pre_close_price and day_open_price < pre_close_price * 1.05 and day_open_price > pre_close_price * 0.99 and current_price < day_high_limit:
                    print("1."+stock+"买入金额"+str(cash))
                    orders = order_value(stock, cash)
                    if str(orders.status) == 'held':
                        g.help_stock_five.remove(stock)
                        g.help_stock_five_sell.append(stock)
                elif day_open_price > pre_close_price * 1.05 and current_price > pre_close_price * 1.03 and time_buy > ten_day and current_price < day_high_limit:
                    print("2."+stock+"买入金额"+str(cash))
                    orders = order_value(stock, cash)
                    if str(orders.status) == 'held':
                        g.help_stock_five.remove(stock)
                        g.help_stock_five_sell.append(stock)
                    
    time_sell = context.current_dt.strftime('%H:%M:%S')
    cday = datetime.datetime.strptime('14:40:00', '%H:%M:%S').strftime('%H:%M:%S')
    ten_day = datetime.datetime.strptime('10:15:00', '%H:%M:%S').strftime('%H:%M:%S')
    now = context.current_dt
    zeroToday = now - datetime.timedelta(hours=now.hour, minutes=now.minute, seconds=now.second,microseconds=now.microsecond)
    lastToday = zeroToday + datetime.timedelta(hours=9, minutes=31, seconds=00)
    stock_owner = context.portfolio.positions
    if len(stock_owner) > 0 and len(g.help_stock_five_sell) > 0:
        if time_sell > cday :
            for stock_two in stock_owner:
                if context.portfolio.positions[stock_two].closeable_amount > 0:
                    current_price = get_current_data()[stock_two].last_price
                    day_open_price = get_current_data()[stock_two].day_open
                    day_high_limit = get_current_data()[stock_two].high_limit 
                    
                    pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
                    df_panel = get_price(stock_two, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','low','pre_close'])
                    pre_low_price =df_panel['low'].values
                    pre_close_price =df_panel['close'].values
                    pre_pre_close =df_panel['pre_close'].values
                    
                    df_panel_allday = get_price(stock_two, start_date=lastToday, end_date=context.current_dt, frequency='minute', fields=['close','high_limit'])
                    low_allday = df_panel_allday.loc[:,"close"].min()
                    high_allday = df_panel_allday.loc[:,"close"].max()
                    current_price = context.portfolio.positions[stock_two].price #持仓股票的当前价 
                    cost = context.portfolio.positions[stock_two].avg_cost
                    close_data = attribute_history(stock_two, 20, '1d', ['close'])
                    MA20 = close_data['close'].mean()
                    
                    pre_date_init =  (context.portfolio.positions[stock_two].init_time + timedelta(days = 30)).strftime("%Y-%m-%d")
    
                    if current_price < cost * 0.95:
                        print("#1.卖出股票：亏5个点")
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_five_sell.remove(stock_two)
                    elif current_price <  day_open_price * 0.95 and current_price > cost * 1.4:
                        print("#3.卖出股票：放量大阴线")
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_five_sell.remove(stock_two)
                    #高位十字星
                    elif current_price <  high_allday * 0.97 and day_open_price > low_allday * 1.05 and day_open_price < high_allday * 0.95 and current_price > cost * 1.4:
                        print("#3.卖出股票：放量大阴线")
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_five_sell.remove(stock_two)
        else:
            for stock_two in stock_owner:
                if context.portfolio.positions[stock_two].closeable_amount > 0:
                    current_price = get_current_data()[stock_two].last_price
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
                    
                    df_panel_allday = get_price(stock_two, start_date=lastToday, end_date=context.current_dt, frequency='minute', fields=['close','high_limit'])
                    low_allday = df_panel_allday.loc[:,"close"].min()
                    high_allday = df_panel_allday.loc[:,"close"].max()
                    current_price = context.portfolio.positions[stock_two].price #持仓股票的当前价 
                    cost = context.portfolio.positions[stock_two].avg_cost
                    close_data = attribute_history(stock_two, 5, '1d', ['close'])
                    MA5 = close_data['close'].mean()
                    
                    pre_date_init =  (context.portfolio.positions[stock_two].init_time + timedelta(days = 25)).strftime("%Y-%m-%d")
                    current_time = (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
    
                    if current_price < cost * 0.95 and time_sell > ten_day :
                        print("1.卖出股票：亏5个点")
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_five_sell.remove(stock_two)
                    elif sum_limit_num_three == 3 and day_open_price < pre_close_price and current_price < pre_close_price * 0.97:
                        print("2.卖出股票:三个连扳之后的")
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_five_sell.remove(stock_two)
                    elif current_price <  day_open_price * 0.93 and current_price < df_max_high_60 and current_price > cost * 1.3:
                        print("4.卖出股票：放量大阴线")
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_five_sell.remove(stock_two)
                    elif current_price > cost * 1.4 and current_price < MA5:
                        print("6.卖出股票：放量大阴线")
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_five_sell.remove(stock_two)
                    elif current_price < day_open_price * 0.90:
                        print("7.卖出股票：小于最低价的3%")
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_five_sell.remove(stock_two)
                    elif current_price < day_open_price * 0.97 and sum_limit_num_three == 2 and current_price > cost * 1.1:
                        print("8.卖出股票：开盘价小于最低价")
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_five_sell.remove(stock_two)
                    elif current_price < day_open_price * 0.97 and sum_limit_num_three == 2 and time_sell > ten_day:
                        print("#8.卖出股票：开盘价小于最低价")
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_five_sell.remove(stock_two)
                    elif current_time > pre_date_init and current_price < cost * 1.4:
                        print("9.持仓超过25天，卖掉")
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_five_sell.remove(stock_two)
                    elif current_price > cost * 1.4 and len(g.help_stock_seven) > 0:
                        print("9.持仓超过25天，卖掉")
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_five_sell.remove(stock_two)
 

## 开盘前运行函数
def before_market_open_five(context):
    date_now =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")#'2021-01-15'#datetime.datetime.now()
    yesterday = (context.current_dt + timedelta(days = -31)).strftime("%Y-%m-%d")
    trade_date = get_trade_days(start_date=yesterday, end_date=date_now, count=None)
    yes_date_one = trade_date[trade_date.size-1]
    stocks = list(get_all_securities(['stock']).index)
    pick_high_list = pick_high_limit_five(stocks,yes_date_one)
    codelist = filter_st(pick_high_list)
    filter_paused_list =filter_paused_stock(codelist)
    templist = filter_stock_by_days_five(context, filter_paused_list, 1080)
    for stock in templist:
        high_continous_five(stock,trade_date,date_now,context)
    # print("------今天要扫描的股票------")
    # print(g.help_stock_five)
    
#查询最近最高点的位置，之前是不是连续涨
def high_continous_five(stock,trade_date,date_now,context):
    df_panel = get_price(stock, count = 40,end_date=date_now, frequency='daily', fields=['open', 'high', 'close','low', 'high_limit','money'])
    sum_plus_num_40= (df_panel.loc[:,'open'] > df_panel.loc[:,'close'] * 1.14).sum()
    time_high = df_panel['high'].idxmax()
    df_max_high = df_panel["close"].max()
    
    df_panel_40 = get_price(stock, count = 12,end_date=time_high, frequency='daily', fields=['open', 'high', 'close','low', 'high_limit','money'])
    df_max_high_40 = df_panel_40["close"].max()
    df_min_low_40 = df_panel_40["close"].min()
    sum_plus_num_four= (df_panel_40.loc[:,'high'] == df_panel_40.loc[:,'high_limit']).sum()
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

    # if stock == '600776.XSHG':
    #     print("sum_plus_num_two="+str(sum_plus_num_two))
    #     print("sum_down="+str(sum_down))
    #     print("rate_40="+str(rate_40))
    #     print("sum_close_low_pre_close="+str(sum_close_low_pre_close))
    #     print("df_max_high_40="+str(df_max_high_40))
    #     print("df_min_low_40="+str(df_min_low_40))
    #     print("df_max_high="+str(df_max_high))
    #     print("rate_80="+str(rate_80))
    #     print("rate_80="+str(rate_80))
    #     print("rate_80="+str(rate_80))
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
        
        #bool_result = check_first_valley(trade_date,stock)
        # if stock == '600211.XSHG':
        #     print("-------------------------------------")
        #     print("df_close_three="+str(df_close_three))
        #     print("df_high_limit_three="+str(df_high_limit_three))
        #     print("df_open_one="+str(df_open_one))
        #     print("df_close_two="+str(df_close_two))
        #     print("df_close_three="+str(df_close_three))
        #     print("df_high_one="+str(df_high_one))
        #     print("rate_two="+str(rate_two))
        #     print("rate_two_high="+str(rate_two_high))
            #print("bool_result="+str(bool_result))
        #要在60日均线之上
        df_panel_60 = get_price(stock, count = 60,end_date=yes_date_two, frequency='daily', fields=['open', 'close','high_limit','money'])
        df_close_mean_60 = df_panel_60['close'].mean()
        #底分型
        if df_close_three == df_high_limit_three and df_close_two > df_close_mean_60 and rate_two < 0.025 and rate_two_high < 0.08 and df_open_one > df_close_two * 1.02 and df_open_one > df_open_two * 1.02 and df_close_three > df_close_two * 1.07 and df_close_three > df_open_one:
            
            g.help_stock_five.append(stock)

##选出打板的股票
def pick_high_limit_five(stocks,end_date):
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
        
    
##过滤上市时间不满1080天的股票
def filter_stock_by_days_five(context, stock_list, days):
    tmpList = []
    for stock in stock_list :
        days_public=(context.current_dt.date() - get_security_info(stock).start_date).days
        if days_public > days:
            tmpList.append(stock)
    return tmpList


def filter_paused_stock(stock_list):
    current_data = get_current_data()
    stock_list = [stock for stock in stock_list if not current_data[stock].paused]
    return stock_list
    
    
#七龙珠
def market_open_seven(context):
    time_buy = context.current_dt.strftime('%H:%M:%S')
    aday = datetime.datetime.strptime('13:00:00', '%H:%M:%S').strftime('%H:%M:%S')
    if len(g.help_stock_seven) > 0 :
        for stock in g.help_stock_seven:
            #log.info("当前时间 %s" % (context.current_dt))
            #log.info("股票 %s 的最新价: %f" % (stock, get_current_data()[stock].last_price))
            cash = context.portfolio.available_cash
            #print(cash)
            day_open_price = get_current_data()[stock].day_open
            current_price = get_current_data()[stock].last_price
            high_limit_price = get_current_data()[stock].high_limit
            pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
            df_panel = get_price(stock, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'high', 'close','low', 'high_limit','money','pre_close'])
            pre_high_limit = df_panel['high_limit'].values
            pre_close = df_panel['close'].values
            pre_open = df_panel['open'].values
            pre_high = df_panel['high'].values
            pre_low = df_panel['low'].values
            pre_pre_close = df_panel['pre_close'].values
            
            now = context.current_dt
            zeroToday = now - datetime.timedelta(hours=now.hour, minutes=now.minute, seconds=now.second,microseconds=now.microsecond)
            lastToday = zeroToday + datetime.timedelta(hours=9, minutes=31, seconds=00)
            df_panel_allday = get_price(stock, start_date=lastToday, end_date=context.current_dt, frequency='minute', fields=['high','low','close','high_limit','money'])
            low_allday = df_panel_allday.loc[:,"low"].min()
            high_allday = df_panel_allday.loc[:,"high"].max()
            sum_plus_num_two = (df_panel_allday.loc[:,'close'] == df_panel_allday.loc[:,'high_limit']).sum()
            
            ##当前持仓有哪些股票
            if cash > 5000 :
                if current_price > pre_close * 1.05 and day_open_price > pre_close and current_price > day_open_price and current_price > low_allday * 1.03 and current_price < high_limit_price:
                    print("1."+stock+"买入金额"+str(cash))
                    orders = order_value(stock, cash)
                    if str(orders.status) == 'held':
                        g.help_stock_seven.remove(stock)
                        g.help_stock_seven_sell.append(stock)

    time_sell = context.current_dt.strftime('%H:%M:%S')
    cday = datetime.datetime.strptime('14:40:00', '%H:%M:%S').strftime('%H:%M:%S')
    sell_day = datetime.datetime.strptime('11:10:00', '%H:%M:%S').strftime('%H:%M:%S')
    sell_day_10 = datetime.datetime.strptime('13:30:00', '%H:%M:%S').strftime('%H:%M:%S')
    if time_sell > cday:
        stock_owner = context.portfolio.positions
        if len(stock_owner) > 0 and len(g.help_stock_seven_sell) > 0:
            for stock_two in stock_owner:
                if context.portfolio.positions[stock_two].closeable_amount > 0:
                    current_price_list = get_ticks(stock_two,start_dt=None, end_dt=context.current_dt, count=1, fields=['time', 'current', 'high', 'low', 'volume', 'money'])
                    current_price = current_price_list['current'][0]
                    day_open_price = get_current_data()[stock_two].day_open
                    day_high_limit = get_current_data()[stock_two].high_limit 
                    day_low_limit = get_current_data()[stock_two].low_limit 
                    
                    now = context.current_dt
                    zeroToday = now - datetime.timedelta(hours=now.hour, minutes=now.minute, seconds=now.second,microseconds=now.microsecond)
                    lastToday = zeroToday + datetime.timedelta(hours=9, minutes=31, seconds=00)
                    df_panel_allday = get_price(stock_two, start_date=lastToday, end_date=context.current_dt, frequency='minute', fields=['high','low','close','high_limit','money'])
                    low_allday = df_panel_allday.loc[:,"low"].min()
                    high_allday = df_panel_allday.loc[:,"high"].max()
                    sum_plus_num_two = (df_panel_allday.loc[:,'close'] == df_panel_allday.loc[:,'high_limit']).sum()
                    
                    ##获取前一天的收盘价
                    pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
                    df_panel = get_price(stock_two, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','low',])
                    pre_low_price =df_panel['low'].values
                    pre_close_price =df_panel['close'].values
                    
                    #平均持仓成本
                    cost = context.portfolio.positions[stock_two].avg_cost
                    if current_price < high_allday * 0.92 and day_open_price > pre_close_price and current_price > day_low_limit:
                        print("1.卖出股票：小于最高价0.869倍"+str(stock_two))
                        sell_seven(stock_two)
                    elif current_price > cost * 1.3 and sum_plus_num_two < 80 and current_price > day_low_limit:
                        print("2.卖出股票：亏8个点"+str(stock_two))
                        sell_seven(stock_two)
                    elif day_open_price < pre_close_price * 0.98 and current_price < pre_close_price * 0.93 and current_price > day_low_limit:
                        print("3.卖出股票：1.3以下"+str(stock_two))
                        sell_seven(stock_two)
    else:
        stock_owner = context.portfolio.positions
        if len(stock_owner) > 0 and len(g.help_stock_seven_sell) > 0:
            for stock_two in stock_owner:
                if context.portfolio.positions[stock_two].closeable_amount > 0:
                    current_price_list = get_ticks(stock_two,start_dt=None, end_dt=context.current_dt, count=1, fields=['time', 'current', 'high', 'low', 'volume', 'money'])
                    current_price = current_price_list['current'][0]
                    day_open_price = get_current_data()[stock_two].day_open
                    day_high_limit = get_current_data()[stock_two].high_limit 
                    day_low_limit = get_current_data()[stock_two].low_limit 
                    
                    ##获取前一天的收盘价
                    pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
                    df_panel = get_price(stock_two, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','low',])
                    pre_low_price =df_panel['low'].values
                    pre_close_price =df_panel['close'].values
                    now = context.current_dt
                    zeroToday = now - datetime.timedelta(hours=now.hour, minutes=now.minute, seconds=now.second,microseconds=now.microsecond)
                    lastToday = zeroToday + datetime.timedelta(hours=9, minutes=31, seconds=00)
                    df_panel_allday = get_price(stock_two, start_date=lastToday, end_date=context.current_dt, frequency='minute', fields=['high','low','close','high_limit','money'])
                    low_allday = df_panel_allday.loc[:,"low"].min()
                    high_allday = df_panel_allday.loc[:,"high"].max()
                    sum_plus_num_two = (df_panel_allday.loc[:,'close'] == df_panel_allday.loc[:,'high_limit']).sum()
                    
                    current_price = context.portfolio.positions[stock_two].price #持仓股票的当前价 
                    cost = context.portfolio.positions[stock_two].avg_cost
                    
                    df_panel_three = get_price(stock_two, count = 2, end_date=context.current_dt, frequency='minute', fields=['high','low','close','pre_close','high_limit','money'])
                    
                    df_min_close_three = df_panel_three['close'].iloc[0]
                    df_max_close_three = df_panel_three['close'].iloc[1]
                    
                    
                    if current_price < cost * 0.91:
                        print("6.卖出股票：亏5个点"+str(stock_two))
                        sell_seven(stock_two)
                    elif day_open_price < pre_close_price * 0.92 and current_price > pre_close_price * 0.97 and current_price > day_low_limit:
                        print("add.高位放量，请走！"+str(day_open_price))
                        sell_seven(stock_two)
                    elif high_allday > pre_close_price * 1.09 and current_price < day_open_price and day_open_price < day_high_limit * 0.95 and current_price < cost * 1.2 and current_price > day_low_limit:
                        print("8.高位放量，请走！"+str(day_open_price))
                        sell_seven(stock_two)
                    elif current_price > cost * 1.25 and current_price < day_high_limit * 0.95 and time_sell > sell_day and current_price > day_low_limit:
                        print("9.挣够25%，高位放量，请走！"+str(day_open_price))
                        sell_seven(stock_two)
                    elif current_price < high_allday * 0.93 and high_allday > pre_close_price * 1.06 and time_sell > sell_day_10 and current_price > day_low_limit:
                        print("11.挣够25%，高位放量，请走！"+str(day_open_price))
                        sell_seven(stock_two)
                    elif df_max_close_three < df_min_close_three * 0.95 and current_price < pre_close_price * 0.98 and current_price > day_low_limit:
                        print("11.挣够25%，高位放量，请走！"+str(day_open_price))
                        sell_seven(stock_two)


def sell_seven(stock_two):
    orders = order_target(stock_two, 0)
    if str(orders.status) == 'held':
        g.help_stock_seven_sell.remove(stock_two)

## 选出连续涨停超过3天的，最近一天是阴板的
def before_market_open_seven(context):
    date_now =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")#'2021-01-15'#datetime.datetime.now()
    yesterday = (context.current_dt + timedelta(days = -90)).strftime("%Y-%m-%d")
    trade_date = get_trade_days(start_date=yesterday, end_date=date_now, count=None)
    stocks = list(get_all_securities(['stock']).index)
    end_date = trade_date[trade_date.size-1]
    pre_date = trade_date[trade_date.size-3]
    #选出昨天是涨停板的个股
    continuous_price_limit = pick_high_limit_seven(stocks,end_date,pre_date)

    filter_st_stock = filter_st(continuous_price_limit)
    templist = filter_stock_by_days_seven(context,filter_st_stock,150)
    print("选出的连扳股票")
    print(templist)
    for stock in templist:
        ##查询昨天的股票是否阴板
        stock_date=trade_date[trade_date.size-2]
        df_panel = get_price(stock, count = 1,end_date=stock_date, frequency='daily', fields=['open', 'close','high_limit','money','low','high','pre_close'])
        df_close = df_panel['close'].values
        df_high = df_panel['high'].values
        df_low = df_panel['low'].values
        df_open = df_panel['open'].values
        df_pre_close = df_panel['pre_close'].values
        df_high_limit = df_panel['high_limit'].values
        df_money = df_panel['money'].values
        #查询昨天的close价格
        df_panel_yes = get_price(stock, count = 1,end_date=end_date, frequency='daily', fields=['open', 'close','high_limit','money','low','high','pre_close'],skip_paused=True)
        df_close_yes = df_panel_yes['close'].values
        df_money_yes = df_panel_yes['money'].values
        # if stock == '600956.XSHG':
        #     print(df_open)
        #     print(df_close)
        #     print(df_high)
        #     print(df_money_yes)
        #     print(df_money * 0.65)
        pre_date_two = trade_date[trade_date.size-8]
        if df_close < df_high_limit * 0.98:
            g.help_stock_seven.append(stock)
    print("被选出的股票为:")
    print(g.help_stock_seven)            
            
##选出打板的股票
def pick_high_limit_seven(stocks,end_date,pre_date):
    df_panel = get_price(stocks, count = 1,end_date=end_date, frequency='daily', fields=['open', 'close','high_limit','money','pre_close','low'])
    df_close = df_panel['close']
    df_open = df_panel['open']
    df_high_limit = df_panel['high_limit']
    df_pre_close = df_panel['pre_close']
    df_low = df_panel['low']
    high_limit_stock = []
    for stock in (stocks):
        _high_limit = (df_high_limit[stock].values)
        _close = (df_close[stock].values)
        _open =  (df_open[stock].values)
        _pre_close = (df_pre_close[stock].values)
        _low = (df_low[stock].values)
        if(stock[0:3] == '300'):
            continue
        if _high_limit == _close and _close > _pre_close * 1.02:
            df_panel_2 = get_price(stock, count = 2,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','pre_close'],skip_paused=True)
            sum_plus_num_2 = (df_panel_2.loc[:,'close'] == df_panel_2.loc[:,'high_limit']).sum()
            
            df_panel_10 = get_price(stock, count = 10,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','pre_close'],skip_paused=True)
            sum_plus_num_10 = (df_panel_10.loc[:,'close'] == df_panel_10.loc[:,'high_limit']).sum()
            
            if sum_plus_num_2 == 2 and sum_plus_num_10 <= 5:
                if _open > _pre_close * 1.04:
                    high_limit_stock.append(stock)
    return high_limit_stock
    
##去除st的股票
def filter_st(codelist):
    current_data = get_current_data()
    codelist = [code for code in codelist if not current_data[code].is_st]
    return codelist
    
##过滤上市时间不满1080天的股票
def filter_stock_by_days_seven(context, stock_list, days):
    tmpList = []
    for stock in stock_list :
        days_public=(context.current_dt.date() - get_security_info(stock).start_date).days
        market_cap = get_circulating_market_cap(stock)
        market_cap_num = market_cap['circulating_market_cap'].values
        if days_public > days and market_cap_num > 10 and market_cap_num < 350:
            tmpList.append(stock)
    return tmpList
    
##获取个股流通市值数据
def get_circulating_market_cap(stock_list):
    query_list = [stock_list]
    q = query(valuation.code,valuation.circulating_market_cap).filter(valuation.code.in_(query_list))
    market_cap = get_fundamentals(q)
    market_cap.set_index('code', inplace=True)
    return market_cap

##过滤上市时间不满1080天的股票
def filter_stock_by_days(context, stock_list, days):
    tmpList = []
    for stock in stock_list :
        days_public=(context.current_dt.date() - get_security_info(stock).start_date).days
        if days_public > days:
            tmpList.append(stock)
    return tmpList
    
# def turn_ratio(stock,end_date):    
#     q = query(valuation.day,valuation.code,valuation.turnover_ratio).filter(valuation.code == stock,valuation.day == end_date).limit(1)
#     aa=finance.run_query(q)
#     #print(aa)
#     return aa   #换手率
    

## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #今天交易的股票有
    print("-------今天交易的股票有--------")
    print("four="+str(g.help_stock_four))
    print("four_sell="+str(g.help_stock_four_sell))
    print("five="+str(g.help_stock_five))
    print("five_sell="+str(g.help_stock_five_sell))
    print("seven="+str(g.help_stock_seven))
    print("seven_sell="+str(g.help_stock_seven_sell))
    
    print("现在开始清空每日的复盘情况--------->>")
    g.help_stock_four = []

    g.help_stock_five = []

    g.help_stock_seven = []

    print("#four="+str(g.help_stock_four))
    print("#four_sell="+str(g.help_stock_four_sell))
    print("#five="+str(g.help_stock_five))
    print("#five_sell="+str(g.help_stock_five_sell))
    print("seven="+str(g.help_stock_seven))
    print("seven_sell="+str(g.help_stock_seven_sell))
    log.info('一天结束')
    log.info('##############################################################')
