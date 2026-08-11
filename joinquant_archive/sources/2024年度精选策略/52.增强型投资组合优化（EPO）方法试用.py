# 克隆自聚宽文章：https://www.joinquant.com/post/43949
# 标题：增强型投资组合优化（EPO）方法试用
# 作者：开心果

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
    log.set_level('system', 'error')
    # 参数
    g.etf_pool = [
        '518880.XSHG', #黄金ETF（大宗商品）
        '513100.XSHG', #纳指100（海外资产）
        '159915.XSHE', #创业板100（成长股，科技股，题材性，中小盘）
        '510880.XSHG', #红利ETF（价值股，蓝筹股，防御性，中大盘）
    ]
    run_monthly(trade, 1, '10:00') #每天运行确保即时捕捉动量变化

'''
Computes the optimal portfolio allocation using the EPO method.
#'
#' @param x A data-set with asset returns. It should be a {tibble}, a {xts}
#' or a {matrix}.
#' @param signal A {double} vector with the investor's belief's (signals, forecasts).
#' @param lambda A {double} with the investor's risk-aversion preference.
#' @param method A {character}. One of: `"simple"` or `"anchored"`.
#' @param w A {double} between {0} and {1}. The shrinkage level #' increases from 0 to 1.
#' @param anchor A{double} vector with the anchor (benchmark) in which
#' the allocation should not deviate too much from. Only used when `method = "anchored"`.
#' @param normalize A{boolean} indicating whether the allocation should be
#' normalized to sum {1} (full-investment constraint). The default is `normalize = TRUE`.
#' @param endogenous A {boolean} indicating whether the risk-aversion parameter
#' should be considered endogenous (only used when `method = "anchored"`).
#' The default is `endogenous = TRUE`.
'''
def epo(x, signal, lambda_, method="simple", w=None, anchor=None, normalize=True, endogenous=True):
    assert isinstance(method, str), "`method` must be a string."
    assert isinstance(lambda_, (int, float)), "`lambda` must be a number."
    assert isinstance(w, (int, float)), "`w` must be a number."
    assert isinstance(normalize, bool), "`normalize` must be a boolean."

    if method == "anchored" and anchor is None:
        raise ValueError("When the `anchored` method is chosen the `anchor` can't be `None`.")

    n = x.shape[1]
    vcov = x.cov()
    corr = x.corr()
    I = np.eye(n)
    V = np.zeros((n, n))
    np.fill_diagonal(V, vcov.values.diagonal())
    std = np.sqrt(V)
    s = signal
    a = anchor

    shrunk_cor = ((1 - w) * I @ corr.values) + (w * I)  # equation 7
    cov_tilde = std @ shrunk_cor @ std  # topic 2.II: page 11
    inv_shrunk_cov = solve(cov_tilde, np.eye(n))

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
    prices = get_price(stocks, count=1200, end_date=end_date, frequency='daily', fields=['close'])['close']
    returns = prices.pct_change().dropna() # 计算收益率
    d = np.diag(returns.cov())
    a = (1/d) / (1/d).sum()
    # a= np.array([0.25,0.25,0.25,0.25])
    weights = epo(x = returns, signal = returns.mean(), lambda_ = 10, method = "anchored", w = 1, anchor=a)
    return weights
    
# 交易
def trade(context):
    end_date = context.previous_date            
    weights = run_optimization(g.etf_pool, end_date)
    print("weights",weights)
    if weights is None:
        return
    total_value = context.portfolio.total_value # 获取总资产
    index = 0
    for w in weights:
        value = total_value * w # 确定每个标的的权重
        order_target_value(g.etf_pool[index], value) # 调整标的至目标权重
        index+=1
