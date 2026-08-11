# 克隆自聚宽文章：https://www.joinquant.com/post/34253
# 标题：北向RSRS与布林带择时
# 作者：韭菜001

#from .API import *
# 导入函数库
from jqdata import *
import random
import pandas as pd
import numpy as np
import datetime as dt
import statsmodels.api as sm



# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5),
                   type='stock')
    g.fund = '420002.OF'
    g.max_stock_count =20
    g.back_trade_days=80
    g.top_money_in = []
    g.up_ratio = 0.96
    g.window = 90
    g.stdev_up = 2
    g.stdev_dn = 2
    g.mf, g.upper, g.lower = None, None, None
    g.init = True
    g.quantile_N = 15
    g.quantile_M = 15
    g.buy = -0.1
    g.sell = -0.4
    #用于记录回归后的beta值，即斜率
    g.ans = []
    #用于计算被决定系数加权修正后的贝塔值
    g.ans_rightdev= []
    g.security = '000300.XSHG'
    # g.security = ''
    g.N = 18
    g.M = 600

    prices = get_price(g.security, context.current_dt - timedelta(g.M+1), context.previous_date, '1d', ['high', 'low'])
    highs = prices.high
    lows = prices.low
    g.ans = []
    for i in range(len(highs))[g.N:]:
        data_high = highs.iloc[i-g.N+1:i+1]
        data_low = lows.iloc[i-g.N+1:i+1]
        beta,r2 = get_ols(data_low,data_high)
        g.ans.append(beta)
        g.ans_rightdev.append(r2)
        # X = sm.add_constant(data_low)
        # model = sm.OLS(data_high,X)
        # results = model.fit()
        # g.ans.append(results.params[1])
        # #计算r2
        # g.ans_rightdev.append(results.rsquared)
        
    run_daily(before_market_open, time='07:00')
    run_daily(reblance, '9:35')
    
    
def before_market_open(context):
    pre_date = (context.current_dt - datetime.timedelta(1)).strftime('%Y-%m-%d')
    g.mf, g.upper, g.lower = get_boll(pre_date)
    log.info('北上资金均值：%.2f  北上资金上界：%.2f 北上资金下界：%.2f' % (g.mf, g.upper, g.lower))

def get_boll(end_date):
    """
    获取北向资金布林带
    """
    table = finance.STK_ML_QUOTA
    q = query(
        table.day, table.quota_daily, table.quota_daily_balance
    ).filter(
        table.link_id.in_(['310001', '310002']), table.day<=end_date
    ).order_by(table.day)
    money_df = finance.run_query(q)
    money_df['net_amount'] = (money_df['quota_daily'] - money_df['quota_daily_balance'])
    # 分组求和
    money_df = money_df.groupby('day')[['net_amount']].sum().iloc[-g.window:]
    mid = money_df['net_amount'].mean()
    stdev = money_df['net_amount'].std()
    upper = mid + g.stdev_up * stdev
    lower = mid - g.stdev_dn * stdev
    mf = money_df['net_amount'].iloc[-1]
    return mf, upper, lower

def calc_change(context,stock_universe = []):
    table = finance.STK_HK_HOLD_INFO
    q = query(table.day, table.name, table.code, table.share_ratio)\
        .filter(table.link_id.in_(['310001', '310002']),
                table.day.in_([context.previous_date]),
                table.code.in_(stock_universe)
                )
    df = finance.run_query(q)

    # df['share_ratio'] = df['share_ratio']
    return df.sort_values(by='share_ratio',ascending=False)[3:g.max_stock_count]['code'].values
    
def reblance(context):

    # stock_universe = get_up_stock(get_index_stocks(g.security))
    # stock_universe = get_index_stocks(g.security)
    if g.mf >= g.upper:
        # s_change_rank=get_up_stock(calc_change(context,get_index_stocks(g.security)))
        # s_change_rank = calc_change(context,stock_universe)
        
        s_change_rank = calc_change(context,get_index_stocks(g.security))
        final = list(s_change_rank)
        current_hold_funds_set = set(context.portfolio.positions.keys())
        rsrs_sell = []
        rsrs_buy = []
        for stock in final:
            rsrs = calc_zscore_Rdev(stock)
            if rsrs < g.sell:
                rsrs_sell.append(stock)
                
        if set(final) != current_hold_funds_set:
            need_buy= set(final).difference(current_hold_funds_set).difference(rsrs_sell)
            need_sell= current_hold_funds_set.difference(set(final).difference(rsrs_sell))
            
            for fund in need_sell:
                order_target(fund, 0)
            if len(need_buy):
                redeem(g.fund,context.portfolio.positions[g.fund].closeable_amount)
                cash_per_fund=context.portfolio.total_value/len(need_buy)
            for fund in need_buy:
                order_value(fund,cash_per_fund)
    
    elif g.mf <= g.lower:
        current_hold_funds_set = set(context.portfolio.positions.keys())
        if len(current_hold_funds_set)!=0:
            for fund in current_hold_funds_set:
                order_target(fund, 0)
        # purchase(g.fund,context.portfolio.total_value)



def calc_zscore_Rdev(stock):
    beta=0
    r2=0
    signal = 0
    if g.init:
        g.init = False
        signal = 1
    else:
        #RSRS斜率指标定义
        # signal = 1
        prices = attribute_history(stock, g.N, '1d', ['high', 'low','close'])
        highs = prices.high**2
        lows = prices.low**2
        ret = prices.close.pct_change().dropna()
        beta,r2 = get_ols(lows,highs)
        # X = sm.add_constant(lows)
        # model = sm.OLS(highs, X)
        # beta = model.fit().params[1]
        g.ans.append(beta)
        #计算r2
        # r2=model.fit().rsquared
        g.ans_rightdev.append(r2)
    
    # 计算标准化的RSRS指标
    # 计算均值序列    
    section = g.ans[-g.M:]
    # 计算均值序列
    mu = np.mean(section)
    # 计算标准化RSRS指标序列
    sigma = np.std(section)
    zscore = (section[-1]-mu)/sigma  
    # ret = attribute_history(stock,g.N,'1d')
    #计算右偏RSRS标准分
    if signal:
        return zscore*r2
    else:
        return zscore*r2**(2*cal_ret_quantile(ret))

def cal_ret_quantile(price_df):

    # 计算收益波动
    ret_std = np.sqrt(price_df.rolling(g.quantile_N).std())
    ret_quantile = ret_std.rolling(g.quantile_M).apply(
        lambda x: x.rank(pct=True)[-1], raw=False)

    return ret_quantile.values[-1]

def get_up_stock(stocks, fq='post'):
    current_price = [attribute_history(stock, 1, '1m', ['close'], fq=fq)['close'][0] for stock in stocks]
    lastd_close = [attribute_history(stock,1,'1d',['open'],fq = fq)['open'][0] for stock in stocks ]
    # price = [float(x) for x in price]

    final_stocks = pd.DataFrame(current_price,index = stocks,columns = ['current_price'])
    final_stocks['lastd_close'] = lastd_close
    return final_stocks[final_stocks.current_price > g.up_ratio * final_stocks.lastd_close].index.values
def get_ols(X,y):
    X = list(X)
    y = list(y)
    if X and y:
        n = len(y)
        cov = np.cov(np.vstack((X,y)))
        beta = cov[0,1]/cov[0,0]
        # r2 =1 - (1- beta**2 * cov[0,0]/cov[1,1])*(n-1)/(n-2)
        r2 = beta**2 * cov[0,0]/cov[1,1]
        return beta,r2
    return 0,0
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    

