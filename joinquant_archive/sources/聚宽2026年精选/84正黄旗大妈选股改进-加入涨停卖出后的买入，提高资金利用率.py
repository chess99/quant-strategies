# 克隆自聚宽文章：https://www.joinquant.com/post/44743
# 标题：正黄旗大妈选股改进-加入涨停卖出后的买入，提高资金利用率
# 作者：jql123

# 克隆自聚宽文章：https://www.joinquant.com/post/40004
# 标题：删
# 作者：开心果

# 克隆自聚宽文章：https://www.joinquant.com/post/40038
# 标题：正黄旗大妈选股法
# 作者：GoodThinker

# 克隆自聚宽文章：https://www.joinquant.com/post/40004
# 标题：菜场大妈选股法
# 作者：开心果

import pandas as pd # 聚宽的panda版本是 0.23.4
from jqdata import *


def initialize(context):
    # setting
    log.set_level('order', 'error')
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    set_benchmark('000905.XSHG')
    # 设置滑点为理想情况，纯为了跑分好看，实际使用注释掉为好
    # set_slippage(PriceRelatedSlippage(0.000))
    # 设置交易成本
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),type='fund')
    # strategy
    g.stock_num = 10
    g.choice = []
    g.just_sold = []
    run_daily(prepare_stock_list, time='9:05', reference_security='000300.XSHG') 
    run_daily(check_limit_up, time='14:00') 
    run_monthly(my_Trader, 1 ,time='9:30') 
    run_monthly(go_Trader, 1 ,time='14:55') 
    
def my_Trader(context):
    #1 all stocks
    dt_last = context.previous_date
    stocks = get_all_securities('stock', dt_last).index.tolist()
    stocks = filter_kcbj_stock(stocks)
    #2 股息率
    stocks = get_dividend_ratio_filter_list(context, stocks, False, 0, 0.25)  
    #3 peg
    stocks = get_peg(context,stocks)
    #4 各种过滤
    choice = filter_st_stock(stocks)
    choice = filter_paused_stock(choice)
    choice = filter_limitup_stock(context,choice)
    choice = filter_limitdown_stock(context,choice)
    #5 低价股
    choice = filter_highprice_stock(context,choice)
    g.choice = choice[:g.stock_num]

def go_Trader(context):
    g.just_sold = [] #每月清零一次 g.just_sold 防止其中内容一直膨胀
    cdata = get_current_data()
    choice = g.choice
    # Sell
    for s in context.portfolio.positions:
        if (s  not in choice) :
            log.info('Sell', s, cdata[s].name)
            order_target(s, 0) # 如果跌停怎么办？
    # buy
    position_count = len(context.portfolio.positions)
    if g.stock_num > position_count:
        psize = context.portfolio.available_cash/(g.stock_num - position_count)
        for s in choice:
            if s not in context.portfolio.positions:
                log.info('buy', s, cdata[s].name)
                order_value(s, psize) # 这里如果涨停怎么办？
                if len(context.portfolio.positions) == g.stock_num:
                    break

def cap(context):
    current_data = get_current_data()   #获取日期
    hold_stocks = context.portfolio.positions.keys()
    for s in hold_stocks:
        q = query(valuation).filter(valuation.code == s)
        df = get_fundamentals(q)
        # log.info(s,current_data[s].name,'流值',df['circulating_market_cap'][0],'亿')
        log.info(s,current_data[s].name,'市值',df['market_cap'][0],'亿')
        log.info(s,current_data[s].name,'股价',current_data[s].last_price,'元')

def get_peg(context,stocks):
    # 获取基本面数据
    q = query(valuation.code,
                valuation.pe_ratio / indicator.inc_net_profit_year_on_year,# PEG
                indicator.roe / valuation.pb_ratio, # PB-ROE  收益率指标：ROE/PB特别适合于周期类、成长性一般企业的估值分析
                indicator.roe,
                ).filter(
                    valuation.pe_ratio / indicator.inc_net_profit_year_on_year>-3,
                    valuation.pe_ratio / indicator.inc_net_profit_year_on_year<3,
                    # indicator.roe / valuation.pb_ratio > 3.2,   #国债收益率
                    valuation.code.in_(stocks))
    df_fundamentals = get_fundamentals(q, date = None)       
    stocks = list(df_fundamentals.code)
    # fuandamental data
    df = get_fundamentals(query(valuation.code).filter(valuation.code.in_(stocks)).order_by(valuation.market_cap.asc()))
    choice = list(df.code)
    return choice

#1-1 根据最近一年分红除以当前总市值计算股息率并筛选    
def get_dividend_ratio_filter_list(context, stock_list, sort, p1, p2):
    time1 = context.previous_date
    time0 = time1 - datetime.timedelta(days=365)
    #获取分红数据，由于finance.run_query最多返回4000行，以防未来数据超限，最好把stock_list拆分后查询再组合
    interval = 1000 #某只股票可能一年内多次分红，导致其所占行数大于1，所以interval不要取满4000
    list_len = len(stock_list)
    #截取不超过interval的列表并查询
    q = query(
        finance.STK_XR_XD.code, 
        finance.STK_XR_XD.a_registration_date, 
        finance.STK_XR_XD.bonus_amount_rmb
    ).filter(
        finance.STK_XR_XD.a_registration_date >= time0,
        finance.STK_XR_XD.a_registration_date <= time1,
        finance.STK_XR_XD.code.in_(stock_list[:min(list_len, interval)]))
    df = finance.run_query(q)
    #对interval的部分分别查询并拼接
    if list_len > interval:
        df_num = list_len // interval
        for i in range(df_num):
            q = query(
                finance.STK_XR_XD.code,
                finance.STK_XR_XD.a_registration_date,
                finance.STK_XR_XD.bonus_amount_rmb
            ).filter(
                finance.STK_XR_XD.a_registration_date >= time0,
                finance.STK_XR_XD.a_registration_date <= time1,
                finance.STK_XR_XD.code.in_(stock_list[interval*(i+1):min(list_len,interval*(i+2))]))
            temp_df = finance.run_query(q)
            df = df.append(temp_df)
    dividend = df.fillna(0)
    dividend = dividend.set_index('code')
    dividend = dividend.groupby('code').sum()
    temp_list = list(dividend.index) #query查询不到无分红信息的股票，所以temp_list长度会小于stock_list
    #获取市值相关数据
    q = query(valuation.code,valuation.market_cap).filter(valuation.code.in_(temp_list))
    cap = get_fundamentals(q, date=time1)
    cap = cap.set_index('code')
    #计算股息率
    DR = pd.concat([dividend, cap] ,axis=1, sort=False)
    DR['dividend_ratio'] = (DR['bonus_amount_rmb']/10000) / DR['market_cap']
    #排序并筛选
    DR = DR.sort_values(by=['dividend_ratio'], ascending=sort)
    final_list = list(DR.index)[int(p1*len(DR)):int(p2*len(DR))]
    return final_list
    
# 准备股票池
def prepare_stock_list(context):
    #获取已持有列表
    g.high_limit_list = []
    hold_list = list(context.portfolio.positions)
    if hold_list:
        df = get_price(hold_list, end_date=context.previous_date, frequency='daily',
                       fields=['close', 'high_limit'],
                       count=1, panel=False)
        g.high_limit_list = df[df['close'] == df['high_limit']]['code'].tolist()

#  调整昨日涨停股票
def check_limit_up(context):
    # 检查持仓，如果有卖出就再买入
    position_count = len(context.portfolio.positions)
    if g.stock_num > position_count and position_count != 0: # position_count != 0 用于避免第一次运行时代替go_trader 买入
        my_Trader(context) # 计算 g.choice
        cdata = get_current_data()
        psize = context.portfolio.available_cash/(g.stock_num - position_count)
        for s in g.choice:
            if s not in context.portfolio.positions and s not in g.just_sold:
                order_value(s, psize) 
                if len(context.portfolio.positions) == g.stock_num:
                    break
    # 获取持仓的昨日涨停列表
    current_data = get_current_data()
    if g.high_limit_list:
        for stock in g.high_limit_list:
            if current_data[stock].last_price < current_data[stock].high_limit:
                order_target(stock, 0)
                g.just_sold.append(stock)
            
 
# 过滤科创北交股票
def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68':
            stock_list.remove(stock)
    return stock_list

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
	
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] < current_data[stock].high_limit]

# 过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] > current_data[stock].low_limit]

#2-4 过滤股价高于9元的股票	
def filter_highprice_stock(context,stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] < 9]
						
# end
