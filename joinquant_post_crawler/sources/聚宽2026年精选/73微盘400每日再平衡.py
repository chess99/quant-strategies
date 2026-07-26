# 克隆自聚宽文章：https://www.joinquant.com/post/44853
# 标题：微盘400每日再平衡
# 作者：开心果

from jqdata import *

#初始化函数 
def initialize(context):
    set_benchmark('399303.XSHE')
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    log.set_level('system', 'error')
    g.stock_num = 400
    run_daily(rebalance, '9:30')
    
def rebalance(context):
    stocks = get_all_securities('stock').index.tolist()
    stocks = filter_kcbj_stock(stocks)
    stocks = filter_st_stock(stocks)
    
    df = get_fundamentals(query(valuation.code,valuation.market_cap
    ).filter(valuation.code.in_(stocks)
    ).order_by(valuation.market_cap.asc()
    ).limit(int(g.stock_num)))
    
    stocks= list(df.code)
    
    for s in context.portfolio.positions:
        if s not in stocks:
            order_target_value(s, 0)
            
    value = context.portfolio.total_value/g.stock_num        
    balance = {}        
    for s in stocks:
        if s in context.portfolio.positions:
            diff = (value - context.portfolio.positions[s].value)
        else:
            diff = value
        balance[s] = diff
         
    stocks = dict(sorted(balance.items(),key= lambda x: x[1],reverse=False))
    for s in stocks.keys():
        order_target_value(s, value)
        
    cap = df.market_cap.sum()
    record(market_cap=cap)

# 过滤科创北交股票
def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68':
            stock_list.remove(stock)
    return stock_list

# 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
	current_data = get_current_data()
	return [stock for stock in stock_list
			if not current_data[stock].is_st
			and 'ST' not in current_data[stock].name
			and '*' not in current_data[stock].name
			and '退' not in current_data[stock].name]

