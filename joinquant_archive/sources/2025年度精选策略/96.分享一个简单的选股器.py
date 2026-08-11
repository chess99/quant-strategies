#!/usr/bin/env python
# coding: utf-8

# In[4]:


# 导入函数库
import math
import talib
import numpy as np
from jqdata import *
from talib import MA_Type
from functools import reduce
from jqlib.technical_analysis import *
from jqlib.alpha101 import *

# 获取近期n天大于value_list的个数
def get_bigger_than_val_counter (close, n, value_list):
    np_close = np.array (close[-n:])
    np_value = np.array (value_list[-n:])
    np_value = np_value * 0.98 # 运行向下浮动2%
    
    diff = np_close - np_value
    return sum (diff > 0)
        
# 均线
def get_ma (close, timeperiod=5):
    return talib.SMA(close, timeperiod)
    
# 获取均值
def get_avg_price (close, day:int):
    return get_ma (close, day)[-1]
    
# 获取macd技术线
def get_macd (close):
    diff, dea, macd = talib.MACDEXT(close, fastperiod=12, fastmatype=1, slowperiod=26, slowmatype=1, signalperiod=9, signalmatype=1)
    macd = macd * 2
    return diff, dea, macd

# 获取day最大价格
def get_max_price (high_values, day):
    return high_values[-day:].max()
        
# 获取最小价格
def get_min_price (low_values, day):
    return low_values[-day:].min()
    
# 单日成交量 大于该股的前5日所有成交量的2倍
def is_multiple_stocks (volume, days = 5):
    vol = volume[-1]
    
    for i in range(2, days + 2):
        if volume[-i] * 2 > vol:
            return False
    
    return True
    
# 获取波动的百分比的标准差
def get_std_percentage(var_list):
    v_array = np.array(var_list)
    
    # 获取每个单元的涨跌幅百分比
    ratio = (v_array - np.median(v_array))/np.median(v_array)
    
    # 每个单元的平方，消除负号
    ratio_p2 = ratio * ratio
    
    # 得到平均涨跌幅的平方
    ratio = ratio_p2.sum()/len(v_array)
    
    # 开方 得到平均涨跌幅
    return np.sqrt(ratio)

# 均线多头排列
def get_avg_array (avg_list):
    ratio = 0;
    count = len(avg_list)
    
    for i in range(1, count):
        if avg_list[-i-1] < avg_list[-i]:
            return 0
        ratio += (avg_list[-i-1] - avg_list[-i]) / avg_list[-i]
    
    return ratio

# 给股票评分
def get_stocks_score (tick_list, data_frame, pass_time):
    score = {}
    avg_score = {}
    
    for code in tick_list:
        high = data_frame[data_frame['code'] == code]['high'].values
        low = data_frame[data_frame['code'] == code]['low'].values
        close = data_frame[data_frame['code'] == code]['close'].values
        
        # 获取均线矩阵， 不要5日线
        avg_list = np.array([get_ma(close, 10), get_ma(close, 20),
                             get_ma(close, 30), get_ma(close, 60)])

        box_ratio = 0
        for i in range(2, 32): # 不考虑当日的影响
            box_ratio += get_std_percentage(avg_list.T[-i])
        
        #print (str(code)+" box " + str(box_ratio))
        
        array_ratio = 0
        for i in range (1, 6):
            array_ratio += get_avg_array (avg_list.T[-i])
        #print (str(code)+" array " + str(array_ratio))
        
        avg_score[code] = array_ratio
        score[code] = box_ratio - array_ratio
        
    tick_list.clear()
    score = sorted(score.items(), key = lambda kv:(kv[1], kv[0]), reverse=False)
    for key in score:
        sec_info = get_security_info (key[0])
        print("\t"+str(sec_info.display_name) + ": " +str(key[0]) + " 得分是 " + str(key[1]))
        tick_list.append(key[0])
        
    return tick_list
    
# 获取过去180天
def select_ticks (check_date):
    tick_list = get_fundamentals(query(
            valuation.code
         ).filter(
            valuation.turnover_ratio > 3,
            valuation.turnover_ratio <= 10,
         ).order_by (
            # 按换手率降序排列
            valuation.turnover_ratio.desc()
         ), date = check_date)['code'].values

    tick_list = list(tick_list)
    print (str(check_date)+" 筛选到股票数量："+str(len(tick_list)))
    
    # 获取股票基本信息
    stock_base = get_all_securities(['stock'])
    
    # 次新股不考虑
    filter_list = []
    for code in tick_list:
        s_days = datetime.datetime.strptime(str(stock_base.loc[code]['start_date']),"%Y-%m-%d")
        c_days = datetime.datetime.strptime(str(check_date), "%Y-%m-%d")
        if (c_days - s_days).days < 365:
            filter_list.append(code)
    
    for code in filter_list:
        tick_list.remove (code)

    # ST股票不考虑
    filter_list = []
    for code in tick_list:
        if stock_base.loc[code]['display_name'].find('ST') != -1:
            filter_list.append(code)
    
    for code in filter_list:
        tick_list.remove (code)
    
    print (str(check_date)+" 过滤掉ST和次新股后，股票数量："+str(len(tick_list)))
    if len(tick_list) == 0:
        return tick_list
    
    filter_list = []
    print ("获取：" + str(check_date) + "的数据")
    df = get_price(tick_list, count=130, end_date=check_date, panel = False)
    for code in tick_list:
        tdf = df[df['code'] == code]
        
        low = tdf['low'].values
        open = tdf['open'].values
        high = tdf['high'].values
        close = tdf['close'].values
        volume = tdf['volume'].values
        
        # 获取倍量的股票
        if not is_multiple_stocks (volume, 5):
            filter_list.append(code)
            continue

        # 昨日是跌
        if close[-1] < open[-1]:
            filter_list.append(code)
            continue
         
        # 放量上涨，昨日不能是长上影线, 倍量换手，不能长上影线
        if (close[-1] - open[-1]) < (high[-1] - close[-1]):
            filter_list.append(code)
            continue
        
        # 倍量当日，开盘价超过5%
        if open[-1] > close[-2] * 1.05:
            filter_list.append(code)
            continue

        # 倍量涨幅低于5%
        if close[-1] < close[-2] * 1.05:
            filter_list.append(code)
            continue

        # 10日有7日股价高于60日均线， 否则不考虑
        avg60_list = get_ma (close, 60)
        count = get_bigger_than_val_counter (close, 11, avg60_list)
        if count < 7:
            filter_list.append(code)
            continue
        
        # 近3日，股价必须高于60日均线
        count = get_bigger_than_val_counter (close, 4, avg60_list)
        if count < 3:
            filter_list.append(code)
            continue

        # 不得高于30日最低价的1.25
        min30 = get_min_price (close, 30)
        if min30 * 1.25 < close[-1]:
            filter_list.append(code)
            continue
        
        # 不得高于5日最低价的1.13
        min5 = get_min_price (close, 5)
        if min5 * 1.13 < close[-1]:
            filter_list.append(code)
            continue

    # 剔除前面不满足条件的股票
    for code in filter_list:
        tick_list.remove (code)
    
    # 通过阿尔法11进行排序，优质股放在最前面
    tick_list = get_stocks_score (tick_list, df, check_date)
    
    return tick_list


check_date = '2020-08-21'
security_list = select_ticks (check_date)
print (security_list)

    


# In[ ]:




