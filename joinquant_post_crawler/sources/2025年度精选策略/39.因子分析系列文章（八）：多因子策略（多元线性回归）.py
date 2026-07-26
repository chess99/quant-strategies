# 克隆自聚宽文章：https://www.joinquant.com/post/25273
# 标题：因子分析系列文章（八）：多因子策略（多元线性回归）
# 作者：量化狙击

# 多因子策略-APT模型（Multi-factor） 
import math
import datetime
import numpy as np
import pandas as pd
from jqdata import *
# 导入多元线性规划需要的工具包
import statsmodels.api as sm
from statsmodels import regression
import datetime as dt

'''
================================================================================
总体回测前
================================================================================
'''
#总体回测前要做的事情
def initialize(context):
    set_params()      # 设置策参数
    set_variables()   # 设置中间变量
    set_backtest()    # 设置回测条件
    

#设置策略参数
def set_params():
    g.tc = 5          # 设置调仓天数
    g.stocknum = 20   # 持有股票数量


#设置中间变量
def set_variables():
    g.t = 0                # 记录回测运行的天数
    g.if_trade = False     # 当天是否交易


#设置回测条件
def set_backtest():
    # 当前价格的百分比设置滑点
    set_slippage(PriceRelatedSlippage(0.002))   
    # 设置对比基准
    set_benchmark('000985.XSHG') 
    # 使用真实价格
    set_option('use_real_price', True)
    # 设置报错等级
    log.set_level('order', 'error')


'''
================================================================================
每天开盘前
================================================================================
'''
# 每天开盘前要做的事。计算tiaocang
def before_trading_start(context):
    if g.t%g.tc==0:
        #每g.tc天，交易一次
        g.if_trade=True 
        # 设置手续费与手续费
        set_slip_fee(context) 
    g.t += 1
    

# 设置可行股票池：
# 过滤掉当日停牌的股票,且筛选出前days天未停牌股票
# 输入：stock_list为list类型,样本天数days为int类型，context（见API）
# 输出：list
def set_feasible_stocks(stock_list,days,context):
    # 得到是否停牌信息的dataframe，停牌的1，未停牌得0
    suspened_info_df = get_price(list(stock_list), start_date=context.current_dt, end_date=context.current_dt, frequency='daily', fields='paused')['paused'].T
    # 过滤停牌股票 返回dataframe
    unsuspened_index = suspened_info_df.iloc[:,0]<1
    # 得到当日未停牌股票的代码list:
    unsuspened_stocks = suspened_info_df[unsuspened_index].index
    # 进一步，筛选出前days天未曾停牌的股票list:
    feasible_stocks=[]
    current_data=get_current_data()
    for stock in unsuspened_stocks:
        if sum(attribute_history(stock, days, unit='1d',fields=('paused'),skip_paused=False))[0]==0:
            feasible_stocks.append(stock)
    return feasible_stocks


# 根据不同的时间段设置滑点与手续费
def set_slip_fee(context):
    # 将滑点设置为0
    set_slippage(FixedSlippage(0)) 
    # 根据不同的时间段设置手续费
    dt=context.current_dt
    if dt>datetime.datetime(2013,1, 1):
        set_commission(PerTrade(buy_cost=0.0003, sell_cost=0.0013, min_cost=5)) 
        
    elif dt>datetime.datetime(2011,1, 1):
        set_commission(PerTrade(buy_cost=0.001, sell_cost=0.002, min_cost=5))
            
    elif dt>datetime.datetime(2009,1, 1):
        set_commission(PerTrade(buy_cost=0.002, sell_cost=0.003, min_cost=5))
    else:
        set_commission(PerTrade(buy_cost=0.003, sell_cost=0.004, min_cost=5))


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


# DF类型MAD数据清洗function，一次处理多列数据
def fun_normalizeData(df):
    for key in df.keys():
        if (key != 'code'):
            mad = func_mad(df[key])
            MA = np.mean(df[key])
            for i in range(len(df[key])):
                x = df.loc[i,key]
                if (x > MA + 3*mad):
                    x = MA + 3*mad
                elif (x < MA - 3*mad):
                    x = MA - 3*mad
    return df


# 求MAD绝对中位值
def func_mad(myData):
    return np.mean(np.absolute(myData - np.mean(myData)))    


# 取得股票某个区间内的所有收盘价（用于取前interval日和当前日 收盘价）
def getStockPrice(stock, interval): # 输入stock证券名，interval期
    h = attribute_history(stock, interval, unit='1d', fields=('close'), skip_paused=True)
    return (h['close'].values[0] , h['close'].values[-1])
    # 0是第一个（interval周期的值,-1是最近的一个值(昨天收盘价)）
 

# 协助进行线性回归(SVR)
# 输入：factors是所有股票的上一期因子值-list，returns是股票上一期的收益
# 支持list,array,DataFrame等三种数据类型
def linreg(factors,returns):
    # 加入一列常数列，表示市场的状态以及因子以外没有考虑到的因素
    X = sm.add_constant(array(factors))
    Y = array(returns)
    # 进行多元线性回归
    results = regression.linear_model.OLS(Y, X).fit()
    # 进行SVR回归
    # svr = SVR(kernel='rbf', gamma=0.1) 
    # model = svr.fit(X, Y)
    # 返回多元线性回归的参数值
    return results.params
    # return model.get_params()

# 求dataframe 对于X的中性化后的df, X是df中的一个key
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
    
    
'''
================================================================================
每天交易时
================================================================================
'''
def handle_data(context, data):

    # 每个调仓日截面上，进行数据提取和计算
    if g.if_trade == True:
        # 从000985中证全指中提取个股，由全部A股股票中剔除ST、*ST股票，不足3个月等股票后的剩余股票构成样本股
        sample = get_index_stocks('000985.XSHG', date = None)
        
        # 过滤停牌退市ST股票，次新股
        sample = filter_stock_ST(sample)
        sample = remove_new_stocks(sample,context)
        sample = filter_stock_limit(sample)
    
        # 获取基本面数据并作初步计算
        q = query(valuation.code, 
                    valuation.market_cap, # 总市值(亿元)
                    balance.total_assets / balance.total_liability, # 杠杆率
                    indicator.inc_net_profit_year_on_year, # 净利润同比增长率（质量成长）
                    indicator.inc_revenue_year_on_year, # 营业收入同比增长率（规模成长）
                    indicator.roe / valuation.pb_ratio, # PB-ROE
                    valuation.pe_ratio / indicator.inc_net_profit_year_on_year, # PEG
                    ).filter(
                        # 优选基本面质量较好的股票进行回归
                        valuation.pe_ratio / indicator.inc_net_profit_year_on_year>0,
                        valuation.pe_ratio / indicator.inc_net_profit_year_on_year<1,
                        valuation.code.in_(sample))
                    
        # 本期基本面数据df，并清洗
        df = get_fundamentals(q, date = None)
        df.dropna(axis=0,how='any') # 删除表中含有任何NaN的行
        # 打开后执行3倍MAD数据清洗
        # df = fun_normalizeData(df)
        # 上一期时间,context.current_dt是交易日，不是一般的日期，这非常重要！！
        pre_date = context.current_dt - dt.timedelta(days=g.tc+1)
        

   
        
       # print (pre_date)
        # 上一期基本面数据df_p，并清洗
        df_p = get_fundamentals(q, date = pre_date)
        df_p.dropna(axis=0,how='any') # 删除表中含有任何NaN的行
        # 打开后执行3倍MAD数据清洗
        # df_p = fun_normalizeData(df_p)
        
        # 求个股本周期回报值（个股名单在df.code列中），作为回归目标Y
        momentum = []
        # for i in sample:
        for i in list(df.code):    
            interval,Yesterday = getStockPrice(i, g.tc) 
            stock_momentum = Yesterday / interval - 1
            momentum.append((i, stock_momentum))
        # 转化成np.array结构，方便取出第二列数据（回报值）
        np_momentuma = np.array(momentum)
        momentum_value = np_momentuma[:,1].astype(float).tolist()
        df['momentum_value'] = momentum_value


        # ====================== 新增因子部分 开始 ========================
        # 此处可新增各类自定义因子
        # ====================== 新增因子部分 结束 ========================
    
        # 本期因子排列命名，并中性化（可选）
        df = df.dropna()
        df.columns = ['code','market_cap','LEV','INP_YOY','IR_YOY','ROE_PB', 'PE_G','momentum_value']
        df.index = df.code.values
        # df['momentum_value'] = np.log(df['momentum_value']) 
        # 市值中性化过程
        # df = df_neutralization(df,'market_cap')
        del df['code']
        
        # 上期因子排列命名，并中性化（可选）
        df_p = df_p.dropna()
        df_p.columns = ['code','market_cap','LEV','INP_YOY','IR_YOY','ROE_PB', 'PE_G']
        df_p.index = df_p.code.values
        # 市值中性化过程
        # df_p = df_neutralization(df_p,'market_cap')
        del df_p['code']

        # X_p是上一期的因子值部分，X是本期因子值部分，Y是回归目标
        X_p = df_p[['LEV','IR_YOY','INP_YOY','ROE_PB','PE_G']]
        X = df[['LEV','IR_YOY','INP_YOY','ROE_PB', 'PE_G']]
        Y = df[['momentum_value']]

        
        # 舍弃X_p和Y中不同的index（股票代码），如[u'000975.XSHE']
        # 先去除X_p比Y多的index
        diffIndex = X_p.index.difference(Y.index)   #包含在第一个集合中，但不包含在第二个集合
        # 删除整行
        X_p = X_p.drop(diffIndex,errors='ignore')
        X = X.drop(diffIndex,errors='ignore')
        Y = Y.drop(diffIndex,errors='ignore')
        
        # 然后去除Y比X_p多的index
        diffIndex = Y.index.difference(X_p.index)
        X_p = X_p.drop(diffIndex,errors='ignore')
        X = X.drop(diffIndex,errors='ignore')
        Y = Y.drop(diffIndex,errors='ignore')
        
        # 用上期因子值，和本期回报率，训练得到权重weights
        weights = linreg(X_p,Y)   #一元线性回归
        print (weights)
        # 带入本期因子值X，到股价公式，weights[1:]是从第二行开始所有行
        # print(weights)
        points = X.dot(weights[1:]) + weights[0]
       
        # 做降序排序，买入回归股价高的股票
        points.sort(ascending = False)
        print (points)        
        # 通过list函数将factor的index列转化成list数据类型，然后买入前g.stocknum个
        order_list = list(points.index[:g.stocknum])
        # 最终名单，分别下单给两个交易函数
        order_stock_sell(context,order_list)
        order_stock_buy(context,order_list)
        
    g.if_trade = False


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
        # g.each_stock_cash = 10000000/num
    else:
        # 如果持仓个数满足要求，不再计算g.each_stock_cash
        cash = 0
        num = 0
    # 执行买入
    for stock in order_list:
        if stock not in context.portfolio.positions:
            order_target_value(stock, g.each_stock_cash)    
