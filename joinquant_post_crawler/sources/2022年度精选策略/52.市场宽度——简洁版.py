#!/usr/bin/env python
# coding: utf-8

# In[1]:


from jqdata import *
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import datetime
import warnings

warnings.filterwarnings('ignore')

plt.rcParams['font.sans-serif'] = ['SimHei']  # 中文字体设置-黑体
plt.rcParams['axes.unicode_minus'] = False  # 解决保存图像是负号'-'显示为方块的问题


# In[2]:


def display_mkt(df, p_vmax=100):
    fig = plt.figure(figsize=(16, count_))
    grid = plt.GridSpec(1, 10)
    cmap = sns.diverging_palette(200, 10, as_cmap=True)
    
    heatmap1 = fig.add_subplot(grid[:, :-1])
    heatmap1.xaxis.set_ticks_position('top')
    ax = sns.heatmap(df[df.columns[:-1]], vmin=0, vmax=100, annot=True, fmt="d", cmap=cmap,
                annot_kws={'size': 10}, cbar=False)
    ax.set_yticklabels(df.index.strftime('%Y-%m-%d'))
    
    heatmap2 = fig.add_subplot(grid[:, -1])
    heatmap2.xaxis.set_ticks_position('top')
    sns.heatmap(df[[df.columns[-1]]], vmin=0,
                vmax=p_vmax, # 方案差异点
                annot=True, fmt="d", cmap=cmap, annot_kws={'size': 10})

    plt.yticks([])
    plt.show()
    # 显示折线图
    plt.style.use({'figure.figsize': (16, 8)})
    df[df.columns[-1]].plot()


# In[3]:


def display_mkt2(df, p_vmax=100):
    """
    只显示总体列，而不显示各个行业
    """
    fig = plt.figure(figsize=(16, count_))
    grid = plt.GridSpec(1, 10)
    cmap = sns.diverging_palette(200, 10, as_cmap=True)
    
    heatmap2 = fig.add_subplot(grid[:, -1])
    heatmap2.xaxis.set_ticks_position('top')
    df_tot = df[[df.columns[-1]]]
    ax = sns.heatmap(df_tot, vmin=0,
                vmax=p_vmax, # 方案差异点
                annot=True, fmt="d", cmap=cmap, annot_kws={'size': 10})
    ax.set_yticklabels(df_tot.index.strftime('%Y-%m-%d'))

    plt.show()


# ### 指定参数

# In[4]:


end_date = '2022-09-02'  # 计算截止日
count_ = 20 # 计算天数


# ### 一、 准备数据

# In[5]:


by_date = get_trade_days(end_date=end_date,count=count_+20)[0]
stock_list = get_all_securities(date=by_date).index.tolist()  # count_+20个交易日之前就已经上市的
#
df_close = get_price(stock_list, end_date=end_date, count=count_+20, fields='close', panel=False
                    ).pivot(index='time', values='close', columns='code')
df_bias = df_close.iloc[20:] > df_close.rolling(20).mean().iloc[20:]  # C > MA20


# In[6]:


df_bias.tail()


# ### 二、 按行业汇总

# In[7]:


df_industries = get_industries('sw_l1', date=end_date)
df_industries.head()


# In[8]:


df=pd.DataFrame()
columns = set(df_bias.columns)
for idx, row in df_industries.iterrows():
    ind_stocks = set(get_industry_stocks(idx, date=end_date))  # 行业成分股
    ind_avail_stocks = list(columns & ind_stocks) # 成分股 在df_bias表中存在的
    if ind_avail_stocks:
        # 计算该行业成分股C>MA20的百分比，技巧：df_bias[ind_avail_stocks]
        df[row['name']] = (100*(df_bias[ind_avail_stocks].sum(axis=1))/len(ind_avail_stocks)).astype(int)
#
df.sort_index(ascending=False, inplace=True)


# In[9]:


df.head()


# ### 三、图形显示
# 有三种显示方案可以选择

# #### 方案一：直接加总各行业及格率
# 
# 这是雷公的原始方案。该方案表面上看是简单地汇总了各个行业的及格率，但在图形化显示时，通过赋予了vmax，让不同的值显示出不同的颜色。
# 
# 关键是参数vmax。多少个行业，每个行业的及格率最大值可达100，所以汇总后，总体的最大值顶格(vmax)=行业数*100
# 
# 显示时，heatmap根据各个值相对于vmax的水平，赋予了表示冷暖的不同颜色。

# In[10]:


df_1 = df.copy(deep=True)   # 为不破坏原数据，以比较3种方案，所以先copy
vmax=len(df.columns) * 100

# 方案 1：各行业的及格率 再汇总
df_1['总体']=df_1.sum(axis=1)
display_mkt(df_1, p_vmax=vmax)  


# #### 方案二：行业及格率的再评均
# 方案二是方案一的延续。方案1的汇总数——“总体”，会显示出大大小小的数字，这数字究竟意味着什么？
# 
# 前面已经解释过了，在图形展示时，这些值会按照相对于vmax的水平，显示出不同颜色。
# 
# 既然如此，方案二就试图直截了当，去求行业及格率的再平均数，在“总体”这一列中显示相对百分比值，而不是绝对值。
# 
# 举个例子。申万一级行业31个，每个行业的及格率都可能到100，所以汇总后，可能的最大值(vmax)是3100，而2022年9月2日的及格率加总是1127，而1127/3100=36%，那就在“总体”列中直接显示36。表示居于vmax的36%水平。

# In[11]:


df_2 = df.copy(deep=True)
# 方案 2
df_2['总体']=(df_2.sum(axis=1)/len(df_2.columns)).astype(int)  # 方案3
display_mkt(df_2, p_vmax=100)


# #### 方案三:市场整体比例
# 
# 这是我设想的：不区分行业，直接计算所有股票C>MA20的比例。这样图形既显示了分行业的及格率，也显示了市场整体的及格率。
# 
# 例如，2022-9-2，合格的股票共4654只，其中及格的（Close>MA20）是1360只，1360/4654=29%，于是“总体”显示为29。

# In[12]:


df_3 = df.copy(deep=True)
# 方案 3
df_3['总体']=(100*df_bias.sum(axis=1)/len(df_bias.columns)).astype(int)
display_mkt(df_3, p_vmax=100)  # v_max：最大值顶格100


# In[ ]:




