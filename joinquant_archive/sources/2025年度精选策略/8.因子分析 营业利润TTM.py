#!/usr/bin/env python
# coding: utf-8

# In[1]:


import pandas as pd
import numpy as np

import seaborn as sns
import scipy.stats as st
import time

from datetime import datetime, timedelta
from scipy.stats import ttest_ind
from multiprocessing.dummy import Pool as ThreadPool

import statsmodels.api as sm
from pandas import DataFrame,Series

import jqdata
sns.set_style('whitegrid')

import matplotlib
matplotlib.rcParams['font.family']='serif'
matplotlib.rcParams['font.serif']='SimHei'
matplotlib.rcParams['axes.unicode_minus']=False # 处理负号问题
matplotlib.rcParams['font.sans-serif'] = ['FangSong'] # 指定默认字体
from matplotlib.font_manager import FontProperties 
font = FontProperties(fname=r"simsun.ttc", size=14) 
import matplotlib.pyplot as plt


# 忽略警告
import warnings
warnings.filterwarnings("ignore")

from jqfactor import get_all_factors    
from jqfactor import get_factor_values

from six import BytesIO
import pickle

from IPython.display import HTML,display,clear_output

import os


# # 1参数准备

# In[2]:


index = 'all'


# In[3]:


start = '2008-01-01'
end = '2020-07-11'
interval = 20 # 间隔区间

# 日期列表
date_list = list(jqdata.get_trade_days(start_date = start, end_date = end))

# 需要回测的日期
trade_date_list = list(filter(lambda x:date_list.index(x) % interval == 0, date_list))


# In[4]:


# 回测日期的上一个交易日
pre_date_list = list(map(lambda x:jqdata.get_trade_days(end_date = x,count=2)[0],trade_date_list))


# In[5]:


facName = "operating_profit_ttm"#'TVSTD20'


# # 2 工具函数

# ## 2.1 数据获取

# ### 股票池获取

# In[6]:


def get_All_trade_tickers(date):
    """
    给定日期，获取这一天上市时间不低于60天的股票（参照中证全指指数编制）
    输入：
        date: str， 'YYYYMMDD'格式
    返回：
        list： 元素为股票ticker
    """
    df = get_all_securities(types=['stock'], date=date)
    daysBefore = jqdata.get_trade_days(end_date=date, count=60)[0]
    df['60DaysBefore'] = daysBefore
    df = (df[df['start_date'] < df['60DaysBefore']])
    return df.index.tolist()


# In[7]:


def get_idx_cons(idx, date):
    """
    获取某天指数成分股ticker列表
    输入:
        idx:str，指数代码
        date:str，'YYYY-MM-DD'格式
    返回：
        list:指数成份股的ticker
    """
    universe_idx = get_index_stocks(idx, date=date)
    
    universe_A = get_All_trade_tickers(date)
    return list(set(universe_idx) & set(universe_A))


# ### 价格数据获取

# In[8]:


def getPriceData(date):
    all_stocks = get_all_securities(types=['stock'], date=date).index.tolist()
    price=get_price(all_stocks, start_date=date, end_date=date, frequency='1d',fields=['close'])['close']
    return price

#getPriceData('2019-11-13').T


# ### 行业数据获取

# In[9]:


def getStockIndustry(fdate):
    stock_list = get_all_securities(types=['stock'], date=fdate).index.tolist()
    industry_set = ['801010', '801020', '801030', '801040', '801050', '801080', '801110', '801120', '801130', 
              '801140', '801150', '801160', '801170', '801180', '801200', '801210', '801230', '801710',
              '801720', '801730', '801740', '801750', '801760', '801770', '801780', '801790', '801880','801890']
    df = pd.DataFrame(index = stock_list,columns = [fdate])
    df.index.name = 'code'
    for i in range(len(industry_set)):
        industry = get_industry_stocks(industry_set[i], date = fdate)
        industry = list(set(industry) & set(df.index.tolist()))
        df[fdate].ix[industry] = industry_set[i]
        
    return df.T.fillna('other')       

#getStockIndustry('2019-12-11').fillna('801140')        


# ### 市值数据获取

# In[10]:


def getStockMktValue(fdate):
    df = get_factor_data(fdate, "market_cap", index) 
    df.columns = ['code','tradeDate','MC']
    df = df.reset_index()
    df = df.pivot(index='tradeDate', columns='code', values='MC')
    return df

#getStockMktValue('2019-11-13')


# ### 因子数据获取

# In[11]:



# 得到因子数据
def get_factor_data(fdate, factor, index):
    
    if index == 'all':
        stock_list = get_all_securities(types=['stock'], date=fdate).index.tolist()
    else:
        stock_list = get_index_stocks(index, date=fdate)

    factor_data = get_factor_values(securities=stock_list, factors=[factor],start_date=fdate, end_date=fdate)[factor].T
    factor_data.columns = [factor]
    factor_data['tradeDate'] = fdate
    factor_data = factor_data[['tradeDate',factor]]
    factor_data = factor_data.reset_index()
    return factor_data

'''
fdate = '2020-07-14'
index = 'all'
all_factor_df = get_all_factors()
#factor = "market_cap"#all_factor_df.factor.tolist()[0]
df = get_factor_data(fdate, facName, index) 
df
'''


# In[12]:


def get_factor_by_day(tdate):
    '''
    根据日期，获取当天的因子值
    tdate：str，'YYYYMMDD'格式
    '''
    
    cnt = 0
    while True:
        try:
            #x = get_all_factors1(tdate, factors, TTM_factors, fac_dict, index)
            x = get_factor_data(tdate, facName, index)
            return x
        except Exception as e:
            cnt += 1
            if cnt >= 3:
                print('error get factor data: ', tdate)
                break
                
'''tdate = '2019-11-13'          
df_tmp = get_factor_by_day(tdate)
df_tmp'''


# ## 2.2 数据处理

# ### 时间格式转换

# In[13]:


def dateTransform(date_list_to_transform):
    date_str_list = list(map(lambda x:x.strftime('%Y-%m-%d') if type(x)!=str else x ,date_list_to_transform))
    date_list_result = list(map(lambda x:datetime.strptime(x, '%Y-%m-%d'),date_str_list))
    
    return date_list_result


# ### 行业中位数填充缺失值

# In[14]:


def replace_nan_indu(factor,indu):
    """缺失值填充函数，使用行业中位数进行填充
    输入：
        factor：DataFrame，index为日期，columns为股票代码，value为因子值
    返回：
        factor：格式保持不变，为填充后的因子
    """ 
    fill_factor = pd.DataFrame()
    for date in factor.index[:]:
        # 因子值
        factor_array = factor.ix[date, :].to_frame('factor')
        # 行业值
        indu_array = indu.ix[date, :].dropna().to_frame('industryName')
        # 合并
        factor_array = factor_array.merge(indu_array, left_index=True, right_index=True, how='inner')
        # 行业中值
        mid = factor_array.groupby('industryName').median()
        mid.columns = ['mid_values']
        #print(mid)
        factor_array = factor_array.merge(mid, left_on='industryName', right_index=True, how='left')
        # 行业中值填充缺失
        factor_array['factor'][pd.isnull(factor_array['factor'])] = factor_array['mid_values'][pd.isnull(factor_array['factor'])]
        # 将当前日期的因子数据追加到结果
        fill_factor = fill_factor.append(factor_array['factor'].to_frame(date).T)
        
    return fill_factor

#replace_nan_indu(factor_data,indu)


# ### 根据股票池筛选因子

# In[15]:


def get_universe_factor(factor, idx=None, univ=None):
    """
    筛选出某指数成份股或者指定域内的因子值
    输入：
        factor:DataFrame，index为日期，columns为股票代码，value为因子值
        idx:指数代码，000300:沪深300，000905：中证500，000985：中证全指
        univ:DataFrame，index为日期，'YYYYMMDD'格式。columns为'code'，value为股票代码
    返回：
        factor:DataFrame，指定域下的因子值，index为日期，columns为股票代码，value为因子值
    """
    universe_factor = pd.DataFrame()
    if idx is not None:
        for date in factor.index:
            universe = get_idx_cons(idx, date)
            universe_factor = universe_factor.append(factor.loc[date, universe].to_frame(date).T)
    else:
        if univ is not None:
            for date in factor.index:
                universe = univ.loc[date, 'code'].tolist()
                universe_factor = universe_factor.append(factor.loc[date, universe].to_frame(date).T)
        else:
            raise Exception('请指定成分股或域')
    return universe_factor


# ### 因子数据处理

# In[16]:


# 去极值
def winsorize(se):
    q = se.quantile([0.025, 0.975])
    if isinstance(q, pd.Series) and len(q) == 2:
        se[se < q.iloc[0]] = q.iloc[0]
        se[se > q.iloc[1]] = q.iloc[1]
    return se

# 标准化
def standardize(se):
    mean = se.mean()
    std = se.std()
    se = (se - mean)/std
    return se

# 中性化
def neutralize(factor_se, market_cap_se, concept_se):
    
    stock_list = factor_se.index.tolist()
    
    # 行业数据哑变量
    groups = array(concept_se.ix[stock_list].tolist())
    dummy = sm.categorical(groups, drop=True)
    
    # 市值对数化
    market_cap_log = np.log(market_cap_se.ix[stock_list].tolist())
    
    
    # 自变量
    X = np.c_[dummy,market_cap_log]
    # 因变量
    y = factor_se.ix[stock_list]

    # 拟合
    model = sm.OLS(y,X)
    results = model.fit()
    
    # 拟合结果
    y_fitted = results.fittedvalues
    
    neutralize_factor_se = factor_se - y_fitted
    
    return neutralize_factor_se


# In[17]:


def pretreat_factor(factor_df, neu=True):
    """
    因子处理函数
    输入：
        factor_df：DataFrame，index为日期，columns为股票代码，value为因子值
        neu：Bool，是否进行行业+市值中性化，若为True，则进行去极值->中性化->标准化；若为否，则进行去极值->标准化
    返回：
        factor_df：DataFrame，处理之后的因子
    """
    pretreat_data = factor_df.copy(deep=True)
    for dt in pretreat_data.index:
        
        market_cap_se = mkt.loc[dt].dropna()
        stock_list = market_cap_se.index.tolist()
        
        concept_se = indu.loc[dt].loc[stock_list]
        factor_dt = pretreat_data.loc[dt].loc[stock_list].dropna()
        
        if neu:
            pretreat_data.ix[dt] = standardize(neutralize(winsorize(factor_dt),market_cap_se,concept_se))
        else:
            pretreat_data.ix[dt] = standardize(winsorize(factor_dt))
            
    return pretreat_data


# ### 行业过滤

# In[18]:


def filter_by_industry(factor, indu):
    factor_data = factor.copy()
    for date in factor_data.index.tolist():
        # 找到金融类(银行，非银金融)股票，便于后面进行剔除
        finance = indu.loc[date, :]
        finance = finance[finance.isin(['801780', '801790'])].index
        factor_data.loc[date, finance] = np.nan
        
    return factor_data


# In[19]:


def keep_by_industry(factor, indu, indu_code):
    factor_data = factor.copy()
    for date in factor_data.index.tolist():
        keep = indu.loc[date, :]
        keep = keep[keep.isin([indu_code])].index
        factor_data.loc[date, :] = factor_data.loc[date, keep]
        
    return factor_data


# ## 2.3 结果展示

# ### 2.3.1 因子值多空组合

# #### 计算分组回报

# In[20]:


def get_group_ret(factor, month_ret, n_quantile=10):
    """
    计算分组超额收益：组合构建方式为等权，基准也为等权.
    注意：month_ret和factor应该错开一期，也就是说，month_ret要比factor晚一期
    输入：
        factor:DataFrame，index为日期，columns为股票代码，value为因子值
        month_ret:DataFrame，index为日期，columns为股票代码，value为收益率，month_ret的日期频率应和factor保持一致
        n_quantile:int，分组数量
    返回：
        DataFrame：列为分组序号，index为日期，值为每个调仓周期的组合收益率
    """
    # 统计分位数
    cols_mean = [i+1 for i in range(n_quantile)]
    cols = cols_mean
    

    excess_returns_means = pd.DataFrame(index=month_ret.index[:len(factor+1)], columns=cols)

    # 计算因子分组的超额收益平均值
    for t, dt in enumerate(excess_returns_means.index):
        qt_mean_results = []

        # ILLIQ去掉nan
        tmp_factor = factor.loc[dt].dropna()
        tmp_return = month_ret.loc[dt].dropna()
        tmp_return = tmp_return.loc[tmp_factor.index]
        tmp_return_mean = tmp_return.mean()

        pct_quantiles = 1.0 / n_quantile
        for i in range(n_quantile):
            down = tmp_factor.quantile(pct_quantiles*i)
            up = tmp_factor.quantile(pct_quantiles*(i + 1))
            i_quantile_index = tmp_factor[(tmp_factor <= up) & (tmp_factor >= down)].index
            mean_tmp = tmp_return[i_quantile_index].mean() #- tmp_return_mean
            qt_mean_results.append(mean_tmp)
        excess_returns_means.ix[t] = qt_mean_results
    return excess_returns_means


# #### 按行业计算分组回报

# In[21]:


def get_group_indu_ret(factor, month_ret,indu, induName, n_quantile=5):
    # 统计分位数
    cols_mean = [i+1 for i in range(n_quantile)]
    cols = cols_mean
    

    excess_returns_means = pd.DataFrame(index=month_ret.index[:len(factor+1)], columns=cols)

    # 计算因子分组的超额收益平均值
    for t, dt in enumerate(excess_returns_means.index):
        qt_mean_results = []
        
        tmp_indu = indu.loc[dt]
        stocklist = tmp_indu[tmp_indu==induName].index.tolist()
        
        tmp_factor = factor.loc[dt].dropna()
        
        stocklist = list(set(tmp_factor.index.tolist()) & set(stocklist))
        #print(len(stocklist))
        # ILLIQ去掉nan
        tmp_factor = tmp_factor.loc[stocklist]
        tmp_return = month_ret.loc[dt]
        tmp_return = tmp_return.loc[stocklist].dropna()
        
        tmp_return_mean = tmp_return.mean()

        pct_quantiles = 1.0 / n_quantile
        for i in range(n_quantile):
            down = tmp_factor.quantile(pct_quantiles*i)
            up = tmp_factor.quantile(pct_quantiles*(i + 1))
            i_quantile_index = tmp_factor[(tmp_factor <= up) & (tmp_factor >= down)].index
            mean_tmp = tmp_return[i_quantile_index].mean() #- tmp_return_mean
            qt_mean_results.append(mean_tmp)
        excess_returns_means.ix[t] = qt_mean_results
    return excess_returns_means


# #### 多空收益计算

# In[22]:


# 多空收益计算
def get_long_short_return(group_return, direction=-1):
    
    month_return = (group_return.iloc[:, np.sign(direction-1)] - group_return.iloc[:, -np.sign(direction+1)]).fillna(0)
    long_short_return = (month_return.values+1).cumprod()
    
    return pd.Series(long_short_return,index=month_return.index)


# #### 多空组合收益曲线（单曲线）

# In[23]:


def long_short_return_plot(group_return,stock_index, direction=1):
    """
    分组收益绘图
    group_return：分组收益，columns为分组序号，index为日期，值为每个调仓周期的组合收益率。可由函数get_group_ret产生
    """
    fig = plt.figure(figsize=(16, 16))
    ax1 = fig.add_subplot(212)
    
    month_return = (group_return.iloc[:, np.sign(direction-1)] - group_return.iloc[:, -np.sign(direction+1)]).fillna(0)
    
    ax1.bar(pd.to_datetime(month_return.index), month_return.values)
    ax1.plot(pd.to_datetime(month_return.index), (month_return.values+1).cumprod(), color='r')
    ax1.set_title(u"因子（扣除金融）多空组合累积收益的表现【{0}】".format(stock_index), fontsize=16,fontproperties=font)
    
    return fig


# #### 多空组合收益曲线（多曲线）

# In[24]:


def returns_plot(group_return,title):
    
    fig = plt.figure(figsize=(16, 16))
    
    ax1 = fig.add_subplot(212)
    
    # 颜色设置
    colormap=plt.cm.tab20b
    ax1.set_prop_cycle(color = [colormap(i) for i in np.linspace(0,0.9,len(group_return.columns))])
    
    ax1.plot(pd.to_datetime(group_return.index), group_return)
    ax1.set_title(title, fontsize=16,fontproperties=font)
    
    cols = group_return.columns.tolist()
    
    font1 = FontProperties(fname=r"simsun.ttc", size=10) 
    ax1.legend(cols,prop=font,loc='upper left',ncol = 4)
    
    
    return fig


# ### 2.3.2 各分位收益

# In[25]:


def group_mean_plot(group_return,stock_index, direction=1):
    """
    分组收益绘图
    group_return：分组收益，columns为分组序号，index为日期，值为每个调仓周期的组合收益率。可由函数get_group_ret产生
    """
    fig = plt.figure(figsize=(16, 16))
    ax1 = fig.add_subplot(212)
    
    month_return = (group_return.iloc[:, np.sign(direction-1)] - group_return.iloc[:, -np.sign(direction+1)]).fillna(0)
    
    excess_returns_means_dist = group_return.mean()
    excess_dist_plus = excess_returns_means_dist[excess_returns_means_dist>0]
    excess_dist_minus = excess_returns_means_dist[excess_returns_means_dist<0]
    lns2 = ax1.bar(excess_dist_plus.index, excess_dist_plus.values, align='center', color='r', width=0.35)
    lns3 = ax1.bar(excess_dist_minus.index, excess_dist_minus.values, align='center', color='g', width=0.35)

    ax1.set_xlim(left=0.5, right=len(excess_returns_means_dist)+0.5)
    ax1.set_xticks(excess_returns_means_dist.index)
    ax1.set_title(u"因子分组超额收益【{0}】".format(stock_index), fontsize=16,fontproperties=font)
    ax1.grid(True)
    
    return fig


# ### 2.3.3 各分位累计收益

# In[26]:


def cumprod_return_plot(group_return,stock_index):
    
    fig = plt.figure(figsize=(16, 16))
    ax1 = fig.add_subplot(212)
    
    cumprod_return = (group_return+1).cumprod()
    
    ax1.plot(pd.to_datetime(cumprod_return.index), cumprod_return)
    ax1.set_title(u"因子（扣除金融）累积收益表现【{0}】".format(stock_index), fontsize=16,fontproperties=font)
    
    cols = group_return.columns.tolist()
    legends = [ u"{}分位累积收益".format(col) for col in cols]
    ax1.legend(legends,prop=font)
    return fig

#fig = cumprod_return_plot(result_returns,"A")


# ### 2.3.4 信息系数IC

# #### 计算信息系数IC

# In[37]:


def get_rank_ic(factor, forward_return):
    """
    计算因子的信息系数
    输入：
        factor:DataFrame，index为日期，columns为股票代码，value为因子值
        forward_return:DataFrame，index为日期，columns为股票代码，value为下一期的股票收益率
    返回：
        DataFrame:index为日期，columns为IC，IC t检验的pvalue
    注意：factor与forward_return的index及columns应保持一致
    """
    common_index = factor.index.intersection(forward_return.index)
    ic_data = pd.DataFrame(index=common_index, columns=['IC','pValue'])

    # 计算相关系数
    for dt in ic_data.index:
        tmp_factor = factor.ix[dt]
        tmp_ret = forward_return.ix[dt]
        cor = pd.DataFrame(tmp_factor)
        ret = pd.DataFrame(tmp_ret)
        cor.columns = ['corr']
        ret.columns = ['ret']
        cor['ret'] = ret['ret']
        cor = cor[~pd.isnull(cor['corr'])][~pd.isnull(cor['ret'])]
        if len(cor) < 5:
            continue

        ic, p_value = st.spearmanr(cor['corr'], cor['ret'])   # 计算秩相关系数RankIC
        ic_data['IC'][dt] = ic
        ic_data['pValue'][dt] = p_value
    return ic_data


# #### IC曲线绘图

# In[27]:


def ic_line_plot(ic,interval,text):
    fig = plt.figure(figsize=(16, 16))
    ax1 = fig.add_subplot(212)
    
    
    ax1.plot(pd.to_datetime(ic.index), (ic.values), color='g')
    ax1.set(ylabel='IC', xlabel="")
    ax1.axhline(0.0, linestyle='-', color='black', lw=2, alpha=0.8)
    ax1.set_title(u"{}日因子IC【{}】".format(interval,text), fontsize=16,fontproperties=font)
    
    ymin, ymax = (-0.4, 0.4)
    curr_ymin, curr_ymax = ax1.get_ylim()
    ymin = curr_ymin if ymin is None else min(ymin, curr_ymin)
    ymax = curr_ymax if ymax is None else max(ymax, curr_ymax)
    ax1.set_ylim([ymin, ymax])
    
    return fig


# #### IC直方图绘图

# In[28]:


def ic_hist_plot(ic,interval,text):
    fig = plt.figure(figsize=(8, 16))
    ax1 = fig.add_subplot(212)
    
    sns.distplot(ic.replace(np.nan, 0.), norm_hist=True, ax=ax1)
    ax1.axvline(ic.mean(), color='w', linestyle='dashed', linewidth=2)
    ax1.set_title(u"{}日IC分布直方图【{}】".format(interval,text), fontsize=16,fontproperties=font)
    
    ax1.set_xlim([-1, 1])
    
    return fig


# #### IC正态分布qq图

# In[29]:


from statsmodels.api import qqplot
from scipy import stats
def ic_qq_plot(ic,interval,text,theoretical_dist=stats.norm):
    fig = plt.figure(figsize=(8, 16))
    ax1 = fig.add_subplot(212)
    
    qqplot(
            ic.replace(np.nan, 0.).values,
            theoretical_dist,
            fit=True,
            line='45',
            ax=ax1
        )
    ax1.axvline(ic.mean(), color='w', linestyle='dashed', linewidth=2)
    ax1.set_title(u"{}日IC正态分布qq图【{}】".format(interval,text), fontsize=16,fontproperties=font)
    
    return fig


# #### 行业信息系数绘图

# In[30]:


def get_indu_rank_ic(factor, forward_return, indu, induName):
    """
    计算因子的信息系数
    输入：
        factor:DataFrame，index为日期，columns为股票代码，value为因子值
        forward_return:DataFrame，index为日期，columns为股票代码，value为下一期的股票收益率
    返回：
        DataFrame:index为日期，columns为IC，IC t检验的pvalue
    注意：factor与forward_return的index及columns应保持一致
    """
    common_index = factor.index.intersection(forward_return.index)
    ic_data = pd.DataFrame(index=common_index, columns=['IC','pValue'])

    # 计算相关系数
    for dt in ic_data.index:
        tmp_indu = indu.loc[dt]
        stocklist = tmp_indu[tmp_indu==induName].index.tolist()
        tmp_factor = factor.loc[dt].dropna()
        stocklist = list(set(tmp_factor.index.tolist()) & set(stocklist))
        
        tmp_factor = factor.ix[dt].ix[stocklist]
        tmp_ret = forward_return.ix[dt].ix[stocklist]
        
        
        cor = pd.DataFrame(tmp_factor)
        ret = pd.DataFrame(tmp_ret)
        cor.columns = ['corr']
        ret.columns = ['ret']
        cor['ret'] = ret['ret']
        cor = cor[~pd.isnull(cor['corr'])][~pd.isnull(cor['ret'])]
        if len(cor) < 5:
            continue

        ic, p_value = st.spearmanr(cor['corr'], cor['ret'])   # 计算秩相关系数RankIC
        ic_data['IC'][dt] = ic
        ic_data['pValue'][dt] = p_value
    return ic_data


# In[31]:


def ic_indu_plot(ic_se):
    """
    分组收益绘图
    group_return：分组收益，columns为分组序号，index为日期，值为每个调仓周期的组合收益率。可由函数get_group_ret产生
    """
    fig = plt.figure(figsize=(16, 16))
    ax1 = fig.add_subplot(212)
    
    lns2 = ax1.bar(ic_se.index, ic_se.values, align='center', color='blue', width=0.35)

    ax1.set_xlim(left=0.5, right=len(ic_se)+0.5)
    ax1.set_xticklabels(ic_se.index,rotation = 90,fontproperties=font)
    ax1.set_title(u"因子行业IC", fontsize=16,fontproperties=font)
    ax1.grid(True)
    
    return fig


# ### 2.3.5 换手率

# #### 计算分组换手率

# In[32]:


def get_group_turnover(factor, n_quantile=10):
    """
    计算分组超额收益：组合构建方式为等权，基准也为等权.
    注意：month_ret和factor应该错开一期，也就是说，month_ret要比factor晚一期
    输入：
        factor:DataFrame，index为日期，columns为股票代码，value为因子值
        month_ret:DataFrame，index为日期，columns为股票代码，value为收益率，month_ret的日期频率应和factor保持一致
        n_quantile:int，分组数量
    返回：
        DataFrame：列为分组序号，index为日期，值为每个调仓周期的组合收益率
    """
    # 统计分位数
    cols_mean = [i+1 for i in range(n_quantile)]
    cols = cols_mean
    
    quantile_factor = factor.copy()

    # 计算因子分组的超额收益平均值
    for t, dt in enumerate(quantile_factor.index[:]):

        # ILLIQ去掉nan
        tmp_factor = factor.loc[dt].dropna()

        pct_quantiles = 1.0 / n_quantile
        for i in range(n_quantile):
            down = tmp_factor.quantile(pct_quantiles*i)
            up = tmp_factor.quantile(pct_quantiles*(i + 1))
            i_quantile_index = tmp_factor[(tmp_factor <= up) & (tmp_factor >= down)].index
            
            quantile_factor.loc[dt].loc[i_quantile_index] = int(i)

    quantile_turnover = pd.DataFrame(columns=cols)
    for i in range(n_quantile):
        quant_names = quantile_factor[quantile_factor == i]
        # 分位持仓数量
        hold_num_se = quant_names.apply(lambda x:(len(x.dropna())),axis=1)
        # 分位不变持仓数量
        not_change_num_se = (quant_names - quant_names.shift(1)).apply(lambda x: (len(x.dropna())),axis=1)
        # 分位换手率
        turnover_ratio = 1 - not_change_num_se / hold_num_se
        quantile_turnover[i+1] = turnover_ratio
        
    return quantile_turnover


# #### 分组换手率绘图

# In[33]:


def turnover_ratio_plot(quantile_turnover,interval,text):
    fig = plt.figure(figsize=(16, 16))
    ax1 = fig.add_subplot(212)
    
    cols = quantile_turnover.columns.tolist()
    
    ax1.plot(pd.to_datetime(quantile_turnover.index), (quantile_turnover[cols[0]].values), color='g')
    ax1.plot(pd.to_datetime(quantile_turnover.index), (quantile_turnover[cols[-1]].values), color='r')
    ax1.set_title(u"{}日因子换手率【{}】".format(interval,text), fontsize=16,fontproperties=font)
    
    ax1.legend([u"{}分位换手率".format(cols[0]),u"{}分位换手率".format(cols[-1])],prop=font)
    return fig


# ### 2.3.6 因子自相关绘图

# In[34]:


def factor_corr_plot(corr_se,interval,text):
    fig = plt.figure(figsize=(16, 16))
    ax1 = fig.add_subplot(212)
    
    ax1.plot(pd.to_datetime(corr_se.index), (corr_se.values), color='b')
    ax1.set(ylabel='IC', xlabel="")
    ax1.axhline(0.0, linestyle='-', color='black', lw=2, alpha=0.8)
    ax1.set_title(u"{}日因子自相关【{}】".format(interval,text), fontsize=16,fontproperties=font)
    
    
    return fig


# ### 收益表计算

# In[35]:


def get_easy_factor_report(factor, month_return, direction):
    """
    获得简单的因子分析报告，注意后面的分析会剔除金融行业。
    在输入的month_return中，索引应该和factor保持一致，
    输入：
        factor：DataFrame，index为日期，columns为股票代码，value为因子值
        month_return：DataFrame，index为日期，columns为股票代码，value为股票收益率。month_return
    返回：
        DataFrame：记录中性化前因子在不同域的IC，IC_IR，pValue，以及中性化后因子在不同域的IC，IC_IR，以及不同域的多空表现
    """
    columns = list(filter(lambda x:x not in finance,factor.columns))
    factor_hs300 = get_universe_factor(factor, univ=univ_hs300).loc[:, columns]
    factor_zz500 = get_universe_factor(factor, univ=univ_zz500).loc[:, columns]

    factor_hs300_neu = pretreat_factor(factor_hs300)
    factor_zz500_neu = pretreat_factor(factor_zz500)
    factor_a_neu = pretreat_factor(factor)

    # 中性化前因子分析
    rank_ic_hs300 = get_rank_ic(factor_hs300, month_return)
    rank_ic_zz500 = get_rank_ic(factor_zz500, month_return)
    rank_ic_a = get_rank_ic(factor, month_return)

    rank_ic_hs300_mean = rank_ic_hs300['IC'].mean()
    rank_ic_zz500_mean = rank_ic_zz500['IC'].mean()
    rank_ic_a_mean = rank_ic_a['IC'].mean()

    rank_ic_hs300_pvalue = ttest_ind(rank_ic_hs300['IC'].dropna().tolist(), [0] * len(rank_ic_hs300.dropna()))[1]
    rank_ic_zz500_pvalue = ttest_ind(rank_ic_zz500['IC'].dropna().tolist(), [0] * len(rank_ic_zz500.dropna()))[1]
    rank_ic_a_pvalue = ttest_ind(rank_ic_a['IC'].dropna().tolist(), [0] * len(rank_ic_a.dropna()))[1]

    rank_ic_ir_hs300 = rank_ic_hs300['IC'].mean() / rank_ic_hs300['IC'].std()
    rank_ic_ir_zz500 = rank_ic_zz500['IC'].mean() / rank_ic_zz500['IC'].std()
    rank_ic_ir_a = rank_ic_a['IC'].mean() / rank_ic_a['IC'].std()

    # 中性化后因子分析
    rank_ic_neu_hs300 = get_rank_ic(factor_hs300_neu, month_return)
    rank_ic_neu_zz500 = get_rank_ic(factor_zz500_neu, month_return)
    rank_ic_neu_a = get_rank_ic(factor_a_neu, month_return)

    rank_ic_hs300_neu_pvalue = ttest_ind(rank_ic_neu_hs300['IC'].dropna().tolist(), [0] * len(rank_ic_neu_hs300['IC'].dropna()))[1]
    rank_ic_zz500_neu_pvalue = ttest_ind(rank_ic_neu_zz500['IC'].dropna().tolist(), [0] * len(rank_ic_neu_zz500['IC'].dropna()))[1]
    rank_ic_a_neu_pvalue = ttest_ind(rank_ic_neu_a['IC'].dropna().tolist(), [0] * len(rank_ic_neu_a['IC'].dropna()))[1]

    rank_ic_neu_hs300_mean = rank_ic_neu_hs300['IC'].mean()
    rank_ic_neu_zz500_mean = rank_ic_neu_zz500['IC'].mean()
    rank_ic_neu_a_mean = rank_ic_neu_a['IC'].mean()

    rank_ic_ir_neu_hs300 = rank_ic_neu_hs300['IC'].mean() / rank_ic_neu_hs300['IC'].std()
    rank_ic_ir_neu_zz500 = rank_ic_neu_zz500['IC'].mean() / rank_ic_neu_zz500['IC'].std()
    rank_ic_ir_neu_a = rank_ic_neu_a['IC'].mean() / rank_ic_neu_a['IC'].std()

    hs300_excess_returns = get_group_ret(factor_hs300_neu, month_return, n_quantile=10)
    zz500_excess_returns = get_group_ret(factor_zz500_neu, month_return, n_quantile=10)
    a_excess_returns = get_group_ret(factor_a_neu, month_return, n_quantile=10)
    
    plot_fig(hs300_excess_returns,"hs300","1")
    plot_fig(zz500_excess_returns,"zz500","2")
    plot_fig(a_excess_returns,"A","3")
    

    hs300_long_short_ret = (hs300_excess_returns.iloc[:, np.sign(direction-1)] - 
                            hs300_excess_returns.iloc[:, -np.sign(direction+1)]).fillna(0)
    zz500_long_short_ret = (zz500_excess_returns.iloc[:, np.sign(direction-1)] - zz500_excess_returns.iloc[:, -np.sign(direction+1)]).fillna(0)
    a_long_short_ret = (a_excess_returns.iloc[:, np.sign(direction-1)] - a_excess_returns.iloc[:, -np.sign(direction+1)]).fillna(0)

    hs300_long_short_month_ret = hs300_long_short_ret.mean()
    zz500_long_short_month_ret = zz500_long_short_ret.mean()
    a_long_short_month_ret = a_long_short_ret.mean()

    hs300_long_short_win_ratio = float(len(hs300_long_short_ret[hs300_long_short_ret > 0])) / len(hs300_long_short_ret)
    zz500_long_short_win_ratio = float(len(zz500_long_short_ret[zz500_long_short_ret > 0])) / len(zz500_long_short_ret)
    a_long_short_win_ratio = float(len(a_long_short_ret[a_long_short_ret > 0])) / len(a_long_short_ret)

    hs300_long_short_sharp_ratio = hs300_long_short_ret.mean() / hs300_long_short_ret.std()
    zz500_long_short_sharp_ratio = zz500_long_short_ret.mean() / zz500_long_short_ret.std()
    a_long_short_sharp_ratio = a_long_short_ret.mean() / a_long_short_ret.std()

    # 最大回撤
    hs300_long_short_max_drawdown = max([1 - v/max(1, max((hs300_long_short_ret+1).cumprod()[:i+1])) for i,v in enumerate((hs300_long_short_ret+1).cumprod())])
    zz500_long_short_max_drawdown = max([1 - v/max(1, max((zz500_long_short_ret+1).cumprod()[:i+1])) for i,v in enumerate((zz500_long_short_ret+1).cumprod())])
    a_long_short_max_drawdown = max([1 - v/max(1, max((a_long_short_ret+1).cumprod()[:i+1])) for i,v in enumerate((a_long_short_ret+1).cumprod())])

    # 结果汇总
    report = pd.DataFrame(index=['沪深300', '中证500', '全A'], 
                          columns=[['原始因子', '原始因子', '原始因子', '行业和市值中性化后因子', '行业和市值中性化后因子','行业和市值中性化后因子',
                                    '行业和市值中性化后因子','行业和市值中性化后因子','行业和市值中性化后因子', '行业和市值中性化后因子'], 
                                   ['IC', 'IC_IR', 'pvalue', 'IC', 'IC_IR', 'pvalue', '多空组合月度收益', '胜率', '最大回撤', '夏普比率']])
    #report = pd.DataFrame(index=['沪深300', '中证500', '全A'], 
    #                      columns=['raw_IC', 'raw_IC_IR', 'rawpvalue', 'neu_IC', 'neu_IC_IR', 'neu_pvalue', 'neu_多空组合月度收益', 'neu_胜率', 'neu_最大回撤', 'neu_夏普比率'])
    
    report.iloc[:, 0] = [rank_ic_hs300_mean, rank_ic_zz500_mean, rank_ic_a_mean]
    report.iloc[:, 1] = [rank_ic_ir_hs300, rank_ic_ir_zz500, rank_ic_ir_a]
    report.iloc[:, 2] = [rank_ic_hs300_pvalue, rank_ic_zz500_pvalue, rank_ic_a_pvalue]
    report.iloc[:, 3] = [rank_ic_neu_hs300_mean, rank_ic_neu_zz500_mean, rank_ic_neu_a_mean]
    report.iloc[:, 4] = [rank_ic_ir_neu_hs300, rank_ic_ir_neu_zz500, rank_ic_ir_neu_a]
    report.iloc[:, 5] = [rank_ic_hs300_neu_pvalue, rank_ic_zz500_neu_pvalue, rank_ic_a_neu_pvalue]
    report.iloc[:, 6] = [hs300_long_short_month_ret, zz500_long_short_month_ret, a_long_short_month_ret]
    report.iloc[:, 7] = [hs300_long_short_win_ratio, zz500_long_short_win_ratio, a_long_short_win_ratio]
    report.iloc[:, 8] = [hs300_long_short_max_drawdown, zz500_long_short_max_drawdown, a_long_short_max_drawdown]
    report.iloc[:, 9] = [hs300_long_short_sharp_ratio, zz500_long_short_sharp_ratio, a_long_short_sharp_ratio]
    return report


# ### 分组收益绘图

# In[36]:


def group_mean_report_plot(group_return,stock_index, direction=1):
    """
    分组收益绘图
    group_return：分组收益，columns为分组序号，index为日期，值为每个调仓周期的组合收益率。可由函数get_group_ret产生
    """
    #fig = plt.figure(figsize=(12, 8))
    fig = plt.figure(figsize=(12, 8))
    ax1 = fig.add_subplot(212)
    ax2 = ax1.twinx()
    ax3 = fig.add_subplot(211)
    ax2.grid(False)
    
    month_return = (group_return.iloc[:, np.sign(direction-1)] - group_return.iloc[:, -np.sign(direction+1)]).fillna(0)
    
    ax1.bar(pd.to_datetime(month_return.index), month_return.values)
    ax2.plot(pd.to_datetime(month_return.index), (month_return.values+1).cumprod(), color='r')
    ax1.set_title(u"因子在中证全指（扣除金融）的表现【{0}】".format(stock_index), fontsize=16,fontproperties=font)
    
    excess_returns_means_dist = group_return.mean()
    excess_dist_plus = excess_returns_means_dist[excess_returns_means_dist>0]
    excess_dist_minus = excess_returns_means_dist[excess_returns_means_dist<0]
    lns2 = ax3.bar(excess_dist_plus.index, excess_dist_plus.values, align='center', color='r', width=0.35)
    lns3 = ax3.bar(excess_dist_minus.index, excess_dist_minus.values, align='center', color='g', width=0.35)

    ax3.set_xlim(left=0.5, right=len(excess_returns_means_dist)+0.5)
    ax3.set_xticks(excess_returns_means_dist.index)
    ax3.set_title(u"因子分组超额收益【{0}】".format(stock_index), fontsize=16,fontproperties=font)
    ax3.grid(True)
    
    return fig


# # 3 数据的准备
# ---
# 这部分主要获得后文分析所需要的一些数据，包括因子数据及股票的行情数据。
# 
# 注意：除了价格数据读取当日之外，其他数据均为上一个交易日的数据：股票池、行业、市值、因子

# ## 价格数据获取与保存

# In[38]:


'''
# 月度收益
print ('个股行情数据开始计算...')

pool = ThreadPool(processes=16)
frame_list = pool.map(getPriceData, trade_date_list)
pool.close()
pool.join()

price = pd.concat(frame_list, axis=0)
#month_return = price.pct_change()
month_return = price.pct_change().shift(-1)

print ('个股行情数据计算完成')
print ('---------------------')
'''


# ## 股票池获取与保存

# In[39]:


'''
print ('开始生成前文所定义的股票池...')
univ, univ_zz500, univ_hs300 = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

for date in pre_date_list:
    current_universe = pd.Series(get_All_trade_tickers(date)).to_frame(name='code')
    current_universe.index = [date] * len(current_universe)
    univ = univ.append(current_universe)
    
    current_hs300_universe = pd.Series(get_idx_cons('000300.XSHG', date)).to_frame(name='code')
    current_hs300_universe.index = [date] * len(current_hs300_universe)
    univ_hs300 = univ_hs300.append(current_hs300_universe)
    
    current_zz500_universe = pd.Series(get_idx_cons('000905.XSHG', date)).to_frame(name='code')
    current_zz500_universe.index = [date] * len(current_zz500_universe)
    univ_zz500 = univ_zz500.append(current_zz500_universe)
print ('股票池生成结束')
print ('--------------------'    )
'''


# In[40]:


'''from six import BytesIO
import pickle

# 写入 
filename = "2_MyFactorAnalyze/univ.pkl"
# 文件写入
#使用pickle模块从文件中重构python对象
content = pickle.dumps(univ) # 该方法返回字符串
write_file(filename, content, append=False)


# 写入
filename = "2_MyFactorAnalyze/univ_zz500.pkl"
# 文件写入
#使用pickle模块从文件中重构python对象
content = pickle.dumps(univ_zz500) # 该方法返回字符串
write_file(filename, content, append=False)

# 写入
filename = "2_MyFactorAnalyze/univ_hs300.pkl"
# 文件写入
#使用pickle模块从文件中重构python对象
content = pickle.dumps(univ_hs300) # 该方法返回字符串
write_file(filename, content, append=False)
'''


# In[41]:


'''
# 写入
filename = "2_MyFactorAnalyze/month_return.pkl"
# 文件写入
#使用pickle模块从文件中重构python对象
content = pickle.dumps(month_return) # 该方法返回字符串
write_file(filename, content, append=False)

'''


# ## 行业数据获取与保存

# In[42]:


'''print ('开始计算行业数据...')
frame_list = []
for date in pre_date_list:
    temp_df = getStockIndustry(date)
    frame_list.append(temp_df)
indu = pd.concat(frame_list, axis=0)
print ('行业数据计算完成')
print ('--------------------')

'''


# In[43]:


'''
# 写入
filename = "2_MyFactorAnalyze/indu.pkl"
# 文件写入
#使用pickle模块从文件中重构python对象
content = pickle.dumps(indu) # 该方法返回字符串
write_file(filename, content, append=False)

'''


# ## 市值数据获取与保存

# In[44]:


'''
print ('开始计算市值数据...')
frame_list = []
for date in pre_date_list:
    temp_df = getStockMktValue(date)
    frame_list.append(temp_df)
mkt = pd.concat(frame_list, axis=0)
print ('市值数据计算完成')
print ('--------------------')

'''


# In[45]:


'''
# 写入
filename = "2_MyFactorAnalyze/mkt.pkl"
# 文件写入
#使用pickle模块从文件中重构python对象
content = pickle.dumps(mkt) # 该方法返回字符串
write_file(filename, content, append=False)

'''


# ## 因子数据获取

# In[46]:



print ('开始计算因子数据...')


frame_list = []
for date in pre_date_list:
    temp_df = get_factor_data(date, facName, index)
    frame_list.append(temp_df)
  
factor_csv = pd.concat(frame_list, axis=0)
factor_csv.reset_index(inplace=True, drop=True)
print ('因子数据计算完成')
print ('--------------------')


# ## 读取已计算数据
# ---
# 在回测区间一定的情况下，股票池、价格、行业、市值等数据固定，并且在之前已经计算保存，这里不再重复计算，以节省时间。
# 

# In[47]:


print ('读取数据...')

# 读取股票池数据
filename = "2_MyFactorAnalyze/univ.pkl"#_{0}.pkl".format(interval)
body = read_file(filename)
univ = pickle.load(BytesIO(body))

filename = "2_MyFactorAnalyze/univ_zz500.pkl"#_{0}.pkl".format(interval)
body = read_file(filename)
univ_zz500 = pickle.load(BytesIO(body))

filename = "2_MyFactorAnalyze/univ_hs300.pkl"#_{0}.pkl".format(interval)
body = read_file(filename)
univ_hs300 = pickle.load(BytesIO(body))

# 读取价格数据
filename = "2_MyFactorAnalyze/month_return.pkl"#_{0}.pkl".format(interval)
body = read_file(filename)
month_return = pickle.load(BytesIO(body))


# 读取行业数据
filename = "2_MyFactorAnalyze/indu.pkl"#_{0}.pkl".format(interval)
body = read_file(filename)
indu = pickle.load(BytesIO(body))


# 读取市值数据
filename = "2_MyFactorAnalyze/mkt.pkl"#_{0}.pkl".format(interval)
body = read_file(filename)
mkt = pickle.load(BytesIO(body))

print ('数据读取完成。')


# # 4 数据的处理

# ## 时间处理

# In[48]:


# 统一时间格式
month_return.index = dateTransform(month_return.index)

univ.index = dateTransform(univ.index)
univ_hs300.index = dateTransform(univ_hs300.index)
univ_zz500.index = dateTransform(univ_zz500.index)

indu.index = dateTransform(indu.index)
mkt.index = dateTransform(mkt.index)


# In[49]:


factor_csv.tradeDate = dateTransform(factor_csv.tradeDate)


# In[50]:


# 用于计算下一个交易日
date_df = pd.DataFrame(columns=['trade_date','pre_date'])
date_df['trade_date'] = dateTransform(trade_date_list)
date_df['pre_date'] = dateTransform(pre_date_list)
date_df = date_df.set_index('pre_date')


# In[51]:


# 上一个交易日的数据修改为当前交易日期
univ.index = list(map(lambda x: date_df.loc[x].iloc[0],univ.index))
univ_hs300.index = list(map(lambda x: date_df.loc[x].iloc[0],univ_hs300.index))
univ_zz500.index = list(map(lambda x: date_df.loc[x].iloc[0],univ_zz500.index))
indu.index = list(map(lambda x: date_df.loc[x].iloc[0],indu.index))
mkt.index = list(map(lambda x: date_df.loc[x].iloc[0],mkt.index))


# In[52]:


factor_csv.tradeDate = list(map(lambda x: date_df.loc[x].iloc[0],factor_csv.tradeDate))


# ## 因子处理
# ---
# 1.使用行业中位数进行填充
# 
# 2.去极值、中性化、标准化处理
# 
# 3.去除金融行业
# 
# 4.根据股票池筛选因子

# ### 原始因子数据

# In[53]:


# 原始因子数据
factor_data = factor_csv.pivot(index='tradeDate', columns='code', values=facName)


# In[54]:


factor_data.index = dateTransform(factor_data.index)


# In[55]:


factor_data.head()


# ### 行业中位数填充缺失值

# In[56]:


# 行业中位数填充
factor = replace_nan_indu(factor_data,indu)


# In[93]:


factor.head()


# ### 去极值、中性化、标准化

# In[58]:


factor_neu = pretreat_factor(factor)


# In[59]:


factor_neu.head()


# ### 行业过滤
# ---
# 金融行业因子均值明显高于其他行业，对于因子选股而言，容易出现偏差，因此过滤。

# #### 各个因子行业平均值

# In[60]:



# 各个因子在申万一级行业内的平均值
industry_name_sw1 = {'801740':'国防军工','801020':'采掘','801110':'家用电器','801160':'公用事业','801770':'通信','801010':'农林牧渔','801120':'食品饮料','801750':'计算机','801050':'有色金属','801890':'机械设备','801170':'交通运输','801710':'建筑材料','801040':'钢铁','801130':'纺织服装','801880':'汽车','801180':'房地产','801230':'综合','801760':'传媒','801200':'商业贸易','801780':'银行','801140':'轻工制造','801720':'建筑装饰','801080':'电子','801790':'非银金融','801030':'化工','801730':'电气设备','801210':'休闲服务','801150':'医药生物','other':"其他"}
indu_last = (indu.iloc[-1]).to_frame('indu')
fac_last = factor.iloc[-1, :].to_frame('all')
fac_indu_mean = pd.merge(fac_last, indu_last, how='inner', right_index=True, left_index=True).groupby('indu').mean()
indu_dist = pd.concat([fac_indu_mean], axis=1)

#indu_dist = indu_dist.dropna().iloc[:-1]

fig = plt.figure(figsize=(16, 8))
for i in range(indu_dist.shape[1]):
    k = 100 + indu_dist.shape[1] * 10 + i + 1
    ax = indu_dist.iloc[:, i].plot(kind='barh', ax=fig.add_subplot(k), color='r')
    ax.set_title(u"各个因子在申万一级行业内的平均值", fontsize=16,fontproperties=font)
    ax.set_xlabel(indu_dist.columns[i])
    ax.set_xticklabels(ax.get_xticks(), rotation=45)
    if i == 0:
        s = ax.set_yticklabels([industry_name_sw1[i] for i in indu_dist.index],fontproperties=font) #.decode('utf-8')
        s = ax.set_ylabel(u'行业', fontsize=14,fontproperties=font)
    else:
        ax.set_yticklabels([])
        ax.set_ylabel('')
    fig = plt.gcf()


# #### 过滤

# In[61]:


factor = filter_by_industry(factor, indu)   
factor_neu = filter_by_industry(factor_neu, indu)   


# In[62]:


factor.head()


# In[63]:


factor_neu.head()


# ### 当日股票池筛选因子
# ---
# 刚刚上市的新股，大概率连续涨停，统计时会显著影响结果，但实际情况下很难参与，这里要求上市时间不低于60天。

# #### 全A 

# In[64]:


# 根据当日市场股票
factor_a = get_universe_factor(factor,univ=univ)
factor_a_neu = get_universe_factor(factor_neu,univ=univ)


# #### 沪深300

# In[65]:


# 根据当日市场股票
factor_hs300 = get_universe_factor(factor,univ=univ_hs300)
factor_hs300_neu = get_universe_factor(factor_neu,univ=univ_hs300)


# #### 中证500

# In[66]:


# 根据当日市场股票
factor_zz500 = get_universe_factor(factor,univ=univ_zz500)
factor_zz500_neu = get_universe_factor(factor_neu,univ=univ_zz500)


# # 5 结果展示

# ## 5.1 因子值多空组合累积收益
# 
# ---
# 
# 做多因子值头部股票，做空因子值尾部股票，计算多空组合累积收益，该曲线走势，越向上越好。越没有下挫越好

# ### 5.1.1 股票指数

# In[67]:


factor_datas = [factor_a,factor_a_neu,factor_hs300,factor_hs300_neu,factor_zz500,factor_zz500_neu]
columns = ['全A','全A反向','全A中性化','全A中性化反向','沪深300','沪深300反向','沪深300中性化','沪深300中性化反向','中证500','中证500反向','中证500中性化','中证500中性化反向']


# In[68]:


data = []
for factor_data_tmp in factor_datas[:]:
    returns = get_group_ret(factor_data_tmp.iloc[:-1], month_return, n_quantile=10)
    long_short_return = get_long_short_return(returns)
    
    # 倒数处理
    factor_data_tmp_reciprocal = (1.0/factor_data_tmp).replace([-np.inf, np.inf], np.NaN) # 取倒数
    reciprocal_returns = get_group_ret(factor_data_tmp_reciprocal.iloc[:-1], month_return, n_quantile=10)
    reciprocal_long_short_return = get_long_short_return(reciprocal_returns)
    
    data.append(long_short_return)
    data.append(reciprocal_long_short_return)
all_returns = pd.DataFrame(data,index=columns[:]).T


# #### 全部多空收益结果

# In[69]:


fig = returns_plot(all_returns,title = "多空收益净值曲线")


# #### 筛选多空收益结果

# In[70]:


cols_3 = all_returns.iloc[-1].sort_values(ascending=False).index[:3].tolist()
fig = returns_plot(all_returns[cols_3],title = "多空收益净值曲线")


# #### 筛选结果因子

# In[71]:


values = all_returns.iloc[-1][:2].tolist()
if values[-1] > values[0]:
    result_factor = factor_a_neu
    text = "全A中性化"
    
else:
    result_factor = factor_a
    text = "全A因子"
    
print("筛选结果：{}".format(text))    


# ### 5.1.2 行业多收益绘图

# In[72]:


industry_name_sw1 = {'801740':'国防军工','801020':'采掘','801110':'家用电器','801160':'公用事业','801770':'通信','801010':'农林牧渔','801120':'食品饮料','801750':'计算机','801050':'有色金属','801890':'机械设备','801170':'交通运输','801710':'建筑材料','801040':'钢铁','801130':'纺织服装','801880':'汽车','801180':'房地产','801230':'综合','801760':'传媒','801200':'商业贸易','801780':'银行','801140':'轻工制造','801720':'建筑装饰','801080':'电子','801790':'非银金融','801030':'化工','801730':'电气设备','801210':'休闲服务','801150':'医药生物'}


# In[73]:


data = []
count = 1
for k,v in industry_name_sw1.items():
    if k == 'other':
        continue
    indu_return = get_group_indu_ret(result_factor, month_return,indu, k, n_quantile=10)
    long_short_return = get_long_short_return(indu_return)
    long_short_return.name = "{}({})".format(v,k)
    count +=1 
    data.append(long_short_return)
    if count > 2:
        pass
        #break
indu_returns = pd.DataFrame(data).T        


# #### 全部多空收益结果

# In[74]:


fig = returns_plot(indu_returns,title = "行业多空收益净值曲线")


# #### 筛选多空收益结果

# In[75]:


cols_4 = indu_returns.iloc[-1].sort_values(ascending=False).index[:4].tolist()
fig = returns_plot(indu_returns[cols_4],title = "行业多空收益净值曲线")


# #### 最优行业因子

# In[76]:


indu_text = indu_returns.iloc[-1].sort_values(ascending=False).index[0]
indu_code = indu_text.split('(')[-1].replace(')',"")
indu_result_factor = keep_by_industry(result_factor, indu, indu_code)


# ## 5.2 各分位收益
# 
# ---
# 
# 计算各分位数平均收益，可以明了地看到不同分位因子值的收益效果，最好是递增关系或者递减关系。

# ### 全A

# In[94]:


result_returns = get_group_ret(result_factor.iloc[:-1], month_return, n_quantile=10)
fig = group_mean_plot(result_returns,text,1) 


# ### 最优行业

# In[95]:


indu_result_returns = get_group_ret(indu_result_factor.iloc[:-1], month_return, n_quantile=10)
fig = group_mean_plot(indu_result_returns,indu_text,1) 


# ## 5.3 各分位累计收益曲线
# ---
# 通过计算各分位累计收益，可以查看各收益分层的分散度。
# 
# 各组曲线不相交，不缠绕，各组优劣关系始终保持1to10，或者10to1，说明因子持续有效。越分散越好，分层越明显越好。
# 
# 这里有一点需要注意：
# 
# 如果最高收益组与次高收益组差异很大，在样本外因子的选股能力可能会存在比较大的波动。由于因子性能变化，市场环境变化等因素，因子的实际表现，很容易在第一组和其他组之间变动。
# 
# 
# 

# ### 全A

# In[96]:


fig = cumprod_return_plot(result_returns,text)


# ### 最优行业

# In[97]:


fig = cumprod_return_plot(indu_result_returns,indu_text)


# ## 5.4 信息系数IC
# 
# ---
# 计算当期的因子值的排序值和下期的因子收益的排序值之间的相关系数，可以衡量因子值的大小多大程度上能预测未来的收益。
# 
# 一般来说IC的均值的绝对值大于3%，则认为因子比较有效。

# ### 5.4.1 IC曲线
# ---
# 通过描绘信息系数IC的曲线，可以探究因子是否有预测能力。如果持续大于0或者持续小于0，说明因子有效。
# 
# 

# #### 获取IC值

# In[98]:


rank_ic_a = get_rank_ic(result_factor, month_return)


# In[99]:


rank_ic_indu = get_rank_ic(indu_result_factor, month_return)


# #### 全A

# In[100]:


fig = ic_line_plot(rank_ic_a['IC'],interval,text)


# #### 最优行业

# In[101]:


fig = ic_line_plot(rank_ic_indu['IC'],interval,indu_text)


# ### 5.4.2 IC 直方图
# ---
# 大概是中间高两边低，符合正态分布即可。如果明显不符合正态分布，说明该统计结果不可靠。

# #### 全A

# In[102]:


fig = ic_hist_plot(rank_ic_a['IC'],interval,text)


# #### 最优行业

# In[103]:


fig = ic_hist_plot(rank_ic_indu['IC'],interval,indu_text)


# ### 5.4.3 IC QQ图
# ---
# 蓝点全部在红色对角线上，认为IC分布等同于正态分布。越偏离红色对角线，越说明偏离正态分布。

# #### 全A

# In[104]:


fig = ic_qq_plot(rank_ic_a['IC'],interval,text)


# #### 最优行业

# In[105]:


fig = ic_qq_plot(rank_ic_indu['IC'],interval,indu_text)


# ### 5.4.4 按行业分组信息比率IC
# 
# ---
# 行业维度展开IC，可以看到在不同行业的表现。因子在某些行业表现很好，在某些行业表现不好，可以和前面的多空累计收益相互印证，看看因子的表现是否符合预期。

# In[106]:


count = 1
ic_dict = {}
for k,v in industry_name_sw1.items():
    ic_data = get_indu_rank_ic(result_factor, month_return,indu, k)
    ic_mean = ic_data['IC'].mean()
    ic_dict[v] = ic_mean
    count +=1 
    if count > 1:
        pass
        #break


# In[107]:


def ic_indu_plot(ic_se):
    """
    分组收益绘图
    group_return：分组收益，columns为分组序号，index为日期，值为每个调仓周期的组合收益率。可由函数get_group_ret产生
    """
    fig = plt.figure(figsize=(16, 16))
    ax1 = fig.add_subplot(212)
    
    lns2 = ax1.bar(ic_se.index, ic_se.values, align='center', color='blue', width=0.35)

    ax1.set_xlim(left=0.5, right=len(ic_se)+0.5)
    ax1.set_xticklabels(ic_se.index,rotation = 90,fontproperties=font)
    ax1.set_title(u"因子行业IC", fontsize=16,fontproperties=font)
    ax1.grid(True)
    
    return fig


# In[108]:


ic_se = pd.Series(ic_dict).dropna()
fig = ic_indu_plot(ic_se)


# ## 5.5 换手情况
# ---
# 通过计算因子的自相关系数，可以了解到当期的因子值与往期因子值的相关程度。
# 
# 如果自相关系数比较高，意味着选股的结果具有持续性。
# 
# 如果自相关系数比较低，会导致频繁的换手。出于交易佣金和印花税的原因，容易导致价值损耗。
# 

# ### 5.5.1 因子自相关图
# 
# ---
# 自相关系数越大越好

# #### 全A

# In[112]:


corr_se = result_factor.corrwith(result_factor.shift(1),axis=1)
fig = factor_corr_plot(corr_se,interval,text)


# #### 最优行业

# In[113]:


indu_corr_se = result_factor.corrwith(indu_result_factor.shift(1),axis=1)
fig = factor_corr_plot(indu_corr_se,interval,indu_text)


# ### 5.5.2 最高最低分位换手率
# ---
# 换手率越低越好。
# 
# 
# 

# #### 全A

# In[109]:


quantile_turnover = get_group_turnover(result_factor, n_quantile=10)
# 除去首日开仓的换手率
fig = turnover_ratio_plot(quantile_turnover.iloc[1:],interval,text)


# #### 最优行业

# In[111]:


indu_quantile_turnover = get_group_turnover(indu_result_factor, n_quantile=10)
# 除去首日开仓的换手率
fig = turnover_ratio_plot(indu_quantile_turnover.iloc[1:],interval,indu_text)


# In[ ]:




