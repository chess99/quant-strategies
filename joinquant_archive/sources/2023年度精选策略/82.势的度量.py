#!/usr/bin/env python
# coding: utf-8

# In[1]:


from jqdata import *

import pandas as pd
import numpy as np

from scipy.signal import argrelextrema, argrelmax, argrelmin


# ## 一、收盘价序列(pd.Series)的标准化：三种模式
# 
# 其中第三种模式：融合收盘价单调性和5周期均线的标准化，与研报算法完全不同，但效果一致，且本算法极其简练，还处理了研报中没有考虑的问题，比如收盘价等于均线。

# In[2]:


def normalize_monotone(close_ser: pd.Series) -> np.ndarray:
    """基于收盘价单调性的标准化"""
    sign = close_ser.pct_change().apply(np.sign)

    std_closes = sign.cumsum().fillna(0).values

    return std_closes


def normalize_moving_average(close_ser: pd.Series, window: int = 5) -> np.ndarray:
    """基于5周期均线(MA5)的标准化"""
    size = len(close_ser)
    if size < window:
        raise ValueError('输入数据长度小于窗口期')

    ma = close_ser.rolling(window).mean()
    sign = (close_ser - ma).apply(np.sign)
    std_closes = sign.cumsum().fillna(0).values

    return std_closes


def normalize_compound(close_ser: pd.Series, window: int = 5) -> np.ndarray:
    """融合收盘价单调性和5周期均线的标准化"""
    size = len(close_ser)
    if size < window:
        raise ValueError('输入数据长度小于窗口期')

    sign_monotone = close_ser.pct_change().apply(np.sign)

    ma = close_ser.rolling(window).mean()
    sign_ma = (close_ser - ma).apply(np.sign)

    # 处理特殊情况：平盘时，sign_monotone值为0，导致与MA平均时，出现0.5
    sign_monotone[sign_monotone == 0] = sign_ma[sign_monotone == 0] * -1
    # 处理特殊情况：Close恰恰等于MA时，sign_ma值为0，导致与monotone平均时，出现0.5
    sign_ma[sign_ma == 0] = sign_monotone[sign_ma == 0]

    sign_compound = (sign_monotone + sign_ma) / 2  # 简单平均
    std_closes = sign_compound.cumsum().fillna(0).values

    return std_closes


# ## 二、势的度量：三种模式
# ### 2.1 基于连续波段的势

# In[3]:


def continuous_score(x: np.ndarray) -> float:
    """基于连续波段的势"""

    # 拐点：起点0/极低点/极高点/终点len(x)-1，合并为一个数组，然后排序
    points = np.concatenate(([0], argrelextrema(x, np.less)[0], argrelextrema(x, np.greater)[0], [len(x) - 1]))
    points = np.sort(points)

    # 势trend强度
    trend = 0
    for i in range(1, len(points)):
        trend += (x[points[i]] - x[points[i - 1]]) ** 2

    return trend


# ### 2.2 基于绝对波动区间的势

# 探索绝对波动区间的势算法时，过程比较艰难，记录如下：
# 
# #### 2.2.1） 严格照本宣科写的绝对势函数
# 
# 一开始，严格按照研报P.9-10页的定义去写算法，研报这部分试图用数学公式描述其算法，描述的晦涩难懂，看了半天，终于写出来如下函数，函数区分为三种情形分别处理，用到了`递归调用`，很复杂。

# In[4]:


# 废弃的绝对势计算函数
def absolute_score2(x):
    max_ps = argrelmax(x)[0]  # 最大点s
    min_ps = argrelmin(x)[0]  # 最小点s
    if max_ps.size or min_ps.size:  # 有最大 和（或）最小
        if max_ps.size and min_ps.size:  # 既有最大，又有最小，N字形
            max_p = max_ps[0]
            min_p = min_ps[0]
            #
            start = min(max_p, min_p)
            end = max(max_p, min_p)
            #
            trend = (x[end] - x[start])** 2

        else:  # 只有最大，或者只有最小，V字形
            if max_ps.size:  # 只有最大
                start = end = max_ps[0]
            else:  # 只有最小
                start = end = min_ps[0]
            #
            trend = 0
        # 分割为左右两个部分
        points_left = x[:start + 1]  # 左边部分
        l_trend = absolute_score2(points_left)
        #
        points_right = x[end:]  # 右半部分
        r_trend = absolute_score2(points_right)
        return trend + l_trend + r_trend

    else:  # 没有最大，也没有最小，直线型
        trend = (x[-1] - x[0]) ** 2
        return trend


# 在测试函数正确性的时候，使用了研报P.11图13中的6个例子，一测，神奇地发现: `continuous_score`函数和`absolute_score2`函数计算出来的**势完全相同！明明算法迥异**啊。

# In[5]:


test_array = np.array([
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    [0, 1, 2, 3, 4, 5, 4, 5, 6, 7, 8],
    [0, 1, 2, 3, 4, 5, 6, 5, 4, 3, 2],
    [0, 1, 2, 3, 2, 3, 4, 3, 4, 5, 6],
    [0, 1, 2, 1, 0, 1, 2, 1, 0, 1, 2],
    [0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
])

for i in range(len(test_array)):
    x = test_array[i]
    nc, na = continuous_score(x), absolute_score2(x)
    print(x, '(' + chr(97+i) + ')','continuous:', nc, 'absolute2:', na)


# 与研报结果相对比，其中(b)和(d)对不上。研报中P.11页中b、d的绝对波动区间的势分别是64、36。
# 
# 反复思考、检查，觉得自己`absolute_score2`算法没有错。但b、d就是对不上，苦苦查找原因。
# 
# 好在了解`argrelextrema，argrelmax, argrelmin`这三个函数的特性，知道其结果是不包括两个端点的，一看b、d，果然，最大值和最小值是在两端！这种情况下，直接用两个端点计算势就可以了。

# #### 2.2.2） 一个极其简洁的绝对势函数
# 
# 基于以上发现，写出来一个极其简洁的绝对波动区间势函数（与P11图13的结果对上了）：

# In[6]:


def absolute_score(x: np.ndarray) -> float:
    """基于绝对波动区间的势"""

    # 如果最大最小值在起点和终点
    if x.max() > x[1:-1].max() and x.min() <x[1:-1].min():
        trend = (x[-1] - x[0]) ** 2
    else:
        trend = continuous_score(x)

    return trend


# In[7]:


# 验证
test_array = np.array([
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    [0, 1, 2, 3, 4, 5, 4, 5, 6, 7, 8],
    [0, 1, 2, 3, 4, 5, 6, 5, 4, 3, 2],
    [0, 1, 2, 3, 2, 3, 4, 3, 4, 5, 6],
    [0, 1, 2, 1, 0, 1, 2, 1, 0, 1, 2],
    [0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
])
#
for i in range(len(test_array)):
    x = test_array[i]
    nc, na = continuous_score(x), absolute_score(x)
    print('(' + chr(97+i) + ')',x, 'continuous:', nc, 'absolute:', na)


# ### 2.3 势的终极定义：基于绝对波动区间与连续波段的势
# 
# 合理的势应该是连续波段定义的势与绝对波动区间的势取二者较大的值，并除以N的3/2次方予以修正。
# $$
# T=\frac{max(连续波段势, 绝对波动区间势)}{N^{\frac{3}{2}}}
# $$
# 阅读研报后文，可以发现N并不等于$len(x)$，而是等于$len(x)-1$
# 
# 由于`绝对势永远是大于连续势`的，故研报取$max$没有意义，直接采用绝对势。故此，可以将势的终极定义写成如下函数：

# In[8]:


def ultimate_score(x: np.ndarray) -> float:
    """终极的势"""

    trend = absolute_score(x)

    trend = trend / ((len(x) - 1) ** (3 / 2))

    return trend


# In[9]:


# 验证
# 验证时，使用了研报P.22图35的数据，本算法计算结果与研报图35完全一致。
test_array = np.array([
    [5, 4, 3, 2, 1, 0],
    [3, 4, 3, 2, 1, 0],
    [4, 3, 2, 2, 1, 0],
    [1, 2, 3, 2, 1, 0],
    [2, 3, 2, 2, 1, 0],
    [3, 2, 2, 1, 1, 0]
])

for i in range(len(test_array)):
    x = test_array[i]
    nu = round(ultimate_score(x),2)
    print(x, 'ultimate:', nu)


# ### 2.4 势计算的代码合集
# 
# 上面代码较为零散，最后将之收录到一起。

# In[10]:


# ----------------------------------------------------------
# 势的度量：三种模式
# ----------------------------------------------------------
def continuous_score(x: np.ndarray) -> float:
    """基于连续波段的势"""

    # 拐点：起点0/极低点/极高点/终点len(x)-1，合并为一个数组，然后排序
    points = np.sort(np.concatenate(([0], argrelextrema(x, np.less)[0], argrelextrema(x, np.greater)[0], [len(x) - 1])))

    # 势trend
    trend = 0
    for i in range(1, len(points)):
        trend += (x[points[i]] - x[points[i - 1]]) ** 2

    return trend


def absolute_score(x: np.ndarray) -> float:
    """基于绝对波动区间的势"""

    # 如果最大最小值在起点和终点
    if x.max() > x[1:-1].max() and x.min() < x[1:-1].min():
        trend = (x[-1] - x[0]) ** 2
    else:
        trend = continuous_score(x)

    return trend


def ultimate_score(x: np.ndarray) -> float:
    """终极的势"""

    trend = absolute_score(x)

    trend = trend / ((len(x) - 1) ** (3 / 2))

    return trend


# ## 三、应用举例

# 应用上面的势函数，比较一下2021-3-8，湖北宜化、兴发集团和云天化，看看谁的势头更猛些。

# In[11]:


stock_list = ['000422.XSHE','600141.XSHG','600096.XSHG']  # 湖北宜化、兴发集团、云天化

h = get_price(stock_list, end_date='2021-3-8', 
              fields='close', count=30, panel=False
             ).pivot(index='time',columns='code', values='close')
h2 = h.apply(normalize_compound)
s_score = h2.apply(ultimate_score, raw=True)


# In[12]:


s_score.sort_values(ascending=False)


# In[ ]:




