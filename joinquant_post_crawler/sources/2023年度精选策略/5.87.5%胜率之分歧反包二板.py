# 克隆自聚宽文章：https://www.joinquant.com/post/34048
# 标题：87.5%胜率之分歧反包二板
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
    run_daily(market_open, time='every_bar', reference_security='000300.XSHG')
    #run_daily(market_run_sell, time='every_bar', reference_security='000300.XSHG')

      # 收盘后运行before_open
    #run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')

## 开盘时运行函数
def market_open(context):
    time_buy = context.current_dt.strftime('%H:%M:%S')
    aday = datetime.datetime.strptime('13:00:00', '%H:%M:%S').strftime('%H:%M:%S')
    if len(help_stock) > 0 :
        for stock in help_stock:
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
            
            pre_date_two =  (context.current_dt + timedelta(days = -10)).strftime("%Y-%m-%d")
            df_panel_150 = get_price(stock, count = 150,end_date=pre_date_two, frequency='daily', fields=['open', 'close','high_limit','money','low','high','pre_close'])
            df_max_high_150 = df_panel_150["close"].max()
            ##当前持仓有哪些股票
            if cash > 5000 :

                if sum_plus_num_two > 10 and current_price < high_limit_price and current_price > pre_close * 1.08:
                    print("1."+stock+"买入金额"+str(cash))
                    send_micromessage("2.跳空首阴反包---"+stock)    
                    orders = order_value(stock, cash)
                    if str(orders.status) == 'held':
                        help_stock.remove(stock)
                elif day_open_price > pre_close * 1.05 and current_price > day_open_price * 1.02 and current_price > df_max_high_150 and current_price < high_limit_price:
                    print("2."+stock+"买入金额"+str(cash))
                    send_micromessage("2.跳空首阴反包---"+stock)    
                    orders = order_value(stock, cash)
                    if str(orders.status) == 'held':
                        help_stock.remove(stock)


    time_sell = context.current_dt.strftime('%H:%M:%S')
    cday = datetime.datetime.strptime('14:40:00', '%H:%M:%S').strftime('%H:%M:%S')
    sell_day = datetime.datetime.strptime('11:10:00', '%H:%M:%S').strftime('%H:%M:%S')
    sell_day_10 = datetime.datetime.strptime('13:30:00', '%H:%M:%S').strftime('%H:%M:%S')
    if time_sell > cday:
        stock_owner = context.portfolio.positions
        if len(stock_owner) > 0:
            for stock_two in stock_owner:
                if context.portfolio.positions[stock_two].closeable_amount > 0:
                    current_price_list = get_ticks(stock_two,start_dt=None, end_dt=context.current_dt, count=1, fields=['time', 'current', 'high', 'low', 'volume', 'money'])
                    current_price = current_price_list['current'][0]
                    day_open_price = get_current_data()[stock_two].day_open
                    day_high_limit = get_current_data()[stock_two].high_limit 
                    
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
                    if current_price < high_allday * 0.92 and day_open_price > pre_close_price:
                        print("1.卖出股票：小于最高价0.869倍"+str(stock_two))
                        order_target(stock_two, 0)
                    elif current_price > cost * 1.3 and sum_plus_num_two < 80:
                        print("2.卖出股票：亏8个点"+str(stock_two))
                        order_target(stock_two, 0)
                    elif day_open_price < pre_close_price * 0.98 and current_price < pre_close_price * 0.93:
                        print("3.卖出股票：1.3以下"+str(stock_two))
                        order_target(stock_two, 0)
    else:
        stock_owner = context.portfolio.positions
        if len(stock_owner) > 0:
            for stock_two in stock_owner:
                if context.portfolio.positions[stock_two].closeable_amount > 0:
                    current_price_list = get_ticks(stock_two,start_dt=None, end_dt=context.current_dt, count=1, fields=['time', 'current', 'high', 'low', 'volume', 'money'])
                    current_price = current_price_list['current'][0]
                    day_open_price = get_current_data()[stock_two].day_open
                    day_high_limit = get_current_data()[stock_two].high_limit 
                    
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
                    
                    if current_price < cost * 0.91:
                        print("6.卖出股票：亏5个点"+str(stock_two))
                        order_target(stock_two, 0)
                    elif current_price < pre_close_price and time_sell > sell_day :
                        print("7.高位放量，请走！"+str(day_open_price))
                        order_target(stock_two, 0)
                    elif day_open_price < pre_close_price * 0.95 and current_price > pre_close_price * 0.97:
                        print("add.高位放量，请走！"+str(day_open_price))
                        order_target(stock_two, 0)
                    elif high_allday > pre_close_price * 1.09 and current_price < day_open_price and day_open_price < day_high_limit * 0.95 and current_price < cost * 1.2:
                        print("8.高位放量，请走！"+str(day_open_price))
                        order_target(stock_two, 0)
                    elif current_price > cost * 1.25 and current_price < day_high_limit * 0.95 and time_sell > sell_day:
                        print("9.挣够25%，高位放量，请走！"+str(day_open_price))
                        order_target(stock_two, 0)
                    elif day_open_price < pre_close_price * 0.98 and current_price < high_allday * 0.95 and high_allday > pre_close_price * 1.05:
                        print("10.挣够25%，高位放量，请走！"+str(day_open_price))
                        order_target(stock_two, 0)
                    elif current_price < high_allday * 0.93 and high_allday > pre_close_price * 1.06 and time_sell > sell_day_10:
                        print("11.挣够25%，高位放量，请走！"+str(day_open_price))
                        order_target(stock_two, 0)
                    elif day_open_price < pre_close_price * 0.97 and current_price > pre_close_price:
                        print("10.挣够25%，高位放量，请走！"+str(day_open_price))
                        order_target(stock_two, 0)
    if time_sell > cday and len(help_stock) > 0:
        instead_stock = help_stock
        for stock_remove in instead_stock:
            help_stock.remove(stock_remove)

def send_micromessage(result_in):
   #调用send_message
   send_message(result_in)

## 选出连续涨停超过3天的，最近一天是阴板的
def before_market_open(context):
    date_now =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")#'2021-01-15'#datetime.datetime.now()
    yesterday = (context.current_dt + timedelta(days = -90)).strftime("%Y-%m-%d")
    trade_date = get_trade_days(start_date=yesterday, end_date=date_now, count=None)
    stocks = list(get_all_securities(['stock']).index)
    end_date = trade_date[trade_date.size-1]
    pre_date = trade_date[trade_date.size-3]
    #选出昨天是涨停板的个股
    continuous_price_limit = pick_high_limit(stocks,end_date,pre_date)

    filter_st_stock = filter_st(continuous_price_limit)
    templist = filter_stock_by_days(context,filter_st_stock,150)
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
        #查询昨天的close价格
        df_panel_yes = get_price(stock, count = 1,end_date=end_date, frequency='daily', fields=['open', 'close','high_limit','money','low','high','pre_close'])
        df_close_yes = df_panel_yes['close'].values
        count_limit = count_limit_num_all(stock,context)
        if stock == '002400.XSHE':
            print(df_open)
            print(df_close)
            print(df_high)
            print(count_limit)
        pre_date_two = trade_date[trade_date.size-8]
        if df_open >= df_close and df_open < df_high and count_limit <= 5 and df_close_yes > df_high:
            df_panel_80 = get_price(stock, count = 45,end_date=pre_date_two, frequency='daily', fields=['open', 'close','high_limit','money','low','high','pre_close'])
            df_max_high_80 = df_panel_80["close"].max()
            df_min_low_80 = df_panel_80["close"].min()
            abs_sum_80 = (df_panel_80.loc[:,'close'] - df_panel_80.loc[:,'open']).abs() / ((df_panel_80.loc[:,'open']+df_panel_80.loc[:,'close']) / 2)
            abs_sum_num_803 = (abs_sum_80 < 0.03).sum()
            sum_plus_num_80 = (df_panel_80.loc[:,'close'] == df_panel_80.loc[:,'high_limit']).sum()
            rate_80 = (df_max_high_80 - df_min_low_80) / df_min_low_80
            if stock == '002996.XSHE':
                print(df_close)
                print(df_max_high_80)
                print(rate_80)
                print(abs_sum_num_803)
            if rate_80 < 0.5 and abs_sum_num_803 > 25 and sum_plus_num_80 <= 7 and df_close_yes > df_max_high_80:
                help_stock.append(stock)
    print("被选出的股票为:")
    print(help_stock)            
            
##选出打板的股票
def pick_high_limit(stocks,end_date,pre_date):
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
            if stock == '002996.XSHE':
                print(sum_plus_num_2)
            if sum_plus_num_2 == 2:
                high_limit_stock.append(stock)
    return high_limit_stock
    
##查看他总的涨停数
def count_limit_num_all(stock,context):
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


    
##去除st的股票
def filter_st(codelist):
    current_data = get_current_data()
    codelist = [code for code in codelist if not current_data[code].is_st]
    return codelist

##过滤上市时间不满1080天的股票
def filter_stock_by_days(context, stock_list, days):
    tmpList = []
    for stock in stock_list :
        days_public=(context.current_dt.date() - get_security_info(stock).start_date).days
        if days_public > days:
            tmpList.append(stock)
    return tmpList


## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    log.info('一天结束')
    log.info('##############################################################')
