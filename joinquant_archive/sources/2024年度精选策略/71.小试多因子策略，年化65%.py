# 克隆自聚宽文章：https://www.joinquant.com/post/42841
# 标题：小试多因子策略，年化65%
# 作者：乘风万里

# 多因子模板分位法之2
# 和第一个分位法相比，稍微做了些修改：
# 1、自定义因子这里添加了排序类型，True表示按照因子升序排列；False 表示按照因子降序排列
# 2、交易模块里面对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
#

#导入函数库
from jqdata import *
from jqlib.technical_analysis import *
from jqfactor import get_factor_values
import numpy as np
import pandas as pd
import statsmodels.api as sm
import datetime as dt

#初始化函数 
def initialize(context):

    # 设定基准
    set_benchmark('000905.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 设置交易成本万分之三，不同滑点影响可在归因分析中查看
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),type='fund')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    
    #初始化全局变量
    g.stock_num =10  #最大持仓数
    g.limit_up_list = [] #记录持仓中涨停的股票
    g.hold_list = [] #当前持仓的全部股票
    g.history_hold_list = [] #过去一段时间内持仓过的股票
    g.not_buy_again_list = [] #最近买过且涨停过的股票一段时间内不再买入
    g.limit_days = 20 #不再买入的时间段天数
    g.target_list = [] #开盘前预操作股票池
    
    #自定义因子及分位值                       
    #分位数说明：  0.2表示选取前20%分位的个股
    #g.sort说明：True表示升序，以小为美；False表示降序，以大为美;  若因子改变，排序方法可能需要作相的调整。 
    g.factor1,g.P1,g.sort1='net_profit_growth_rate',0.1,False                               
    g.factor2,g.P2,g.sort2='EBIT',0.4, True                  
    g.factor3,g.P3,g.sort3='roe_ttm',1,False                 #当分位数设为1，则该因子不起作用               
    
    #因子列表，分为三大类
    #1、只与财务报表相关
    #'gross_income_ratio'   销售毛利率
    #'net_profit_ratio' 销售净利率
    #'roe_ttm' 权益回报率
    #'net_interest_expense' 净利息费用
    #'account_receivable_turnover_days' 应收账款周转天数
    #'OperateNetIncome'  经营活动净收益 
    #'EBIT'  息税前利润                   也就是PEG+EBIT搭配可以，和BP搭配不行。起到副作用。
    #'margin_stability'   盈利能力稳定性
    #'operating_revenue_growth_rate', #成长类因子 营业收入增长率
    #'total_profit_growth_rate', #成长类因子 利润总额增长率
    #'net_profit_growth_rate', #成长类因子 净利润增长率
    #'earnings_growth', #风格因子 5年盈利增长率
    #'eps_ttm' #每股指标因子 每股收益TTM
    
    #2、与股价和财报都有关系
    #'book_to_price_ratio'市净率因子              BP
    #'cash_flow_to_price_ratio' 现金流市值比 
    #'earnings_to_price_ratio' 利润市值比         EP ,PE的倒数
    #'PEG'
    
    #3、只与股价波动相关
    #'turnover_volatility'          换手率相对波动率   
    #'liquidity'                    流动性因子
    #'daily_standard_deviation'     日收益率标准差      
    
    
    # 设置交易运行时间
    run_daily(prepare_stock_list, time='9:05', reference_security='000300.XSHG') #准备预操作股票池
    run_weekly(weekly_adjustment, weekday=1, time='9:30', reference_security='000300.XSHG') #默认周一开盘调仓，收益最高
    run_daily(check_limit_up, time='14:00', reference_security='000300.XSHG') #检查持仓中的涨停股是否需要卖出
    run_daily(print_position_info, time='15:10', reference_security='000300.XSHG') #打印复盘信息


#2-1 选股模块--因子分位器
def get_factor_filter_list(context,stock_list,jqfactor,sort,p):
    yesterday = context.previous_date
    score_list = get_factor_values(stock_list, jqfactor, end_date=yesterday, count=1)[jqfactor].iloc[0].tolist()
    df = pd.DataFrame(columns=['code','score'])
    df['code'] = stock_list
    df['score'] = score_list
    df = df.dropna()
    #df = df[df['score']>0]
    df.sort_values(by='score', ascending=sort, inplace=True)
    filter_list = list(df.code)[0:int(p*len(stock_list))]
    return filter_list


#2-2 选股模块
def get_stock_list(context):
    initial_list = get_all_securities().index.tolist()
    initial_list = filter_new_stock(context,initial_list)
    initial_list = filter_kcb_stock(context, initial_list)
    initial_list = filter_st_stock(initial_list)
    
    #返回因子列表
    factor1_list = get_factor_filter_list(context, initial_list, g.factor1, g.sort1, g.P1)   
    #print('list1 length:',len(factor1_list))
    factor2_list = get_factor_filter_list(context, factor1_list, g.factor2, g.sort2, g.P2)
    #print('list2 length:',len(factor2_list))
    factor3_list = get_factor_filter_list(context, factor2_list, g.factor3, g.sort3, g.P3)
    #print('list3 length:',len(factor3_list))
    q = query(valuation.code,valuation.circulating_market_cap,indicator.eps).filter(
            valuation.code.in_(factor3_list)).order_by(valuation.circulating_market_cap.asc())
    df = get_fundamentals(q)
    df = df[df['eps']>0]    #剔除亏损股
    final_list = list(df.code)
    return final_list


#1-3 准备股票池
def prepare_stock_list(context):
    #1...2
    #获取已持有列表
    g.hold_list= []
    for position in list(context.portfolio.positions.values()):
        stock = position.security
        g.hold_list.append(stock)
    #获取最近一段时间持有过的股票列表
    g.history_hold_list.append(g.hold_list)
    if len(g.history_hold_list) >= g.limit_days:
        g.history_hold_list = g.history_hold_list[-g.limit_days:]
    temp_set = set()
    for hold_list in g.history_hold_list:
        for stock in hold_list:
            temp_set.add(stock)
    g.not_buy_again_list = list(temp_set)
    #获取昨日涨停列表
    if g.hold_list != []:
        df = get_price(g.hold_list, end_date=context.previous_date, frequency='daily', fields=['close','high_limit'], count=1, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        g.high_limit_list = list(df.code)
    else:
        g.high_limit_list = []


#1-4 整体调整持仓
def weekly_adjustment(context):
    #1 #获取应买入列表 
    g.target_list = get_stock_list(context)[:g.stock_num+5] #2
    g.target_list = filter_paused_stock(g.target_list)
    g.target_list = filter_limitup_stock(context, g.target_list)
    g.target_list = filter_limitdown_stock(context, g.target_list)
    #过滤最近买过且涨停过的股票
    recent_limit_up_list = get_recent_limit_up_stock(context, g.target_list, g.limit_days)
    black_list = list(set(g.not_buy_again_list).intersection(set(recent_limit_up_list)))
    g.target_list = [stock for stock in g.target_list if stock not in black_list]
    #截取不超过最大持仓数的股票量
    g.target_list = g.target_list[:min(g.stock_num, len(g.target_list))]
    #调仓卖出
    for stock in g.hold_list:
        if (stock not in g.target_list) and (stock not in g.high_limit_list):
            log.info("卖出[%s]" % (stock))
            position = context.portfolio.positions[stock]
            close_position(position)
        else:
            log.info("已持有[%s]" % (stock))
    #调仓买入
    position_count = len(context.portfolio.positions)
    target_num = len(g.target_list)
    if target_num > position_count:
        value = context.portfolio.cash / (target_num - position_count)
        for stock in g.target_list:
            if context.portfolio.positions[stock].total_amount == 0:
                if open_position(stock, value):
                    if len(context.portfolio.positions) == target_num:
                        break


#1-5 调整昨日涨停股票
def check_limit_up(context):
    now_time = context.current_dt
    if g.high_limit_list != []:
        #对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
        for stock in g.high_limit_list:
            current_data = get_price(stock, end_date=now_time, frequency='1m', fields=['close','high_limit'], skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True)
            if current_data.iloc[0,0] < current_data.iloc[0,1]:
                log.info("[%s]涨停打开，卖出" % (stock))
                position = context.portfolio.positions[stock]
                close_position(position)
            else:
                log.info("[%s]涨停，继续持有" % (stock))



#2-1 过滤停牌股票
def filter_paused_stock(stock_list):
	current_data = get_current_data()
	return [stock for stock in stock_list if not current_data[stock].paused]

#2-2 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
	current_data = get_current_data()
	return [stock for stock in stock_list
			if not current_data[stock].is_st
			and 'ST' not in current_data[stock].name
			and '*' not in current_data[stock].name
			and '退' not in current_data[stock].name]

#2-3 获取最近N个交易日内有涨停的股票
def get_recent_limit_up_stock(context, stock_list, recent_days):
    stat_date = context.previous_date
    new_list = []
    for stock in stock_list:
        df = get_price(stock, end_date=stat_date, frequency='daily', fields=['close','high_limit'], count=recent_days, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        if len(df) > 0:
            new_list.append(stock)
    return new_list

#2-4 过滤涨停的股票
def filter_limitup_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] < current_data[stock].high_limit]

#2-5 过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] > current_data[stock].low_limit]

#2-6 过滤科创板
def filter_kcb_stock(context, stock_list):
    return [stock for stock in stock_list  if stock[0:3] != '688']

#2-7 过滤次新股
def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=250)]

#3-1 交易模块-自定义下单
def order_target_value_(security, value):
	if value == 0:
		log.debug("Selling out %s" % (security))
	else:
		log.debug("Order %s to value %f" % (security, value))
	return order_target_value(security, value)

#3-2 交易模块-开仓
def open_position(security, value):
	order = order_target_value_(security, value)
	if order != None and order.filled > 0:
		return True
	return False

#3-3 交易模块-平仓
def close_position(position):
	security = position.security
	order = order_target_value_(security, 0)  # 可能会因停牌失败
	if order != None:
		if order.status == OrderStatus.held and order.filled == order.amount:
			return True
	return False



#4-1 打印每日持仓信息
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
