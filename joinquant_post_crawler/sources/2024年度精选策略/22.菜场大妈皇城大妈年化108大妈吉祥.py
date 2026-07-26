# 克隆自聚宽文章：https://www.joinquant.com/post/40850
# 标题：菜场大妈！皇城大妈！年化108%！大妈吉祥！
# 作者：Clarence.罗

# 克隆自聚宽文章：https://www.joinquant.com/post/40139
# 标题：正黄旗大妈选股法，修改版，年化108%
# 作者：clarence 罗 感谢下列各位大咖
# 这是Python 2 版本，回测请调到Python 2，一创可以运行
# 但请注意PE为负值，和利润大幅下降的股票

# 克隆自聚宽文章：https://www.joinquant.com/post/40811
# 标题：策略分析辅助--实时最大回撤记录
# 作者：Bingyou

# 克隆自聚宽文章：https://www.joinquant.com/post/40139
# 标题：正黄旗大妈选股法，修改版，年化92%
# 作者：oupian 1211修改

# 克隆自聚宽文章：https://www.joinquant.com/post/40004
# 标题：菜场大妈选股法
# 作者：美吉姆优秀毕业代表 贴在社区下面的

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
    # set_option('avoid_future_data', True)
    set_benchmark('000905.XSHG')
    # 设置滑点为理想情况，纯为了跑分好看，实际使用注释掉为好
    set_slippage(PriceRelatedSlippage(0.000))
    # 设置交易成本
    set_order_cost(OrderCost(open_tax=0, close_tax=0.0001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),type='fund')
    # strategy
    g.stock_num = 10
    g.buylist = []

    g.new_high_value = context.portfolio.starting_cash  # 资金量新高值
    g.maxdown = 0  #最大回撤
    g.new_high_value = 0

    run_daily(get_high_limit_stocks, time='9:05', reference_security='000300.XSHG')
    run_monthly(select_stocks_and_buy,1,time='9:30')  #每月派息好股，按小市值排序建立了g.buylist；派息不怎么变，市值在变; #每月买了一次
    run_daily(sell_stocks_opened_from_up_limit, time='14:00') #每日检查头天涨停，当日打开的股，卖出
    run_daily(sell_hi_vol_stocks_at_dayend_and_buy_again, time='14:30')  #每日检查涨停不放量的股，卖出；多出来的钱，又买了一次，
    #问题是买入了刚卖出的股.
    run_monthly(analyze_stocks_held, 1, time='15:01')  #收盘了没事儿再算算，发现一大堆PE为负值，和利润大幅下滑的股:-(


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
    #PY3 dividend = dividend.set_index('code')
    dividend = dividend.groupby('code').sum()
    temp_list = list(dividend.index) #query查询不到无分红信息的股票，所以temp_list长度会小于stock_list
    #获取市值相关数据
    q = query(valuation.code,valuation.market_cap).filter(valuation.code.in_(temp_list))
    cap = get_fundamentals(q, date=time1)
    cap = cap.set_index('code')
    #计算股息率
    #PY3 DR = pd.concat([dividend, cap] ,axis=1, sort=False)
    DR = pd.concat([dividend, cap], axis=1)

    DR['dividend_ratio'] = (DR['bonus_amount_rmb']/10000) / DR['market_cap']
    #排序并筛选
    #PY3 DR = DR.sort_values(by=['dividend_ratio'], ascending=sort)
    DR = DR.sort(columns='dividend_ratio', ascending=False)
    final_list = list(DR.index)[int(p1*len(DR)):int(p2*len(DR))]
    return final_list

def select_stocks_and_buy(context):
    select_stocks(context)
    
    choice=g.buylist # [:g.stock_num]
    # Sell
    #sell_list = []
    #for s in context.portfolio.positions:
    #    if (s not in choice) :
    #        sell_list.append(s)
    #sell_stocks(context, sell_list)

    # buy
    buy_stocks(context, g.buylist)

def select_stocks(context):
    # all stocks
    dt_last = context.previous_date
    stocks = get_all_securities('stock', dt_last).index.tolist()

    stocks = filter_kcbj_stock(stocks)
    #stocks = filter_st_stock(stocks)
    #stocks = filter_paused_stock(stocks)
    #stocks = filter_limitup_stock(context,stocks)
    #stocks = filter_limitdown_stock(context,stocks)
    #stocks = filter_highprice_stock(context,stocks)
    
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
    choice = choice[:g.stock_num*2]
    g.buylist = choice
################End select_stocks_and_buy

def buy_stocks(context, choice):
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
################End buy_stocks

def sell_stocks(context, sell_list):
    current_data=get_current_data()
    if len(sell_list)>0:
        for security in sell_list:
            cprice = current_data[security].last_price
            boughtcost = context.portfolio.positions[security].avg_cost
            if context.portfolio.positions[security].avg_cost==0:
                log.error("Sell %s " % (current_data[security].name), "avg_cost is 0")
                profit = 0
            else:
                profit = (cprice - boughtcost)/boughtcost *100
            log.info("Sell %s " % (current_data[security].name), "profit: %.1f%%" % profit, "init time %s" % context.portfolio.positions[security].init_time)
            limit_price = max(cprice*0.95,current_data[security].low_limit)
            ordert = order_target_value(security,0, LimitOrderStyle(limit_price))
            if (None == ordert):
                log.info("Sell failed %s" % (current_data[security].name))
    #else:
    #    log.info("no one to sell")
    return
################End sell_stocks

# 准备股票池
def get_high_limit_stocks(context):
    #获取已持有列表
    g.high_limit_list = []
    hold_list = list(context.portfolio.positions)
    if hold_list:
        #panel = get_price(hold_list, end_date=context.previous_date, frequency='daily',
        #               fields=['close', 'high_limit'],
        #               count=1) # , panel=False)
        #PY3 g.high_limit_list = df[df['close'] == df['high_limit']]['code'].tolist()
        for stock in hold_list:
            df=get_price(stock, count = 1, end_date=context.previous_date, frequency='daily', fields=['high_limit', 'close'])
            if df['high_limit'][-1]==df['close'][-1]:
                g.high_limit_list.append(stock)

#  调整昨日涨停股票
def sell_stocks_opened_from_up_limit(context):
     # 获取持仓的昨日涨停列表
    cdata = get_current_data()
    sell_list = []
    if len(g.high_limit_list)>0:
        for stock in g.high_limit_list:
            if cdata[stock].last_price < cdata[stock].high_limit:
                log.info("[%s]涨停打开，卖出" % cdata[stock].name)
                #order_target(stock, 0)
                sell_list.append(stock)
                #if stock in g.buylist:
                #    g.buylist.remove(stock)
            else:
                log.info("[%s]涨停，继续持有" % cdata[stock].name)

    if sell_list:
    #    select_stocks(context) 
    #    for stock in sell_list: 
    #        if stock in g.buylist: 
    #            g.buylist.remove(stock)

        sell_stocks(context, sell_list)
    #    buy_stocks(context, g.buylist)
 
 # 尾盘买卖股；放量未涨停的卖出；低位的买进
def sell_hi_vol_stocks_at_dayend_and_buy_again(context):

    btlist = context.portfolio.positions
    cdata=get_current_data()

    #PY3 VOLT,MAVOL5,MAVOL10 = VOL(btlist, check_date=context.current_dt, M1=5, M2=10, include_now = True)

    sell_list = []
    for stock in btlist:
        if (cdata[stock].last_price == cdata[stock].high_limit):
            continue
        stock_now_vol = now_vol(context, stock)
        stock_ma10_vol = ma_vol(context, stock, 10)
        if (stock_now_vol>stock_ma10_vol*3): #放量未涨停
            log.info("[%s]放量未涨停，卖出" % cdata[stock].name)
            sell_list.append(stock)
    
    if sell_list:
    #    select_stocks(context) 
    #    for stock in sell_list: 
    #        if stock in g.buylist: 
    #            g.buylist.remove(stock)

        sell_stocks(context, sell_list)
    
    buy_stocks(context, g.buylist)


def ma_vol(context, stock, number_of_days):   
    df_vol = get_price(stock, end_date=context.previous_date, frequency='daily', count=number_of_days, fields=['volume'])
    ft_ma_vol = df_vol['volume'].mean()
    #print (stock, number_of_days, 'volume mean', ft_ma_vol) 
    return ft_ma_vol    

def now_vol(context, stock):   
    
    dt_zero_clock_today = context.current_dt - datetime.timedelta(hours=context.current_dt.hour, minutes=context.current_dt.minute, seconds=context.current_dt.second, microseconds=context.current_dt.microsecond)
    #print ('dt_zero_clock_today', dt_zero_clock_today, type(dt_zero_clock_today))
    dt_trading_start_today = dt_zero_clock_today + datetime.timedelta(hours=9, minutes=15, seconds=00)
    #print ('dt_trading_start_today', dt_trading_start_today, type(dt_trading_start_today))

    df_vol = get_price(stock, start_date=dt_trading_start_today, end_date=context.current_dt, frequency='minute', fields=['volume'])
    ft_now_vol = df_vol['volume'].sum()
    #print (stock, 'ft_now_vol', ft_now_vol)
    return ft_now_vol    

def analyze_stocks_held(context):
    current_data = get_current_data()   #获取日期
    hold_stocks = context.portfolio.positions.keys()
    for s in hold_stocks:
        q = query(valuation.code,valuation.market_cap,valuation.pe_ratio, indicator.inc_net_profit_year_on_year).filter(valuation.code == s)
        df = get_fundamentals(q)
        # log.info(s,current_data[s].name,'流值',df['circulating_market_cap'][0],'亿')
        #log.info(s,current_data[s].name,'市值',df['market_cap'][0],'亿')
        #log.info(s,current_data[s].name,'股价',current_data[s].last_price,'元')
        log.info(s,current_data[s].name,'市盈率',df['pe_ratio'][0])
        log.info(s,current_data[s].name,'净利润同比增长率',df['inc_net_profit_year_on_year'][0])
        #inc_net_profit_year_on_year
        #净利润同比增长率(%)	
        #（当期的净利润-上年当期的净利润）/上年当期的净利润绝对值=净利润同比增长率。
        #log.info('##############################################################')
        #inc_net_profit_year_on_year
        #净利润同比增长率(%)	
        #（当期的净利润-上年当期的净利润）/上年当期的净利润绝对值=净利润同比增长率。
    log.info('一天结束')
    log.info('##############################################################')

def after_trading_end(context):
    g.total_value = context.portfolio.total_value
    # 若总资金大于昨天纪录的资金新高值，则将资金新高值变为今日总资金，令最大回撤值归0；否则计算今日总资金的回撤值
    if g.total_value > g.new_high_value:   
        g.new_high_value = g.total_value  
        g.maxdown = 0
    else:
        max_down = (g.new_high_value - g.total_value)/g.new_high_value*100
    # 若今日总资金回撤值大于最大回撤值，则替代最大回撤值，否则最大回撤值不变。
        g.maxdown = max_down if max_down > g.maxdown else g.maxdown
    record(maxdown=g.maxdown)
    
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
