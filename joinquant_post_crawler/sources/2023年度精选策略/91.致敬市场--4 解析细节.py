# 克隆自聚宽文章：https://www.joinquant.com/post/33312
# 标题：致敬市场(4)--解析细节
# 作者：Gyro

import pandas as pd
import datetime as dt
from six import BytesIO

def initialize(context):
    g.index = '399311.XSHE' #国证1000
    set_benchmark(g.index)
    log.set_level('order', 'error')
    set_option('use_real_price', True)
    set_option('avoid_future_data', False) # 提取指定年份年报不能开启

def after_code_changed(context):
    unschedule_all()
    run_monthly(update_stocks, 1, 'open')
    run_monthly(trader, 1, '14:30')
    run_monthly(report_porfolio, -1, 'after_close')
    g.file_name = 'iEpsilon_portfolio.csv'
    g.stocks = pd.Series() # 投资组合
    g.position_num = 100 # 持股数
    update_stocks(context) # 启动

def update_stocks(context):
    if context.run_params.type == 'sim_trade' and\
        len(g.stocks) == 0:
        # load stocks list
        fData = read_file(g.file_name)
        ptable = pd.read_csv(BytesIO(fData)).set_index('code')
        g.stocks = 0.01 * ptable.weight
    elif context.current_dt.month == 5:
        # update stocks list
        # running only on the first trading-day in May
        g.stocks = choice_stocks(context)

def choice_stocks(context):
    # init
    stocks = get_index_stocks(g.index)
    last_year = context.current_dt.year - 1
    log.info('stocks pool size', len(stocks))
    # get annual report
    q = query(
        indicator.code,
        indicator.pubDate,
        indicator.inc_return.label('ROE'),
        indicator.inc_total_revenue_year_on_year.label('grow'),
      ).filter(
        income.code.in_(stocks),
        indicator.inc_return > 10,
        indicator.inc_total_revenue_year_on_year > 0,
      )
    df = get_fundamentals(q, statDate=str(last_year)).dropna().set_index('code')
    stocks = df.index.tolist()
    log.info('Total annual reports', last_year, len(df))
    # history stocks return
    h = history(241, '1d', 'close', stocks).dropna(axis=1)
    r = h.pct_change()[1:]
    # history index return
    h = history(241, '1d', 'close', g.index)
    rx = h[g.index].pct_change()[1:]
    # low covariation
    cvar = pd.Series()
    for s in r.columns:
        cm = cov(r[s], rx)
        cvar[s] = cm[0, 1]
    cvar = cvar.sort_values(ascending=True)
    stocks = cvar.index.tolist() 
    # report
    df = df.loc[stocks]
    df['covar'] = 100 * 240 * cvar
    pd.set_option('display.max_rows', len(df)+1)
    log.info('\n', df)
    log.info('Total choice', len(df))
    # return
    weight = pd.Series(1.0/g.position_num, index=cvar.index.tolist())
    return weight

def trader(context):
    cdata = get_current_data()
    # Sell
    for s in context.portfolio.positions:
        if s not in g.stocks.index and\
            not cdata[s].paused:
            log.info('sell', s, cdata[s].name)
            order_target(s, 0)
    # Buy
    for s in g.stocks.index:
        poisition_size = g.stocks[s] * context.portfolio.total_value
        if s not in context.portfolio.positions and\
            context.portfolio.available_cash > poisition_size and\
            not cdata[s].paused:
            log.info('buy', s, cdata[s].name)
            order_value(s, poisition_size)

def report_porfolio(context):
    # table of positions
    cdata = get_current_data()
    tvalue = context.portfolio.total_value
    ptable = pd.DataFrame(columns=['name', 'volume', 'weight'])
    ptable.index.name = 'code'
    for s in context.portfolio.positions:
        ps = context.portfolio.positions[s]
        ptable.loc[s] = [cdata[s].name, ps.total_amount, 100*ps.value/tvalue]
    ptable = ptable.sort_values(by='weight', ascending=False)
    # report
    pd.set_option('display.max_rows', len(ptable)+1)
    log.info('\n', ptable)
    log.info('Total positions', len(ptable))
    # save
    write_file(g.file_name, ptable.to_csv())
# end
