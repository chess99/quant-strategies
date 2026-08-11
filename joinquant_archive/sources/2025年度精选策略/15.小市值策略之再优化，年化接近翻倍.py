# 克隆自聚宽文章：https://www.joinquant.com/post/30600
# 标题：小市值策略之再优化，年化接近翻倍
# 作者：仓建右三

# 克隆自聚宽文章：https://www.joinquant.com/post/25496
# 标题：收益狂飙，年化收益100%，11年1700倍，绝无未来函数
# 作者：jqz1226

# 导入函数库
from jqdata import *
from jqlib.technical_analysis import *


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
	
	# 股票池
	g.security_universe_index = "399101.XSHE"  # 中小板
	g.buy_stock_count = 3
	g.ma_period = 5  #买入时的均线
	g.sell_ma_period = 1   #卖出时的均线
	
	### 股票相关设定 ###
	# 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
	set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5),
				   type='stock')
	
	## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
	# 定时运行
	# run_daily(my_trade, time='14:40', reference_security='000300.XSHG')
	run_daily(my_trade, time='14:30', reference_security='000300.XSHG')
	# 收盘后运行
	run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')


## 开盘时运行函数
def my_trade(context):
	# 选取中小板中市值最小的若干只
	check_out_lists = get_index_stocks(g.security_universe_index)
	q = query(valuation.code).filter(
		valuation.code.in_(check_out_lists)
	).order_by(
		valuation.circulating_market_cap.asc()
	).limit(
		g.buy_stock_count * 3
	)
	check_out_lists = list(get_fundamentals(q).code)
	# 过滤: 三停（停牌、涨停、跌停）及st,*st,退市
	check_out_lists = filter_st_stock(check_out_lists)
	check_out_lists = filter_limitup_stock(context, check_out_lists)
	check_out_lists = filter_limitdown_stock(context, check_out_lists)
	check_out_lists = filter_paused_stock(check_out_lists)
	# 过滤符合MA条件的
	#check_out_lists = filter_ma_stock(context,check_out_lists)
	# 取需要的只数
	check_out_lists = check_out_lists[:g.buy_stock_count]
	# 买卖
	adjust_position(context, check_out_lists)


## 收盘后运行函数
def after_market_close(context):
	log.info(str('函数运行时间(after_market_close):' + str(context.current_dt.time())))
	# 得到当天所有成交记录
	trades = get_trades()
	for _trade in trades.values():
		log.info('成交记录：' + str(_trade))
	log.info('一天结束')
	log.info('##############################################################')


# 自定义下单
# 根据Joinquant文档，当前报单函数都是阻塞执行，报单函数（如order_target_value）返回即表示报单完成
# 报单成功返回报单（不代表一定会成交），否则返回None
def order_target_value_(security, value):
	if value == 0:
		log.debug("Selling out %s" % (security))
	else:
		log.debug("Order %s to value %f" % (security, value))
	
	# 如果股票停牌，创建报单会失败，order_target_value 返回None
	# 如果股票涨跌停，创建报单会成功，order_target_value 返回Order，但是报单会取消
	# 部成部撤的报单，聚宽状态是已撤，此时成交量>0，可通过成交量判断是否有成交
	return order_target_value(security, value)


# 开仓，买入指定价值的证券
# 报单成功并成交（包括全部成交或部分成交，此时成交量大于0），返回True
# 报单失败或者报单成功但被取消（此时成交量等于0），返回False
def open_position(context, security, value):
    
    now = context.current_dt
    now_date = now.strftime("%Y-%m-%d")[-10:]
    MA1 = MA(security, check_date=now_date, timeperiod=g.ma_period)
    now_price = get_bars(security, 1, unit='1m',fields=['open','close'],include_now=False)['close']
    # 当前价站上相应平均线后，才进行买入
    print(MA1[security])
    print(now_price)
    if now_price < MA1[security]: 
        return False
    order = order_target_value_(security, value)
    if order != None and order.filled > 0:
        return True
    return False


# 平仓，卖出指定持仓
# 平仓成功并全部成交，返回True
# 报单失败或者报单成功但被取消（此时成交量等于0），或者报单非全部成交，返回False
def close_position(context,position):
    security = position.security
    '''
    now = context.current_dt
    now_date = now.strftime("%Y-%m-%d")[-10:]
    ma_sell = MA(security, check_date=now_date, timeperiod=g.sell_ma_period)
    now_price = get_bars(security, 1, unit='1m',fields=['open','close'],include_now=False)['close']
    #print(MA1[security])
    #print(now_price)
    # 在相应均线上，先不卖出
    if now_price > ma_sell[security]: 
        return False
    '''
    order = order_target_value_(security, 0)  # 可能会因停牌失败
    if order != None:
        if order.status == OrderStatus.held and order.filled == order.amount:
            return True
    return False


# 交易
def adjust_position(context, buy_stocks):
	for stock in context.portfolio.positions:
		if stock not in buy_stocks:
			log.info("stock [%s] in position is not buyable" % (stock))
			position = context.portfolio.positions[stock]
			close_position(context, position)
		else:
			log.info("stock [%s] is already in position" % (stock))
	
	# 根据股票数量分仓
	# 此处只根据可用金额平均分配购买，不能保证每个仓位平均分配
	position_count = len(context.portfolio.positions)
	if g.buy_stock_count > position_count:
		value = context.portfolio.cash / (g.buy_stock_count - position_count)
		
		for stock in buy_stocks:
			if context.portfolio.positions[stock].total_amount == 0:
				if open_position(context, stock, value):
					if len(context.portfolio.positions) == g.buy_stock_count:
						break


# 过滤符合MA条件的股票
def filter_ma_stock(context,stock_list):
    ma_stock_list = []
    for stock in stock_list:
        now = context.current_dt
        
        now_date = now.strftime("%Y-%m-%d")[-10:]
        MA1 = MA(stock, check_date=now_date, timeperiod=g.ma_period)
        now_price = get_bars(stock, 1, unit='1m',fields=['open','close'],include_now=False)['close']
        # 当前价站上相应平均线后，才进行买入
        print(MA1[stock])
        print(now_price)
        if now_price > MA1[stock]: 
            ma_stock_list.append(stock)

    return ma_stock_list

# 过滤停牌股票
def filter_paused_stock(stock_list):
	current_data = get_current_data()
	return [stock for stock in stock_list if not current_data[stock].paused]


# 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
	current_data = get_current_data()
	return [stock for stock in stock_list
			if not current_data[stock].is_st
			and 'ST' not in current_data[stock].name
			and '*' not in current_data[stock].name
			and '退' not in current_data[stock].name]


# 过滤涨停的股票
def filter_limitup_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	
	# 已存在于持仓的股票即使涨停也不过滤，避免此股票再次可买，但因被过滤而导致选择别的股票
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] < current_data[stock].high_limit]


# return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
#    or last_prices[stock][-1] < current_data[stock].high_limit * 0.995]

# 过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] > current_data[stock].low_limit]
