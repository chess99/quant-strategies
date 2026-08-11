#!/usr/bin/env python
# coding: utf-8

# In[1]:


import os
import sys

sys.path.append(os.path.dirname(os.getcwd()))
from typing import Dict, Tuple, List, Union
from collections import namedtuple

import pandas as pd
import numpy as np
import empyrical as ep
from talib import BETA
from scr.backtest_engine import get_backtesting
from knight_scr.BackTestReport.tear import analysis_rets, analysis_trade
from knight_scr.scr.sql_service import (
    get_trade_days,
    Tdaysoffset,
    get_ind_classify,
    get_ind_price,
    get_ts_index_price,
)

import seaborn as sns
import matplotlib as mpl
from matplotlib.gridspec import GridSpec
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["SimHei"]  # 用来正常显示中文标签
plt.rcParams["axes.unicode_minus"] = False  # 用来正常显示负号


# In[2]:


def calc_gsisi(
    close_ser: pd.Series, pivot_swprice: pd.DataFrame, window: int, pct_window: int = 5
) -> pd.Series:
    """投资者情绪指数

    Args:
        close_ser (pd.Series): 默认为沪深300收盘价
        pivot_swprice (pd.DataFrame): 申万收盘数据 index-date columns-swcode values-close
        window (int): sw与close计算beta的窗口
        pct_window (int, optional): 收益率计算窗口. Defaults to 5.

    Returns:
        pd.Series: spearman index-date values-spearman
    """
    # 周度收益
    sw_pct: pd.DataFrame = pivot_swprice.pct_change(pct_window)
    index_pct: pd.Series = close_ser.pct_change(pct_window)

    # 计算beta
    beta_roll5: pd.DataFrame = sw_pct.apply(lambda x: BETA(x, index_pct, window))

    # spearman
    return sw_pct.corrwith(beta_roll5, method="spearman", axis=1)


def get_gsisi_bt(
    index_price: pd.DataFrame,
    pivot_swprice: pd.DataFrame,
    window: int,
    pct_window: int = 5,
    **kw
) -> namedtuple:
    """GSISI回测

    Args:
        index_price (pd.DataFrame): 默认为hs300收盘价 index-date values-close
        pivot_swprice (pd.DataFrame): 申万行业收盘为 index-date columns-sw_code values-close
        window (int): beta与pct的滚动窗口
        pct_window (int, optional): 收益率计算窗口. Defaults to 5.

    Returns:
        namedtuple: bt_result result,cerebro
    """
    data: pd.DataFrame = index_price.copy()
    data["GSISI"] = calc_gsisi(index_price["close"], pivot_swprice, window, pct_window)

    data.dropna(subset=["GSISI"], inplace=True)
    data.index = pd.to_datetime(data.index)

    return get_backtesting(data, "HS300", **kw)


def opt_strat(
    index_price: pd.DataFrame,
    pivot_swprice: pd.DataFrame,
    window: int,
    pct_window: int = 5,
    score_name: str = "_SQN",
    **kw
) -> float:
    """用于寻找参数

    Args:
        index_price (pd.DataFrame): 默认为hs300收盘价 index-date values-close
        pivot_swprice (pd.DataFrame): 申万行业收盘为 index-date columns-sw_code values-close
        window (int): beta与pct的滚动窗口
        pct_window (int, optional): 收益率计算窗口. Defaults to 5.
        score_name (str, optional): 目标参数. Defaults to "_SQN".

    Returns:
        float: 目标参数的数值
    """
    bt_res: namedtuple = get_gsisi_bt(
        index_price, pivot_swprice, window, pct_window, **kw
    )
    anzs = bt_res.result[0].analyzers

    fields: Dict = {
        "_Sharpe": "sharperatio",
        "_SQN": "sqn",
        "_Returns": "rnorm",
    }

    return anzs.getbyname(score_name).get_analysis()[fields[score_name]]


# # 投资者情绪指数构建
# 
# 基本思路是首先计算28个申万一级行业周收益率以及其相对沪深300指数的周Beta系数；然后测算28个申万一级行业周收益率与其周Beta系数的Spearman秩相关系数;最后以Spearman秩相关系数为基础构建国信投资者情绪指数GSISI。

# In[3]:


sw_classify: pd.DataFrame = get_ind_classify("2023-01-10", "sw_level1")

sw_codes: List = sw_classify["code"].tolist()

begin_dt: str = "2014-01-01"
end_dt: str = "2023-01-10"

sw_price: pd.DataFrame = get_ind_price(
    sw_codes, begin_dt, end_dt, fields="close", level="sw_level1"
)
index_price: pd.DataFrame = get_ts_index_price(
    "000300.SH", begin_dt, end_dt, fields=["close", "open", "high", "low", "volume"]
)
index_price: pd.Series = index_price.set_index("trade_date")

benchmark_close: pd.Series = index_price["close"]
benchmark_close.index = pd.to_datetime(benchmark_close.index)


# In[4]:


pivot_swprice: pd.DataFrame = pd.pivot_table(
    sw_price, index="trade_date", columns="code", values="close"
)


# In[5]:


# 滚动5日收益率
window1:int = 5
sw_pct:pd.DataFrame = pivot_swprice.pct_change(window1)
index_pct:pd.Series = benchmark_close.pct_change(window1)

window2: int = 50
# 计算beta
beta_roll5: pd.DataFrame = sw_pct.apply(
    lambda x: BETA(x, index_pct, window2)
)

# 计算每个行业与基准的spearman
sw_roll5_pct_rank: pd.DataFrame = sw_pct.rolling(window2).rank()
sw_roll5_beta_rank: pd.DataFrame = beta_roll5.rolling(window2).rank()

sw_spearman: pd.DataFrame = sw_roll5_beta_rank.rolling(window2).corr(sw_roll5_pct_rank)


# In[6]:


spearman_roll5: pd.DataFrame = calc_gsisi(benchmark_close, pivot_swprice, window2)


# >当国信投资者情绪指数$GSISI \geq 31.7$时,投资乐观情绪上扬；当国信投资者情绪指数$GSISI \leq -31.7$时，投资悲观情绪蔓延。
# 
# 该阈值来源为:
# >对Spearman秩相关系数进行显著性检验,显著性水平$\alpha=0.05$,n=28,查表得Spearman秩相关系数的临界值为0.317
# 
# 这里我们的申万有31个行业,显著性水平$\alpha=0.05$,n=31,查表临界值应该为0.301
# 
# 从数据上来看开平仓标准差不多是信号的2倍标准差,感觉可以使用该数据

# In[7]:


avg:float = spearman_roll5.mean()
std:float = spearman_roll5.std()
std_up:float = avg + std * 2
std_low:float = avg - std * 2

print('均值:{:.4f},2 Std:{:.4f},-2 Std:{:.4f}'.format(avg,std_up,std_low))
ax = sns.histplot(spearman_roll5)
ax.axvline(std_up,ls='--',color='red')
ax.axvline(std_low,ls='--',color='green')
ax.axvline(avg,ls='--',color='black');


# In[8]:


benchmark_close.plot(figsize=(18, 4), color="r", label="Close")
spearman_roll5.plot(color="darkgray", label="GSISI", secondary_y=True, alpha=0.5)
plt.axhline(std_up, ls="--", color="red", alpha=0.5)
plt.axhline(std_low, ls="--", color="green", alpha=0.5);


# # GSISI择时模型设计
# 
# 若GSISI**连续两次**发出看多(或看空)信号,则看多(或看空)沪深300指数,且保持这个判断,直到**连续两次**看空(或看多)信号出现,则发生看空(或看多)沪深300指数的反转判断;若GSISI发出多空交叉互现信号,则除最新信号外,前面的交叉信号作废,以最新信号为判断起点,按照前面两条准则重新分析后面的信号。
# 
# **具体步骤是:**
# 
# 1. 若国信投资者情绪指数$GSISI \geq 0.301$，则作为看多沪深300的一次警示信号.若紧接着再次$GSISI \geq 0.301$，则作为看多沪深300的确认信号,正式看多沪深300,一次判断完成,且保持此判断,直到有相反的判断出现.若紧接着$GSISI \leq -0.301$,则看多沪深300的一次警示信号作废,以此最新的信号为判断起点,进行下一轮的判断.
# 2. 类似地,若国信投资者情绪指数$GSISI \leq -0.301$，则作为看空沪深300的一次警示信号.若紧接着再次$GSISI \leq -0.301$,则作为看空沪深300的确认信号,正式看空沪深300,一次判断完成,且保持此判断,直到有相反的判断出现.若紧接着$GSISI \geq 0.301$,则看空沪深300的一次警示信号作废,以此最新的信号为判断起点,进行下一轮的判断.

# In[9]:


import ipywidgets as ipw

import gradient_free_optimizers as gfo
from knight_scr.BackTestReport.tear import analysis_rets,analysis_trade


# In[10]:


search_space = {'window': np.arange(5, 100),'pct_window':np.arange(5,21,5)}

iterations = 200

opt = gfo.EvolutionStrategyOptimizer(search_space)
opt.search(lambda x:opt_strat(index_price,pivot_swprice,**x,score_name='_Returns',show_log=False), n_iter=iterations,verbosity=['progress_bar'])

best_params_window = {'window': opt.best_para['window'],'pct_window':opt.best_para['pct_window']}


# In[11]:


# _Sharpe/_Returns {'window': 35, 'pct_window': 15} rets 13.01% sharpe 79.76%
# _SQN {'window': 88, 'pct_window': 15} rets 9.11% sharpe 61.07%
best_params_window = {'window': 35, 'pct_window': 15}
bt_res = get_gsisi_bt(index_price,pivot_swprice,**best_params_window)


# In[12]:


print(best_params_window)
report2ts = analysis_rets(benchmark_close, bt_res.result, use_widgets=True)
report2trade = analysis_trade(benchmark_close, bt_res.result, use_widgets=True)


# In[13]:


from plotly.offline import iplot
from plotly.offline import init_notebook_mode
init_notebook_mode()


# In[14]:


box_layout = ipw.Layout(
    display="space-between", border="3px solid black", align_items="inherit"
)

ipw.VBox(
    [   report2ts.risk_table,
        report2ts.cumulative_chart,
        report2trade.position_chart,
        report2trade.pnl_chart,
        report2ts.maxdrawdowns_chart,
    ],
    layout=box_layout,
)


# In[15]:


for chart in [   report2ts.risk_table,
        report2ts.cumulative_chart,
        report2trade.position_chart,
        report2trade.pnl_chart,
        report2ts.maxdrawdowns_chart,
    ]:
    iplot(chart)


# In[ ]:




