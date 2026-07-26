#!/usr/bin/env python
# coding: utf-8

# # 行业指数顶部和底部信号：净新高占比（(NH-NL)%）
# 
# ## 背景
# 
# **行业涨跌分化增加了行业指数顶部和底部信号的必要性：**
# 
# 一方面，近年来A股行业指数同涨同跌的现象减弱,尤其是2020年以来，**行业指数间的分化越来越严重，因此寻找行业指数的顶部和底部信号显得尤为重要**。28个中信一级行业估值分位数的波动率验证了行情的分化。另一方面，各行业指数ETF、主题基金的兴起和壮大，增加了对行业指数顶部和底部判断的需求。
# 
# **行业指数顶部和底部信号的构建及简单反转策略：**
# 我们通过构建净新高占比（(NH-NL)%）指标来刻画行业指数的情绪，这延 续了我们对价格新高和价格新低的重视，与我们衡量宽基指数的情绪指标 （NHNL）一脉相承，**其核心逻辑仍基于行为金融学的锚定效应**。在净新高占比（(NH-NL)%）信号的基础上，我们构建了一个简单的反转策略，包括买入、卖出、仓位、止损及移动等要素。
# 
# **净新高占比能较好地提示科技板块行业指数的顶部和底部：**
# 
# 通过对科技板块的电子、通信、计算机和传媒行业的逐一复盘，从准确率 和简单反转策略盈利性等角度进行分析，我们发现净新高占比（(NH-NL)%） 指标能较好地提示行业指数的顶部和顶部；简单反转策略有效，且2020年 以来策略在科技板块的表现较好。考虑到反转策略资金占用时间较少，因此比较适合作为指数增强型策略。
# 
# 
# 近年来，A 股行业指数同涨同跌的现象减弱，尤其是 2020 年行业指数间分化更 加明显；同时，伴随各行业指数 ETF、主题基金的兴起和壮大，增加了对行业指数顶部和底部判断的需求。因此，我们尝试寻找提示行业指数顶部和底部的信号。我们通过构建净新高占比指标（简称“(NH-NL)%”），来寻找行业指数（中信一 级行业指数）的顶部和底部。通过回溯检验发现，净新高占比（(NH-NL)%）在科技 板块和周期板块表现较好。本篇报告并以科技板块为例，复盘了净新高占比（(NH-NL)%）提示科技板块行业指数的准确率及简单反转策略的有效性。

# In[9]:


import pandas as pd
import numpy as np
from typing import Dict, List


# ## 构建逻辑
# 
# 净新高占比指标（(NH-NL)%）即行业指数中创年度新高与年度新低之差的个股 数占全行业个股数的百分比，其逻辑自洽性来源包括以下四个方面：
# 
# - <b>锚定效应与新高新低。</b>行为金融学告诉我们，绝大多数投资者都有很强的锚 定效应，他们都清楚地记得所持有个股/基金的成本价（即“锚定成本”）， 甚至他们的很多决定都是视他们处于浮盈还是浮亏状态而定。创年度新高的 个股，其股票持有者均为浮盈状态，因此即使其计划卖出，也愿意等行情再 上涨一段时间，因此其抛压相对较小；而创年度新低的个股，因其股票持有者均为浮亏状态，因此只要行情反弹便有投资者卖出，抛压反而较大。
#   
# - <b>新高新低是个股走强走弱最直接的刻画。</b>创新高/新低是个股走强/走弱最直 接的刻画，10 倍股都是从 1 倍股开始涨的，优秀的个股能不断创出新高；另一方面，个股跌到 2 折前都是先腰斩，而最开始的表现则是创年度新低。
#   
# - <b>新高新低差代表行业内个股整体强弱，亦即代表行业指数的强弱。</b>如果一 个行业指数中创年度新高多于创年度新低的个股数，即表示其中更多个股正在走强，反之亦然。
#   
# - <b>净新高占比（(NH-NL)%）能较好地刻画行业指数强弱及市场情绪。</b>净新高占比通过归一化（指标值在【-1,1】之间），能有效去除行业规模的影响（机 械行业目前有接近 500 个公司上市超过 1 年，煤炭行业上市超过 1 年的上
# 市公司仅 36 个），而且能进行横向比较，去除行业的特殊性。
# 
# ## 信号构建方法
# 
# 我们通过构建指标净新高占比（Net Percent of New High Minus New Low，简 称“(NH-NL)%”，亦简称“NPNMN”）来衡量中信一级行业指数的强弱：
# 
# $$净新高占比(NH-NL)\%=\frac{创年度新高的个股数-创年度新低的个股数}{行业内部上市超过1年的个股数}$$
# 
# 其中,"创年度新高/新低"指*收盘价大于/小于过去52周至一周前的区间最高/最低收盘价*
# 
# 这里有两个注意:
# 1. 传统使用high>Max(high)表示最高(最低同),而这里用的close>Max(close);
# 2. 识别前期高点的时间是$T_{1-52}$而非$T_{0-51}$
# 
# ## (NH-NL)%指标的阈值选择
# 
# 我们用20%和30%作为中信一级行业指数**乐观**和**贪婪**的阈值，用-20%和-30% 作为**悲观**和**恐惧**的阈值。
# 
# $$NHNL = \begin{cases} 
# x \geq 30\% \ 贪婪\\\
# 20\% \leq x \lt 30\% \ 乐观\\\
# -20\% \lt x \lt 20\% \ 正常区间\\\
# -30\% \lt x \leq -20\% \ 悲观\\\
# x \leq -30\% \ 恐惧
# \end{cases}$$
# 
# 为了防止一级行业指数个股数太少引发的跳跃，当一级行业指数上市超过 1 年的个股数小于 40 时，将阈值放宽为±30%/40%：
# 
# $$NHNL = \begin{cases} 
# x \geq 40\% \ 贪婪\\\
# 30\% \leq x \lt 40\% \ 乐观\\\
# -30\% \lt x \lt 30\% \ 正常区间\\\
# -40\% \lt x \leq -30\% \ 悲观\\\
# x \leq -40\ \ 恐惧%
# \end{cases}$$
# 
# ## 跟踪方法
# 
# 我们构建一个基于净新高占比指标（(NH-NL)%）简单的反转策略：当净新高占比指标提示贪婪后开始关注，第一天回到阈值内视为做空信号，下一个交易日开盘做空，止损点为前一周（5 个交易日）区间最高点，否则持有30天后以收盘价平仓，入场一周后若未止损则将止损位移至成本价。
# 
# 当净新高占比指标提示恐慌后开始关注，第一天回到阈值内视为做多信号，下一个交易日开盘做多，止损点为前一周区间最低点，否则持有 30 天后以收盘价平仓，入场一周后若未止损则将止损位移至成本价。

# ### 数据获取
# 
# **此部分可以跳过直接读取data文件中的数据构建信号**
# 
# [数据获取](https://drive.google.com/drive/folders/1AKnaQVwp_DdZ6wl27miQTWwuJAcAPDPv?usp=share_link)

# In[68]:



import sys
from pathlib import Path

sys.path.append(str(Path().resolve().parents[0]))
from tqdm.notebook import tqdm
# 这里我使用的自己的数据库
from knight_scr.scr.sql_service import (
    get_ts_price,
    get_ind_classify,
    get_ind_concept_cons,
    get_ind_price,
    get_ts_stock_basic,
    get_trade_days,
)

def get_ind_overthreshold_num(
    sw_cons_name: Dict, start_dt: str, end_dt: str, limit: int
) -> pd.DataFrame:
    """交易日至ipodate的天数(自然日)

    Args:
        sw_cons_name (Dict): k-codes v-industry_name
        start_dt (str): 起始日期
        end_dt (str): 结束日期
        limit (int): 阈值

    Returns:
        pd.DataFrame: index-date columns-code values-days
    """
    # 获取股票基础数据
    stock_basic: pd.DataFrame = get_ts_stock_basic()
    codes: List = list(sw_cons_name.keys())

    cond: pd.DataFrame = stock_basic["code"].isin(codes)
    stock_basic: pd.DataFrame = stock_basic[cond]
    # 获取交易日期
    periods: np.ndarray = get_trade_days(start_dt, end_dt)

    stock_ipo_list: pd.Series = stock_basic.set_index("code")["list_date"]
    stock_ipo_list: pd.Series = stock_ipo_list.astype(np.datetime64)

    data: np.ndarray = np.broadcast_to(periods, (len(codes), len(periods))).T
    ipo_date: pd.DataFrame = (
        pd.DataFrame(data=data, index=periods, columns=codes)
        .sub(stock_ipo_list)
        .applymap(lambda x: x.days)
    )

    ipo_date.columns = ipo_date.columns.map(sw_cons_name)

    return ipo_date.apply(lambda x: x > limit).groupby(level=0, axis=1).sum()


# In[6]:


watch_date = "2023-03-03"


# In[7]:


sw_classify: pd.DataFrame = get_ind_classify(watch_date, "sw_level1")
sw_cons: pd.DataFrame = get_ind_concept_cons(watch_date, "sw_level1")

# k-code v-industry_code
sw_cons_dict: Dict = sw_cons.set_index("code")["industry_code"].to_dict()
# k-industry_code v-industry_name
classify_dict: Dict = sw_classify.set_index("code")["sec_name"].to_dict()
# k-code v-industry_code
sw_cons_name: Dict = {k: classify_dict[v] for k, v in sw_cons_dict.items()}
# name-cons_num
# classify_num: pd.Series = pd.Series(Counter(sw_cons_name.values()))


# In[70]:


sw_classify.head()


# In[71]:


sw_cons.head()


# In[8]:


ind_price: pd.DataFrame = get_ind_price(
    list(classify_dict.keys()),
    start_date="2014-01-01",
    end_date="2023-03-03",
    fields=["close"],
    level="sw_level1",
)
ind_price["name"] = ind_price["code"].map(classify_dict)
pivot_ind_price: pd.DataFrame = pd.pivot_table(
    ind_price, index="trade_date", columns="name", values="close"
)


# In[72]:


ind_price.head()


# In[74]:


# 获取2013至2023申万一级行的数据
codes: List = sw_cons["code"].unique().tolist()
begin_periods = pd.date_range("2013-01-01", watch_date, freq="YS")
end_periods = (
    pd.date_range("2013-01-01", watch_date, freq="Y")
    .append(pd.to_datetime([watch_date]))
    .unique()
)

dfs: List = [
    get_ts_price(
        codes,
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
        fields=["high", "low"],
        fq="post",
    )
    for start, end in tqdm(
        zip(begin_periods, end_periods), total=len(begin_periods), desc="数据查询"
    )
]

price: pd.DataFrame = pd.concat(dfs)


# In[76]:


price.head()


# In[10]:


pivot_table: pd.DataFrame = pd.pivot_table(price,
                                           index="trade_date",
                                           columns="code",
                                           values=["low", "high"])


# In[16]:


start_dt = pivot_table.index.min()
end_dt = pivot_table.index.max()

classify_num: pd.DataFrame = get_ind_overthreshold_num(
    sw_cons_name, start_dt, end_dt, 252
)


# In[6]:


classify_num.head()


# ### 信号构建
# 
# 这里直接构建已有数据构建
# 
# 这里有个细节问题:*行业每半年调整一次成分股,这里我近用了最近截面上的行业成分股生成信号,故前序行情可能失真*

# In[10]:


from scr import load_data
from scr import calc_industry_nhnl,plot_nhnl_signal
from plotly.offline import init_notebook_mode, iplot

init_notebook_mode(True)


# In[11]:


nhnl_df: pd.DataFrame = calc_industry_nhnl(
   load_data.pivot_table, load_data.sw_cons_name, 52 * 5, load_data.classify_num,tradition=False
)


# In[12]:


chart = plot_nhnl_signal(load_data.pivot_ind_price["电子"], nhnl_df["电子"], 40, "电子行业净新高占比", True)
iplot(chart)

