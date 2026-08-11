# 克隆自聚宽文章：https://www.joinquant.com/post/28714
# 标题：北向资金A股择时策略
# 作者：量化看市场

import pandas as pd
from jqdata import finance

def initialize(context):
    """初始化"""
    set_params()
    set_benchmark('000300.XSHG')
    log.set_level('order', 'error')
    set_subportfolios([SubPortfolioConfig(cash=context.portfolio.starting_cash, type='index_futures')])
    # 手续费
    set_order_cost(OrderCost(open_commission=0.000023, close_commission=0.000023, close_today_commission=0.0023), type='index_futures')
    # 保证金率
    set_option('futures_margin_rate', g.margin_rate)
    # 定时运行函数
    run_daily(before_market_open, time='07:00', reference_security='IF8888.CCFX')
    run_daily(market_open, time='09:30', reference_security='IF8888.CCFX')
    
def set_params():
    """全局变量设定"""
    # 期货合约
    g.future_symbol = 'IF'
    # 保证金率
    g.margin_rate = 0.2
    # 布林带参数
    g.window = 252
    g.stdev_n = 1.5
    # 资金占用比例
    g.cash_rate = 0.2
    
    g.mf, g.upper, g.lower = None, None, None
    g.hold_future = ''

def before_market_open(context):
    """盘前运行"""
    pre_date = (context.current_dt - datetime.timedelta(1)).strftime('%Y-%m-%d')
    g.mf, g.upper, g.lower = get_boll(pre_date)
    str_log = '昨日北向资金：%.2f，布林带上下轨：（%.2f，%.2f）' % (g.mf, g.upper, g.lower)
    log.info(str_log)
    send_message(str_log)

def market_open(context):
    """开盘运行"""
    # 当日主力合约
    dom_future = get_dominant_future(g.future_symbol)
    if get_security_info(dom_future).end_date.strftime('%Y-%m-%d') == context.current_dt.strftime('%Y-%m-%d'):
        dom_future = get_future_contracts(g.future_symbol)[1]
    # 有持仓
    if g.hold_future:
        if g.hold_future in context.portfolio.positions:
            # 平多
            if g.mf < g.lower:
                order_target(g.hold_future, 0)
                g.hold_future = ''
                log.info('sell close')
            # 移仓换月
            elif g.hold_future != dom_future:
                order_target(g.hold_future, 0)
                log.info('sell close')
                cash = context.portfolio.total_value * g.cash_rate
                order_value(dom_future, cash)
                g.hold_future = dom_future
                log.info('buy open')
        else:
            # 平空
            if g.mf > g.upper:
                order_target(g.hold_future, 0, side='short')
                g.hold_future = ''
                log.info('buy close')
            # 移仓换月
            elif g.hold_future != dom_future:
                order_target(g.hold_future, 0, side='short')
                log.info('buy close')
                cash = context.portfolio.total_value * g.cash_rate
                order_value(dom_future, cash, side='short')
                g.hold_future = dom_future
                log.info('sell open')
    # 无持仓
    if not g.hold_future:
        cash = context.portfolio.total_value * g.cash_rate
        # 开多
        if g.mf > g.upper:
            order_value(dom_future, cash)
            g.hold_future = dom_future
            log.info('buy open')
        # 开空
        # elif g.mf < g.lower:
        #     order_value(dom_future, cash, side='short')
        #     g.hold_future = dom_future
        #     log.info('sell open')

def get_boll(end_date):
    """布林带"""
    table = finance.STK_ML_QUOTA
    q = query(
        table.day, table.buy_amount, table.sell_amount, table.quota_daily, table.quota_daily_balance
    ).filter(
        table.link_id.in_(['310001', '310002']), table.day <= end_date
    ).order_by(table.day)
    money_df = finance.run_query(q)
    money_df['net_amount'] = money_df['buy_amount'] - money_df['sell_amount']
    # money_df['net_amount'] = money_df['quota_daily'] - money_df['quota_daily_balance']
    # 分组求和
    money_df = money_df.groupby('day')[['net_amount']].sum().iloc[-g.window:]
    mid = money_df['net_amount'].mean()
    stdev = money_df['net_amount'].std()
    upper = mid + g.stdev_n * stdev
    lower = mid - g.stdev_n * stdev
    mf = money_df['net_amount'].iloc[-1]
    return mf, upper, lower

