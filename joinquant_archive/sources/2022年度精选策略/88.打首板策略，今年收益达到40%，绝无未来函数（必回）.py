# 克隆自聚宽文章：https://www.joinquant.com/post/36905
# 标题：打首板策略，今年收益达到40%，绝无未来函数（必回）
# 作者：Pengpengpeng

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
    g.help_stock = []
    set_universe(g.help_stock)
    
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    
    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='9:28', reference_security='000300.XSHG')
      # 开盘时运行
    run_daily(market_run, time='every_bar', reference_security='000300.XSHG')
 
# 开盘时运行函数
def market_run(context):
    # log.info('【market_run】')
    time_buy = context.current_dt.strftime('%H:%M:%S')
    aday = datetime.datetime.strptime('10:30:00', '%H:%M:%S').strftime('%H:%M:%S')
    now = context.current_dt
    zeroToday = now - datetime.timedelta(hours=now.hour, minutes=now.minute, seconds=now.second,microseconds=now.microsecond)
    lastToday = zeroToday + datetime.timedelta(hours=9, minutes=30, seconds=00)
    n = len(g.help_stock)
    if n>10:
        ratio = 0.2
    elif n>5 and n<10:
        ratio = 0.3
    elif n>3:
        ratio = 0.5 
    else:
        ratio = 1
    if len(g.help_stock) > 0 and time_buy>='09:30:00' and time_buy<='11:25:00':
        cash = context.portfolio.available_cash
       
        gc_data = get_current_data()
       
        for stock in g.help_stock:
            if(cash > 5000):
                gc_stock = gc_data[stock]
                current_price = gc_stock.last_price
                day_open_price = gc_stock.day_open
                day_high_limit = gc_stock.high_limit 
                
                pre_high = g.yest_df_panel['high'][stock][0]
                pre_close = g.yest_df_panel['close'][stock][0]
               
                if cash > 5000:
                    if   current_price> pre_close and current_price <  day_high_limit :
                        #open_cash = cash / len(help_stock)
                        print(stock+" 1.买入金额 "+str(cash*ratio))
                        order_value(stock, cash*ratio)
                 
                        g.help_stock.remove(stock)
    
        time_sell = context.current_dt.strftime('%H:%M:%S')
        cday = datetime.datetime.strptime('14:40:00', '%H:%M:%S').strftime('%H:%M:%S')
        dday = datetime.datetime.strptime('10:30:00', '%H:%M:%S').strftime('%H:%M:%S')
        now = context.current_dt
        zeroToday = now - datetime.timedelta(hours=now.hour, minutes=now.minute, seconds=now.second,microseconds=now.microsecond)
        lastToday = zeroToday + datetime.timedelta(hours=9, minutes=30, seconds=00)
        if time_sell > cday and len(context.portfolio.positions):
            stock_owner = context.portfolio.positions
            for stock_two in stock_owner:

                current_price = gc_data[stock_two].last_price
                day_open_price = gc_data[stock_two].day_open
                day_high_limit = gc_data[stock_two].high_limit 
                day_low_limit = gc_data[stock_two].low_limit 
    
                #查询当天的最高价
                df_panel_allday = get_price(
                    stock_two, 
                    start_date=lastToday, 
                    end_date=context.current_dt, 
                    frequency='minute', 
                    fields=['high','low','close','high_limit','money']
                )

                high_allday = df_panel_allday.loc[:,"high"].max()
     
                #平均持仓成本
                cost = context.portfolio.positions[stock_two].avg_cost
    
                if current_price <  high_allday * 0.97 and current_price > day_low_limit:
                    print("1.卖出股票：小于最高价0.97倍")
                    order_target(stock_two, 0)
                elif current_price <  cost * 0.93 and current_price <  day_open_price and current_price >day_low_limit:
                    print("卖出股票：比开盘价低7个点")
                    order_target(stock_two, 0)
        elif time_sell > dday and len(context.portfolio.positions):
            stock_owner = context.portfolio.positions
            # if len(stock_owner) > 0:
            for stock_two in stock_owner:
          

                current_price = gc_data[stock_two].last_price
                day_open_price = gc_data[stock_two].day_open
                day_high_limit = gc_data[stock_two].high_limit 
                day_low_limit = gc_data[stock_two].low_limit 
    

                ##获取前一天的收盘价
                pre_date =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
                df_panel = get_price(stock_two, count = 1,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','low',])
                pre_low_price =df_panel['low'].values
                pre_close_price =df_panel['close'].values
      
                cost = context.portfolio.positions[stock_two].avg_cost
     
                if current_price <  pre_close_price * 1.03 and current_price > day_low_limit:
                    # print("1.卖出股票：小于最高价0.97倍"+str(num_limit_stock))
                    print("1.卖出股票：小于最高价0.97倍")
                    order_target(stock_two, 0)
        
        time_sell = context.current_dt.strftime('%H:%M:%S')
        cday = datetime.datetime.strptime('14:45:00', '%H:%M:%S').strftime('%H:%M:%S')
        if time_sell > cday and len(g.help_stock) > 0:
            instead_stock = g.help_stock
            for stock_remove in instead_stock:
                g.help_stock.remove(stock_remove)
# 开盘前运行函数 选择二板放量股 并且横盘震荡
def before_market_open(context):
    date_now = (context.current_dt+ timedelta(days = -1)).strftime("%Y-%m-%d")#'2021-01-15'#datetime.datetime.now()


    
    ##查询所有股票的当天的涨停板
    stocks = get_all_securities(['stock'])
    stock_list = filter_stock(stocks,context)
   
    ##查询所有股票的当天的涨停板
    # 耗时
    g.help_stock = filter_one_limit(stock_list, context)
    
        
    
    

    print("----------------最后被选出的股票-----------")
    print(g.help_stock)
    help_stock = g.help_stock
    if help_stock:
        g.yest_df_panel = get_price(help_stock, count = 1,end_date= context.previous_date,frequency='daily', fields=['open', 'high', 'close','low', 'high_limit','money','pre_close'])
    else:
        g.yest_df_panel = []

##选出打板的股票

def filter_one_limit(stocks_list,context):
    # date1 = get_trade_days(end_date=datetime.date.today(),count=5)[-1]
    
    end_date =context.previous_date
    high_limit_stock = []
    security_list = []
    # stock= ['000001.XSHE']
    for st1 in stocks_list:
    #     print(st1)
        df_panel = get_price(st1, count = 1,end_date=end_date, frequency='daily', fields=['open', 'close','high_limit','money','pre_close'])
        df_close = df_panel['close']
        df_open = df_panel['open']
        df_high_limit = df_panel['high_limit']
        df_pre_close = df_panel['pre_close']
       
        
        _high_limit = (df_high_limit.values)
        _close = (df_close.values)
        _open =  (df_open.values)
        _pre_close = (df_pre_close.values)
    
    
        if _high_limit == _close:
            high_limit_stock.append(st1)
    security_list = []
    for st in high_limit_stock:##十天内首次涨停（首板）
        df_panel_20 = get_price(st, count = 60,end_date=end_date, frequency='daily', 
                                fields=['open', 'close','high_limit','money','high','low'])
    
        sum_plus_num_20 = (df_panel_20.tail(8)['high'] == df_panel_20.tail(8)['high_limit']).sum()
        if sum_plus_num_20==1 and df_panel_20['high'][-1]==max(df_panel_20['high']) and df_panel_20['money'][-1]>df_panel_20['money'][-2]:
            # cd = [st,df_panel_20['high'][-1]]
            # print(cd)
            
            security_list.append(st)
    return security_list           
    # high_limit_stock = []
    # security_list = []
    # date1 = context.previous_date
    # for stock in stocks_list:
    #     df_panel = get_price(stock, count = 1,end_date=date1, frequency='daily', fields=['open', 'close','high_limit','money','pre_close'])
    #     df_close = df_panel.close[0]
    #     df_open = df_panel.open[0]
    #     df_high_limit = df_panel.high_limit[0]
    #     df_pre_close = df_panel.pre_close[0]
    #     if df_high_limit == df_close:
    #         high_limit_stock.append(stock)
    # for stock in high_limit_stock:##十天内首次涨停（首板）
    
    #     df_panel_20 = get_price(stock, count = 60,end_date=date1, frequency='daily', fields=['open', 'close','high_limit','money','high','low'])
    #     sum_plus_num_20 = (df_panel_20.loc[:,'high'] == df_panel_20.loc[:,'high_limit']).sum()
    #     if sum_plus_num_20==1:
    #         security_list.append(stock)
    # print('yiban',security_list)
    # return security_list


# 查看股票前期是否平整 且两板的最高点是否超过其他的最高点
def filter_flat_stock(stock,end_date,pre_date):
    #查询昨天的涨停价格
    df_panel = get_price(stock, count = 1,end_date=end_date, frequency='daily', fields=['open', 'close','high_limit','money'])
    df_close = df_panel['close'].values
    df_open = df_panel['open'].values
    df_high_limit = df_panel['high_limit'].values
    df_money = df_panel['money'].values
    
    df_panel_20 = get_price(stock, count = 20,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','high','low'])
    sum_shipan_num = ((df_panel_20.loc[:,'high_limit'] == df_panel_20.loc[:,'high']) * (df_panel_20.loc[:,'close'] <= df_panel_20.loc[:,'high_limit'] * 0.97)).sum()
    df_max_high_20 = df_panel_20["high"].max()
    sum_plus_num_20 = (df_panel_20.loc[:,'high'] == df_panel_20.loc[:,'high_limit']).sum()
    abs_sum_20 = (df_panel_20.loc[:,'close'] - df_panel_20.loc[:,'open']).abs() / ((df_panel_20.loc[:,'open']+df_panel_20.loc[:,'close']) / 2)
    abs_sum_num_2030 = (abs_sum_20 <  0.03).sum()
    abs_sum_num_2015 = (abs_sum_20 <  0.015).sum()
    abs_sum_num_2055 = (abs_sum_20 <  0.055).sum()
    #12天的波动率
    df_panel_60 = get_price(stock, count = 60,end_date=pre_date, frequency='daily', fields=['open', 'close','high_limit','money','high','low'])
    high_allday_60 = df_panel_60.loc[:,"high"].max()
    low_allday_60 = df_panel_60.loc[:,"low"].min()
    close_allday_60 = df_panel_60.loc[:,"close"].max()
    percent_rate_60 = low_allday_60 / high_allday_60
    sum_close_num_60 = (df_panel_60.loc[:,'close'] <= df_panel_60.loc[:,'open']).sum()
    abs_sum_60 = (df_panel_60.loc[:,'close'] - df_panel_60.loc[:,'open']).abs() / df_panel_60.loc[:,'open']
    abs_sum_num_6015 = (abs_sum_60 <  0.015).sum()
    abs_sum_num_6030 = (abs_sum_60 <  0.03).sum()
    abs_sum_num_6055 = (abs_sum_60 <  0.055).sum()
    sum_plus_num_60 = (df_panel_60.loc[:,'high'] > df_panel_60.loc[:,'high_limit'] * 0.99).sum()
    
  
    if (
        df_close * 1.1 > close_allday_60 
        and abs_sum_num_2030 > 15 
        and abs_sum_num_2015 > 7 
        and abs_sum_num_2055 >= 18
    ):
        if (abs_sum_num_6015 >=28 
            and abs_sum_num_6030 > 45 
            and abs_sum_num_6055 > 50
        ):
            return True


def filter_stock(stock_pool,context):
    
    return list(stock for stock in stock_pool.index
                if not stock.startswith('300') and not stock.startswith('688')
                and not 'ST' in stock_pool['display_name']
                and not '*' in stock_pool['display_name']
                and not '退' in stock_pool['display_name']
                and (context.current_dt.date() - get_security_info(stock).start_date).days >200)
    # return list(stock for stock in stock_pool.index
    #             if not '退' in stock_pool['display_name']
    #             )
#过滤上市时间不满1080天的股票
def filter_stock_by_days(context, stock_list, days):
    tmpList = []
    for stock in stock_list :
        #days_public=(context.current_dt.date() - get_security_info(stock).start_date).days days_public > days and 
        market_cap = get_circulating_market_cap(stock)
        market_cap_num = market_cap['circulating_market_cap'].values
        if market_cap_num >10 and market_cap_num <  150:
            tmpList.append(stock)
    return tmpList
# 查看他总的涨停数
def count_limit_num_all(stock,context):
    date_now = (context.current_dt+ timedelta(days = -1)).strftime("%Y-%m-%d")#'2021-01-15'#datetime.datetime.now()
    yesterday = (context.current_dt + timedelta(days = -30)).strftime("%Y-%m-%d")
    trade_date = get_trade_days(start_date=yesterday, end_date=date_now, count=None)
    limit_num = 0
    for datenum in trade_date:
        # 耗时
        df_panel = get_price(stock, count = 1,end_date=datenum, frequency='daily', fields=['open', 'close','high_limit','money'])
        df_close = df_panel['close'].values
        df_high_limit = df_panel['high_limit'].values
        if df_close == df_high_limit:
            limit_num = limit_num + 1
    return limit_num
# 获取个股流通市 值数据
def getcirculating_market_cap(stock_list):
    query_list = [stock_list]
    q = query(valuation.code,valuation.circulating_market_cap).filter(valuation.code.in_(query_list))
    market_cap = get_fundamentals(q)
    market_cap.set_index('code', inplace=True)
    return market_cap

def count_limit_num(stock,context):
    date_now = (context.current_dt+ timedelta(days = -1)).strftime("%Y-%m-%d")#'2021-01-15'#datetime.datetime.now()
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

# 收盘后运行函数
def after_market_close(context):
    log.info(str('除当天的股票数据-----函数运行时间(after_market_close):'+str(context.current_dt.time())))
    
    #消除当天的股票数据
    help_stock = []
    #print(help_stock)


