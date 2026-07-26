#!/usr/bin/env python
# coding: utf-8

# ### 导入基本的类库

# In[1]:


import numpy as np
import pandas as pd
from jqdata import *

import requests
import re
from bs4 import BeautifulSoup


# ### 从聚宽获取ETF信息
# 
# 聚宽的信息还是比较全的。但是有些属性不全，比如想要知道哪些ETF可以T+0，哪些是跨境ETF，管理机构是谁。tushare上的免费数据可以拿，但要积分。所以打算结合站外数据做一下填充。

# In[2]:


trade_date = get_trade_days(end_date=datetime.datetime.now(), count=10)
# 获取聚宽ETF数据
funds = get_all_securities(['fund'], date=trade_date[-1])  # 所有基金
etfs = funds[funds['type'] == 'etf']  # 挑出ETF
etfs.tail()


# In[3]:


# 格式整理
df_etfs = pd.DataFrame(index=etfs.index)
codes = [code.split('.')[0] for code in etfs.index.values]
df_etfs['代码'] = codes
df_etfs['全称'] = etfs.display_name
df_etfs['简称'] = etfs.name
df_etfs['开始时间'] = etfs.start_date
df_etfs['结束时间'] = etfs.end_date
df_etfs.reset_index(inplace=True, drop=True)
df_etfs.tail()


# ### 从站外获取ETF数据

# In[5]:


# html 内容请求
def get_html(code):
    # url中的参数是个ETF的代码
    link = 'http://.../'+code+'.html?spm=search'  # 为了成为一个有责任心的爬虫者，这里暂不公开网站地址啦
    headers = {'User-Agent' : 'Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US; rv:1.9.1.6) Gecko/20091201 Firefox/3.5.6'} 
    r = requests.get(link, headers= headers)
    r.encoding='utf-8'
    return r.text


# In[21]:


# 获取特征内容
def get_content(code):
    text = get_html(code)
    soup = BeautifulSoup(text,"lxml")
    div = soup.find("div", class_="infoOfFund")
    td = div.find_all('td')

    fund_dict = dict()
    fund_dict['代码'] = code
    for t in td:
        text = t.text
        key_value = re.split('[:：|]',text.strip())
        fund_dict[key_value[0]] = key_value[1]
        if len(key_value) > 2:
            fund_dict[key_value[2]] = key_value[3]

    return fund_dict


# In[22]:


# 测试爬到的数据
get_content('515950')


# In[23]:


# 开始将所有的数据爬一遍，并组合成DataFrame格式
list_f = []
for code in df_etfs['代码']:
    try:
        contect_dict = get_content(code)
        list_f.append(contect_dict)
    except:
        print(code+'的内容查不到')
df_f = pd.DataFrame(list_f)
df_f.head()


# ### 内容合并
# 
# 最后的步骤就简单，将聚宽的数据和爬到的数据整合到一起，然后导出。将excel收到自己的备用百宝箱里，常用常新。今后有需要的其它属性后再更新。

# In[46]:


e_f = df_etfs.set_index("代码")
f_f = df_f.set_index("代码")
f_f['名称'] = e_f['全称']
f_f.head()


# In[48]:


# 最基础类型数据导出
f_f.to_excel('ETFS.xlsx')


# ___
# 
# #### 针对宽友的要求，后续添加的数据列（持续更新)

# In[54]:


trade_date = get_trade_days(end_date=datetime.datetime.now(), count=10)


# In[56]:


# 增加当日单位净值数据 2020-4-14
codes = [normalize_code(code) for code in e_f['代码']]
unit_net_values = get_extras('unit_net_value', 
                             codes, 
                             end_date=trade_date[-2], 
                             count=1,
                             df=False)
df_unit_net = pd.DataFrame(unit_net_values, index=['unit_net_value']).T
df_unit_net.tail()  # 净值查看


# In[64]:


# 数据合并
indexs = [normalize_code(code) for code in e_f['代码']]
df_old = e_f
df_old['code'] = indexs
df_old.set_index('code', inplace=True)
df_old['基金净值'] = df_unit_net['unit_net_value']
df_new = df_old.reset_index(drop=False)
df_new.tail()


# In[66]:


# 包含净值列数据的导出
df_new.to_excel('ETFS_NEW.xlsx')

