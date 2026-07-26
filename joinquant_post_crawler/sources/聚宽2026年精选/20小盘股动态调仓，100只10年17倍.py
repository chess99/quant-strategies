#!/usr/bin/env python
# coding: utf-8

# In[1]:


import numpy as np
import pandas as pd
import datetime as dt
import json


# In[2]:


pd.set_option('display.width', None)
pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)


# In[3]:


funds = [
    '159650.XSHE', # 国开ETF
    '511020.XSHG', # 活跃国债ETF
    '518880.XSHG', # 黄金ETF
    '513500.XSHG', # 标普500
    '513300.XSHG', # 纳指100
    ]


# In[4]:


# report
for s in funds:
    print(s, get_security_info(s).display_name)


# In[5]:


# save
write_file('funds', json.dumps(funds))


# In[6]:


# load
_funds = json.loads(read_file('funds'))
_funds


# In[ ]:




