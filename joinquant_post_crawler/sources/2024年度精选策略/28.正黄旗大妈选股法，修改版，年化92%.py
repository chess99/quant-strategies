# 克隆自聚宽文章：https://www.joinquant.com/post/40139
# 标题：正黄旗大妈选股法，修改版，年化92%
# 作者：oupian

# 作者：oupian 1211修改

# 克隆自聚宽文章：https://www.joinquant.com/post/40038
# 标题：正黄旗大妈选股法
# 作者：GoodThinker

# 克隆自聚宽文章：https://www.joinquant.com/post/40004
# 标题：菜场大妈选股法
# 作者：开心果

import pandas as pd
from jqdata import *
from jqlib.technical_analysis import *

def initialize(context):
    # setting
    log.set_level('order', 'error')
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    set_benchmark('000905.XSHG')
    # 设置滑点为理想情况，纯为了跑分好看，实际使用注释掉为好
    set_slippage(PriceRelatedSlippage(0.000))
    # 设置交易成本
    set_order_cost(OrderCost(open_tax=0, close_tax=0.0001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),type='fund')
    # strategy
    g.stock_num = 10
    run_daily(prepare_stock_list, time='9:05', reference_security='000300.XSHG')
    run_monthly(my_Trader, 1 ,time='9:30')
    run_daily(check_limit_up, time='14:00')
    run_daily(check_at_dayend, time='14:30')
    g.buylist = []


#1-1 根据最近一年分红除以当前总市值计算股息率并筛选    
def get_dividend_ratio_filter_list(context, stock_list, sort, p1, p2):
    time1 = context.previous_date
    time0 = time1 - datetime.timedelta(days=365)
    #获取分红数据，由于finance.run_query最多返回4000行，以防未来数据超限，最好把stock_list拆分后查询再组合
    interval = 1000 #某只股票可能一年内多次分红，导致其所占行数大于1，所以interval不要取满4000
    list_len = len(stock_list)
    #截取不超过interval的列表并查询
    q = query(finance.STK_XR_XD.code, finance.STK_XR_XD.a_registration_date, finance.STK_XR_XD.bonus_amount_rmb
    ).filter(
        finance.STK_XR_XD.a_registration_date >= time0,
        finance.STK_XR_XD.a_registration_date <= time1,
        finance.STK_XR_XD.code.in_(stock_list[:min(list_len, interval)]))
    df = finance.run_query(q)
    #对interval的部分分别查询并拼接
    if list_len > interval:
        df_num = list_len // interval
        for i in range(df_num):
            q = query(finance.STK_XR_XD.code, finance.STK_XR_XD.a_registration_date, finance.STK_XR_XD.bonus_amount_rmb
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

def my_Trader(context):
    # all stocks
    dt_last = context.previous_date
    stocks = get_all_securities('stock', dt_last).index.tolist()
    stocks = filter_kcbj_stock(stocks)
    
     #高股息(全市场最大25%)
    stocks = get_dividend_ratio_filter_list(context, stocks, False, 0, 0.25)
    # 获取基本面数据
    q = query(valuation.code,
                valuation.pe_ratio / indicator.inc_net_profit_year_on_year,# PEG
                indicator.roe / valuation.pb_ratio, # PB-ROE
                indicator.roe ,
                ).filter(
                    valuation.pe_ratio / indicator.inc_net_profit_year_on_year>-1,
                    valuation.pe_ratio / indicator.inc_net_profit_year_on_year<3,
                    #indicator.roe / valuation.pb_ratio > 0,
                    valuation.code.in_(stocks))
    df_fundamentals = get_fundamentals(q, date = None)       
    stocks = list(df_fundamentals.code)
    # fuandamental data
    #df = get_fundamentals(query(valuation.code).filter(valuation.code.in_(stocks)).order_by(valuation.market_cap.asc()))
    #df = get_fundamentals(query(valuation.code,valuation.market_cap).filter(valuation.code.in_(stocks)).order_by(valuation.market_cap.asc()))
    q = query(valuation.code,
              valuation.market_cap
                ).filter(
                    valuation.code.in_(stocks),
                    valuation.market_cap<=100).order_by(valuation.market_cap.asc())    
    df = get_fundamentals(q, date = None)
    print(df.shape)
    #print(df)
    choice = list(df.code)
    choice = filter_st_stock(choice)
    choice = filter_paused_stock(choice)
    choice = filter_limitup_stock(context,choice)
    choice = filter_limitdown_stock(context,choice)
    choice = filter_highprice_stock(context,choice)
    #choice = choice[:g.stock_num]
    g.buylist = choice
    # Sell
    #sell_list = []
    #for s in context.portfolio.positions:
    #    if (s not in choice) :
    #        sell_list.append(s)
    #sellstock(context, sell_list)
    # buy
    buystock(context, g.buylist)
################End My_Trader
def buystock(context,choice):
    position_count = len(context.portfolio.positions)
    if g.stock_num <= position_count:
        return
    
    buylist = choice
    #buylist = []
    #K,D = KD(choice, check_date=context.previous_date, N = 9, M1 = 3, M2 = 3)
    #VOLT,MAVOL10,MAVOL20 = VOL(choice, check_date=context.current_dt, M1=10, M2=20, include_now = True)
    #VOLT,MAVOL5,MAVOL20 = VOL(choice, check_date=context.current_dt, M1=5, M2=20, include_now = True)
    #for s in choice:
        #K值小于25 #20日均量不能超过10日均量的1.3倍；10日均量不能超过50日均量的1.3倍；说明前期未明显放量
        #if (K[s] > 25) or (MAVOL20[s] > MAVOL10[s]*1.3) or (MAVOL10[s] > MAVOL5[s]*1.8):
        #    continue
    #    buylist.append(s)
    cdata = get_current_data()
    #namelist = []
    #for s in buylist:
    #    namelist.append(cdata[s].name)
    #log.info('bulist:', namelist)    
    
    psize = context.portfolio.available_cash/(g.stock_num - position_count)
    for s in buylist:
        if s not in context.portfolio.positions:
            log.info('buy', s, cdata[s].name)
            order_value(s, psize)
            if len(context.portfolio.positions) == g.stock_num:
                break   
################End buystock
def sellstock(context, sell_list):
    current_data=get_current_data()
    if len(sell_list)>0:
        for security in sell_list:
            cprice = current_data[security].last_price
            boughtcost = context.portfolio.positions[security].acc_avg_cost
            profit = (cprice - boughtcost)/boughtcost *100
            log.info("Sell %s " % (current_data[security].name), "profit: %.1f%%" % profit, "init time %s" % context.portfolio.positions[security].init_time)
            limit_price = max(cprice*0.95,current_data[security].low_limit)
            ordert = order_target_value(security,0, LimitOrderStyle(limit_price))
            if (None == ordert):
                log.info("Sell failed %s" % (current_data[security].name))
    #else:
    #    log.info("no one to sell")
    return
################End sellstock
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
     # 获取持仓的昨日涨停列表
    cdata = get_current_data()
    sell_list = []
    if g.high_limit_list:
        for stock in g.high_limit_list:
            if cdata[stock].last_price < cdata[stock].high_limit:
                log.info("[%s]涨停打开，卖出" % cdata[stock].name)
                #order_target(stock, 0)
                sell_list.append(stock)
            else:
                log.info("[%s]涨停，继续持有" % cdata[stock].name)
    if (len(sell_list)>0):
        sellstock(context, sell_list)
 
 # 尾盘买卖股；放量未涨停的卖出；低位的买进
def check_at_dayend(context):
    btlist = context.portfolio.positions
    cdata=get_current_data()
    VOLT,MAVOL5,MAVOL10 = VOL(btlist, check_date=context.current_dt, M1=5, M2=10, include_now = True)
    sell_list = []
    for stock in btlist:
        if (cdata[stock].last_price == cdata[stock].high_limit):
            continue
        if (VOLT[stock]>MAVOL10[stock]*3): #放量未涨停
            log.info("[%s]放量未涨停，卖出" % cdata[stock].name)
            sell_list.append(stock)
    sellstock(context, sell_list)
    buystock(context, g.buylist)
    
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
	
	# 已存在于持仓的股票即使涨停也不过滤，避免此股票再次可买，但因被过滤而导致选择别的股票
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
