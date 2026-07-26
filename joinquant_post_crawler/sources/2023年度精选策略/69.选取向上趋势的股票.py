#!/usr/bin/env python
# coding: utf-8

# In[2]:


import numpy as np 
import pylab as pl
import matplotlib.pyplot as plt
import scipy.signal as signal
from sklearn.linear_model import LinearRegression

#dfs=get_all_securities(types=['stock'], date=end_date)

df=get_price('000858.XSHE', start_date='2020-09-09', end_date='2020-12-20', frequency='daily', fields=["close"], skip_paused=False, fq='pre')


cl=df['close'].tolist()


x=np.array(df['close'].tolist())

plt.figure(figsize=(16,4))
plt.plot(np.arange(len(x)),x)
#print (x[signal.argrelextrema(x, np.greater)])
#print (signal.argrelextrema(x, np.greater))

#找出极大值画“o”
plt.plot(signal.argrelextrema(x,np.greater)[0],x[signal.argrelextrema(x, np.greater)],'o')

#找出极小值画“X”
plt.plot(signal.argrelextrema(x,np.less)[0],x[signal.argrelextrema(x, np.less)],'X')

plt.show()



Y=x[signal.argrelextrema(x, np.greater)]
X=range(len(Y))
#转换成numpy的ndarray数据格式，n行1列,LinearRegression需要列格式数据，如下：
X_train = np.array(X).reshape((len(X), 1))
Y_train = np.array(Y).reshape((len(Y), 1))
#新建一个线性回归模型，并把数据放进去对模型进行训练
lineModel = LinearRegression()
lineModel.fit(X_train, Y_train)

#用训练后的模型，进行预测
Y_predict = lineModel.predict(X_train)

#coef_是系数，intercept_是截距，拟合的直线是y=ax+b
a = lineModel.coef_[0][0]
b = lineModel.intercept_[0]
print("y=%.4f*x+%.4f" % (a,b))

#对回归模型进行评分，这里简单使用训练集进行评分，实际很多时候用其他的测试集进行评分
print("得分", lineModel.score(X_train, Y_train))

#简单画图显示
plt.scatter(X, Y, c="blue")
plt.plot(X_train,Y_predict, c="red")
plt.show()







# In[4]:


import numpy as np 
import pylab as pl
import matplotlib.pyplot as plt
import scipy.signal as signal
from sklearn.linear_model import LinearRegression

print('-----------start------------')
sstart_date='2020-06-21'
send_date='2020-12-21'
i=0
dfs=get_all_securities(types=['stock'], date=send_date)
#dfs=get_index_stocks("000300.XSHG", date='2020-12-20')
for s in dfs.index:
    df=get_price(s, start_date=sstart_date, end_date=send_date, frequency='daily', fields=["close"], skip_paused=False, fq='pre')

    #print(df['low'].tolist())
    cl=df['close'].tolist()
    if len(cl)<=120:
        continue
    x=np.array(df['close'].tolist())


    Y=x[signal.argrelextrema(x, np.less_equal)]
    if len(Y)<=0:
        #print("------------"+s+"-------------------")
        continue
    X=range(len(Y))
    #转换成numpy的ndarray数据格式，n行1列,LinearRegression需要列格式数据，如下：
    X_train = np.array(X).reshape((len(X), 1))
    Y_train = np.array(Y).reshape((len(Y), 1))
    #新建一个线性回归模型，并把数据放进去对模型进行训练
    lineModel = LinearRegression()
    lineModel.fit(X_train, Y_train)

    #用训练后的模型，进行预测
    Y_predict = lineModel.predict(X_train)

    #coef_是系数，intercept_是截距
    a1 = lineModel.coef_[0][0]
    b = lineModel.intercept_[0]
    #print("y=%.4f*x+%.4f" % (a1,b))
    if a1>2:
        #print("y=%.4f*x+%.4f " % (a1,b))
        print("%s %s"%(s,dfs.loc[s]['display_name']))
        i=i+1
    #对回归模型进行评分，这里简单使用训练集进行评分，实际很多时候用其他的测试集进行评分
    #print("得分", lineModel.score(X_train, Y_train))

print('total '+str(i)+' stocks!')
print('-------------End-------------')


# In[ ]:




