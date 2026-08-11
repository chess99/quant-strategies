# 克隆自聚宽文章：https://www.joinquant.com/post/35235
# 标题：ETF动量轮动MA乖离择时
# 作者：莫急莫急

from jqdata import *
import numpy as np

#初始化函数 
def initialize(context):
    set_benchmark('399006.XSHE')
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    set_slippage(FixedSlippage(0.001))
    set_order_cost(OrderCost(open_tax=0, close_tax=0, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),
                   type='fund')
    log.set_level('order', 'error')
    g.stock_pool = [
        '510050.XSHG', # 上证50ETF
        # '159915.XSHE', # 创业板ETF
        '159928.XSHE', # 中证消费ETF
        '510300.XSHG', # 沪深300ETF
        # '510500.XSHG', # 中证500ETF
        '159949.XSHE', # 创业板50ETF
    ]
    # 备选池：用流动性和市值更大的50ETF分别代替宽指ETF，500与300ETF保留一个
    
    g.stock_num = 1 #买入评分最高的前stock_num只股票
    g.momentum_day = 20 #最新动量参考最近momentum_day的
    g.ref_stock = '000300.XSHG' #用ref_stock做择时计算的基础数据
    run_daily(my_trade, time='14:50', reference_security='000300.XSHG')
    run_daily(check_lose, time='open', reference_security='000300.XSHG')

# 20日收益率动量拟合取斜率最大的
def get_rank(stock_pool):
    rank = []
    for stock in g.stock_pool:
        data = attribute_history(stock, g.momentum_day, '1d', ['close'])
        score = np.polyfit(np.arange(len(data)),data.close/data.close[0],1)[0]
        rank.append([stock, score])
    rank.sort(key=lambda x: x[-1],reverse=True)
    return rank[0]

# 因子标准化
def get_zscore(series):
    mean = np.mean(series)
    std = np.std(series)
    return (series[-1] - mean) / std

# 相对均线的乖离作为择时信号，效果不如RSRS择时好，可能模型不好或者参数没有优化好，
# 不过大体上每个时段都有一些超额
def get_timing_signal(stock):
    score_threshold = 4.0  # 择时因子阈值
    data = attribute_history(g.ref_stock,200,'1d',['close'])
    data['bias'] = data.close/data.close.rolling(60).mean()  # 计算相对60日均线的乖离
    data['biasma'] = data.bias.rolling(10).mean()            # 计算乖离的10日均线，降低涨落
    score = get_zscore(data.biasma[-30:])  # 因子标准化
    if score > score_threshold: return 'BUY'
    if score < -score_threshold: return 'SELL'
    else: return 'KEEP'
   

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
		    log.info('换仓！')
		    close_position(context.portfolio.positions[stock])
	position_count = len(context.portfolio.positions)
	if g.stock_num > position_count:
		value = context.portfolio.cash / (g.stock_num - position_count)
		for stock in buy_stocks:
		    if not context.portfolio.positions: open_position(stock,value)

def my_trade(context):
    hour = context.current_dt.hour
    minute = context.current_dt.minute
    if hour == 14 and minute == 50:
        check_out_list = get_rank(g.stock_pool)
        # print('今日自选股:{}'.format(check_out_list))
        timing_signal = get_timing_signal(g.ref_stock)
        print('今日自选及择时信号:{} {}'.format(check_out_list,timing_signal))
        if timing_signal == 'SELL':
            for stock in context.portfolio.positions:
                position = context.portfolio.positions[stock]
                close_position(position)
        elif timing_signal == 'BUY' or timing_signal == 'KEEP':
            adjust_position(context, check_out_list)
        else: pass

# 止损模块，有一点点用
def check_lose(context):
    for stk in context.portfolio.positions:
        position = context.portfolio.positions[stk]
        if position.price/position.avg_cost < 0.9:
            log.info('触发止损!')
            order_target_value(position.security, 0)
