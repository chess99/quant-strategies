# 克隆自聚宽文章：https://www.joinquant.com/post/41917
# 标题：致敬聚宽: 机器学习多因子,50只持仓,14年37倍
# 作者：Gyro^.^

# 克隆自聚宽文章：https://www.joinquant.com/post/10778
# 标题：【量化课堂】机器学习多因子策略
# 作者：JoinQuant量化课堂

import pandas as pd
import numpy as np
import datetime as dt
from sklearn.svm import SVR
from jqdata import *

def initialize(context):
    # setting system
    log.set_level('order', 'error')
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    # setting strategy
    run_daily(handle_training, 'before_open')
    run_daily(handle_trader, 'open')

def handle_trader(context):
    # init
    choice = g.choice
    psize  = g.psize
    cdata  = get_current_data()
    # sell
    for s in context.portfolio.positions:
        if s not in choice and\
            not cdata[s].paused:
            log.info('sell', s, cdata[s].name)
            order_target(s, 0, LimitOrderStyle(cdata[s].last_price))
    # buy
    for s in choice:
        if context.portfolio.available_cash < psize:
            break
        if s not in context.portfolio.positions and\
            not cdata[s].paused:
            log.info('buy', s, cdata[s].name)
            order_value(s, psize, LimitOrderStyle(cdata[s].last_price))

def handle_training(context):
    # parameter
    n_position = 50 # 持股数
    n_choice = int(1.2*n_position) # 选股数，20%缓冲
    index = '399317.XSHE' # 市场指数
    cdata  = get_current_data()
    dt_last = context.previous_date
    # stocks
    stocks = get_index_stocks(index, dt_last)
    # fundamental data
    q = query(
            valuation.code, 
            valuation.market_cap,
            balance.total_assets - balance.total_liability,
            income.net_profit,
            balance.development_expenditure,
            valuation.pe_ratio,
            balance.total_assets / balance.total_liability,
            indicator.inc_revenue_year_on_year / 100,
        ).filter(
            valuation.code.in_(stocks),
            balance.total_assets > balance.total_liability,
            income.net_profit > 0,
        )
    df = get_fundamentals(q, dt_last).fillna(0).set_index('code')
    df.columns = ['log_mc', 'log_NC', 'log_NI', 'log_RD', 'PE', 'lev', 'grow']
    # sign ln
    def _sign_ln(X):
        return sign(X) * np.log(1.0 + abs(X))
    # factor value
    df['log_mc'] = _sign_ln(df['log_mc'])
    df['log_NC'] = _sign_ln(df['log_NC'])
    df['log_NI'] = _sign_ln(df['log_NI'])
    df['log_RD'] = _sign_ln(df['log_RD'])
    df['PE']     = _sign_ln(df['PE'])
    df['lev']    = _sign_ln(df['lev'])
    df['grow']   = _sign_ln(df['grow'])
    # industry factor
    industry_list = get_industries('sw_l1', dt_last).index.tolist()
    for sector in industry_list:
        istocks = get_industry_stocks(sector, dt_last)
        s = pd.Series(0, index=df.index)
        s[set(istocks) & set(df.index)] = 1
        df[sector] = s
    # SVR model
    svr = SVR(kernel='rbf')
    # training model 
    Y = df['log_mc']
    X = df.drop('log_mc', axis=1)
    model = svr.fit(X, Y)
    # choice
    r = Y - pd.Series(svr.predict(X), Y.index)
    r = r[r < 0].sort_values().head(n_choice)
    choice = r.index.tolist()
    # sell list
    for s in context.portfolio.positions:
        if s not in choice:
            log.info('to sell', s, cdata[s].name)
    # buy list
    for s in choice:
        if s not in context.portfolio.positions:
            log.info('to buy', s, cdata[s].name)
    # save results
    g.choice = choice
    g.psize = 1.0/n_position * context.portfolio.total_value
# end
