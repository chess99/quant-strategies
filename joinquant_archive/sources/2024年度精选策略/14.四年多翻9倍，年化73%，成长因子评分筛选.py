# 克隆自聚宽文章：https://www.joinquant.com/post/42677
# 标题：四年多翻9倍，年化73%，成长因子评分筛选
# 作者：wolfman

# 三个成长因子评分后，筛选，每周调仓。年化达70%
# 导入函数库
from jqdata import *
from jqfactor import *
import pandas as pd

#初始化函数 
def initialize(context):
    #设定股票池
    set_benchmark('000905.XSHG')
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
    g.stock_num = 5 #持仓数
    
    g.no_trading_today_signal = False
    g.hold_list = [] #当前持仓的全部股票  
    
    # 设置交易时间，每天运行
    run_weekly(my_trade, weekday=1, time='9:30', reference_security='000300.XSHG')
    run_daily(close_account, '14:30')
    run_daily(print_position_info, time='15:10', reference_security='000300.XSHG')



#1-1 选股模块
#先根据资产负债排除一些股票，再选出roe改善最多的列表，最后在这个列表中根据pb轮动
def get_stock_list(context):
    yesterday = str(context.previous_date)
    initial_list = get_all_securities().index.tolist()
    initial_list = filter_new_stock(context,initial_list)
    initial_list = filter_kcb_stock(context, initial_list)
    initial_list = filter_st_stock(initial_list)
    
    factor_values = get_factor_values(initial_list, ['operating_revenue_growth_rate', #营业收入增长率
    'total_profit_growth_rate', #利润总额增长率
    'earnings_growth', #5年盈利增长率
    ], end_date=yesterday, count=1)
    
    df = pd.DataFrame(index=initial_list, columns=factor_values.keys())
    df['operating_revenue_growth_rate'] = list(factor_values['operating_revenue_growth_rate'].T.iloc[:,0])
    df['total_profit_growth_rate'] = list(factor_values['total_profit_growth_rate'].T.iloc[:,0])
    df['earnings_growth'] = list(factor_values['earnings_growth'].T.iloc[:,0])
    df['total_score'] = 0.2*df['operating_revenue_growth_rate'] + 0.4*df['total_profit_growth_rate'] +  0.4*df['earnings_growth'] 
    df = df.sort_values(by=['total_score'], ascending=False)
    complex_growth_list = list(df.index)[:int(0.1*len(list(df.index)))]
    
    q = query(valuation.code,valuation.circulating_market_cap,indicator.eps).filter(valuation.code.in_(complex_growth_list)).order_by(valuation.circulating_market_cap.asc())
    df = get_fundamentals(q)
    df = df[df['eps']>0]
    final_list = list(df.code)
    
    return final_list

#1-2 开盘前打印自选股
def print_stock_list_before_open(context):
    stock_list = get_stock_list(context)
    stock_list = filter_paused_stock(stock_list)
    stock_list = stock_list[:g.stock_num]
    print('今日自选股:{}'.format(stock_list))



#2-1 开盘时运行函数
def my_trade(context):
    #判断今天是否为账户资金再平衡的日期
    g.no_trading_today_signal = today_is_between(context, '04-05', '04-30')
    g.hold_list= list(context.portfolio.positions.keys())
    if g.no_trading_today_signal:
        return
    
    check_out_list = get_stock_list(context)
    check_out_list = filter_limitup_stock(context, check_out_list)
    check_out_list = filter_limitdown_stock(context, check_out_list)
    check_out_list = filter_paused_stock(check_out_list)
    check_out_list = check_out_list[:g.stock_num]
    adjust_position(context, check_out_list)

    

#3-1 交易函数
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
	
def close_account(context):
    if g.no_trading_today_signal == True:
        if len(g.hold_list) != 0:
            for stock in g.hold_list:
                order_target(stock, 0)
                log.info("卖出[%s]" % (stock))

def adjust_position(context, buy_stocks):
	for stock in context.portfolio.positions:
		if stock not in buy_stocks:
			log.info("[%s]不在应买入列表中" % (stock))
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



#4-1 过滤函数
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

def filter_kcb_stock(context, stock_list):
    return [stock for stock in stock_list  if stock[0:3] != '688']

def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=250)]
#4-1 判断今天是否为账户资金再平衡的日期
def today_is_between(context, start_date, end_date):
    today = context.current_dt.strftime('%m-%d')
    return start_date <= today <= end_date


#5-1 打印每日持仓信息
def print_position_info(context):
    #打印当天成交记录
    trades = get_trades()
    for _trade in trades.values():
        print('成交记录：'+str(_trade))
    #打印账户信息
    for position in list(context.portfolio.positions.values()):
        securities=position.security
        cost=position.avg_cost
        price=position.price
        ret=100*(price/cost-1)
        value=position.value
        amount=position.total_amount    
        print('代码:{}'.format(securities))
        print('成本价:{}'.format(format(cost,'.2f')))
        print('现价:{}'.format(price))
        print('收益率:{}%'.format(format(ret,'.2f')))
        print('持仓(股):{}'.format(amount))
        print('市值:{}'.format(format(value,'.2f')))
        print('———————————————————————————————————')
    print('———————————————————————————————————————分割线————————————————————————————————————————')
