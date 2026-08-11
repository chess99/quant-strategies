# 克隆自聚宽文章：https://www.joinquant.com/post/44491
# 标题：年化46.77，alpha191因子选股
# 作者：小白F

import pandas as pd
import numpy as np
import math
from sklearn.svm import SVR  
from sklearn.metrics import r2_score, mean_absolute_error, mean_squared_error, explained_variance_score
import statsmodels.api as sm 
from statsmodels import regression
import jqdata
import datetime as dt
from jqlib.alpha191 import *
def initialize(context):
    set_params()
    set_backtest()
    g.factors=['alpha_006', 'alpha_015', 'alpha_026']
def set_params():
    g.days = 0          # 日期计数器开始值
    g.refresh_rate = 10 # 调仓间隔周期
    g.stocknum = 3     # 同时持有个股数量
def set_backtest():
    # 当前价格的百分比设置滑点
    # set_slippage(PriceRelatedSlippage(0.002))   
    # 设置佣金
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, \
    close_commission=0.0003, close_today_commission=0, min_commission=5), type='stock')
    # 设置对比基准
    set_benchmark('000300.XSHG') 
    # 使用真实价格
    set_option('use_real_price', True)
    log.set_level('order', 'error')
    log.set_level('system', 'error')
# 过滤股票，过滤停牌退市ST股票，选股时使用
def filter_stock_ST(stock_list):
    curr_data = get_current_data()
    for stock in stock_list:
        if (curr_data[stock].paused) or (curr_data[stock].is_st) or ('ST' in curr_data[stock].name)\
            or ('*' in curr_data[stock].name)\
            or ('退' in curr_data[stock].name):
            stock_list.remove(stock)
    return stock_list
# 交易时使用，过滤每日开盘时的涨跌停股filter low_limit/high_limit    
def filter_stock_limit(stock_list):  
    curr_data = get_current_data()
    for stock in stock_list:
        price = curr_data[stock].day_open
        if (curr_data[stock].high_limit <= price) or (price <= curr_data[stock].low_limit):
            stock_list.remove(stock)
    return stock_list
# 可选项: 过滤上市180日以内次新股
def remove_new_stocks(security_list,context):
    for stock in security_list:
        days_public = (context.current_dt.date() - get_security_info(stock).start_date).days
        if days_public < 180:
            security_list.remove(stock)
    return security_list
# 取得股票某个区间内的所有收盘价（用于取前interval日和当前日收盘价）
def getStockPrice(stock, interval): # 输入stock证券名，interval期
    h = attribute_history(stock, interval, unit='1d', fields=('close'), skip_paused=True)
    return (h['close'].values[0] , h['close'].values[-1])
    # 0是第一个（interval周期的值,-1是最近的一个值(昨天收盘价)）
# 求线性回归beta值
# 输入:X:回归自变量（因子值，或个股回报） Y:回归因变量（超额收益率，或指数回报）
# 支持list,array,DataFrame等三种数据类型
def linreg(x,y):
    x = sm.add_constant(array(x))
    y = array(y)
    if len(y)>1:
        model = regression.linear_model.OLS(y,x).fit()
        x = x[:,1]
    return model.params[1]
#求dataframe 对于X的中性化后的df, X是df中的一个key 数据类型
def df_neutralization(df, X):
    for key in df.keys():
        if (key!='code' and key!=X):
            y = df[key]
            x = df[X]
            df[key] = linres(y, x)
    return df
# 求线性回归残差（中性化用途）
def linres(y,x):
    y = array(y)
    x = sm.add_constant(array(x))
    if len(y)>1:
        model = regression.linear_model.OLS(y,x).fit()
    return model.resid
# =================择时==============================
# FISHER 择时
def fisher_transform_strategy(context, security_list):
    buyable_stocks = []
    end_date = context.previous_date
    period = 10
    for security in security_list:
        # 获取股票数据
        df = get_price(security, end_date=end_date, count=period, panel=False, fill_paused=False)
        # df_price = get_price(stock_list, end_date=date,frequency='daily', , count=1, panel=False, fill_paused=False)
        # 计算 Fisher Transform
        def fisher_transform(data, period=period):
            high = data['high']
            low = data['low']
            close = data['close']

            mid_price = (high + low) / 2.0
            typical_price = (high + low + close) / 3.0
            smoothed_price = (mid_price + typical_price) / 2.0
            price_diff = typical_price - mid_price
            abs_diff = np.abs(price_diff)

            fft_result = np.fft.fft(smoothed_price)
            fisher = np.log((1 + abs_diff) / (1 - abs_diff))

            return fisher

        # 计算 Fisher Transform 值
        df['fisher'] = fisher_transform(df)

        # 生成择时信号
        df['signal'] = np.where(df['fisher'] > 0, 1, -1)

        # 判断是否可以买入（Fisher Transform 大于零）
        if df['fisher'].iloc[-1] > 0:
            buyable_stocks.append(security)

    return buyable_stocks
    
# ================= 以下是正式回测=============== 
def handle_data(context, data):
    # 每个调仓日截面上，进行数据提取和计算
    if g.days % g.refresh_rate == 0:
        # 从股票池提取样本股
        sample = get_index_stocks('000985.XSHG', date = None)
        # 过滤停牌退市ST股票，次新股
        sample = filter_stock_ST(sample)
        sample = remove_new_stocks(sample,context)
        sample = filter_stock_limit(sample)
        # 获取基本面数据并作初步计算
        q = query(valuation.code, 
                    valuation.market_cap, # 总市值
                    indicator.roe / valuation.pb_ratio, # PB-ROE
                    valuation.pe_ratio / indicator.inc_net_profit_year_on_year, #  PEG
                ).filter(
                    valuation.pe_ratio < 100,
                    valuation.market_cap < 1000,
                    valuation.code.in_(sample)
                ).order_by(
                    # 按市值降序排列
                    # valuation.market_cap.asc()
                    (valuation.pe_ratio / indicator.inc_net_profit_year_on_year).asc()
                ).limit(
                    # 最多返回500个
                    500)
        df  = get_fundamentals(q, date = None)
        select_list =list(df['code'])
        # select_list = sample
        # 获取价量因子和技术指标
        # alpha_datas = {}
        for factor in g.factors:
            df[factor] = np.array(eval(factor)(select_list, end_date=None))
        # a004 = alpha_004(select_list, end_date = None)
        # a004 = np.array(a004)
        # df['a004'] = a004
        # a052 = alpha_052(select_list, end_date = None)
        # a052 = np.array(a052)
        # df['a052'] = a052
        # a126 = alpha_126(select_list, end_date = None)
        # a126 = np.array(a126)
        # df['a126'] = a126
        # 求个股调仓周期回报率
        momentum = []
        for i in select_list:
            interval,Yesterday = getStockPrice(i, g.refresh_rate) 
            stock_momentum = Yesterday / interval - 1
            momentum.append((i, stock_momentum))
        # 转化成np.array结构，方便取出第二列数据（回报率）
        np_momentuma = np.array(momentum)
        momentum_value = np_momentuma[:,1].astype(float).tolist()
        df['momentum_value'] = momentum_value
        # ========== 所有整合完毕的因子数据dataframe表格========= 
        # 所有整合完毕的因子数据dataframe表格
        df.columns = ['code','market_cap','PB_ROE','PE_G',\
        g.factors[0],g.factors[1],g.factors[2],'momentum_value']
        # print df
        df = df_neutralization(df,'market_cap')
        # df.index是这个dataframe的index索引
        df.index = df.code.values
        del df['code']
        df = df.fillna(0)
        # ==================== 支持向量回归 ====================     
        # 自变量X列表
        X = df[g.factors] 
        # 应变量Y列表
        Y = df[['market_cap']]
        X = X.fillna(0)
        Y = Y.fillna(0)
        svr = SVR(kernel='poly', gamma=0.01) 
        model = svr.fit(X, Y)
        # factor是真实值 - 回归值 = 残差
        predict = svr.predict(X)
        record(R2=r2_score(Y, predict))
        record(MAE=mean_absolute_error(Y, predict))
        record(MSE=mean_squared_error(Y, predict))
        record(EVS=explained_variance_score(Y, predict))
        factor = Y - pd.DataFrame(predict, index = Y.index, columns = ['market_cap'])
        # 按回报率升序排列，残差最低的被排名靠前，优先买入
        factor = factor.sort_index(by = 'market_cap', ascending = True)
        # order_list = list(factor.index)
        # 过滤300开头的创业板股票
        # order_list = [s for s in order_list if s[0:3] != '300'][:g.stocknum]
        # 通过list函数将factor的index列转化成list数据类型，然后买入前g.stocknum个
        # order_list = list(factor.index[:g.stocknum])
        order_list = fisher_transform_strategy(context, list(factor.index))[:g.stocknum]
        # 最终名单，分别下单给两个交易函数
        order_stock_sell(context,order_list)
        order_stock_buy(context,order_list)
        g.days += 1
    else:
        g.days += 1
# 执行卖出
def order_stock_sell(context,order_list):
    # 对于不需要持仓的股票，全仓卖出
    for stock in context.portfolio.positions:
        # 除去buy_list内的股票，其他都卖出
        if stock not in order_list:
            order_target_value(stock, 0)
# 执行买入
def order_stock_buy(context,order_list):
    # 先求出可用资金，如果持仓个数小于g.stocknum
    if len(context.portfolio.positions) < g.stocknum:
        # 求出要买的数量num
        num = g.stocknum - len(context.portfolio.positions)
        # 求出每只股票要买的金额cash
        g.each_stock_cash = context.portfolio.cash/num
    else:
        # 如果持仓个数满足要求，不再计算g.each_stock_cash
        cash = 0
        num = 0
    # 执行买入
    for stock in order_list:
        if stock not in context.portfolio.positions:
            order_target_value(stock, g.each_stock_cash)
