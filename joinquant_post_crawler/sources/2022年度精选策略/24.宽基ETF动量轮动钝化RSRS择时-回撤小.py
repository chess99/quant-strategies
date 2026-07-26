# 克隆自聚宽文章：https://www.joinquant.com/post/37120
# 标题：宽基ETF动量轮动钝化RSRS择时-回撤小
# 作者：DominicLiu

'''
策略思路来自萌新王富贵和莫急莫急两位大神
引入钝化RSRS，并增加止损，买入511880等模块
'''
# 导入函数库
from jqdata import *
import numpy as np

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    # log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 股票池
    g.stock_pool = [
        # '510050.XSHG', # 上证50ETF
         '000300.XSHG', # 沪深300
         '000905.XSHG', # 500
         '399006.XSHE', # 创业板
        # '510180.XSHG', # 上证180
        # '513100.XSHG', # 纳指
        # '159928.XSHE', # 消费ETF
    ]
    g.momentum_day = 29 #最新动量参考最近momentum_day的
    g.N = {'000300.XSHG':18, '000905.XSHG':18, '399006.XSHE':18}# 计算最新斜率slope，拟合度r2参考最近N天
    g.M = {'000300.XSHG':700, '000905.XSHG':800, '399006.XSHE':500} # 计算最新标准分zscore，rsrs_score参考    g.slope_series = initial_slope_series() # 除去回测第一天的slope，避免运行时重复加入
    g.score_threshold = {'000300.XSHG':0.7, '000905.XSHG':1, '399006.XSHE':0.4} # rsrs标准分指标阈值
    g.max_value = None #止损使用
    g.last_value = None #止损使用
    g.check_out_list = None #选股
    g.timing_signal = None #择时

    
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之一一，卖出时佣金万分之一一, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0, open_commission=0.00011, close_commission=0.00011, min_commission=5), type='stock')
    # 滑点0.001
    set_slippage(FixedSlippage(0.001))

      # 开盘时运行
    run_daily(calculate, time='8:00', reference_security='000300.XSHG')
    run_daily(market_open, time='open', reference_security='000300.XSHG')
    run_daily(my_trade, time='11:20', reference_security='000300.XSHG')
    run_daily(my_trade, time='14:50', reference_security='000300.XSHG')

#选股：动量因子轮动，基于股票年化收益和判定系数打分,选出最高的
def get_rank(context,stock_pool):
    score_list = []
    for stock in g.stock_pool:
        data = attribute_history(stock, g.momentum_day, '1d', ['close'])
        y = data['log'] = np.log(data.close)
        x = data['num'] = np.arange(data.log.size)
        slope, intercept = np.polyfit(x, y, 1)
        annualized_returns = math.pow(math.exp(slope), 250) - 1
        r_squared = 1 - (sum((y - (slope * x + intercept))**2) / ((len(y) - 1) * np.var(y, ddof=1)))
        score = annualized_returns * r_squared
        score_list.append(score)
    stock_dict=dict(zip(g.stock_pool, score_list))
    sort_list=sorted(stock_dict.items(), key=lambda item:item[1], reverse=True) #True为降序
    code_list=[]
    for i in range((len(g.stock_pool))):
        code_list.append(sort_list[i][0])
    rank_stock = code_list[0]
    return rank_stock

#线性回归：复现statsmodels的get_OLS函数
def get_ols(x, y):
    slope, intercept = np.polyfit(x, y, 1)
    r2 = 1 - (sum((y - (slope * x + intercept))**2) / ((len(y) - 1) * np.var(y, ddof=1)))
    return (intercept, slope, r2)

#因子标准化
def get_zscore(slope_series):
    mean = np.mean(slope_series)
    std = np.std(slope_series)
    return (slope_series[-1] - mean) / std
    
#择时：使用钝化RSRS因子值作为买入、持有和清仓依据
def get_timing_signal(context,stock):
    data = attribute_history(stock, g.M[stock]+g.N[stock], '1d', ['high', 'low', 'close'])
    for index in data.iterrows():
        data['pre_close'] = data.shift(periods=1)['close'] 
    data['ret'] = data['close']/data['pre_close'] - 1
    ret_std = data['ret'].rolling(g.N[stock]).std()
    ret_quantile = ret_std.tail(g.M[stock]).rank(pct=True)[-1]
    intercept, slope, r2 = get_ols(data.tail(g.N[stock]).low, data.tail(g.N[stock]).high)
    slope_series = [get_ols(data.low[i:i+g.N[stock]], data.high[i:i+g.N[stock]])[1] for i in range(g.M[stock])]
    slope_series.append(slope)
    zscore = get_zscore(slope_series[-g.M[stock]:]) 
    rsrs_score = zscore* r2**(2*ret_quantile)
    if rsrs_score > g.score_threshold[stock] : return "BUY"
    elif rsrs_score < -g.score_threshold[stock] : return "SELL"
    else: return "KEEP"
 
#提前计算当天信号
def calculate(context):
    g.check_out_list = get_rank(context,g.stock_pool)
    g.timing_signal = get_timing_signal(context,g.check_out_list)
    print("今天选股：", g.check_out_list)
    print("今天信号：", g.timing_signal)
    
# 开盘交易函数，根据信号调仓，空仓买入511880
def market_open(context):
    stock = list(context.portfolio.positions.keys())
    security = ''.join(stock)
    if g.timing_signal == 'SELL' and security != '511880.XSHG' and security != '':
        if security == g.check_out_list:
            order = order_target_value(security, 0)
        elif get_timing_signal(context,security) == 'SELL':
            order = order_target_value(security, 0)
    elif g.timing_signal == 'BUY' and g.check_out_list != security:
        order_target_value(security, 0)
        order_value(g.check_out_list, context.portfolio.available_cash)
    if context.portfolio.positions_value == 0:
        order_value('511880.XSHG', context.portfolio.available_cash)

#上午和下午收盘前止损
def my_trade(context):
    loss_ctrl(context)
    if context.portfolio.positions_value == 0:
        order_value('511880.XSHG', context.portfolio.available_cash)

# 动态止损模块
def loss_ctrl(context):
    if g.max_value is None:
        g.max_value = context.portfolio.total_value
    if g.last_value is None:
        g.last_value = context.portfolio.total_value
        
    k = context.portfolio.total_value/g.last_value-1
    if k<-0.02:
        for code in context.portfolio.positions:
            order_target(code, 0)
        log.info('市值极速下跌清仓')
        
    k = context.portfolio.total_value/g.max_value-1
    if k<-0.1:
        for code in context.portfolio.positions:
            order_target(code, 0)
        log.info('最大市值下跌清仓')
        g.max_value = context.portfolio.total_value
            
    if context.portfolio.total_value>g.max_value:
        g.max_value = context.portfolio.total_value
    g.last_value = context.portfolio.total_value    
