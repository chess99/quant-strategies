# 克隆自聚宽文章：https://www.joinquant.com/post/39814
# 标题：持仓95只大容量小市值，媲美金元顺安元启
# 作者：开心果

import pandas as pd

def initialize(context):
    # setting
    log.set_level('order', 'error')
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    set_benchmark('000905.XSHG')
    # strategy
    g.stock_num = 95
    run_daily(prepare_stock_list, time='9:05', reference_security='000300.XSHG')
    run_monthly(my_Trader, 1 ,time='9:30')
    run_daily(check_limit_up, time='14:00')
                
def my_Trader(context):
    # all stocks
    dt_last = context.previous_date
    stocks = get_all_securities('stock', dt_last).index.tolist()
    # filter, ST
    stocks = filter_kcbj_stock(stocks)
    stocks = filter_st_stock(stocks)
    # fuandamental data
    df = get_fundamentals(query(
            valuation.code
        ).filter(
            valuation.code.in_(stocks),
            valuation.pb_ratio > 0,
            indicator.inc_return >0,
            indicator.inc_total_revenue_year_on_year>0,
            indicator.inc_net_profit_year_on_year>0,
            indicator.ocf_to_operating_profit>5,
        ).order_by(
            valuation.market_cap.asc()
		).limit(
		    g.stock_num
	    ))
    choice = list(df.code)
    # Sell
    for s in context.portfolio.positions:
        if (s  not in choice) and (s not in g.high_limit_list):
            order_target(s, 0)
    # buy
    psize = 1.0/g.stock_num * context.portfolio.total_value
    for s in choice:
        if context.portfolio.available_cash < psize:
            break
        if s not in context.portfolio.positions:
            order_value(s, psize)
            

#1-3 准备股票池
def prepare_stock_list(context):
    #获取已持有列表
    g.high_limit_list = []
    hold_list = list(context.portfolio.positions)
    if hold_list:
        df = get_price(hold_list, end_date=context.previous_date, frequency='daily',
                       fields=['close', 'high_limit', 'paused'],
                       count=1, panel=False)
        g.high_limit_list = df.query('close==high_limit and paused==0')['code'].tolist()
        
# 1-5 调整昨日涨停股票
def check_limit_up(context):
     # 获取持仓的昨日涨停列表
    current_data = get_current_data()
    if g.high_limit_list:
        for stock in g.high_limit_list:
            if current_data[stock].last_price < current_data[stock].high_limit:
                log.info("[%s]涨停打开，卖出" % stock)
                order_target(stock, 0)
            else:
                log.info("[%s]涨停，继续持有" % stock)
 
 
#2-6 过滤科创北交股票
def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68':
            stock_list.remove(stock)
    return stock_list

# 2-2 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not (
            current_data[stock].is_st or
            'ST' in current_data[stock].name or
            '*' in current_data[stock].name or
            '退' in current_data[stock].name)]
            
# end
