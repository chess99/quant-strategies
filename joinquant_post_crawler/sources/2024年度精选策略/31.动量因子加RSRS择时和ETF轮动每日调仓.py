# 克隆自聚宽文章：https://www.joinquant.com/post/42949
# 标题：动量因子加RSRS择时和ETF轮动每日调仓
# 作者：wentaogg

# 参考以下策略，感谢两位大佬
# 克隆自聚宽文章：https://www.joinquant.com/post/26142
# 标题：基于动量因子的ETF轮动加上RSRS择时
# 作者：慕长风
# 克隆自聚宽文章：https://www.joinquant.com/post/42673
# 标题：【回顾3】ETF策略之核心资产轮动
# 作者：wywy1995

from jqdata import *
import numpy as np


def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0.004))    
    # 设置交易成本万分之五
    set_order_cost(OrderCost(open_tax=0, close_tax=0, open_commission=0.0005, close_commission=0.0005, close_today_commission=0, min_commission=5),
                   type='fund')
    
    log.set_level('order', 'error')
    
  
    g.index_pool = [
        
        '518880.XSHG', #黄金ETF（大宗商品）'518880.XSHG'
        '513100.XSHG', #纳指100（海外资产）
        '159915.XSHE', #创业板100（成长股，科技股，题材性，中小盘）
        # '515080.XSHG', #红利ETF（价值股，蓝筹股，防御性，中大盘） '515080.XSHG'
        # '159928.XSHE', # 中证消费ETF
        '510180.XSHG',#上证180（价值股，蓝筹股，中大盘）
        # '159981.XSHE'#能源化工期货
    ]
    
    g.stock_num = 1
    g.momentum_day =25
    g.stock = '000300.XSHG'
    g.N = 18
    g.M = 600
    g.mean_day = 20 
    g.mean_diff_day = 3 # 比较均线时的前后天数差
    g.score_threshold = 0.7 # RSRS标准分指标阈值
    g.slope_series = initial_slope_series()[:-1] # 除去回测第一天的slope，避免运行时重复加入
     # 设置交易时间，每周任意时间执行一次
    # run_weekly(trade, weekday=3, time='9:45',reference_security='000300.XSHG')
    run_daily(trade,time='9:45')
   
def trade(context):
    stock_hold = set(context.portfolio.positions.keys())
    stock_pool = get_stock_pool()
    g.stock_number = g.stock_num if (len(stock_pool) > g.stock_num) else len(stock_pool)
    
    # print(g.stock_number)
    
    set_stock_pool=set(stock_pool[:g.stock_num])
    print(f'持仓股票{stock_hold}')
    # print(f'所有要买入的股票{stock_pool}')
    print(f'最后要买入股票{set_stock_pool}')
    signal = get_signal()
    print(signal)
    
    if stock_pool and signal != "SELL":#代表有符合买入的etf且当前信号不是卖出信号
        if stock_hold == set_stock_pool and len(set_stock_pool) != 0:
            print("当前持仓和需买入集合一致，不进行调仓")
        else:
            change_position(context, set_stock_pool)
      
    else:
        if signal == "SELL":
            print("RSRS择时模型发出清仓信号！")
        for stock in stock_hold:
            order_target_value(stock, 0)
    
    log.info('美好的一天结束')
    log.info('##############################################################')
    

def get_stock_pool():
    ''' 对指数池内股票进行筛选和排名

    Returns:
        tuple of stock_code
    '''
    # index_pool = [index for index, stock in g.index_pool]
    index_rank = []
    for index in g.index_pool:
        score = get_socre(index)
        # print((index,score))
        # if score > 0:
        index_rank.append((index, score))
    index_rank = sorted(index_rank, key=lambda x: x[1], reverse=True)#类似('510050.XSHG', -0.01681031193340185)元祖
    
    index_dict = dict(index_rank)
    record(黄金 = round(index_dict['518880.XSHG'], 2))
    record(纳指 = round(index_dict['513100.XSHG'], 2))
    record(成长 = round(index_dict['159915.XSHE'], 2))
    record(价值 = round(index_dict['510180.XSHG'], 2))
    # return tuple(index_dict[index[0]] for index in index_rank)
    return tuple(index[0] for index in index_rank)


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

def change_position(context, target_list):

    # 卖出    
    hold_list = list(context.portfolio.positions)
    for etf in hold_list:
        order_target_value(etf, 0)
        print('卖出' + str(etf))
        
    # 买入
    
    if g.stock_number > 0:
        value = context.portfolio.available_cash / g.stock_number
        for etf in target_list:
            if context.portfolio.positions[etf].total_amount == 0:
                order_target_value(etf, value)
                print('买入' + str(etf))
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
    rsrs_score = get_zscore(g.slope_series[-g.M:])  * r2 # 右偏标准分
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
