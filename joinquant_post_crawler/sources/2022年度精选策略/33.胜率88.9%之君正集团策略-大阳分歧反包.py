# 克隆自聚宽文章：https://www.joinquant.com/post/36885
# 标题：胜率88.9%之君正集团策略-大阳分歧反包
# 作者：游资小码哥

# 导入函数库
from jqdata import *


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
    g.help_stock = []
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
    aday = datetime.datetime.strptime('09:55:00', '%H:%M:%S').strftime('%H:%M:%S')
    if len(g.help_stock) > 0 and time_buy < aday:
        for stock in g.help_stock:
            #log.info("当前时间 %s" % (context.current_dt))
            #log.info("股票 %s 的最新价: %f" % (stock, get_current_data()[stock].last_price))
            cash = context.portfolio.available_cash
            #print(cash)
            current_price_list = get_ticks(stock,start_dt=None, end_dt=context.current_dt, count=1, fields=['time', 'current', 'high', 'low', 'volume', 'money'])
            current_price = current_price_list['current'][0]
            low_price = current_price_list['low'][0] 
            day_open_price = get_current_data()[stock].day_open
            pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
            df_panel = get_price(stock, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'high', 'close','low', 'high_limit','money'])
            pre_high_limit = df_panel['high_limit'].values
            pre_close = df_panel['close'].values
            pre_open = df_panel['low'].values
            pre_high = df_panel['high'].values
            ##当前持仓有哪些股票
            if cash > 5000 :
                if current_price > pre_high and current_price > pre_close * 1.06 and day_open_price > pre_close * 0.96:
                    print("1."+stock+"买入金额"+str(cash))
                    orders = order_value(stock, cash)
                    if str(orders.status) == 'held':
                        g.help_stock.remove(stock)

    time_sell = context.current_dt.strftime('%H:%M:%S')
    cday = datetime.datetime.strptime('14:40:00', '%H:%M:%S').strftime('%H:%M:%S')
    stock_owner = context.portfolio.positions
    if len(stock_owner) > 0:
        for stock_two in stock_owner:
            current_price_list = get_ticks(stock_two,start_dt=None, end_dt=context.current_dt, count=1, fields=['time', 'current', 'high', 'low', 'volume', 'money'])
            current_price = current_price_list['current'][0]
            day_open_price = get_current_data()[stock_two].day_open
            day_high_limit = get_current_data()[stock_two].high_limit 
            
            #查询当天的最高价
            df = get_price(stock_two, start_date=context.portfolio.positions[stock_two].init_time,end_date=context.current_dt, frequency='minute', fields=['high','low'],skip_paused=True)
            df_max_high = df["high"].max()
            df_min_high = df["low"].min()
            ##获取前一天的收盘价
            pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
            df_panel = get_price(stock_two, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','low',])
            pre_low_price =df_panel['low'].values
            pre_close_price =df_panel['close'].values
            #平均持仓成本
            cost = context.portfolio.positions[stock_two].avg_cost
            # print("----------------------------------")
            # print("current_price="+str(current_price))
            # print("day_open_price="+str(day_open_price))
            # print("pre_close_price="+str(pre_close_price))
            # print("df_max_high="+str(df_max_high))
            # print("=====================================")
            if current_price < cost * 0.85:
                print("1.卖出股票：小于最高价0.9倍")
                order_target(stock_two, 0)
            elif df_max_high > cost * 1.20 and day_open_price < pre_close_price:
                print("2.卖出股票：赚了30个点")
                order_target(stock_two, 0)
            elif df_max_high > cost * 1.20 and current_price < df_max_high * 0.95:
                print("3.卖出股票：赚了30个点")
                order_target(stock_two, 0)
                
    if time_sell > cday and len(g.help_stock) > 0:
        instead_stock = g.help_stock
        for stock_remove in instead_stock:
            g.help_stock.remove(stock_remove)

## 选出连续涨停超过3天的，最近一天是阴板的
def before_market_open(context):
    date_now =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")#'2021-01-15'#datetime.datetime.now()
    yesterday = (context.current_dt + timedelta(days = -90)).strftime("%Y-%m-%d")
    trade_date = get_trade_days(start_date=yesterday, end_date=date_now, count=None)
    stocks = list(get_all_securities(['stock']).index)
    end_date = trade_date[trade_date.size-1]
    filter_st_stock = filter_st(stocks)
    pre_date = trade_date[trade_date.size-2]
    filter_stock = filter_stocks_by_days(context, filter_st_stock, 1080)
    templist = pick_high_limit(filter_st_stock,pre_date)

    for stock in templist:
        stock_date=trade_date[trade_date.size-1]
        df_panel = get_price(stock, count = 1,end_date=stock_date, frequency='daily', fields=['open', 'close','high_limit','money','low','high','pre_close'])
        df_close = df_panel['close'].values
        df_high = df_panel['high'].values
        df_low = df_panel['low'].values
        df_open = df_panel['open'].values
        df_pre_close = df_panel['pre_close'].values
        df_high_limit = df_panel['high_limit'].values
        stock_date_150=trade_date[trade_date.size-10]
        df_panel_150 = get_price(stock, count = 150,end_date=stock_date_150, frequency='daily', fields=['open', 'close','high_limit','money','low','high','pre_close'])
        df_max_close_150 = df_panel_150["close"].max()
        #查询大前天的close价格
        if stock == '601519.XSHG':
            print(df_close)
            print(df_high)
            print(df_pre_close)
            
        if df_close < df_high * 0.976 and df_close > df_pre_close and df_close > df_open * 1.08 and df_close > df_max_close_150 * 1.2:
            g.help_stock.append(stock)
    print("-----被选出的股票为:-------")
    print(g.help_stock)            
    
##选出打板的股票
def pick_high_limit(stocks,end_date_limit):
    high_limit_stock = []
    for stock in (stocks):
        df_panel = get_price(stock, count = 4,end_date=end_date_limit, frequency='daily', fields=['open', 'close','high_limit','money','pre_close'])
        sum_plus_num = (df_panel.loc[:,'close'] > df_panel.loc[:,'high_limit'] * 0.98).sum()
        if(stock[0:3] == '300'):
            continue
        if stock == '601519.XSHG':
            print(end_date_limit)
            print(sum_plus_num)
        if sum_plus_num == 4:
            high_limit_stock.append(stock)
    return high_limit_stock        


##去除st的股票
def filter_st(codelist):
    current_data = get_current_data()
    codelist = [code for code in codelist if not current_data[code].is_st]
    return codelist

##过滤上市时间不满1080天的股票,绿色锥型结构
def filter_stock_by_days(context, stock_list, days):
    days_public=(context.current_dt.date() - get_security_info(stock_list).start_date).days
    if days_public > days:
        return True
    return False

##过滤上市时间不满1080天的股票
def filter_stocks_by_days(context, stock_list, days):
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
    g.help_stock = []
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    log.info('一天结束')
    log.info('##############################################################')
