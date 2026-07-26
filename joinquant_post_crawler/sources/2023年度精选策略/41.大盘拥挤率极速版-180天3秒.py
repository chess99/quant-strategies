from jqdata import *
import datetime
import pandas as pd
# date_now的过去180天
date_now = datetime.date(2021, 3, 12)
days = 180
%%time
# ---------------------
# 2021-4 第一版
# ---------------------
dict_crowd = {}
trade_days = get_trade_days(end_date=date_now, count=days)
for date1 in trade_days:
    all_stocks = list(get_all_securities(date=date1).index)
    h = get_price(all_stocks, end_date=date1, frequency='1d', fields='money',
                  count=1, panel=False).sort_values(by='money', ascending=False)
    #
    n_five_pct = int(len(h) / 20)   # 5%
    n_crowd = h.iloc[:n_five_pct]['money'].sum() / h['money'].sum()
    dict_crowd[date1] = n_crowd * 100
#
df_crowd = pd.DataFrame.from_dict(dict_crowd, orient='index',columns=['crowd_rate',])
df_crowd.plot()
df_crowd[df_crowd.crowd_rate>=55]
df_crowd[df_crowd.crowd_rate<=33]
%%time
# ---------------------
# 2021-10-6 新版
# ---------------------
trade_day = get_trade_days(end_date=date_now, count=1)[-1]
all_stocks = list(get_all_securities(date=trade_day).index)

h = get_price(all_stocks, end_date=trade_day, frequency='1d', fields='money',
                  count=days, panel=False
             ).pivot(index='code',columns='time',values='money')
#
dict_crowd = {}
for day in h.columns:
    s2 = h[day].dropna().sort_values(ascending=False)
    dict_crowd[day] = (100 * s2.iloc[:len(s2)//20].sum()) / s2.sum()
#
s_crowd = pd.Series(dict_crowd)
s_crowd.plot()
s_crowd[s_crowd>=55]
s_crowd[s_crowd<=33]
