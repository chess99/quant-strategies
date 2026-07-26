# 克隆自聚宽文章：https://www.joinquant.com/post/49554
# 标题：手把手教你构建ETF策略候选池优化版
# 作者：N365128

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
print(today)
#获得etf基金列表
df = get_all_securities(['etf'])
df = df.reset_index().rename(columns={'index':'code'})
df = df[df['start_date'] < datetime.date(2021, 1, 1)]
df = df[df['end_date'] >= datetime.datetime.today().date()]

# 剔除成交额过低（流动性差）的etf
codes = []
for code in df.code:
    price = get_price(code, end_date=today, count=300).dropna()
    price['pchg'] = price['close'].pct_change()
    if price['money'].mean() > 1e7: # 日均低于5000w成交额
        codes.append([code, price['money'].mean()/1e8, price['pchg'].mean(), price['pchg'].std()])
    # else:
        # print(f"排除{code} {df[df['code']==code]['display_name'].iloc[0]}, 成交额均值 {round(price['money'].mean()/1e7, 2)}kw")
codes = pd.DataFrame(codes, columns=['code', 'money','pchg_mean','pchg_std'])
df = df.merge(codes, how='inner', on='code')

raw_codes = df.sort_values('pchg_std')

prices = []
for code in df.code:
#     price = get_price(code, fields='close',end_date='2024-06-26', count=240)
    price = get_price(code, fields='close',end_date=datetime.datetime.today().date(), count=450)
    price['pchg'] = price['close'].pct_change()
    prices.append(price['pchg'].values)
prices = np.array(prices).T
prices = pd.DataFrame(prices, columns=df.code).iloc[1:]

from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
x = prices.T
n_clusters = 24
cluster = KMeans(n_clusters=n_clusters,random_state=42)
y_pred = cluster.fit_predict(x)   ## 每个样本所对应的簇的标签
x['cluster_id'] = y_pred
silhouette_score(x, y_pred)

x = x.reset_index().rename(columns={'index':'code'})
df = df.merge(x[['code','cluster_id']]).sort_values(['cluster_id', 'start_date'])

pd.set_option('display.max_rows', None)#显示全部行
# pd.set_option('display.max_columns', None)#显示全部列
# print(df)

df = df.groupby('cluster_id').first()
print('下面的结果已经是机器学习挑选出来可以直接用的策略池')
print(df)
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
remove = []
for i in union:
    remove += df[df['code'].isin(i)].sort_values('start_date').iloc[1:]['code'].tolist()
    print(i)
    # print(f"排除{code} {df[df['code']==code]['display_name'].iloc[0]}, 成交额均值 {round(price['money'].mean()/1e7, 2)}kw")
print('corr 剔除: ', remove)
df = df[~df['code'].isin(remove)]

print('按照0.85相关性再次过滤的策略池')
print(df)

# remove = df[df['start_date'] > datetime.date(2020, 1, 1)]['code'].tolist()
# print('成立时间：剔除2020后成立的', remove)
# df = df[~df['code'].isin(remove)]
# print('按照成立日期过滤后的策略池')
# print(df)
