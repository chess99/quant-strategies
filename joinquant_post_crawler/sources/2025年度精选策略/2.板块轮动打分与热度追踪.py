#!/usr/bin/env python
# coding: utf-8

# In[110]:


#板块轮动统计打分
# 所有A股,剔除ST,停牌,上市不足半年的
# 针对个股计算指标，N日价格涨幅
# group by 板块，给板块热度打分，排序
# 展示给定日期最热门板块，板块内涨幅靠前个股，绘制板块历史热度情况


# In[92]:


#"sw_l1": 申万一级行业
#"sw_l2": 申万二级行业
#"sw_l3": 申万三级行业
#"jq_l1": 聚宽一级行业
#"jq_l2": 聚宽二级行业
#"zjw": 证监会行业
from jqdata import *
import pandas as pd
import numpy as np
from datetime import datetime,date,timedelta
import warnings
warnings.filterwarnings('ignore')

pd.set_option('display.max_rows', 100)
pd.set_option('display.max_columns', 10)
pd.set_option('display.width', None)
pd.set_option('display.max_colwidth', -1)
import time
def time_me(fn):
    def _wrapper(*args, **kwargs):
        start = time.clock()
        ret=fn(*args, **kwargs)
        print("%s cost %s second"%(fn.__name__, time.clock() - start))
        return ret
    return _wrapper


# In[150]:


import pandas as pd
from datetime import datetime,date,timedelta

@time_me
def stock_industry(date,industry_category_list):
    """
    获得指定日期所有股票的行业分类
    :param date:
    :param industry_category_list: ['jq_l1','jq_l2','sw_l1','sw_l2','sw_l3','zjw']  聚宽1级，聚宽2级，申万1级，申万2级，申万3级，证监会行业
    :return:
    """
    # 过滤新股
    dt=datetime.strptime(date,'%Y-%m-%d')
    df = get_all_securities(types=['stock'], date=date)
    df = df[df['start_date'] < (dt - timedelta(days=180)).date()]
    # 过滤ST股
    df_st_stock = get_extras('is_st', list(df.index), end_date=date, count=1).reset_index(drop=True).T
    stock_list = list(df_st_stock[df_st_stock[0] == False].index)
    df_sec = df[df.index.isin(stock_list)]
    ind=get_industry(list(df_sec.index),date=date)
    ind_dict={k:[ind[k][icode]['industry_name'] for icode in industry_category_list if len(set(ind[k].keys()).intersection(set(industry_category_list)))==len(industry_category_list)] for k in ind}
    df_ind=pd.DataFrame.from_dict(ind_dict, orient='index',
                       columns=[code for code in industry_category_list])
    df_ret = pd.merge(df_sec,df_ind,left_index=True,right_index=True,how='left')
    #print(len(df[df.isnull().T.any()]))
    return df_ret


def stock_industry_df(date,industry_category_list,df_stock):
    """
    获取给定股票列表，指定日期的行业分类
    :param date:
    :param industry_category_list: ['jq_l1','jq_l2','sw_l1','sw_l2','sw_l3','zjw']  聚宽1级，聚宽2级，申万1级，申万2级，申万3级，证监会行业
    :param df_stock: 股票dataframe index是股票代码
    :return:
    """
    ind = get_industry(df_stock.index, date=date)
    ind_dict = {k: [ind[k][industry_category]['industry_name'] for industry_category in industry_category_list if
                    len(set(ind[k].keys()).intersection(set(industry_category_list))) == len(industry_category_list)]
                for k in ind}
    df_ind = pd.DataFrame.from_dict(ind_dict, orient='index',
                                    columns=[code for code in industry_category_list])
    df = pd.merge(df_stock, df_ind, left_index=True, right_index=True, how='left')
    return df

@time_me
def returns(stock_df,date,days):
    """
    计算N日收益率
    :param stock_df:
    :param date: 2020-01-01
    :param days: 5
    :return: 输入的DataFrame
    """
    panel = get_price(list(stock_df.index), end_date=date, frequency='daily', fields=['close'], fq='pre', count=days+1,panel=True)
    df_close = panel.close
    # 可以修改收益率计算公式改变排名规则
    series_return = (df_close.iloc[-1] / df_close.iloc[-days-1])-1
    stock_df['return']=series_return
    return stock_df

@time_me
def returns_series(stock_df,date,days,back_days):
    """
    计算连续back_days天的days日收益率
    :param stock_df:
    :param date: 2020-01-01
    :param days: 5
    :return: 输入的DataFrame
    """
    panel = get_price(list(stock_df.index), end_date=date, frequency='daily', fields=['close'], fq='pre', count=days+back_days+1,panel=True)
    df_close = panel.close
    series_returns=[]
    for i in range(0,back_days):
        # 可以修改收益率计算公式改变排名规则
        series_returns.append( (df_close.iloc[-(back_days+1-i)] / df_close.iloc[-(back_days+1-i+days)])-1)
        stock_df['return_'+str(i+1)]=series_returns[i]
    return stock_df


def group_score(df,change_limit,back_days):
    """
    板块得分根据最后一天计算的收益率得到
    :param df:
    :param change_limit:
    :return:
    """
    df_ok=df[df['return_'+str(back_days)]>change_limit/100]
    # 超过收益率阈值的股票上涨均值
    mean =df_ok['return_'+str(back_days)].mean()*100 if len(df_ok)>0 and len(df)>10 else 0
    # 行业内超过收益率阈值股票的平均收益率*超过阈值股票个数占行业比例
    score= int(len(df_ok)/len(df)*mean*10)
    return score

def group_score_series(df,change_limit,days,back_days):
    """
    板块热度热分序列
    :param df:
    :param change_limit:
    :return:
    """
    scores=[]
    for i in range(0,back_days):
        df_ok=df[df['return_'+str(i+1)]>change_limit/100]
        mean =df_ok['return_'+str(i+1)].mean()*100 if len(df_ok)>0 and len(df)>10 else 0
        score= int(len(df_ok)/len(df)*mean*10)
        scores.append(score)
    return scores


def group_top_list(df,top_count,change_limit,days):
    """
    板块days日收益率排名前top_count的股票
    :param df:
    :param top_count:
    :return:
    """
    df_top = df.sort_values(by='return_'+str(days), ascending=False).head(top_count)
    df_top['print']=df_top['display_name']+":"+(df_top['return_'+str(days)]*100).round(2).astype('str')+"%"
    df_ok=df[df['return_'+str(days)]>change_limit/100]
    return "["+str(len(df_ok))+"/"+str(len(df))+"]"+",".join(list(df_top['print']))

@time_me
def top_industry(date,industry_category='sw_l2',return_days=5,back_days=10,stock_top_count=5,industry_top_count=10,up_limit=10):
    """
    计算当前根据return_days收益率计算的行业热度指数前industry_top_count名,并展示这些行业最近back_days日的得分
    :param date: 
    :param industry_category: sw_l1 sw_l2 sw_l3 zjw jq_l1 jq_l2
    :param return_days:  10  10日收益率
    :param back_days: 10  回溯10天当前topN热度行业历史得分
    :param stock_top_count:  展示前多少位股票
    :param industry_top_count:  展示前多少行业
    :param up_limit: 涨幅限制
    :return: 
    """
    df_ind = stock_industry(date, [industry_category])
    df_return = returns_series(df_ind, date, return_days,back_days)
    s_tops = df_return.groupby(industry_category).apply(group_top_list, stock_top_count,up_limit,return_days)
    s_scores = df_return.groupby(industry_category).apply(group_score_series, up_limit,return_days,back_days)
    s_score = df_return.groupby(industry_category).apply(group_score, up_limit,back_days)
    df= pd.DataFrame({"scores": s_scores, "top": s_tops,"score":s_score}, index=s_tops.index).sort_values(by='score',ascending=False).head(industry_top_count)
    display(df[['score','top']])
    plot_industry_hot(df,back_days,date)
    
    
markerMap = {'o': 'circle', 'v': 'triangle_down', '^': 'triangle_up', '<': 'triangle_left', '>': 'triangle_right', 's': 'square', 'p': 'pentagon', '*': 'star', 'h': 'hexagon1', 'H': 'hexagon2', '+': 'plus', 'x': 'x', 'D': 'diamond', 'd': 'thin_diamond', '|': 'vline', '_': 'hline', 'P': 'plus_filled', 'X': 'x_filled', 0: 'tickleft', 1: 'tickright', 2: 'tickup', 3: 'tickdown', 4: 'caretleft', 5: 'caretright', 6: 'caretup', 7: 'caretdown', 8: 'caretleftbase', 9: 'caretrightbase', 10: 'caretupbase', 11: 'caretdownbase'}
markers=[key for key in markerMap]
@time_me
def plot_industry_hot(df,days,date):
    import matplotlib.pyplot as plt
    plt.figure(figsize=(15,10))
    x = [i for i in range(1,days+1)] 
    plt.title('板块热度指数:'+date)  
    markerIndex=0
    for row in df.itertuples():
        plt.plot(x, row[1], label=row[0],marker=markers[markerIndex%days])
        markerIndex=markerIndex+1
    plt.legend()  #显示上面的label
    plt.xlabel('天')
    plt.ylabel('板块热度')
    plt.xticks(x)
    plt.show()


# In[154]:


top_industry('2020-06-17','zjw',return_days=5,back_days=30,stock_top_count=5,industry_top_count=10,up_limit=5)
top_industry('2020-06-17','sw_l2',return_days=5,back_days=30,stock_top_count=5,industry_top_count=10,up_limit=5)
top_industry('2020-06-17','jq_l2',return_days=5,back_days=30,stock_top_count=5,industry_top_count=10,up_limit=5)

