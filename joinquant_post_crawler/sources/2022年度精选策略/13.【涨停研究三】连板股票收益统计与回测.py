import pandas as pd
import datetime as dt
from jqdata import *
#起始日期
sd = '2019-01-01'
#结束日期
ed = '2020-12-31'
#过滤新股天数
fn = 250
#观察窗口
wd_count = 10
#连续涨停或跌停
limit_condition = 'high'
#最大持仓天数
keep_days = 3
#情绪周期择时参数
emo_cycle = 3

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

def limit_count(limit, stock_list, stat_date, watch_days):
    if limit == 'high':
        df = get_price(stock_list, end_date=stat_date, frequency='daily', fields=['close','high_limit'], count=watch_days, panel=False, fill_paused=False)
        df['limit'] = df['high_limit']
    elif limit =='low':
        df = get_price(stock_list, end_date=stat_date, frequency='daily', fields=['close','low_limit'], count=watch_days, panel=False, fill_paused=False)
        df['limit'] = df['low_limit']
    df.index = df.code
    count_list = []
    for stock in stock_list:
        df_sub = df.loc[stock]
        limit_days = df_sub[df_sub.close==df_sub.limit].close.count()
        count_list.append(limit_days)   
    df = pd.DataFrame(columns=['code','count'])
    df['code'] = stock_list
    df['count'] = count_list
    df = df.dropna()
    return df

def get_smallest(stock_list, stat_date):
    q = query(valuation.code,valuation.circulating_market_cap).filter(valuation.code.in_(stock_list)).order_by(valuation.circulating_market_cap.asc())
    df = get_fundamentals(q, date=stat_date)
    df.index = df.code
    stock = list(df.code)[0]
    cap = df.loc[stock]['circulating_market_cap']
    return (stock, cap)

def get_future_price_summary(stock, stat_date, watch_date, sellable_date, last_keep_date):
    df = get_price(security=stock, end_date=watch_date, fields=['open'], count=1, panel=False)
    start_price = df.iloc[0]['open'] 
    
    df = get_price(security=stock, end_date=last_keep_date, fields=['close'], count=1, panel=False)
    over_price = df.iloc[0]['close']
    
    df = get_price(security=stock, start_date=sellable_date, end_date=last_keep_date, fields=['high','low'], panel=False)
    max_price = df['high'].max()
    min_price = df['low'].min()
    
    gain = round(((max_price - start_price)/start_price), 2)
    lose = round(((min_price - start_price)/start_price), 2)
    
    average = round((0.5 * (gain + lose)), 2)
    keep = round((over_price - start_price)/start_price, 2)
    
    return (start_price, min_price, max_price, over_price, lose, gain, average, keep)
