# 克隆自聚宽文章：https://www.joinquant.com/post/26142
# 标题：基于动量因子的ETF轮动加上RSRS择时
# 作者：慕长风

from jqdata import *
import numpy as np


def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))    
    # 设置交易成本万分之五
    set_order_cost(OrderCost(open_tax=0, close_tax=0, open_commission=0.0005, close_commission=0.0005, close_today_commission=0, min_commission=5),
                   type='fund')
    # 初始化各类全局变量
    initial_config()
    # 设置交易时间，每周任意时间执行一次
    run_weekly(trade, weekday=3, reference_security='000300.XSHG')


def initial_config():
    log.set_level('order', 'error')
    g.index_pool = [
        ('000016.XSHG', '510050.XSHG'), # 上证50 2005/2/23
        ('000300.XSHG', '510300.XSHG'), # 沪深300 2012/5/28
        ('399905.XSHE', '510500.XSHG'), # 中证500 2013/3/15
        ('399006.XSHE', '159915.XSHE'), # 创业板指 2011/12/9
        ('000015.XSHG', '510880.XSHG'), # 红利指数 2007/1/18
        ('399932.XSHE', '159928.XSHE'), # 中证消费 2013/9/16
        ('399913.XSHE', '512010.XSHG'), # 300医药 2013/10/28
        # ('399986.XSHE', '512800.XSHG'), # 中证银行 2017/8/3
        # ('399975.XSHE', '512880.XSHG'), # 证券公司 2016/8/8
        # ('000993.XSHG', '159939.XSHE'), # 全指信息 2015/2/5
    ]
    g.stock_num = 2
    g.momentum_day = 15
    g.stock = '000300.XSHG'
    g.N = 18
    g.M = 600
    g.mean_day = 20 
    g.mean_diff_day = 3 # 比较均线时的前后天数差
    g.score_threshold = 0.7 # RSRS标准分指标阈值
    g.slope_series = initial_slope_series()[:-1] # 除去回测第一天的slope，避免运行时重复加入

def trade(context):
    stock_hold = set(context.portfolio.positions.keys())
    stock_pool = get_stock_pool()
    signal = get_signal()
    if stock_pool and signal != "SELL":
        if stock_hold:
            change_signal = 0
            for stock in stock_hold:
                if stock not in stock_pool or stock_pool.index(stock) > g.stock_num + 1:
                    change_signal = 1
            if change_signal:
                change_position(context, stock_pool)
            else:
                pass
        else:
            change_position(context, stock_pool)
    else:
        if stock_pool and signal == "SELL":
            print("RSRS择时模型发出清仓信号！")
        for stock in stock_hold:
            order_target_value(stock, 0)


def get_stock_pool():
    ''' 对指数池内股票进行筛选和排名

    Returns:
        tuple of stock_code
    '''
    index_pool = [index for index, stock in g.index_pool]
    index_rank = []
    for index in index_pool:
        score = get_socre(index)
        if score > 0:
            index_rank.append((index, score))
    index_rank = sorted(index_rank, key=lambda x: x[1], reverse=True)
    index_dict = dict(g.index_pool)
    return tuple(index_dict[index[0]] for index in index_rank)


def get_socre(stock):
    ''' 基于股票年化收益和判定系数打分

    Returns:
        score (float): score of stock
    '''
    data = attribute_history(stock, g.momentum_day, '1d', ['close'])
    y = data['log'] = np.log(data.close)
    x = data['num'] = np.arange(data.log.size)
    slope, intercept = np.polyfit(x, y, 1)
    annualized_returns = math.pow(math.exp(slope), 250) - 1
    r_squared = 1 - (sum((y - (slope * x + intercept))**2) / ((len(y) - 1) * np.var(y, ddof=1)))
    return annualized_returns * r_squared

def change_position(context, stock_pool):
    ''' 根据stock_pool进行调仓,调仓逻辑： 
        1. 清仓
        2. 等权重依次买入股票
    '''
    for security in set(context.portfolio.positions.keys()):
        order_target_value(security, 0)
    stock_num = g.stock_num if len(stock_pool) > g.stock_num else len(stock_pool)
    cash = context.portfolio.available_cash / stock_num
    for stock in stock_pool[:stock_num]:
        order_target_value(stock, cash)

def get_signal():
    ''' 产生交易信号

    Returns:
        str: "BUY" or "SELL" or "KEEP"
    '''
    close_data = attribute_history(g.stock, g.mean_day + g.mean_diff_day, '1d', ['close'])
    today_MA = close_data.close[g.mean_diff_day:].mean() 
    before_MA = close_data.close[:-g.mean_diff_day].mean()
    data = attribute_history(g.stock, g.N, '1d', ['high', 'low'])
    intercept, slope, r2 = get_ols(data.low, data.high)
    g.slope_series.append(slope)
    rsrs_score = get_zscore(g.slope_series[-g.M:]) * slope * r2 # 右偏标准分
    if rsrs_score > g.score_threshold and today_MA > before_MA:
        return "BUY"
    elif rsrs_score < -g.score_threshold and today_MA < before_MA:
        return "SELL"
    else:
        return "KEEP"

def get_ols(x, y):
    ''' 对输入的自变量和因变量建立OLS回归模型

    Args:
        x (series of x): 每日最低价
        y (series of y): 每日最高价

    Returns：
        tuple: (截距，斜率，判定系数)
    '''
    slope, intercept = np.polyfit(x, y, 1)
    r2 = 1 - (sum((y - (slope * x + intercept))**2) / ((len(y) - 1) * np.var(y, ddof=1)))
    # print(f"slope: {slope}\tintercept: {intercept}\tr2: {r2}")
    return (intercept, slope, r2)

def initial_slope_series():
    ''' 初始化前M日内的斜率时间序列

    Returns：
        list of slope (float)
    '''
    data = attribute_history(g.stock, g.N + g.M, '1d', ['high', 'low'])
    return [get_ols(data.low[i:i+g.N], data.high[i:i+g.N])[1] for i in range(g.M)]

def get_zscore(slope_series):
    ''' 通过斜率序列计算标准分

    Returns:
        float
    '''
    mean = np.mean(slope_series)
    std = np.std(slope_series)
    return (slope_series[-1] - mean) / std
