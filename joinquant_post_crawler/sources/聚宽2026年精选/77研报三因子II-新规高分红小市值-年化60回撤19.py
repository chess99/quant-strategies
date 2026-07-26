# 克隆自聚宽文章：https://www.joinquant.com/post/47618
# 标题：研报三因子II-新规高分红小市值-年化60回撤19
# 作者：xiaohui1108

#导入函数库
from jqdata import *
from jqfactor import *
import pandas as pd

#初始化函数 
def initialize(context):
    # 设定基准
    set_benchmark('399303.XSHE')
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
    g.stock_num = 10
    # 设置交易运行时间
    run_daily(prepare_stock_list, '9:05')
    run_weekly(weekly_adjustment, 1, '09:30')
    run_daily(check_limit_up, '14:30')
    run_daily(close_account, '14:30')


#1-1 准备股票池
def prepare_stock_list(context):
    # 获取已持有列表
    g.hold_list = list(context.portfolio.positions)
    # 获取持仓中涨停列表
    g.high_limit_list = []
    if g.hold_list:
        g.high_limit_list = get_price(g.hold_list, end_date=context.previous_date, count=1,fields=['close', 'high_limit', 'paused'], panel=False
                                      ).query('close==high_limit')['code'].tolist()
    # 判断今天是否为账户资金再平衡的日期
    g.no_trading_today_signal = today_is_between(context, '04-08', '04-30')
    
#1-1 选股模块
def get_factor_filter_list(context,stock_list,jqfactor,sort,p1,p2):
    yesterday = context.previous_date
    score_list = get_factor_values(stock_list, jqfactor, end_date=yesterday, count=1)[jqfactor].iloc[0].tolist()
    df = pd.DataFrame(columns=['code','score'])
    df['code'] = stock_list
    df['score'] = score_list
    df = df.dropna()
    df.sort_values(by='score', ascending=sort, inplace=True)
    filter_list = list(df.code)[int(p1*len(stock_list)):int(p2*len(stock_list))]
    return filter_list

#1-2 选股模块
def get_stock_list(context):
    yesterday = str(context.previous_date)    
    initial_list = get_all_securities().index.tolist()
    initial_list = filter_new_stock(context, initial_list, 375)
    initial_list = filter_kcbj_stock(initial_list)
    initial_list = filter_st_stock(initial_list)
    #高分红
    de_list = get_dividend_ratio_filter_list(context, initial_list, False, 0, 0.1)
    q = query(valuation.code).filter(valuation.code.in_(de_list),indicator.eps > 0).order_by(valuation.market_cap.asc())
    df = get_fundamentals(q, date=yesterday)
    de_list = list(df.code)
    #高pe
    q = query(valuation.code).filter(valuation.code.in_(initial_list),indicator.eps > 0,).order_by(valuation.pe_ratio.desc())
    df = get_fundamentals(q, date=yesterday)
    ml_list = list(df.code)[:int(len(initial_list)*0.1)]
    q = query(valuation.code).filter(valuation.code.in_(ml_list)).order_by(valuation.market_cap.asc())
    df = get_fundamentals(q, date=yesterday)
    ml_list = list(df.code)
    #高增长率
    sg_list = get_factor_filter_list(context, initial_list, 'sales_growth', False, 0, 0.1)
    q = query(valuation.code).filter(valuation.code.in_(sg_list),indicator.eps > 0,).order_by(valuation.market_cap.asc())
    df = get_fundamentals(q, date=yesterday)
    sg_list = list(df.code)

    final_list = [de_list, ml_list, sg_list]
    return final_list


#1-5 整体调整持仓
def weekly_adjustment(context):
    if g.no_trading_today_signal:
        print("四月空仓")
        return
    #获取应买入列表 
    all_list = get_stock_list(context)
    de_list = all_list[0][:int(g.stock_num*0.6)]
    ml_list = all_list[1][:int(g.stock_num*0.6)]
    ne_list = all_list[2][:int(g.stock_num*0.6)]
    union_list = list(set(de_list).union(set(ml_list)).union(set(ne_list)))
    df = get_fundamentals(query(valuation.code,valuation.circulating_market_cap).filter(valuation.code.in_(union_list)).order_by(valuation.market_cap.asc()))
    target_list = list(df.code)
    target_list = filter_paused_stock(target_list)
    target_list = filter_limitup_stock(context, target_list)
    target_list = filter_limitdown_stock(context, target_list)
    #截取不超过最大持仓数的股票量
    target_list = target_list[:min(g.stock_num, len(target_list))]
    #调仓卖出
    for stock in g.hold_list:
        if (stock not in target_list) and (stock not in g.high_limit_list):
            log.info("卖出[%s]" % (stock))
            order_target_value(stock, 0)
        else:
            log.info("已持有[%s]" % (stock))
    #调仓买入
    position_count = len(context.portfolio.positions)
    target_num = len(target_list)
    if target_num > position_count:
        value = context.portfolio.cash / (target_num - position_count)
        for stock in target_list:
            if context.portfolio.positions[stock].total_amount == 0:
                order_target_value(stock, value)
                log.info("买入[%s]" % (stock))
                if len(context.portfolio.positions) == target_num:
                    break


#1-6 调整昨日涨停股票
def check_limit_up(context):
    current_data = get_current_data()
    if g.high_limit_list:
        #对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
        for stock in g.high_limit_list:
            if current_data[stock].last_price < current_data[stock].high_limit:
                log.info("涨停打开，卖出：{}".format((stock)))
                order_target_value(stock, 0)
            else:
                log.info("涨停，继续持有：{}".format((stock)))
                print('—'*50)

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
    #dividend = dividend.set_index('code')
    #print(dividend)
    dividend = dividend.groupby('code').sum()
    #print(dividend)
    temp_list = list(dividend.index) #query查询不到无分红信息的股票，所以temp_list长度会小于stock_list
    #获取市值相关数据
    q = query(valuation.code,valuation.market_cap).filter(valuation.code.in_(temp_list))
    cap = get_fundamentals(q, date=time1)
    cap = cap.set_index('code')
    #计算股息率
    DR = pd.concat([dividend, cap] ,axis=1)
    DR['dividend_ratio'] = (DR['bonus_amount_rmb']/10000) / DR['market_cap']
    #排序并筛选
    DR = DR.sort_values(by='dividend_ratio', ascending=sort)
    final_list = list(DR.index)[int(p1*len(DR)):int(p2*len(DR))]
    return final_list

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

#4-1 判断今天是否为账户资金再平衡的日期
def today_is_between(context, start_date, end_date):
    today = context.current_dt.strftime('%m-%d')
    if (start_date <= today) and (today <= end_date):
        return True
    else:
        return False

#4-2 清仓后次日资金可转
def close_account(context):
    if g.no_trading_today_signal == True:
        if len(g.hold_list) != 0:
            for stock in g.hold_list:
                order_target_value(stock, 0)
                log.info("卖出[%s]" % (stock))

# end
