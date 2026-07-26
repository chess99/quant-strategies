#!/usr/bin/env python
# coding: utf-8

# In[56]:


import numpy as np
import pandas as pd
import datetime as dt
from jqdata import *
from jqfactor import *
from six import *


# In[57]:


# set option
pd.set_option('display.width', None)
pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)


# In[58]:


# parameter
index = '000300.XSHG' # market index
mday = 21
nday = 241
rday = sqrt(nday)


# In[59]:


# last day
h = history(1, '1d', 'close', index)
dt_last = h.index[0].date()
dt_last


# In[60]:


# all fund
all_fund = get_all_securities('fund', dt_last)
len(all_fund)


# In[61]:


all_fund.head()


# In[62]:


# filter, on list 1-year
dt_1y = dt_last - dt.timedelta(days=365)
all_fund = all_fund[all_fund.start_date < dt_1y]
funds = all_fund.index.tolist()
len(funds)


# In[63]:


# shares
ff = finance.run_query(query(
        finance.FUND_SHARE_DAILY
    ).filter(
        finance.FUND_SHARE_DAILY.code.in_(funds),
        finance.FUND_SHARE_DAILY.date==dt_last,
    )).set_index('code')
shares = ff.shares
shares.head()


# In[64]:


#  filter, size
price = history(1, '1d', 'close', funds).iloc[0]
value = price*shares
value = value[value > 1e8].dropna()
funds = value.index.tolist()
len(funds)


# In[65]:


# filter, liquidity
h = history(mday, '1d', 'money', funds+[index])
hm = h.min()
hx = 1e-6*h[index].mean()
funds = [s for s in funds if hm[s] > hx]
len(funds), hx/10000


# In[66]:


#  history return
h = history(nday, '1d', 'close', funds+[index])
r = np.log(h).diff()[1:]
rx = r[index]


# In[67]:


# filter, volatility
V = 100*rday*r.std()
Vx = V[index]
V = V[V > 1.0]
V = V[V < Vx]
V = V.sort_values()
funds = V.index.tolist()
len(funds)


# In[68]:


# weight
w = 1.0/V
weight = 0.95*w/w.sum()
funds = weight.index.tolist()


# In[69]:


# report
df = pd.DataFrame(index=funds)
df['Value'] = 1e-8*value[funds]
df['Volatility'] = V
df['Weight'] = 100*weight
df['Name'] = all_fund.display_name[funds]
df


# In[70]:


# feature
Rp = np.dot(r[funds], weight)
100*240*Rp.mean(), 100*15.5*Rp.std()


# In[ ]:




