#!/usr/bin/env python
# coding: utf-8

# In[1]:


import numpy as np
import pandas as pd
import graphviz
from scipy.stats import rankdata
import pickle
import scipy.stats as stats
from gplearn import genetic
from gplearn.functions import make_function
from gplearn.genetic import SymbolicTransformer, SymbolicRegressor
from gplearn.fitness import make_fitness

from sklearn.utils import check_random_state
from sklearn.model_selection import train_test_split


# In[2]:


fields = ['open', 'high', 'low', 'avg', 'pre_close', 'close','volume']
length = []

total_data = pd.read_csv('C:/Users/Dell/Desktop/金工研报/stock_data.csv')
total_data.index = total_data.date
total_data = total_data.iloc[:,1:]

#total_data = total_data.iloc[:80000,:]

stock_list = total_data.stock_code.values.tolist()

length =  []
num = 1
for i in range(len(stock_list)-1):
    if stock_list[i+1] == stock_list[i]:
        if i == len(stock_list)-2:
            length.append(num)
            break
        num+=1
    else:
        
        length.append(num)
        num = 1
        
# ------------------------------       
target = total_data['pct10'].values

data = total_data[fields]
data['3'] = 3
data['5'] = 5
data['6']=6
data['8'] = 8
data['10'] = 10
data['12'] = 12
data['15'] = 15
data['20']=20
fields = fields + ['3','5','6','8','10','12','15','20']

X_train = np.nan_to_num(data[:].values)
#X_test = data[-test_num:]
y_train = np.nan_to_num(target)
del data
del target


# In[3]:


init_function = ['add', 'sub', 'mul', 'div','sqrt', 'log','inv','sin','max','min']

import scipy.stats as stats


def _my_metric(y, y_pred, w):
    x1 = pd.Series(y.flatten() )
    x2 = pd.Series(y_pred.flatten()) 
    df = pd.concat([x1,x2],axis=1)
    df.columns = ['y','y_pred']
    df.sort_values(by = 'y_pred',ascending = True,inplace = True)
    num = int(len(df)*0.1)
    #df.fillna(0, inplace=True)
    
    y_high = df["y"][-num:]
    y_low = df["y"][:num]
    #value = y_high.sum() - y_low.sum()
    value = y_high.mean()/y_low.mean()
    return value

my_metric = make_fitness(function=_my_metric, greater_is_better=True)


# In[4]:


def _rolling_rank(data):
    value = rankdata(data)[-1]
    
    return value

def _rolling_prod(data):
    
    return np.prod(data)

def _cube(data):
    return np.square(data)*data

def _square(data):
    return np.square(data)




# In[5]:


def _delta(data):
    value = np.diff(data.flatten())
    value = np.append(0, value)

    return value

def _delay(data):
    period=1
    value = pd.Series(data.flatten()).shift(1)
    value = np.nan_to_num(value)
    
    return value


'''
def _scale(data):
    k=1
    data = pd.Series(data.flatten())
    value = data.mul(1).div(np.abs(data).sum())
    value = np.nan_to_num(value)
    
    return value
'''

        
        
def _corr(data1,data2,n):
    
    with np.errstate(divide='ignore', invalid='ignore'):

            
        try:
            if n[0] == n[1] and n[1] ==n[2]:
                window  = n[0]

                x1 = pd.Series(data1.flatten())
                x2 = pd.Series(data2.flatten())

                df = pd.concat([x1,x2],axis=1)
                temp = pd.Series()
                for i in range(len(df)):
                    if i<=window-2:
                        temp[str(i)] = np.nan
                    else:
                        df2 = df.iloc[i-window+1:i,:]
                        temp[str(i)] = df2.corr('spearman').iloc[1,0]
                return np.nan_to_num(temp)
            else:
                return np.zeros(data1.shape[0])
            
        except:
            return np.zeros(data1.shape[0])



def _ts_sum(data,n):

    with np.errstate(divide='ignore', invalid='ignore'):

        try:
            if n[0] == n[1] and n[1] ==n[2]:
                window  = n[0]
    
                value = np.array(pd.Series(data.flatten()).rolling(window).sum().tolist())
                value = np.nan_to_num(value)
    
                return value
            else:
                return np.zeros(data.shape[0])

        except:
            return np.zeros(data.shape[0])
        


def _sma(data,n):
    with np.errstate(divide='ignore', invalid='ignore'):

        try:    
            if n[0] == n[1] and n[1] ==n[2]:
                window  = n[0]
                
                value = np.array(pd.Series(data.flatten()).rolling(window).mean().tolist())
                value = np.nan_to_num(value)
    
                return value
            else:
                return np.zeros(data.shape[0])
              
        except:
            return np.zeros(data.shape[0])

def _stddev(data,n):   
    with np.errstate(divide='ignore', invalid='ignore'):

        try:    
            if n[0] == n[1] and n[1] ==n[2]:
                window  = int(np.mean(n))
                
                value = np.array(pd.Series(data.flatten()).rolling(window).std().tolist())
                value = np.nan_to_num(value)
    
                return value
            else:
                return np.zeros(data.shape[0])
                
        except:
            return np.zeros(data.shape[0])

def _ts_rank(data,n):
    
    with np.errstate(divide='ignore', invalid='ignore'):

        try:
            if n[0] == n[1] and n[1] ==n[2]:        
                value = np.array(pd.Series(data.flatten()).rolling(window).apply(_rolling_rank).tolist())
                value = np.nan_to_num(value)

                return value
            else:
                return np.zeros(data.shape[0])    
        except:
            return np.zeros(data.shape[0])


ts_rank = make_function(function=_ts_rank, name='ts_rank', arity=2)



def _ts_argmin(data,n):

    try:
        if n[0] == n[1] and n[1] ==n[2]:
            window=n[0]
            value = pd.Series(data.flatten()).rolling(window).apply(np.argmin) + 1 
            value = np.nan_to_num(value)
            return value
        else:
            return np.zeros(data.shape[0])  
    except:
        return np.zeros(data.shape[0])


def _ts_argmax(data,n):
    with np.errstate(divide='ignore', invalid='ignore'):
        try:
            if n[0] == n[1] and n[1] ==n[2]:
                window=n[0]
                value = pd.Series(data.flatten()).rolling(window).apply(np.argmax) + 1 
                value = np.nan_to_num(value)
                return value
            else:
                return np.zeros(data.shape[0])
        except:
            return np.zeros(data.shape[0])
        
def _ts_min(data,n):
    with np.errstate(divide='ignore', invalid='ignore'):
        
        try:
            if n[0] == n[1] and n[1] ==n[2]:
                window  = n[0]
                #window  = int(np.mean(n))
                value = np.array(pd.Series(data.flatten()).rolling(window).min().tolist())
                value = np.nan_to_num(value)
    
                return value
            else:
                return np.zeros(data.shape[0])
                
        except:
            return np.zeros(data.shape[0])  
        
def _ts_max(data,n):
    with np.errstate(divide='ignore', invalid='ignore'):
        
        try:
            if n[0] == n[1] and n[1] ==n[2]:
                window  = n[0]
    
                value = np.array(pd.Series(data.flatten()).rolling(window).max().tolist())
                value = np.nan_to_num(value)
    
                return value
            else:
                return np.zeros(data.shape[0])
         
                
        except:
            return np.zeros(data.shape[0])  
        
def _ts_argmaxmin(data,n):
    return _ts_argmax(data,n) - _ts_argmin(data,n)


# In[6]:


stddev = make_function(function=_stddev, name='stddev', arity=2)
ts_sum = make_function(function=_ts_sum, name='ts_sum', arity=2)


# In[7]:


ts_sum = make_function(function=_ts_sum, name='ts_sum', arity=2)
stddev = make_function(function=_stddev, name='stddev', arity=2)


# In[8]:


corr = make_function(function=_corr, name='corr', arity=3)#     


# In[9]:


#ts_min = make_function(function=_ts_min, name='ts_min', arity=2)

delta = make_function(function=_delta, name='delta', arity=1)
delay = make_function(function=_delay, name='delay', arity=1)
sma = make_function(function=_sma, name='sma', arity=2)

cube = make_function(function=_cube, name='cube', arity=1)
square = make_function(function=_square, name='square', arity=1)


# In[10]:


ts_argmaxmin = make_function(function=_ts_argmaxmin, name='ts_argmaxmin', arity=2)

ts_argmax = make_function(function=_ts_argmax, name='ts_argmax', arity=2)
ts_argmin = make_function(function=_ts_argmin, name='ts_argmin', arity=2)


# In[11]:


ts_min = make_function(function=_ts_min, name='ts_min', arity=2)
   
ts_max = make_function(function=_ts_max, name='ts_max', arity=2)


# In[12]:


user_function = [square,cube,delta, delay, ts_argmax ,sma,stddev, ts_argmin, ts_max,ts_min,ts_sum,ts_rank,ts_argmaxmin,corr 
                 ]


# In[25]:


function_set = init_function + user_function
metric = my_metric
population_size = 3000
generations = 3
random_state=5
est_gp = SymbolicTransformer(
                            feature_names=fields, 
                            function_set=function_set,
                            generations=generations,
                            metric=metric,#'spearman'秩相关系数
                            population_size=population_size,
                            tournament_size=30, 
                            random_state=random_state,
                            verbose=2,
                            parsimony_coefficient=0.0001,
                            p_crossover = 0.4,
                            p_subtree_mutation = 0.01,
                            p_hoist_mutation = 0,
                            p_point_mutation = 0.01,
                            p_point_replace = 0.4,
                            n_jobs = 6
                         )
###------------set 训练集的为空值---------
num_set_y_nan = 0
for i in length:
    num_set_y_nan = i + num_set_y_nan
    try:
        y_train[num_set_y_nan] = np.nan
    except:
        break

X_train = np.nan_to_num(X_train)
y_train = np.nan_to_num(y_train)

est_gp.fit(X_train, y_train)


# In[26]:


best_programs = est_gp._best_programs
best_programs_dict = {}

for p in best_programs:
    factor_name = 'alpha_' + str(best_programs.index(p) + 1)
    best_programs_dict[factor_name] = {'fitness':p.fitness_, 'expression':str(p), 'depth':p.depth_, 'length':p.length_}
     
best_programs_dict = pd.DataFrame(best_programs_dict).T
best_programs_dict = best_programs_dict.sort_values(by='fitness')
best_programs_dict 


# In[27]:


def alpha_factor_graph(num):
    # 打印指定num的表达式图

    factor = best_programs[num-1]
    print(factor)
    print('fitness: {0}, depth: {1}, length: {2}'.format(factor.fitness_, factor.depth_, factor.length_))

    dot_data = factor.export_graphviz()
    graph = graphviz.Source(dot_data)
    graph.render('images/alpha_factor_graph', format='png', cleanup=True)
    
    return graph

graph1 = alpha_factor_graph(1)
graph1


# In[29]:


import jqdatasdk as jq
import jqfactor_analyzer as ja

jq.auth('账号', 'password')


stock_list = jq.get_index_stocks('000906.XSHG')


# In[31]:


data = jq.get_price(stock_list, end_date='2020-03-20', 
frequency='daily', fields=['high'], count=30)
df1 = 12/data['high']


# In[35]:


np.square()


# In[39]:


def alpha2(stock_list,date1,N):
    data = jq.get_price(stock_list, end_date=date1, 
    frequency='daily', fields=['high'], count=N)
    df1 = 12/data['high']
    df2 = pd.DataFrame(np.diff(df1,axis=0),index = df1.iloc[1:].index,columns = df1.columns)
    
    return df2*df2


# In[40]:


factor = alpha2(stock_list,'2020-03-20',500)


# In[41]:


factor


# In[43]:


periods=(5, 10)
# 设置分层数量
quantiles=10

far = ja.analyze_factor(factor=factor, 
                        weight_method='avg', 
                        industry='jq_l1', 
                        quantiles=quantiles, 

                        periods=periods,
                        max_loss=0.4)


# 生成统计图表
far.create_full_tear_sheet(
    demeaned=False, group_adjust=False, by_group=False,
    turnover_periods=None, avgretplot=(5, 15), std_bar=False
)


# In[ ]:





# In[ ]:





# In[ ]:





# In[ ]:





# In[ ]:


stock_list = jq.get_index_stocks('000906.XSHG')

def alpha2(stock_list,date1,N):
    data = jq.get_price(stock_list, end_date=date1, 
    frequency='daily', fields=['open','volume'], count=N)
    df1 = data['open'].rank(axis='columns')
    df2 = data['volume'].rank(axis='columns')
    return sigmoid(df1/df2)

alpha2(stock_list,'2020-03-12',5)


factor23 = alpha23(stock_list,'2020-03-12',700)

periods=(5, 10,20)

