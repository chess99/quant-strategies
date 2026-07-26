#!/usr/bin/env python
# coding: utf-8

# In[18]:


import os
import pandas as pd
import numpy as np
from datetime import date, datetime, timedelta
from dateutil.relativedelta import *
import time
import math
import sqlite3
from tqdm import tqdm

import talib
import statsmodels.api as sm
from jqdatasdk import *
# auth('XXXXXXXXXX','XXXXX')

import matplotlib.pyplot as plt
plt.rcParams['font.sans-serif'] = ['SimHei']
plt.rcParams["font.family"] = 'Arial Unicode MS' 
plt.rcParams['axes.unicode_minus'] = False # 用来正常显示负号
from matplotlib.font_manager import FontProperties
myfont=FontProperties(fname=r'C:\Windows\Fonts\simhei.ttf',size=14)

import pyecharts.options as opts
from pyecharts.charts import Kline, Line, Page, Grid

from IPython import display
display.set_matplotlib_formats('svg') # 提高绘图清晰度

import seaborn as sns
sns.set(font=myfont.get_name())

# 將html另存爲圖片jpeg
from pyecharts.render import make_snapshot
from snapshot_phantomjs import snapshot # js法
# import pyecharts # cromedriver法
# from snapshot_selenium import snapshot

import warnings
warnings.filterwarnings("ignore")


# ## 限定分析范围

# In[19]:


ystd = str(datetime.now().date()+timedelta(days=-1))
today = str(datetime.now().date())
info_dt = ystd
rect_2_trd_dt = [str(dt) for dt in get_trade_days(end_date=info_dt, count=2)] # 注：本脚本只有交易日判断会用到聚宽数据！
info_dt_m1 = rect_2_trd_dt[-1] if info_dt not in rect_2_trd_dt else rect_2_trd_dt[-2]

# info_dt_m1 = '2022-04-20' # 补数据（注意数据库最早日期！！）
print('最近一个交易日（非当天）为：'+info_dt_m1)


# In[3]:


# 获取股票池列表
df_stk_pool = pd.read_excel('../../basic_auto_get_factors/df_far_{info_dt_m1}.xlsx'.format(info_dt_m1=info_dt_m1)) # 注：依赖当日已经跑出的因子数据！
df_ind_stk = df_stk_pool[['code','name','sw_l1_name']]
stk_list = list(df_ind_stk['code'])
df_stk_pool.head(3)


# In[4]:


# 获取近一年个股股价变动及近三年个股换手率
day_m1y = str(int(info_dt_m1.split('-')[0])-1)+'-'+info_dt_m1.split('-')[1]+'-'+info_dt_m1.split('-')[2]
day_m4y = str(int(info_dt_m1.split('-')[0])-4)+'-'+info_dt_m1.split('-')[1]+'-'+info_dt_m1.split('-')[2]
conn = sqlite3.connect('../../basic_auto_get_factors/factors_base_Price_and_TAindex.db')
print ("因子数据库（价格及技术指标）打开成功")
c = conn.cursor()
sql_ = '''SELECT day, code, chg_close
        FROM stocks_chg_close_data 
        WHERE day>='{day_m4y}' AND day<='{info_dt_m1}'
        '''.format(day_m4y=day_m4y,info_dt_m1=info_dt_m1)
p_chg = pd.read_sql(sql_,conn)
p_chg = p_chg.loc[p_chg['code'].isin(stk_list)==True]
conn.commit()
conn.close()
conn = sqlite3.connect('../../basic_auto_get_factors/factors_base_valuation.db')
print ("因子数据库（市值及估值）打开成功")
c = conn.cursor()
sql_ = '''SELECT day, code, market_cap, turnover_ratio
        FROM stocks_valuation_data
        WHERE day>='{day_m4y}' AND day<='{info_dt_m1}'
        '''.format(day_m4y=day_m4y,info_dt_m1=info_dt_m1)
val = pd.read_sql(sql_,conn)
val = val.loc[val['code'].isin(stk_list)==True]
conn.commit()
conn.close()


# ## 通用计算
# 

# In[5]:


## 构建运算大表
p_chg = pd.merge(p_chg,val,how='left',on=['code','day'])
p_chg = pd.merge(p_chg, df_stk_pool[['code','sw_l1_name']],how='left',on='code')
p_chg.head(3)


# In[6]:


## 计算全市场收益序列 -- 市值加权（非行业等权）
day_list = list(set(p_chg['day']))
day_list.sort(reverse=False)
df_mkt_r = pd.DataFrame()
for dt in tqdm(day_list):
    df_dt = p_chg.loc[p_chg['day']==dt]
    r_mkt = (df_dt['chg_close']*df_dt['market_cap']).sum()/(df_dt['market_cap'].sum())
    df_mkt_r = df_mkt_r.append({'date':dt,'r_mkt':r_mkt},ignore_index=True)
df_mkt_r.head(3)


# ## 行业动量（趋势度）

# In[7]:


## 计算行业动量
day_list = list(set(p_chg.loc[p_chg['day']>=day_m1y]['day'])) # 确定时间范围为过去1年
day_list.sort(reverse=False)

# 计算各行业IR值（行业动量）
ind_list = list(set(p_chg['sw_l1_name']))
df_ind_mom = pd.DataFrame()
for ind_ in tqdm(ind_list):
    df_ind_r = pd.DataFrame()
    df_ind = p_chg.loc[p_chg['sw_l1_name']==ind_]
    for dt in day_list:
        df_dt = df_ind.loc[df_ind['day']==dt]
        r_ind = (df_dt['chg_close']*df_dt['market_cap']).sum()/(df_dt['market_cap'].sum())
        df_ind_r = df_ind_r.append({'date':dt,'r_ind':r_ind},ignore_index=True)
    df_mgd = pd.merge(df_ind_r, df_mkt_r, how='left', on='date')
    r_ind_1y = (df_mgd['r_ind']+1).cumprod().iloc[-1]-1
    r_mkt_1y = (df_mgd['r_mkt']+1).cumprod().iloc[-1]-1
    error_std = (df_mgd['r_ind']-df_mgd['r_mkt']).std()
    IR_ind = (r_ind_1y-r_mkt_1y)/error_std
    df_ind_mom = df_ind_mom.append({'ind_name':ind_,
                                    'r_ind_1y':r_ind_1y, 'r_mkt_1y':r_mkt_1y, 'error_std':error_std,
                                    'IR_ind':IR_ind},ignore_index=True)
    
print(df_ind_mom.sort_values(by='IR_ind',ascending=False).head(3))


# ## 换手率/波动率/beta均值（拥挤度）

# In[37]:


# 计算个股3个月（40个交易日）换手率、波动率、beta
print('========== 计算个股3个月（40个交易日）换手率、波动率、beta ==========')
df_cpt_per_stk = pd.DataFrame()
for stk in tqdm(stk_list):
#     print(stk) # tmp检查
    df_stk_cpted = pd.DataFrame()
    df_stk = p_chg.loc[p_chg['code']==stk].sort_values(by=['day'],ascending=True)
    df_stk_cpted['day'], df_stk_cpted['code'], df_stk_cpted['sw_l1_name'] = df_stk['day'], df_stk['code'], df_stk['sw_l1_name']
    # 波动率
    df_stk_cpted['p_chg_40std'] = [np.nan]*39+[df_stk.iloc[i:i+40]['chg_close'].std() for i in range(len(df_stk)-39)]
    # 换手率
    df_stk_cpted['tovr_MA40'] = [np.nan]*39+[df_stk.iloc[i:i+40]['turnover_ratio'].mean() for i in range(len(df_stk)-39)]
    # beta
    beta_ = [np.nan]*39
    for i in range(len(df_stk)-39):
        x_y = pd.merge(df_stk.iloc[i:i+40],df_mkt_r,how='left',left_on='day',right_on='date').dropna()
        if len(x_y)<40:
            beta_.append(np.nan)
        else:
            y = x_y['chg_close'].values
            x = x_y['r_mkt'].values
            X = sm.add_constant(x)
            model = sm.OLS(y,X,missing='drop')
            results = model.fit()
            beta_.append(results.params[1])
    df_stk_cpted['beta_40d'] = beta_
    df_cpt_per_stk = df_cpt_per_stk.append(df_stk_cpted.dropna(), ignore_index=True)

# 计算行业各指标等权平均值
print('========== 计算行业各指标等权平均值 ==========')
ind_list = list(set(df_cpt_per_stk['sw_l1_name']))
day_list = list(set(df_cpt_per_stk['day']))
day_list.sort(reverse=False)
df_cpt_per_ind = pd.DataFrame()
for ind_ in tqdm(ind_list):
    df_ind_cpted = pd.DataFrame()
    df_ind = df_cpt_per_stk.loc[df_cpt_per_stk['sw_l1_name']==ind_]
    df_ind_cpted['day'], df_ind_cpted['sw_l1_name'] = day_list, [ind_]*len(day_list)
    std_list, tovr_list, beta_list = [], [], []
    for dt in day_list:
        avg_tmp = df_ind.loc[df_ind['day']==dt].mean()
        std_list.append(avg_tmp['p_chg_40std'])
        tovr_list.append(avg_tmp['tovr_MA40'])
        beta_list.append(avg_tmp['beta_40d'])
    df_ind_cpted['p_chg_40std'], df_ind_cpted['tovr_MA40'], df_ind_cpted['beta_40d'] = std_list, tovr_list, beta_list
    df_cpt_per_ind = df_cpt_per_ind.append(df_ind_cpted, ignore_index=True)
    
# 计算行业各指标同全行业均值之比
print('========== 计算行业各指标同全行业均值之比 ==========')
df_cpt_per_ind_2Avg = pd.DataFrame()
for dt in tqdm(day_list):
    df_dt_ind = df_cpt_per_ind.loc[df_cpt_per_ind['day']==dt]
    avg_tmp = df_dt_ind.mean()
    df_dt_ind['p_chg_40std_2Avg'] = df_dt_ind['p_chg_40std']/avg_tmp['p_chg_40std']
    df_dt_ind['tovr_MA40_2Avg'] = df_dt_ind['tovr_MA40']/avg_tmp['tovr_MA40']
    df_dt_ind['beta_40d_2Avg'] = df_dt_ind['beta_40d']/avg_tmp['beta_40d']
    df_dt_ind = df_dt_ind[['day','sw_l1_name','p_chg_40std_2Avg','tovr_MA40_2Avg','beta_40d_2Avg']]
    df_cpt_per_ind_2Avg = df_cpt_per_ind_2Avg.append(df_dt_ind, ignore_index=True)
    
# 计算各行业滚动N年的z-score
print('========== 计算各行业滚动N年的z-score ==========')
df_ind_crowd = pd.DataFrame()
for ind_ in tqdm(ind_list):
    df_ratio_ind = df_cpt_per_ind_2Avg.loc[df_cpt_per_ind_2Avg['sw_l1_name']==ind_].sort_values(by='day',ascending=True)
    z_p_chg_40std = (df_ratio_ind.iloc[-1]['p_chg_40std_2Avg']-df_ratio_ind['p_chg_40std_2Avg'].mean())/(df_ratio_ind['p_chg_40std_2Avg'].std())
    z_tovr_MA40 = (df_ratio_ind.iloc[-1]['tovr_MA40_2Avg']-df_ratio_ind['tovr_MA40_2Avg'].mean())/(df_ratio_ind['tovr_MA40_2Avg'].std())
    z_beta_40d = (df_ratio_ind.iloc[-1]['beta_40d_2Avg']-df_ratio_ind['beta_40d_2Avg'].mean())/(df_ratio_ind['beta_40d_2Avg'].std())
    crowdedness = (z_p_chg_40std+z_tovr_MA40+z_beta_40d)/3
    df_ind_crowd = df_ind_crowd.append({'ind_name':ind_, 
                                        'z_p_chg_40std':z_p_chg_40std,'z_tovr_MA40':z_tovr_MA40,'z_beta_40d':z_beta_40d,
                                        'crowdedness':crowdedness},ignore_index=True)
print(df_ind_crowd.sort_values(by='crowdedness',ascending=False).head(3))


# ## 营收、净利、ROE增长（景气度）
# 对于各行业，三者取行业各股中位数（防止亏损、盈利大幅波动带来的影响）

# In[33]:


df_g_ix = df_stk_pool[['code','trade_date','sw_l1_name','sales_G_ttm','profit_G_ttm','ocf_G_ttm','roe_G_ttm']]
ind_list = list(set(df_g_ix['sw_l1_name']))
df_ind_boom = pd.DataFrame()
for ind_ in ind_list:
    df_ind = df_g_ix.loc[df_g_ix['sw_l1_name']==ind_]
    median_tmp = df_ind.quantile(0.5)
    boom_ = (median_tmp['sales_G_ttm']+median_tmp['profit_G_ttm']+median_tmp['ocf_G_ttm']+median_tmp['roe_G_ttm'])/4
    df_ind_boom = df_ind_boom.append({'ind_name':ind_,
                                      'sales_G_ttm':median_tmp['sales_G_ttm'],'profit_G_ttm':median_tmp['profit_G_ttm'],
                                      'ocf_G_ttm':median_tmp['ocf_G_ttm'],'roe_G_ttm':median_tmp['roe_G_ttm'],
                                      'boom':boom_},
                                     ignore_index=True)
print(df_ind_boom.sort_values(by='boom',ascending=False).head(3))


# ## 合并数据、储存、绘图

# In[36]:


# 合并数据并储存
df_mgd = df_ind_mom.copy()
df_mgd = pd.merge(df_mgd, df_ind_crowd, how='left', on='ind_name')
df_mgd = pd.merge(df_mgd, df_ind_boom, how='left', on='ind_name')
df_mgd['trade_date'] = [info_dt_m1]*len(df_mgd)
df_mgd.to_excel('industry_3d_alys_{info_dt_m1}.xlsx'.format(info_dt_m1=info_dt_m1),index=False)
print(df_mgd.head(3))


# In[3]:


# 绘图
df_mgd = pd.read_excel('industry_3d_alys_{info_dt_m1}.xlsx'.format(info_dt_m1=info_dt_m1))
df_plot = df_mgd[['ind_name','IR_ind','crowdedness','boom']]
df_plot['IR_ind'] = (df_plot['IR_ind']-df_plot['IR_ind'].mean())/df_plot['IR_ind'].std()
df_plot['crowdedness'] = (df_plot['crowdedness']-df_plot['crowdedness'].mean())/df_plot['crowdedness'].std()
df_plot['boom'] = (df_plot['boom']-df_plot['boom'].mean())/df_plot['boom'].std()/20
df_plot['tol'] = 0.51*df_plot['IR_ind'] - 0.23*df_plot['crowdedness'] + 1.13*df_plot['boom']
print(df_plot.sort_values(by=['tol'],ascending=False).head(3))


# In[1]:


from pyecharts import options as opts
from pyecharts.charts import Scatter
from pyecharts.commons.utils import JsCode

c = (
    Scatter(init_opts=opts.InitOpts(
            width="1000px",
            height="900px",
            animation_opts=opts.AnimationOpts(animation=False),
            bg_color='white')
           )
    .add_xaxis(df_plot['IR_ind'])
    .add_yaxis("景气度(大小)    综合得分(颜色)",
               [list(z) for z in zip(df_plot['crowdedness'], df_plot['boom'], df_plot['tol'], df_plot['ind_name'])],
               label_opts=opts.LabelOpts(
                   formatter=JsCode(
                       "function(params){return params.value[4];}"
                   )
               ),
              )
    .set_global_opts(
        title_opts=opts.TitleOpts(title="行业趋势-拥挤-景气模型"),
        visualmap_opts=[opts.VisualMapOpts(type_="size",
                                           pos_top = 50,
                                           max_=df_plot['boom'].max(), min_=df_plot['boom'].min(),
                                           dimension=2),
                        opts.VisualMapOpts(type_="color",
                                           pos_bottom = 50,
                                           max_=df_plot['tol'].max(), min_=df_plot['tol'].min(),
                                           dimension=3)
                       ],
        yaxis_opts=opts.AxisOpts(name="拥挤度",splitline_opts=opts.SplitLineOpts(is_show=True)),
        xaxis_opts=opts.AxisOpts(name="趋势度",splitline_opts=opts.SplitLineOpts(is_show=True)),
    )
)
c.render("scatter_trend_crowded_boom.html")
make_snapshot(snapshot,c.render('scatter_trend_crowded_boom.HTML'),
              'scatter_trend_crowded_boom.jpeg',is_remove_html=True)
# jupyter展示
c.render_notebook()


# In[ ]:




