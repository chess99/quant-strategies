# 克隆自聚宽文章：https://www.joinquant.com/post/34745
# 标题：价值成长轮动策略
# 作者：wywy1995

#导入函数库
from jqdata import *
from jqfactor import get_factor_values
import numpy as np
import pandas as pd

#初始化函数 
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 设置交易成本万分之三
    set_order_cost(OrderCost(open_tax=0, close_tax=0, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),
                   type='fund')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    #指数池
    g.index_pool = [
        '000300.XSHG', #沪深300
        '000905.XSHG', #中证500
    ]
    #动量轮动参数
    g.momentum_day = 30 #最新动量参考最近momentum_day的
    #rsrs择时参数
    g.ref_stock = '000300.XSHG' #用ref_stock做择时计算的基础数据
    g.N = 18 # 计算最新斜率slope，拟合度r2参考最近N天
    g.M = 600 # 计算最新标准分zscore，rsrs_score参考最近M天
    g.score_threshold = 0.7 # rsrs标准分指标阈值
    g.slope_series = initial_slope_series()[:-1] # 除去回测第一天的slope，避免运行时重复加入
    #ma择时参数
    g.mean_day = 20 #计算mean_day的ma
    g.mean_diff_day = 3 #计算mean_diff_day前的g.mean_diff_day的ma
    # 设置交易时间，每天运行
    run_daily(my_trade, time='9:30', reference_security='000300.XSHG')
    run_daily(print_trade_info, time='15:00', reference_security='000300.XSHG')


    
#1-1 计算线性回归统计值
#对输入的自变量每日最低价x(series)和因变量每日最高价y(series)建立OLS回归模型,返回元组(截距,斜率,拟合度)
def get_ols(x, y):
    slope, intercept = np.polyfit(x, y, 1)
    r2 = 1 - (sum((y - (slope * x + intercept))**2) / ((len(y) - 1) * np.var(y, ddof=1)))
    return (intercept, slope, r2)

#1-2 设定初始斜率序列
#通过前M日最高最低价的线性回归计算初始的斜率,返回斜率的列表
def initial_slope_series():
    data = attribute_history(g.ref_stock, g.N + g.M, '1d', ['high', 'low'])
    return [get_ols(data.low[i:i+g.N], data.high[i:i+g.N])[1] for i in range(g.M)]

#1-3 计算标准分
#通过斜率列表计算并返回截至回测结束日的最新标准分
def get_zscore(slope_series):
    mean = np.mean(slope_series)
    std = np.std(slope_series)
    return (slope_series[-1] - mean) / std

#1-4 计算综合信号
#获得rsrs与MA信号，信号至少一个为True时返回调仓信号，同为False时返回卖出信号
def get_timing_signal(stock):
    #计算MA信号
    close_data = attribute_history(g.ref_stock, g.mean_day + g.mean_diff_day, '1d', ['close'])
    today_MA = close_data.close[g.mean_diff_day:].mean() 
    before_MA = close_data.close[:-g.mean_diff_day].mean()
    print('MA差值={}'.format(format(today_MA-before_MA,'.2f')))
    #计算rsrs信号
    high_low_data = attribute_history(g.ref_stock, g.N, '1d', ['high', 'low'])
    intercept, slope, r2 = get_ols(high_low_data.low, high_low_data.high)
    g.slope_series.append(slope)
    rsrs_score = get_zscore(g.slope_series[-g.M:]) * r2
    print('rsrs_score={}'.format(format(rsrs_score,'.2f')))
    #综合判断所有信号
    if rsrs_score > g.score_threshold or today_MA > before_MA:
        return "BUY"
    elif rsrs_score < -g.score_threshold and today_MA < before_MA:
        return "SELL"



#2-1 根据动量判断市场风格
#基于指数年化收益和判定系数打分,并按照分数从大到小排名
def get_index_signal(index_pool):
    score_list = []
    for index in index_pool:
        data = attribute_history(index, g.momentum_day, '1d', ['close'])
        y = data['log'] = np.log(data.close)
        x = data['num'] = np.arange(data.log.size)
        slope, intercept = np.polyfit(x, y, 1)
        annualized_returns = math.pow(math.exp(slope), 250) - 1
        r_squared = 1 - (sum((y - (slope * x + intercept))**2) / ((len(y) - 1) * np.var(y, ddof=1)))
        score = annualized_returns * r_squared
        score_list.append(score)
    index_dict=dict(zip(index_pool, score_list))
    print(index_dict)
    sort_list=sorted(index_dict.items(), key=lambda item:item[1], reverse=True) #True为降序
    code_list=[]
    for i in range((len(index_pool))):
        code_list.append(sort_list[i][0])
    best_index = code_list[0]
    return best_index

#2-2 聚宽因子选股
#输入股票列表，要查询的聚宽因子，排序方式，选股比例，返回选股后的列表
def get_factor_filter_list(context, stock_list, jqfactor, sort, p1, p2):
    yesterday = context.previous_date
    score_list = get_factor_values(stock_list, jqfactor, end_date=yesterday, count=1)[jqfactor].iloc[0].tolist()
    df = pd.DataFrame(columns=['code','score'])
    df['code'] = stock_list
    df['score'] = score_list
    df = df.dropna()
    df = df[df['score']>0]
    df.sort_values(by='score', ascending=sort, inplace=True)
    filter_list = list(df.code)[int(p1*len(stock_list)):int(p2*len(stock_list))]
    return filter_list

#2-3 价值选股
#eps-ms-cap因子全市场(剔除st，新股，科创板)选股，返回股票列表
def get_value_stock_list(context):
    initial_list = get_all_securities().index.tolist()
    initial_list = filter_new_stock(context,initial_list)
    initial_list = filter_kcb_stock(context, initial_list)
    initial_list = filter_st_stock(initial_list)
    eps_list = get_factor_filter_list(context, initial_list, 'eps_ttm', False, 0, 0.1)
    ms_list = get_factor_filter_list(context, eps_list, 'margin_stability', False, 0, 0.1)
    q = query(valuation.code).filter(valuation.code.in_(ms_list)).order_by(valuation.circulating_market_cap.desc())
    stock_list = list(get_fundamentals(q).code)
    return stock_list

#2-4 成长选股
#peg-ebit-cap因子全市场(剔除st，新股，科创板)选股，返回股票列表
def get_growth_stock_list(context):
    initial_list = get_all_securities().index.tolist()
    initial_list = filter_new_stock(context,initial_list)
    initial_list = filter_kcb_stock(context, initial_list)
    initial_list = filter_st_stock(initial_list)
    peg_list = get_factor_filter_list(context, initial_list, 'PEG', True, 0, 0.1)
    ebit_list = get_factor_filter_list(context, peg_list, 'EBIT', True, 0, 0.2)
    q = query(valuation.code,valuation.circulating_market_cap).filter(valuation.code.in_(ebit_list)).order_by(valuation.circulating_market_cap.asc())
    df = get_fundamentals(q)
    stock_list = list(df.code)
    return stock_list



#2-5 轮动交易
#先判断市场风格，再选股调仓
def my_trade(context):
    #获取选股列表并过滤掉:st,st*,退市,涨停,跌停,停牌
    index_signal = get_index_signal(g.index_pool)
    if index_signal == '000300.XSHG':
        stock_list = get_value_stock_list(context)
        stock_num = 5
    elif index_signal == '000905.XSHG':
        stock_list = get_growth_stock_list(context)
        stock_num = 5
    stock_list = filter_limitup_stock(context, stock_list)
    stock_list = filter_limitdown_stock(context, stock_list)
    stock_list = filter_paused_stock(stock_list)
    stock_list = stock_list[:stock_num]
    print('今日自选股:{}'.format(stock_list))
    timing_signal = get_timing_signal(g.ref_stock)
    print('今日择时信号:{}'.format(timing_signal))
    if timing_signal == 'SELL':
        for stock in context.portfolio.positions:
            position = context.portfolio.positions[stock]
            close_position(position)
    elif timing_signal == 'BUY':
        adjust_position(context, stock_list, stock_num)
    else:
        pass



#3-1 过滤停牌股票
#输入选股列表，返回剔除停牌股票后的列表
def filter_paused_stock(stock_list):
	current_data = get_current_data()
	return [stock for stock in stock_list if not current_data[stock].paused]

#3-2 过滤ST及其他具有退市标签的股票
#输入选股列表，返回剔除ST及其他具有退市标签股票后的列表
def filter_st_stock(stock_list):
	current_data = get_current_data()
	return [stock for stock in stock_list
			if not current_data[stock].is_st
			and 'ST' not in current_data[stock].name
			and '*' not in current_data[stock].name
			and '退' not in current_data[stock].name]

#3-3 过滤涨停的股票
#输入选股列表，返回剔除未持有且已涨停股票后的列表
def filter_limitup_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	# 已存在于持仓的股票即使涨停也不过滤，避免此股票再次可买，但因被过滤而导致选择别的股票
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] < current_data[stock].high_limit]

#3-4 过滤跌停的股票
#输入股票列表，返回剔除已跌停股票后的列表
def filter_limitdown_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] > current_data[stock].low_limit]

#3-5 过滤科创板
#输入股票列表，返回剔除科创板后的列表
def filter_kcb_stock(context, stock_list):
    return [stock for stock in stock_list  if stock[0:3] != '688']

#3-6 过滤次新股
#输入股票列表，返回剔除上市日期不足250日股票后的列表
def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=250)]



#4-1 自定义下单
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

#4-2 开仓
#买入指定价值的证券,报单成功并成交(包括全部成交或部分成交,此时成交量大于0)返回True,报单失败或者报单成功但被取消(此时成交量等于0),返回False
def open_position(security, value):
	order = order_target_value_(security, value)
	if order != None and order.filled > 0:
		return True
	return False

#4-3 平仓
#卖出指定持仓,报单成功并全部成交返回True，报单失败或者报单成功但被取消(此时成交量等于0),或者报单非全部成交,返回False
def close_position(position):
	security = position.security
	order = order_target_value_(security, 0)  # 可能会因停牌失败
	if order != None:
		if order.status == OrderStatus.held and order.filled == order.amount:
			return True
	return False

#4-4 调仓
#当择时信号为买入时开始调仓，输入过滤模块处理后的股票列表，执行交易模块中的开平仓操作
def adjust_position(context, buy_stocks, stock_num):
	for stock in context.portfolio.positions:
		if stock not in buy_stocks:
			log.info("[%s]已不在应买入列表中" % (stock))
			position = context.portfolio.positions[stock]
			close_position(position)
		else:
			log.info("[%s]已经持有无需重复买入" % (stock))
	# 根据股票数量分仓
	# 此处只根据可用金额平均分配购买，不能保证每个仓位平均分配
	position_count = len(context.portfolio.positions)
	if stock_num > position_count:
		value = context.portfolio.cash / (stock_num - position_count)
		for stock in buy_stocks:
			if context.portfolio.positions[stock].total_amount == 0:
				if open_position(stock, value):
					if len(context.portfolio.positions) == stock_num:
						break




#5-1 复盘模块-打印
#打印每日持仓信息
def print_trade_info(context):
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
        print('————————————————————————————————————')
    print('———————————————————————————————————————分割线————————————————————————————————————————')
