# 克隆自聚宽文章：https://www.joinquant.com/post/36382
# 标题：龙头首阴战法改版二
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
    
    g.help_stock = []
    g.help_stock_sell = []
    
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
    before_market_open(context)
    
    help_stock_msg = "今日选出股票："
    help_stock_msg_one = "龙头首阴战法："
    if len(g.help_stock) > 0:
        for stock in g.help_stock:
            help_stock_msg_one =  help_stock_msg_one + stock + "; "
        help_stock_msg = help_stock_msg + help_stock_msg_one

    # sell类型     
    help_stock_msg_sell = "#今日持仓的股票："
    help_stock_msg_one_sell = "--龙头首阴战法持仓："
    if len(g.help_stock_sell) > 0:
        for stock in g.help_stock_sell:
            help_stock_msg_one_sell =  help_stock_msg_one_sell + stock + "; "
        help_stock_msg_sell = help_stock_msg_sell + help_stock_msg_one_sell
        
    ##每日买卖持仓
    print(help_stock_msg)
    print(help_stock_msg_sell)


## 开盘时运行函数
def market_open(context):
    
    #First 龙头 首阴战法
    market_open_one(context)
    
    
def market_open_one(context):
    time_buy = context.current_dt.strftime('%H:%M:%S')
    aday_one = datetime.datetime.strptime('09:40:00', '%H:%M:%S').strftime('%H:%M:%S')
    aday_two = datetime.datetime.strptime('11:20:00', '%H:%M:%S').strftime('%H:%M:%S')
    if len(g.help_stock) > 0:
        for stock in g.help_stock:
            #log.info("当前时间 %s" % (context.current_dt))
            #log.info("股票 %s 的最新价: %f" % (stock, get_current_data()[stock].last_price))
            cash = context.portfolio.available_cash
            #print(cash)
            current_price = get_current_data()[stock].last_price
            day_open_price = get_current_data()[stock].day_open
            day_high_limit = get_current_data()[stock].high_limit 
            pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
            df_panel = get_price(stock, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'high', 'close','low', 'high_limit','money'])
            pre_high_limit = df_panel['high_limit'].values
            pre_close = df_panel['close'].values
            pre_high = df_panel['high'].values
            pre_low = df_panel['low'].values

            #First-buy
            ##当前持仓有哪些股票
            if cash > 20000 :
                if current_price > pre_high_limit * 0.99 and current_price > pre_close * 1.03 and day_open_price > pre_close * 1.07 and pre_close < pre_high_limit and current_price < day_high_limit:
                    print("1."+stock+"买入金额"+str(cash))
                    orders = order_value(stock, cash)
                    if str(orders.status) == 'held':
                        g.help_stock.remove(stock)
                        g.help_stock_sell.append(stock)
                elif current_price > pre_high_limit * 0.99 and time_buy > aday_one and time_buy < aday_two and current_price > day_open_price and current_price > pre_close * 1.03 and day_open_price > pre_low and pre_close < pre_high_limit and current_price < day_high_limit:
                    print("2."+stock+"买入金额"+str(cash))
                    orders = order_value(stock, cash)
                    if str(orders.status) == 'held':
                        g.help_stock.remove(stock)
                        g.help_stock_sell.append(stock)
                elif pre_close == pre_high_limit and current_price > pre_high_limit * 1.06 and day_open_price > pre_high_limit * 0.95 and time_buy < aday_two and current_price < day_high_limit:
                    print("2."+stock+"买入金额"+str(cash))
                    orders = order_value(stock, cash)
                    if str(orders.status) == 'held':
                        g.help_stock.remove(stock)
                        g.help_stock_sell.append(stock)
    time_sell = context.current_dt.strftime('%H:%M:%S')
    cday = datetime.datetime.strptime('14:40:00', '%H:%M:%S').strftime('%H:%M:%S')
    if time_sell > cday:
        stock_owner = context.portfolio.positions
        if len(stock_owner) > 0 and len(g.help_stock_sell) > 0:
            for stock_two in stock_owner:
                if context.portfolio.positions[stock_two].closeable_amount > 0:
                    #current_price_list = get_ticks(stock_two,start_dt=None, end_dt=context.current_dt, count=1, fields=['time', 'current', 'high', 'low', 'volume', 'money'])
                    current_price = get_current_data()[stock_two].last_price
                    day_open_price = get_current_data()[stock_two].day_open
                    day_high_limit = get_current_data()[stock_two].high_limit 
                    day_low_limit = get_current_data()[stock_two].low_limit

                    #查询当天的最高价
                    df = get_price(stock_two, start_date=context.portfolio.positions[stock_two].init_time,end_date=context.current_dt, frequency='minute', fields=['close'],skip_paused=True)
                    df_max_high = df["close"].max()
                    df_min_high = df["close"].min()
                    ##获取前一天的收盘价
                    pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
                    df_panel = get_price(stock_two, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','low',])
                    pre_low_price =df_panel['low'].values
                    pre_close_price =df_panel['close'].values
                    df_panel_2 = get_price(stock_two, count = 2,end_date=pre_date, frequency='daily', fields=['high', 'close','high_limit','money'],skip_paused=True)
                    sum_plus_num_2 = (df_panel_2.loc[:,'close'] == df_panel_2.loc[:,'high_limit'] ).sum()
                    #平均持仓成本
                    cost = context.portfolio.positions[stock_two].avg_cost

                    if current_price < df_max_high * 0.869 and day_open_price > pre_close_price and current_price > day_low_limit:
                        print("1.卖出股票：小于最高价0.869倍")
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_sell.remove(stock_two)
                    elif current_price < cost * 0.92 and current_price > day_low_limit:
                        print("卖出股票：亏8个点")
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_sell.remove(stock_two)
                    elif current_price < cost * 1.2 and current_price < df_max_high * 0.92 and day_open_price < df_max_high * 0.968 and current_price < day_open_price and current_price > day_low_limit:
                        print("3.卖出股票：1.3以下")
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_sell.remove(stock_two)
                    elif df_min_high/df_max_high < 0.86 and current_price < cost * 1.20 and df_min_high < pre_close_price * 0.95 and current_price < day_open_price and current_price < pre_close_price and current_price > day_low_limit:
                        print("4.炸板卖出股票：开盘价为"+str(day_open_price))
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_sell.remove(stock_two)
                    elif current_price > cost * 1.30 and current_price < df_max_high * 0.95 and current_price > df_min_high * 1.05 and sum_plus_num_2 == 2 and current_price > pre_close_price and current_price > day_low_limit:
                        print("#4.炸板卖出股票：开盘价为"+str(day_open_price))
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_sell.remove(stock_two)
    else:
        stock_owner = context.portfolio.positions
        if len(stock_owner) > 0 and len(g.help_stock_sell) > 0:
            for stock_two in stock_owner:
                if context.portfolio.positions[stock_two].closeable_amount > 0:
                    current_price = get_current_data()[stock_two].last_price
                    day_open_price = get_current_data()[stock_two].day_open
                    day_high_limit = get_current_data()[stock_two].high_limit 
                    day_low_limit = get_current_data()[stock_two].low_limit
                    
                    #查询当天的最高价
                    df = get_price(stock_two, start_date=context.portfolio.positions[stock_two].init_time,end_date=context.current_dt, frequency='minute', fields=['high'],skip_paused=True)
                    df_max_high = df["high"].max()
                    
                    ##获取前一天的收盘价
                    pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
                    df_panel = get_price(stock_two, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','low',])
                    pre_low_price =df_panel['low'].values
                    pre_close_price =df_panel['close'].values
                    num_limit_stock = count_limit_num_all(stock_two,context)
                    #查看是否连续涨停超过5次，只有后面低于前一交易日就卖
                    num_limit_stock_two = count_limit_num(stock_two,context)
                    df = get_price(stock_two, start_date=context.portfolio.positions[stock_two].init_time,end_date=context.previous_date, frequency='minute', fields=['close'],skip_paused=True)
                    df_max_high = df["close"].max()  #从买入至今的最高价
                    current_price = context.portfolio.positions[stock_two].price #持仓股票的当前价 
                    cost = context.portfolio.positions[stock_two].avg_cost

                    if num_limit_stock >= 12 and current_price < df_max_high * 0.95 and day_open_price > pre_close_price and current_price > day_low_limit:
                        print("5.卖出股票：12个板以上"+str(num_limit_stock))
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_sell.remove(stock_two)
                    elif current_price < cost * 0.92 and current_price > day_low_limit:
                        print("6.卖出股票：亏8个点"+str(num_limit_stock))
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_sell.remove(stock_two)
                    elif num_limit_stock_two > 5 and day_open_price < pre_close_price * 1.01 and current_price > 1.3 * cost and current_price < pre_close_price * 0.95 and current_price > day_low_limit:
                        print("7.查看是否连续涨停超过5次，只有后面低于前一交易日就卖"+str(num_limit_stock_two))
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_sell.remove(stock_two)
                    elif day_open_price == day_high_limit and current_price < pre_close_price and current_price > day_low_limit:
                        print("8.高位放量，请走！"+str(day_open_price))
                        orders = order_target(stock_two, 0)
                        if str(orders.status) == 'held':
                            g.help_stock_sell.remove(stock_two)
    
    
## 龙头首阴战法
def before_market_open(context):
    date_now =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")#'2021-01-15'#datetime.datetime.now()
    yesterday = (context.current_dt + timedelta(days = -90)).strftime("%Y-%m-%d")
    trade_date = get_trade_days(start_date=yesterday, end_date=date_now, count=None)
    stocks = list(get_all_securities(['stock']).index)
    end_date = trade_date[trade_date.size-1]
    pre_date = trade_date[trade_date.size-2]
    continuous_price_limit = pick_high_limit(stocks,pre_date)
    filter_st_stock = filter_st(continuous_price_limit)
    templist = filter_stock_by_days(context,filter_st_stock,1080)
    pre_date_six = trade_date[trade_date.size-6]
    # print("选出的连扳股票")
    # print(templist)
    for stock in templist:
        
        ##查询昨天的股票是否阴板和阳板
        stock_date=trade_date[trade_date.size-1]
        df_panel = get_price(stock, count = 1,end_date=stock_date, frequency='daily', fields=['open', 'close','high_limit','money','low','high','pre_close'])
        df_close = df_panel['close'].values
        df_high = df_panel['high'].values
        df_low = df_panel['low'].values
        df_open = df_panel['open'].values
        df_pre_close = df_panel['pre_close'].values
        df_high_limit = df_panel['high_limit'].values
        df_panel_8 = get_price(stock, count = 8,end_date=end_date, frequency='daily', fields=['high', 'close','high_limit','money'],skip_paused=True)
        sum_plus_num_8 = (df_panel_8.loc[:,'close'] == df_panel_8.loc[:,'high_limit'] ).sum()
        #查询大前天的close价格
        if df_close < df_high * 0.976 and df_close >= df_pre_close and df_open == df_high:
            number_stock = count_limit_num(stock,context)
            if stock == '603069.XSHG':
                print("---------hahahahahha-------")
                print(number_stock)
                print(sum_plus_num_8)
            if number_stock >=2 and sum_plus_num_8 <= 6:
                g.help_stock.append(stock)
        elif df_open < 0.95 * df_high and df_close == df_high_limit and df_open > df_pre_close * 0.986 and df_low < df_pre_close * 0.92 and df_close == df_high_limit:
            df_panel_30 = get_price(stock, count = 30,end_date=pre_date_six, frequency='daily', fields=['high', 'close','high_limit','money'],skip_paused=True)
            sum_plus_num_30 = (df_panel_30.loc[:,'close'] == df_panel_30.loc[:,'high_limit'] ).sum()
            if sum_plus_num_8 <=5 and sum_plus_num_30 <= 4:
                g.help_stock.append(stock)
    # print("---------(锤型结构)典型案例三:被选出的股票为:---------")
    # print(g.help_stock)            
            

##查看他的连扳天数，还需要不涨停的时候，前面的交易日是非涨停的
def count_limit_num(stock,context):
    date_now =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")#'2021-01-15'#datetime.datetime.now()
    yesterday = (context.current_dt + timedelta(days = -50)).strftime("%Y-%m-%d")
    df_panel_close = get_price(stock, count = 1,end_date=date_now, frequency='daily', fields=['open', 'close','high','money'])
    df_close_now = df_panel_close['high'].values
    if stock == '603069.XSHG':
        print("日期")
        print(date_now)
        print(df_close_now)
    trade_date = get_trade_days(start_date=yesterday, end_date=date_now, count=None)
    limit_num = 0
    date_size = 3
    trade_date_break = (context.current_dt).strftime("%Y-%m-%d")
    #print(trade_date)
    for datenum in trade_date:
        pre_date=trade_date[trade_date.size-date_size]
        pre_date_two=trade_date[trade_date.size-date_size-1]
        # if stock == '600812.XSHG':
        #     print("002819.XSHE")
        #     print(pre_date)
        #     print(pre_date_two)
        #查询当天的
        df_panel = get_price(stock, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money'])
        df_close = df_panel['close'].values
        df_high_limit = df_panel['high_limit'].values
        #查询前一天的
        df_panel_two = get_price(stock, count = 1,end_date=pre_date_two, frequency='daily', fields=['open', 'close','high_limit','money'])
        df_close_two = df_panel_two['close'].values
        df_high_limit_two = df_panel_two['high_limit'].values
        # if stock == '600983.XSHG':
        #     print(stock+"pre_date="+str(pre_date)+"df_close="+str(df_close)+"df_high_limit="+str(df_high_limit))
        if df_close == df_high_limit and df_close > df_close_two * 1.05:
            limit_num = limit_num + 1
            date_size = date_size + 1
        else:
            trade_date_break = trade_date[trade_date.size-date_size]
            pre_trade_date_break = trade_date[trade_date.size-date_size-1]
            df_panel_pre = get_price(stock, count = 1,end_date=pre_trade_date_break, frequency='daily', fields=['open', 'close','high_limit','money','pre_close'])
            df_close_pre = df_panel_pre['close'].values
            df_high_limit_pre = df_panel_pre['high_limit'].values
            df_pre_close = df_panel_pre['pre_close'].values
            if df_close_pre == df_high_limit_pre and df_close_pre > df_pre_close * 1.05:
                limit_num =0
                
            df_panel_all = get_price(stock, count = 250,end_date=trade_date_break, frequency='daily', fields=['high', 'close','high_limit','money'])
            high_allday = df_panel_all.loc[:,"high"].max()
            
            if df_close_now < high_allday:
                limit_num =0
            #启动前之前不能大于3个板
            df_panel_30 = get_price(stock, count = 30,end_date=trade_date_break, frequency='daily', fields=['high', 'close','high_limit','money'],skip_paused=True)
            low_allday = df_panel_all.loc[:,"close"].min()
            sum_plus_num_two = (df_panel_30.loc[:,'close'] == df_panel_30.loc[:,'high_limit']).sum()
            # close_high_allday = df_panel_all.loc[:,"close"].max()
            # close_low_allday = df_panel_all.loc[:,"close"].min()
            # rate_30 = (close_high_allday - close_low_allday)
            #count_limit_num = count_limit_num_before(stock,trade_date_break)
            if sum_plus_num_two > 4:
                limit_num = 0
            break
    return limit_num
    
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

##查看他总的涨停数
def count_limit_num_before(stock,date_come):
    #date_now = datetime.datetime.strptime(date_come, '%Y-%m-%d')
    #date_now =  date_come.strftime("%Y-%m-%d")#'2021-01-15'#datetime.datetime.now()
    start_date = (datetime.datetime.strptime(date_come.strftime('%Y-%m-%d'), '%Y-%m-%d') + timedelta(days = -30)).strftime("%Y-%m-%d")
    trade_date = get_trade_days(start_date=start_date, end_date=date_come, count=None)
    limit_num = 0
    #print(date_come)
    for datenum in trade_date:
        df_panel = get_price(stock, count = 1,end_date=datenum, frequency='daily', fields=['open', 'close','high_limit','money','pre_close'])
        df_close = df_panel['close'].values
        df_high_limit = df_panel['high_limit'].values
        df_pre_close = df_panel['pre_close'].values
        if df_close == df_high_limit and df_close > df_pre_close * 1.05:
            limit_num = limit_num + 1
    return limit_num

##选出打板的股票
def pick_high_limit(stocks,pre_date):
    df_panel = get_price(stocks, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money'])
    df_close = df_panel['close']
    df_open = df_panel['open']
    df_high_limit = df_panel['high_limit']
    df_money = df_panel['money']
    high_limit_stock = []
    for stock in (stocks):
        _high_limit = (df_high_limit[stock].values)
        _close = (df_close[stock].values)
        _open =  (df_open[stock].values)
        _money = (df_money[stock].values)
        if(stock[0:3] == '300'):
            continue
        if _high_limit == _close :
            high_limit_stock.append(stock)
    return high_limit_stock
    
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
    #今天交易的股票有
    print("-------今天交易的股票有--------")
    print("one="+str(g.help_stock))
    print("one_sell="+str(g.help_stock_sell))
    
    print("现在开始清空每日的复盘情况--------->>")
    g.help_stock = []


    print("#one="+str(g.help_stock))
    print("#one_sell="+str(g.help_stock_sell))
    log.info('一天结束')
    log.info('##############################################################')
