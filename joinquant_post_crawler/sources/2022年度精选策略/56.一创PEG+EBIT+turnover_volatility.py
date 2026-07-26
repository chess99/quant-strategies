# 克隆自聚宽文章：https://www.joinquant.com/post/39698
# 标题：一创PEG+EBIT+turnover_volatility
# 作者：tianguong

#导入函数库
from jqdata import *
import numpy as np
import pandas as pd

#初始化函数 
def initialize(context):
    set_benchmark('000905.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 设置交易成本万分之三
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),type='fund')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    #选股数目
    g.stock_num = 5 
    # 设置交易时间，每天运行
    run_weekly(blue_chip_small_cap, weekday=1, time='9:30', reference_security='000300.XSHG')


# PEG、EBIT过滤，小市值选股
def get_stock_list(context):
    initial_list = get_all_securities().index.tolist()
    initial_list = filter_new_stock(context,initial_list)
    initial_list = filter_kcb_stock(context, initial_list)
    initial_list = filter_st_stock(initial_list)

    peg_list = get_inc_net_profit_ttm(context, initial_list, 0.1)
    ebit_list = get_EBIT(context, peg_list, 0.25)
    test_list = get_turnover_volatility(context, ebit_list, 0.5)
    q = query(valuation.code,valuation.circulating_market_cap).filter(valuation.code.in_(test_list)).order_by(valuation.circulating_market_cap.asc())
    df = get_fundamentals(q)
    final_list = list(df.code)
    return final_list


#过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]

#过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list
            if not current_data[stock].is_st
            and 'ST' not in current_data[stock].name
            and '*' not in current_data[stock].name
            and '退' not in current_data[stock].name]

#过滤涨停的股票
def filter_limitup_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    # 已存在于持仓的股票即使涨停也不过滤，避免此股票再次可买，但因被过滤而导致选择别的股票
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] < current_data[stock].high_limit]

#过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] > current_data[stock].low_limit]

#过滤科创板
def filter_kcb_stock(context, stock_list):
    return [stock for stock in stock_list  if stock[0:3] != '688']

#过滤次新股
def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=250)]

#下单交易
def order_target_value_(security, value):
    if value == 0:
        log.debug("卖出 %s" % (security))
    else:
        log.debug("调整 %s 市值到 %f" % (security, value))
    # 如果股票停牌，创建报单会失败，order_target_value 返回None
    # 如果股票涨跌停，创建报单会成功，order_target_value 返回Order，但是报单会取消
    # 部成部撤的报单，聚宽状态是已撤，此时成交量>0，可通过成交量判断是否有成交
    return order_target_value(security, value)

#开仓买入
def open_position(security, value):
    order = order_target_value_(security, value)
    if order != None and order.filled > 0:
        return True
    return False

#平仓卖出
def close_position(position):
    security = position.security
    order = order_target_value_(security, 0)  # 可能会因停牌失败
    if order != None:
        if order.status == OrderStatus.held and order.filled == order.amount:
            return True
    return False

#调整仓位
def adjust_position(context, buy_stocks):
    for stock in context.portfolio.positions:
        if stock not in buy_stocks:
            position = context.portfolio.positions[stock]
            close_position(position)
    # 根据可用金额平均分配购买，不能保证每个仓位平均分配
    position_count = len(context.portfolio.positions)
    if g.stock_num > position_count:
        value = context.portfolio.cash / (g.stock_num - position_count)
        for stock in buy_stocks:
            if context.portfolio.positions[stock].total_amount == 0:
                if open_position(stock, value):
                    if len(context.portfolio.positions) == g.stock_num:
                        break

#绩优小市值策略
def blue_chip_small_cap(context):
    #获取选股列表并过滤掉:st,st*,退市,涨停,跌停,停牌
    check_out_list = get_stock_list(context)
    check_out_list = filter_limitup_stock(context, check_out_list)
    check_out_list = filter_limitdown_stock(context, check_out_list)
    check_out_list = filter_paused_stock(check_out_list)
    check_out_list = check_out_list[:g.stock_num]
    print('入选股票:{}'.format(check_out_list))
    adjust_position(context, check_out_list)



def get_inc_net_profit_ttm(context, stock_list, p):
    date_list = get_quarters(context)
    q = query(
        valuation.code,
        valuation.pe_ratio,
        valuation.circulating_market_cap
    ).filter(
        valuation.code.in_(stock_list)
    )
    df = get_fundamentals(q)
    df = df.set_index('code', drop=False)

    stock_list = df.code
    for qdate in date_list:
        q = query(
            valuation.code,
            income.np_parent_company_owners,
        ).filter(
            valuation.code.in_(stock_list)
        )
        df1 = get_fundamentals(q, statDate=qdate)
        df1 = df1.set_index('code', drop=False)
        df[qdate] = df1['np_parent_company_owners']

    df = df.dropna(axis=0, how="any")
    df['inc_net_profit_ttm'] = df[date_list[4:]].sum(axis=1)/df[date_list[:4]].sum(axis=1) - 1
    df['peg1'] = df['pe_ratio']/(df['inc_net_profit_ttm']*100)
    df = df[df['peg1']>0]
    df.sort_values(by='peg1', ascending=True, inplace=True)
    # df.sort('peg1', ascending=True, inplace=True)
    filter_list = list(df.code)[0:int(p*len(stock_list))]
    return filter_list


def get_quarters(context):
    pdate = str(context.previous_date)
    year = int(pdate[:4])
    month_and_day = pdate[5:10]

    statDate_list = []
    if month_and_day < '05-01':
        statDate_list = [str(year-3)+'q4',str(year-2)+'q1',str(year-2)+'q2',str(year-2)+'q3', 
                        str(year-2)+'q4', str(year-1)+'q1', str(year-1)+'q2', str(year-1)+'q3']
    elif month_and_day >= '05-01' and month_and_day < '09-01':
        statDate_list = [str(year-2)+'q2',str(year-2)+'q3',str(year-2)+'q4', str(year-1)+'q1', 
                        str(year-1)+'q2',str(year-1)+'q3', str(year-1)+'q4', str(year)+'q1']
    elif month_and_day >= '09-01' and month_and_day < '11-01':
        statDate_list = [str(year-2)+'q3', str(year-2)+'q4', str(year-1)+'q1', str(year-1)+'q2', 
                        str(year-1)+'q3', str(year-1)+'q4', str(year)+'q1', str(year)+'q2']
    elif month_and_day >= '11-01':
        statDate_list = [str(year-2)+'q4', str(year-1)+'q1', str(year-1)+'q2', str(year-1)+'q3', 
                        str(year-1)+'q4', str(year)+'q1', str(year)+'q2', str(year)+'q3']
    return statDate_list



# EBIT
def get_EBIT(context, stock_list, p):
    q = query(
        valuation.code,
        income.net_profit,
        income.income_tax_expense,
        income.financial_expense
    ).filter(
        valuation.code.in_(stock_list)
    )
    df = get_fundamentals(q)
    df = df.set_index('code', drop=False)

    df = df.dropna(axis=0, how="any")
    df['EBIT1'] = df['net_profit']+df['income_tax_expense']+df['financial_expense']
    df = df[df['EBIT1']>0]
    df.sort_values(by='EBIT1', ascending=True, inplace=True)
    # df.sort('EBIT1', ascending=True, inplace=True)
    filter_list = list(df.code)[0:int(p*len(stock_list))]
    return filter_list


# 换手率方差
def get_turnover_volatility(context, stock_list, p):
    days=20
    total_count = len(stock_list)
    max_query = int(5000/days - 1)
    n = 1
    df_all = pd.DataFrame()
    while (n-1)*max_query < total_count:
        stocks = []
        if n*max_query > total_count:
            stocks = stock_list[(n-1)*max_query:]
        else:
            stocks = stock_list[(n-1)*max_query:n*max_query]
        q = query(
            valuation.code,
            valuation.turnover_ratio
        ).filter(
            valuation.code.in_(stocks)
        )
        df = get_fundamentals_continuously(q, end_date=context.previous_date, count=days).turnover_ratio.T
        df['turnover_volatility'] = df.std(axis=1)/100
        df_all = df_all.append(df)
        n = n+1
    df_all = df_all.dropna(axis=0, how="any")
    df_all = df_all[df_all['turnover_volatility']>0]
    df.sort_values(by='turnover_volatility', ascending=True, inplace=True)
    # df_all.sort('turnover_volatility', ascending=True, inplace=True)
    filter_list = list(df_all.index)[0:int(p*len(stock_list))]
    return filter_list
