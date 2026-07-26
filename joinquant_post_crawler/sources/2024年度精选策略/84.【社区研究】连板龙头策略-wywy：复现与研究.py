#!/usr/bin/env python
# coding: utf-8

# In[17]:


from jqdata import *
import datetime
import pandas as pd 
stock_df = get_all_securities(types=['stock'], date=None)
stock_df['code'] = stock_df.index
# 过滤科创和创业板，这个看个人喜欢
stock_df = stock_df[~(stock_df['code'].str.startswith("3") | stock_df['code'].str.startswith("68"))]

stock_lists = list(stock_df['code'])
stock_df.head()

# 获取交易日列表，因为财务数据限制了单次获取条数，干脆分天获取了
start_date = '2022-01-01'

# 自己设置，简单示例
end_date = '2022-03-01'
trade_days = get_trade_days(start_date=start_date, end_date=end_date, count=None)
trade_days[:5],trade_days[-5:]


# In[18]:


# 量价信息
price_df = get_price(stock_lists, start_date=start_date, end_date=end_date, frequency='daily', fields=['open','close','low','high','volume','money',
        'high_limit','low_limit','pre_close','paused'], skip_paused=False, fq='post', count=None,round=True,panel=False)
price_df.head()


# In[19]:


has_limit_stocks = list(price_df.query("close == high_limit")['code'].unique())


# In[20]:


stock_lists = has_limit_stocks


# In[21]:


st_df = get_extras('is_st', stock_lists, start_date=start_date, end_date=end_date)
st_df = st_df.stack().reset_index().rename(columns={'level_0':'time','level_1':'code',0:'is_st'})
st_df.head()


# # 数据合并

# In[22]:


merge_df = price_df.merge(stock_df,how='left',on=['code'],suffixes=['','_x'])
merge_df = merge_df.merge(st_df,how='left',on=['code','time'],suffixes=['','_x'])
merge_df['list_days'] = (merge_df['time'] - pd.to_datetime(merge_df['start_date'])).dt.days
merge_df.head()


# In[23]:


def cal_lb_count(xs):
    """
    计算股票连板数
    """
    x = 0
    for d in xs[::-1]:
        if d == 0:
            return x
        else:
            x += 1
            
    return x 
    


# In[24]:


merge_df['open_valid1'] = merge_df.groupby('code')['open'].shift(-1)
merge_df['is_close_high_limit'] = (merge_df['close'] == merge_df['high_limit']) * (1-merge_df['paused'])
merge_df['is_low_high_limit'] = (merge_df['low'] == merge_df['high_limit']) * (1-merge_df['paused'])
merge_df['is_low_low_limit'] = (merge_df['low'] == merge_df['low_limit']) * (1-merge_df['paused'])
merge_df['is_close_low_limit'] = (merge_df['close'] == merge_df['low_limit']) * (1-merge_df['paused'])
merge_df['最大连板数'] = merge_df.groupby('code').rolling(20)['is_close_high_limit'].apply(lambda x:cal_lb_count(x)).values
merge_df['open_pct_valid_1'] = merge_df['open_valid1']/merge_df['close']
merge_df.head()


# ## 衍生特征

# In[25]:


# 概念龙头特征计算
result_dfs = []
from tqdm import tqdm
for t,tmp_df in tqdm(merge_df.query("is_close_high_limit == 1").groupby('time')):
    security = list(tmp_df['code'])
    date = t
    cs = get_concept(security, date=date)
    dfs = []
    for code,concept_data in cs.items():
        for c in concept_data['jq_concept']:
            if c['concept_name'] not in ['转融券标的', '融资融券', '深股通', '沪股通']:
                dfs.append({'code':code,'concept':c['concept_name']})
    concept_df = pd.DataFrame(dfs)

    a = concept_df['concept'].value_counts()
    hot_concept_limit_count = a.max()
    hot_concepts = list(a[a==hot_concept_limit_count].index)
    hot_concept_stocks = list(concept_df[concept_df['concept'].isin(hot_concepts)].code)
    hot_concept_limit_count,hot_concepts,hot_concept_stocks
    result_dfs.append({"time":t,
                        "概念龙头涨停数":hot_concept_limit_count,
                      "概念龙头列表":hot_concepts,
                       "概念龙头股票列表":hot_concept_stocks,
                      })


hot_concept_df = pd.DataFrame(result_dfs)
hot_concept_df.head()


# In[26]:


# 当天市场特征
day_feature_df = pd.DataFrame(merge_df.groupby('time')['最大连板数'].max().rename("市场最大连板数"))
day_feature_df['一字板数量'] = merge_df.groupby('time')['is_low_high_limit'].sum()
day_feature_df['涨停板数量'] = merge_df.groupby('time')['is_close_high_limit'].sum()
day_feature_df['涨停溢价'] = merge_df.query("is_close_high_limit == 1").groupby('time')['open_pct_valid_1'].mean()
day_feature_df['近3天市场最大连板数'] = day_feature_df['市场最大连板数'].rolling(3).max()
day_feature_df['近3天市场平均涨停溢价'] = day_feature_df['涨停溢价'].rolling(3).mean()
day_feature_df['近3天市场最高涨停溢价'] = day_feature_df['涨停溢价'].rolling(3).max()
day_feature_df['近3天市场涨停溢价std'] = day_feature_df['涨停溢价'].rolling(3).std()
day_feature_df['近3天市场最低涨停溢价'] = day_feature_df['涨停溢价'].rolling(3).min()
day_feature_df['今天是否等于近3天市场最大连板数'] = day_feature_df['市场最大连板数']==day_feature_df['近3天市场最大连板数']
day_feature_df.tail(10)


# In[27]:


day_feature_df = day_feature_df.merge(hot_concept_df,how='left',left_index=True,right_on=['time'])
day_feature_df.head()


# In[28]:


# 只看今天有涨停的票
merge_df = merge_df.query("is_close_high_limit == 1").merge(day_feature_df,how='left',on=['time'],suffixes=['','_市场'])
merge_df.head()


# In[29]:



# - 股票是否在概念龙头中
merge_df['股票在概念龙头'] = merge_df.apply(lambda row: row['code'] in row['概念龙头股票列表'],axis=1)


# In[ ]:




