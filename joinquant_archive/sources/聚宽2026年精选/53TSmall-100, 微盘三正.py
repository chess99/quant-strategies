# 克隆自聚宽文章：https://www.joinquant.com/post/50238
# 标题：TSmall-100, 微盘三正
# 作者：Gyro^.^

import pandas as pd
import datetime as dt

def initialize(context):
    # setting system
    log.set_level('order', 'error')
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    # setting strategy
    run_daily(iUpdate, 'before_open')
    run_daily(iTrader, 'open')
    run_daily(iReport, 'after_close')
    g.values = pd.DataFrame(columns=['Value']) # daily portfolio value
    g.values.index.name = 'date'
    g.values.loc[context.previous_date] = [context.portfolio.total_value] # init value

def iUpdate(context):
    # parameters
    nposition = 100 # number of positions
    nchoice = 120 # number of choice stocks
    # daily update
    g.stocks = _choice_small(context, nchoice)
    g.position_size = 1.0/nposition * context.portfolio.total_value

def iTrader(context):
    # load data
    stocks = g.stocks
    position_size = g.position_size
    cash_size = 1.5 * position_size
    cdata = get_current_data()
    # sell
    for s in context.portfolio.positions:
        if cdata[s].paused or \
            cdata[s].last_price >= cdata[s].high_limit or cdata[s].last_price <= cdata[s].low_limit:
            continue
        if s not in stocks:
            log.info('sell', s, cdata[s].name)
            order_target(s, 0, MarketOrderStyle(0.99*cdata[s].last_price))
    # buy stocks
    for s in stocks:
        if context.portfolio.available_cash < cash_size:
            break
        if cdata[s].paused or \
            cdata[s].last_price >= cdata[s].high_limit or cdata[s].last_price <= cdata[s].low_limit:
            continue
        if s not in context.portfolio.positions:
            log.info('buy', s, cdata[s].name)
            order_value(s, position_size, MarketOrderStyle(1.01*cdata[s].last_price))

def iReport(context):
    # table of positions
    cdata = get_current_data()
    tvalue = context.portfolio.total_value
    ptable = pd.DataFrame(columns=['amount', 'value', 'weight', 'name'])
    for s in context.portfolio.positions:
        ps = context.portfolio.positions[s]
        ptable.loc[s] = [ps.total_amount, int(ps.value), 100*ps.value/tvalue, cdata[s].name]
    ptable = ptable.sort_values(by='weight', ascending=False)
    # daily report
    log.info('  positions', len(ptable), '\n', ptable.head())
    log.info('  total value %.2f, cash %.2f', \
            context.portfolio.total_value/10000, context.portfolio.available_cash/10000)
    # daily save
    d = context.current_dt.date()
    g.values.loc[d] = [context.portfolio.total_value]
    write_file('Tiny-100', g.values.to_csv())

def _choice_small(context, nchoice):
    # parameters
    index = '399317.XSHE'
    # stocks
    cdata = get_current_data()
    stocks = get_index_stocks(index)
    # fundamental data
    df = get_fundamentals(query(
            valuation.code,
            valuation.market_cap,
        ).filter(
            valuation.code.in_(stocks),
            valuation.pb_ratio > 0,
            indicator.inc_return > 0,
            indicator.ocf_to_revenue > 0,
        ).order_by(valuation.market_cap.asc()
        ).limit(nchoice)
        ).dropna().set_index('code')
    stocks = df.index.tolist()
    # report
    df = df.loc[stocks]
    df['name'] = [cdata[s].name for s in df.index]
    log.info('small stocks', len(df), '\n', df.head())
    # reuslt
    return stocks
# end
