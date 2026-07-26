#!/usr/bin/env python
# coding: utf-8

# In[1]:


import numpy as np
import pandas as pd
import datetime as dt
from jqdata import *
import statsmodels.api as sm


# In[2]:


# 信息设置
pd.set_option('display.width', None)
pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)


# In[3]:


#
# 基金市场研究
#


# In[7]:


#  参数
index = '399311.XSHE'


# In[8]:


# 当前
dt_now = dt.datetime.now().date()
dt_now


# In[9]:


# 股票池
stocks = get_index_stocks(index)


# In[11]:


# 数据段
dt_end = dt.date(2023, 3, 31)
reportId = 403001 # 年度403006，半年度403005，第一季度403001


# In[12]:


# 测试
# 注意：code和symbol的格式，没有后缀！
stock = '600519'
df = finance.run_query(query(
        finance.FUND_PORTFOLIO_STOCK
    ).filter(
        finance.FUND_PORTFOLIO_STOCK.symbol == stock,
        finance.FUND_PORTFOLIO_STOCK.period_end == dt_end,
        finance.FUND_PORTFOLIO_STOCK.report_type_id == reportId,
    ).limit(5)
    )
df


# In[13]:


# 逐股提取基金持仓
fportfolio = pd.Series()
for s in stocks:
    stock = s[:6]
    df = finance.run_query(query(
            finance.FUND_PORTFOLIO_STOCK
        ).filter(
            finance.FUND_PORTFOLIO_STOCK.symbol == stock,
            finance.FUND_PORTFOLIO_STOCK.period_end == dt_end,
            finance.FUND_PORTFOLIO_STOCK.report_type_id == reportId,
        ).order_by(finance.FUND_PORTFOLIO_STOCK.market_cap.desc())                           
        )
    total_value = 1e-8*df.market_cap.sum()
    fportfolio[s] = total_value
    print(s, get_security_info(s).display_name, total_value) # 提取数据过程很长，需要不停输出信息以示运行进度


# In[14]:


fportfolio.head()


# In[15]:


fweight = 100 * fportfolio / fportfolio.sum()
fweight = fweight.sort_values(ascending=False)
fweight.head()


# In[16]:


index_weight = get_index_weights(index, dt_end)
index_weight = index_weight.sort_values(by='weight', ascending=False)
index_weight[:10]


# In[17]:


fdelta = pd.Series()
for s in index_weight.index:
    if s in fweight.index:
        fdelta[s] = fweight[s] - index_weight.weight[s]
fdelta = fdelta.sort_values(ascending=False)


# In[18]:


# 最受欢迎的个股
the_best_delta = fdelta[fdelta > 0].sort_values(ascending=False)
the_best_list = the_best_delta.index.tolist()
the_best = index_weight.loc[the_best_list]
the_best['delta'] = the_best_delta
print(len(the_best))
the_best.head(15)


# In[19]:


# 最被抛弃的个股
the_worst_delta = fdelta[fdelta < 0].sort_values(ascending=True)
the_worst_list = the_worst_delta.index.tolist()
the_worst = index_weight.loc[the_worst_list]
the_worst['delta'] = the_worst_delta
print(len(the_worst))
the_worst.head(15)


# In[ ]:




