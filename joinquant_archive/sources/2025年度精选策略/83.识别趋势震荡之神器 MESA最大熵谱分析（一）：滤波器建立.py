#!/usr/bin/env python
# coding: utf-8

# # 识别趋势震荡之神器 MESA --最大熵谱分析（一）：滤波器模型建立

# ### 导入需要的Package

# In[2]:


from jqdatasdk import * 
auth('user_name','password')


# In[3]:


import matplotlib.pyplot as plt
import numpy as np
import tushare as ts
import seaborn as sns
import pandas as pd
import statsmodels.tsa.api as smt


# In[4]:


from statsmodels.tsa.ar_model import AutoReg, ar_select_order


# In[5]:


import statsmodels.api as sm
import scipy.stats as scs
from arch import arch_model


# In[6]:


from statsmodels.tsa.api import acf, pacf, graphics


# In[7]:


import math


# In[19]:


from statsmodels.tsa.stattools import adfuller as ADF


# ## 取分钟级数据，在可能的情况下尽可能取更细致的数据，避免信息丢失

# In[8]:


start_date = '2020-06-01'
end_date = '2020-07-02'


# In[9]:


df = get_price('000300.XSHG', start_date = start_date, end_date = end_date, frequency = 'minute')
df


# In[10]:


plt.plot(df['close'])


# In[11]:


df = df.reset_index()
df


# In[12]:


plt.plot(df['close'])


# ## 使用AR模型估计最大熵谱分析模型的系数，AR模型有效的前提是平稳序列

# In[20]:


ADF(df['close'])


# ### 序列不平稳，进行差分

# In[21]:


df = df.diff()
df = df.dropna()


# In[22]:


ADF(df['close'])


# ### 序列平稳，对差分数据等间隔取值，选取合适的间隔建立AR模型
# ### 每天的数据量和AR模型滞后项保持一致

# In[23]:


max_range = df.shape[0]


# In[24]:


df_40 = pd.DataFrame()
for i in range(0, max_range, 6):
    s = df.iloc[i]
    df_40 = df_40.append(s, ignore_index = True)
df_40_close = df_40['close']
df_40_close


# In[25]:


df_30 = pd.DataFrame()
for i in range(0, max_range, 8):
    s = df.iloc[i]
    df_30 = df_30.append(s, ignore_index = True)
df_30_close = df_30['close']


# In[26]:


df_20 = pd.DataFrame()
for i in range(0, max_range, 12):
    s = df.iloc[i]
    df_20 = df_20.append(s, ignore_index = True)
df_20_close = df_20['close']


# In[27]:


df_10 = pd.DataFrame()
for i in range(0, max_range, 24):
    s = df.iloc[i]
    df_10 = df_10.append(s, ignore_index = True)
df_10_close = df_10['close']


# In[28]:


plt.subplot(2, 2, 1)
plt.plot(df_10_close)
plt.subplot(2, 2, 2)
plt.plot(df_20_close)
plt.subplot(2, 2, 3)
plt.plot(df_30_close)
plt.subplot(2, 2, 4)
plt.plot(df_40_close)


# In[29]:


def ts_plot(data, lags=None,title=''):
    if not isinstance(data, pd.Series):   
        data = pd.Series(data)
    #matplotlib官方提供了五种不同的图形风格，
    #包括bmh、ggplot、dark_background、fivethirtyeight和grayscale
    with plt.style.context('ggplot'):    
        fig = plt.figure(figsize=(10, 8))
        layout = (3, 2)
        ts_ax = plt.subplot2grid(layout, (0, 0), colspan=2)
        acf_ax = plt.subplot2grid(layout, (1, 0))
        pacf_ax = plt.subplot2grid(layout, (1, 1))
        qq_ax = plt.subplot2grid(layout, (2, 0))
        pp_ax = plt.subplot2grid(layout, (2, 1))
        data.plot(ax=ts_ax)
        ts_ax.set_title(title)
        smt.graphics.plot_acf(data, lags=lags, ax=acf_ax, alpha=0.5)
        acf_ax.set_title('ACF')
        smt.graphics.plot_pacf(data, lags=lags, ax=pacf_ax, alpha=0.5)
        pacf_ax.set_title('PACF')
        sm.qqplot(data, line='s', ax=qq_ax)
        qq_ax.set_title('QQ')        
        scs.probplot(data, sparams=(data.mean(), 
                     data.std()), plot=pp_ax)
        pp_ax.set_title('PP') 
        plt.tight_layout()
    return


# In[30]:


max_lag = 10
Y_10 = df_10['close']


# In[31]:


ts_plot(Y_10,lags = max_lag,title = '10 datas per day')


# In[32]:


max_lag = 20
Y_20 = df_20['close']


# In[33]:


ts_plot(Y_20,lags = max_lag,title = '20 datas per day')


# In[34]:


max_lag = 30
Y_30 = df_30['close']


# In[35]:


ts_plot(Y_30,lags = max_lag,title = '30 datas per day')


# In[36]:


max_lag = 40
Y_40 = df_40['close']


# In[37]:


ts_plot(Y_40,lags = max_lag,title = '40 datas per day')


# In[38]:


mod = AutoReg(Y_10, 4)
res = mod.fit()
res.aic


# ### 绘制AIC图像，选取最合适的滞后项数和阶数

# In[39]:


aic_10 = []
for i in range(1, 10):
    mod = AutoReg(Y_10, i)
    res = mod.fit()
    aic_10.append(res.aic)
aic_10


# In[40]:


aic_20 = []
for i in range(1, 10):
    mod = AutoReg(Y_20, i)
    res = mod.fit()
    aic_20.append(res.aic)
aic_20


# In[41]:


aic_30 = []
for i in range(1, 10):
    mod = AutoReg(Y_30, i)
    res = mod.fit()
    aic_30.append(res.aic)
aic_30


# In[42]:


aic_40 = []
for i in range(1, 10):
    mod = AutoReg(Y_40, i)
    res = mod.fit()
    aic_40.append(res.aic)
aic_40


# In[43]:


x = range(0, 9)
y1 = aic_10
y2 = aic_20
y3 = aic_30
y4 = aic_40


# In[44]:


plt.plot(x, y1, color = 'green', label = 'AIC_10')
plt.plot(x, y2, color = 'red', label = 'AIC_20')
plt.plot(x, y3, color = 'b', label = 'AIC_30')
plt.plot(x, y4, color = 'black', label = 'AIC_40')
plt.legend()


# ### 显然滞后项为40最为合适，目测估计是AR（2）模型，（理论上ARMA（1，1）模型更好，但是无法转化为最大熵模型），接下来用statsmodel的package进行检验

# In[45]:


result = smt.AR(Y_40).fit(maxlag=40, ic='aic', trend='nc')
est_order = smt.AR(Y_40).select_order(maxlag=40, 
            ic='aic', trend='nc')
print(f'沪深300拟合AR模型的最佳滞后阶数 {est_order}')


# ### 这里显示最佳滞后阶数是1，但是如果是1，频谱密度将为一个常数，所以选择最接近的2，建立AR（2）模型

# In[46]:


mod = AutoReg(Y_40, 2)
res = mod.fit()
res.summary()


# In[47]:


phi1 = res.params[1]
phi2 = res.params[2]
phi1


# In[48]:


phi2


# ### 通过Z变换得到需要的alpha系数

# In[49]:


alpha1 = phi1
alpha2 = phi2


# In[50]:


alpha = np.array([alpha1, alpha2])
sigma = alpha.std()
sigma


# In[51]:


pi = math.pi
pi


# In[52]:


e = math.e
e


# In[53]:


np.exp(complex(1,5))


# In[54]:


f = np.linspace(0, 0.5, 1000)


# In[55]:


s = lambda f : (2*sigma)/(abs(1 - alpha1*np.exp(complex(0,-1*2*pi*f)) - alpha2*np.exp(complex(0,-4*pi*f))))**2


# In[56]:


s(0.8)-s(0.2)


# In[57]:


spectral_density = map(s, f)


# In[58]:


spectral_density = list(spectral_density)
spectral_density


# In[59]:


plt.plot(f, spectral_density)


# ## 以1为周期的偶函数，我们只取正的部分，从0到0.5，函数形状由alpha决定，alpha1比较大，是单峰，大周期，是趋势，alpha比较大，是双峰，小周期是震荡

# In[60]:


alpha1 = 0.05
alpha2 = -0.1


# In[61]:


alpha = np.array([alpha1, alpha2])
sigma = alpha.std()
sigma


# In[62]:


s = lambda f : (2*sigma)/(abs(1 - alpha1*np.exp(complex(0,-1*2*pi*f)) - alpha2*np.exp(complex(0,-4*pi*f))))**2


# In[63]:


spectral_density = map(s, f)
spectral_density = list(spectral_density)
plt.plot(f, spectral_density)


# In[66]:


max(spectral_density)


# ### 选取频谱密度最大的点作为频率

# In[69]:


max_index = spectral_density.index(max(spectral_density))


# In[70]:


f = max_index / 1000 * 0.5


# In[71]:


T = 1/f


# In[72]:


T


# # 可以直接运行的滤波器函数，输入当前时间，输出当前期货价格对应周期的大小

# In[ ]:


now = datetime.datetime.now()


# In[ ]:


def Filter(now):
    time_delta = datetime.timedelta(weeks=4, days=0, hours=0, minutes=0,  seconds=0)
    start_date = now - time_delta
    end_date = now
    df = get_price('000300.XSHG', start_date = start_date, end_date = end_date, frequency = 'minute')
    df = df.reset_index()
    df = df.diff()
    df = df.dropna()
    max_range = df.shape[0]
    df_40 = pd.DataFrame()
    for i in range(0, max_range, 6):
        s = df.iloc[i]
        df_40 = df_40.append(s, ignore_index = True)
    max_lag = 40
    Y_40 = df_40['close']
    mod = AutoReg(Y_40, 2)
    res = mod.fit()
    phi1 = res.params[1]
    phi2 = res.params[2]
    alpha1 = phi1
    alpha2 = phi2
    alpha = np.array([alpha1, alpha2])
    sigma = alpha.std()
    pi = math.pi
    f = np.linspace(0, 0.5, 1000)
    spectrum = lambda f : (2*sigma)/(abs(1 - alpha1*np.exp(complex(0,-1*2*pi*f)) - alpha2*np.exp(complex(0,-4*pi*f))))**2
    spectral_density = map(spectrum, f)
    spectral_density = list(spectral_density)
    #plt.plot(f, spectral_density) #画图
    max_index = spectral_density.index(max(spectral_density))
    f_max = max_index / 1000 * 0.5
    if (f_max == 0):
        T = math.inf
    else:
        T = 1/f_max
    return T


# In[ ]:


Filter(now)

