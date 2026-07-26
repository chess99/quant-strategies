#!/usr/bin/env python
# coding: utf-8

# In[36]:


import pandas as pd
import datetime as dt
from jqdata import *

#获取全部交易日，不受下面两个个日期设定的影响
all_trade_days=[i.strftime('%Y-%m-%d') for i in list(get_all_trade_days())]
#循环起始日期，取11月1日，即所有上市公司三季报发布完毕日期，可以改动年份但不要改月日
sd = '2022-11-01'
#循环结束日期，选用当前时间的前一天不会产生未来函数，最多到次年5月
ed = '2023-02-07'
#获取从sd到ed时间段(以下简称循环时段)所有交易日的日期存为列表
test_days = get_trade_days(start_date=sd, end_date=ed, count=None)
test_days_list = []
for item in list(test_days):
    test_days_list.append(str(item))

#公用函数
def get_date(initial_date, shift_days):
    all_trade_days=[i.strftime('%Y-%m-%d') for i in list(get_all_trade_days())]
    return str(datetime.datetime.strptime(all_trade_days[all_trade_days.index(initial_date)+shift_days],"%Y-%m-%d").date())

def get_fiscal_quarters(start_date):
    md_lst = ['-03-31','-06-30','-09-30','-12-31']
    y3 = str(start_date[:4])
    y2 = str(int(y3) - 1)
    y1 = str(int(y2) - 1)
    y1_lst, y2_lst, y3_lst = [], [], []
    for i in range(4):
        y1_lst.append(y1 + md_lst[i])
        y2_lst.append(y2 + md_lst[i])
        y3_lst.append(y3 + md_lst[i])
    fq_date_lst = [y1_lst, y2_lst, y3_lst]
    return fq_date_lst

def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68':
            stock_list.remove(stock)
    return stock_list

def check_st_stock(initial_list, stat_date, is_st):
    df = get_extras('is_st', initial_list, start_date=stat_date, end_date=stat_date, df=True)
    df = df.T
    df.columns = ['is_st']
    df = df[df['is_st'] == is_st]
    filter_list = list(df.index)
    return filter_list

def filter_new_stock(initial_list, stat_date, n_days):
    df = get_all_securities(types=['stock'], date=stat_date)[['start_date']]
    df = df.loc[initial_list]
    date = datetime.datetime.strptime(all_trade_days[all_trade_days.index(stat_date)-n_days],"%Y-%m-%d").date()
    return list(df[df['start_date'] < date].index)


# In[37]:


fqd = get_fiscal_quarters(sd)
fqd


# In[38]:


'''
根据上海证券交易所股票上市规则（2022年1月修订）第九章第八节第六条，被实施其它风险警示(st)的股票需符合：
公司最近三个会计年度扣除非经常性损益前后净利润孰低者均为负值，且最近一年审计报告显示公司持续经营能力存在不确定性。
解读：扣非前净利润跟扣非后净利润哪个更低用哪个数据，这个数据需要连续三年为负。
    “持续经营能力不确定”这条不好量化，如果不符合这点，即使连亏三年也不会被st，加之最新一季度净利润是估算值，可能被低估，
    所以下面结果会含有很大一部分被“错杀”的股票。
    另外，即使没有连亏三年，也可能因别的情形被实施其它风险警示(st)，所以也会有一部分“漏网之鱼”。
'''
#根据过去4+4+3个季报的净利润与扣非净利润初步估计有被st风险的股票
def predict_st_stocks(stock_list, stat_date, fqd):
    tmp = []
    k1 = 'net_profit' #净利润 
    k2 = 'adjusted_profit' #扣非净利润    
    for stock in stock_list:
        try:
            df = get_history_fundamentals(stock, fields=[income.net_profit, indicator.adjusted_profit], watch_date=stat_date, count=11, interval='1q')
            df = df.set_index('statDate')
            #距离观察日(ed)最近一个还未披露的季度用前一年同期替代
            #由于get_history_fundamentals返回数据可能缺失，所以不要用iloc定位，会“串行”。
            y1 = df.loc[fqd[0][0]][k1] + df.loc[fqd[0][1]][k1] + df.loc[fqd[0][2]][k1] + df.loc[fqd[0][3]][k1]
            y1a = df.loc[fqd[0][0]][k2] + df.loc[fqd[0][1]][k2] + df.loc[fqd[0][2]][k2] + df.loc[fqd[0][3]][k2]
            y2 = df.loc[fqd[1][0]][k1] + df.loc[fqd[1][1]][k1] + df.loc[fqd[1][2]][k1] + df.loc[fqd[1][3]][k1]
            y2a = df.loc[fqd[1][0]][k2] + df.loc[fqd[1][1]][k2] + df.loc[fqd[1][2]][k2] + df.loc[fqd[1][3]][k2]
            y3 = df.loc[fqd[2][0]][k1] + df.loc[fqd[2][1]][k1] + df.loc[fqd[2][2]][k1] + df.loc[fqd[1][3]][k1]
            y3a = df.loc[fqd[2][0]][k2] + df.loc[fqd[2][1]][k2] + df.loc[fqd[2][2]][k2] + df.loc[fqd[1][3]][k2]
            if (min(y1,y1a)<0) and (min(y2,y2a)<0) and (min(y3, y3a)<0):
                tmp.append(stock)
        except:
            #如不符合上述数据结构，说明上市公司可能未按时披露信息，或上市不足3年
            pass
    return tmp


df = get_all_securities(types=['stock'], date=sd)
stock_list = list(df.index)
#由于风险警示制度与主板不同，这里过滤掉了科创板跟北交所股票(聚宽目前也没有北交所数据)
stock_list = filter_kcbj_stock(stock_list)
#本研究主要是预防被st，所以只保留在循环起始日之前正常的股票
stock_list = check_st_stock(stock_list, sd, False)
#上市3年以内一般不会因为连续亏损退市，所以过滤掉上市不足500个交易日的股票
stock_list = filter_new_stock(stock_list, sd, 500)
#获取需要查询的日期列表
fiscal_quarter_date_list = get_fiscal_quarters(sd)
#预测当前非st但是有可能变st的股票，此列表为初次预测，之后需要随着时间推进更新
predict_list0 = predict_st_stocks(stock_list, sd, fiscal_quarter_date_list)
print(len(predict_list0))
predict_list0


# In[39]:


'''
循环时段中每天检查是否发布至少扭亏为盈的业绩预告，
如果有，说明最新年度扣非前后最小净利润已经大于零，一般不会被st，可以在年报发布前提前排除出风险名单。
循环计算较慢，日常更新只需要用新的日期(ed)替换stat_date计算当日即可。
'''
predict_list1 = predict_list0.copy()
for stat_date in test_days_list:
    print(stat_date)
    for stock in predict_list1[:]:        
        df = finance.run_query(query(finance.STK_FIN_FORCAST).filter(finance.STK_FIN_FORCAST.code==stock))
        df = df[(df['report_type'] == '四季度预告') & (df['type_id'] <= 305004) & (df['pub_date'] < datetime.date(*map(int,stat_date.split('-'))))]
        if len(df) > 0:
            if str(df.iloc[-1,:]['end_date'])[2:4] == str(sd)[2:4]:
                print('预增预盈或扭亏为盈', stock)
                #在一月会产生一批预盈的股票
                predict_list1.remove(stock)
        try:
            df = get_history_fundamentals(stock, fields=[income.net_profit, indicator.adjusted_profit], watch_date=stat_date, count=4, interval='1q')
            df = df.set_index('statDate')
            k1 = 'net_profit' #净利润 
            k2 = 'adjusted_profit' #扣非净利润
            fqd = get_fiscal_quarters(sd)
            #这里与11月1日预判不同的是第四项，这里是每天查看如果有公司发布了年报，第四项就不要用估算值了
            y3 = df.loc[fqd[2][0]][k1] + df.loc[fqd[2][1]][k1] + df.loc[fqd[2][2]][k1] + df.loc[fqd[2][3]][k1]
            y3a = df.loc[fqd[2][0]][k2] + df.loc[fqd[2][1]][k2] + df.loc[fqd[2][2]][k2] + df.loc[fqd[2][3]][k2]
            if min(y3, y3a) > 0:
                print('年报已出最近一年盈利', stock)
                predict_list1.remove(stock)
        except:
            pass
print(len(predict_list1))
predict_list1 #最后输出的是，去除预盈和已经公布财报盈利后，仍然有被st风险的股票


# In[ ]:




