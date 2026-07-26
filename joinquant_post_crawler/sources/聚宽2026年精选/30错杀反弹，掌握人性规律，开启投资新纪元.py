# 克隆自聚宽文章：https://www.joinquant.com/post/47792
# 标题：错杀反弹，掌握人性规律，开启投资新纪元
# 作者：养家大哥

from jqdata import *
from jqfactor import *
from jqlib.technical_analysis import *
import math
import pandas as pd



def initialize(context):
    # 设定基准
    set_benchmark('000905.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 设置滑点为理想情况，不同滑点影响可以在归因分析中查看
    #set_slippage(FixedSlippage(0.03))
    set_slippage(PriceRelatedSlippage(0.001),type='stock')
    # 设置交易成本
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0001, close_commission=0.0001, close_today_commission=0, min_commission=5),type='fund')
    # 除非需要精简信息，否则不要过滤日志，方便debug
    log.set_level('order', 'error')
    #log.set_level('system', 'error')
    #初始化全局变量
    g.security_universe_index = "399101.XSHE"  # 中小板
    g.stock_num = 5
    g.small_stock_index = g.stock_num*10000
    g.limit_up_list = []
    g.target_list = []
    g.hold_list = []
    g.stock_index_list = []
    g.hold_days = 0
    #初始化全局变量
    g.panic_today_signal = False
    # 设置交易时间，每天运行
    run_daily(prepare_stock_list, time='9:15', reference_security='000300.XSHG')
    run_daily(check_panic_status, '9:15')
    run_weekly(prepare_weekly_adjustment, weekday=1, time='9:16', reference_security='000300.XSHG')
    run_daily(daily_adjustment_buy, time='10:40', reference_security='000300.XSHG')
    run_daily(check_limit_up, time='14:00', reference_security='000300.XSHG')
    run_daily(close_account1, '14:55')
    run_daily(close_account2, '14:55')


#1-1 准备股票池
def prepare_stock_list(context):
    #获取已持有列表
    g.hold_list= []
    g.hold_days += 1
    for position in list(context.portfolio.positions.values()):
        stock = position.security
        g.hold_list.append(stock)
    #获取昨日涨停列表
    if g.hold_list != []:
        df = get_price(g.hold_list, end_date=context.previous_date, frequency='daily', fields=['close','high_limit'], count=1, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        g.high_limit_list = list(df.code)
    else:
        g.high_limit_list = [] 

# 初始化股票信息
def initial_stock_series(ndays=100):
    stock_dict = {}
    if(len(g.target_list)>0):
        for stock in g.target_list:
            stock_df = attribute_history(stock,ndays,'1d',['close','pre_close'],skip_paused=True, df=True, fq='pre')
            stock_dict[stock] = stock_df.close/stock_df.pre_close
        for i in range(ndays):
            one_stock_vlu = g.small_stock_index/g.stock_num
            stock_index_tmp = 0
            for stock in g.target_list:
                if(not math.isnan(stock_dict[stock][i])):
                    stock_index_tmp += one_stock_vlu*stock_dict[stock][i]
                else:
                    stock_index_tmp += one_stock_vlu
            g.small_stock_index = stock_index_tmp
            g.stock_index_list.append(stock_index_tmp)

#1-4 整体调整持仓
def prepare_weekly_adjustment(context):
    # type: (Context) -> None
    # 选取中小板中市值最小的若干只
    check_out_lists = get_index_stocks(g.security_universe_index)
    q = query(valuation.code).filter(
        valuation.code.in_(check_out_lists)
    ).order_by(
        valuation.circulating_market_cap.asc()
    ).limit(
        g.stock_num * 3
    )
    check_out_lists = list(get_fundamentals(q, date=context.previous_date).code)
    # 过滤: 三停（停牌、涨停、跌停）及st,*st,退市
    curr_data = get_current_data()
    check_out_lists = [stock for stock in check_out_lists if not (
            curr_data[stock].paused or
            curr_data[stock].is_st or  # ST
            ('ST' in curr_data[stock].name) or
            ('*' in curr_data[stock].name) or
            ('退' in curr_data[stock].name) or
            (curr_data[stock].last_price == curr_data[stock].high_limit) or  # 涨停开盘, 其它时间用last_price
            (curr_data[stock].last_price == curr_data[stock].low_limit)  # 跌停开盘, 其它时间用last_price
    )]
    #截取不超过最大持仓数的股票量
    target_list = check_out_lists[:min(g.stock_num, len(check_out_lists))]
    for stock in g.high_limit_list:
        if(stock not in g.target_list):
            target_list.insert(0, stock)
    g.target_list = target_list[:min(g.stock_num, len(target_list))]
    if(len(g.stock_index_list)<=100):
        initial_stock_series(100)
        g.panic_today_signal = g.panic_today_signal or has_risk_sig(context,0)

                        
def daily_adjustment_buy(context):
    if (cur_stock_status(context)==0)and(g.panic_today_signal==True):
        print("日买入信号")
        target_list = g.target_list
        g.panic_today_signal = False
        #调仓买入
        position_count = len(context.portfolio.positions)
        target_num = len(target_list)
        if target_num > position_count:
            value = context.portfolio.cash / (target_num - position_count)
            for stock in target_list:
                if context.portfolio.positions[stock].total_amount == 0:
                    if open_position(stock, value):
                        g.hold_days = 0
                        if len(context.portfolio.positions) == target_num:
                            break

#1-6 调整昨日涨停股票
def check_limit_up(context):
    now_time = context.current_dt
    if g.high_limit_list != []:
        #对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
        for stock in g.high_limit_list:
            current_data = get_price(stock, end_date=now_time, frequency='1m',\
                           fields=['close','high_limit'], skip_paused=False, fq='pre',\
                           count=1, panel=False, fill_paused=True)
            if current_data.iloc[0,0] <    current_data.iloc[0,1]:
                send_message("[%s]涨停打开，卖出" % (stock))
                log.info("[%s]涨停打开，卖出" % (stock))
                position = context.portfolio.positions[stock]
                close_position(position)
                

def cur_stock_status(context):
    fell_cnt = 0
    is_panic = 1
    if(len(g.target_list)>0):
        current_data = get_current_data()
        for stock in g.target_list:
            stock_df = attribute_history(stock,1,'1d',['close'],skip_paused=True, df=True, fq='pre')
            if(not math.isnan(current_data[stock].last_price))and(not math.isnan(current_data[stock].day_open))and\
              (not math.isnan(stock_df.close[-1])):
                if(current_data[stock].last_price<current_data[stock].day_open)and\
                  (current_data[stock].last_price<stock_df.close[-1]):
                    fell_cnt = fell_cnt+1
    if(fell_cnt <= g.stock_num*0.7): is_panic = 0
    return(is_panic)
    
def gen_small_stock_index(context,small_stock_index):
    one_stock_vlu = small_stock_index/g.stock_num
    stock_index_tmp = 0
    stock_index_cur = 0
    fell_cnt1 = 0
    fell_cnt2 = 0
    is_panic = 0
    if(len(g.target_list)>0):
        current_data = get_current_data()
        for stock in g.target_list:
            stock_df = attribute_history(stock,1,'1d',['close','pre_close'],skip_paused=True, df=True, fq='pre')
            if (not math.isnan(stock_df.close[-1]))and(not math.isnan(stock_df.pre_close[-1])):
                stock_index_tmp += one_stock_vlu*(stock_df.close[-1]/stock_df.pre_close[-1])
            else:
                stock_index_tmp += one_stock_vlu
            if (not math.isnan(current_data[stock].last_price))and(not math.isnan(stock_df.pre_close[-1])):
                stock_index_cur += one_stock_vlu*(current_data[stock].last_price/stock_df.pre_close[-1])
            else:
                stock_index_cur += one_stock_vlu
            if(stock_df.close[-1]<stock_df.pre_close[-1]):
                fell_cnt1 = fell_cnt1+1
            if(current_data[stock].last_price<current_data[stock].day_open)and\
              (current_data[stock].last_price<stock_df.close[-1]):
                fell_cnt2= fell_cnt2+1
    else:
        stock_index_tmp = small_stock_index
    if(fell_cnt1 >= g.stock_num*0.85)and(fell_cnt2 >= g.stock_num*0.85): is_panic = 1
    return(stock_index_tmp, stock_index_cur, is_panic)
    
    
# 1-6 调整涨幅过大的股票
def has_risk_sig(context, is_append=1):
    sell = 0
    g.small_stock_index,stock_index_cur,is_panic = gen_small_stock_index(context,g.small_stock_index)
    if(is_append):
        g.stock_index_list.append(g.small_stock_index)
        if(len(g.stock_index_list)>100):g.stock_index_list.pop(0)
    if len(g.stock_index_list)>10:
        max_value = max(g.stock_index_list[-10:])
    else:
        max_value = stock_index_cur
    if(stock_index_cur < max_value*0.78):
        sell = 1
    else:
        sell = 0
    return(sell)
    
def break_risk_status(context):
    sell = 0
    g.small_stock_index,stock_index_cur,is_panic = gen_small_stock_index(context,g.small_stock_index)
    if(stock_index_cur < g.small_stock_index*0.98):
        sell = 1
    else:
        sell = 0
    return(sell)
    
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
	last_prices = history(1, unit='1d', field='close', security_list=stock_list)
	limit_prices = history(1, unit='1d', field='high_limit', security_list=stock_list)
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] < limit_prices[stock][-1]]

#2-5 过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
	last_prices = history(1, unit='1d', field='close', security_list=stock_list)
	limit_prices = history(1, unit='1d', field='low_limit', security_list=stock_list)
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] > limit_prices[stock][-1]]

#2-6 过滤科创北交股票
def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68':
            stock_list.remove(stock)
    return stock_list

#2-7 过滤次新股
def filter_new_stock(context, stock_list, d):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=d)]

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

#1-8 清仓后次日资金可转
def close_account1(context):
    val = has_risk_sig(context, 1)
    print("今日持仓%0d天"%(g.hold_days))
    if (g.stock_index_list[-1]<g.stock_index_list[-2])and(g.hold_days>10):
        if len(g.hold_list) != 0:
            current_data = get_current_data()
            for stock in g.hold_list:
                if(current_data[stock].last_price<current_data[stock].high_limit):
                    position = context.portfolio.positions[stock]
                    close_position(position)
                    log.info("平仓卖掉[%s]" % (stock))

def close_account2(context):
    if(break_risk_status(context) == 1):
        if len(g.hold_list) != 0:
            current_data = get_current_data()
            for stock in g.hold_list:
                position = context.portfolio.positions[stock]
                close_position(position)
                log.info("恐慌卖出[%s]" % (stock))
                
def check_panic_status(context):
    if(has_risk_sig(context,0) == 1):
        g.panic_today_signal = True
        log.info("处于恐慌状态")
    else:
        g.panic_today_signal = False
        log.info("处于正常状态")
                
    
    


    
