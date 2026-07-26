#!/usr/bin/env python
# coding: utf-8

# In[2]:


from typing import (List,Tuple,Dict,Callable,Union)

import datetime as dt
import numpy as np
import pandas as pd
import empyrical as ep

import graphviz
from sklearn.tree import export_graphviz
from sklearn.ensemble import RandomForestClassifier

from tqdm import tqdm_notebook

import alphalens as al

from jqdata import *
from jqfactor import (calc_factors,Factor)

import seaborn as sns
import matplotlib as mpl
import matplotlib.pyplot as plt

plt.rcParams['font.sans-serif']=['SimHei'] #用来正常显示中文标签
plt.rcParams['axes.unicode_minus']=False #用来正常显示负号


# In[3]:


'''股票池筛选'''
# 获取年末季末时点
def get_trade_period(start_date: str, end_date: str, freq: str = 'ME') -> list:
    '''
    start_date/end_date:str YYYY-MM-DD
    freq:M月，Q季,Y年 默认ME E代表期末 S代表期初
    ================
    return  list[datetime.date]
    '''
    days = pd.Index(pd.to_datetime(get_trade_days(start_date, end_date)))
    idx_df = days.to_frame()

    if freq[-1] == 'E':
        day_range = idx_df.resample(freq[0]).last()
    else:
        day_range = idx_df.resample(freq[0]).first()

    day_range = day_range[0].dt.date

    return day_range.dropna().values.tolist()


# 筛选股票池
class Filter_Stocks(object):
    '''
    获取某日的成分股股票
    1. 过滤st
    2. 过滤上市不足N个月
    3. 过滤当月交易不超过N日的股票
    ---------------
    输入参数：
        index_symbol:指数代码,A等于全市场,
        watch_date:日期
    '''
    
    def __init__(self,symbol:str,watch_date:str)->None:
        
        if isinstance(watch_date,str):
            
            self.watch_date = pd.to_datetime(watch_date).date()
            
        else:
            
            self.watch_date = watch_date
            
        self.symbol = symbol
        self.get_index_component_stocks()
        
    def get_index_component_stocks(self)->list:
        
        '''获取指数成分股'''
        
        if self.symbol == 'A':
            
            wd:pd.DataFrame = get_all_securities(types=['stock'],date=self.watch_date)
            self.securities:List = wd.query('end_date != "2200-01-01"').index.tolist()
        else:
            
            self.securities:List = get_index_stocks(self.symbol,self.watch_date)
    
    def filter_paused(self,paused_N:int=1,threshold:int=None)->list:
        
        '''过滤停牌股
        -----
        输入:
            paused_N:默认为1即查询当日不停牌
            threshold:在过paused_N日内停牌数量小于threshold
        '''
        
        if (threshold is not None) and (threshold > paused_N):
            raise ValueError(f'参数threshold天数不能大于paused_N天数')
            
        
        paused = get_price(self.securities,end_date=self.watch_date,count=paused_N,fields='paused',panel=False)
        paused = paused.pivot(index='time',columns='code')['paused']
        
        # 如果threhold不为None 获取过去paused_N内停牌数少于threshodl天数的股票
        if threshold:
            
            sum_paused_day = paused.sum()
            self.securities = sum_paused_day[sum_paused_day < threshold].index.tolist()
        
        else:
            
            paused_ser = paused.iloc[-1]
            self.securities = paused_ser[paused_ser == 0].index.tolist()

    def filter_zdt(self)->list:
        
        '''过滤zdt股
        0是满足非涨跌，非停板
        '''
        zdt = get_price(self.securities,end_date=self.watch_date,fields=['close','high_limit','low_limit','paused'],count=1,panel=False,fq='post')
        zdt['zdt_raw'] = zdt.apply(lambda x :1 if ((x['close']==x['high_limit']) or (x['close']==x['low_limit'])) else 0, axis = 1)
        zdt['zdt'] = zdt.apply(lambda x: 0 if ((x['paused']==0) and (x['zdt_raw']==0)) else 1, axis = 1)
        
        zdt = zdt.pivot(index='time',columns='code')['zdt']
        zdt_ser = zdt.iloc[-1]
        self.securities = zdt_ser[zdt_ser == 0].index.tolist()
    
    def filter_st(self)->list:
        
        '''过滤ST'''
              
        extras_ser = get_extras('is_st',self.securities,end_date=self.watch_date,count=1).iloc[-1]
        
        self.securities = extras_ser[extras_ser == False].index.tolist()
    
    def filter_ipodate(self,threshold:int=180)->list:
        
        '''
        过滤上市天数不足以threshold天的股票
        -----
        输入：
            threhold:默认为180日
        '''
        
        def _check_ipodate(code:str,watch_date:dt.date)->bool:
            
            code_info = get_security_info(code)
            
            if (code_info is not None) and ((watch_date - code_info.start_date).days > threshold):
                
                return True
            
            else:
                
                return False

        self.securities = [code for code in self.securities if _check_ipodate(code,self.watch_date)]
    
    
    
    def filter_industry(self,industry:Union[List,str],level:str='sw_l1',method:str='industry_name')->list:
        '''过略行业'''
        ind = get_stock_ind(self.securities,self.watch_date,level,method)
        target = ind.to_frame('industry').query('industry != @industry')
        self.securities = target.index.tolist()
        
def get_stock_ind(securities:list,watch_date:str,level:str='sw_l1',method:str='industry_code')->pd.Series:
    
    '''
    获取行业
    --------
        securities:股票列表
        watch_date:查询日期
        level:查询股票所属行业级别
        method:返回行业名称or代码
    '''
    
    indusrty_dict = get_industry(securities, watch_date)

    indusrty_ser = pd.Series({k: v.get(level, {method: np.nan})[
                             method] for k, v in indusrty_dict.items()})
    
    indusrty_ser.name = method.upper()
    
    return indusrty_ser

'''风险指标'''
# 风险指标


def Strategy_performance(return_df: pd.DataFrame,
                         periods='daily') -> pd.DataFrame:
    '''计算风险指标 默认为月度:月度调仓'''

    ser: pd.DataFrame = pd.DataFrame()
    ser['年化收益率'] = ep.annual_return(return_df, period=periods)
    ser['累计收益'] = ep.cum_returns(return_df).iloc[-1]
    ser['波动率'] = return_df.apply(
        lambda x: ep.annual_volatility(x, period=periods))
    ser['夏普'] = return_df.apply(ep.sharpe_ratio, period=periods)
    ser['最大回撤'] = return_df.apply(lambda x: ep.max_drawdown(x))
    
    if 'benchmark' in return_df.columns:

        select_col = [col for col in return_df.columns if col != 'benchmark']

        ser['IR'] = return_df[select_col].apply(
            lambda x: information_ratio(x, return_df['benchmark']))
        ser['Alpha'] = return_df[select_col].apply(
            lambda x: ep.alpha(x, return_df['benchmark'], period=periods))
        
        ser['超额收益'] = ser['年化收益率'] - ser.loc[
            'benchmark', '年化收益率']  #计算相对年化波动率
        
    return ser.T


def information_ratio(returns, factor_returns):
    """
    Determines the Information ratio of a strategy.

    Parameters
    ----------
    returns : :py:class:`pandas.Series` or pd.DataFrame
        Daily returns of the strategy, noncumulative.
        See full explanation in :func:`~empyrical.stats.cum_returns`.
    factor_returns: :class:`float` / :py:class:`pandas.Series`
        Benchmark return to compare returns against.

    Returns
    -------
    :class:`float`
        The information ratio.

    Note
    -----
    See https://en.wikipedia.org/wiki/information_ratio for more details.

    """
    if len(returns) < 2:
        return np.nan

    active_return = _adjust_returns(returns, factor_returns)
    tracking_error = np.std(active_return, ddof=1)
    if np.isnan(tracking_error):
        return 0.0
    if tracking_error == 0:
        return np.nan
    return np.mean(active_return) / tracking_error


def _adjust_returns(returns, adjustment_factor):
    """
    Returns a new :py:class:`pandas.Series` adjusted by adjustment_factor.
    Optimizes for the case of adjustment_factor being 0.

    Parameters
    ----------
    returns : :py:class:`pandas.Series`
    adjustment_factor : :py:class:`pandas.Series` / :class:`float`

    Returns
    -------
    :py:class:`pandas.Series`
    """
    if isinstance(adjustment_factor, (float, int)) and adjustment_factor == 0:
        return returns.copy()
    return returns - adjustment_factor


# In[5]:


# 标记得分
def sign(ser: pd.Series) -> pd.Series:
    '''标记分数,正数为1,负数为0'''
    
    return ser.apply(lambda x: np.where(x > 0, 1, 0))

class FScore(Factor):
    '''
    FScore原始模型
    '''
    name = 'FScore'
    max_window = 1

    watch_date = None
    # paidin_capital 实收资本 股本变化会反应在该科目中
    dependencies = [
        'roa', 'roa_4', 'net_operate_cash_flow', 'total_assets',
        'total_assets_1', 'total_assets_4', 'total_assets_5',
        'operating_revenue', 'operating_revenue_4',
        'total_non_current_assets', 'total_non_current_liability',
        'total_non_current_assets_4', 'total_non_current_liability_4',
        'total_current_assets', 'total_current_liability',
        'total_current_assets_4', 'total_current_liability_4',
        'gross_profit_margin', 'gross_profit_margin_4', 'paidin_capital',
        'paidin_capital_4'
    ]

    def calc(self, data: Dict) -> None:

        roa: pd.DataFrame = data['roa'] # 单位为百分号

        cfo: pd.DataFrame = data['net_operate_cash_flow'] /             data['total_assets']

        delta_roa: pd.DataFrame = roa / data['roa_4'] - 1

        accrual: pd.DataFrame = cfo - roa * 0.01

        # 杠杆变化
        ## 变化为负数时为1，否则为0 取相反
        leveler: pd.DataFrame = data['total_non_current_liability'] /             data['total_non_current_assets']

        leveler1: pd.DataFrame = data['total_non_current_liability_4'] /             data['total_non_current_assets_4']

        delta_leveler: pd.DataFrame = -(leveler / leveler1 - 1)

        # 流动性变化
        liquid: pd.DataFrame = data['total_current_assets'] /             data['total_current_liability']

        liquid_1: pd.DataFrame = data['total_current_assets_4'] /             data['total_current_liability_4']

        delta_liquid: pd.DataFrame = liquid / liquid_1 - 1

        # 毛利率变化
        delta_margin: pd.DataFrame = data['gross_profit_margin'] /             data['gross_profit_margin_4'] - 1

        # 是否发行普通股权
        eq_offser: pd.DataFrame = -(data['paidin_capital'] / data[
            'paidin_capital_4'] - 1)

        # 总资产周转率
        total_asset_turnover_rate: pd.DataFrame = data[
            'operating_revenue'] / (data['total_assets'] +
                                          data['total_assets_1']).mean()

        total_asset_turnover_rate_1: pd.DataFrame = data[
            'operating_revenue_4'] / (data['total_assets_4'] +
                                            data['total_assets_5']).mean()

        # 总资产周转率同比
        delta_turn: pd.DataFrame = total_asset_turnover_rate /             total_asset_turnover_rate_1 - 1

        indicator_tuple: Tuple = (roa, cfo, delta_roa, accrual, delta_leveler,
                                  delta_liquid, delta_margin, delta_turn,
                                  eq_offser)

        # 储存计算FFscore所需原始数据
        self.basic: pd.DataFrame = pd.concat(indicator_tuple).T.replace([-np.inf,np.inf],np.nan)

        self.basic.columns = [
            'ROA', 'CFO', 'DELTA_ROA', 'ACCRUAL', 'DELTA_LEVELER',
            'DLTA_LIQUID', 'DELTA_MARGIN', 'DELTA_TURN', 'EQ_OFFSER'
        ]
        
        self.fscore: pd.Series = self.basic.apply(sign).sum(axis=1)


# In[6]:


# 因子获取
def get_FFScore(
    symbol: str,
    factor: Factor,
    periods: List,
    filter_industry: Union[List,
                           str] = None) -> Tuple[pd.Series, pd.DataFrame]:
    '''
    获取FFScore得分
    ------
    输入参数：
        symbol:输入A表示全A股票池或者输入指数代码
        factor:不同的ffscore模型
        periods:计算得分的时间序列
        filter_industry:传入需要过滤的行业
    ------
    return 最终得分,财务数据
    '''
    for trade in tqdm_notebook(periods, desc='FFScore因子获取'):

        # 获取股票池
        stock_pool_func = Filter_Stocks(symbol, trade)
        stock_pool_func.filter_zdt()
        stock_pool_func.filter_paused(22, 21)  # 过滤22日停牌超过21日的股票
        stock_pool_func.filter_st()  # 过滤st
        stock_pool_func.filter_ipodate(180)  # 过滤次新
        # 是否过滤行业
        if filter_industry:

            stock_pool_func.filter_industry(filter_industry)

        my_factor = factor()
        my_factor.watch_date = trade
        calc_factors(stock_pool_func.securities,[my_factor],start_date=trade,end_date=trade)
        
        yield my_factor


# In[7]:


def quantile_trans(df, tau):
    df_trans = df.apply(lambda x: -1 * (x - x.quantile(tau))**2, axis=1)
    return df_trans

def get_factor_price(security: Union[List, str],
                     periods: List) -> pd.DataFrame:
    '''获取对应频率的收盘价'''
    for trade in tqdm_notebook(periods, desc='获取收盘价数据'):

        yield get_price(security,
                        end_date=trade,
                        count=1,
                        fields='close',
                        fq = 'post',
                        panel=False)


def get_factor_pb_ratio(securities: Union[list, str],
                        periods: list) -> pd.DataFrame:
    '''获取PB数据'''
    for trade in tqdm_notebook(periods, desc='获取PB数据'):

        yield get_valuation(securities,
                            end_date=trade,
                            fields=['pb_ratio'],
                            count=1)

def get_factor_pe_ratio(securities: Union[list, str],
                        periods: list) -> pd.DataFrame:
    '''获取PE数据'''
    for trade in tqdm_notebook(periods, desc='获取PE数据'):

        yield get_valuation(securities,
                            end_date=trade,
                            fields=['pe_ratio'],
                            count=1)        
        
def get_factor_ps_ratio(securities: Union[list, str],
                        periods: list) -> pd.DataFrame:
    '''获取PS数据'''
    for trade in tqdm_notebook(periods, desc='获取PS数据'):

        yield get_valuation(securities,
                            end_date=trade,
                            fields=['ps_ratio'],
                            count=1) 
        
def get_factor_pcf_ratio(securities: Union[list, str],
                        periods: list) -> pd.DataFrame:
    '''获取PCF数据'''
    for trade in tqdm_notebook(periods, desc='获取PCF数据'):

        yield get_valuation(securities,
                            end_date=trade,
                            fields=['pcf_ratio'],
                            count=1)         

        
def get_DP(security,watch_date,days):
    
    # 获取股息数据
    one_year_ago=watch_date-datetime.timedelta(days=days)
    
    q1=query(finance.STK_XR_XD.a_registration_date,finance.STK_XR_XD.bonus_amount_rmb,            finance.STK_XR_XD.code           ).filter(finance.STK_XR_XD.a_registration_date>= one_year_ago,                    finance.STK_XR_XD.a_registration_date<=watch_date,                    finance.STK_XR_XD.code.in_(security[0:int(len(security)*0.3)]))
    q2=query(finance.STK_XR_XD.a_registration_date,finance.STK_XR_XD.bonus_amount_rmb,            finance.STK_XR_XD.code           ).filter(finance.STK_XR_XD.a_registration_date>= one_year_ago,                    finance.STK_XR_XD.a_registration_date<=watch_date,                    finance.STK_XR_XD.code.in_(security[int(len(security)*0.3):int(len(security)*0.6)]))
    q3=query(finance.STK_XR_XD.a_registration_date,finance.STK_XR_XD.bonus_amount_rmb,            finance.STK_XR_XD.code           ).filter(finance.STK_XR_XD.a_registration_date>= one_year_ago,                    finance.STK_XR_XD.a_registration_date<=watch_date,                    finance.STK_XR_XD.code.in_(security[int(len(security)*0.6):]))
    
    
    df_data1=finance.run_query(q1)
    df_data2=finance.run_query(q2)
    df_data3=finance.run_query(q3)
    df_data=pd.concat([df_data1,df_data2,df_data3],axis=0,sort=False)
    df_data.fillna(0,inplace=True)
    
    df_data=df_data.set_index('code')
    df_data=df_data.groupby('code').sum()
    
    #获取市值相关数据
    q01=query(valuation.code,valuation.market_cap).filter(valuation.code.in_(security))
    BP_data=get_fundamentals(q01,date=watch_date)
    BP_data=BP_data.set_index('code')
    
    #合并数据
    data=pd.concat([df_data,BP_data],axis=1,sort=False)
    data.fillna(0,inplace=True)
    data['dp']=(data['bonus_amount_rmb']/10000)/data['market_cap']
#     data1=data.sort_values(by=['股息率'],ascending=False)
    data.reset_index(inplace=True)
    data.rename(columns = {'index':'code'},inplace=True)
    data['day']= watch_date
    data1 = data[['code','day','dp']]
    data1 = data1[data1['dp']!=0]
    return data1
        
        
def get_factor_dp(securities: Union[list, str],
                        periods: list, days: int) -> pd.DataFrame:
    '''获取股息率数据'''
    for trade in tqdm_notebook(periods, desc='获取股息率数据'):

        yield get_DP(security=securities,watch_date=trade,days=days)


# In[8]:


# 设置时间范围
startDt, endDt = '2018-01-01', '2022-12-31'
# 每月初
periods: List = get_trade_period(startDt, endDt, 'M')
# 获取FFScore得分
data_list = list(get_FFScore('A', FScore, periods))

# 因子值
FScore_factor: pd.Series = pd.concat(
    {pd.to_datetime(f.watch_date): f.fscore
     for f in data_list},
    names=['date', 'asset'])

# 基础数据
basic_df: pd.DataFrame = pd.concat({f.watch_date: f.basic
                                    for f in data_list},
                                   names=['date', 'asset'])


# In[9]:


# 储存数据
# FScore_factor.to_frame('FScore').to_csv('FScore.csv')
# basic_df.to_csv('basic.csv')


# In[10]:


FScore_factor = pd.read_csv('FScore.csv', 
                             index_col=[0,1], 
                             parse_dates=[0])

basic_df = pd.read_csv('basic.csv',
                       index_col=[0,1], 
                       parse_dates=[0])


# 股票池
securities = FScore_factor.index.levels[1].tolist()


# ## 数据获取

# In[11]:


# 获取收盘价
price_list = list(get_factor_price(securities, periods))
price_df = pd.concat(price_list)
pivot_price = pd.pivot_table(price_df,
                             index='time',
                             columns='code',
                             values='close')


# In[19]:


benchmark = list(get_factor_price('000300.XSHG', periods))
benchmark = pd.concat(benchmark)
benchmark_ret = benchmark['close'].pct_change()


# # 1. 以下因子可能能衡量股票价格被低估的情况
# **比乔斯基选股模型**是一种基本面价值投资策略，其核心思想是选择市盈率、市净率、股息率等基本面指标较低的股票。其中，低市净率被认为是其重要的选股指标之一，原因有以下几点：
# + 首先，市净率可作为衡量公司估值水平的指标。市净率越低，表明公司股价相对于其净资产价值越便宜，即“买入花费”较少，因此更容易获得较高的回报。在价值投资中，低市净率往往被视为低估公司的标志。
# + 其次，低市净率的公司往往有健康的财务状况。一般来说，低市净率通常与高资产质量和高盈利能力相关。在投资过程中，寻找这些强劲的基本面公司通常会确保您投资的稳健性。
# + 第三，低市净率指标可能是经济周期波动期的风险避险指标。在经济萎缩期间，公司愿意借贷以获得资金，这会增加其负债。因此，价值投资者倾向于选择资产证明的企业，这样即使在经济衰退期间，他们仍然可以获得相对较高的回报。因此，在市场经济周期的下行期，这样的公司往往会受益。
# + 最后，低市净率标志着市场对该公司的低期望。相对较低的市净率说明市场对该公司未来的增长潜力较低。但是，如果一家公司实际上具有强劲的基本面和未来的增长潜力，则它被低估可能会导致投资机会。因此，选择低市净率的股票可能会使投资者获得相对低的价格和更高的回报。
# 
# **综上所述，低市净率通常具有较好的投资性价比和风险避险性，因此比乔斯基选股模型以其作为重要的选股指标，是合理的选择。**
# 
# 1. 市盈率（PE Ratio）：市盈率是指股票的市值与公司的盈利之比。如果股票的市盈率低于同行业股票的平均水平，或者低于公司的历史平均值，就可能表明该股票被低估。
# 2. 市净率（PB Ratio）：市净率是指股票市值与公司账面净资产之比。如果股票的市净率低于同行业股票的平均水平，或者低于公司的历史平均值，就可能表明该股票被低估。
# 3. 股息收益率（Dividend Yield）：股息收益率是指公司派发的股息与股票价格之比。如果某个公司的股息收益率高于同行业平均水平或历史平均值，就表明公司可能被低估。
# 4. 市销率（PS Ratio）：市销率是指股票市值与公司销售额之比。如果股票的市销率低于同行业股票的平均水平，或者低于公司的历史平均值，就可能带表明该股票被低估。
# 5. 价格/现金流比率（Price-to-Cash-Flow Ratio）：价格/现金流比率是指股票价格与公司现金流量之比。如果此比率低于同行业平均值或历史平均值，就可能表明该股票被低估。

# > 为了防止内存不够，统一使用相同的变量名

# ## 1.1 PE因子分层测试

# In[163]:


# 获取PE 这里用的时间段与因子的一致
valuation_list = list(get_factor_pe_ratio(securities,periods))
valuation_df = pd.concat(valuation_list)
pivot_valuation = pd.pivot_table(valuation_df,
                         index='day',
                         columns='code',
                         values='pe_ratio')


# In[164]:


#只取pe为正的
pivot_valuation = pivot_valuation[pivot_valuation > 0]
pivot_valuation.index = pd.to_datetime(pivot_valuation.index)
valuation_ser = pivot_valuation.stack()
valuation_ser.index.names = ['date','asset']
valuation_factor = al.utils.get_clean_factor_and_forward_returns(valuation_ser,
                                                           pivot_price,
                                                           quantiles = 10,
                                                           periods=(1,))


# In[165]:


valuation_ret = pd.pivot_table(valuation_factor.reset_index(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(18, 12))
ax.set_title('pe因子分组收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))

color_map =['#000000', '#800080',  '#FFFF00', '#008000', '#FF6600','#0000FF', '#4B0082', '#008982', '#808080', '#FF0000']
ep.cum_returns(valuation_ret).plot(ax=ax,color=color_map);
Strategy_performance(valuation_ret,'monthly').style.format('{:.2%}')


# ## 1.2 PB因子分层测试

# In[12]:


# 获取PB 这里用的时间段与因子的一致
valuation_list = list(get_factor_pb_ratio(securities,periods))
valuation_df = pd.concat(valuation_list)
pivot_valuation = pd.pivot_table(valuation_df,
                         index='day',
                         columns='code',
                         values='pb_ratio')


# In[92]:


#只取pb为正的
pivot_valuation = pivot_valuation[pivot_valuation > 0]
pivot_valuation.index = pd.to_datetime(pivot_valuation.index)
valuation_ser = pivot_valuation.stack()
valuation_ser.index.names = ['date','asset']
valuation_factor = al.utils.get_clean_factor_and_forward_returns(valuation_ser,
                                                           pivot_price,
                                                           quantiles = 10,
                                                           periods=(1,))
valuation_ret = pd.pivot_table(valuation_factor.reset_index(),index='date',columns='factor_quantile',values=1)


# In[14]:


fig, ax = plt.subplots(figsize=(18, 12))
ax.set_title('pb因子分组收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))

color_map =['#000000', '#800080',  '#FFFF00', '#008000', '#FF6600','#0000FF', '#4B0082', '#008982', '#808080', '#FF0000']
ep.cum_returns(valuation_ret).plot(ax=ax,color=color_map);
Strategy_performance(valuation_ret,'monthly').style.format('{:.2%}')


# In[109]:


#5层分层
valuation_factor = al.utils.get_clean_factor_and_forward_returns(valuation_ser,
                                                           pivot_price,
                                                           quantiles = 5,
                                                           periods=(1,))
valuation_ret = pd.pivot_table(valuation_factor.reset_index(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(18, 12))
ax.set_title('pb因子分组收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))

color_map =['#000000', '#800080',  '#FFFF00', '#008000', '#FF6600','#0000FF', '#4B0082', '#008982', '#808080', '#FF0000']
ep.cum_returns(valuation_ret).plot(ax=ax,color=color_map);
Strategy_performance(valuation_ret,'monthly').style.format('{:.2%}')


# ## 1.3 DP(股息率=最近一年分红/总市值)因子分层测试

# In[172]:


# 获取dp 这里用的时间段与因子的一致
valuation_list = list(get_factor_dp(securities,periods,365))
valuation_df = pd.concat(valuation_list)
pivot_valuation = pd.pivot_table(valuation_df,
                         index='day',
                         columns='code',
                         values='dp')


# In[173]:


pivot_valuation.index = pd.to_datetime(pivot_valuation.index)
valuation_ser = pivot_valuation.stack()
valuation_ser.index.names = ['date','asset']
valuation_factor = al.utils.get_clean_factor_and_forward_returns(valuation_ser,
                                                           pivot_price,
                                                           quantiles = 10,
                                                           periods=(1,))


# In[174]:


valuation_ret = pd.pivot_table(valuation_factor.reset_index(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(18, 12))
ax.set_title('dp因子分组收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))

color_map =['#000000', '#800080',  '#FFFF00', '#008000', '#FF6600','#0000FF', '#4B0082', '#008982', '#808080', '#FF0000']
ep.cum_returns(valuation_ret).plot(ax=ax,color=color_map);
Strategy_performance(valuation_ret,'monthly').style.format('{:.2%}')


# ## 1.4 PS因子分层回测

# In[180]:


# 获取PS 这里用的时间段与因子的一致
valuation_list = list(get_factor_ps_ratio(securities,periods))
valuation_df = pd.concat(valuation_list)
pivot_valuation = pd.pivot_table(valuation_df,
                         index='day',
                         columns='code',
                         values='ps_ratio')


# In[181]:


#只取ps为正的
pivot_valuation = pivot_valuation[pivot_valuation > 0]
pivot_valuation.index = pd.to_datetime(pivot_valuation.index)
valuation_ser = pivot_valuation.stack()
valuation_ser.index.names = ['date','asset']
valuation_factor = al.utils.get_clean_factor_and_forward_returns(valuation_ser,
                                                           pivot_price,
                                                           quantiles = 10,
                                                           periods=(1,))


# In[182]:


valuation_ret = pd.pivot_table(valuation_factor.reset_index(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(18, 12))
ax.set_title('ps因子分组收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))

color_map =['#000000', '#800080',  '#FFFF00', '#008000', '#FF6600','#0000FF', '#4B0082', '#008982', '#808080', '#FF0000']
ep.cum_returns(valuation_ret).plot(ax=ax,color=color_map);
Strategy_performance(valuation_ret,'monthly').style.format('{:.2%}')


# ## 1.5 PCF因子分层回测

# In[186]:


# 获取PCF 这里用的时间段与因子的一致
valuation_list = list(get_factor_pcf_ratio(securities,periods))
valuation_df = pd.concat(valuation_list)
pivot_valuation = pd.pivot_table(valuation_df,
                         index='day',
                         columns='code',
                         values='pcf_ratio')


# In[187]:


#只取pcf为正的
pivot_valuation = pivot_valuation[pivot_valuation > 0]
pivot_valuation.index = pd.to_datetime(pivot_valuation.index)
valuation_ser = pivot_valuation.stack()
valuation_ser.index.names = ['date','asset']
valuation_factor = al.utils.get_clean_factor_and_forward_returns(valuation_ser,
                                                           pivot_price,
                                                           quantiles = 10,
                                                           periods=(1,))


# In[188]:


valuation_ret = pd.pivot_table(valuation_factor.reset_index(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(18, 12))
ax.set_title('pcf因子分组收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))

color_map =['#000000', '#800080',  '#FFFF00', '#008000', '#FF6600','#0000FF', '#4B0082', '#008982', '#808080', '#FF0000']
ep.cum_returns(valuation_ret).plot(ax=ax,color=color_map);
Strategy_performance(valuation_ret,'monthly').style.format('{:.2%}')


# In[ ]:





# In[208]:


dp_list = list(get_factor_dp(securities,price_periods,1825))

dp_df = pd.concat(dp_list)

pivot_dp = pd.pivot_table(dp_df,
                         index='day',
                         columns='code',
                         values='dp')


# In[216]:


pe_list = list(get_factor_pe_ratio(securities,price_periods))

pe_df = pd.concat(pe_list)

pivot_pe = pd.pivot_table(pe_df,
                         index='day',
                         columns='code',
                         values='pe_ratio')


# In[240]:


pivot_pe = pd.pivot_table(pe_df,
                         index='day',
                         columns='code',
                         values='pe_ratio')


# In[237]:


#pivot_pe = pivot_pe.apply(lambda x: -1 * (x - x.quantile(0.5))**2, axis=1)


# In[241]:


pivot_pe.index = pd.to_datetime(pivot_pe.index)
pe_ser = pivot_pe.stack()
pe_ser.index.names = ['date','asset']
pe_factor = al.utils.get_clean_factor_and_forward_returns(pe_ser,
                                                           pivot_price,
                                                           quantiles = 10,
                                                           periods=(1,))


# In[242]:


pe_ret = pd.pivot_table(pe_factor.reset_index(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(18, 12))
ax.set_title('pe因子分组收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))

color_map =['#000000', '#800080',  '#FFFF00', '#008000', '#FF6600','#0000FF', '#4B0082', '#008982', '#808080', '#FF0000']
ep.cum_returns(pe_ret).plot(ax=ax,color=color_map);


# In[243]:


#pivot_dp = pivot_dp.apply(lambda x: -1 * (x - x.quantile(0.8))**2, axis=1)


# # 2 调整FScore构造

# ## 2.1盈利水平

# ### 2.1.1 roa，delta_roa正负分层良好，保留

# In[37]:


fscore_factor_data = al.utils.get_clean_factor_and_forward_returns(basic_df['ROA'],
                                                           pivot_price,
                                                           quantiles = None,
                                                           bins=[-inf,0,inf],
                                                           periods=(1,))
fscore_factor_ret = pd.pivot_table(fscore_factor_data.reset_index(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(9, 5))
ax.set_title('ROA因子分组收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))
color_map = ['#000000', '#800080',  '#FFFF00', '#008000', '#FF6600','#0000FF', '#4B0082', '#008982', '#808080', '#FF0000']
ep.cum_returns(fscore_factor_ret).plot(ax=ax,color=color_map);
# Strategy_performance(fscore_factor_ret,'monthly').style.format('{:.2%}')


# In[38]:


fscore_factor_data = al.utils.get_clean_factor_and_forward_returns(basic_df['DELTA_ROA'],
                                                           pivot_price,
                                                           quantiles = None,
                                                           bins=[-inf,0,inf],
                                                           periods=(1,))
fscore_factor_ret = pd.pivot_table(fscore_factor_data.reset_index(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(9, 5))
ax.set_title('DELTA_ROA因子分组收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))
color_map = ['#000000', '#800080',  '#FFFF00', '#008000', '#FF6600','#0000FF', '#4B0082', '#008982', '#808080', '#FF0000']
ep.cum_returns(fscore_factor_ret).plot(ax=ax,color=color_map);
# Strategy_performance(fscore_factor_ret,'monthly').style.format('{:.2%}')


# ### 2.1.2 CFO与ACCRUAL正负分层不明显，删除

# In[40]:


fscore_factor_data = al.utils.get_clean_factor_and_forward_returns(basic_df['CFO'],
                                                           pivot_price,
                                                           quantiles = None,
                                                           bins=[-inf,0,inf],
                                                           periods=(1,))
fscore_factor_ret = pd.pivot_table(fscore_factor_data.reset_index(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(9, 5))
ax.set_title('CFO因子分组收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))
color_map = ['#000000', '#800080',  '#FFFF00', '#008000', '#FF6600','#0000FF', '#4B0082', '#008982', '#808080', '#FF0000']
ep.cum_returns(fscore_factor_ret).plot(ax=ax,color=color_map);
Strategy_performance(fscore_factor_ret,'monthly').style.format('{:.2%}')


# In[41]:


fscore_factor_data = al.utils.get_clean_factor_and_forward_returns(basic_df['ACCRUAL'],
                                                           pivot_price,
                                                           quantiles = None,
                                                           bins=[-inf,0,inf],
                                                           periods=(1,))
fscore_factor_ret = pd.pivot_table(fscore_factor_data.reset_index(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(9, 5))
ax.set_title('ACCRUAL因子分组收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))
color_map = ['#000000', '#800080',  '#FFFF00', '#008000', '#FF6600','#0000FF', '#4B0082', '#008982', '#808080', '#FF0000']
ep.cum_returns(fscore_factor_ret).plot(ax=ax,color=color_map);
Strategy_performance(fscore_factor_ret,'monthly').style.format('{:.2%}')


# ### 2.1.3 CFO与ACCRUAL构造修改

# net_operate_cash_flow 	经营活动产生的现金流量净额(元) 	公式: 经营活动产生的现金流量净额, 是指某一季度，故将四个季度相加
# 
# total_assets 	资产总计(元) 这里取ttm

# `cfo_sum: pd.DataFrame = (data['net_operate_cash_flow']+data['net_operate_cash_flow_1']+data['net_operate_cash_flow_2']+data['net_operate_cash_flow_3'])`
# 
# `fcfo: pd.DataFrame = data['net_operate_cash_flow'] / \
#             data['total_assets']`

# > 以下针对CFO和ACCRUAL单因子测试

# In[71]:


#单因子测试
class CFOA(Factor):
    '''
    FScore原始模型
    '''
    name = 'CFOA'
    max_window = 1

    watch_date = None
    # paidin_capital 实收资本 股本变化会反应在该科目中
    dependencies = ['roa','net_operate_cash_flow','net_operate_cash_flow_1','net_operate_cash_flow_2'
                    ,'net_operate_cash_flow_3','net_operate_cash_flow_4','total_assets','total_assets_1'
                    ,'total_assets_2','total_assets_3','total_assets_4',
    
    ]

    def calc(self, data: Dict) -> None:
        roa: pd.DataFrame = data['roa']
            
        
        cfo_sum: pd.DataFrame = (data['net_operate_cash_flow']+data['net_operate_cash_flow_1']+data['net_operate_cash_flow_2']+            data['net_operate_cash_flow_3'])
            
        tt_ttm: pd.DataFrame = (data['total_assets']+data['total_assets_1']+data['total_assets_2']+            data['total_assets_3'])/4
        
        fcfo: pd.DataFrame = data['net_operate_cash_flow'] /             data['total_assets']
        
        fcfoa: pd.DataFrame = cfo_sum/tt_ttm
            
        fcfoa1: pd.DataFrame = cfo_sum/data['total_assets']

        accrual: pd.DataFrame = fcfoa - roa * 0.01
            
        accrual1: pd.DataFrame = fcfoa1 - roa * 0.01

        indicator_tuple: Tuple = (roa,cfo_sum,tt_ttm,fcfo,fcfoa,fcfoa1,accrual,accrual1)

        # 储存计算FFscore所需原始数据
        self.basic: pd.DataFrame = pd.concat(indicator_tuple).T.replace([-np.inf,np.inf],np.nan)
        self.basic.columns = [
            'roa','cfo_sum','tt_ttm','fcfo','fcfoa','fcfoa1','accrual','accrual1'
        ]


# In[55]:


data_list = list(get_FFScore('A', CFOA, periods))


# In[61]:


# basic_df1 = pd.read_csv('basic1.csv',
#                        index_col=[0,1], 
#                        parse_dates=[0])


# > 测试结束，输出basic_df1，具体列名详见函数

# In[72]:


fscore_factor_data = al.utils.get_clean_factor_and_forward_returns(basic_df1['fcfoa'],
                                                           pivot_price,
                                                           quantiles = None,
                                                           bins=[-inf,0,inf],
                                                           periods=(1,))
fscore_factor_ret = pd.pivot_table(fscore_factor_data.reset_index(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(9, 5))
ax.set_title('OCFOA因子分组收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))
color_map = ['#000000', '#800080',  '#FFFF00', '#008000', '#FF6600','#0000FF', '#4B0082', '#008982', '#808080', '#FF0000']
ep.cum_returns(fscore_factor_ret).plot(ax=ax,color=color_map);
Strategy_performance(fscore_factor_ret,'monthly').style.format('{:.2%}')


# In[74]:


#可选择删除
fscore_factor_data = al.utils.get_clean_factor_and_forward_returns(basic_df1['accrual'],
                                                           pivot_price,
                                                           quantiles = None,
                                                           bins=[-inf,0,inf],
                                                           periods=(1,))
fscore_factor_ret = pd.pivot_table(fscore_factor_data.reset_index(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(9, 5))
ax.set_title('ACCRUAL因子分组收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))
color_map = ['#000000', '#800080',  '#FFFF00', '#008000', '#FF6600','#0000FF', '#4B0082', '#008982', '#808080', '#FF0000']
ep.cum_returns(fscore_factor_ret).plot(ax=ax,color=color_map);
Strategy_performance(fscore_factor_ret,'monthly').style.format('{:.2%}')


# ## 2.2 财务杠杆和流动性

# ### 2.2.1 DELTA_LEVELER，DLTA_LIQUID，EQ_OFFSER正负分层均表现不好，删除

# In[80]:


fscore_factor_data = al.utils.get_clean_factor_and_forward_returns(basic_df['DELTA_LEVELER'],
                                                           pivot_price,
                                                           quantiles = None,
                                                           bins=[-inf,0,inf],
                                                           periods=(1,))
fscore_factor_ret = pd.pivot_table(fscore_factor_data.reset_index(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(9, 5))
ax.set_title('DELTA_LEVELER因子分组收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))
color_map = ['#000000', '#800080',  '#FFFF00', '#008000', '#FF6600','#0000FF', '#4B0082', '#008982', '#808080', '#FF0000']
ep.cum_returns(fscore_factor_ret).plot(ax=ax,color=color_map);
Strategy_performance(fscore_factor_ret,'monthly').style.format('{:.2%}')


# In[81]:


fscore_factor_data = al.utils.get_clean_factor_and_forward_returns(basic_df['DLTA_LIQUID'],
                                                           pivot_price,
                                                           quantiles = None,
                                                           bins=[-inf,0,inf],
                                                           periods=(1,))
fscore_factor_ret = pd.pivot_table(fscore_factor_data.reset_index(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(9, 5))
ax.set_title('DLTA_LIQUID因子分组收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))
color_map = ['#000000', '#800080',  '#FFFF00', '#008000', '#FF6600','#0000FF', '#4B0082', '#008982', '#808080', '#FF0000']
ep.cum_returns(fscore_factor_ret).plot(ax=ax,color=color_map);
Strategy_performance(fscore_factor_ret,'monthly').style.format('{:.2%}')


# In[82]:


fscore_factor_data = al.utils.get_clean_factor_and_forward_returns(basic_df['EQ_OFFSER'],
                                                           pivot_price,
                                                           quantiles = None,
                                                           bins=[-inf,0,inf],
                                                           periods=(1,))
fscore_factor_ret = pd.pivot_table(fscore_factor_data.reset_index(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(9, 5))
ax.set_title('EQ_OFFSER因子分组收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))
color_map = ['#000000', '#800080',  '#FFFF00', '#008000', '#FF6600','#0000FF', '#4B0082', '#008982', '#808080', '#FF0000']
ep.cum_returns(fscore_factor_ret).plot(ax=ax,color=color_map);
Strategy_performance(fscore_factor_ret,'monthly').style.format('{:.2%}')


# >以下针对财务杠杆和流动性测试

# In[85]:


class LEVELER(Factor):

    name = 'LEVELER'
    max_window = 1

    watch_date = None
    # paidin_capital 实收资本 股本变化会反应在该科目中
    dependencies = ['total_non_current_liability','total_non_current_liability_1','total_non_current_liability_4',
                    'total_assets','total_assets_1','total_assets_4','total_current_assets','total_current_assets_1',
                    'total_current_assets_4','total_current_liability','total_current_liability_1','total_current_liability_4']

    def calc(self, data: Dict) -> None:
        leveler: pd.DataFrame = data['total_non_current_liability'] / data['total_assets']
        leveler1: pd.DataFrame = data['total_non_current_liability_1'] / data['total_assets_1']
        leveler4: pd.DataFrame = data['total_non_current_liability_4'] / data['total_assets_4']
            
        delta_leveler1: pd.DataFrame = -(leveler / leveler1 - 1)
        delta_leveler4: pd.DataFrame = -(leveler / leveler4 - 1)

        liquid: pd.DataFrame = data['total_current_assets'] / data['total_current_liability']
        liquid_1: pd.DataFrame = data['total_current_assets_1'] / data['total_current_liability_1']
        liquid_4: pd.DataFrame = data['total_current_assets_4'] / data['total_current_liability_4']

        delta_liquid1: pd.DataFrame = liquid / liquid_1 - 1
        delta_liquid4: pd.DataFrame = liquid / liquid_4 - 1
            
        #股本增发暂时不处理
        indicator_tuple: Tuple = (delta_leveler1,delta_leveler4,delta_liquid1,delta_liquid4)

        # 储存计算FFscore所需原始数据
        self.basic: pd.DataFrame = pd.concat(indicator_tuple).T.replace([-np.inf,np.inf],np.nan)
        self.basic.columns = [
            'delta_leveler1','delta_leveler4','delta_liquid1','delta_liquid4'
        ]


# In[86]:


data_list = list(get_FFScore('A', LEVELER, periods))


# In[88]:


# # 基础数据
# basic_df1: pd.DataFrame = pd.concat({f.watch_date: f.basic
#                                     for f in data_list},
#                                    names=['date', 'asset'])
# # 储存数据
# basic_df1.to_csv('basic1.csv')

basic_df1 = pd.read_csv('basic1.csv',
                       index_col=[0,1], 
                       parse_dates=[0])


# > 测试结束

# ### 2.2.2 只保留修改后的delta_leveler

# In[92]:


fscore_factor_data = al.utils.get_clean_factor_and_forward_returns(basic_df1['delta_leveler1'],
                                                           pivot_price,
                                                           quantiles = None,
                                                           bins=[-inf,0,inf],
                                                           periods=(1,))
fscore_factor_ret = pd.pivot_table(fscore_factor_data.reset_index(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(9, 5))
ax.set_title('delta_leveler1因子分组收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))
color_map = ['#000000', '#800080',  '#FFFF00', '#008000', '#FF6600','#0000FF', '#4B0082', '#008982', '#808080', '#FF0000']
ep.cum_returns(fscore_factor_ret).plot(ax=ax,color=color_map);
Strategy_performance(fscore_factor_ret,'monthly').style.format('{:.2%}')


# In[95]:


fscore_factor_data = al.utils.get_clean_factor_and_forward_returns(basic_df1['delta_liquid1'],
                                                           pivot_price,
                                                           quantiles = None,
                                                           bins=[-inf,0,inf],
                                                           periods=(1,))
fscore_factor_ret = pd.pivot_table(fscore_factor_data.reset_index(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(9, 5))
ax.set_title('delta_liquid1因子分组收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))
color_map = ['#000000', '#800080',  '#FFFF00', '#008000', '#FF6600','#0000FF', '#4B0082', '#008982', '#808080', '#FF0000']
ep.cum_returns(fscore_factor_ret).plot(ax=ax,color=color_map);
Strategy_performance(fscore_factor_ret,'monthly').style.format('{:.2%}')


# ## 2.3 运营效率：分离均不错，保留
# 代表了运营效率的指标为毛利润率变化( ΔMARGIN )与资产周转率变化( ΔTURN )。毛利润的增加意味着公司的成本降低或者产品售价提高。资产周转率增加则反映了公司运营周转效率的提升。因此，这两个指标有效的表示了企业在运营方面的能力提高，从而为其未来生存竞争力与公司的成长提供有力的支持。

# In[96]:


fscore_factor_data = al.utils.get_clean_factor_and_forward_returns(basic_df['DELTA_MARGIN'],
                                                           pivot_price,
                                                           quantiles = None,
                                                           bins=[-inf,0,inf],
                                                           periods=(1,))
fscore_factor_ret = pd.pivot_table(fscore_factor_data.reset_index(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(9, 5))
ax.set_title('DELTA_MARGIN因子分组收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))
color_map = ['#000000', '#800080',  '#FFFF00', '#008000', '#FF6600','#0000FF', '#4B0082', '#008982', '#808080', '#FF0000']
ep.cum_returns(fscore_factor_ret).plot(ax=ax,color=color_map);
Strategy_performance(fscore_factor_ret,'monthly').style.format('{:.2%}')


# In[97]:


fscore_factor_data = al.utils.get_clean_factor_and_forward_returns(basic_df['DELTA_TURN'],
                                                           pivot_price,
                                                           quantiles = None,
                                                           bins=[-inf,0,inf],
                                                           periods=(1,))
fscore_factor_ret = pd.pivot_table(fscore_factor_data.reset_index(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(9, 5))
ax.set_title('DELTA_TURN因子分组收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))
color_map = ['#000000', '#800080',  '#FFFF00', '#008000', '#FF6600','#0000FF', '#4B0082', '#008982', '#808080', '#FF0000']
ep.cum_returns(fscore_factor_ret).plot(ax=ax,color=color_map);
Strategy_performance(fscore_factor_ret,'monthly').style.format('{:.2%}')


# ## 2.4 重构后的FScore模型——RFScore(7分制)

# In[98]:




class RFScore(Factor):
    '''
    RFScore原始模型
    '''
    name = 'RFScore'
    max_window = 1

    watch_date = None
    # paidin_capital 实收资本 股本变化会反应在该科目中
    dependencies = [
        'roa', 'roa_4','net_operate_cash_flow','net_operate_cash_flow_1','net_operate_cash_flow_2',
        'net_operate_cash_flow_3','total_assets','total_assets_1','total_assets_2','total_assets_3',
        'total_assets_4','total_assets_5',
        'total_non_current_liability','total_non_current_liability_1','gross_profit_margin',
        'gross_profit_margin_4','operating_revenue','operating_revenue_4'
    ]

    def calc(self, data: Dict) -> None:

        roa: pd.DataFrame = data['roa'] # 单位为百分号

        delta_roa: pd.DataFrame = roa / data['roa_4'] - 1

        cfo_sum: pd.DataFrame = (data['net_operate_cash_flow']+data['net_operate_cash_flow_1']+data['net_operate_cash_flow_2']+            data['net_operate_cash_flow_3'])
        
        ta_ttm: pd.DataFrame = (data['total_assets']+data['total_assets_1']+data['total_assets_2']+            data['total_assets_3'])/4
            
        ocfoa: pd.DataFrame = cfo_sum/ta_ttm
            
        accrual: pd.DataFrame = ocfoa - roa * 0.01
            
        #杠杆变化    
        leveler: pd.DataFrame = data['total_non_current_liability'] / data['total_assets']
        leveler1: pd.DataFrame = data['total_non_current_liability_1'] / data['total_assets_1']    

            
        delta_leveler: pd.DataFrame = -(leveler / leveler1 - 1)
            
        # 毛利率变化
        delta_margin: pd.DataFrame = data['gross_profit_margin'] /             data['gross_profit_margin_4'] - 1
            
        # 总资产周转率
        total_asset_turnover_rate: pd.DataFrame = data[
            'operating_revenue'] / (data['total_assets'] +
                                          data['total_assets_1']).mean()

        total_asset_turnover_rate_1: pd.DataFrame = data[
            'operating_revenue_4'] / (data['total_assets_4'] +
                                            data['total_assets_5']).mean()

        # 总资产周转率同比
        delta_turn: pd.DataFrame = total_asset_turnover_rate /             total_asset_turnover_rate_1 - 1
        
        
        indicator_tuple: Tuple = (roa, delta_roa, ocfoa, accrual, delta_leveler,
                                   delta_margin, delta_turn)
        # 储存计算RFscore所需原始数据
        self.basic: pd.DataFrame = pd.concat(indicator_tuple).T.replace([-np.inf,np.inf],np.nan)
        
        
        self.basic.columns = [
            'ROA', 'DELTA_ROA', 'OCFOA','ACCRUAL', 'DELTA_LEVELER',
             'DELTA_MARGIN', 'DELTA_TURN',]
        
        self.fscore: pd.Series = self.basic.apply(sign).sum(axis=1)


# In[99]:


data_list = list(get_FFScore('A', RFScore, periods))


# In[100]:


# 因子值
RFScore_factor: pd.Series = pd.concat(
    {pd.to_datetime(f.watch_date): f.fscore
     for f in data_list},
    names=['date', 'asset'])

# 基础数据
Rbasic_df: pd.DataFrame = pd.concat({f.watch_date: f.basic
                                    for f in data_list},
                                   names=['date', 'asset'])


# In[101]:


# 储存数据
# RFScore_factor.to_frame('RFScore').to_csv('RFScore.csv')
# Rbasic_df.to_csv('Rbasic.csv')


# In[62]:


RFScore_factor = pd.read_csv('RFScore.csv', 
                             index_col=[0,1], 
                             parse_dates=[0])
Rbasic_df = pd.read_csv('Rbasic.csv',
                       index_col=[0,1], 
                       parse_dates=[0])


# # 3 修改后的FScore模型与原模型比较：以PB为例

# In[ ]:





# ## 3.1 原模型

# In[15]:


plt.title('FScore值分布情况')
FScore_factor['FScore'].hist();


# In[20]:


fscore_factor_data = al.utils.get_clean_factor_and_forward_returns(FScore_factor,
                                                           pivot_price,
                                                           quantiles = None,
                                                           bins=[0,1,2,3,4,5,6,7,8,9],
                                                           periods=(1,))
fscore_factor_ret = pd.pivot_table(fscore_factor_data.reindex(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(15, 8))
ax.set_title('RFScore累计收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))
ep.cum_returns(fscore_factor_ret).plot(ax=ax,color=['#FFAA00', '#FFD700', '#5F9EA0', '#8A2BE2', '#FF69B4', '#00FF00', '#DC143C', '#1E90FF', '#FF4500'])
ep.cum_returns(benchmark_ret.reindex(fscore_factor_ret.index)).plot(ax=ax,
                                   label='HS300',
                                   color='darkgray',
                                   ls='--')
ax.axhline(0, color='black', lw=1)
plt.legend();
Strategy_performance(fscore_factor_ret,'monthly').style.format('{:.2%}')


# In[21]:


df = fscore_factor_data.copy()
df['Fundamental_group'] = valuation_factor['factor_quantile']
df.head()


# ### 3.1.1 FScore9分与PB10%，数量太少，无法形成比较

# In[24]:


cross_df = df.query('Fundamental_group == 1 and factor_quantile == 9')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基9指标模型策略')

all_ret = pd.concat((cross_ret[9],fscore_factor_ret[9],valuation_ret[1],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基9指标模型策略','FScore9分组','PB因子(10%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')


# In[23]:


cross_df.groupby(level='date')['factor'].count().plot(title='持仓数量',figsize=(18,4));


# ### 3.1.2 FScore8-9分与PB10%

# In[91]:


fscore_factor_data = al.utils.get_clean_factor_and_forward_returns(FScore_factor,
                                                           pivot_price,
                                                           quantiles = None,
                                                           bins=[0,1,2,3,4,5,6,7,9],
                                                           periods=(1,))
fscore_factor_ret = pd.pivot_table(fscore_factor_data.reindex(),index='date',columns='factor_quantile',values=1)


# In[93]:


df = fscore_factor_data.copy()
df['Fundamental_group'] = valuation_factor['factor_quantile']
df.head()


# In[94]:


cross_df = df.query('Fundamental_group == 1 and factor_quantile == 8')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基9指标模型策略')

all_ret = pd.concat((cross_ret[8],fscore_factor_ret[8],valuation_ret[1],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基9指标模型策略','FScore8-9分组','PB因子(10%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')


# In[95]:


cross_df.groupby(level='date')['factor'].count().plot(title='持仓数量',figsize=(18,4));


# In[96]:


cross_df['industry'] = cross_df.groupby(
    level='date').apply(lambda x: get_stock_ind(
        x.index.get_level_values(1).values.tolist(), x.name, 'sw_l1',
        'industry_name'))
cross_df.groupby('industry')[1].count().sort_values(ascending=False).plot.bar(
    color='r', figsize=(18, 5), title='各行业入选次数',rot=25);


# In[97]:


fig,ax = plt.subplots(figsize=(18,5))

ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'{:.2%}'.format(x * 100)))
cross_df.groupby('industry')[1].mean().sort_values(ascending=False).plot.bar(
    color='r', figsize=(18, 5),title='每期收益贡献',ax=ax,rot=25)
plt.axhline(0);


# In[107]:


cross_df[cross_df['industry']=='有色金属I']


# In[108]:


cross_df[cross_df['industry']=='农林牧渔I']


# ### 3.1.2 FScore8-9分与PB20%

# In[47]:


df = fscore_factor_data.copy()
df['Fundamental_group'] = valuation_factor['factor_quantile']
df.head()


# In[48]:


cross_df = df.query('Fundamental_group == 1 and factor_quantile == 8')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基9指标模型策略')

all_ret = pd.concat((cross_ret[8],fscore_factor_ret[8],valuation_ret[1],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基9指标模型策略','FScore8-9分组','PB因子(20%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')


# In[49]:


cross_df.groupby(level='date')['factor'].count().plot(title='持仓数量',figsize=(18,4));


# In[50]:


cross_df['industry'] = cross_df.groupby(
    level='date').apply(lambda x: get_stock_ind(
        x.index.get_level_values(1).values.tolist(), x.name, 'sw_l1',
        'industry_name'))


# In[52]:


cross_df.groupby('industry')[1].count().sort_values(ascending=False).plot.bar(
    color='r', figsize=(18, 5), title='各行业入选次数',rot=25);


# In[54]:


fig,ax = plt.subplots(figsize=(18,5))

ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'{:.2%}'.format(x * 100)))
cross_df.groupby('industry')[1].mean().sort_values(ascending=False).plot.bar(
    color='r', figsize=(18, 5),title='每期收益贡献',ax=ax,rot=25)
plt.axhline(0);


# ## 3.2 修改后的FScore模型

# In[63]:


plt.title('RFScore值分布情况')
RFScore_factor['RFScore'].hist();


# In[109]:


plt.title('RFScore值分布情况')
RFScore_factor['RFScore'].hist();


# In[121]:


fscore_factor_data  = al.utils.get_clean_factor_and_forward_returns(RFScore_factor,
                                                           pivot_price,
                                                           quantiles = None,
                                                           bins=[0,1,2,3,4,5,6,7],
                                                           periods=(1,))
fscore_factor_ret = pd.pivot_table(fscore_factor_data.reindex(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(15, 8))
ax.set_title('RFScore累计收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))
ep.cum_returns(fscore_factor_ret).plot(ax=ax,color=['#FFAA00', '#FFD700', '#5F9EA0', '#8A2BE2', '#FF69B4', '#00FF00', '#DC143C', '#1E90FF', '#FF4500'])
ep.cum_returns(benchmark_ret.reindex(fscore_factor_ret.index)).plot(ax=ax,
                                   label='HS300',
                                   color='darkgray',
                                   ls='--')
ax.axhline(0, color='black', lw=1)
plt.legend();
Strategy_performance(fscore_factor_ret,'monthly').style.format('{:.2%}')


# In[64]:


fscore_factor_data  = al.utils.get_clean_factor_and_forward_returns(RFScore_factor,
                                                           pivot_price,
                                                           quantiles = None,
                                                           bins=[0,1,2,3,4,5,6,7],
                                                           periods=(1,))
fscore_factor_ret = pd.pivot_table(fscore_factor_data.reindex(),index='date',columns='factor_quantile',values=1)
fig, ax = plt.subplots(figsize=(15, 8))
ax.set_title('RFScore累计收益')
ax.yaxis.set_major_formatter(
    mpl.ticker.FuncFormatter(lambda x, pos: '%.2f%%' % (x * 100)))
ep.cum_returns(fscore_factor_ret).plot(ax=ax,color=['#FFAA00', '#FFD700', '#5F9EA0', '#8A2BE2', '#FF69B4', '#00FF00', '#DC143C', '#1E90FF', '#FF4500'])
ep.cum_returns(benchmark_ret.reindex(fscore_factor_ret.index)).plot(ax=ax,
                                   label='HS300',
                                   color='darkgray',
                                   ls='--')
ax.axhline(0, color='black', lw=1)
plt.legend();
Strategy_performance(fscore_factor_ret,'monthly').style.format('{:.2%}')


# ### 3.2.1 RFScore7分与PB10%

# In[78]:


#只取pb为正的

valuation_factor = al.utils.get_clean_factor_and_forward_returns(valuation_ser,
                                                           pivot_price,
                                                           quantiles = 10,
                                                           periods=(1,))
valuation_ret = pd.pivot_table(valuation_factor.reset_index(),index='date',columns='factor_quantile',values=1)


# In[79]:


#给出对应RFScore与PB因子对应层数
df = fscore_factor_data.copy()
df['Fundamental_group'] = valuation_factor['factor_quantile']
df.head()


# In[80]:



cross_df = df.query('Fundamental_group == 1 and factor_quantile == 7')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基7指标模型策略')

all_ret = pd.concat((cross_ret[7],fscore_factor_ret[7],valuation_ret[1],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基7指标模型策略','RFScore7分组','PB因子(10%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')


# In[81]:


cross_df.groupby(level='date')['factor'].count().plot(title='持仓数量',figsize=(18,4));


# In[82]:


cross_df['industry'] = cross_df.groupby(
    level='date').apply(lambda x: get_stock_ind(
        x.index.get_level_values(1).values.tolist(), x.name, 'sw_l1',
        'industry_name'))
cross_df.groupby('industry')[1].count().sort_values(ascending=False).plot.bar(
    color='r', figsize=(18, 5), title='各行业入选次数',rot=25);


# In[83]:


fig,ax = plt.subplots(figsize=(18,5))

ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'{:.2%}'.format(x * 100)))
cross_df.groupby('industry')[1].mean().sort_values(ascending=False).plot.bar(
    color='r', figsize=(18, 5),title='每期收益贡献',ax=ax,rot=25)
plt.axhline(0);


# ### 3.2.2 RFScore7分与PB20%

# In[84]:


#将20%单独分离出来
valuation_factor = al.utils.get_clean_factor_and_forward_returns(valuation_ser,
                                                           pivot_price,
                                                           quantiles = 5,
                                                           periods=(1,))
valuation_ret = pd.pivot_table(valuation_factor.reset_index(),index='date',columns='factor_quantile',values=1)


# In[85]:


valuation_factor.head()


# In[86]:


#给出对应RFScore与PB因子对应层数
df = fscore_factor_data.copy()
df['Fundamental_group'] = valuation_factor['factor_quantile']
df.head()


# In[87]:



cross_df = df.query('Fundamental_group == 1 and factor_quantile == 7')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基7指标模型策略')

all_ret = pd.concat((cross_ret[7],fscore_factor_ret[7],valuation_ret[1],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基7指标模型策略','RFScore7分组','PB因子(20%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')


# In[88]:


cross_df.groupby(level='date')['factor'].count().plot(title='持仓数量',figsize=(18,4));


# In[89]:


cross_df['industry'] = cross_df.groupby(
    level='date').apply(lambda x: get_stock_ind(
        x.index.get_level_values(1).values.tolist(), x.name, 'sw_l1',
        'industry_name'))
cross_df.groupby('industry')[1].count().sort_values(ascending=False).plot.bar(
    color='r', figsize=(18, 5), title='各行业入选次数',rot=25);


# In[90]:


fig,ax = plt.subplots(figsize=(18,5))

ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'{:.2%}'.format(x * 100)))
cross_df.groupby('industry')[1].mean().sort_values(ascending=False).plot.bar(
    color='r', figsize=(18, 5),title='每期收益贡献',ax=ax,rot=25)
plt.axhline(0);


# ### 3.2.3 RFScore7分与PB后9层

# In[147]:


#将20%单独分离出来
valuation_factor = al.utils.get_clean_factor_and_forward_returns(valuation_ser,
                                                           pivot_price,
                                                           quantiles = 10,
                                                           periods=(1,))
valuation_ret = pd.pivot_table(valuation_factor.reset_index(),index='date',columns='factor_quantile',values=1)


# In[148]:


#给出对应RFScore与PB因子对应层数
df = fscore_factor_data.copy()
df['Fundamental_group'] = valuation_factor['factor_quantile']
df.head()


# In[149]:


cross_df = df.query('Fundamental_group == 2 and factor_quantile == 7')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基7指标模型策略')

all_ret = pd.concat((cross_ret[7],fscore_factor_ret[7],valuation_ret[2],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基7指标模型策略','RFScore7分组','PB因子(10-20%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')


# In[150]:


cross_df = df.query('Fundamental_group == 3 and factor_quantile == 7')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基7指标模型策略')

all_ret = pd.concat((cross_ret[7],fscore_factor_ret[7],valuation_ret[3],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基7指标模型策略','RFScore7分组','PB因子(20-30%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')


# In[152]:


cross_df = df.query('Fundamental_group == 4 and factor_quantile == 7')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基7指标模型策略')

all_ret = pd.concat((cross_ret[7],fscore_factor_ret[7],valuation_ret[4],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基7指标模型策略','RFScore7分组','PB因子(30-40%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')


# In[153]:


cross_df = df.query('Fundamental_group == 5 and factor_quantile == 7')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基7指标模型策略')

all_ret = pd.concat((cross_ret[7],fscore_factor_ret[7],valuation_ret[5],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基7指标模型策略','RFScore7分组','PB因子(40-50%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')


# In[162]:


cross_df = df.query('Fundamental_group == 6 and factor_quantile == 7')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基7指标模型策略')

all_ret = pd.concat((cross_ret[7],fscore_factor_ret[7],valuation_ret[6],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基7指标模型策略','RFScore7分组','PB因子(50-60%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')


# In[161]:


cross_df = df.query('Fundamental_group == 7 and factor_quantile == 7')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基7指标模型策略')

all_ret = pd.concat((cross_ret[7],fscore_factor_ret[7],valuation_ret[7],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基7指标模型策略','RFScore7分组','PB因子(60-70%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')


# In[160]:


cross_df = df.query('Fundamental_group == 8 and factor_quantile == 7')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基7指标模型策略')

all_ret = pd.concat((cross_ret[7],fscore_factor_ret[7],valuation_ret[8],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基7指标模型策略','RFScore7分组','PB因子(70-80%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')


# In[158]:


cross_df = df.query('Fundamental_group == 9 and factor_quantile == 7')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基7指标模型策略')

all_ret = pd.concat((cross_ret[7],fscore_factor_ret[7],valuation_ret[9],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基7指标模型策略','RFScore7分组','PB因子(80-90%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')


# In[159]:


cross_df = df.query('Fundamental_group == 10 and factor_quantile == 7')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基7指标模型策略')

all_ret = pd.concat((cross_ret[7],fscore_factor_ret[7],valuation_ret[10],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基7指标模型策略','RFScore7分组','PB因子(90-100%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')


# # 4 改变基本面因子：PE,DP,PS,PCF

# ## 4.1PE，无效

# In[166]:


valuation_factor = al.utils.get_clean_factor_and_forward_returns(valuation_ser,
                                                           pivot_price,
                                                           quantiles = 10,
                                                           periods=(1,))
valuation_ret = pd.pivot_table(valuation_factor.reset_index(),index='date',columns='factor_quantile',values=1)


# In[167]:


#给出对应RFScore与PB因子对应层数
df = fscore_factor_data.copy()
df['Fundamental_group'] = valuation_factor['factor_quantile']
df.head()


# In[168]:



cross_df = df.query('Fundamental_group == 1 and factor_quantile == 7')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基7指标模型策略')

all_ret = pd.concat((cross_ret[7],fscore_factor_ret[7],valuation_ret[1],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基7指标模型策略','RFScore7分组','PE因子(10%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')


# In[169]:


valuation_factor = al.utils.get_clean_factor_and_forward_returns(valuation_ser,
                                                           pivot_price,
                                                           quantiles = 5,
                                                           periods=(1,))
valuation_ret = pd.pivot_table(valuation_factor.reset_index(),index='date',columns='factor_quantile',values=1)


# In[170]:


df = fscore_factor_data.copy()
df['Fundamental_group'] = valuation_factor['factor_quantile']
df.head()


# In[171]:


cross_df = df.query('Fundamental_group == 1 and factor_quantile == 7')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基7指标模型策略')

all_ret = pd.concat((cross_ret[7],fscore_factor_ret[7],valuation_ret[1],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基7指标模型策略','RFScore7分组','PE因子(20%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')


# ## 4.2 DP因子：结合效果稍好，但比RFScore7分效果差

# In[175]:


df = fscore_factor_data.copy()
df['Fundamental_group'] = valuation_factor['factor_quantile']
df.head()


# In[176]:



cross_df = df.query('Fundamental_group == 1 and factor_quantile == 7')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基7指标模型策略')

all_ret = pd.concat((cross_ret[7],fscore_factor_ret[7],valuation_ret[1],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基7指标模型策略','RFScore7分组','DP因子(10%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')


# In[177]:


pivot_valuation.index = pd.to_datetime(pivot_valuation.index)
valuation_ser = pivot_valuation.stack()
valuation_ser.index.names = ['date','asset']
valuation_factor = al.utils.get_clean_factor_and_forward_returns(valuation_ser,
                                                           pivot_price,
                                                           quantiles = 5,
                                                           periods=(1,))


# In[178]:


df = fscore_factor_data.copy()
df['Fundamental_group'] = valuation_factor['factor_quantile']
df.head()


# In[179]:



cross_df = df.query('Fundamental_group == 1 and factor_quantile == 7')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基7指标模型策略')

all_ret = pd.concat((cross_ret[7],fscore_factor_ret[7],valuation_ret[1],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基7指标模型策略','RFScore7分组','DP因子(20%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')


# ## 4.3 PS因子：无效

# In[183]:


df = fscore_factor_data.copy()
df['Fundamental_group'] = valuation_factor['factor_quantile']
df.head()


# In[184]:



cross_df = df.query('Fundamental_group == 1 and factor_quantile == 7')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基7指标模型策略')

all_ret = pd.concat((cross_ret[7],fscore_factor_ret[7],valuation_ret[1],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基7指标模型策略','RFScore7分组','PS因子(10%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')


# ## 4.4 PCF因子：结合效果一般，依然比RFScore7分差

# In[189]:


df = fscore_factor_data.copy()
df['Fundamental_group'] = valuation_factor['factor_quantile']
df.head()


# In[190]:



cross_df = df.query('Fundamental_group == 1 and factor_quantile == 7')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基7指标模型策略')

all_ret = pd.concat((cross_ret[7],fscore_factor_ret[7],valuation_ret[1],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基7指标模型策略','RFScore7分组','PCF因子(10%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')


# In[191]:


cross_df.groupby(level='date')['factor'].count().plot(title='持仓数量',figsize=(18,4));


# In[192]:


pivot_valuation.index = pd.to_datetime(pivot_valuation.index)
valuation_ser = pivot_valuation.stack()
valuation_ser.index.names = ['date','asset']
valuation_factor = al.utils.get_clean_factor_and_forward_returns(valuation_ser,
                                                           pivot_price,
                                                           quantiles = 5,
                                                           periods=(1,))


# In[193]:


df = fscore_factor_data.copy()
df['Fundamental_group'] = valuation_factor['factor_quantile']
df.head()


# In[194]:



cross_df = df.query('Fundamental_group == 1 and factor_quantile == 7')
cross_ret = pd.pivot_table(cross_df.reset_index(),index='date',columns='factor_quantile',values=1)
fih,ax = plt.subplots(figsize=(15,8))
ax.set_title('比乔斯基7指标模型策略')

all_ret = pd.concat((cross_ret[7],fscore_factor_ret[7],valuation_ret[1],benchmark_ret.reindex(cross_ret.index)),axis=1)
all_ret.columns = ['比乔斯基7指标模型策略','RFScore7分组','PCF因子(20%)','benchmark']


ax.yaxis.set_major_formatter(mpl.ticker.FuncFormatter(lambda x,pos:'%.2f%%'%(x*100)))
ep.cum_returns(all_ret).plot(ax=ax,color=color_map[:3] + ['darkgray'])
ax.legend();
Strategy_performance(all_ret,'monthly').style.format('{:.2%}')

