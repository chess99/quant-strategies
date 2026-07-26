#!/usr/bin/env python
# coding: utf-8

# In[1]:


from jqdata import bond
import numpy as np
import math
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import norm
from pylab import mpl
import seaborn
import os
seaborn.set()
mpl.rcParams['font.sans-serif'] = ['KaiTi']
mpl.rcParams['axes.unicode_minus'] = False
from jqdata import finance
from jqdata import get_all_trade_days
import pandas as pd


# In[2]:


import datetime
import re
from bs4 import BeautifulSoup
import requests


# In[3]:


get_ipython().run_line_magic('matplotlib', 'inline')
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import ticker
plt.style.use('seaborn-white')


# In[4]:


pd.set_option('display.max_rows', 300)


# In[7]:


# 爬虫相关函数，用于从集思录获取可转债评级和到期赎回价格信息
# 由于聚宽无法拿到可转债赎回价格和评级数据，只能通过爬集思录获得。。。
# 后续聚宽数据完善后可以删除集思录爬虫部分
def getHTMLtext(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/72.0.3626.119 Safari/537.36"
    }
    r = requests.get(url=url, headers=headers)
    r.raise_for_status()
    r.encoding=r.apparent_encoding
    return r.text

def get_bond_extra_info(code):
    url = 'https://www.jisilu.cn/data/convert_bond_detail/' + code
    html=getHTMLtext(url)
    soup=BeautifulSoup(html,'html.parser')
    price = float(soup.find('td', id = 'redeem_price').get_text().strip())
    rating = soup.find('td', id = 'rating_cd').get_text().strip()
    return price, rating

def get_before_after_trade_days(date, count, is_before=True):
    """
    date :查询日期
    count : 前后追朔的数量
    is_before : True , 前count个交易日  ; False ,后count个交易日

    返回 : 基于date的日期, 向前或者向后count个交易日的日期 ,一个datetime.date 对象
    """
    all_date = pd.Series(get_all_trade_days())
    if isinstance(date,str):
        all_date = all_date.astype(str)
    if isinstance(date,datetime.datetime):
        date = date.date()
    print(all_date.tail(10))

    if is_before :
        return all_date[all_date< date].tail(count).values[0]
    else :
        return all_date[all_date>date].head(count).values[-1]

#获得具体某只可转债指定日期可转债价格，股票价格，行权价格双低值，是否到期，是否可交易等信息
def get_bond_detail(code, date):
    today_date = datetime.datetime.strptime(str(date), "%Y-%m-%d")
    today = today_date.strftime("%Y-%m-%d")
    date_1_y = today_date + datetime.timedelta(days=-365)
    one_year_ago = date_1_y.strftime("%Y-%m-%d")
    df=bond.run_query(query(bond.BOND_BASIC_INFO).filter(bond.BOND_BASIC_INFO.bond_type_id== '703013',
                                                     bond.BOND_BASIC_INFO.code==code).limit(1000))
    conv_df = bond.run_query(query(bond.CONBOND_BASIC_INFO).filter(bond.CONBOND_BASIC_INFO.code==code).limit(100))
    bond_name = df.loc[0, 'short_name']
    stock_code = df.loc[0, 'company_code']
    mature_date = df.loc[0, 'maturity_date']
    bond_start_date = df.loc[0, 'list_date']
    # 以下代码用于判断可转债是否可交易，是否终止上市
    if(not pd.isna(bond_start_date)):
        bond_start_date_str = bond_start_date.strftime('%Y-%m-%d')
    else:
        bond_start_date = df.loc[0, 'interest_begin_date']
        bond_start_date_str = bond_start_date.strftime('%Y-%m-%d')
    conv_start_date = conv_df.loc[0, 'convert_start_date']
    conv_start_date_str = conv_start_date.strftime('%Y-%m-%d')
    mature_date_str = mature_date.strftime('%Y-%m-%d')
    if(today <= bond_start_date_str):
        print('date:{}|bond:{}|invalid'.format(today, code))
        return np.NaN, np.NaN, np.NaN, np.NaN, np.NaN, np.NaN, np.NaN, 0, 0, 0
    conv_bond_price_df = bond.run_query(query(bond.CONBOND_DAILY_PRICE).filter(bond.CONBOND_DAILY_PRICE.date<today,
                                                         bond.CONBOND_DAILY_PRICE.code==code).limit(1000))
    if(len(conv_bond_price_df)==0):
        print('date:{}|bond:{}|invalid'.format(today, code))
        return np.NaN, np.NaN, np.NaN, np.NaN, np.NaN, np.NaN, np.NaN, 0, 0, 0
    if(today > mature_date_str):
        print('date:{}|bond:{}|stop trading'.format(today, code))
        return np.NaN, np.NaN, np.NaN, np.NaN, np.NaN, np.NaN, np.NaN, 0, 1, 1
    if(today > conv_start_date_str):
        conv_info = bond.run_query(query(bond.CONBOND_DAILY_CONVERT).filter(bond.CONBOND_DAILY_CONVERT.code==code,
                                                       bond.CONBOND_DAILY_CONVERT.date>=today).limit(100))
        if(len(conv_info)==0):
            print('date:{}|bond:{}|stop trading'.format(today, code))
            return np.NaN, np.NaN, np.NaN, np.NaN, np.NaN, np.NaN, np.NaN, 0, 1, 1
    # 获得对应正股价格信息
    price_df = get_price(security=stock_code, start_date=one_year_ago, end_date=today, frequency='daily', fields=None, skip_paused=False, fq=None, panel=True)
    stock_price = price_df.tail(1).reset_index(drop=True).loc[0, 'close']
    stock_date = price_df.index[len(price_df.index)-1].strftime("%Y-%m-%d")
    
    price_change = bond.run_query(query(bond.CONBOND_CONVERT_PRICE_ADJUST).filter(bond.CONBOND_CONVERT_PRICE_ADJUST.code==code,
                                                         ).limit(1000))
    strike_price = price_change[price_change.adjust_date.map(lambda x:x.strftime("%Y-%m-%d")<=stock_date)].tail(1).reset_index(drop=True).loc[0, 'new_convert_price']
    cur_price = price_df.tail(1).reset_index(drop=True).loc[0, 'close']
    
    #获得可转债价格，用于计算双低值
    bond_price_df = bond.run_query(query(bond.CONBOND_DAILY_PRICE).filter(bond.CONBOND_DAILY_PRICE.date== stock_date,
                                                         bond.CONBOND_DAILY_PRICE.code==code).limit(1000))
    bond_price = bond_price_df.tail(1).reset_index(drop=True).loc[0, 'close']
    # 溢价率，双低计算
    final_price, rating = get_bond_extra_info(code)
    bond_inner_value = 100/strike_price*cur_price
    double_low = bond_price + (bond_price-bond_inner_value)/bond_inner_value*100
    return 0, bond_price, stock_price, strike_price, 0, 0, double_low, 1, 0, 1

def get_bond_info(date):
    file_name = 'conv_bond_cache/conv_bond_info_' + date
    if(os.path.exists(file_name)):
        result = pd.read_pickle(file_name)
        return result
    #bond_df=bond.run_query(query(bond.BOND_BASIC_INFO).filter(bond.BOND_BASIC_INFO.bond_type_id== '703013',
    #                                                     bond.BOND_BASIC_INFO.list_status_id == '301001').limit(1000))
    bond_df=bond.run_query(query(bond.BOND_BASIC_INFO).filter(bond.BOND_BASIC_INFO.bond_type_id== '703013').limit(2000))
    bond_df=bond_df[bond_df.maturity_date.map(lambda x:x.strftime("%Y-%m-%d")>date)]
    
    bond_theo_lst = []
    bond_price_lst = []
    stock_price_lst = []
    strike_price_lst = []
    deviation_lst = []
    company_type_lst = []
    premium_rate_lst = []
    double_low_lst = []
    score_lst = []
    tradeable_lst = []
    reach_first_trade_day_lst=[]
    is_delist_lst = []
    print('total_df_len:{}'.format(len(bond_df)))
    i=0
    exception_num = 0
    for info_row in bond_df.iterrows():
        code = info_row[1].code
        security_code = info_row[1].company_code
        industry_val = get_industry(security_code)
        industry_type = industry_val[security_code]['sw_l1']['industry_name']
        print('process:{}|percentage:{}'.format(code, i/len(bond_df)))
        is_delist = 0
        reach_first_trade_day = 0
        i=i+1
        '''
        bond_theo, bond_price, stock_price, strike_price, deviation, premium_rate, double_low, tradeable, is_delist, reach_first_trade_day = get_bond_detail(code, date)
        deviation_rate = deviation*100
        score = double_low + deviation_rate
        '''
        tradeable=0
        try:
            bond_theo, bond_price, stock_price, strike_price, deviation, premium_rate, double_low, tradeable, is_delist, reach_first_trade_day = get_bond_detail(code, date)
            deviation_rate = deviation*100
            score = double_low + deviation_rate
        
        except:
            exception_num = exception_num+1
            print('exception exist for code:{}|except_total_num:{}'.format(code, exception_num))
            bond_theo=np.NaN
            bond_price=np.NaN
            stock_price = np.NaN
            strike_price = np.NaN
            deviation=np.NaN
            deviation_rate=np.NaN
            premium_rate=np.NaN
            double_low = np.NaN
            score = np.NaN
            tradeable = 0
            is_delist = 0
            reach_first_trade_day = 1
        
        
        bond_theo_lst.append(bond_theo)
        bond_price_lst.append(bond_price)
        stock_price_lst.append(stock_price)
        strike_price_lst.append(strike_price)
        deviation_lst.append(deviation_rate)
        premium_rate_lst.append(premium_rate)
        double_low_lst.append(double_low)
        score_lst.append(score)
        company_type_lst.append(industry_type)
        tradeable_lst.append(tradeable)
        is_delist_lst.append(is_delist)
        reach_first_trade_day_lst.append(reach_first_trade_day)
    bond_df_new = bond_df.assign(bond_theo=bond_theo_lst, bond_price=bond_price_lst, stock_price = stock_price_lst, strike_price = strike_price_lst, deviation=deviation_lst, company_type=company_type_lst, premium_rate=premium_rate_lst, double_low=double_low_lst, score=score_lst, tradeable=tradeable_lst, reach_first_trade_day=reach_first_trade_day_lst, is_delist=is_delist_lst)
    bond_df_reslt = bond_df_new
    bond_df_reslt.to_pickle(file_name)
    print('total except num:{}'.format(exception_num))
    return bond_df_reslt


# In[8]:


# 以下为回测主逻辑，用于获得双低策略收益曲线
def get_target_conv_bond_by_double_low(date, candidate_num, money):
    conv_bond_info = get_bond_info(date)
    tradeable_bond = conv_bond_info[(conv_bond_info.tradeable==1)&(conv_bond_info.reach_first_trade_day==1)&(conv_bond_info.is_delist==0)&(conv_bond_info.bond_price>10)].reset_index(drop=True)
    target_conv_bond = tradeable_bond.sort_values(by='double_low').head(candidate_num).reset_index(drop=True)
    money_for_each_bond = money / candidate_num
    target_trade_result = []
    for conv_bond in target_conv_bond.iterrows():
        code = conv_bond[1].code
        bond_price = conv_bond[1].bond_price
        qty = money_for_each_bond / bond_price
        target_trade_result.append((code, bond_price, qty))
    return target_trade_result

def get_benchmark_conv_bond(date, candidate_num, money):
    conv_bond_info = get_bond_info(date)
    tradeable_bond = conv_bond_info[(conv_bond_info.tradeable==1)&(conv_bond_info.reach_first_trade_day==1)&(conv_bond_info.is_delist==0)&(conv_bond_info.bond_price>10)].reset_index(drop=True)
    bond_num = len(tradeable_bond)
    money_for_each_bond = money / bond_num
    target_trade_result = []
    for conv_bond in tradeable_bond.iterrows():
        code = conv_bond[1].code
        bond_price = conv_bond[1].bond_price
        qty = money_for_each_bond / bond_price
        target_trade_result.append((code, bond_price, qty))
    return target_trade_result
    
def sell_bond(date, hold_bond):
    conv_bond_info = get_bond_info(date)
    hold_bond_code_lst = []
    for val in hold_bond:
        hold_bond_code_lst.append(val[0])
    bond_to_sell_info = conv_bond_info[conv_bond_info.code.map(lambda x:x in hold_bond_code_lst)].reset_index(drop=True)
    money = 0
    for conv_bond in bond_to_sell_info.iterrows():
        code = conv_bond[1].code
        bond_price = conv_bond[1].bond_price
        tradeable = conv_bond[1].tradeable
        delist = conv_bond[1].is_delist
        if(delist):
            for val in hold_bond:
                if(val[0]==code):
                    money = money + val[1]*val[2]
                    hold_bond.remove(val)
                    break
        else:
            if((tradeable) and (bond_price>0)):
                for val in hold_bond:
                    if(val[0]==code):
                        money = money + bond_price*val[2]
                        hold_bond.remove(val)
                        break
    return money, hold_bond

def update_bond_price(date, hold_bond):
    conv_bond_info = get_bond_info(date)
    hold_bond_code_lst = []
    new_hold_bond = []
    for val in hold_bond:
        hold_bond_code_lst.append(val[0])
        new_hold_bond.append((val[0], val[1], val[2]))
    bond_to_calc = conv_bond_info[conv_bond_info.code.map(lambda x:x in hold_bond_code_lst)].reset_index(drop=True)
    for conv_bond in bond_to_calc.iterrows():
        code = conv_bond[1].code
        bond_price = conv_bond[1].bond_price
        tradeable = conv_bond[1].tradeable
        delist = conv_bond[1].is_delist
        if((tradeable) and (bond_price>0)):
            for val in new_hold_bond:
                if(val[0]==code):
                    new_val = (val[0], bond_price, val[2])
                    new_hold_bond.remove(val)
                    new_hold_bond.append(new_val)
                    break
    return new_hold_bond
        

def get_bond_total_val(holding_bond):
    total_val = 0
    for val in holding_bond:
        total_val = total_val + val[1]*val[2]
    return total_val

def backtest(start_date, trading_dates, select_target_func, money, candidate_bond_num, trade_interval=1):
    date = start_date
    cur_trade_date = get_before_after_trade_days(date, 1, is_before=False)
    left_trade_date = trading_dates
    result = []
    cur_money = money
    holding_bond = []
    interval = 0
    while(left_trade_date>0):
        #print('backtest|date:{}|left:{}'.format(cur_trade_date, left_trade_date))
        if(interval == 0):
            sell_money, remain_bond = sell_bond(cur_trade_date, holding_bond)
            cur_money = sell_money + cur_money
            target_trade_result = select_target_func(date=cur_trade_date, candidate_num=candidate_bond_num, money=cur_money)
            cur_money = 0
            holding_bond = remain_bond + target_trade_result
            interval = trade_interval-1
        else:
            holding_bond = update_bond_price(cur_trade_date, holding_bond)
            interval = interval-1
        total_value = get_bond_total_val(holding_bond)
        #print('date:{}|hold_bond:{}|value:{}'.format(cur_trade_date, holding_bond, total_value))
        result.append((cur_trade_date, total_value))
        cur_trade_date = get_before_after_trade_days(cur_trade_date, 1, is_before=False)
        left_trade_date = left_trade_date - 1
    print(holding_bond)
    return result

def get_result_value(result):
    dates = []
    value_all = []
    for val in result:
        dates.append(val[0])
        value_all.append(val[1])
    return dates, value_all

def plot_backtest_result(result_map):
    data_num = 10
    plt.figure(dpi=180)
    for key in result_map.keys():
        result = result_map[key]
        dates, value_all = get_result_value(result)
        date_num = len(dates)
        #print('tag:{}|date:{}|val:{}'.format(key, dates, value_all))
        plt.plot(dates, value_all, label=key)
    plt.legend()
    plt.xlabel('date')
    multiplier = int(date_num / data_num)
    if(multiplier > 1):
        plt.gca().xaxis.set_major_locator(ticker.MultipleLocator(multiplier))
    plt.ylabel('value')
    plt.title('backtest')
    plt.gcf().autofmt_xdate()
    plt.show()

def show_backtest_result(start_date, days):
    trading_dates = days
    result = backtest(start_date=start_date, trading_dates=trading_dates, select_target_func=get_target_conv_bond_by_double_low, money=10000, candidate_bond_num=10)
    benchmark_result = backtest(start_date=start_date, trading_dates=trading_dates, select_target_func=get_benchmark_conv_bond, money=10000, candidate_bond_num=10)
    result_lst = {'double_low':result, 'benchmark':benchmark_result}
    plot_backtest_result(result_lst)


# In[12]:


result=get_bond_info('2022-04-15')


# In[ ]:


# 拉取所需数据，以dataframe保存成文件，方便回测使用
# 一天数据需6min左右，请耐心等待
date = '2020-09-22'
end_date = '2022-04-09'
cur_date = date
while(cur_date < end_date):
    get_bond_info(cur_date)
    cur_date = get_before_after_trade_days(cur_date, 1, is_before=False)


# In[ ]:


# 展示从2020-09-22开始一年的收益率
show_backtest_result('2020-09-22', 240)

