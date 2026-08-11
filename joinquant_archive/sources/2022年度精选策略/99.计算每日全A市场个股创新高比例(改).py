#!/usr/bin/env python
# coding: utf-8

# In[1]:


from jqdata import *
import numpy as np
import pandas as pd


# In[2]:


end_date = '2022-04-12'
check_days = 15 # end_date之前的15个交易日
window = 252  # 此参数为创新高统计周期
gap = 60  # 此参数为创新高间隔，即间隔期内未突破前期新高，只在今天创下新高


# In[3]:


get_ipython().run_cell_magic('time', '', "by_date = get_trade_days(end_date=end_date, count=window+check_days)[0]   \n# 确保end_date之前的window+check_days个交易日已经上市，从而确保get_price取数的正确性\nstock_list = get_all_securities(date=by_date).index.tolist()\n#\nnew_high_list_dic={}\nnewhigh_percent = pd.Series()\n#\nprices = get_price(stock_list, end_date=end_date, frequency='daily', \n                   fields='close', count=window+check_days, panel=False\n                  ).pivot(index='time', columns='code',values='close')\n#\nfor i in range(check_days):\n    check_date = prices.index[window+i].date()\n    price = prices.iloc[i+1:window+i+1]\n    s_result = price.apply(lambda x: np.argmax(x.values) == (len(x) -1) and np.argmax(x.values[:-1])<(len(x)-1-gap))\n    new_high_list = s_result[s_result].index.tolist()\n    newhigh_percent.loc[check_date] = 100*(len(new_high_list) / len(stock_list))\n    new_high_list_dic[check_date]=new_high_list")


# In[4]:


newhigh_percent.tail()


# In[5]:


new_high_list_dic[datetime.datetime.strptime(end_date,"%Y-%m-%d").date()]


# In[ ]:




