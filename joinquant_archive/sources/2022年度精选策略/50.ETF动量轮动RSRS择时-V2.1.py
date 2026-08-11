# 克隆自聚宽文章：https://www.joinquant.com/post/37516
# 标题：ETF动量轮动RSRS择时-V2.1
# 作者：Deemoo

# 克隆自聚宽文章：https://www.joinquant.com/post/36113
# 标题：动量ETF轮动RSRS择时-v2
# 作者：Deemoo
# v2 莫急莫急的思路：
# 趋势因子的特点是无法及时判断趋势的变向，往往趋势变向一段时间后才能跟上，
# 巨大回撤往往就发生在这种时候。因此基于动量因子的一阶导数，衡量趋势的潜在变化速度，
# 若变化速度过快则空仓，反之则按原计划操作。
# 可以进一步发散，衡量动量因子的二阶导、三阶导等等，暂时只测试过一阶导，就是目前这个升级2版本。


from jqdata import *
import numpy as np


#初始化函数 
def initialize(context):
    set_benchmark('399006.XSHE')
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)  # 避免引入未来信息
    set_slippage(FixedSlippage(0.001))
    set_order_cost(OrderCost(open_tax=0, close_tax=0, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=0),
                   type='fund')
    log.set_level('order', 'error')
    g.stock_pool = [
        # ======== 大盘 ===================
        '510050.XSHG', # 上证50ETF
        '510300.XSHG', # 沪深300ETF
        # '510180.XSHG', # 上证180 （用于替换上证50或沪深300，其与创业板有重合）
        '159949.XSHE', # 创业板500 
        # '159915.XSHE', # 创业指数，替代创业500
        # '510500.XSHG', # 500ETF
        # '159915.XSHE', # 创业板 ETF
        '159928.XSHE', # 中证消费ETF
        # '512120.XSHG', # 医药50ETF
        # '510880.XSHG', # 红利ETF
    ]
    # 备选池：用流动性和市值更大的50ETF分别代替宽指ETF，500与300ETF保留一个
    
    g.stock_num = 1 #买入评分最高的前stock_num只股票
    g.momentum_day = 20 #最新动量参考最近momentum_day的
    g.ref_stock = '000300.XSHG' #用ref_stock做择时计算的基础数据
    g.N = 18 # 计算最新斜率slope，拟合度r2参考最近N天
    g.M = 600 # 计算最新标准分zscore，rsrs_score参考最近M天
    g.K = 8 # 计算 zscore 斜率的窗口大小
    g.score_threshold = 0.7 # rsrs标准分指标阈值
    g.slope_series,g.rsrs_score_hisitory = initial_slope_series() # 除去回测第一天的slope，避免运行时重复加入
    g.checktime = '13:00'
    g.checktime2 = '13:50'

    
    run_daily(my_trade, time='9:30', reference_security='000300.XSHG')
    run_daily(check_lose, time='open', reference_security='000300.XSHG')
    # run_daily(print_trade_info, time='15:30', reference_security='000300.XSHG')
    run_daily(hold_check,time=g.checktime)

## 持仓检查，盘中动态止损：早盘结束后，若60分钟周期跌破MA20均线则卖出 
def hold_check(context):
    N = 20
    if context.portfolio.positions:
        for stk in context.portfolio.positions:
            dt = attribute_history(stk,N+2,'60m',['close'])
            dt['man'] = dt.close/dt.close.rolling(N).mean()
            if (dt.man[-1] < 1.0):
                stk_dict = context.portfolio.positions[stk]
                log.info('准备平仓，总仓位:{}, 可卖出：{}, '.format(stk_dict.total_amount,stk_dict.closeable_amount))
                send_message("盘中止损，卖出：{}".format(stk))
                if(stk_dict.closeable_amount):
                    order_target_value(stk,0)
                    log.info('盘中止损',stk)
                else:
                    log.info('无法止损',stk)
         
                    


## 动量因子：由收益率动量改为相对MA90均线的乖离动量
def get_rank(context,stock_pool):
    rank,biasN = [], 90
    for stock in g.stock_pool:
        data = attribute_history(stock, biasN + g.momentum_day, '1d', ['close'])
        bias = (data.close/data.close.rolling(biasN).mean())[-g.momentum_day:] # 乖离因子
        score = np.polyfit(np.arange(g.momentum_day),bias/bias[0],1)[0].real # 乖离动量拟合
        
        # data = attribute_history(stock, g.momentum_day, '1d', ['close'])
        # score = np.polyfit(np.arange(g.momentum_day),data.close/data.close[0],1)[0].real # 乖离动量拟合
        rank.append([stock, score])
    rank.sort(key=lambda x: x[-1],reverse=True)
    return rank[0]

## 线性回归：复现statsmodels的get_OLS函数
def get_ols(x, y):
    slope, intercept = np.polyfit(x, y, 1)
    r2 = 1 - (sum((y - (slope * x + intercept))**2) / ((len(y) - 1) * np.var(y, ddof=1)))
    return (intercept, slope, r2)

## 因子标准化
def get_zscore(slope_series):
    mean = np.mean(slope_series)
    std = np.std(slope_series)
    return (slope_series[-1] - mean) / std


# 初始化准备数据
def initial_slope_series():
    length = g.N+g.M+g.K
    data = attribute_history(g.ref_stock, length, '1d', ['high', 'low'])
    multe_data = [get_ols(data.low[i:i+g.N], data.high[i:i+g.N]) for i in range(length-g.N)]
    slopes = [i[1] for i in multe_data]
    r2s = [i[2] for i in multe_data]
    zscores =[(get_zscore(slopes[i:i+g.M])*r2s[i-g.K])  for i in range(g.K)]
    return (slopes,zscores)


def get_zscore_slope():
    y = g.rsrs_score_hisitory[-g.K:]
    x = np.arange(g.K)
    slope, intercept = np.polyfit(x, y, 1)
    return slope
    
# 只看RSRS因子值作为买入、持有和清仓依据，前版本还加入了移动均线的上行作为条件
def get_timing_signal(context,stock):
    
    data = attribute_history(g.ref_stock, g.N, '1d', ['high', 'low','volume'])
    intercept, slope, r2 = get_ols(data.low, data.high)
    # log.info('intercept={}, slope={}, r2={} '.format(intercept,slope,r2))
    g.slope_series.append(slope)
 
    rsrs_score = get_zscore(g.slope_series[-g.M:]) * r2
    log.info('rsrs_score {:.3f} '.format(rsrs_score))
    g.rsrs_score_hisitory.append(rsrs_score)
    
    rsrs_slope = get_zscore_slope()
    record(rsrs_score=rsrs_score,rsrs_slope=rsrs_slope)
    
    
    if(rsrs_slope< 0 and rsrs_score >0):
        return "SELL"
    
    if (rsrs_score> (-g.score_threshold)) : return "BUY"
    else: return "SELL"


#4-1 交易模块-自定义下单
#报单成功返回报单(不代表一定会成交),否则返回None,应用于
def order_target_value_(security, value):
# 	if value == 0:
# # 		log.debug("Selling out %s" % (security))
# 	else:
# 		log.debug("Order %s to value %f" % (security, value))
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
# 			log.info("[%s]已不在应买入列表中" % (stock))
			position = context.portfolio.positions[stock]
			close_position(position)
		else:
		    pass
# 			log.info("[%s]已经持有无需重复买入" % (stock))
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
    if hour == 9 and minute == 30:   # 9:30开盘时买入（标的根据昨天之前的数据算出来）
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
        security=position.security
        cost=position.avg_cost
        price=position.price
        ret=100*(price/cost-1)
  
        
        if ret <=-90:
            order_target_value(position.security, 0)
            print("！！！！！！触发止损信号1: 标的={},标的价值={},浮动盈亏={}% ！！！！！！"
                .format(security,format(value,'.2f'),format(ret,'.2f')))

    
def print_trade_info(context):
    #打印当天成交记录
    trades = get_trades()
    for _trade in trades.values(): print('成交记录：'+str(_trade))
    #打印账户信息
    print('———————————————————————————————————————分割线————————————————————————————————————————')



