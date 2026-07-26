# 克隆自聚宽文章：https://www.joinquant.com/post/46218
# 标题：（乱改一版）股票加“钱粮”ETF组合
# 作者：美吉姆优秀毕业代表

# 克隆自聚宽文章：https://www.joinquant.com/post/46015
# 标题：“低风险，小市值+ETF轮动策略”修改版，略有改善
# 作者：请叫我大大白

# 克隆自聚宽文章：https://www.joinquant.com/post/45931
# 标题：低风险，小市值+ETF轮动策略
# 作者：无逻辑的光

from jqdata import *
from jqfactor import get_factor_values
import numpy as np
import pandas as pd
from scipy.optimize import minimize  

def initialize(context):
    # 设定基准
    set_benchmark('000906.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0.002))
    # 设置交易成本万分之三，不同滑点影响可在归因分析中查看
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),type='stock')
    # 过滤order中低于error级别的日志
    log.set_level('system', 'error')
    #初始化全局变量
    g.stock_num = 10
    g.etf = []
    g.commodity_etf = [
             '162411.XSHE', #华宝油气
             '518880.XSHG', #黄金ETF
            #  '511010.XSHG', #国债ETF
             '159985.XSHE', #豆粕ETF
            ]
            
    g.qdii_etf = []
    
    g.no_trading_today_signal = False
    
    g.limit_up_list = []
    g.hold_list = []
    g.stock_rate = 0.4  #中国股票股票仓位
    g.qdii_rate = 0.3   #外国股票组合仓位
    g.risk_management = -0.0382
    
# 设置交易运行时间
    run_daily(prepare_stock_list, '9:05')
    
    run_monthly(Trader_stocks,1, '9:35')
    # run_weekly(Trader_stocks,1, '9:35')
    
    run_monthly(Trader_etf,1,time='14:55')
    # run_weekly(Trader_etf,1,time='14:55')
    
    run_daily(rec,time='15:01')

    run_daily(check_limit_up, '14:00') #检查持仓中的涨停股是否需要卖出
    run_daily(close_account, '14:30')
    #run_daily(print_position_info, '15:10')
    
    run_daily(risk_management, '13:00')
    #run_daily(print_position_info, '15:10')
    
# 盘中浮亏止损
def risk_management(context):
    # 获取前n个单位时间当时的收盘价
    def get_close_price(code, n, unit='1d'):
        return attribute_history(code, n, unit, 'close', df=False)['close'][0]

    for stock in context.portfolio.positions.keys():
        # 计算个股即时的浮动盈亏
        fuying =  context.portfolio.positions[stock].price/ context.portfolio.positions[stock].avg_cost-1
        current_data = get_current_data()
        price1d = get_close_price(stock, 1)
        nosell_1 = context.portfolio.positions[stock].price >= current_data[stock].high_limit
        # 浮动亏6.5个百分点卖出
        if fuying < g.risk_management and not nosell_1:
            position = context.portfolio.positions[stock]
            # close_position(context,stock)
            close_position(position)
            print('盘中止损%s'%current_data[stock].name)
    

def Trader_etf(context):
    #today = context.current_dt
    #if today.month in [1,4,7,10]:
    total_value = context.portfolio.total_value
    #stock_Trader(context,total_value*0.1)
    commodity_etf_trade(context,total_value*(1-g.stock_rate-g.qdii_rate))
    qdii_etf_trade(context,total_value*(g.qdii_rate))
    
def commodity_etf_trade(context,total_value):
    print('商品etf可用资金 %s'%int(total_value))
    # 计算商品etf权重
    end_date = context.previous_date
    if end_date.year < 2020:
        g.commodity_etf = [
             '162411.XSHE', #华宝油气
             '518880.XSHG', #黄金ETF
             '511010.XSHG', #国债ETF
            #  '159985.XSHE', #豆粕ETF
            ]
    else:
        g.commodity_etf = [
             '162411.XSHE', #华宝油气
             '518880.XSHG', #黄金ETF
            #  '511010.XSHG', #国债ETF
             '159985.XSHE', #豆粕ETF
            ]
    weights = run_optimization(g.commodity_etf, end_date)

    # print("commodity_etf weights",weights)
    record(commodity_etf = len(g.commodity_etf))
    if weights is None:
        return
    index = 0
    for w in weights:
        value = total_value * w # 确定每个标的的权重
        order_target_value(g.commodity_etf[index], value) # 调整标的至目标权重
        print(g.commodity_etf[index], value)
        index+=1
    
def qdii_etf_trade(context,total_value):
    end_date = context.previous_date    
    print('qdii_etf可用资金 %s'%int(total_value))
    # 计算qdii etf权重    
    g.qdii_etf = filter_DQII_etf(context)
    g.qdii_etf = g.qdii_etf[:10]
    record(qdii_etf = len(g.qdii_etf))
    print('qdii_etf 有 %s 个'%len(g.qdii_etf))
    weights = run_optimization(g.qdii_etf, end_date)
    # print("qdii_etf weights",weights)
    if weights is None:
        return
    index = 0
    for w in weights:
        value = total_value * w # 确定每个标的的权重
        order_target_value(g.qdii_etf[index], value) # 调整标的至目标权重
        print(g.qdii_etf[index], value)
        index+=1

#1-4 整体调整持仓
def Trader_stocks(context):
    if g.no_trading_today_signal == False:
        #获取应买入列表
        today = context.current_dt
        if today.month in [1,4]:#,7,10
            target_list_small_cap = []

        else:
            target_list_small_cap = get_stock_list(context)   #选小市值股
            target_list_small_cap = target_list_small_cap[0:g.stock_num]

        target_list_Dividend_stock = choice_try_A(context)  #选红利股
        target_list_Dividend_stock = target_list_Dividend_stock[0:g.stock_num]
        target_list = list(set(target_list_small_cap + target_list_Dividend_stock)) #10或20
        print('选出股票 %s 只'%len(target_list))
        record(股票数 = len(target_list))
        #调仓卖出
        for stock in g.hold_list:
            if (stock not in target_list) and (stock not in g.high_limit_list) and (stock not in g.etf):
                log.info("卖出[%s]" % (stock))
                position = context.portfolio.positions[stock]
                close_position(position)
            else:
                log.info("已持有[%s]" % (stock))
        #调仓买入
        # position_count = len(context.portfolio.positions)   #持股数
        # target_num = len(target_list)   #待买列表
        # if target_num > (position_count-len(g.qdii_etf)-len(g.commodity_etf)):
        #     #value = context.portfolio.cash / (target_num - position_count+len(g.etf))
        #     value = min(context.portfolio.cash,context.portfolio.total_value*g.stock_rate) / (target_num - position_count + len(g.qdii_etf) + len(g.commodity_etf))
        #     for stock in target_list:
        #         if context.portfolio.positions[stock].total_amount == 0:
        #             if open_position(stock, value):
        #                 if len(context.portfolio.positions) == target_num + len(g.qdii_etf) + len(g.commodity_etf):
        #                     break
        g.etf = set(g.qdii_etf + g.commodity_etf)
        #调仓买入
        # position_count = len(context.portfolio.positions)
        # target_num = len(target_list)
        # if target_num > (position_count-len(g.etf)):
        #     #value = context.portfolio.cash / (target_num - position_count+len(g.etf))
        #     value = min(context.portfolio.cash,context.portfolio.total_value*g.stock_rate) / (target_num - position_count+len(g.etf))
        #     for stock in target_list:
        #         if context.portfolio.positions[stock].total_amount == 0:
        #             if value > 1000:
        #                 if open_position(stock, value):
        #                     if len(context.portfolio.positions) == target_num+len(g.etf):
        #                         break
        # 获取当前投资组合中的仓位数量
        position_count = len(context.portfolio.positions)
        hold_stock_num = position_count-len(g.etf)
        free_stock_position = position_count-hold_stock_num
        # 获取目标列表中的股票数量
        target_num = len(target_list)
        # 检查目标列表中的股票数量是否大于当前的仓位数量减去ETF的数量
        if target_num > hold_stock_num:
            # 计算每只股票的投资金额，金额为现金和总价值乘以一定系数的较小值，除以需要买入的股票数量
            value = min(context.portfolio.cash,context.portfolio.total_value*g.stock_rate) / free_stock_position #20-19+10
            # 遍历目标列表中的每一支股票
            for stock in target_list:
                # 检查当前投资组合是否没有持有该股票
                if context.portfolio.positions[stock].total_amount == 0:
                    # 检查预计投资金额是否超过了1000元
                    if value > 1000:
                        # 如果上述条件都满足，尝试开仓
                        if open_position(stock, value):
                            # 检查当前组合仓位数是否达到了目标数量（包括ETF数量），如果达到则停止买入
                            if len(context.portfolio.positions) == target_num+len(g.etf):
                                break
                    else:
                        break

def filter_DQII_etf(context):

    lofs = get_all_securities(['etf'])
    lofs = lofs[lofs['start_date'] < context.previous_date]
    lofs = lofs[lofs['end_date'] > context.current_dt.date()]
    lofs = lofs.index.tolist()

    current_data = get_current_data()   #获取日期
    lofs =  [stock for stock in lofs 
        if (
            '德' in current_data[stock].name or 
           '纳' in current_data[stock].name or 
           '法' in current_data[stock].name or 
           'DAX' in current_data[stock].name or 
           '标' in current_data[stock].name or 
           '英' in current_data[stock].name or 
           '日' in current_data[stock].name or 
           '印' in current_data[stock].name or 
           '越' in current_data[stock].name or 
           '225' in current_data[stock].name
           ) and 
           '中' not in current_data[stock].name and 
           '企' not in current_data[stock].name
           ] 
            
    # 基金净值
    net_value=get_extras('unit_net_value', lofs, end_date=context.previous_date, df=True, count=1).T
    net_value.columns=['unit_net_value']
    # 基金价格
    close=history(count=1, unit='1d', field="close", security_list=lofs).T
    volume=history(count=1, unit='1d', field="volume", security_list=lofs).T

    # print(volume)
    volume = volume[volume>1000000] #日成交额大于100万
    
    close = close[close.index.isin(volume.index)]
    
    close.columns=['close']
    # score = 价格/净值
    val=net_value.join(close)
    val['score'] = val['close'] / val['unit_net_value']
    # 过滤
    val = val[(val['score'] > 0)]
    val = val[(val['score'] < 1.1)] #溢价太多不要
    # 排序
    val = val.sort_values(by='score', ascending = False)    #溢价越多越买，气死你
    buy_list = val.index.tolist()
    
    return buy_list
    
    
# 计算投资组合方差的函数
def portfolio_variance(weights, cov_matrix):  # 定义投资组合方差函数
    return np.dot(weights.T, np.dot(cov_matrix* 250, weights))  # 计算并返回投资组合方差

# 优化投资组合的函数
def optimize_portfolio(returns):  # 定义优化投资组合函数
    # 计算协方差矩阵
    cov_matrix = returns.cov()  # 计算收益的协方差矩阵
    # 投资组合中的资产数量
    num_assets = len(returns.columns)  # 计算投资组合中的资产数量
    w_min = 1/(np.power(num_assets,2))
    w_max = 0.9

    # 初始权重（平均分配）
    init_weights = np.array([1/num_assets] * num_assets)  # 设置初始权重
    # 约束条件
    weight_sum_constraint = {'type': 'eq', 'fun': lambda weights: np.sum(weights) - 1}  # 权重和约束
    #bounds = [(0, 1) for _ in range(num_assets)]  # 权重范围约束
    bnds = tuple((w_min,w_max) for x in range(num_assets))
    # 优化
    result = minimize(portfolio_variance, init_weights,method='SLSQP', args=(cov_matrix), bounds=bnds, constraints=weight_sum_constraint)  
    return result.x  # 返回优化结果

# 定义获取数据并调用优化函数的函数
def run_optimization(stocks, end_date):
    prices = get_price(stocks, count=250, end_date=end_date, frequency='daily', fields=['close'])['close']
    returns = prices.pct_change().dropna() # 计算收益率
    weights = optimize_portfolio(returns)
    return weights




#1-1 选股模块
def get_factor_filter_list(context,stock_list,jqfactor,sort,p1,p2):
    yesterday = context.previous_date
    score_list = get_factor_values(stock_list, jqfactor, end_date=yesterday, count=1)[jqfactor].iloc[0].tolist()
    df = pd.DataFrame(columns=['code','score'])
    df['code'] = stock_list
    df['score'] = score_list
    df = df.dropna()
    df.sort_values(by='score', ascending=sort, inplace=True)
    filter_list = list(df.code)[int(p1*len(df)):int(p2*len(df))]
    return filter_list

#1-2 选股模块
def get_stock_list(context):
    yesterday = context.previous_date
    initial_list = get_all_securities().index.tolist()
    initial_list = filter_new_stock(context, initial_list)
    initial_list = filter_kcbj_stock(initial_list)
    initial_list = filter_st_stock(initial_list)
    initial_list = filter_paused_stock(initial_list)
    initial_list = filter_limitup_stock(context, initial_list)
    initial_list = filter_limitdown_stock(context, initial_list)
    #用两种方法获取的昨日收盘价回测效果相差不大
    #用因子获得昨日收盘价
    # price_list1 = get_factor_filter_list(context, initial_list, 'size', True, 0, 0.1)
    price_list1 = get_factor_filter_list(context, initial_list, 'price_no_fq', True, 0, 0.1)
    #用get_price获得昨日收盘价
    df = get_price(initial_list, start_date=yesterday, end_date=yesterday, fields=['close'], fq='pre', panel=False)
    df = df.sort_values(by='close', ascending=True)
    price_list2 = list(df.code)[int(0*len(df)):int(0.1*len(df))]
    #流通市值轮动(这里选择了用因子获取的价格)
    q = query(valuation.code,valuation.circulating_market_cap,indicator.eps).filter(valuation.code.in_(price_list1)).order_by(valuation.circulating_market_cap.asc())
    df = get_fundamentals(q, date=yesterday)
    df = df[df['eps']>0]
    final_list = list(df.code)[:15]
    return final_list

#1-3 准备股票池
def prepare_stock_list(context):
    #获取已持有列表
    g.hold_list= []
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

def choice_try_A(context,):
    
    yesterday = context.previous_date
    stocks = get_all_securities().index.tolist()
    stocks = filter_new_stock(context, stocks)
    stocks = filter_kcbj_stock(stocks)
    stocks = filter_st_stock(stocks)
    stocks = filter_paused_stock(stocks)
    stocks = filter_limitup_stock(context, stocks)
    stocks = filter_limitdown_stock(context, stocks)
    
    stocks = get_dividend_ratio_filter_list(context, stocks, False, 0, 0.10)    #股息率排序
    # 获取基本面数据
    df = get_fundamentals(query(
            valuation.code,
            valuation.circulating_market_cap,
        ).filter(
            valuation.code.in_(stocks),
            valuation.pe_ratio.between(0,25),#市盈率
            indicator.inc_return >3,#净资产收益率(扣除非经常损益)(%)
            indicator.inc_total_revenue_year_on_year>5,#营业总收入同比增长率(%)
            indicator.inc_net_profit_year_on_year>11,#净利润同比增长率。
            valuation.pe_ratio / indicator.inc_net_profit_year_on_year>0.08,#净利润同比增长率
            valuation.pe_ratio / indicator.inc_net_profit_year_on_year<1.9,
            ))
    stocks = list(df.code)
    # print("分红比率筛选后的股票有：{}".format(len(stocks)))
    return stocks

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

#2-3 过滤涨停的股票
def filter_limitup_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] < current_data[stock].high_limit]

#2-4 过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] > current_data[stock].low_limit]

#2-5 过滤科创北交股票
def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68':
            stock_list.remove(stock)
    return stock_list

#2-6 过滤次新股
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


#4-2 清仓后次日资金可转
def close_account(context):
    if g.no_trading_today_signal == True:
        if len(g.hold_list) != 0:
            for stock in g.hold_list:
                if stock not in g.etf:
                    position = context.portfolio.positions[stock]
                    close_position(position)
                    log.info("卖出[%s]" % (stock))

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
    
#2-1 过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]
    
#2-4 过滤涨停的股票
def filter_limitup_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] <    current_data[stock].high_limit]

#2-5 过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] > current_data[stock].low_limit]

def rec(context):
    _cent = context.portfolio.positions_value / context.portfolio.total_value
    _cent = int(_cent*10000)/10000
    formatted_cent = "{:.2%}".format(_cent)  # 格式化为百分比形式，保留两位小数
    log.info('当前仓位 %s' % formatted_cent)
    record(当前仓位=_cent*10)
    
    stock_list = context.portfolio.positions.keys()
    record(总持股数=len(stock_list))
    
    
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
