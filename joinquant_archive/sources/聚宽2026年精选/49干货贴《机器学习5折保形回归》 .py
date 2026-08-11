#!/usr/bin/env python
# coding: utf-8

# In[3]:


from jqdata import *
from jqlib.technical_analysis import *
from jqfactor import get_factor_values
from jqfactor import winsorize_med
from jqfactor import standardlize
from jqfactor import neutralize
import datetime
import pandas as pd
import numpy as np
from scipy import stats
import statsmodels.api as sm
from statsmodels import regression
from six import StringIO
#导入pca
from sklearn.decomposition import PCA
from sklearn import svm
from sklearn.model_selection import train_test_split
from sklearn.grid_search import GridSearchCV
from sklearn import metrics
from tqdm import tqdm
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings("ignore")
import seaborn as sns
#获取指定周期的日期列表 'W、M、Q'
def get_period_date(peroid,start_date, end_date):
    #设定转换周期period_type  转换为周是'W',月'M',季度线'Q',五分钟'5min',12天'12D'
    stock_data = get_price('000001.XSHE',start_date,end_date,'daily',fields=['close'])
    #记录每个周期中最后一个交易日
    stock_data['date']=stock_data.index
    #进行转换，周线的每个变量都等于那一周中最后一个交易日的变量值
    period_stock_data=stock_data.resample(peroid,how='last')
    period_stock_data = period_stock_data.set_index('date').dropna()
    date=period_stock_data.index
    pydate_array = date.to_pydatetime()
    date_only_array = np.vectorize(lambda s: s.strftime('%Y-%m-%d'))(pydate_array )

    date_only_series = pd.Series(date_only_array)

    start_date = datetime.datetime.strptime(start_date, "%Y-%m-%d")
    start_date=start_date-datetime.timedelta(days=1)
    start_date = start_date.strftime("%Y-%m-%d")
    date_list=date_only_series.values.tolist()
    date_list.insert(0,start_date)
    return date_list
peroid = 'M'
start_date = '2010-01-01'
end_date = '2024-01-01'


DAY = get_period_date(peroid,start_date, end_date)
print(len(DAY))


# In[4]:


#去除上市距beginDate不足3个月的股票
def delect_stop(stocks,beginDate,n=30*3):
    stockList=[]
    beginDate = datetime.datetime.strptime(beginDate, "%Y-%m-%d")
    for stock in stocks:
        start_date=get_security_info(stock).start_date
        if start_date<(beginDate-datetime.timedelta(days=n)).date():
            stockList.append(stock)
    return stockList
#获取股票池
def get_stock(stockPool,begin_date):
    if stockPool=='HS300':
        stockList=get_index_stocks('000300.XSHG',begin_date)
    elif stockPool=='ZZ500':
        stockList=get_index_stocks('399905.XSHE',begin_date)
    elif stockPool=='ZZ800':
        stockList=get_index_stocks('399906.XSHE',begin_date)   
    elif stockPool=='CYBZ':
        stockList=get_index_stocks('399006.XSHE',begin_date)
    elif stockPool=='ZXBZ':
        stockList=get_index_stocks('399005.XSHE',begin_date)
    elif stockPool=='A':
        stockList=get_index_stocks('000002.XSHG',begin_date)+get_index_stocks('399107.XSHE',begin_date)
        stockList = [stock for stock in stockList if not stock.startswith(('68', '4', '8'))]
    elif stockPool=='AA':
        stockList=get_index_stocks('000985.XSHG',begin_date)
        stockList = [stock for stock in stockList if not stock.startswith(('3', '68', '4', '8'))]

    #剔除ST股
    st_data=get_extras('is_st',stockList, count = 1,end_date=begin_date)
    stockList = [stock for stock in stockList if not st_data[stock][0]]
    #剔除停牌、新股及退市股票
    stockList=delect_stop(stockList,begin_date)
    return stockList


# In[6]:



#取股票对应行业
def get_industry_name(i_Constituent_Stocks, value):
    return [k for k, v in i_Constituent_Stocks.items() if value in v]

#缺失值处理
def replace_nan_indu(factor_data,stockList,industry_code,date):
    #把nan用行业平均值代替，依然会有nan，此时用所有股票平均值代替
    i_Constituent_Stocks={}
    data_temp=pd.DataFrame(index=industry_code,columns=factor_data.columns)
    for i in industry_code:
        temp = get_industry_stocks(i, date)
        i_Constituent_Stocks[i] = list(set(temp).intersection(set(stockList)))
        data_temp.loc[i]=mean(factor_data.loc[i_Constituent_Stocks[i],:])
    for factor in data_temp.columns:
        #行业缺失值用所有行业平均值代替
        null_industry=list(data_temp.loc[pd.isnull(data_temp[factor]),factor].keys())
        for i in null_industry:
            data_temp.loc[i,factor]=mean(data_temp[factor])
        null_stock=list(factor_data.loc[pd.isnull(factor_data[factor]),factor].keys())
        for i in null_stock:
            industry=get_industry_name(i_Constituent_Stocks, i)
            if industry:
                factor_data.loc[i,factor]=data_temp.loc[industry[0],factor] 
            else:
                factor_data.loc[i,factor]=mean(factor_data[factor])
    return factor_data

#数据预处理
def data_preprocessing(factor_data,stockList,industry_code,date):
    #去极值
    factor_data=winsorize_med(factor_data, scale=5, inf2nan=False,axis=0)
    #缺失值处理
    factor_data=replace_nan_indu(factor_data,stockList,industry_code,date)
    factor_data=standardlize(factor_data,axis=0)
    return factor_data
jqfactors_list=['non_linear_size',#非线性市值(风格因子)5
                'beta',            #贝塔
                 'book_to_price_ratio',  #市面账值比
                'earnings_yield',  #盈利能力，
               'growth'            #成长 
               ]
#获取时间为date的全部因子数据
def get_factor_data(securities_list,date):
    factor_data = get_factor_values(securities=securities_list,                                     factors=jqfactors_list,                                     count=1,                                     end_date=date)
    df_jq_factor=pd.DataFrame(index=securities_list)
    
    for i in factor_data.keys():
        df_jq_factor[i]=factor_data[i].iloc[0,:]
    
    return df_jq_factor


industry_old_code = ['801010','801020','801030','801040','801050','801080','801110','801120','801130','801140','801150',                    '801160','801170','801180','801200','801210','801230']
industry_new_code = ['801010','801020','801030','801040','801050','801080','801110','801120','801130','801140','801150',                    '801160','801170','801180','801200','801210','801230','801710','801720','801730','801740','801750',                   '801760','801770','801780','801790','801880','801890']

dateList = get_period_date(peroid,start_date, end_date)
print(len(dateList))
train_data=pd.DataFrame()
train_length = 10*12
for date in tqdm(dateList[:train_length]):
    try:
        #获取行业因子数据
        if datetime.datetime.strptime(date,"%Y-%m-%d").date()<datetime.date(2014,2,21):
            industry_code=industry_old_code
        else:
            industry_code=industry_new_code
        stockList=get_stock('A',date)
        print(len(stockList))

        factor_origl_data = get_factor_data(stockList,date)
        factor_solve_data = data_preprocessing(factor_origl_data,stockList,industry_code,date)
        
        data_close=get_price(stockList,date,dateList[dateList.index(date)+1],'1d','close')['close']
        factor_solve_data['pchg']=data_close.iloc[-1]/data_close.iloc[1]-1

        SZ=get_price('000001.XSHG',date,dateList[dateList.index(date)+1],'1d','close')['close']
        factor_solve_data['SZ']=SZ.iloc[-1]/SZ.iloc[1]-1
        factor_solve_data['LABEL']=factor_solve_data['pchg']-factor_solve_data['SZ']
        factor_solve_data['label'] = 0 
        factor_solve_data.loc[factor_solve_data['LABEL'] > 0.1, 'label'] = 1 
        
        
        

        if train_data.empty:
            train_data=factor_solve_data
        else:
            train_data=train_data.append(factor_solve_data)
    except:
        pass
            
train_data.to_csv(r'train_conformal_base.csv')
print(len(train_data))  


# In[7]:


train_data=pd.DataFrame()
for date in tqdm(dateList[train_length:-1]):
    try:
        #获取行业因子数据
        if datetime.datetime.strptime(date,"%Y-%m-%d").date()<datetime.date(2014,2,21):
            industry_code=industry_old_code
        else:
            industry_code=industry_new_code
        stockList=get_stock('A',date)
        factor_origl_data = get_factor_data(stockList,date)
        factor_solve_data = data_preprocessing(factor_origl_data,stockList,industry_code,date)

        data_close=get_price(stockList,date,dateList[dateList.index(date)+1],'1d','close')['close']
        factor_solve_data['pchg']=data_close.iloc[-1]/data_close.iloc[1]-1

        SZ=get_price('000001.XSHG',date,dateList[dateList.index(date)+1],'1d','close')['close']
        factor_solve_data['SZ']=SZ.iloc[-1]/SZ.iloc[1]-1
        factor_solve_data['LABEL']=factor_solve_data['pchg']-factor_solve_data['SZ']
        factor_solve_data['label'] = 0 
        factor_solve_data.loc[factor_solve_data['LABEL'] > 0.1, 'label'] = 1 
        
        

        if train_data.empty:
            train_data=factor_solve_data
        else:
            train_data=train_data.append(factor_solve_data)
    except:
        pass
            
train_data.to_csv(r'test_conformal_base.csv')
print(len(train_data))

