#!/usr/bin/env python
# coding: utf-8

# In[1]:


from __future__ import print_function, division
import pandas as pd
from pprint import pprint

from jqdata import *

pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)
pd.set_option('display.width', None)
pd.set_option('display.max_colwidth', -1)

# 获取行业列表

# 申万一级，若想使用此行业，请将下面两行代码最左边的 # 及空格删掉，此行不要改动。
# print("使用申万一级行业")
# industry_level = "sw_l1"

# 申万二级，若想使用此行业，请将下面两行代码最左边的 # 及空格删掉，此行不要改动。
# print("使用申万二级行业")
# industry_level = "sw_l2"

# 申万三级，若想使用此行业，请将下面两行代码最左边的 # 及空格删掉，此行不要改动。
print("使用申万三级行业")
industry_level = "sw_l3"

# 聚宽一级，若想使用此行业，请将下面两行代码最左边的 # 及空格删掉，此行不要改动。
# print("使用聚宽一级行业")
# industry_level = "jq_l1"

# 聚宽二级，若想使用此行业，请将下面两行代码最左边的 # 及空格删掉，此行不要改动。
# print("使用聚宽二级行业")
# industry_level = "jq_l2"

# 证监会，若想使用此行业，请将下面两行代码最左边的 # 及空格删掉，此行不要改动。
# print("使用证监会行业")
# industry_level = "zjw"

today = datetime.datetime.today().strftime("%Y-%m-%d")

# 获取所有个股
all_securities_pd = get_all_securities()

# 过滤掉退市股
filtered_securities_pd = all_securities_pd[all_securities_pd.end_date>datetime.date.today()]

# 过滤掉最近 150 天上市的新股
last_150_days = datetime.date.today() - datetime.timedelta(days=150)
filtered_securities_pd = filtered_securities_pd[filtered_securities_pd.start_date<last_150_days]

# 过滤掉 st 股
security_is_st_pd = get_extras('is_st', filtered_securities_pd.index.tolist(), end_date=today, count=1).T
security_is_st_pd.columns=['is_st'] 
filtered_securities_pd = filtered_securities_pd.join(security_is_st_pd)
filtered_securities_pd = filtered_securities_pd[filtered_securities_pd.is_st==False]

security_code_list = filtered_securities_pd.index.tolist()

# 获取个股编码与个股名称对应关系
security_code_name_dict = {}
for row in filtered_securities_pd.itertuples():
    security_code = row.Index
    security_name = row.display_name
    security_code_name_dict[security_code] = security_name

security_industry_dict = {}
industry_code_name_dict = {}
industry_code_security_count_dict = {}
for security_code, industry_info_dict in get_industry(security_code_list).items():
    
    industry_info = industry_info_dict.get(industry_level)
    if not industry_info:
        security_code_list.remove(security_code)
        print("没有获取到{}({})对应的行业信息".format(security_code, security_code_name_dict[security_code]))
        continue
        
    industry_code = industry_info.get('industry_code')
    if not industry_code:
        security_code_list.remove(security_code)
        print("没有获取到{}({})对应的行业编码".format(security_code, security_code_name_dict[security_code]))
        continue
        
    # 获取个股编码与行业编码对应关系
    security_industry_dict[security_code] = industry_code 
    
    # 获取行业内个股总数
    if industry_code not in industry_code_security_count_dict:
        industry_code_security_count_dict[industry_code] = 1
    else:
        industry_code_security_count_dict[industry_code] += 1

    # 获取行业编码与名称对应关系
    industry_name = industry_info.get('industry_name')
    if not industry_name:
        del(security_code_list[security_code])
        print("没有获取到{}({})对应的行业名称".format(security_code, security_code_name_dict[security_code]))
        continue
        
    if industry_code not in industry_code_name_dict:
        industry_code_name_dict[industry_code] = industry_name
    
print("\n过滤掉退市股、上市未满150天的新股、st股，统计总共{}支个股".format(len(security_code_list)))
print("注意，还没有找到方法过滤掉停牌的股票，但影响不大")

last_x_days = 30
print("获取所有个股最近{}日的收盘、成交额数据\nloading".format(last_x_days))
date_security_close_money_pd = get_price(security_code_list, start_date=None, end_date=today,
                                         frequency='daily', fields=['close', 'money'],
                                         skip_paused=False, fq='pre', count=last_x_days, panel=False)

security_date_close_money_dict = {}
for row in date_security_close_money_pd.itertuples():
    
    security_code = row.code
    
    date = row.time.strftime("%Y-%m-%d")
    close = row.close
    money = row.money
    
    info = [date, close, money]
    
    if security_code not in security_date_close_money_dict:
        security_date_close_money_dict[security_code] = [info]
    else:
        security_date_close_money_dict[security_code].append(info)

last_trade_date = date

def get_top_secutiry(top_growth_list):
    
    # top_growth_list
    #
    # [('002046.XSHE', 0.6104129263913824), ('601038.XSHG', 0.4076704545454546), ...]
    
    # 获取行业内前排个股名称
    front_industry_code_security_name_dict = {}
    for item in top_growth_list:
        
        security_code = item[0]
        growth = item[1]
        
        security_name = security_code_name_dict.get(security_code)
        if not security_name:
            print("没有找到{}对应名称".format(security_code))
            continue
            
        industry_code = security_industry_dict.get(security_code)
        if not industry_code:
            print("没有找到{}所属板块".format(security_code))
            continue
            
        info = "{}({:.2%})".format(security_name, growth)
        if industry_code not in front_industry_code_security_name_dict:
            front_industry_code_security_name_dict[industry_code] = [info]
        elif len(front_industry_code_security_name_dict[industry_code]) <= 6:
            front_industry_code_security_name_dict[industry_code].append(info)

    # 行业代码转换为行业名称
    index = []
    data = {}
    security_name_list = []
    for industry_code, top_security in front_industry_code_security_name_dict.items():
        
        if industry_level == "sw_l1":
            industry_name = industry_code_name_dict[industry_code][:-1]
        elif industry_level == "sw_l2":
            industry_name = industry_code_name_dict[industry_code][:-2]
        elif industry_level == "sw_l3":
            industry_name = industry_code_name_dict[industry_code][:-3]
        else:
            industry_name = industry_code_name_dict[industry_code]

        index.append("{}({})".format(industry_name, industry_code))
        security_name_list.append(top_security)

    data["{} 前排个股名称".format(today)] = security_name_list
    return pd.DataFrame(data, index=index)

def get_momentum_result(top_growth_list, date):
    
    # top_growth_list
    #
    # [('002046.XSHE', 0.6104129263913824), ('601038.XSHG', 0.4076704545454546), ...]
    
    # 计算版块内前排个股数量
    front_industry_code_security_count_dict = {}
    front_industry_code_security_name_dict = {}
    for item in top_growth_list:
        
        security_code = item[0]
        
        industry_code = security_industry_dict.get(security_code)
        if not industry_code:
            print("没有找到{}所属板块".format(security_code))
            continue
        
        # 获取行业内上榜个股数量
        if industry_code not in front_industry_code_security_count_dict:
            front_industry_code_security_count_dict[industry_code] = 1
        else:
            front_industry_code_security_count_dict[industry_code] += 1
    
    # 计算动量 （momentum）
    momentum = {}
    for industry_code, total_count in industry_code_security_count_dict.items():
        if industry_code in front_industry_code_security_count_dict:
            count = front_industry_code_security_count_dict[industry_code]
        else:
            count = 0
            
        momentum[industry_code] = float(format(count * count / total_count, '.2f'))

    sorted_momentum_list = sorted(momentum.items(), key=lambda v: v[1], reverse=True)

    # 行业代码转换为行业名称
    index = []
    data = {}
    
    momentum_list = []
    for item in sorted_momentum_list:

        industry_code = item[0]
        if not industry_code:
            continue

        if industry_level == "sw_l1":
            industry_name = industry_code_name_dict[industry_code][:-1]
        elif industry_level == "sw_l2":
            industry_name = industry_code_name_dict[industry_code][:-2]
        elif industry_level == "sw_l3":
            industry_name = industry_code_name_dict[industry_code][:-3]
        else:
            industry_name = industry_code_name_dict[industry_code]
            
        index.append("{}({})".format(industry_name, industry_code))
        momentum_list.append(item[1])

    data[date[5:]] = momentum_list
    return pd.DataFrame(data, index=index)

def get_momentum_list(statistics_days, security_date_close_money_dict):
    
    momentum_list = []
    
    if statistics_days == 1:
        growth_limit = 0.05
    elif statistics_days == 3:
        growth_limit = 0.08
    elif statistics_days == 5:
        growth_limit = 0.1
    elif statistics_days == 10:
        growth_limit = 0.15
    elif statistics_days == 20:
        growth_limit = 0.2
        
#     growth_limit = statistics_days * 0.01
    
    # 统计最近10日的数据
    # [-1, -2, -3....]
    day_list = list(range(-1, -11, -1))
    for day in day_list:
        
        # security_date_close_money_dict
        #
        # {'000001.XSHE': [['2020-03-26', 13.06, 1408651057.34],
        #                  ['2020-03-27', 13.15, 861618663.05],
        #                  ['2020-03-30', 12.94, 852956240.25],
        #                  ...  
        #                  ['2020-05-11', 14.0, 859156594.22],
        #                  ['2020-05-12', 13.79, 772109502.04]],
        #  '000002.XSHE': [['2020-03-26', 26.2, 1513738535.87],
        #                ...
        
        security_growth_dict = {}
        for security_code, date_close_money_list in security_date_close_money_dict.items():
            
            date = date_close_money_list[day][0]
            
            close_start = date_close_money_list[day-statistics_days][1]
            close_end = date_close_money_list[day][1]
            growth = (close_end-close_start)/close_start
            
            security_growth_dict[security_code] = growth

        # sort by security growth
        sorted_list = sorted(security_growth_dict.items(), key=lambda v: v[1], reverse=True)
        
        # filter out growth less than xxx
        top_growth_list = list(filter(lambda item : item[1] >= growth_limit, sorted_list))

        momentum = get_momentum_result(top_growth_list, date)
        momentum_list.append(momentum)
        
        if day == -1:
            top_security = get_top_secutiry(top_growth_list)
        
    return momentum_list, top_security

def recursive_join(momentum_list):
    
    if len(momentum_list) == 1:
        return momentum_list[0]
    else:
        momentum_list[1] = momentum_list[1].join(momentum_list[0])
        del(momentum_list[0])
        return recursive_join(momentum_list)
    
def get_result(statistics_days, security_date_close_money_dict):
    momentum_list, top_security = get_momentum_list(statistics_days, security_date_close_money_dict)
    result = recursive_join(momentum_list)
    result = result.sort_values(by=last_trade_date[5:], ascending=False)[0:6]
    return result.iloc[:, -10:], top_security


# ## 按当日涨幅排序，统计涨幅超过5%的个股，列出板块动量前6名+最强个股（最多6个）

# In[2]:


result, top_security = get_result(1, security_date_close_money_dict)
result.iloc[:, -1:].join(top_security)


# In[3]:


result.T.plot(kind='line', marker='o', title='动量趋势')


# ## 按3日涨幅排序，统计涨幅超过8%的个股，列出板块动量前6名+最强个股（最多6个）

# In[4]:


result, top_security = get_result(3, security_date_close_money_dict)
result.iloc[:, -1:].join(top_security)


# In[5]:


result.T.plot(kind='line', marker='o', title='动量趋势')


# ## 按5日涨幅排序，统计涨幅超过10%的个股，列出板块动量前6名+最强个股（最多6个）

# In[6]:


result, top_security = get_result(5, security_date_close_money_dict)
result.iloc[:, -1:].join(top_security)


# In[7]:


result.T.plot(kind='line', marker='o', title='动量趋势')


# ## 按10日涨幅排序，统计涨幅超过15%的个股，列出板块动量前6名+最强个股（最多6个）

# In[8]:


result, top_security = get_result(10, security_date_close_money_dict)
result.iloc[:, -1:].join(top_security)


# In[9]:


result.T.plot(kind='line', marker='o', title='动量趋势')


# ## 按20日涨幅排序，统计涨幅超过20%的个股，列出板块动量前6名+最强个股（最多6个）

# In[10]:


result, top_security = get_result(20, security_date_close_money_dict)
result.iloc[:, -1:].join(top_security)


# In[11]:


result.T.plot(kind='line', marker='o', title='动量趋势')

