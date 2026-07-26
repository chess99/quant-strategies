# 克隆自聚宽文章：https://www.joinquant.com/post/26117
# 标题：持续跑赢大盘-真蓝筹v2(资金容量千万以上)
# 作者：柱子嗨翻天

# 导入函数库
import statsmodels.api as sm
import pandas as pd
import numpy as np
import datetime as dt 
from jqdata import *

# 初始化函数，设定基准等等
def initialize(context):
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    # 设置RSRS指标
    set_parameter_RSRS(context)
    # 设置一般参数
    g.trend='None'
    g.day_count=0
    g.period=22

     # 开盘前运行
    run_daily(before_market_open, time='9:20', reference_security='000300.XSHG')
     # 开盘时运行
    run_daily(market_open, time='open', reference_security='000300.XSHG')
 

#################################参数设置部分#################################
def set_parameter_RSRS(context):
    # 设置RSRS指标
    #统计周期
    g.N = 18
    #统计样本长度
    g.M = 1100
    # g.M = 600
    #首次运行判断
    g.init = True
    #风险参考基准
    g.security = '000300.XSHG' #沪深300
    # 设定策略运行基准
    set_benchmark(g.security)
    # 买入阈值
    g.buy = 0.7
    g.sell = -0.7
    #用于记录回归后的beta值，即斜率
    g.ans = []
    #用于计算被决定系数加权修正后的贝塔值
    g.ans_rightdev= []

    # 计算2005年1月5日至回测开始日期的RSRS斜率指标
    # 获得回测前一天日期，千万避免未来数据
    previous_date = context.current_dt - datetime.timedelta(days=2)
    prices = get_price(g.security, '2005-01-05', previous_date, '1d', ['high', 'low'])
    prices[np.isnan(prices)] = 0
    prices[np.isinf(prices)] = 0    
    highs = prices.high
    lows = prices.low
    g.ans = []
    for i in range(len(highs))[g.N:]:
        data_high = highs.iloc[i-g.N+1:i+1]
        data_low = lows.iloc[i-g.N+1:i+1]
        X = sm.add_constant(data_low)
        model = sm.OLS(data_high,X)
        results = model.fit()
        g.ans.append(results.params[1])
        #计算r2
        g.ans_rightdev.append(results.rsquared)
    
## 开盘前运行函数     
def before_market_open(context):
    # 计算RSRS斜率数据，判断多空时机
    # 填入各个日期的RSRS斜率值
    beta=0
    r2=0
    if g.init:
        g.init = False
    else:
        #RSRS斜率指标定义
        prices = attribute_history(g.security, g.N, '1d', ['high', 'low'])
        prices[np.isnan(prices)] = 0
        prices[np.isinf(prices)] = 0
        highs = prices.high
        lows = prices.low
        X = sm.add_constant(lows)
        model = sm.OLS(highs, X)
        beta = model.fit().params[1]
        g.ans.append(beta)
        #计算r2
        r2=model.fit().rsquared
        g.ans_rightdev.append(r2)
    # 计算标准化的RSRS指标
    section = g.ans[-g.M:]
    # 计算均值序列
    mu = np.mean(section)
    # 计算标准化RSRS指标序列
    sigma = np.std(section)
    zscore = (section[-1]-mu)/sigma  
    #计算右偏RSRS标准分
    g.zscore_rightdev= zscore*beta*r2
    
    # 如果上一时间点的RSRS斜率大于买入阈值, 则全仓买入
    if g.zscore_rightdev > g.buy:
        log.info("市场风险在合理范围。做多。")
        g.trend='up'   
        
    # 如果上一时间点的RSRS斜率小于卖出阈值, 则空仓卖出
    if g.zscore_rightdev < g.sell:
        log.info("市场风险过大。不做多")
        g.trend='down'
    log.info('趋势',g.trend)
    log.info('今日右偏RSRS标准分：',g.zscore_rightdev)

## 开盘时运行函数
def market_open(context):
    # 先检测期货空单卖出（平空单当天做多）
    if g.trend=='up':
        log.info('趋势向上，多头交易')
    elif g.trend=='down':
        log.info('趋势向下，清仓')
        sell_all(context)
        g.day_count=0
        return
    
    # 以月为周期轮动（更新持仓股票）
    if g.day_count%g.period!=0:
        g.day_count=g.day_count+1
        return
    pool=get_stock_pool('000300.XSHG',context)    
    # 换仓
    positions_list = context.portfolio.positions.keys()
    sell_list = set(positions_list)-set(pool)
    buy_list = set(pool)-set(positions_list)
    # 将不在股票池中的股票卖出
    for stock in sell_list:
        order_target_value(stock, 0)    
    #买入股票（每只持仓股票金额保持一致）
    for stock in pool:
        value = context.portfolio.total_value/len(pool)
        order_target_value(stock,value)
    
    # 持仓计数器
    g.day_count=g.day_count+1
    log.info('g.day_count',g.day_count) 
 
 
 
#################################工具函数######################################    
# 获取连续10年盈利增长的股票
def get_stock_pool(index,context):
    stocks = get_index_stocks(index) #股票池
    dt_now =  context.current_dt.date() #当前时间
    # 过滤，上市10年以上
    date_list = [ 
        dt_now - datetime.timedelta(days = 1),
        dt_now - datetime.timedelta(days = 1*365),
        dt_now - datetime.timedelta(days = 2*365),
        dt_now - datetime.timedelta(days = 3*365),
        dt_now - datetime.timedelta(days = 4*365),
        dt_now - datetime.timedelta(days = 5*365),
        dt_now - datetime.timedelta(days = 6*365),
        dt_now - datetime.timedelta(days = 7*365),
        dt_now - datetime.timedelta(days = 8*365),
        dt_now - datetime.timedelta(days = 9*365),
        ]#十年的时间序列    
    stocks = [s for s in stocks if get_security_info(s).start_date <  date_list[-1]]
    
    # 过滤，当前基本面良好（pe>0,pb>0）
    df = get_fundamentals(query(
            valuation.code,
            valuation.pb_ratio,
            valuation.pe_ratio,
        ).filter(
            valuation.code.in_(stocks),
            valuation.pb_ratio > 0,
            valuation.pe_ratio > 0,
        )).dropna().set_index('code')
    stocks = list(df.index)
    
    # 提取收益数据
    df_earn = pd.DataFrame(columns = stocks)
    for idate in date_list:
        idf = get_fundamentals(query(
                valuation.code,
                valuation.market_cap,
                (valuation.market_cap/valuation.pe_ratio).label('earn'),
            ).filter(
                valuation.code.in_(stocks)
            ), date=idate
            ).set_index('code')
        df_earn.loc[idate] = idf.earn.T   
    
    # 过滤，连续10年增长
    for ix in range(len(date_list)-1):
        stocks = [s for s in stocks if df_earn.iloc[ix][s] > df_earn.iloc[ix+1][s]]

    # 输出所有蓝筹股
    # df = df.loc[stocks]
    # df['name'] = [get_security_info(s).display_name for s in list(df.index)]
    # log.info('股票池数量', len(df))
    # log.info(df)  
    return stocks

def sell_all(context):
    for stock in context.portfolio.positions.keys():
        order_target(stock,0)
    
