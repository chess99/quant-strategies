# 克隆自聚宽文章：https://www.joinquant.com/post/50253
# 标题：EPO优化低相关etf组合
# 作者：开心果

from jqdata import *
import numpy as np
import pandas as pd
from scipy.linalg import solve
#初始化函数 
def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    set_slippage(FixedSlippage(0.002))
    set_order_cost(OrderCost(open_tax=0, close_tax=0, open_commission=0.0002, close_commission=0.0002, close_today_commission=0, min_commission=5), type='fund')
    log.set_level('order', 'error')
    g.etf_pool = ['159985.XSHE', '518800.XSHG', '513000.XSHG', '513100.XSHG', '513030.XSHG', '159930.XSHE', '159981.XSHE', '159980.XSHE', '510880.XSHG', '510230.XSHG']
    run_monthly(trade, 1, '10:00') 


def epo(x, signal, lambda_, method="simple", w=None, anchor=None, normalize=True, endogenous=True):
    n = x.shape[1]
    vcov = x.cov()
    corr = x.corr()
    I = np.eye(n)
    V = np.diag(np.diag(vcov))
    std = np.sqrt(V)
    s = signal
    a = anchor

    shrunk_cor = ((1 - w) * I @ corr.values) + (w * I)  # equation 7
    cov_tilde = std @ shrunk_cor @ std  # topic 2.II: page 11
    shrunk_cov =  (1 - w) * cov_tilde + w * V # equation 15
    inv_shrunk_cov = solve(cov_tilde, I)

    if method == "simple":
        epo = (1 / lambda_) * inv_shrunk_cov @ signal  # equation 16
    elif method == "anchored":
        if endogenous:
            gamma = np.sqrt(a.T @ cov_tilde @ a) / np.sqrt(s.T @ inv_shrunk_cov @ cov_tilde @ inv_shrunk_cov @ s)
            epo = inv_shrunk_cov @ (((1 - w) * gamma * s) + ((w * I @ V @ a)))
        else:
            epo = inv_shrunk_cov @ (((1 - w) * (1 / lambda_) * s) + ((w * I @ V @ a)))
    else:
        raise ValueError("`method` not accepted. Try `simple` or `anchored` instead.")

    if normalize:
        epo = [0 if a < 0 else a for a in epo]
        epo = epo / np.sum(epo)

    return epo

# 定义获取数据并调用优化函数的函数
def run_optimization(stocks, end_date):
    prices = get_price(stocks, count=250, end_date=end_date, frequency='daily', fields=['close'])['close']
    returns = prices.pct_change().dropna() 
    d = returns.var()
    a = (1/d) / (1/d).sum()
    w = epo(x = returns, signal = a, lambda_ = 10, method = "simple", w = 0.6)
    weights = dict(zip(stocks,w))
    return weights
    
# 交易
def trade(context):
    end_date = context.previous_date 
    etf_pool = filter_new_stock(context,g.etf_pool,30)
    weights = run_optimization(etf_pool, end_date)
    total_value = context.portfolio.total_value 
    for s in weights.keys():
        value = total_value * weights[s] 
        order_target_value(s, value)
        
def filter_new_stock(context, stock_list, d):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=d)]


