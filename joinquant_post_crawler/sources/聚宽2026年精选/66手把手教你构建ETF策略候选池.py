#!/usr/bin/env python
# coding: utf-8

# In[1]:


from jqdata import *
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import datetime
import warnings
from tqdm import tqdm
import torch 
import torch.nn as nn
import matplotlib.pyplot as plt
import torch.nn.functional as F
from torch.utils.data import Dataset
from torch.utils.data import DataLoader
from torch.utils.data import random_split
from torch.utils.data import TensorDataset

warnings.filterwarnings('ignore')

plt.rcParams['font.sans-serif'] = ['SimHei']  # 中文字体设置-黑体
plt.rcParams['axes.unicode_minus'] = False  # 解决保存图像是负号'-'显示为方块的问题
today = str(datetime.datetime.today().date())


# # 获取所有ETF，过滤流动性较差的

# In[2]:


#获得etf基金列表
df = get_all_securities(['etf'])
df = df.reset_index().rename(columns={'index':'code'})
df = df[df['start_date'] < datetime.date(2023, 1, 1)]


# In[3]:


# 剔除成交额过低（流动性差）的etf
codes = []
for code in df.code:
    price = get_price(code, end_date=today, count=1000).dropna()
    price['pchg'] = price['close'].pct_change()
    if price['money'].mean() > 5e7: # 日均低于5000w成交额
        codes.append([code, price['money'].mean()/1e8, price['pchg'].mean(), price['pchg'].std()])
    else:
        print(f"排除{code} {df[df['code']==code]['display_name'].iloc[0]}, 成交额均值 {round(price['money'].mean()/1e7, 2)}kw")
codes = pd.DataFrame(codes, columns=['code', 'money','pchg_mean','pchg_std'])
df = df.merge(codes, how='inner', on='code')


# In[4]:


raw_codes = df.sort_values('pchg_std')


# # 获取ETF日线数据

# In[5]:


today = datetime.datetime.today().date()
end_date = str(today)  # 计算截止日

prices = []
for code in df.code:
    price = get_price(code, fields='close',end_date=end_date, count=240)
    price['pchg'] = price['close'].pct_change()
    prices.append(price['pchg'].values)
prices = np.array(prices).T
prices = pd.DataFrame(prices, columns=df.code).iloc[1:]


# # K-Means对ETF走势进行聚类
# ## 为了避免误杀，我这里把聚类簇的数量设置的比较多，如果太少的话不相似的ETF也可能聚到一起

# In[8]:


from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
x = prices.T
n_clusters = 30
cluster = KMeans(n_clusters=n_clusters,random_state=42)
y_pred = cluster.fit_predict(x)   ## 每个样本所对应的簇的标签

print(silhouette_score(x, y_pred))

x['cluster_id'] = y_pred


# In[9]:


x = x.reset_index().rename(columns={'index':'code'})
df = df.merge(x[['code','cluster_id']]).sort_values(['cluster_id', 'start_date'])


# # 聚类到同一个簇里的ETF，仅保留发行时间最早的，原因如下：
# ## 1. 成立最早的一般成交额最大，流动性最好
# ## 2. 成立最早的历史数据最多，做模型训练数据也更多

# In[10]:


# 每个簇里面选 成立最早的
df = df.groupby('cluster_id').first()


# # 然而聚类效果并不能一次解决问题，如下所示还是有部分类似的ETF被保留下来
# # 当然了，这个池子也是能用的

# In[11]:


df


# # 如果想要更精简的池子就继续上武器：相关系数过滤，ETF之间两两计算相关系数，当相关系数超过0.85（我拍的）的ETF对，仅保留成立时间早的

# In[12]:


# 再用相关系数聚类一遍
corr = prices[df.code].corr()

codes = df.code.tolist()
union = []
for i in codes:
    for j in codes:
        if i == j:
            continue
        if corr.loc[i, j] > 0.85:
            find = False
            for k in range(len(union)):
                if i in union[k] or j in union[k]:
                    union[k].add(i)
                    union[k].add(j)
                    find = True
            if not find:
                union.append(set([i, j]))


# In[13]:


# 同理，仅保留成立最早的
remove = []
for i in union:
    remove += df[df['code'].isin(i)].sort_values('start_date').iloc[1:]['code'].tolist()
print('corr 剔除: ', remove)
df = df[~df['code'].isin(remove)]


# # 看下结果是不是清爽很多

# In[14]:


df


# # （可选）如果要构建ETF候选池用于模型训练的，过滤下数据较少的EFT，即把成立晚的ETF剔除，这里我拍的2020年为阈值
# 
# # 最终结果里是不是有很多是经常出现在ETF策略里的老熟人，也可以一定程度解释为啥要选这几只ETF组合做策略比较好

# In[15]:


# 去掉较晚成立的
remove = df[df['start_date'] > datetime.date(2020, 1, 1)]['code'].tolist()
print('成立时间：剔除2020后成立的', remove)
df = df[~df['code'].isin(remove)]
df


# # 画一下走势图人眼看下是不是相关度比较低，还比较符合预期
# ## 注意，我的方法只是筛选相关度低，流动性好的ETF，所以结果中会有一些和其他相关低但是常年下跌的，比如医药ETF，房产ETF，我这里没把它从池子里剔除，你做策略回测可以把它剔除掉，不过这也算是引入了未来函数吧？
# ## 换句话说，如果你的池子里有常年下跌的，但是策略收益仍然可观，那是不是说明策略鲁棒性较好，你也说不准以前一直下跌的ETF未来会不会反转大涨吧？

# In[16]:


plt.rcParams['figure.figsize'] = [20, 10]
codes = df.code.unique().tolist()
df = []
for code in tqdm(codes):
    tmp = get_price(code, start_date='2017-01-01', end_date=today, fields=['close', 'low']).dropna()
    tmp['close_norm'] = tmp['close'] / tmp['close'].iloc[0]
    tmp['close_norm'] = tmp['close_norm'].rolling(5).mean()
    tmp['close_norm'].plot()
    tmp['code'] = code
    df.append(tmp)
df = pd.concat(df).dropna()


# # 一个Tip：如果要用于模型训练，511010 国债ETF要去掉
# ## 1. 国债ETF基本和余额宝一样，走势几乎是一个直线，稳定收益没有波动，和其他波动较大的ETF相比完全是异常值，会严重干扰模型学习，起码我测试是这样
# ## 2. 而且国债ETF的收益/走势还需要预测么？

# In[ ]:




