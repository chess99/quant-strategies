#!/usr/bin/env python
# coding: utf-8

# In[9]:


# 过滤 ST,停牌，新股,科创板
def filter_st_paused_new(stock_list,days,context):
    df = get_all_securities(types=['stock'], date=context.current_dt)
    kcb=list(df[df.index.str.startswith('688')].index.unique()) # 排除科创板股票
    start_date=(context.current_dt - timedelta(days=days)).date()
    df_new_stock = df[df['start_date'] > start_date]
    stock_list = list(set(stock_list).difference(set(df_new_stock.index)).difference(set(kcb)))
    curr_data = get_current_data()
    stock_list = [stock for stock in stock_list if not curr_data[stock].is_st] # 非ST 几百只
    stock_list = [stock for stock in stock_list if not curr_data[stock].paused]  #非停牌 几十只
    stock_list = [curr_data[stock].code for stock in stock_list if '退' not in curr_data[stock].name] #排除退市股票
    return stock_list


# In[10]:


# 过滤 ST,停牌，新股
def filter_st_paused_new(days,context):
    df = get_all_securities(types=['stock'], date=context.current_dt)
    df = df[~df.index.str.startswith('688')] # 排除科创板股票
    start_date=(context.current_dt - timedelta(days=days)).date()
    df_new_stock = df[df['start_date'] > start_date]
    stock_list = list(set(df.index).difference(set(df_new_stock.index)))
    curr_data = get_current_data()
    stock_list = [stock for stock in stock_list if not curr_data[stock].is_st] # 非ST 几百只
    stock_list = [stock for stock in stock_list if not curr_data[stock].paused]  #非停牌 几十只
    stock_list = [curr_data[stock].code for stock in stock_list if '退' not in curr_data[stock].name] #排除退市股票
    return stock_list


# In[20]:


# 经过测试 get_current_data 全A股遍历，1个字段 100ms左右，增加一个字段增加30ms左右
# get_current_data[symbol].is_st 覆盖 ST，*ST，退 关键词个股 无需再name字段过滤
# 全A股的新股过滤耗时约30ms-40ms
# 整个函数调用 平均160ms左右
# 影响回测速度最大是是数据API的调用次数,调用一次增加几十毫秒延迟
# 使用get_current_data过滤，过滤条件最好分开写，层层过滤，缩小股票池，减少下一次API调用次数


# In[11]:


# 函数测试环境代码
import jqdata
from datetime import datetime,date,timedelta
# 初始化函数，设定要操作的股票、基准等等
def initialize(context):
    g.total_time=0
    g.total_count=0
    

# 每个单位时间(如果按天回测,则每天调用一次,如果按分钟,则每分钟调用一次)调用一次
def handle_data(context, data):
    securities=list(get_all_securities().index)
    start=datetime.now()
    stock_list= filter_st_paused_new(securities,180,context)
    g.total_time+=(datetime.now()-start).microseconds
    g.total_count+=1
    log.info("avg time in microseconds:-----"+str(g.total_time/g.total_count))   

import pandas as pd

# 过滤 ST,停牌，新股,科创板
def filter_st_paused_new(stock_list,days,context):
    df = get_all_securities(types=['stock'], date=context.current_dt)
    kcb=list(df[df.index.str.startswith('688')].index.unique()) # 排除科创板股票
    start_date=(context.current_dt - timedelta(days=days)).date()
    df_new_stock = df[df['start_date'] > start_date]
    stock_list = list(set(stock_list).difference(set(df_new_stock.index)).difference(set(kcb)))
    curr_data = get_current_data()
    stock_list = [stock for stock in stock_list if not curr_data[stock].is_st] # 非ST 几百只
    stock_list = [stock for stock in stock_list if not curr_data[stock].paused]  #非停牌 几十只
    stock_list = [curr_data[stock].code for stock in stock_list if '退' not in curr_data[stock].name] #排除退市股票
    return stock_list


# In[ ]:





# In[ ]:





# In[ ]:




