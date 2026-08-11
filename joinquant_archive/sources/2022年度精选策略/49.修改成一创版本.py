# 克隆自聚宽文章：https://www.joinquant.com/post/40159
# 标题：修改成一创版本
# 作者：keep_silent

# 克隆自聚宽文章：https://www.joinquant.com/post/40147
# 标题：wywy尾盘买入-一创报错
# 作者：天悦

# 克隆自聚宽文章：https://www.joinquant.com/post/40098
# 标题：小市值尾盘买改编
# 作者：Pengpengpeng

#导入函数库
from jqdata import *
#from jqfactor import get_factor_values
#from jqlib.technical_analysis import *
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
    g.stock_num = 5
    g.limit_up_list = [] #记录持仓中涨停的股票
    g.hold_list = [] #当前持仓的全部股票
    g.history_hold_list = [] #过去一段时间内持仓过的股票
    g.not_buy_again_list = [] #最近买过且涨停过的股票一段时间内不再买入
    g.limit_days = 20 #不再买入的时间段天数
    g.target_list = [] #开盘前预操作股票池
    # 设置交易运行时间
    run_daily(prepare_stock_list, time='9:05', reference_security='000300.XSHG')
    run_daily(weekly_adjustment,time='14:53', reference_security='000300.XSHG')
    run_daily(check_limit_up, time='14:00', reference_security='000300.XSHG') #检查持仓中的涨停股是否需要卖出
    run_daily(print_position_info, time='15:10', reference_security='000300.XSHG')

# 去除异常值(绝对中位差法)
def __error_drop(Series):
    Xm = Series.median()
    MADe =  (abs(Series - Xm)).median() * 1.4826
    return Series[(Series > (Xm - 3*MADe)) & (Series < (Xm + 3*MADe))]
        
# 市值中性化(返回Series)
def __mkt_cap_ind_neu(Series, end_date):
    stock_list = Series.index.tolist()
    q = query(valuation.code, 
      valuation.market_cap,
     ).filter(valuation.code.in_(stock_list),
             )
    df_mkt_cap = get_fundamentals(q, date=end_date)
    df_mkt_cap.set_index(['code'], inplace=True)
    
    df = pd.merge(Series.to_frame(),df_mkt_cap,how='left',left_index=True,right_index=True).dropna(axis=0)
    df['market_cap'] = df['market_cap'].apply(lambda x: math.log(x))
    
    x = df['market_cap'].values
    y = df.iloc[:,0].values
    X = sm.add_constant(x) # 添加常数项
    model = sm.OLS(y,X)
    results = model.fit()
    alpha = results.params[0]
    beta = results.params[1]
    res =  y - (alpha + beta*x) # 残差
    df.iloc[:,0] = res
    return df.iloc[:,0]
    
# 行业中性化(返回Series) 
def __ind_neu(Series, end_date):
    stock_list = Series.index.tolist()
    df = get_industries(name='sw_l2')
    df = df[df['start_date'] <= end_date] # 注意: 取今天以前的行业防止未来函数
    ind_list = df.index.tolist()
    ind_stks_dict = {}
    #print(df)
    for key in ind_list:
        ind_stocks_list = get_industry_stocks(key, date=end_date) # 所有板块成份股
        if len(ind_stocks_list) == 0:
            continue
        ind_stks_dict[key] = list(set(ind_stocks_list) & set(stock_list))
    ind_df = pd.DataFrame(np.zeros([len(stock_list),len(ind_stks_dict.keys())]), 
                          columns=ind_stks_dict.keys(), 
                          index=stock_list)
    def func(x):  
        col = x.name
        stk_list_ = ind_stks_dict[x.name]
        x[stk_list_] = 1
        #print(x[stk_list_])
        return x
    ind_df = ind_df.apply(lambda x: func(x), axis=0)
    #print(len(ind_df))
    #print(len(Series))
    x = ind_df.values
    y = Series.values
    X = sm.add_constant(x) # 添加常数项
    model = sm.OLS(y,X)
    results = model.fit()
    params_ = results.params
    alpha = params_[0]
    beta = params_[1:]
    res =  y - (alpha + np.dot(x,beta)) # 残差
    Series.iloc[:] = res
    return Series    
 
 
 
 # peg因子
def get_peg(stock_list, end_date):
    q = query(
    #valuation.market_cap,
    valuation.code,
    valuation.pe_ratio,
    indicator.inc_net_profit_year_on_year,
    ).filter(
      valuation.code.in_(stock_list),
      valuation.pe_ratio > 0,
      indicator.inc_net_profit_year_on_year > 0,
      #valuation.pe_ratio > 0,
      #valuation.pb_ratio > 0,
    )
    
    df = get_fundamentals(q, date=end_date)
    df = df.set_index(['code'])
    df['peg'] = 1.0 * df['pe_ratio'] / df['inc_net_profit_year_on_year']
    Series = __error_drop(df['peg'])
    Series = __mkt_cap_ind_neu(Series, end_date)
    Series = __ind_neu(Series, end_date)
    new_Series = Series.copy()
    new_Series.sort(ascending=True, inplace=True)
    new_Series = new_Series.iloc[:int(0.2*len(new_Series))]
    print(new_Series)
    return new_Series

# 一次最多返回3000条，对股票列表拆分
def __get_stk_list_split(stock_list, split_n):
    new_stock_list = []
    for i in range(0,len(stock_list)):
        if split_n*(i+1) >= len(stock_list):
            new_stock_list.append(stock_list[split_n*i:])
            break
        new_stock_list.append(stock_list[split_n*i:split_n*(i+1)])
    return new_stock_list




    
# 获取多日多股票换手率的df,split_stk_list格式:[[stk1,stk2],[stk3,stk4]]
def __get_turnover_ratio(count_days, split_stk_list, end_date):
    new_df = pd.DataFrame()
    for stk_list_temp in split_stk_list:
        q = query(
              valuation.turnover_ratio,
          ).filter(
              valuation.code.in_(stk_list_temp),
          )

        df = get_fundamentals_continuously(q, end_date=end_date, count=count_days)['turnover_ratio'].dropna(axis=1).T

        new_df = pd.concat([new_df,df],axis=0).dropna(axis=0)
    return new_df


# 换手率相对波动率    
def get_hsl_std(stock_list, end_date):
    count_days = 20
    split_stk_list = __get_stk_list_split(stock_list, 3000 // count_days) # 拆分后的股票列表
    new_df = __get_turnover_ratio(count_days, split_stk_list, end_date)
    Series = new_df.std(axis=1)
    #Series = self.__error_drop(Series)
    Series = Series[Series > 0]
    Series = __mkt_cap_ind_neu(Series, end_date)
    Series = __ind_neu(Series, end_date)
    new_Series = Series.copy()
    new_Series.sort(ascending=True, inplace=True)
    new_Series = new_Series.iloc[:int(0.5*len(new_Series))]
    new_Series.name = 'hsl_std'
    print(new_Series)
    return new_Series



#1-2 选股模块
def get_stock_list(context):
    yesterday = context.previous_date   
    initial_list = get_all_securities(types=['stock'], date=yesterday).index.tolist()
    initial_list = filter_new_stock(context,initial_list)
    initial_list = filter_kcb_stock(context, initial_list)
    initial_list = filter_st_stock(initial_list)
 
    
    #PEG
    peg_Series = get_peg(initial_list, yesterday)
    hsl_std_Series = get_hsl_std(peg_Series.index.tolist(), yesterday)
    q = query(valuation.code,valuation.circulating_market_cap,indicator.eps).filter(valuation.code.in_(hsl_std_Series.index.tolist())).order_by(valuation.circulating_market_cap.asc())
    df = get_fundamentals(q, date=yesterday)
    peg_list = list(df.code)

    return peg_list


#1-3 准备股票池
def prepare_stock_list(context):
    # 1...2
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
        df = get_price(g.hold_list, end_date=context.previous_date, frequency='daily', fields=['close','high_limit'], count=1)
        close_df = df['close']
        high_limit_df = df['high_limit']
        diff_df = close_df - high_limit_df
        diff_df = diff_df[diff_df == 0].dropna(axis=1)
        g.high_limit_list = list(diff_df)
        
    else:
        g.high_limit_list = []


#1-5 整体调整持仓
def weekly_adjustment(context):
    yes_day = context.previous_date
    #1 #获取应买入列表 
    peg_list = get_stock_list(context)[:10]

    q = query(valuation.code,valuation.circulating_market_cap).filter(valuation.code.in_(peg_list)).order_by(valuation.circulating_market_cap.asc())
    df = get_fundamentals(q, yes_day)
    g.target_list = list(df.code) #...2
    g.target_list = filter_paused_stock(g.target_list)
    g.target_list = filter_limitup_stock(context, g.target_list)
    g.target_list = filter_limitdown_stock(context, g.target_list)
    #过滤最近买过且涨停过的股票
    recent_limit_up_list = get_recent_limit_up_stock(g.target_list, yes_day, g.limit_days)
    black_list = list(set(g.not_buy_again_list).intersection(set(recent_limit_up_list)))
    g.target_list = [stock for stock in g.target_list if stock not in black_list]
    #截取不超过最大持仓数的股票量
    g.target_list0 = g.target_list[:min(g.stock_num, len(g.target_list))]
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
    target_num = len(g.target_list0)
    if target_num > position_count:
        value = context.portfolio.cash / (target_num - position_count)
        for stock in g.target_list:
            if context.portfolio.positions[stock].total_amount == 0:
                if open_position(stock, value):
                    if len(context.portfolio.positions) == target_num:
                        break


#1-6 调整昨日涨停股票
def check_limit_up(context):
    now_time = context.current_dt
    if g.high_limit_list != []:
        #对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
        current_data = get_current_data()
        for stock in g.high_limit_list:
            if current_data[stock].last_price < current_data[stock].high_limit:
                log.info("[%s]涨停打开，卖出" % (stock))
                position = context.portfolio.positions[stock]
                close_position(position)
            else:
                log.info("[%s]涨停，继续持有" % (stock))

#1-2 行业过滤函数
def get_stock_industry(securities, watch_date, level='sw_l1', method='industry_name'): 
    industry_dict = get_industry(securities, watch_date)
    industry_ser = pd.Series({k: v.get(level, {method: np.nan})[method] for k, v in industry_dict.items()})
    industry_df = industry_ser.to_frame('industry')
    return industry_df

def filter_industry(industry_df, select_industry, level='sw_l1', method='industry_name'):
    filter_df = industry_df.query('industry != @select_industry')
    filter_list = filter_df.index.tolist()
    return filter_list


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
def get_recent_limit_up_stock(stock_list, end_date, recent_days):
    panel = get_price(stock_list, end_date=end_date, frequency='daily',fields=['close','high_limit'], count=recent_days+1)
    if_high_limit = panel['high_limit'].iloc[-recent_days:]
    close_price = panel['close'].iloc[-recent_days:]
    diff_df = if_high_limit - close_price
    diff_df =(diff_df == 0).sum(axis=0)
    diff_df = diff_df[diff_df > 0]
    del panel
    return diff_df.index.tolist()

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
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=375)]

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

#3-4 交易模块-调仓
def adjust_position(context, buy_stocks, stock_num):
	for stock in context.portfolio.positions:
		if stock not in buy_stocks:
			log.info("[%s]不在应买入列表中" % (stock))
			position = context.portfolio.positions[stock]
			close_position(position)
		else:
			log.info("[%s]已经持有无需重复买入" % (stock))

	position_count = len(context.portfolio.positions)
	if stock_num > position_count:
		value = context.portfolio.cash / (stock_num - position_count)
		for stock in buy_stocks:
			if context.portfolio.positions[stock].total_amount == 0:
				if open_position(stock, value):
					if len(context.portfolio.positions) == g.stock_num:
						break



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
    print('———————————————————————————————————————分割线———————')
