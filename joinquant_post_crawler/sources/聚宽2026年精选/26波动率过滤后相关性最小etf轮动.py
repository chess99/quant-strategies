# 克隆自聚宽文章：https://www.joinquant.com/post/49615
# 标题：波动率过滤后相关性最小etf轮动
# 作者：开心果

import numpy as np
import pandas as pd
#初始化函数 
def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    log.set_level('system', 'error')
    g.etf_pool = ['512660.XSHG', '511010.XSHG', '510880.XSHG', '159915.XSHE', '513050.XSHG', '510050.XSHG', '588100.XSHG', '512100.XSHG', '518800.XSHG', '513060.XSHG', '512980.XSHG', '512010.XSHG', '513100.XSHG', '512720.XSHG', 
                    '512070.XSHG', '515880.XSHG', '159920.XSHE', '159922.XSHE', '513520.XSHG', '515000.XSHG', '515790.XSHG', '515700.XSHG', '159825.XSHE', '512400.XSHG', '512200.XSHG', '513360.XSHG', '512480.XSHG', '510230.XSHG', '159647.XSHE', '159928.XSHE']
   
    g.m_days = 25  
    run_daily(trade, '10:00')

def min_corr(stocks):
    nday = 729
    p = history(nday, '1d', 'close', stocks).dropna(axis=1)
    r = np.log(p).diff()[1:]
    v = r.std()*math.sqrt(243)
    v = v[(v>0.05) & (v<0.33)]
    r = r[v.index]
    m_corr = r.corr()
    corr_mean = {}
    for stock in m_corr.columns:
        corr_mean[stock] = m_corr[stock].abs().mean()
    etf_pool = sorted(corr_mean, key=corr_mean.get)[:4]
    return etf_pool

def get_rank(etf_pool):
    score_list = []
    for etf in etf_pool:
        df = attribute_history(etf, g.m_days, '1d', ['close'])
        y = df['log'] = np.log(df.close)
        x = df['num'] = np.arange(df.log.size)
        slope, intercept = np.polyfit(x, y, 1)
        annualized_returns = math.pow(math.exp(slope), 250) - 1
        r_squared = 1 - (sum((y - (slope * x + intercept))**2) / ((len(y) - 1) * np.var(y, ddof=1)))
        score = annualized_returns * r_squared
        score_list.append(score)
    df = pd.DataFrame(index=etf_pool, data={'score':score_list})
    df = df[(df['score']>-0.5) & (df['score']<4.5)]
    df = df.sort_values(by='score', ascending=False)
    rank_list = list(df.index)
    return rank_list

# 交易
def trade(context):
    target_num = 1
    etf_pool = min_corr(g.etf_pool)
    target_list = get_rank(etf_pool)[:target_num]
    # 卖出    
    hold_list = list(context.portfolio.positions)
    for etf in hold_list:
        if etf not in target_list:
            order_target_value(etf, 0)
    # 买入
    hold_list = list(context.portfolio.positions)
    if len(hold_list) < target_num:
        value = context.portfolio.available_cash / (target_num - len(hold_list))
        for etf in target_list:
            if context.portfolio.positions[etf].total_amount == 0:
                order_target_value(etf, value)
