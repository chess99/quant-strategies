# 克隆自聚宽文章：https://www.joinquant.com/post/29535
# 标题：北上资金持股比选股策略（北向/港资/外资）
# 作者：逆熵者

# 导入函数库
import pandas as pd
from jqdata import *

# 初始化函数
def initialize(context):
    # 设置基准
    g.benchmark = '000300.XSHG'
    set_benchmark(g.benchmark)
    # 使用真实价格并避免未来数据
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)

# 为方便修改将变量置于此函数中
def after_code_changed(context):
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.00025, close_commission=0.00025, min_commission=5), type='stock')
    # set_order_cost(OrderCost(close_tax=0.0, open_commission=0.0, close_commission=0.0, min_commission=0), type='stock')
    # 设置基础股票池
    g.universe_index = '000902.XSHG'
    # 最大持股数量
    g.max_hold_stocknum = 10
    # 可以继续持股的排名
    g.check_out_ranking = 30
    # 个股最大最小仓位比例限制
    g.security_max_proportion = 0.20
    g.security_min_proportion = 0.05
    # 卖出后10交易日内不再买入
    g.n_tradeday_not_buy = 10
    # 初始化港资持股比例排名和已卖出股票列表
    g.prev_hk_hold_df = pd.DataFrame({})
    g.selled_security_dict = {}
    # run_weekly(main_func, 3, time='open', reference_security=g.benchmark)
    run_daily(main_func, time='open', reference_security=g.benchmark)
    run_daily(selled_security_list_count, time='after_close', reference_security=g.benchmark)

# 主函数
def main_func(context):
    prev_date = context.previous_date
    stock_list = get_index_stocks(g.universe_index)
    hk_hold_df = get_hk_hold_ratio(stock_list, end_date=prev_date, start_date=prev_date, sorted_by_circulation=False)
    # 查询结果为空时沿用上一次的有效查询结果
    if len(hk_hold_df) == 0:
        log.info('港资查询失败，沿用上次查询结果')
        hk_hold_df = g.prev_hk_hold_df
    else:
        g.prev_hk_hold_df = hk_hold_df
    hold_lists = list(hk_hold_df['code'])
    # 过滤ST停牌退市
    hold_lists = st_filter(context, hold_lists)
    hold_lists = paused_filter(context, hold_lists)
    hold_lists = delisted_filter(context, hold_lists)
    hold_lists = hold_lists[:g.check_out_ranking]
    trade(context, hold_lists, g.max_hold_stocknum, g.security_max_proportion, g.security_min_proportion)

## 卖出股票日期计数
def selled_security_list_count(context):
    selled_num = len(g.selled_security_dict)
    if selled_num > 0:
        log.info('累积清仓标的数：%s' % selled_num)
        for stock in g.selled_security_dict.keys():
            g.selled_security_dict[stock] += 1

## 交易函数
def trade(context, hold_lists, max_hold_stocknum, security_max_proportion=None, security_min_proportion=None):
    # 设置个股仓位限制默认值
    if security_max_proportion==None:
        security_max_proportion = (1 / max_hold_stocknum) * 2
    if security_min_proportion==None:
        security_min_proportion = (1 / max_hold_stocknum) / 2
    # 当前持仓股
    positions_lists = list(context.portfolio.positions.keys())
    keep_holding_lists = [stock for stock in hold_lists if stock in positions_lists][:max_hold_stocknum]
    new_entry_num = max_hold_stocknum - len(keep_holding_lists)
    new_entry_lists = [stock for stock in hold_lists if stock not in keep_holding_lists][:new_entry_num]
    buy_lists = list(set(keep_holding_lists + new_entry_lists))
    # 卖出不在目标列表中的股票
    sell_lists = [stock for stock in positions_lists if stock not in buy_lists]
    # 涨停或停牌不卖
    sell_lists = high_limit_filter(context, sell_lists)
    sell_lists = paused_filter(context, sell_lists)
    for stock in sell_lists:
        log.info('【卖出】%s' % stock)
        order_target_value(stock, 0)
    # 记入已卖出dict
    selled_security_list_dict(context, sell_lists)
    # 将持仓比例超过个股上限的股票减仓至上限的90%
    total_value = context.portfolio.total_value
    max_value = total_value * security_max_proportion
    min_value = total_value * security_min_proportion
    target_value = total_value / max_hold_stocknum
    positions_lists = list(context.portfolio.positions.keys())
    for stock in positions_lists:
        now_value = context.portfolio.positions[stock].value
        if now_value > max_value:
            log.info('【减仓】%s超过个股仓位上限，减仓' % stock)
            order_target_value(stock, 0.9 * max_value)
        if now_value < min_value:
            log.info('【补仓】%s低于个股仓位下限，补仓' % stock)
            order_target_value(stock, target_value)
    # 根据空闲仓位买入
    buy_orders_num = max_hold_stocknum - len(positions_lists)
    buy_orders = new_entry_lists[:buy_orders_num]
    # N日内卖出不买
    buy_orders = [stock for stock in buy_orders if filter_n_tradeday_not_buy(stock, g.n_tradeday_not_buy)]
    cash = context.portfolio.available_cash
    for stock in buy_orders:
        log.info('【买入】%s' % stock)
        order_target_value(stock, cash / buy_orders_num)
    
## 获取港资持股比例
def get_hk_hold_ratio(stock_list, end_date, start_date=None, count=None, sorted_by_circulation=False):
    # 北上资金持股比例（上证为占流通比例，深证为占总股本比例，需进行统一）
    trade_days = get_trade_days(start_date=start_date, end_date=end_date, count=count)
    q_hk_hold = query(
        finance.STK_HK_HOLD_INFO.day, 
        finance.STK_HK_HOLD_INFO.code, 
        finance.STK_HK_HOLD_INFO.name, 
        finance.STK_HK_HOLD_INFO.link_id, 
        finance.STK_HK_HOLD_INFO.share_ratio 
    ).filter(
        finance.STK_HK_HOLD_INFO.code.in_(stock_list), 
        finance.STK_HK_HOLD_INFO.link_id != '310005', #排除南下资金数据
        finance.STK_HK_HOLD_INFO.day.in_(trade_days)
    ).order_by(finance.STK_HK_HOLD_INFO.share_ratio.desc())
    df_hk_hold=finance.run_query(q_hk_hold)
    
    q_valuation = query(
        valuation.day, 
        valuation.code, 
        valuation.pe_ratio, 
        valuation.capitalization, 
        valuation.circulating_cap 
    ).filter(
        valuation.code.in_(stock_list), 
        valuation.day.in_(trade_days)
    ).order_by(valuation.day.desc())
    
    df_valuation=finance.run_query(q_valuation)
    df_valuation['circulation_ratio'] = df_valuation['circulating_cap'] / df_valuation['capitalization']
    df_valuation = df_valuation.drop(['circulating_cap', 'capitalization'], axis=1)

    result = pd.merge(df_hk_hold, df_valuation, on=['day', 'code'])
    result['market_share_ratio'] = result['share_ratio']
    result.loc[result['link_id']==310001, ['market_share_ratio']] = result['share_ratio'] * result['circulation_ratio']
    result['circulation_share_ratio'] = (result['market_share_ratio'] / result['circulation_ratio'])
    if sorted_by_circulation == False:
        result = result.sort_values(by=['day', 'market_share_ratio'], ascending = False).reset_index(drop = True)
    else:
        result = result.sort_values(by=['day', 'circulation_share_ratio'], ascending = False).reset_index(drop = True)
    result = result[['day', 'code', 'name', 'market_share_ratio', 'circulation_share_ratio', 'pe_ratio']]
    log.info('北上资金持股比排名\n', result[['code', 'name', 'market_share_ratio']][:20])
    return result

## 过滤同一标的继上次卖出N天不再买入
def filter_n_tradeday_not_buy(security, n=0):
    try:
        if (security in g.selled_security_dict.keys()) and (g.selled_security_dict[security] < n):
            log.info('%s %s交易日前曾卖出，不符合买入要求(%s)' % (security, g.selled_security_dict[security], n))
            return False
        return True
    except:
        return True

## 卖出股票加入dict
def selled_security_list_dict(context, security_list):
    selled_sl = [s for s in security_list if s not in context.portfolio.positions.keys()]
    if len(selled_sl)>0:
        for stock in selled_sl:
            g.selled_security_dict[stock] = 0

## 过滤停牌股票
def paused_filter(context, security_list):
    current_data = get_current_data()
    security_list = [stock for stock in security_list if not current_data[stock].paused]
    return security_list

## 过滤退市股票
def delisted_filter(context, security_list):
    current_data = get_current_data()
    security_list = [stock for stock in security_list if not (('退' in current_data[stock].name) or ('*' in current_data[stock].name))]
    return security_list

## 过滤ST股票
def st_filter(context, security_list):
    current_data = get_current_data()
    security_list = [stock for stock in security_list if not current_data[stock].is_st]
    return security_list

# 过滤涨停股票
def high_limit_filter(context, security_list):
    current_data = get_current_data()
    security_list = [stock for stock in security_list if not (current_data[stock].day_open >= current_data[stock].high_limit)]
    return security_list
