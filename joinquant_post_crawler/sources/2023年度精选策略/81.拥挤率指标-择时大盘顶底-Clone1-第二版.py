#!/usr/bin/env python
# coding: utf-8

# In[1]:


# # 0.5.11 的老版本 -- 支持python3.6以下
# !pip install pyecharts==0.5.11 --user
# 1.0 以上的新版本 -- 支持python3.6以上 ，不向下兼容，使用时注意，否则会运行失败
# 安装 v1 以上版本
# !pip install pyecharts -U --user
# !pip install snapshot_selenium --user


# In[2]:


# 去掉红色的警告框
import warnings
warnings.filterwarnings("ignore")


# In[3]:


# from jqdata import *
# import datetime
# import pandas as pd

# # date_now的过去180天
# date_now = datetime.date(2021, 3, 21)
# days = 600

# dict_crowd = {}
# trade_days = get_trade_days(end_date=date_now, count=days)
# for date1 in trade_days:
#     all_stocks = list(get_all_securities(date=date1).index)
#     h = get_price(all_stocks, end_date=date1, frequency='1d', fields='money',
#                   count=1, panel=False).sort_values(by='money', ascending=False)
#     #
#     n_five_pct = int(len(h) / 20)   # 5%
#     n_crowd = h.iloc[:n_five_pct]['money'].sum() / h['money'].sum()
#     dict_crowd[date1] = n_crowd * 100
# #
# df_crowd = pd.DataFrame.from_dict(dict_crowd, orient='index',columns=['crowd_rate',])
# df_crowd.plot()


# In[32]:


from jqdata import *
import datetime
import pandas as pd

# 画图相关的包
from pyecharts.charts import Bar
from pyecharts.charts import Line
from pyecharts import options as opts

from pyecharts.render import make_snapshot
# 使用 snapshot-selenium 渲染图片
from snapshot_selenium import snapshot

def crowd_line(daycount, date_now=datetime.datetime.now().strftime('%Y-%m-%d'), piece_count=100):
    all_df_crowd = get_all_crowd_rate_df(daycount, date_now, piece_count)
    
    time_list = list(all_df_crowd.index)

    hs300_df = get_price('000001.XSHG', start_date=time_list[0] ,end_date=time_list[-1], frequency='1d', fields='close',panel=False)
    hs300_list = list(hs300_df['close'])
    hs300_list = [round(x/100,2) for x in hs300_list]

    crowd_rate_list = all_df_crowd['crowd_rate']
    line = produce_line(time_list, hs300_list, crowd_rate_list)
    return line
    
def produce_line(time_list, hs300_list, crowd_rate_list):
    line = (
        Line()
        .add_xaxis(xaxis_data = time_list)
        .add_yaxis(series_name = "拥挤率",
                       y_axis = crowd_rate_list,
                       markpoint_opts=opts.MarkPointOpts(
                            data=[
                                opts.MarkPointItem(type_="max", name="最大值"),
                                opts.MarkPointItem(type_="min", name="最小值"),
                            ]
                        ),
                        markline_opts=opts.MarkLineOpts(
                            data=[opts.MarkLineItem(type_="average", name="平均值")]
                        ),
                    )
        .add_yaxis(series_name = "上证指数收盘价(已处理过，除以100)",
                       y_axis = hs300_list,
                       markpoint_opts=opts.MarkPointOpts(
                            data=[
                                opts.MarkPointItem(type_="max", name="最大值"),
                                opts.MarkPointItem(type_="min", name="最小值"),
                            ]
                        ),
                        markline_opts=opts.MarkLineOpts(
                            data=[opts.MarkLineItem(type_="average", name="平均值")]
                        ),
                    )
        .set_global_opts(
            title_opts=opts.TitleOpts(title="成交前5%拥挤率"),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
            toolbox_opts=opts.ToolboxOpts(is_show=True),
            datazoom_opts=[opts.DataZoomOpts(orient="horizontal"),opts.DataZoomOpts(type_="inside")],
            yaxis_opts=opts.AxisOpts(name = '拥挤率', is_scale= True),
            xaxis_opts=opts.AxisOpts(type_="category", name = '交易日'),
        )
    )
    return line

# 以下方法可以设置双y轴
# x = Faker.choose()
# scatter1 = (
#     Line()
#     .add_xaxis(x)
#     .add_yaxis("商家A", Faker.values(), yaxis_index=0,)
#     .extend_axis(yaxis=opts.AxisOpts())
# #     .set_global_opts(yaxis_opts=opts.AxisOpts(type_="value", name="商家A", position="right"))
# )
# scatter2 = (
#     Line()
#     .add_xaxis(x)
#     .add_yaxis("商家B", [v/1000 for v in Faker.values()], yaxis_index=1)
# #     .extend_axis(yaxis=opts.AxisOpts(type_="value", name="商家B", position="left"))
# #     .set_global_opts(yaxis_opts=opts.AxisOpts(type_="value", name="商家B", position="left"))
# )
# scatter1.overlap(scatter2)
# scatter1.render_notebook()


def get_all_crowd_rate_df(daycount, date_now, piece_count):
    # 数据量比较大，需要分开取数据, 每次取100条
    data_count = int((daycount-1) / piece_count) + 1
    end_date = date_now
    all_stocks = list(get_all_securities(date=date_now).index)
    all_df_crowd = pd.DataFrame(columns=['date', 'crowd_rate']).set_index('date')
    
    trade_dates = get_trade_days(start_date=None, end_date=end_date, count=daycount)
    
    frames = []
    for i in range(data_count):
        last_date = None
        last_count = piece_count*(i+1)
        if piece_count*(i+1) > daycount:
            last_count = daycount
        
        piece_trade_dates = trade_dates[piece_count*i : last_count]
        piece_trade_dates_str = [trade.strftime('%Y-%m-%d') for trade in piece_trade_dates]
        df = get_all_df(piece_trade_dates[0], piece_trade_dates[-1], all_stocks)
        df_crowd = get_crowd_rate_df(df)
        frames.append(df_crowd)
    d = pd.concat(frames)
    return d
        
        
def get_all_df(start_date, end_date, all_stocks):
    dict_crowd = {}
    # trade_days = get_trade_days(end_date=date_now, count=day_count)
    all_df = get_price(all_stocks, start_date=start_date, end_date=end_date, frequency='1d', fields='money',panel=False)

    all_df = all_df.sort_values(['time', 'money'], ascending = [True, False])
    all_df = all_df.set_index('time',drop=True)
    return all_df
    
def get_crowd_rate_df(all_df):
    date_set = set(list(all_df.index))

    df_crowd = pd.DataFrame(columns=['date', 'crowd_rate']).set_index('date')

    for date_str in date_set:
        date_str = date_str.strftime('%Y-%m-%d')
        df = all_df[all_df.index == date_str]
        df = df.sort_values('money', ascending = False)
        all_money = df['money'].sum()
        df = df[df['money'] >= df.iloc[int(len(df) * 0.05)]['money']]
        crowd_rate = df['money'].sum() / all_money
        df_crowd.loc[date_str, 'crowd_rate'] =  round(crowd_rate*100,1)
    df_crowd = df_crowd.sort_values('date')
    return df_crowd
print('over')


# In[34]:


#过去的天数
day_count = 1000
# date_now = datetime.datetime.now().strftime('%Y-%m-%d')
# piece_count = 10
line = crowd_line(day_count)

line.render_notebook()
#     line.render_notebook()
#     line.render('a.html')

