# 克隆自聚宽文章：https://www.joinquant.com/post/38476
# 标题：sales_growth今年最优版
# 作者：jycs

# 克隆自聚宽文章：https://www.joinquant.com/post/35690
# 标题：截止到21年12月依然有效的小市值适配因子
# 作者：wywy1995

#导入函数库
from jqdata import *
from jqfactor import get_factor_values
from datetime import datetime, date, timedelta
import numpy as np
import pandas as pd

#初始化函数 
def initialize(context):
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
    g.un_hold_days=0
    # 设置交易时间，每天运行
    run_weekly(print_stock_list_before_open, weekday=1, time='9:15', reference_security='000300.XSHG')
    run_weekly(my_trade, weekday=1, time='9:31', reference_security='000300.XSHG')
    run_weekly(print_position_info,weekday=1, time='15:10')
    
    run_daily(days_close,time='15:30')
    run_daily(trade_close,time='09:30')
    
def days_close(context):
    if context.portfolio.positions=={}:
        g.un_hold_days=g.un_hold_days+1
    
def trade_close(context):
    idx=attribute_history('000001.XSHG',5,'1d',['close'])
    x=5
    for i in range(1,3):
        idx3=idx['close'][x-3:x].mean()
        idx2=idx['close'][x-2:x].mean()
        exec('g.idx3_%s=idx3'%i)
        exec('g.idx2_%s=idx2'%i)
        x=x-1
    if g.idx3_1<g.idx3_2:
        for st in context.portfolio.positions:
            order_target_value(st,0)
            log.debug("Sellingout__________________3日线走低  %s" % (st))
    if g.idx2_1>g.idx2_2 and context.portfolio.positions=={}:
        my_trade(context)
        
'------------------------------------------------------------------------------------------------------------------'

#1-1 选股模块
def get_factor_filter_list(context,stock_list,jqfactor,sort,p1,p2):
    yesterday = context.previous_date
    score_list = get_factor_values(stock_list, jqfactor, end_date=yesterday, count=1)[jqfactor].iloc[0].tolist()#获取因子数值列表
    df = pd.DataFrame(columns=['code','score'])#建立空df
    df['code'] = stock_list#列赋值
    df['score'] = score_list#列赋值
    df = df.dropna()#去空值
    df.sort_values(by='score', ascending=sort, inplace=True)#排序
    filter_list = list(df.code)[int(p1*len(stock_list)):int(p2*len(stock_list))]#获取前十分之一代码
    return filter_list

#1-2 选股模块
def get_stock_list(context):
    initial_list = get_all_securities().index.tolist()
    initial_list = filter_new_stock(context,initial_list)
    initial_list = filter_kcb_stock(context, initial_list)
    initial_list = filter_st_stock(initial_list)
    x_list = get_factor_filter_list(context, initial_list, 'sales_growth', False, 0, 0.1)
    q = query(valuation.code,valuation.turnover_ratio,valuation.circulating_market_cap,indicator.eps).filter(valuation.code.in_(x_list)).order_by(valuation.circulating_market_cap.asc())
    df = get_fundamentals(q)
    df = df[df['eps']>0]
    final_list1 = list(df.code[0:10])
    print(final_list1)
    final_list = []
    stock_dict={}
    for st in final_list1:
        num=0
        v=attribute_history(st,10,'1d',['close','volume'])
        v20=v['volume'][0:10].mean()
        for i in range(0,10):
            if v['volume'][i]/v20>1.3:
                num=num+1
        stock_dict[st]=num 
    stock_dict=sorted(stock_dict.items(),key=lambda x:x[1],reverse=True)
    for i in range(0,5):
        final_list.append(stock_dict[i][0])
    return final_list

#1-3 开盘前打印自选股
def print_stock_list_before_open(context):
    stock_list = get_stock_list(context)
    stock_list = filter_paused_stock(stock_list)
    stock_list = stock_list[:g.stock_num]
    print('今日自选股:{}'.format(stock_list))

#2-1 过滤模块-过滤停牌股票
#输入选股列表，返回剔除停牌股票后的列表
def filter_paused_stock(stock_list):
	current_data = get_current_data()
	return [stock for stock in stock_list if not current_data[stock].paused]

#2-2 过滤模块-过滤ST及其他具有退市标签的股票
#输入选股列表，返回剔除ST及其他具有退市标签股票后的列表
def filter_st_stock(stock_list):
	current_data = get_current_data()
	return [stock for stock in stock_list
			if not current_data[stock].is_st
			and 'ST' not in current_data[stock].name
			and '*' not in current_data[stock].name
			and '退' not in current_data[stock].name]

#2-3 过滤模块-过滤涨停的股票
#输入选股列表，返回剔除未持有且已涨停股票后的列表
def filter_limitup_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	# 已存在于持仓的股票即使涨停也不过滤，避免此股票再次可买，但因被过滤而导致选择别的股票
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] < current_data[stock].high_limit]

#2-4 过滤模块-过滤跌停的股票
#输入股票列表，返回剔除已跌停股票后的列表
def filter_limitdown_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] > current_data[stock].low_limit]

#2-5 过滤模块-过滤科创板
#输入股票列表，返回剔除科创板后的列表
def filter_kcb_stock(context, stock_list):
    return [stock for stock in stock_list  if stock[0:3] != '688']

#2-6 过滤次新股
#输入股票列表，返回剔除上市日期不足250日股票后的列表
def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    #return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=250)]
    return [stock for stock in stock_list if not (yesterday - get_security_info(stock).start_date).days <250]

'----------------------------------------------------------------------------------------------------------------------'

#3-1 交易模块-自定义下单
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

#3-2 交易模块-开仓
#买入指定价值的证券,报单成功并成交(包括全部成交或部分成交,此时成交量大于0)返回True,报单失败或者报单成功但被取消(此时成交量等于0),返回False
def open_position(security, value):
	order = order_target_value_(security, value)
	if order != None and order.filled > 0:
		return True
	return False

#3-3 交易模块-平仓
#卖出指定持仓,报单成功并全部成交返回True，报单失败或者报单成功但被取消(此时成交量等于0),或者报单非全部成交,返回False
def close_position(position):
	security = position.security
	order = order_target_value_(security, 0)  # 可能会因停牌失败
	if order != None:
		if order.status == OrderStatus.held and order.filled == order.amount:
			return True
	return False

#3-4 交易模块-调仓
#当择时信号为买入时开始调仓，输入过滤模块处理后的股票列表，执行交易模块中的开平仓操作
def adjust_position(context, buy_stocks):
	for stock in context.portfolio.positions:
		if stock not in buy_stocks:
			log.info("[%s]不在应买入列表中" % (stock))
			position = context.portfolio.positions[stock]
			close_position(position)
		else:
			log.info("[%s]已经持有无需重复买入" % (stock))
	# 根据股票数量分仓
	# 此处只根据可用金额平均分配购买，不能保证每个仓位平均分配
	position_count = len(context.portfolio.positions)
	if g.stock_num > position_count:
		value = context.portfolio.cash / (g.stock_num - position_count)
		for stock in buy_stocks:
			if context.portfolio.positions[stock].total_amount == 0:
				if open_position(stock, value):
					if len(context.portfolio.positions) == g.stock_num:
						break

'---------------------------------------------------------------------------------------------------------------------'

#3-5 交易模块-择时交易
#结合择时模块综合信号进行交易
def my_trade(context):
    if g.idx2_1>g.idx2_2:
        
        #获取选股列表并过滤掉:st,st*,退市,涨停,跌停,停牌
        check_out_list = get_stock_list(context)
        check_out_list = filter_limitup_stock(context, check_out_list)
        check_out_list = filter_limitdown_stock(context, check_out_list)
        check_out_list = filter_paused_stock(check_out_list)
        check_out_list = check_out_list[:g.stock_num]
        adjust_position(context, check_out_list)
    
#4-1 复盘模块-打印
#打印每日持仓信息
def print_position_info(context):
    #打印账户信息
    for position in list(context.portfolio.positions.values()):
        securities=position.security
        cost=position.avg_cost
        price=position.price
        ret=100*(price/cost-1)
        value=position.value
        amount=position.total_amount 
        
        buy_time=context.portfolio.positions[position.security].init_time
        buy_date=datetime.date(buy_time)
        hold_days=(context.current_dt.date()-buy_date).days
        #hold_days=(context.current_dt.strptime('%Y-%m-%d')-buy_date).days
        
        print('代码:{}'.format(securities))
        print('成本价:{}'.format(format(cost,'.2f')))
        print('现价:{}'.format(price))
        print('收益率:{}%'.format(format(ret,'.2f')))
        print('持仓(股):{}'.format(amount))
        print('市值:{}'.format(format(value,'.2f')))
        print('持仓天数:{}'.format(hold_days))
        print('———————————————————————————————————')
    print('空仓天数:{}'.format(g.un_hold_days))
    print('———————————————————————————————————————分割线————————————————————————————————————————')
    
    
    
