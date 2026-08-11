# 克隆自聚宽文章：https://www.joinquant.com/post/35338
# 标题：ETF动量轮动RSRS择时-魔改4-低通滤波
# 作者：莫急莫急

from jqdata import *
import numpy as np

#初始化函数 
def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)  # 避免引入未来信息
    set_slippage(FixedSlippage(0.001))
    set_order_cost(OrderCost(open_tax=0, close_tax=0, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),
                   type='fund')
    log.set_level('order', 'error')
    g.stock_pool = [
        '510050.XSHG', # 上证50ETF
        '159928.XSHE', # 中证消费ETF
        '510300.XSHG', # 沪深300ETF
        '159949.XSHE', # 创业板500
        # '510500.XSHG', # 500ETF
        # '159915.XSHE', # 创业板 ETF
        # '512120.XSHG', # 医药50ETF
        # '159806.XSHE', # 新能车ETF
        # '510880.XSHG', # 红利ETF
        
    ]
    # 备选池：用流动性和市值更大的50ETF分别代替宽指ETF，500与300ETF保留一个
    
    g.stock_num = 1 #买入评分最高的前stock_num只股票
    g.momentum_day = 20 #最新动量参考最近momentum_day的
    g.ref_stock = '000300.XSHG' #用ref_stock做择时计算的基础数据
    g.N = 18 # 计算最新斜率slope，拟合度r2参考最近N天
    g.M = 600 # 计算最新标准分zscore，rsrs_score参考最近M天
    g.score_threshold = 0.7 # rsrs标准分指标阈值
    g.slope_series = initial_slope_series()[:-1] # 除去回测第一天的slope，避免运行时重复加入
    run_daily(my_trade, time='9:30', reference_security='000300.XSHG')
    run_daily(check_lose, time='open', reference_security='000300.XSHG')
    run_daily(print_trade_info, time='15:30', reference_security='000300.XSHG')

# FFT低通滤波
def fftFilter(fs,N,dr):
    y = np.fft.fft(dr)
    for i in range(len(y)):  # 低通滤波
        if (i>fs) and (i<N-fs): y[i] = 0.0
    ffty = np.fft.ifft(y)  # 滤波后逆变换成收益率
    return ffty

# 20日收益率动量拟合取斜率最大的
def get_rank(context,stock_pool):
    rank = []
    fs, N = 60, 250
    for stock in g.stock_pool:
        # 用FFT进行低通滤波，fs为截止频率，N为采样数据量
        data = attribute_history(stock, N, '1d', ['close'])
        dr = np.log(data.close/data.close[0])
        newdr = fftFilter(fs,N,dr) # FFT低通滤波
        score = np.polyfit(np.arange(g.momentum_day),newdr[-g.momentum_day:],1)[0].real
        
        # 下面这两句是原始版本
        # data = attribute_history(stock, g.momentum_day, '1d', ['close','high','low','open'])
        # score = np.polyfit(np.arange(g.momentum_day),(data.close/data.close[0])[-g.momentum_day:],1)[0].real
        
        rank.append([stock, score])
    rank.sort(key=lambda x: x[-1],reverse=True)
    # log.info(rank)
    return rank[0]

# 这里求R2的式子有点问题，但是这个效果更好，原因未找到！
def get_ols(x, y):
    slope, intercept = np.polyfit(x, y, 1)
    r2 = 1 - (sum((y - (slope * x + intercept))**2) / ((len(y) - 1) * np.var(y, ddof=1)))
    return (intercept, slope, r2)

def initial_slope_series():
    data = attribute_history(g.ref_stock, g.N + g.M, '1d', ['high', 'low'])
    return [get_ols(data.low[i:i+g.N], data.high[i:i+g.N])[1] for i in range(g.M)]

# 因子标准化
def get_zscore(slope_series):
    mean = np.mean(slope_series)
    std = np.std(slope_series)
    return (slope_series[-1] - mean) / std

# 只看RSRS因子值作为买入、持有和清仓依据，前版本还加入了移动均线的上行作为条件
def get_timing_signal(context,stock):
    high_low_data = attribute_history(g.ref_stock, 18, '1d', ['high', 'low'])
    intercept, slope, r2 = get_ols(high_low_data.low, high_low_data.high)
    g.slope_series.append(slope)
    rsrs_score = get_zscore(g.slope_series[-g.M:]) * r2
    # record(slope=100*slope)
    log.info('rsrs_score {:.3f}'.format(rsrs_score))
    if rsrs_score > g.score_threshold: return "BUY"
    elif rsrs_score < -g.score_threshold: return "SELL"
    else: return "KEEP"


#4-1 交易模块-自定义下单
#报单成功返回报单(不代表一定会成交),否则返回None,应用于
def order_target_value_(security, value):
	if value == 0:
		log.debug("Selling out %s" % (security))
	else:
		log.debug("Order %s to value %f" % (security, value))
	# 如果股票停牌，创建报单会失败，order_target_value 返回None
	# 如果股票涨跌停，创建报单会成功，order_target_value 返回Order，但是报单会取消
	# 部成部撤的报单，聚宽状态是已撤，此时成交量>0，可通过成交量判断是否有成交
	return order_target_value(security, value)

#4-2 交易模块-开仓
#买入指定价值的证券,报单成功并成交(包括全部成交或部分成交,此时成交量大于0)返回True,报单失败或者报单成功但被取消(此时成交量等于0),返回False
def open_position(security, value):
	order = order_target_value_(security, value)
	if order != None and order.filled > 0:
		return True
	return False

#4-3 交易模块-平仓
#卖出指定持仓,报单成功并全部成交返回True，报单失败或者报单成功但被取消(此时成交量等于0),或者报单非全部成交,返回False
def close_position(position):
	security = position.security
	order = order_target_value_(security, 0)  # 可能会因停牌失败
	if order != None:
		if order.status == OrderStatus.held and order.filled == order.amount:
			return True
	return False

def adjust_position(context, buy_stocks):
	for stock in context.portfolio.positions:
		if stock not in buy_stocks:
			log.info("[%s]已不在应买入列表中" % (stock))
			position = context.portfolio.positions[stock]
			close_position(position)
		else:
			log.info("[%s]已经持有无需重复买入" % (stock))
	position_count = len(context.portfolio.positions)
	if g.stock_num > position_count:
		value = context.portfolio.cash / (g.stock_num - position_count)
		for stock in buy_stocks:
			if context.portfolio.positions[stock].total_amount == 0:
				if open_position(stock, value):
					if len(context.portfolio.positions) == g.stock_num:
						break


# 交易主函数，先确定ETF最强的是谁，然后再根据择时信号判断是否需要切换或者清仓
def my_trade(context):
    hour = context.current_dt.hour
    minute = context.current_dt.minute
    if hour == 9 and minute == 30:   # :30开盘时买入（标的根据昨天之前的数据算出来）
        check_out_list = get_rank(context,g.stock_pool)
        timing_signal = get_timing_signal(context,g.ref_stock)
        print('今日自选及择时信号:{} {}'.format(check_out_list,timing_signal))
        if timing_signal == 'SELL':
            for stock in context.portfolio.positions:
                position = context.portfolio.positions[stock]
                close_position(position)
        elif timing_signal == 'BUY' or timing_signal == 'KEEP':
            adjust_position(context, check_out_list)
        else: pass

# 这个函数几乎没用
def check_lose(context):
    for position in list(context.portfolio.positions.values()):
        securities=position.security
        cost=position.avg_cost
        price=position.price
        ret=100*(price/cost-1)
        value=position.value
        amount=position.total_amount
        if ret <=-90:
            order_target_value(position.security, 0)
            print("！！！！！！触发止损信号: 标的={},标的价值={},浮动盈亏={}% ！！！！！！"
                .format(securities,format(value,'.2f'),format(ret,'.2f')))

def print_trade_info(context):
    #打印当天成交记录
    trades = get_trades()
    for _trade in trades.values(): print('成交记录：'+str(_trade))
    #打印账户信息
    print('———————————————————————————————————————分割线————————————————————————————————————————')
