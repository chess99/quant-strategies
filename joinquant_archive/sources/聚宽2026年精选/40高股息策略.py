# 克隆自聚宽文章：https://www.joinquant.com/post/50715
# 标题：高股息策略
# 作者：雨汪

import pandas as pd
from jqdata import *
from sqlalchemy.sql.expression import or_
from jqlib.technical_analysis import *


def initialize(context):
    # setting
    log.set_level('order', 'error')
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    set_benchmark('000300.XSHG')
    # 设置滑点为理想情况，纯为了跑分好看，实际使用注释掉为好
    # set_slippage(PriceRelatedSlippage(0.000))
    # 设置交易成本
    g.days = 0
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),type='fund')
    # strategy
    g.stock_num = 10 #原版为10
    run_daily(prepare_stock_list, time='9:05', reference_security='000300.XSHG')
    run_weekly(my_Trader, 1, time='09:30')
    run_daily(check_limit_up, time='14:00')

#获取五年时间内均有分红股票及股息率
def get_dividend_ratio_filter_list(context, stock_list):
    def helper(stock_list, time0, time1):
        # print(time0, time1)
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
                    finance.STK_XR_XD.a_registration_date > time0,
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
        DR = DR.sort_values(by=['dividend_ratio'], ascending=False)
        return DR
    
    curr_DR = pd.DataFrame()
    for i in range(5):
        time1 = context.previous_date if i == 0 else time0
        time0 = time1 - datetime.timedelta(days=365)
        DR = helper(stock_list, time0, time1)
        stock_list = list(DR.index)
        if i == 0:
            curr_DR = DR
    final_DR = curr_DR.reindex(stock_list)
    # print(curr_DR.shape, curr_DR[:10])
    # print(final_DR.shape, final_DR[:10])
    return final_DR
    
def my_Trader(context):
    # all stocks
    g.days = 0
    dt_last = context.previous_date
    stocks = get_all_securities('stock', dt_last).index.tolist()
    stocks = filter_kcbj_stock(stocks)
    # print(len(stocks))
    
    #基本面过滤
    df = get_fundamentals(query(valuation.code).filter(valuation.code.in_(stocks),
                indicator.inc_operation_profit_year_on_year>0).order_by(valuation.market_cap.asc()))
    
    stocks = list(df.code)
    # print(len(stocks))
    
    #股息率筛选
    DR = get_dividend_ratio_filter_list(context, stocks)

    # 行业中性：每个行业最多选取2只股息率最高的股票
    df = pd.DataFrame(index=DR.index)
    df['dividend_ratio'] = DR['dividend_ratio']
    industry_infos = get_industry(security=list(DR.index), date=dt_last)
    for stock in industry_infos.keys():
        if 'sw_l1' not in industry_infos[stock]: 
            continue
        df.loc[stock, 'industry'] = industry_infos[stock]['sw_l1']['industry_code']
    df = df.groupby('industry').apply(lambda x: x.nlargest(2, 'dividend_ratio'))
    
    stocks = list(df.index.levels[1])
    df = DR.loc[stocks][['dividend_ratio']].sort_values(by='dividend_ratio', ascending=False)
    stocks = list(df[df['dividend_ratio']>0.03].index)
    print(len(stocks))
    
    stocks = filter_st_stock(stocks)
    stocks = filter_paused_stock(stocks)
    stocks = filter_limitup_stock(context, stocks)
    stocks = filter_limitdown_stock(context, stocks)


    buylist = stocks
    current_data = get_current_data()
    # 调仓卖出
    for stock in context.portfolio.positions:
        if stock not in buylist and stock not in g.high_limit_list:
            order = order_target_value(stock, 0)
            if order != None:
                print('卖出股票：%s %s 下单数量：%s 成交数量：%s'%(stock, current_data[stock].name, order.amount, order.filled))
            else:
                print('卖出股票[%s %s]失败。。。' % (stock, current_data[stock].name))
    
    if len(context.portfolio.positions) >= g.stock_num:
        return
    # 调仓买入
    value = context.portfolio.total_value / g.stock_num
    for stock in buylist:
        if stock not in context.portfolio.positions and DR.loc[stock]['dividend_ratio'] > 0.04:
            order = order_target_value(stock, value)
            if order != None:
                print('买入：%s %s 买入金额：%s 下单数量：%s 成交数量：%s'%(stock, current_data[stock].name, value, order.amount, order.filled))
            else:
                print('买入[%s %s]失败。。。' % (stock, current_data[stock].name))
        if len(context.portfolio.positions) >= g.stock_num:
            break
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
    current_data = get_current_data()
    if g.high_limit_list:
        for stock in g.high_limit_list:
            if current_data[stock].last_price < current_data[stock].high_limit:
                log.info("[%s]涨停打开，卖出" % stock)
                order_target(stock, 0)
            else:
                log.info("[%s]涨停，继续持有" % stock)

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
						
# end
