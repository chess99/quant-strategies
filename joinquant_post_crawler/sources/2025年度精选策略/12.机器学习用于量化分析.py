#!/usr/bin/env python
# coding: utf-8

# # 基于机器学习算法的因子选股策略

# 尝试机器学习算法
# 不同的数据清洗方式

# In[1]:


import pandas as pd
import numpy as np
import math
import jqdata
from jqdata import *
import time
import datetime
from jqfactor import *
import pickle
from sklearn.model_selection import StratifiedKFold, cross_val_score  # 导入交叉检验算法
from sklearn.feature_selection import SelectPercentile, f_classif  # 导入特征选择方法库
from sklearn.pipeline import Pipeline  # 导入Pipeline库
from sklearn.metrics import accuracy_score  # 准确率指标
from sklearn.metrics import roc_auc_score
from jqlib.technical_analysis import *
from xgboost.sklearn import XGBClassifier
from sklearn.ensemble import RandomForestClassifier
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import seaborn as sns
import lightgbm as lgb
from sklearn.model_selection import train_test_split
import gc
from sklearn.model_selection import GridSearchCV
import tensorflow as tf
import warnings
warnings.filterwarnings('ignore')


# # 参数设置

# In[2]:



#按月区间取值
peroid = 'M'
#样本区间（训练集+测试集的区间为2014-1-31到2018-12-31）
start_date = '2010-01-01'
end_date = '2020-02-28'
#训练集长度
train_length = 48
#使用行业
industry_name = 'sw_l1'  #申万一级行业
#聚宽一级行业
industry_code = ['HY001', 'HY002', 'HY003', 'HY004', 'HY005', 'HY006', 'HY007', 'HY008', 'HY009', 'HY010', 'HY011']
#去除上市不满足N天的股票
DELETE_STOP_NDAYS = 90 
#股票池，获取中证全指
SELECT_STOCK_INDEX = '000985.XSHG'
#训练样本比例
TRAIN_PERCENT = 0.7
#参与分类计算的数据比例
POSITIVE_PERCENT = 0.3 #从训练样本中选取收益值最高的前30%标签设为1
NAGATIVE_PERCENT = 0.3 #从训练样本中选取收益值最底的后30%标签设为-1


# In[3]:


#聚宽因子
jqfactors_list = ['current_ratio',
                  'net_profit_to_total_operate_revenue_ttm',
                  'gross_income_ratio',
                  'roe_ttm',
                  'roa_ttm',
                  'total_asset_turnover_rate',\
                  'net_operating_cash_flow_coverage',
                  'net_operate_cash_flow_ttm',
                  'net_profit_ttm',\
                  'cash_to_current_liability',
                  'operating_revenue_growth_rate',
                  'non_recurring_gain_loss',\
                  'operating_revenue_ttm',
                  'net_profit_growth_rate']

basis_factors = ['net_working_capital','total_operating_revenue_ttm','operating_profit_ttm',
                'net_operate_cash_flow_ttm','operating_revenue_ttm','interest_carry_current_liability',
                'sale_expense_ttm','retained_earnings','total_operating_cost_ttm','non_operating_net_profit_ttm',
                'net_invest_cash_flow_ttm','financial_expense_ttm','administration_expense_ttm',
                'net_interest_expense','value_change_profit_ttm','total_profit_ttm','net_finance_cash_flow_ttm',
                'interest_free_current_liability','EBIT','net_profit_ttm','OperateNetIncome',
                'EBITDA','asset_impairment_loss_ttm','np_parent_company_owners_ttm',
                'operating_cost_ttm','net_debt','non_recurring_gain_loss','goods_sale_and_service_render_cash_ttm',
                'market_cap','cash_flow_to_price_ratio','sales_to_price_ratio','circulating_market_cap',
                'operating_assets','financial_assets','operating_liability','financial_liability']

#自定义因子
q = query(valuation.code, 
      valuation.market_cap,#市值
      valuation.circulating_market_cap,
      valuation.pe_ratio, #市盈率（TTM）
      valuation.pb_ratio, #市净率（TTM）
      valuation.pcf_ratio, #CFP
      valuation.ps_ratio, #PS
      balance.total_assets,
      balance.total_liability,
      balance.development_expenditure, #RD
      balance.dividend_payable,
      balance.fixed_assets,  
      balance.total_non_current_liability,
      income.operating_profit,
      income.total_profit, #OPTP
      #
      indicator.net_profit_to_total_revenue, #净利润/营业总收入
      indicator.inc_revenue_year_on_year,  #营业收入增长率（同比）
      indicator.inc_net_profit_year_on_year,#净利润增长率（同比）
      indicator.roe,
      indicator.roa,
      indicator.gross_profit_margin #销售毛利率GPM
    )

#所有聚宽因子
all_jqfactors = list(get_all_factors()['factor'].values)
len(all_jqfactors)


# In[ ]:





# # 一、 数据获取

# In[4]:


#去除上市距beginDate不足n天的股票
def delete_stop(stocks,beginDate,n):
    stockList=[]
    beginDate = datetime.datetime.strptime(beginDate, "%Y-%m-%d")
    for stock in stocks:
        start_date=get_security_info(stock).start_date
        if start_date<(beginDate-datetime.timedelta(days=n)).date():
            stockList.append(stock)
    return stockList


# In[5]:


#剔除ST股
def delete_st(stocks,begin_date):
    st_data=get_extras('is_st',stocks, count = 1,end_date=begin_date)
    stockList = [stock for stock in stocks if not st_data[stock][0]]
    return stockList


# In[6]:


securities_list = delete_stop(get_index_stocks(SELECT_STOCK_INDEX),start_date,DELETE_STOP_NDAYS)
securities_list = delete_st(securities_list,start_date)


# In[7]:


print(len(securities_list))


# In[8]:


def get_jq_factor(securities,factor_list,date):
    '''
    获取聚宽因子
    securities：list,股票列表
    factor_list:list,因子列表
    date: 日期， 字符串或 datetime 对象
    output:
    dataframe, index为股票代码，columns为因子
    '''
    factor_data = get_factor_values(securities=securities,                                     factors=factor_list,                                     count=1,                                     end_date=date)
    df_jq_factor=pd.DataFrame(index=securities)
    
    for i in factor_data.keys():
        df_jq_factor[i]=factor_data[i].iloc[0,:]
    
    return df_jq_factor


# In[9]:


def initialize_df(securities,df,date):
    
    #净资产
    df['net_assets']=df['total_assets']-df['total_liability']

    df_new = pd.DataFrame(index=securities)
        
    #估值因子
    df_new['EP'] = df['pe_ratio'].apply(lambda x: 1/x)
    df_new['BP'] = df['pb_ratio'].apply(lambda x: 1/x)
    df_new['SP'] = df['ps_ratio'].apply(lambda x: 1/x)
    #df_new['DP'] = df['dividend_payable']/(df['market_cap']*100000000)
    df_new['RD'] = df['development_expenditure']/(df['market_cap']*100000000)
    df_new['CFP'] = df['pcf_ratio'].apply(lambda x: 1/x)
    
    #杠杆因子
    #对数流通市值
    df_new['CMV'] = np.log(df['circulating_market_cap'])
    #总资产/净资产
    df_new['financial_leverage']=df['total_assets']/df['net_assets']
    #非流动负债/净资产
    df_new['debtequityratio']=df['total_non_current_liability']/df['net_assets']
    #现金比率=(货币资金+有价证券)÷流动负债
    df_new['cashratio']=df['cash_to_current_liability']
    #流动比率=流动资产/流动负债*100%
    df_new['currentratio']=df['current_ratio']
    
    #财务质量因子
    # 净利润与营业总收入之比
    df_new['NI'] = df['net_profit_to_total_operate_revenue_ttm']
    df_new['GPM'] = df['gross_income_ratio']
    df_new['ROE'] = df['roe_ttm']
    df_new['ROA'] = df['roa_ttm']
    df_new['asset_turnover'] = df['total_asset_turnover_rate']
    df_new['net_operating_cash_flow'] = df['net_operating_cash_flow_coverage']
    
    #成长因子
    df_new['Sales_G_q'] = df['operating_revenue_growth_rate']
    df_new['Profit_G_q'] = df['net_profit_growth_rate']
    
    #技术指标
    df_new['RSI']=pd.Series(RSI(securities, date, N1=20))    
    dif,dea,macd=MACD(securities, date, SHORT = 10, LONG = 30, MID = 15)
    df_new['DIF']=pd.Series(dif)
    df_new['DEA']=pd.Series(dea)
    df_new['MACD']=pd.Series(macd)    
    
    return df_new


# In[10]:


#获取指定周期的日期列表 'W、M、Q'
def get_period_date(peroid,start_date, end_date):
    #设定转换周期period_type  转换为周是'W',月'M',季度线'Q',五分钟'5min',12天'12D'
    stock_data = get_price('000001.XSHE',start_date,end_date,'daily',fields=['close'])
    #记录每个周期中最后一个交易日
    stock_data['date']=stock_data.index
    #进行转换，周线的每个变量都等于那一周中最后一个交易日的变量值
    period_stock_data=stock_data.resample(peroid).last()
    date = period_stock_data.index
    pydate_array = date.to_pydatetime()
    date_only_array = np.vectorize(lambda s: s.strftime('%Y-%m-%d'))(pydate_array )
    date_only_series = pd.Series(date_only_array)
    start_date = datetime.datetime.strptime(start_date, "%Y-%m-%d")
    start_date = start_date-datetime.timedelta(days=1)
    start_date = start_date.strftime("%Y-%m-%d")
    date_list = date_only_series.values.tolist()
    date_list.insert(0,start_date)
    return date_list
dateList = get_period_date(peroid,start_date,end_date)


# In[11]:


def get_datelist_stocks_factors(securities,jqfactot_list,date_list):
    # (jqdata)因子
    df_jq_factor = {}
    # （财务数据）因子
    df_q_factor = {}
    # 预处理前的原始因子训练集
    df_factor_pre_train = {}

    for date in dateList:
        df_jq_factor = get_jq_factor(securities,jqfactot_list,date)
        df_q_factor = get_fundamentals(q.filter(valuation.code.in_(securities)), date = date)
        df_q_factor.index = df_q_factor['code']
        # 合并得大表
        df_factor_pre_train[date] = pd.concat([df_q_factor,df_jq_factor],axis=1)
        # 初始化
        df_factor_pre_train[date] = initialize_df(securities,df_factor_pre_train[date],date)
        
    return df_factor_pre_train

#df_factor_pre_train = get_datelist_stocks_factors(securities_list,jqfactors_list,dateList)


# In[12]:


def get_datelist_stocks_factors_jqfactors(securities,jqfactot_list,date_list):
    # (jqdata)因子
    df_jq_factor = {}
    # （财务数据）因子
    df_q_factor = {}
    # 预处理前的原始因子训练集
    df_factor_pre_train = {}

    for date in date_list:      
        length_factors = len(jqfactot_list)
        if length_factors > 50:
            df_factor_pre_train_l = []
            r = int(length_factors/30)
            for i in range(r+1):
                if 30*(i+1) < length_factors:
                    df = get_jq_factor(securities,jqfactot_list[30*i:30*(i+1)],date)
                else:
                    df = get_jq_factor(securities,jqfactot_list[30*i:],date)
                df_factor_pre_train_l.append(df)
            df_jq_factor = pd.concat(df_factor_pre_train_l,axis=1)
        else:
            df_jq_factor = get_jq_factor(securities,jqfactot_list,date)

        df_factor_pre_train[date] = df_jq_factor

    return df_factor_pre_train

#df_factor_pre_train = get_datelist_stocks_factors_jqfactors(securities_list,all_jqfactors,dateList[125:200])


# In[13]:


with open('all_jqfactors.pkl','rb') as pf:
    all_data = pickle.load(pf)


# In[14]:


#提取基础因子
keys = list(all_data.keys())
basic_dic = {}
for key in keys[:2]:
    data = all_data[key]
    basic_data = data[basis_factors]
    basic_dic[key] = basic_data
len(basic_dic)


# # 数据处理

# In[15]:




def get_stock_industry(industry_name,date,output_csv = False):
    '''
    获取股票对应的行业
    input：
    industry_name: str, 
    "sw_l1": 申万一级行业
    "sw_l2": 申万二级行业
    "sw_l3": 申万三级行业
    "jq_l1": 聚宽一级行业
    "jq_l2": 聚宽二级行业
    "zjw": 证监会行业
    date:时间
    output: DataFrame,index 为股票代码，columns 为所属行业代码
    '''
    industries = list(get_industries(industry_name).index)
    all_securities = get_all_securities(date=date)   #获取当天所有股票代码
    all_securities['industry_code'] = 1
    for ind in industries:
        industry_stocks = get_industry_stocks(ind,date)
        #有的行业股票不在all_stocks列表之中
        industry_stocks = set(all_securities) & set(industry_stocks)
        all_securities['industry_code'][industry_stocks] = ind
    stock_industry = all_securities['industry_code'].to_frame()
    if output_csv == True:
        stock_industry.to_csv('stock_industry.csv') #输出csv文件，股票对应行业
    return stock_industry


# In[16]:


def fillna_with_industry(data,date,industry_name='sw_l1'):
    '''
    使用行业均值填充nan值
    input:
    data：DataFrame,输入数据，index为股票代码
    date:string,时间必须和data数值对应时间一致
    output：
    DataFrame,缺失值用行业中值填充，无行业数据的用列均值填充
    '''
    stocks = list(data.index)
    stocks_industry = get_stock_industry(industry_name,date)
    stocks_industry_merge = data.merge(stocks_industry, left_index=True,right_index=True,how='left')
    stocks_dropna = stocks_industry_merge.dropna()
    columns = list(data.columns)
    select_data = []
    group_data = stocks_industry_merge.groupby('industry_code')
    group_data_mean = group_data.mean()
    group_data = stocks_industry_merge.merge(group_data_mean,left_on='industry_code',right_index=True,how='left')
    for column in columns:

        if type(data[column][0]) != str:

            group_data[column+'_x'][pd.isnull(group_data[column+'_x'])] = group_data[column+'_y'][pd.isnull(group_data[column+'_x'])]
            
            group_data[column] = group_data[column+'_x']
            #print(group_data.head())
            select_data.append(group_data[column])
            
    result = pd.concat(select_data,axis=1)
    #行业均值为Nan,用总体均值填充
    mean = result.mean()
    for i in result.columns:
        result[i].fillna(mean[i],inplace=True)
    return result


# In[17]:


#数据预处理
def data_preprocessing(factor_data,date,industry_name='sw_l1'):
    '''
    数据预处理
    input:
    factor_data:df ，index为股票列表，columns为因子
    
    '''
    #去极值
    try:
        factor_data=winsorize(factor_data, inf2nan=False,scale=1,axis=0)

        #缺失值处理
        factor_data=fillna_with_industry(factor_data,date,industry_name=industry_name)
        #中性化处理
        factor_data=neutralize(factor_data,how=['sw_l1','ln_market_cap'], date=date, axis=0)
        #标准化处理
        factor_data=standardlize(factor_data,axis=0)
    except:
        print(factor_data)
        print(date)
    return factor_data


# In[18]:


'''
all_fac = basic_dic
 
date_list =  list(all_fac.keys())
neu_dic = {}
st = time.time()
i=0
for date in date_list:
    data = all_fac[date]
    data_neu = data_preprocessing(data,date)
    neu_dic[date] = data_neu
    et = time.time()
    print((et-st)/60)
    i = i + 1
    print(i)
'''


# In[19]:


'''
with open('all_jqfactors_neu_ln_market_cap_swl1.pkl','rb') as pf:
    all_data = pickle.load(pf)

with open('basic_data_neu_ln_market_cap_swl1.pkl','rb') as pf:
    basic_data = pickle.load(pf)
keys = list(all_data.keys())
combine_dic = {}
for key in keys:
    all_df = all_data[key]
    basic_df = basic_data[key]
    all_df[basis_factors] = basic_df
    combine_dic[key] = all_df
len(combine_dic)
with open('combine_neu_ln_market_cap_swl1.pkl','wb') as pf:
    pickle.dump(combine_dic,pf)
'''


# In[20]:


# 预处理后的原始因子训练集
'''
df_factor_train = {}
for date in dateList:
    try:
        df_factor_train[date] = data_preprocessing(df_factor_pre_train[date],date)
    except:
        print(date)

with open('df_factor_after_process_10_20_all_jqfactors.pkl','wb') as pf:
        pickle.dump(df_factor_train,pf)


    
with open('df_factor_after_process_10_20_all_jqfactors.pkl','rb') as pf:
    df_factor_train = pickle.load(pf)
'''

    


# In[21]:


with open('combine_neu_ln_market_cap_swl1.pkl','rb') as pf:
    df_factor_train = pickle.load(pf)


# # 训练集和交叉验证

# In[22]:


# 训练集数据
def get_train_data(dic_data,date_list):
    '''
    input:
    dic_data:dic,keys为时间，values为df,index为股票列表，columns为因子
    date_list:list，时间列表，必须和dic_data的keys对应
    '''
    length = len(dic_data)
    train_length = int(length * TRAIN_PERCENT)
    train_data=pd.DataFrame()
    for date in dateList[:train_length]:
        traindf=df_factor_train[date]
        stockList=list(traindf.index)
        #取收益率数据
        data_close=get_price(stockList,date,dateList[dateList.index(date)+1],'1d','close')['close']
        traindf['pchg']=data_close.iloc[-1]/data_close.iloc[0]-1
        #剔除空值
        traindf=traindf.dropna() 
        #traindf=traindf.sort(columns='pchg')
        traindf=traindf.sort_values(by=['pchg'],ascending=False)
        
        #选取前后各30%的股票，剔除中间的噪声
        #取0-30%+70%-100%的数据
        traindf=traindf.iloc[:int(len(traindf['pchg'])*POSITIVE_PERCENT),:].append(traindf.iloc[int(len(traindf['pchg'])*(1-NAGATIVE_PERCENT)):,:])
        #前30%为1，后30%为-1
        traindf['label']=list(traindf['pchg'].apply(lambda x:1 if x>np.mean(list(traindf['pchg'])) else -1))    
        if train_data.empty:
            train_data=traindf
        else:
            train_data=train_data.append(traindf)
    return train_data
train_data = get_train_data(df_factor_train,dateList)
            


# In[23]:


len(train_data)


# In[24]:



def get_test_data(dic_data,date_list):
    '''
    input:
    dic_data:dic,keys为时间，values为df,index为股票列表，columns为因子
    date_list:list，时间列表，必须和dic_data的keys对应
    output:
    dic,keys为时间，values为df，index为股票列表，column为因子，其中最后一列是标签值，
    '''
    length = len(dic_data)
    train_length = int(length * TRAIN_PERCENT)
    test_data={}
    for date in dateList[train_length:-1]:
        testdf=df_factor_train[date]
        stockList=list(testdf.index)
        # 取收益率数据
        data_close=get_price(stockList,date,dateList[dateList.index(date)+1],'1d','close')['close']
        testdf['pchg']=data_close.iloc[-1]/data_close.iloc[0]-1
        #剔除空值
        testdf=testdf.dropna()  
    
        testdf=testdf.sort_values(by=['pchg'],ascending=False)
        #选取前后各30%的股票，剔除中间的噪声
        #取0-30%+70%-100%的数据
        #testdf=testdf.iloc[:int(len(traindf['pchg'])/10*3),:].append(testdf.iloc[int(len(testdf['pchg'])/10*7):,:])
        testdf['label']=list(testdf['pchg'].apply(lambda x:1 if x>0 else -1)) 
        test_data[date]=testdf
    return test_data

test_data = get_test_data(df_factor_train,dateList)
            


# In[25]:


#训练集
y_train = train_data['label']  # 分割y
X_train = train_data.copy()
del X_train['pchg']
del X_train['label']


# In[26]:


test_l = []
for key in test_data.keys():
    td = test_data[key]
    test_l.append(td)
test_df = pd.concat(test_l)
y_test = test_df['label']
x_test = test_df.copy()
del x_test['pchg']
del x_test['label']


# # 模型构建

# # 特征选择

# In[27]:


class FeatureSelection():
    '''
    特征选择：
    identify_collinear：基于相关系数，删除小于correlation_threshold的特征
    identify_importance_lgbm：基于LightGBM算法，得到feature_importance,选择和大于p_importance的特征
    filter_select:单变量选择，指定k,selectKBest基于method提供的算法选择前k个特征，
    selectPercentile选择前p百分比的特征
    wrapper_select:RFE，基于estimator递归特征消除，保留n_feature_to_select个特征
    '''
    def __init__(self):
        self.supports = None #bool型，特征是否被选中
        self.columns = None  #选择的特征
        self.record_collinear = None #自相关矩阵大于门限值
        
    def identify_collinear(self, data, correlation_threshold):
        """
        Finds collinear features based on the correlation coefficient between features. 
        For each pair of features with a correlation coefficient greather than `correlation_threshold`,
        only one of the pair is identified for removal. 

        Using code adapted from: https://gist.github.com/Swarchal/e29a3a1113403710b6850590641f046c
        
        Parameters
        --------

        data : dataframe
            Data observations in the rows and features in the columns

        correlation_threshold : float between 0 and 1
            Value of the Pearson correlation cofficient for identifying correlation features

        """
        columns = data.columns
        self.correlation_threshold = correlation_threshold

        # Calculate the correlations between every column
        corr_matrix = data.corr()
        
        self.corr_matrix = corr_matrix
    
        # Extract the upper triangle of the correlation matrix
        upper = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k = 1).astype(np.bool))
        # Select the features with correlations above the threshold
        # Need to use the absolute value
        to_drop = [column for column in upper.columns if any(upper[column].abs() > correlation_threshold)]
        obtain_columns = [column for column in columns if column not in to_drop]
        self.columns = obtain_columns
        # Dataframe to hold correlated pairs
        record_collinear = pd.DataFrame(columns = ['drop_feature', 'corr_feature', 'corr_value'])

        # Iterate through the columns to drop
        for column in to_drop:

            # Find the correlated features
            corr_features = list(upper.index[upper[column].abs() > correlation_threshold])

            # Find the correlated values
            corr_values = list(upper[column][upper[column].abs() > correlation_threshold])
            drop_features = [column for _ in range(len(corr_features))]    

            # Record the information (need a temp df for now)
            temp_df = pd.DataFrame.from_dict({'drop_feature': drop_features,
                                             'corr_feature': corr_features,
                                             'corr_value': corr_values})

            # Add to dataframe
            record_collinear = record_collinear.append(temp_df, ignore_index = True)

        self.record_collinear = record_collinear
        return data[obtain_columns]
     
        
    def identify_importance_lgbm(self, features, labels,p_importance=0.8, eval_metric='auc', task='classification', 
                                 n_iterations=10, early_stopping = True):
        """
        
        Identify the features with zero importance according to a gradient boosting machine.
        The gbm can be trained with early stopping using a validation set to prevent overfitting. 
        The feature importances are averaged over n_iterations to reduce variance. 
        
        Uses the LightGBM implementation (http://lightgbm.readthedocs.io/en/latest/index.html)

        Parameters 
        --------
        features : dataframe
            Data for training the model with observations in the rows
            and features in the columns

        labels : array, shape = (1, )
            Array of labels for training the model. These can be either binary 
            (if task is 'classification') or continuous (if task is 'regression')
            
        p_importance:float, range[0,1],default = 0.8
            sum of the importance of features above the value

        eval_metric : string
            Evaluation metric to use for the gradient boosting machine

        task : string, default = 'classification'
            The machine learning task, either 'classification' or 'regression'

        n_iterations : int, default = 10
            Number of iterations to train the gradient boosting machine
            
        early_stopping : boolean, default = True
            Whether or not to use early stopping with a validation set when training
        
        
        Notes
        --------
        
        - Features are one-hot encoded to handle the categorical variables before training.
        - The gbm is not optimized for any particular task and might need some hyperparameter tuning
        - Feature importances, including zero importance features, can change across runs

        """

        # One hot encoding
        data = features
        features = pd.get_dummies(features)

        # Extract feature names
        feature_names = list(features.columns)

        # Convert to np array
        features = np.array(features)
        labels = np.array(labels).reshape((-1, ))

        # Empty array for feature importances
        feature_importance_values = np.zeros(len(feature_names))
        
        print('Training Gradient Boosting Model\n')
        
        # Iterate through each fold
        for _ in range(n_iterations):

            if task == 'classification':
                model = lgb.LGBMClassifier(n_estimators=100, learning_rate = 0.05, verbose = -1)

            elif task == 'regression':
                model = lgb.LGBMRegressor(n_estimators=100, learning_rate = 0.05, verbose = -1)

            else:
                raise ValueError('Task must be either "classification" or "regression"')
                
            # If training using early stopping need a validation set
            if early_stopping:
                
                train_features, valid_features, train_labels, valid_labels = train_test_split(features, labels, test_size = 0.15)

                # Train the model with early stopping
                model.fit(train_features, train_labels, eval_metric = eval_metric,
                          eval_set = [(valid_features, valid_labels)],
                           verbose = -1)
                
                # Clean up memory
                gc.enable()
                del train_features, train_labels, valid_features, valid_labels
                gc.collect()
                
            else:
                model.fit(features, labels)

            # Record the feature importances
            feature_importance_values += model.feature_importances_ / n_iterations

        feature_importances = pd.DataFrame({'feature': feature_names, 'importance': feature_importance_values})

        # Sort features according to importance
        feature_importances = feature_importances.sort_values('importance', ascending = False).reset_index(drop = True)

        # Normalize the feature importances to add up to one
        feature_importances['normalized_importance'] = feature_importances['importance'] / feature_importances['importance'].sum()
        feature_importances['cumulative_importance'] = np.cumsum(feature_importances['normalized_importance'])
        select_df = feature_importances[feature_importances['cumulative_importance']<=p_importance]
        select_columns = select_df['feature']
        self.columns = list(select_columns.values)
        res = data[self.columns]
        return res
        
    def filter_select(self, data_x, data_y, k=None, p=50,method=f_classif):
        columns = data_x.columns
        if k != None:
            model = SelectKBest(method,k)
            res = model.fit_transform(data_x,data_y)
            supports = model.get_support()
        else:
            model = SelectPercentile(method,p)
            res = model.fit_transform(data_x,data_y)
            supports = model.get_support()
        self.support_ = supports
        self.columns = columns[supports]
        return res
    
    def wrapper_select(self,data_x,data_y,n,estimator):
        columns = data_x.columns
        model = RFE(estimator=estimator,n_features_to_select=n)
        res = model.fit_transform(data_x,data_y)
        supports = model.get_support() #标识被选择的特征在原数据中的位置
        self.supports = supports
        self.columns = columns[supports]
        return res
    
    def embedded_select(self,data_x,data_y,estimator,threshold=None):
        '''
        threshold : string, float, optional default None
        The threshold value to use for feature selection. Features whose importance is greater or
        equal are kept while the others are discarded. If “median” (resp. “mean”), then the 
        threshold value is the median (resp. the mean) of the feature importances. 
        A scaling factor (e.g., “1.25*mean”) may also be used. If None and if the estimator
        has a parameter penalty set to l1, either explicitly or implicitly (e.g, Lasso),
        the threshold used is 1e-5. Otherwise, “mean” is used by default.
        '''
        columns = data_x.columns
        model = SelectFromModel(estimator=estimator,prefit=False,threshold=threshold)
        res = model.fit_transform(data_x,data_y)
        supports = model.get_support()
        self.supports = supports
        self.columns = columns[supports]
        return res


# In[28]:



# 选择最佳特征比例
# #############################################################################
# Plot the cross-validation score as a function of percentile of features
def feature_selection_params_xgboost():
    score_means = list()
    score_stds = list()
    importance_list = [0.5,0.6,0.7,0.8,0.9,1]
    model = XGBClassifier()
    featureSelect = FeatureSelection()
    for importance in importance_list:
        lgbm_res = featureSelect.identify_importance_lgbm(X_train,y_train,p_importance=importance)

        this_scores = cross_val_score(model, lgbm_res, y_train, cv=5, n_jobs=-1)
        score_means.append(this_scores.mean())
        score_stds.append(this_scores.std())
    plt.errorbar(importance_list, score_means, np.array(score_stds))
    plt.title('Performance of the p_importance of features selected')
    plt.xlabel('importance')
    plt.ylabel('Prediction rate')
    plt.axis('tight')
    plt.show()


# In[29]:



# 选择最佳特征比例
# #############################################################################
# Plot the cross-validation score as a function of percentile of features
def feature_selection_params_randomforest():
    score_means = list()
    score_stds = list()
    importance_list = [0.5,0.6,0.7,0.8,0.9,1]
    model = RandomForestClassifier()
    featureSelect = FeatureSelection()
    for importance in importance_list:
        lgbm_res = featureSelect.identify_importance_lgbm(X_train,y_train,p_importance=importance)

        this_scores = cross_val_score(model, lgbm_res, y_train, cv=5, n_jobs=-1)
        score_means.append(this_scores.mean())
        score_stds.append(this_scores.std())
    plt.errorbar(importance_list, score_means, np.array(score_stds))
    plt.title('Performance of the p_importance of features selected')
    plt.xlabel('importance')
    plt.ylabel('Prediction rate')
    plt.axis('tight')
    plt.show()
    


# 通过结果观察，p_importance=0.9时效果最好

# In[30]:


featureSelect = FeatureSelection()

lgbm_feature_select = featureSelect.identify_importance_lgbm(X_train,y_train,p_importance=0.9)

print(len(featureSelect.columns))
len(X_train.columns)


# # 算法检验

# 随机森林

# In[31]:


rf_model = RandomForestClassifier()
model_params = {'n_estimators':range(4,12,3),'max_depth':range(3,8,2),'min_samples_split':range(20,300,50)}
rf_grid_serach_model = GridSearchCV(estimator=rf_model,param_grid=model_params)
rf_grid_serach_model.fit(lgbm_feature_select,y_train)
print(rf_grid_serach_model.best_score_)
print(rf_grid_serach_model.best_params_)


# In[32]:


rf_model = RandomForestClassifier()
model_params = {'n_estimators':range(3,6),'max_depth':range(2,5),'min_samples_split':range(230,300,20)}
rf_grid_serach_model = GridSearchCV(estimator=rf_model,param_grid=model_params)
rf_grid_serach_model.fit(lgbm_feature_select,y_train)
print(rf_grid_serach_model.best_score_)
print(rf_grid_serach_model.best_params_)


# In[33]:


#测试集预测
def test_prediction_score(test_data,select_factors,model):
    '''
    input:
    test_data:dic,keys为时间，values为dataframe,index为样本，columns为因子
    select_factors:特征选择的因子
    model：训练好的模型
    output:
    
    '''
    test_data_keys = list(test_data.keys())
    accuracy_score_list = []
    roc_auc_score_list = []
    date_list = []
    for date in test_data_keys:
        test_d = test_data[date]
        if len(test_d) == 0:
            break
        y_test = test_d['label']
        x_test = test_d.copy()
        del x_test['pchg']
        del x_test['label']
        x_test_featurn_select = x_test[select_factors]
        prediction = model.predict(x_test_featurn_select)
        accuracy_score_res = accuracy_score(y_test,prediction)
        roc_auc_score_res = roc_auc_score(y_test,prediction)
        accuracy_score_list.append(accuracy_score_res)
        roc_auc_score_list.append(roc_auc_score_res)
        date_list.append(date)
    score_df = pd.DataFrame(accuracy_score_list,index=date_list,columns=['accuracy'])
    score_df['roc_auc'] = roc_auc_score_list
    return score_df
select_factors = featureSelect.columns
test_model = rf_grid_serach_model
score_df = test_prediction_score(test_data,select_factors,test_model)
print(score_df.mean())


# xgboost算法
# 
# 第一次执行：n_estimators：12，max_depth：3

# In[34]:


def xgboost_model(x_train,y_train):
    st = time.time()
    xgboost_model = XGBClassifier()
    model_params = {'n_estimators':range(6,14,2),'max_depth':range(3,8,2)}
    model = GridSearchCV(estimator=xgboost_model,param_grid=model_params,cv=5)
    model.fit(x_train,y_train)
    et = time.time()
    delta = (et - st) / 60
    print(model.best_score_)
    print(model.best_params_)
    print('用时：',delta)
    return model
xgboost_model = xgboost_model(lgbm_feature_select,y_train)
    


# In[35]:


xgboost_score_df = test_prediction_score(test_data,select_factors,xgboost_model)
print(xgboost_score_df.mean())


# #神经网络

# In[36]:


y_test.shape


# In[37]:



def nn_model(x_train,y_train,x_test,y_test):
    keep_prob = 0.5
    LR = 0.1
    l1_num = 6
    l2_num = 5
    batch_size = 10
    times = 1000

    v1 = np.array(y_train.values)
    train_y_a = v1.reshape((-1,1))
    v2 = np.array(y_test.values)
    test_y_a = v2.reshape((-1,1))

    n_features = len(x_train.columns)
    print(n_features)
    x = tf.placeholder(tf.float32,[None,n_features])
    y = tf.placeholder(tf.float32,[None,1])

    def weights(shape):
        weights = tf.Variable(tf.truncated_normal(shape,stddev=0.1))
        return weights
    def biases(shape):
        biases = tf.zeros(shape) + 0.1
        return tf.Variable(biases)

    weights1 = weights([n_features,l1_num])
    biases1 = biases([1,l1_num])
    w_plus_b1 = tf.matmul(x,weights1) + biases1
    l1 = tf.nn.relu(w_plus_b1)
    l1_dropout = tf.nn.dropout(l1,keep_prob=keep_prob)

    weight2 = weights([l1_num,l2_num])
    biases2 = biases([l2_num])
    w_plus_b2 = tf.matmul(l1_dropout,weight2) + biases2
    l2 = tf.nn.relu(w_plus_b2)
    l2_dropout = tf.nn.dropout(l2,keep_prob=keep_prob)

    weight3 = weights([l2_num,1])
    biases3 = biases([1])
    w_plus_b3 = tf.matmul(l2_dropout,weight3) + biases3
    l3 = tf.nn.relu(w_plus_b3)
    res = tf.nn.sigmoid(l3)

    loss = tf.reduce_mean(tf.square(y - res))
    train_steps = tf.train.AdadeltaOptimizer(LR).minimize(loss)

    initialize = tf.global_variables_initializer()

    with tf.Session() as sess:
        sess.run(initialize)
        for batch in range(batch_size):
            for time in range(times):
                sess.run(train_steps,feed_dict={x:x_train,y:train_y_a})
            accuracy = sess.run(loss,feed_dict={x:x_train,y:train_y_a})
            accuracy_test = sess.run(loss,feed_dict={x:x_test,y:test_y_a})
            print('train loss is '+ str(batch) + ': '+ str(accuracy))
            print('test loss is' + str(accuracy_test))
x_test_feature_select = x_test[featureSelect.columns]   
print(len(lgbm_feature_select.columns))
nn_model(lgbm_feature_select,y_train,x_test_feature_select,y_test)   


# In[ ]:




