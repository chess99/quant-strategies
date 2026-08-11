#!/usr/bin/env python
# coding: utf-8

# In[34]:


from datetime import datetime, timedelta
import datetime

from jqdata import *
from jqfactor import *

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import seaborn as sns

import math
import statsmodels.api as sm
from statsmodels import regression
from scipy.optimize import minimize
from scipy import stats
import scipy.stats as st

import warnings  
warnings.filterwarnings('ignore') 

mpl.rcParams['font.sans-serif'] = ['SimHei']    
mpl.rcParams['axes.unicode_minus'] = False     
sns.set_style({'font.sans-serif':['simhei', 'Arial']})
pd.set_option('display.max_rows', 200)
pd.set_option('display.max_columns', 200)
pd.set_option('display.width', 200)
plt.style.use('ggplot')


# # 1.函数构造

# ## 1.1获取指定频率交易日数据

# In[35]:


#获取交易日列表，返回DatetimeIndex对象
def get_tradeday_list(start,end,frequency=None,count=None):
    if count != None:
        df = get_price('000001.XSHG',end_date=end,count=count)#有计数n，返回后n天
    else:
        df = get_price('000001.XSHG',start_date=start,end_date=end)#否则返回始末日期之间
    if frequency == None or frequency =='D':
        return df.index
    else:
        df['year-month'] = [str(i)[0:7] for i in df.index]#返回年月
        if frequency == 'M':
            return df.drop_duplicates('year-month').index#根据年月去重
        elif frequency == 'Q':
            df['month'] = [str(i)[5:7] for i in df.index]
            df = df[(df['month']=='01') | (df['month']=='04')                    | (df['month']=='07') | (df['month']=='10') ]#返回1、4、7、10月
            return df.drop_duplicates('year-month').index#去重
        elif frequency =='H-Y':
            df['month'] = [str(i)[5:7] for i in df.index]
            df = df[(df['month']=='01') | (df['month']=='06')]#返回1、6月
            return df.drop_duplicates('year-month').index#去重


# ## 1.2 筛选股票池

# In[36]:


#返回指定交易日下一个交易日
def ShiftTradingDay(date,shift):
    # 获取所有的交易日(从2005年开始),返回一个包含所有交易日的 list,元素值为 datetime.date 类型.
    tradingday = get_all_trade_days()
    # 得到date之后shift天那一天在列表中的行标号 返回一个数
    date = datetime.date(int(str(date)[:4]),int(str(date)[5:7]),int(str(date)[8:10]))
    shiftday_index = list(tradingday).index(date)+shift
    # 根据行号返回该日日期 为datetime.date类型
    return tradingday[shiftday_index] 

#进行新股、St股过滤，返回筛选后的股票
#！！！不能过滤停牌股票
def filter_stock(stockList,date,days=21*3,limit=0):
    #去除上市距beginDate不足3个月的股票
    def delect_stop(stocks,beginDate,n=days):
        stockList=[]
        beginDate = datetime.datetime.strptime(beginDate, "%Y-%m-%d")
        for stock in stocks:
            start_date=get_security_info(stock).start_date
            if start_date<(beginDate-datetime.timedelta(days=n)).date():
                stockList.append(stock)
        return stockList
    
    #剔除ST股
    st_data=get_extras('is_st',stockList, count = 1,end_date=date)
    stockList = [stock for stock in stockList if not st_data[stock][0]]
    
    # 判断当天是否全天停牌
    is_susp = get_price(stockList,end_date=date, count=1,fields='paused'                        ,panel=False).set_index('code')[['paused']]
    stockList = is_susp[is_susp==1].index.tolist()
    
    #新股及退市股票
    stockList=delect_stop(stockList,date)
    
    #剔除开盘涨跌停股票
    if limit == 1:
        #如果需要收盘涨跌停可以改字段即可
        df = get_price(stockList,end_date=date,                       fields=['open','high_limit','low_limit'],count=1).iloc[:,0,:]
        df['h_limit']=(df['open']==df['high_limit'])
        df['l_limit']=(df['open']==df['low_limit'])
        stockList = [df.index[i] for i in range(len(df)) if not                     (df.h_limit[i] or df.l_limit[i])] #过滤涨跌停股票
    return stockList


# ## 1.3 行业标记

# In[37]:


#为股票池添加行业标记,return df格式 ,为中性化函数的子函数   
def get_industry_exposure1(stock_list,date):
    stock_list = list(stock_list)
    df = pd.DataFrame(index=get_industries(name='sw_l1').index, columns=stock_list)
    s = get_industry(security=stock_list, date=date)
    ind_dict = {}#创建一个每个股票所在行业的字典（'sw_l1'标准）
    for idx,stock in enumerate(stock_list):
        #自从2019年后存在找不到'sw_l1'的股票情况
        if 'sw_l1' in s[stock].keys() :
            ind_dict[stock] = s[stock]['sw_l1']['industry_code']
        else:
            # 以相邻股票行业作为自己的行业
            ind_dict[stock] = ind_dict[stock_list[idx-1]]
    
    for stock in stock_list:
        df.loc[ind_dict[stock],stock] = 1

    return df.fillna(0)


# ## 1.4IC统计相关函数

# In[38]:


def dict_to_df(dct,index,name=None):
    df = pd.DataFrame(dct,index=index).T
    df.index = pd.to_datetime(df.index)
    if name:
        df.index.name = name
    return df

def evaluation(ic_df, beta_df, t_df):
    '''
    ic_df: df
    beta_df: df
    t_df: df
    return:
    '''
    eval_dict = {}
    # ----ic----
    ic_mean = []
    ic_002 = []
    ir = []
    # ---beta----
    beta_mean = []
    t_test = []
    p_value = []
    # ----t----
    t_mean = []
    t_2 = []

    for factor in ic_df.columns:
        # 计算ic均值
        mean_temp = np.around(ic_df[factor].mean(), 4)
        # ic绝对值大于0.02的比例
        ratio_002 = np.around(np.sum(ic_df[factor].abs() > 0.02)                              / len(ic_df.index) * 100, 2)
        # IR
        IR = np.around(mean_temp / ic_df[factor].std(), 4)

        # 添加进列表
        ic_mean.append(mean_temp)
        ic_002.append(str(ratio_002) + '%')
        ir.append(IR)
    print("ic表处理完毕!")
    
    for factor in beta_df.columns:
        # 因子收益率均值
        mean_temp = np.around(beta_df[factor].mean(), 4)
        # t检验
        t, p = np.around(st.ttest_1samp((beta_df[factor]), 0), 4)
        # 添加进列表
        beta_mean.append(mean_temp)
        t_test.append(t)
        p_value.append(p)
    print("beta表处理完毕!")
    
    for factor in t_df.columns:
        # t值绝对值的均值
        mean_temp = np.around(t_df[factor].abs().mean(), 4)
        # 大于2的占比
        ratio_2 = np.around(np.sum(t_df[factor].abs() > 2) / len(t_df.index) * 100, 2)

        # 添加列表
        t_mean.append(mean_temp)
        t_2.append(str(ratio_2) + '%')
    print("t值表处理完毕!")
    
    # 添加进字典
    eval_dict['IC均值'] = ic_mean
    eval_dict['|IC|>0.02'] = ic_002
    eval_dict['IR'] = ir
    eval_dict['因子收益率均值'] = beta_mean
    eval_dict['因子收益率t检验'] = t_test
    eval_dict['p值'] = p_value
    eval_dict['|t|均值'] = t_mean
    eval_dict['|t|大于2的占比'] = t_2
    
    # 字典转df
    eval_df = pd.DataFrame(eval_dict,index=t_df.columns)
    eval_df['score'] = eval_df.apply(score,axis=1)
    eval_df = eval_df.sort_values('score',ascending=False)#降序
    
    return eval_df

def score(series):
    """
    打分函数
    """
    score = 0
    if abs(series['IC均值'])>0.02:
        score +=1
    if abs(series['因子收益率t检验'])> 1.8:#存在问题
        score +=1
    if abs(series['IR'])>0.3:
        score +=1
    if series['|t|均值']>2:
        score +=1
    return score


# ## 1.5相关性画图函数

# In[39]:


def plot_heat(ic_df,eval_df):
    # 截取表现好的因子
    eval_df = eval_df[eval_df['score']>=2]
    ic_df = ic_df.loc[:,eval_df.index]
    corr = np.around(ic_df.corr('spearman'),2)
    fig,ax = plt.subplots(figsize=(20,10))
    sns.heatmap(corr.abs(),annot=True,cmap='RdPu',ax=ax)
    return corr


# # 2 数据获取

# ## 2.1初始设置

# In[40]:


#设置统计数据区间
index = '000985.XSHG' #设置股票池，和对比基准，这里是中证500
#stocks_list=list(get_all_securities(['stock']).index)

#设置统计起止日期
date_start = '2023-07-08'
date_end   = '2023-07-14'

#设置调仓频率
trade_freq = 'day' #month每个自然月；day每个交易日；输入任意数字如 5，则为5日调仓 

#获取调仓时间列表
if trade_freq == 'month':  
    #获取交易日列表，每月首个交易日
    date_list = get_tradeday_list(start=date_start,end=date_end,frequency='M',count=None) #自然月的第一天
elif trade_freq == 'day': 
    date_list = get_tradeday_list(start=date_start,end=date_end,count=None)#获取回测日期间的所有交易日
else:
    date_day_list = get_tradeday_list(start=date_start,end=date_end,count=None)#获取回测日期间的所有交易日
    date_list = [date_day_list[i] for i in range(len(date_day_list)) if i%int(trade_freq) == 0]


# In[41]:


date_list #每月首个交易日


# ## 2.2 获取风格因子

# In[42]:


#通过聚宽因子获取barra风险因子值进行记录
factor_name = ['size','beta','momentum','residual_volatility','non_linear_size',               'book_to_price_ratio','liquidity','earnings_yield',               'growth','leverage']
def get_barra_factor(stock_list,date): #返回df对象
    global factor_name
    factor_data = get_factor_values(securities=stock_list, factors = factor_name
            ,end_date=end_date,count=1)
    df = pd.DataFrame()
    for f in factor_name:
        temp_df = pd.DataFrame(factor_data[f]).T
        df = pd.concat([df,temp_df],axis=1)
    df.columns=factor_name
    return df

#进行因子值计算
factor_data_dict = {}

#循环时间列表获取原始因子数据组成dict
for end_date in date_list[:]:
    end_date=str(end_date)[:10]
    print('正在计算 {} 因子数据......'.format(end_date))
    stocks_list = get_index_stocks(index,date=end_date)
    #stocks_list=list(get_all_securities(['stock']).index)
    factor_data_dict[end_date] = get_barra_factor(stocks_list,end_date)
    
print('返回最后一个交易日因子矩阵')
factor_data_dict[end_date].head(5)


# ## 2.3 数据清洗

# In[43]:


#数据清洗、包括去极值、标准化、中性化等,并加入y值
factor_data_y_dict = {}
for date_1,date_2 in zip(date_list[:-1],date_list[1:]):
    d1 = ShiftTradingDay(date_1,1)   #往后推一天
    d2 = ShiftTradingDay(date_2,1)
    d3 = ShiftTradingDay(date_2,2)   #往后推两天
    print('开始整理 {} 数据...'.format(str(date_2)[:10]))
    factor_df = factor_data_dict[str(date_1)[:10]] #根据字典存储的日期格式不同进行不同设置
    pool = list(factor_df.index)
    pool = filter_stock(pool,str(d1)[:10],days=21*3) #进行新股、ST股票过滤
    
    #计算指数涨跌幅
    df_1 = get_price(index,end_date=d1,fields=['open'],count = 1)['open']
    #df_1 = get_price(stocks_list,end_date=d1,fields=['open'],count = 1)['open']
    df_2 = get_price(index,end_date=d2,fields=['open'],count = 1)['open']
    #df_2 = get_price(stocks_list,end_date=d2,fields=['open'],count = 1)['open']
    index_pct = df_2.values[0]/df_1.values[0] - 1#具体数值
    
    #计算各股票涨跌幅
    df_1 = get_price(pool,end_date=d1,fields=['open'],count = 1)['open']
    df_2 = get_price(pool,end_date=d2,fields=['open'],count = 1)['open']
    df_3 = pd.concat([df_1,df_2],axis=0).T #进行合并
    stock_pct = df_3.iloc[:,1]/df_3.iloc[:,0] - 1 #计算pct，series
    
    #对数据进行处理、标准化、去极值、中性化
    factor_df = winsorize_med(factor_df, scale=3, inclusive=True,                              inf2nan=True, axis=0) #中位数去极值处理
    factor_df = standardlize(factor_df, inf2nan=True, axis=0) #对每列做标准化处理
    factor_df = neutralize(factor_df, how=['sw_l1', 'market_cap'], date=date_1,                           axis=0,fillna='sw_l1')#中性化 fillna表示使用行业均值填充

    factor_df['pct_alpha'] =  stock_pct-index_pct#超额收益率
    factor_df['pct_'] =  stock_pct#收益率
    factor_data_y_dict[str(date_2)[:10]] = factor_df#返回一个字段为时期值为因子df的字典

print('返回最后一期的因子矩阵')
factor_data_y_dict[str(date_2)[:10]].head(500)


# # 3 模型回归

# ## 3.1以2020-01-02为例计算行业权重

# In[23]:


###示例，可跳过
df = factor_data_y_dict['2023-07-14']
#计算权重向量
#求w
#计算市值平方根占比
pool = df.index
get_size = get_fundamentals(query(valuation.code,valuation.market_cap)                            .filter(valuation.code.in_(pool)),date='2023-07-14')
get_size.index = get_size['code'].values
get_size['l_size'] = np.sqrt(get_size['market_cap'])
get_size['w'] = get_size['l_size']/sum(get_size['l_size'])
W = (get_size['w'].values).reshape(len(get_size),1)#股票权重（WLS用）
#get_size.head(3)
#计算行业市值权重占比
hy_df = get_industry_exposure1(pool,date='2023-07-14').T
hy_df['cons'] = [1]*len(hy_df)

df_c1 = pd.concat([hy_df,get_size],axis=1)
ind_name = get_industries(name='sw_l1').index
all_mkt = sum(df_c1['market_cap'].values)
ind_w = []
for ind in list(ind_name):
    df_temp = df_c1[df_c1[ind]==1]
    r_temp = sum(df_temp['market_cap'].values)/all_mkt#计算行业市值所占比例
    ind_w.append(r_temp)
ind_w
# 常见只有32个行业，总共有38个行业，有六个行业为0


# ## 3.2 以2017-05-02为例计算拉格朗日最优解--因子收益率

# In[24]:


###示例，可跳过
d = date_list[1]
d = str(d)[:10]
print('正在计算{}...'.format(d))
    #获取因子暴露
factor_df = factor_data_y_dict[d]
x = factor_df.iloc[:,:-2]
r = factor_df['pct_'].fillna(factor_df['pct_'].mean()).values
    # r = factor_df['pct_'].values
pool  = factor_df.index
    
    #计算市值平方根占比
get_size = get_fundamentals(query(valuation.code,valuation.market_cap).filter(valuation.code.in_(pool)),date=d)
get_size.index = get_size['code'].values
get_size['l_size'] = np.sqrt(get_size['market_cap'])
get_size['w'] = get_size['l_size']/sum(get_size['l_size'])
W = (get_size['w'].values).reshape(len(get_size),1)
    
    #计算行业市值权重占比
hy_df = get_industry_exposure1(pool,date=d).T
hy_df['cons'] = [1]*len(hy_df)#常数项

df_c1 = pd.concat([hy_df,get_size],axis=1)
ind_name = get_industries(name='sw_l1').index
df_c1['market_cap'].fillna(df_c1['market_cap'].mean())
all_mkt = df_c1['market_cap'].sum()
ind_w = []
for ind in ind_name:
    df_temp = df_c1[df_c1[ind]==1]
    r_temp = sum(df_temp['market_cap'].values)/all_mkt
    ind_w.append(r_temp)
        
    #风格因子与行业因子与常数
X_ = pd.concat([x,hy_df],axis=1)
    #最优化求解因子收益率
X = matrix(X_.values)
w_m = get_size['market_cap'].values
w_i = ind_w
    
    #最优化求解因子收益率
def func(f):
    sum_l = []
    for i in range(len(r)):
        if str(r[i]) !='nan':
            sum_l.append(w_m[i]*(r[i]-np.dot(X[i],f))**2)#权重*残差的平方
    return sum(sum_l)

def func_cons(f):
    return sum(multiply(f[(-1-len(w_i)):-1],w_i))

    # 初始值 + 约束条件 
f0 = np.ones(X_.shape[1]) / 10**4
bnds = tuple((-1,1) for x in f0)
cons = ({'type':'eq', 'fun': func_cons})
options={'disp':False, 'maxiter':1000, 'ftol':1e-4,'eps':1e-4}

res = minimize(func, f0, bounds=bnds, constraints=cons, method='SLSQP', options=options)

#x对应array即为因子收益率序列
res['x']
    


# ## 3.3 时间序列回归计算因子收益率序列

# In[44]:


#出现wrong是因为财务报表数据缺失，跳过。
factor_f_df = pd.DataFrame()
for d in date_list[1:]:
    d=str(d)[:10]
    print('正在计算{}...'.format(d))
    #获取因子暴露
    factor_df = factor_data_y_dict[d]
    x = factor_df.iloc[:,:-2]
    r = factor_df['pct_'].fillna(factor_df['pct_'].mean()).values
    # r = factor_df['pct_'].values
    pool  = factor_df.index
    
    #计算市值平方根占比
    get_size = get_fundamentals(query(valuation.code,valuation.market_cap).                                filter(valuation.code.in_(pool)),date=d)
    if get_size.shape[0]!=x.shape[0]:
        print('wrong')
        pass
    else:
        get_size.index = get_size['code'].values
        get_size['l_size'] = np.sqrt(get_size['market_cap'])
        get_size['w'] = get_size['l_size']/sum(get_size['l_size'])
        W = (get_size['w'].values).reshape(len(get_size),1)
        
        #计算行业市值权重占比
        hy_df = get_industry_exposure1(pool,date=d).T
        hy_df['cons'] = [1]*len(hy_df)
        
        df_c1 = pd.concat([hy_df,get_size],axis=1)
        ind_name = get_industries(name='sw_l1').index
        df_c1['market_cap'].fillna(df_c1['market_cap'].mean())
        all_mkt = df_c1['market_cap'].sum()
        ind_w = []
        for ind in ind_name:
            df_temp = df_c1[df_c1[ind]==1]
            r_temp = sum(df_temp['market_cap'].values)/all_mkt
            ind_w.append(r_temp)
            
        #进行大X拼接
        X_ = pd.concat([x,hy_df],axis=1)
        #最优化求解因子收益率
        X = matrix(X_.values)
        w_m = get_size['market_cap'].values
        w_i = ind_w
        
        #最优化求解因子收益率
        def func(f):
            sum_l = []
            for i in range(len(r)):
                if str(r[i]) !='nan':
                    sum_l.append(w_m[i]*(r[i]-np.dot(X[i],f))**2)
            return sum(sum_l)
        
        def func_cons(x):
            return sum(multiply(x[-1-len(w_i):-1],w_i))
        
        # 初始值 + 约束条件 
        f0 = np.ones(X_.shape[1]) / 10**4
        bnds = tuple((-1,1) for x in f0)
        cons = ({'type':'eq', 'fun': func_cons})
        options={'disp':False, 'maxiter':1000, 'ftol':1e-4,'eps':1e-4}
        
        res = minimize(func, f0, bounds=bnds, constraints=cons,                       method='SLSQP', options=options)
        
        factor_f_df[d] = res['x']
        
factor_f_df.head()


# In[47]:


factor_f = factor_f_df.T
factor_f.columns = factor_name+list(get_industries(name='sw_l1').index)+['cons']
factor_f.head(15)


# ### 3.3.1市值风格解析

# In[29]:


#因子历史资产价值（第一期起初为1）
ones_df=pd.DataFrame(np.ones([1,len(factor_name)]),columns=factor_name,index=[date_list[0]])
temp_df=(factor_f.iloc[:,:10]+1).cumprod()
pd.concat([ones_df,temp_df]).plot(figsize=(20,8))


# In[30]:


#纯净因子累计收益
((factor_f.iloc[:,:10]+1).cumprod()-1).iloc[-1,:].plot(kind='bar',figsize=(20,8))


# In[31]:


#行业历史资产价值（第一期起初为1）
ones_df=pd.DataFrame(np.ones([1,len(get_industries(name='sw_l1').index)+1])                     ,columns=list(get_industries(name='sw_l1').index)+['cons']                     ,index=[date_list[0]])
temp_df=(factor_f.iloc[:,10:]+1).cumprod()
pd.concat([ones_df,temp_df]).plot(figsize=(20,8))


# In[32]:


#行业累计收益
(temp_df-1).iloc[-1,:].plot(kind='bar',figsize=(20,8))


# ### 3.3.2组合收益归因

# In[62]:


#中证500选50只股票，进行收益分析
#进行因子值计算
factor_data_50_dict = {}
factor_name = ['size','beta','momentum','residual_volatility','non_linear_size',               'book_to_price_ratio','liquidity','earnings_yield','growth',               'leverage']
#循环时间列表获取原始因子数据组成dict
for end_date in date_list[1:]:
    end_date=str(end_date)[:10]
    print('正在计算 {} 因子数据......'.format(end_date))
    stocks_list = get_index_stocks(index,date=end_date)
    pool_ = [stocks_list[i] for i in range(len(stocks_list)) if i%10==0]#等间隔选取50只
    stocks_list = pool_
    #计算行业市值权重占比
    hy_df = get_industry_exposure1(pool_,date=end_date).T
    hy_df['cons'] = [1]*len(hy_df)
    x = factor_data_y_dict[end_date].loc[pool_,factor_name]
    df_pct = factor_data_y_dict[end_date].loc[pool_,['pct_']]
    #进行大X拼接
    X_ = pd.concat([x,hy_df,df_pct],axis=1)
    factor_data_50_dict[end_date] = X_
factor_data_50_dict[end_date].head(200)

df = pd.DataFrame(factor_data_50_dict[end_date])

write_file('from_backtest.csv', df.to_csv(), append=False) #写到文件中


# In[27]:


#收益率与超额收益率的图表？
factor_fT=factor_f.T
mark = 1
for d in date_list[1:]:
    end_date = str(d)[:10]
    if end_date not in factor_fT.columns:
        pass
    else:
        d1 = factor_data_50_dict[end_date]
        d2 = factor_fT.loc[:,end_date]
        y_df = pd.DataFrame()
        y_df['pct_'] = d1['pct_']
        y_df['p_pct_']= np.dot(d1.iloc[:,:-1],d2)
        if mark == 1:
            y_df_ = y_df
            mark = 0
        else:
            y_df_ = pd.concat([y_df_,y_df],axis=0)
y_df_.head(10)


# In[515]:


y_df_.plot(x='pct_', y='p_pct_', kind='scatter',figsize=(12,8))


# ### 3.3.3 以2020-01-02为例,检查因子暴露度百分位

# In[516]:


end_date = '2020-02-03'
d3 = factor_data_y_dict[end_date]
d1 = factor_data_50_dict[end_date].dropna(axis=0)
d_mean = d1.mean(axis=0)[:len(factor_name)]#风格因子的均值
d4 = pd.concat([d3.iloc[:,:len(factor_name)].T,d_mean],axis=1)
d4['mid'] = [0.5]*len(d4)
(d4.rank(axis=1)[0]/500).plot(kind='bar',figsize=(12,6))#0号股票各因素在中证500中的排名
d4['mid'].plot()
plt.show()


# In[517]:


y_df.plot(figsize=(12,8))


# ## 3.4IC值

# In[518]:


# 原来的因子载荷序列中当期股票数据框加入股票下期收益率
factor_data_y_dict_new =  factor_data_y_dict.copy()
factor_data_y_dict_new.pop(str(date_list[-1])[:10])
for idx,timestamp in enumerate(list(date_list[1:-1])):
    print('正在计算'+str(timestamp)[:10])
    t1 = ShiftTradingDay(timestamp,1)
    t2 = ShiftTradingDay(date_list[idx+1],1)
    t3 = ShiftTradingDay(date_list[idx+2],1)
    pool = list(factor_data_y_dict_new[str(timestamp)[:10]].index)
    pool = filter_stock(pool,str(t3)[:10],days=21*3)
    df1 = get_price(pool,end_date=t2,fields=['open'],count = 1)['open']
    df2 = get_price(pool,end_date=t3,fields=['open'],count = 1)['open']
    df3 = pd.concat([df1,df2],axis=0).T #进行合并
    stock_pct_next = df3.iloc[:,1]/df3.iloc[:,0]-1
    factor_data_y_dict_new[str(timestamp)[:10]]['pct_next'] = stock_pct_next
factor_data_y_dict_new[str(date_list[-2])[:10]].head()


# In[519]:


factors_ic={}
factors_beta = {}
factors_t = {}

for date_cur,temp_df in factor_data_y_dict_new.items():
    print('正在计算'+date_cur)
    factors_ic_period = []
    factors_beta_period = []
    factors_t_period = []
    temp_df = temp_df.fillna(0)
    for factor in temp_df.columns[:-3]:
        ########### 因子IC ############
        # 计算与最后一列的收益秩相关系数
        ic = st.spearmanr(temp_df[factor],temp_df['pct_next'])[0]
        # 依次存入列表
        factors_ic_period.append(ic)

        ########### 因子收益率,t值,不考虑行业因子###########
        # 每列因子与收益率RLM回归,得到系数,t值
        # 加截距,变成二维
        x=sm.add_constant(temp_df[factor])
        model = sm.RLM(temp_df['pct_'],x).fit()
        factors_beta_period.append(model.params[1])
        factors_t_period.append(model.tvalues[1])
        
    factors_ic[date_cur] = factors_ic_period
    factors_beta[date_cur] = factors_beta_period 
    factors_t[date_cur] = factors_t_period                           


# In[520]:


factors_ic


# In[521]:


ic_df = dict_to_df(factors_ic,factor_name,'IC')
beta_df = dict_to_df(factors_beta,factor_name,'beta')
t_df = dict_to_df(factors_t,factor_name,'t')


# In[522]:


evaluation(ic_df,beta_df,t_df)


# In[523]:


eval_df = evaluation(ic_df,beta_df,t_df)


# In[524]:


def color_negative_red(val):
    color = 'red' if val < 0 else 'black'
    return 'color: %s' % color

eval_df.style.applymap(color_negative_red,subset=['IC均值', '因子收益率均值', 'IR'])

#eval_df.style.applymap(showColor,subset=pd.IndexSlice[1:,1:])#指定表格位置?


# In[525]:


corr = plot_heat(ic_df,eval_df)


# In[526]:


corr


# # 4 分层回测
# 

# 分组回测
# 
# ①每个交易日取出股票池中股票的因子值，按从小到大进行排序，将排序后的股票池等分成N个股票组合。(本文采用5等分股票池）
# 
# ②等额买入每个等份的股票组合，月底重复①②两步并重新调仓，最后计算平均收益。(本文默认按月调仓）
# 
# ③在总的时间区间上，每个调仓周期结束后进行一个复利的计算，最后将每组股票的累计收益绘制出来进行对比。

# In[556]:


#设置用于分组检查的因子值
factor_test = 'momentum'
pool_dict = {}
groups = 5
return_dict={}
for date_cur,temp_df in factor_data_y_dict_new.items():
    group_split = pd.qcut(temp_df[factor_test],5,labels =                           ['l1','l2','l3','l4','l5'])#将股票池分为l1-l5五类
    group1 = group_split[group_split=='l1'].index
    group2 = group_split[group_split=='l2'].index
    group3 = group_split[group_split=='l3'].index
    group4 = group_split[group_split=='l4'].index
    group5 = group_split[group_split=='l5'].index
    pool_dict[date_cur] = [group1,group2,group3,group4,group5]


# In[557]:


return_df = pd.DataFrame()
for idx,datetimeindex in enumerate(date_list[1:-1]):
    datetimeindex = str(datetimeindex)[:10]
    
    for idx_g,group in enumerate(pool_dict[datetimeindex]):
        group = list(group)
        price1 = get_price(group,end_date=datetimeindex,                           fields=['open'],count = 1)['open']
        price2 = get_price(group,end_date=list(date_list)[idx+2],                           fields=['open'],count = 1)['open']
        price3 = pd.concat([price1,price2],axis=0).T #进行合并
        ret = (price3.iloc[:,1]/price3.iloc[:,0] -1).mean()#每期收益率
        return_df.loc[datetimeindex,idx_g] = ret     
return_df.columns = ['group1','group2','group3','group4','group5']
return_df1=(return_df+1).cumprod()
return_df1


# In[558]:


return_df1.plot(figsize=(12,8))


# In[ ]:




