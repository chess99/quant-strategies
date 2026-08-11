# 克隆自聚宽文章：https://www.joinquant.com/post/43965
# 标题：有赚就好-小市值剥头皮改进 2年3.86%回撤
# 作者：CMA

import talib
import numpy as np
import pandas as pd

def initialize(context):
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    #set_option("t0_mode", True) 
    set_slippage(FixedSlippage(0.02))
    set_commission(PerTrade(buy_cost=0.0003, sell_cost=0.0013, min_cost=5))
    set_benchmark('399303.XSHE')
    g.choice = 500
    g.amount = 7
    g.muster = []
    g.bucket = []
    g.summit = {}
    log.set_level('order', 'warning')
    run_daily(buy, time='9:30', reference_security='399303.XSHE')
    run_daily(sell, time='10:30', reference_security='399303.XSHE')

    
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

# 2-3 过滤科创北交股票 30为创业板
def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68' or stock[:2] == '30':
            stock_list.remove(stock)
    return stock_list

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

#2-6 过滤次新股
def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=375)]
    

def before_trading_start(context):
    log.info('------------------------------------------------------------')
    fundamentals_data = get_fundamentals(query(valuation.code, valuation.market_cap).order_by(valuation.market_cap.asc()).limit(g.choice))
    stocks = list(fundamentals_data['code'])
    current_data = get_current_data()
    g.muster = [s for s in stocks if not current_data[s].paused and not current_data[s].is_st and 'ST' not in current_data[s].name and '*' not in current_data[s].name and '退' not in current_data[s].name and current_data[s].low_limit < current_data[s].day_open < current_data[s].high_limit]
    g.muster = filter_paused_stock(g.muster)
    g.muster = filter_st_stock(g.muster)
    g.muster = filter_kcbj_stock(g.muster)
    g.muster = filter_limitup_stock(context, g.muster)
    g.muster = filter_limitdown_stock(context, g.muster)


def sell(context):
    data_today = get_current_data()
    for s in context.portfolio.positions:
        print("sell:"+s)
        order_target(s, 0)

def buy(context):
    data_today = get_current_data()
    available_slots = g.amount - len(context.portfolio.positions)
    if available_slots <= 0: 
        print("no position")
        return
    allocation = context.portfolio.cash / available_slots
    for s in g.muster:
        if len(context.portfolio.positions) == g.amount:
            break
        if (history(5, '1d', 'paused', s).max().values[0] == 0):
            # 过滤A杀
            low = history(4, '1d', 'low', s).min().values[0]
            high = history(4, '1d', 'high', s).max().values[0]
            precent = (high - low)/low*100
            if(precent<=10):
                open_price_today = data_today[s].day_open
                prev_close = get_price(s, count=1, end_date=context.previous_date).iloc[-1]['close']
                # five_day_avg = history(5, '1d', 'close', s)[s].mean()
                his = history(60, '1d', 'close', s)
                ema = talib.EMA(his.values.flatten(), timeperiod=5)[-1]
                if(prev_close > ema):
                    if (get_price(s, count=1, end_date=context.previous_date).iloc[-1]['low'] > open_price_today):
                        order(s, int(allocation/open_price_today))
