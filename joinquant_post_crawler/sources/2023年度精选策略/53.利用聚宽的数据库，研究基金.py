#!/usr/bin/env python
# coding: utf-8

# In[1]:


import numpy as np
import pandas as pd
import datetime as dt
from jqdata import finance


# In[2]:


# 指数
index = '000300.XSHG'


# In[3]:


# 成分股
stocks = get_index_stocks(index)


# In[4]:


# 测试
# 注意：code和symbol的格式，没有后缀！
code = '000001'
df = finance.run_query(query(
        finance.FUND_PORTFOLIO_STOCK
    ).filter(
        finance.FUND_PORTFOLIO_STOCK.symbol==code,
        finance.FUND_PORTFOLIO_STOCK.pub_date > '2020-10-1',
        finance.FUND_PORTFOLIO_STOCK.pub_date < '2021-1-1',
    ))
df[:3]


# In[6]:


# 时间段
dt_start = '2020-10-1'
dt_end = '2021-1-1'


# In[7]:


# 逐股提取基金持仓
fportfolio = pd.Series()
for s in stocks:
    code = s[:6]
    df = finance.run_query(query(
            finance.FUND_PORTFOLIO_STOCK
        ).filter(
            finance.FUND_PORTFOLIO_STOCK.symbol==code,
            finance.FUND_PORTFOLIO_STOCK.pub_date > dt_start,
            finance.FUND_PORTFOLIO_STOCK.pub_date < dt_end,
        ))
    total_value = 1e-8*df.market_cap.sum()
    print(code, total_value)
    fportfolio[s] = total_value


# In[8]:


fportfolio[:3]


# In[9]:


fweight = 100 * fportfolio / fportfolio.sum()
fweight[:3]


# In[10]:


index_weight = get_index_weights(index, dt_start)
index_weight[:3]


# In[15]:


fdelta = pd.Series()
for s in index_weight.index:
    if s in fweight.index:
        fdelta[s] = d = fweight[s] - index_weight.weight[s]


# In[16]:


fdelta = fdelta.sort_values(ascending=False)


# In[19]:


# 最受欢迎的个股
the_best_delta = fdelta[fdelta > 0.5]
the_best_list = the_best_delta.index.tolist()
the_best = index_weight.loc[the_best_list]
the_best['delta'] = the_best_delta
the_best


# In[20]:


# 最被抛弃的个股
the_worst_delta = fdelta[fdelta < -0.5]
the_worst_list = the_worst_delta.index.tolist()
the_worst = index_weight.loc[the_worst_list]
the_worst['delta'] = the_worst_delta
the_worst


# In[27]:


# 基金持仓变异系数
fportfolio.mean() / fportfolio.std()


# In[26]:


# 指数权重变异系数
index_weight.weight.mean() / index_weight.weight.std()


# In[31]:


# 同期价格
price = get_price(stocks, dt_start, dt_end, 'daily', 'close', panel=False)
price[:3]


# In[50]:


# 同期收益
Rt = pd.Series()
for s in stocks:
    p = price[price.code == s].close
    Rt[s] = 100*p.iloc[-1] / p.iloc[0] - 100


# In[58]:


# 基金组合总收益
1e-2 * np.dot(fweight, Rt)


# In[57]:


# 指数收益
index_price = get_price(index, dt_start, dt_end, 'daily', 'close', panel=False)
100*index_price.iloc[-1] / index_price.iloc[0] - 100


# In[ ]:




