# 克隆自聚宽文章：https://www.joinquant.com/post/34862
# 标题：ROE+PB模型的优化
# 作者：wywy1995

# 导入函数库
from jqdata import *
from jqfactor import get_factor_values

#初始化函数 
def initialize(context):
    #设定股票池
    g.stock_pool = '000300.XSHG'
    set_benchmark(g.stock_pool)
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 设置交易成本万分之三
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),type='fund')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    #选股参数
    g.stock_num = 10 #持仓数
    # 设置交易时间，每天运行
    run_weekly(my_trade, weekday=1, time='9:30', reference_security='000300.XSHG')



#2-2 选股模块
#选出pb大于零且小于四分之一分位，roe改善最多的股票列表
def get_stock_list(context):
    yesterday = str(context.previous_date)
    initial_list = get_all_securities().index.tolist()
    initial_list = filter_new_stock(context,initial_list)
    initial_list = filter_kcb_stock(context, initial_list)
    initial_list = filter_st_stock(initial_list)
    
    q = query(balance.code, balance.total_liability, balance.total_assets).filter(valuation.code.in_(initial_list))
    df = get_fundamentals(q)
    df = df.dropna()    
    df['ratio'] = df['total_liability'] / df['total_assets']
    df = df.sort_values(by='ratio')
    df = df[df['ratio']<df['ratio'].quantile(0.75)]
    low_liability_list = list(df.code)
    
    q = query(balance.code,
    balance.total_assets, #总资产
    balance.bill_receivable, #应收票据
    balance.account_receivable, #应收账款
    balance.other_receivable, #其他应收款
    balance.good_will, #商誉
    balance.intangible_assets, #无形资产
    balance.inventories, #存货
    balance.constru_in_process, #在建工程
    ).filter(balance.code.in_(low_liability_list))
    df = get_fundamentals(q)
    df = df.fillna(0)
    df['bad_assets'] = df.sum(1) - df['total_assets']
    df['ratio'] = df['bad_assets'] / df['total_assets']
    df = df.sort_values(by='ratio')
    proper_receivable_list = list(df.code)[int(0.2*len(list(df.code))):int(0.8*len(list(df.code)))]
    
    df = get_history_fundamentals(proper_receivable_list, fields=[indicator.code, indicator.roe], watch_date=yesterday, count=5, interval='1q')
    df = df.groupby('code').apply(lambda x:x.reset_index()).roe.unstack()
    df['past_average'] = 0.1*df.iloc[:,0] + 0.2*df.iloc[:,1] + 0.3*df.iloc[:,2] + 0.4*df.iloc[:,3]
    df['now_average'] = 0.1*df.iloc[:,1] + 0.2*df.iloc[:,2] + 0.3*df.iloc[:,3] + 0.4*df.iloc[:,4]
    df['delta_average'] = df['now_average'] - df['past_average']
    df.dropna(inplace=True)
    df.sort_values(by='delta_average',ascending=False, inplace=True)
    roe_list = list(df.index)[:int(0.1*len(list(df.index)))]
    
    q = query(valuation.code, valuation.pb_ratio).filter(balance.code.in_(roe_list)).order_by(valuation.pb_ratio.asc())
    df = get_fundamentals(q)
    df = df[df['pb_ratio']>0]
    pb_list = list(df.code)
    
    final_list = pb_list
    return final_list

#开盘时运行函数
def my_trade(context):
    #获取选股列表并过滤掉:st,st*,退市,涨停,跌停,停牌
    check_out_list = get_stock_list(context)
    check_out_list = filter_limitup_stock(context, check_out_list)
    check_out_list = filter_limitdown_stock(context, check_out_list)
    check_out_list = filter_paused_stock(check_out_list)
    check_out_list = check_out_list[:g.stock_num]
    print('今日自选股:{}'.format(check_out_list))
    adjust_position(context, check_out_list)
    
    

#交易及过滤函数
def after_market_close(context):
	log.info(str('函数运行时间(after_market_close):' + str(context.current_dt.time())))
	trades = get_trades()
	for _trade in trades.values():
		log.info('成交记录：' + str(_trade))
	log.info('一天结束')
	log.info('##############################################################')

def order_target_value_(security, value):
	if value == 0:
		log.debug("Selling out %s" % (security))
	else:
		log.debug("Order %s to value %f" % (security, value))
	return order_target_value(security, value)

def open_position(security, value):
	order = order_target_value_(security, value)
	if order != None and order.filled > 0:
		return True
	return False

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
			log.info("stock [%s] in position is not buyable" % (stock))
			position = context.portfolio.positions[stock]
			close_position(position)
		else:
			log.info("stock [%s] is already in position" % (stock))
	position_count = len(context.portfolio.positions)
	if g.stock_num > position_count:
		value = context.portfolio.cash / (g.stock_num - position_count)
		for stock in buy_stocks:
			if context.portfolio.positions[stock].total_amount == 0:
				if open_position(stock, value):
					if len(context.portfolio.positions) == g.stock_num:
						break


def filter_paused_stock(stock_list):
	current_data = get_current_data()
	return [stock for stock in stock_list if not current_data[stock].paused]

def filter_st_stock(stock_list):
	current_data = get_current_data()
	return [stock for stock in stock_list
			if not current_data[stock].is_st
			and 'ST' not in current_data[stock].name
			and '*' not in current_data[stock].name
			and '退' not in current_data[stock].name]

def filter_limitup_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] < current_data[stock].high_limit]

def filter_limitdown_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] > current_data[stock].low_limit]
	
#3-5 过滤模块-过滤科创板
#输入股票列表，返回剔除科创板后的列表
def filter_kcb_stock(context, stock_list):
    return [stock for stock in stock_list  if stock[0:3] != '688']

#3-6 过滤次新股
#输入股票列表，返回剔除上市日期不足250日股票后的列表
def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=250)]

