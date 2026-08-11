#!/usr/bin/env python
# coding: utf-8

# In[48]:


from myTT import *  # 导入myTT库
from jqdata import *
olderr = np.seterr(all='ignore')  # 抑制numpy的一些警告信息


# 以688286.XSHG 敏芯股份为例，该股票在2011年11月1日，出过“飞鹰优化”选股信号。

# ## 1. 取数
# - **取数的时候，必须保证数据的长度**。分析一下公式用到的数据有多长，比如“飞鹰优化”公式，里面有MA(CLOSE, 120)，那说明最少需要120天的数据。然后，把估计出来的数据长度再加上30。所以，本例取数150day。
# - **将取出的数据转化为数组**。比如`CLOSE = h['close'].values`

# In[49]:


h = attribute_history('688286.XSHG',150, '1d', ['close', 'high', 'low'])

CLOSE = h['close'].values
HIGH = h['high'].values
LOW = h['low'].values


# ## 2. 整理通达信公式
# 通达信公式需要整理，具体包括如下8个方面：
# - 过长的语句拆分一下
# - <font color = red> := 以及 : 等赋值语句，统统改为= </font>
# - AND 改为 & 
# - OR 改为 | 
# - 逻辑判断 = 改为 ==
# - 简写的，写全了，例如：C -> CLOSE
# - 每行结束;可以去掉，也可以保留
# - 适当加括号
# 
# 具体可以像本教程这样，在“研究”里面实验，确保没有书写错误。

# In[50]:


# 整理之后，Python可以识别的通达信公式
VAR1 = CLOSE / MA(CLOSE, 40) * 100 < 78;
VAR2 = CLOSE / MA(CLOSE, 60) * 100 < 74;
VAR3 = HIGH > LOW * 1.051;
VAR4 = VAR3 & (COUNT(VAR3, 5) > 1);
TYP = (HIGH + LOW + CLOSE) / 3;
CCI = (TYP - MA(TYP, 14)) / (0.015 * AVEDEV(TYP, 14));
T1 = (MA(CLOSE, 27) > 1.169*CLOSE) & (MA(CLOSE, 17) > 1.158*CLOSE);
T2 = (CLOSE < MA(CLOSE, 120)) & (MA(CLOSE, 60) < MA(CLOSE, 120)) & (MA(CLOSE, 60) > MA(CLOSE, 30)) & (CCI > -210);
FYYH = VAR4 & (VAR1 | VAR2) & T1 & T2;
XG = BARSLASTCOUNT(FYYH) == 1;


# ## 3. 处理计算结果

# In[51]:


h['xg'] = XG  # 信号回写DataFrame


# In[52]:


h[h['xg']]  # 出信号的地方


# 结果表明，myTT准确地计算出来，出信号的位置，是2021-11-1，与通达信相符
# ![Img]( https://image.joinquant.com/cb70e463e59b5d81f98a4f55f92b563f) 

# In[ ]:




