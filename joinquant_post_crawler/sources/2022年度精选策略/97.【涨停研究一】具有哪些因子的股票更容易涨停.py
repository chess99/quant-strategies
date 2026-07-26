import pandas as pd
import datetime as dt
from jqdata import *
#起始日期
sd = '2017-01-01'
#结束日期
ed = '2022-12-31'
#过滤新股天数
fn = 350
#观察窗口
wd_count = 250

all_trade_days=[i.strftime('%Y-%m-%d') for i in list(get_all_trade_days())]
tradingday = get_trade_days(start_date=sd, end_date=ed, count=None)
trade_day_list = []
for item in list(tradingday):
    trade_day_list.append(str(item))

def filter_new_stock(initial_list,watch_date,n_days):
    df=get_all_securities(types=['stock'], date=watch_date)[['start_date']]
    df=df.loc[initial_list]
    date=datetime.datetime.strptime(all_trade_days[all_trade_days.index(watch_date)-n_days],"%Y-%m-%d").date()
    return list(df[df['start_date']< date].index)

def filter_st_stock(initial_list, watch_date):
    df = get_extras('is_st', initial_list, start_date=watch_date, end_date=watch_date, df=True)
    df =df.T
    df.columns = ['is_st']
    df = df[df['is_st'] == False]
    filter_list = list(df.index)
    return filter_list

def high_limit_count(stock_list, stat_date, watch_days):
    df = get_price(stock_list, end_date=stat_date, frequency='daily', fields=['close','high_limit'], count=watch_days, panel=False, fill_paused=True)
    df.index = df.code
    count_list = []
    for stock in stock_list:
        df_sub = df.loc[stock]
        high_limit_days = df_sub[df_sub.close==df_sub.high_limit].close.count()
        count_list.append(high_limit_days)   
    df = pd.DataFrame(columns=['code','count'])
    df['code'] = stock_list
    df['count'] = count_list
    df = df.dropna()
    return df


stat_date_list = []
watch_date_list = []
HL_ratio_list = []
MKT_ratio_list = []
len_list = []

for watch_date in trade_day_list:
    stat_date = str(datetime.datetime.strptime(all_trade_days[all_trade_days.index(watch_date)-1],"%Y-%m-%d").date())

    df = get_all_securities(types=['stock'], date=stat_date)
    stock_list = list(df.index)
    stock_list = filter_new_stock(stock_list, stat_date, fn)
    stock_list = filter_st_stock(stock_list, stat_date)

    #条件：涨停次数
    MKT_df = high_limit_count(stock_list, stat_date, wd_count)
    MKT_mean = MKT_df['count'].mean(0)
    test_df = MKT_df[MKT_df['count']>6*MKT_mean]
    test_list = list(test_df.code)
    test_len = len(test_list)

    #预测结果
    if len(test_list) != 0:
        df = get_price(test_list, end_date=watch_date, frequency='daily', fields=['close','high_limit'], count=1, panel=False)
        HL_ratio = len(df[df['high_limit']==df['close']])/len(df)
    else:
        HL_ratio = 0
    df = get_price(stock_list, end_date=watch_date, frequency='daily', fields=['close','high_limit'], count=1, panel=False)
    MKT_ratio = len(df[df['high_limit']==df['close']])/len(df)

    HL_ratio_list.append(HL_ratio)
    MKT_ratio_list.append(MKT_ratio)
    watch_date_list.append(watch_date)
    len_list.append(test_len)

df = pd.DataFrame(index=watch_date_list, columns=['MKT','HL','len'])
df['MKT'] = MKT_ratio_list
df['HL'] = HL_ratio_list
df['len'] = len_list
df



import pandas as pd
import datetime as dt
from jqdata import *
#起始日期
sd = '2013-01-01'
#结束日期
ed = '2015-12-31'
#过滤新股天数
fn = 350
#观察窗口
wd_rel = 250
wd_count = 250

all_trade_days=[i.strftime('%Y-%m-%d') for i in list(get_all_trade_days())]
tradingday = get_trade_days(start_date=sd, end_date=ed, count=None)
trade_day_list = []
for item in list(tradingday):
    trade_day_list.append(str(item))

def filter_new_stock(initial_list,watch_date,n_days):
    df=get_all_securities(types=['stock'], date=watch_date)[['start_date']]
    df=df.loc[initial_list]
    date=datetime.datetime.strptime(all_trade_days[all_trade_days.index(watch_date)-n_days],"%Y-%m-%d").date()
    return list(df[df['start_date']< date].index)

def filter_st_stock(initial_list, watch_date):
    df = get_extras('is_st', initial_list, start_date=watch_date, end_date=watch_date, df=True)
    df =df.T
    df.columns = ['is_st']
    df = df[df['is_st'] == False]
    filter_list = list(df.index)
    return filter_list

def high_limit_count(stock_list, stat_date, watch_days):
    df = get_price(stock_list, end_date=stat_date, frequency='daily', fields=['close','high_limit'], count=watch_days, panel=False, fill_paused=True)
    df.index = df.code
    count_list = []
    for stock in stock_list:
        df_sub = df.loc[stock]
        high_limit_days = df_sub[df_sub.close==df_sub.high_limit].close.count()
        count_list.append(high_limit_days)   
    df = pd.DataFrame(columns=['code','count'])
    df['code'] = stock_list
    df['count'] = count_list
    df = df.dropna()
    return df

def get_relative_position(stock_list, stat_date, watch_days):
    df = get_price(stock_list, end_date=stat_date, frequency='daily', fields=['high','low','close'], skip_paused=False, fq='pre', count=watch_days, panel=False, fill_paused=True)
    df.index = df.code
    REL_list = []
    for stock in stock_list:
        df_sub = df.loc[stock]
        MAX = df_sub.high.max()
        MIN = df_sub.low.min()
        CLOSE = float(df_sub.iloc[-1:,4])
        if MAX-MIN != 0:
            REL = (CLOSE-MIN)/(MAX-MIN)
        else:
            REL = NaN
        REL_list.append(REL)   
    df = pd.DataFrame(columns=['code','REL'])
    df['code'] = stock_list
    df['REL'] = REL_list
    df = df.dropna()
    return df

stat_date_list = []
watch_date_list = []
HL_ratio_list = []
MKT_ratio_list = []

for watch_date in trade_day_list:
    stat_date = str(datetime.datetime.strptime(all_trade_days[all_trade_days.index(watch_date)-1],"%Y-%m-%d").date())

    df = get_all_securities(types=['stock'], date=stat_date)
    stock_list = list(df.index)
    stock_list = filter_new_stock(stock_list, stat_date, fn)
    stock_list = filter_st_stock(stock_list, stat_date)

    #条件1：相对位置
    df = get_relative_position(stock_list, stat_date, wd_rel)
    REL_mean = df['REL'].mean(0)
    df = df[df['REL'] >= REL_mean]
    rel_list = list(df.code)

    #条件2：市值
    q = query(valuation.code,valuation.circulating_market_cap).filter(valuation.code.in_(stock_list))
    MKT_df = get_fundamentals(q, date=stat_date)
    MKT_mean = MKT_df['circulating_market_cap'].mean(0)

    q = query(valuation.code,valuation.circulating_market_cap).filter(valuation.code.in_(rel_list))
    cap_df = get_fundamentals(q, date=stat_date)
    cap_df = cap_df[cap_df['circulating_market_cap']< 0.5*MKT_mean]
    cap_list = list(cap_df.code)

    #条件3：涨停次数
    MKT_df = high_limit_count(stock_list, stat_date, wd_count)
    MKT_df.index = MKT_df.code
    MKT_mean = MKT_df['count'].mean(0)
    test_df = MKT_df.loc[cap_list]
    test_df = test_df[test_df['count']>5*MKT_mean]
    test_list = list(test_df.code)

    #预测结果
    if len(test_list) != 0:
        df = get_price(test_list, end_date=watch_date, frequency='daily', fields=['close','high_limit'], count=1, panel=False)
        HL_ratio = len(df[df['high_limit']==df['close']])/len(df)
    else:
        HL_ratio = 0
    df = get_price(stock_list, end_date=watch_date, frequency='daily', fields=['close','high_limit'], count=1, panel=False)
    MKT_ratio = len(df[df['high_limit']==df['close']])/len(df)

    HL_ratio_list.append(HL_ratio)
    MKT_ratio_list.append(MKT_ratio)
    watch_date_list.append(watch_date)

df = pd.DataFrame(index=watch_date_list, columns=['MKT','HL'])
df['MKT'] = MKT_ratio_list
df['HL'] = HL_ratio_list
df



#计算预测列表
import pandas as pd
import datetime as dt
from jqdata import *

all_trade_days=[i.strftime('%Y-%m-%d') for i in list(get_all_trade_days())]
tradingday = get_trade_days(start_date='2008-01-01', end_date='2022-02-10', count=None)
trade_day_list = []
for item in list(tradingday):
    trade_day_list.append(str(item))

def filter_new_stock(initial_list,watch_date,n_days):
    df=get_all_securities(types=['stock'], date=watch_date)[['start_date']]
    df=df.loc[initial_list]
    date=datetime.datetime.strptime(all_trade_days[all_trade_days.index(watch_date)-n_days],"%Y-%m-%d").date()
    return list(df[df['start_date']< date].index)

def filter_st_stock(initial_list, watch_date):
    df = get_extras('is_st', initial_list, start_date=watch_date, end_date=watch_date, df=True)
    df =df.T
    df.columns = ['is_st']
    df = df[df['is_st'] == False]
    filter_list = list(df.index)
    return filter_list

def high_limit_count(stock, stat_date, watch_days):
    df = get_price(stock, end_date=stat_date, frequency='daily', fields=['close','high_limit'], count=watch_days, panel=False, fill_paused=True)
    high_limit_days = df[df.close==df.high_limit].close.count()
    return high_limit_days

fn = 350
w = 250
stat_date = '2022-03-01'

df = get_all_securities(types=['stock'], date=stat_date)
stock_list = list(df.index)
stock_list = filter_new_stock(stock_list, stat_date, fn)
stock_list = filter_st_stock(stock_list, stat_date)

q = query(valuation.code,valuation.circulating_market_cap).filter(valuation.code.in_(stock_list))
MKT_df = get_fundamentals(q, date=stat_date)
MKT_mean = MKT_df.circulating_market_cap.mean(0)

DF = pd.DataFrame(columns=['code','count'])
temp_list = []
for stock in stock_list:
    count = high_limit_count(stock, stat_date, w)
    temp_list.append(count)
DF['code'] = stock_list
DF['count'] = temp_list
count_mean = DF['count'].mean(0)
DF = DF[DF['count']>6*count_mean]
temp_list = list(DF.code)

q = query(valuation.code,valuation.circulating_market_cap).filter(valuation.code.in_(temp_list))
test_df = get_fundamentals(q, date=stat_date)
test_df = test_df[test_df['circulating_market_cap']< 0.4*MKT_mean]
test_list = list(test_df.code)

count_list = []
for stock in test_list:
    count = high_limit_count(stock, stat_date, w)
    count_list.append(count)
test_df['count'] = count_list

print("以下列表为{}预测".format(stat_date))
test_df



# 导入函数库
from jqdata import *

# 初始化函数，设定基准等等
def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    log.set_level('order', 'error')
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    init_cash = context.portfolio.starting_cash/2
    set_subportfolios([SubPortfolioConfig(cash=init_cash, type='stock'),SubPortfolioConfig(cash=init_cash, type='stock')])

    g.hold_list0 = []
    g.hold_list1 = []
    g.stock_list = []
    g.to_sell_list = []
    g.stock_num = 5 #单个position最多持仓5只
    g.xh1 = 1
    g.xh2 = 0
    g.fn = 300 #过滤上市不足350个交易日的股票
    g.wd_rel = 250 #观察相对位置的时间窗口
    g.wd_count = 250 #观察涨停次数的时间窗口
    g.target_time_for_buy = '11:20:00' #只追早盘涨停
    g.target_time_for_sale = '14:50:00' #次日卖出时间

    # 开盘前运行
    run_daily(before_market_open, time='9:00', reference_security='000300.XSHG') 

    # 开盘时或每分钟开始时运行
    run_daily(market_open, time='every_bar', reference_security='000300.XSHG')

    # 收盘后运行
    run_daily(after_market_close_get_list, time='15:05', reference_security='000300.XSHG')
    run_daily(after_market_close_allocate_position, time='15:10', reference_security='000300.XSHG')



## 开盘前运行函数     
def before_market_open(context):
    if g.stock_list != []:
        print(len(g.stock_list))
        #print(g.stock_list)
        #print(g.to_sell_list)
    print(('xh1={}'.format(g.xh1)), ('xh2={}'.format(g.xh2)))
    cash0 = context.subportfolios[0].available_cash
    cash1 = context.subportfolios[1].available_cash
    try:
        g.cash0 = cash0/(g.stock_num - len(g.hold_list0))
        g.cash1 = cash1/(g.stock_num - len(g.hold_list1))
    except:
        pass


## 开盘时运行函数
def market_open(context):
    now_time = context.current_dt

    hold_list0 = []
    position_dict0  = context.subportfolios[0].long_positions
    for position in list(position_dict0.values()):  
        hold_list0.append(position.security)

    hold_list1 = []
    position_dict1  = context.subportfolios[1].long_positions
    for position in list(position_dict1.values()):  
        hold_list1.append(position.security)

    if g.xh1 == 1:
        if now_time.strftime('%H:%M:%S') < g.target_time_for_buy:
            if len(hold_list0) < g.stock_num:
                for stock in g.stock_list:
                    if stock not in hold_list0:
                        last_close = get_last_close(context, stock)
                        current_data = get_price(stock, end_date=now_time, frequency='1m', fields=['close'], skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True)
                        price_chg = (current_data.iloc[0,0] - last_close)/last_close
                        if (price_chg >= 0.075) and (price_chg< = 0.095):
                            order_target_value(stock, g.cash0, pindex=0)
                            log.info('仓位一买入{},最多{}元'.format(stock, g.cash0))
                        else:
                            pass

    elif g.xh1 == 0:
        if now_time.strftime('%H:%M:%S') > g.target_time_for_sale:
            for stock in g.to_sell_list:
                if stock in hold_list0:
                    last_close = get_last_close(context, stock)
                    current_data = get_price(stock, end_date=now_time, frequency='1m', fields=['close'], skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True)
                    price_chg = (current_data.iloc[0,0] - last_close)/last_close
                    if price_chg < = 0.099: 
                        order_target_value(stock, 0, pindex=0)
                        log.info('仓位一全部卖出{}'.format(stock))
                    else:
                        pass

    if g.xh2 == 1:
        if now_time.strftime('%H:%M:%S') < g.target_time_for_buy:
            if len(hold_list1) < g.stock_num:
                for stock in g.stock_list:
                    if (stock not in hold_list1) and (stock not in g.to_sell_list):
                        last_close = get_last_close(context, stock)
                        current_data = get_price(stock, end_date=now_time, frequency='1m', fields=['close'], skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True)
                        price_chg = (current_data.iloc[0,0] - last_close)/last_close
                        if (price_chg >= 0.05) and (price_chg< = 0.095):
                            order_target_value(stock, g.cash1, pindex=1)
                            log.info('仓位二买入{},最多{}元'.format(stock, g.cash1))
                        else:
                            pass

    elif g.xh2 == 0:
        if now_time.strftime('%H:%M:%S') > g.target_time_for_sale:
            for stock in g.to_sell_list:
                if stock in hold_list1:
                    last_close = get_last_close(context, stock)
                    current_data = get_price(stock, end_date=now_time, frequency='1m', fields=['close'], skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True)
                    price_chg = (current_data.iloc[0,0] - last_close)/last_close
                    if price_chg < = 0.099: 
                        order_target_value(stock, 0, pindex=1)
                        log.info('仓位二全部卖出{}'.format(stock))
                    else:
                        pass    


## 收盘后运行函数  
def after_market_close_get_list(context):
    stat_date = context.current_dt.strftime('%Y-%m-%d')

    df = get_all_securities(types=['stock'], date=stat_date)
    stock_list = list(df.index)
    stock_list = filter_new_stock(context, stock_list, stat_date, g.fn)
    stock_list = filter_st_stock(stock_list)
    stock_list = filter_kcb_stock(context, stock_list)
    stock_list = filter_cyb_stock(context, stock_list)
    stock_list = filter_paused_stock(stock_list)

    #条件1：相对位置
    df = get_relative_position(stock_list, stat_date, g.wd_rel)
    REL_mean = df['REL'].mean(0)
    df = df[df['REL'] >= REL_mean]
    rel_list = list(df.code)

    #条件2：市值
    q = query(valuation.code,valuation.circulating_market_cap).filter(valuation.code.in_(stock_list))
    MKT_df = get_fundamentals(q, date=stat_date)
    MKT_mean = MKT_df['circulating_market_cap'].mean(0)

    q = query(valuation.code,valuation.circulating_market_cap).filter(valuation.code.in_(rel_list))
    cap_df = get_fundamentals(q, date=stat_date)
    cap_df = cap_df[cap_df['circulating_market_cap']< 0.5*MKT_mean]
    cap_list = list(cap_df.code)

    #条件3：涨停次数
    MKT_df = high_limit_count(stock_list, stat_date, g.wd_count)
    MKT_df.index = MKT_df.code
    MKT_mean = MKT_df['count'].mean(0)
    test_df = MKT_df.loc[cap_list]
    test_df = test_df[test_df['count']>4*MKT_mean]
    test_list = list(test_df.code)

    g.stock_list = test_list

def after_market_close_allocate_position(context):
    to_sell_list = []

    hold_list0 = []
    position_dict0  = context.subportfolios[0].long_positions
    for position in list(position_dict0.values()):  
        hold_list0.append(position.security)

    hold_list1 = []
    position_dict1  = context.subportfolios[1].long_positions
    for position in list(position_dict1.values()):  
        hold_list1.append(position.security)

    if hold_list0 == []:
        xh1 = 1
        xh2 = 0
        to_sell_list = hold_list1

    elif hold_list0 != []:
        xh1 = 0
        to_sell_list = hold_list0
        if hold_list1 == []:
            xh2 = 1

    if hold_list1 != []:
        xh1 = 1
        xh2 = 0
        to_sell_list = hold_list1

    g.xh1 = xh1
    g.xh2 = xh2
    g.hold_list0 = hold_list0
    g.hold_list1 = hold_list1
    g.to_sell_list = to_sell_list



#工具函数
def high_limit_count(stock_list, stat_date, watch_days):
    df = get_price(stock_list, end_date=stat_date, frequency='daily', fields=['close','high_limit'], count=watch_days, panel=False, fill_paused=True)
    df.index = df.code
    count_list = []
    for stock in stock_list:
        df_sub = df.loc[stock]
        high_limit_days = df_sub[df_sub.close==df_sub.high_limit].close.count()
        count_list.append(high_limit_days)   
    df = pd.DataFrame(columns=['code','count'])
    df['code'] = stock_list
    df['count'] = count_list
    df = df.dropna()
    return df

def get_relative_position(stock_list, stat_date, watch_days):
    df = get_price(stock_list, end_date=stat_date, frequency='daily', fields=['high','low','close'], skip_paused=False, fq='pre', count=watch_days, panel=False, fill_paused=True)
    df.index = df.code
    REL_list = []
    for stock in stock_list:
        df_sub = df.loc[stock]
        MAX = df_sub.high.max()
        MIN = df_sub.low.min()
        CLOSE = float(df_sub.iloc[-1:,4])
        if MAX-MIN != 0:
            REL = (CLOSE-MIN)/(MAX-MIN)
        else:
            REL = NaN
        REL_list.append(REL)   
    df = pd.DataFrame(columns=['code','REL'])
    df['code'] = stock_list
    df['REL'] = REL_list
    df = df.dropna()
    return df

def get_last_close(context, stock):
    close_data = get_bars(stock, count=1, unit='1d', fields=['close'])
    last_close = close_data['close'][-1]
    return last_close


#过滤函数
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]

def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list
            if not current_data[stock].is_st
            and 'ST' not in current_data[stock].name
            and '*' not in current_data[stock].name
            and '退' not in current_data[stock].name]

def filter_limitup_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] < current_data[stock].high_limit]

def filter_limitdown_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] > current_data[stock].low_limit]

def filter_kcb_stock(context, stock_list):
    return [stock for stock in stock_list  if stock[0:3] != '688']

def filter_cyb_stock(context, stock_list):
    return [stock for stock in stock_list  if stock[0:3] != '300']

def filter_new_stock(context, stock_list , ed, fn):
    #按交易日天数过滤
    all_trade_days=[i.strftime('%Y-%m-%d') for i in list(get_all_trade_days())]
    tradingday = get_trade_days(start_date='2005-01-01', end_date=ed, count=None)
    trade_day_list = []
    for item in list(tradingday):
        trade_day_list.append(str(item))
    df = get_all_securities(types=['stock'], date=ed)[['start_date']].loc[stock_list]
    date = datetime.datetime.strptime(all_trade_days[all_trade_days.index(ed) - fn],"%Y-%m-%d").date()
    return list(df[df['start_date']< date].index)
