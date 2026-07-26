# 克隆自聚宽文章：https://www.joinquant.com/post/49995
# 标题：快过年了。不想呆在小市值的，可以拿这个策略躲一躲
# 作者：MarioC

# 标题：ETF动量轮动RSRS择时-V4.0，2022/7/22
# 作者：养家大哥

# 标题：动量ETF轮动RSRS择时-v4
# 作者：杨德勇
# v2 养家大哥的思路：
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
    #set_slippage(PriceRelatedSlippage(0.002))
    set_order_cost(OrderCost(open_tax=0, close_tax=0.000, open_commission=0.0001, close_commission=0.0001, close_today_commission=0, min_commission=0),
                   type='fund')
    log.set_level('order', 'error')
    g.stock_pool = [
        # ======== 大盘 ===================
        '510300.XSHG', # 沪深300ETF
        '510050.XSHG', # 上证50ETF
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
    g.M = 600 # 计算最新标准分zscore，rsrs_score参考最近M天(600)
    g.K = 8 # 计算 zscore 斜率的窗口大小
    g.biasN = 90 #乖离动量的时间天数
    g.lossN = 20 #止损MA20---60分钟
    g.lossFactor = 1.005 #下跌止损的比例，相对前一天的收盘价
    g.SwitchFactor = 1.04 # 换仓位的比例，待换股相对当前持股的分数
    g.Motion_1diff = 19 # 股票前一天动量变化速度门限
    g.raiser_thr = 4.8 # 股票前一天上涨的比例门限
    g.hold_stock = 'null'
    g.score_threshold = 0.68 # rsrs标准分指标阈值
    g.slope_series,g.rsrs_score_history = initial_slope_series() # 除去回测第一天的slope，避免运行时重复加入
    g.stock_motion = initial_stock_motion(g.stock_pool) # 除去回测第一天的动量
    
    run_daily(my_trade_prepare, time='7:00', reference_security='000300.XSHG')
    run_daily(my_trade, time='9:30', reference_security='000300.XSHG')
    run_daily(my_sell2buy, time='9:35', reference_security='000300.XSHG')
    run_daily(check_lose, time='open', reference_security='000300.XSHG')
    # run_daily(print_trade_info, time='15:10', reference_security='000300.XSHG')
    run_daily(hold_check, time='11:27')

# 初始化准备数据,除去回测第一天的slope,zscores
def initial_slope_series():
    length = g.N+g.M+g.K
    data = attribute_history(g.ref_stock, length, '1d', ['high', 'low'])
    multe_data = [get_ols(data.low[i:i+g.N], data.high[i:i+g.N]) for i in range(length-g.N)]
    slopes = [i[1] for i in multe_data]
    r2s = [i[2] for i in multe_data]
    zscores =[(get_zscore(slopes[i+1:i+1+g.M])*r2s[i+g.M])  for i in range(g.K)]
    return (slopes,zscores)
    
    
## 获取初始化动量因子，除去回测第一天
def initial_stock_motion(stock_pool):
    stock_motion = {}
    for stock in stock_pool:
        motion_que = []
        data = attribute_history(stock, g.biasN + g.momentum_day + 1, '1d', ['close'])
        data = data[:-1]
        bias = (data.close/data.close.rolling(g.biasN).mean())[-g.momentum_day:] # 乖离因子
        score = np.polyfit(np.arange(g.momentum_day),bias/bias[0],1)[0].real*10000 # 乖离动量拟合
        motion_que.append(score)
        stock_motion[stock] = motion_que
    return(stock_motion)
    
    
## 持仓检查，盘中动态止损：早盘结束后，若60分钟周期跌破MA20均线
## 并且当前价格相对昨天没有上涨，则卖出
def hold_check(context):
    current_data = get_current_data()
    if context.portfolio.positions:
        for stk in context.portfolio.positions:
            yesterday_di = attribute_history(stk,1,'1d',['close'])
            dt = attribute_history(stk,g.lossN+2,'60m',['close'])
            dt['man'] = dt.close/dt.close.rolling(g.lossN).mean()
            #log.info("man=%0f, last_price=%0f, yester=%0f"%(dt.man[-1], current_data[stk].last_price*1.006, yesterday_di['close'][-1]))
            if((dt.man[-1] < 1.0) and (current_data[stk].last_price*g.lossFactor <= yesterday_di['close'][-1])):
            #if (dt.man[-1] < 1.0):
                g.loss_cnt = 0
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
    rank = []
    for stock in stock_pool:
        data = attribute_history(stock, g.biasN + g.momentum_day, '1d', ['close'])
        bias = (data.close/data.close.rolling(g.biasN).mean())[-g.momentum_day:] # 乖离因子
        score = np.polyfit(np.arange(g.momentum_day),bias/bias[0],1)[0].real*10000 # 乖离动量拟合
        adr = 100*(data.close[-1] - data.close[-2])/data.close[-2] #股票的涨跌幅度
        if(stock == g.hold_stock): raise_x = g.SwitchFactor
        else: raise_x = 1
        # data = attribute_history(stock, g.momentum_day, '1d', ['close'])
        # score = np.polyfit(np.arange(g.momentum_day),data.close/data.close[0],1)[0].real # 乖离动量拟合
        #log.info("计算data.close[-1]=%f, data.close[-2]=%f,adr=%f"%(data.close[-1], data.close[-2], adr))
        rank.append([stock, score*raise_x, adr])
        g.stock_motion[stock].append(score)
        if(len(g.stock_motion[stock])>5):g.stock_motion[stock].pop(0)
    #log.info('rsrs_score:')
    log.info(rank)
    rank.sort(key=lambda x: x[1],reverse=True)
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


def get_zscore_slope(z_scores):
    y = z_scores
    x = np.arange(len(z_scores))
    slope, intercept = np.polyfit(x, y, 1)
    return slope
    
# 只看RSRS因子值作为买入、持有和清仓依据，前版本还加入了移动均线的上行作为条件
def get_timing_signal(context,stock):
    data = attribute_history(g.ref_stock, g.N, '1d', ['high', 'low'])
    intercept, slope, r2 = get_ols(data.low, data.high)
    g.slope_series.append(slope)
    rsrs_score = get_zscore(g.slope_series[-g.M:]) * r2
    g.rsrs_score_history.append(rsrs_score)
    rsrs_slope = get_zscore_slope(g.rsrs_score_history[-g.K:])
    
    g.slope_series.pop(0)
    g.rsrs_score_history.pop(0)
    #record(rsrs_score=rsrs_score,rsrs_slope=rsrs_slope)
    
    log.info('rsrs_slope {:.3f}'.format(rsrs_slope)+'  rsrs_score {:.3f} '.format(rsrs_score))
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
			g.hold_stock = 'null'
			return
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
					    g.hold_stock = stock
					    break

def buy_stocks(context, buy_stocks):
	position_count = len(context.portfolio.positions)
	if g.stock_num > position_count:
		value = context.portfolio.cash / (g.stock_num - position_count)
		for stock in buy_stocks:
			if context.portfolio.positions[stock].total_amount == 0:
				if open_position(stock, value):
					if len(context.portfolio.positions) == g.stock_num:
					    g.hold_stock = stock
					    break
						
# 计算待买入的ETF和择时信号,判断股票动量变化一阶导数, 如果变化太大，则空仓
def my_trade_prepare(context):
    hour = context.current_dt.hour
    minute = context.current_dt.minute
    #if hour == 9 and minute == 30:   # 9:30开盘时买入（标的根据昨天之前的数据算出来）
    g.check_out_list = get_rank(context,g.stock_pool)
    g.timing_signal = get_timing_signal(context,g.ref_stock)
    log.info('今日自选及择时信号:{} {}'.format(g.check_out_list,g.timing_signal))
    #判断股票动量变化一阶导数, 如果变化太大，则空仓
    cur_stock = g.check_out_list[0]
    cur_adr = g.check_out_list[2]#股票价格相对前一天涨跌比例
    change_rate = g.stock_motion[cur_stock][-1]-g.stock_motion[cur_stock][-2]
    #log.info("涨跌比例:%f, 动量变化速度:%f"%(cur_adr, change_rate))
    if(change_rate>g.Motion_1diff) or (cur_adr>g.raiser_thr):
        g.timing_signal = 'SELL'
        log.info("由于涨跌:%f, 动量变化%0f，今日空仓"%(cur_adr, change_rate))
    if g.timing_signal == 'SELL':
        for stock in context.portfolio.positions:
            print("准备卖出ETF [%s]"%stock)
            send_message("准备卖出ETF [%s]"%stock)
    elif g.timing_signal == 'BUY' or g.timing_signal == 'KEEP':
        if g.check_out_list[0] not in context.portfolio.positions:
            if(len(context.portfolio.positions)>0):
                stock_tmps = list(context.portfolio.positions.keys())
                print("准备卖ETF [%s], 买入ETF [%s]"%(stock_tmps[0], g.check_out_list[0]))
                send_message("准备卖ETF [%s], 买入ETF [%s]"%(stock_tmps[0], g.check_out_list[0]))
            else:
                print("准备买入ETF [%s]"%g.check_out_list[0])
                send_message("准备买入ETF [%s]"%g.check_out_list[0])
    else: pass
    
# 交易主函数，先确定ETF最强的是谁，然后再根据择时信号判断是否需要切换或者清仓
def my_trade(context):
    hour = context.current_dt.hour
    minute = context.current_dt.minute
    #if hour == 9 and minute == 30:   # 9:30开盘时买入（标的根据昨天之前的数据算出来）
    if g.timing_signal == 'SELL':
        for stock in context.portfolio.positions:
            position = context.portfolio.positions[stock]
            close_position(position)
    elif g.timing_signal == 'BUY' or g.timing_signal == 'KEEP':
        adjust_position(context, g.check_out_list)
    else: pass

def my_sell2buy(context):
    hour = context.current_dt.hour
    minute = context.current_dt.minute
    #if hour == 9 and minute == 30:   # 9:30开盘时买入（标的根据昨天之前的数据算出来）
    if hour == 9:
        if g.timing_signal == 'BUY' or g.timing_signal == 'KEEP':
            buy_stocks(context, g.check_out_list)
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
            print("！！！！！！触发止损信号: 标的={},标的价值={},浮动盈亏={}% ！！！！！！"
                .format(security,format(value,'.2f'),format(ret,'.2f')))

    
def print_trade_info(context):
    #打印当天成交记录
    trades = get_trades()
    for _trade in trades.values(): print('成交记录：'+str(_trade))
    #打印账户信息
    print('———————————————————————————————————————分割线1————————————————————————————————————————')
