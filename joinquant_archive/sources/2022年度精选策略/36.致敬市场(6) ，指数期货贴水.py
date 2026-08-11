# 克隆自聚宽文章：https://www.joinquant.com/post/38555
# 标题：致敬市场(6)--指数期货贴水
# 作者：Gyro

import pandas as pd

def initialize(context):
    # setting system
    log.set_level('order', 'error')
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    # setting portfolio
    init_cash = context.portfolio.starting_cash
    set_subportfolios([SubPortfolioConfig(cash=init_cash, type='index_futures')])
    # setting strategy
    run_daily(Trader_buy,  time='14:30')
    run_daily(Trader_sell, time='9:45')

def after_code_changed(context):
    # setting parameter
    g.future_contract = '' 
    g.leverage = 1.0
    g.index_futures = pd.DataFrame(data={
            'IF':['沪深300指数期货', '000300.XSHG'],
            'IH':['上证50股指期货',  '000016.XSHG'],
            'IC':['中证500股指期货', '000905.XSHG'],
            'IM':['中证1000股指期货','000852.XSHG'],
        }, index=['Name','Index']).T
    log.info('Leverage', g.leverage)
    log.info('\n', g.index_futures)

def Trader_buy(context):
    # ratio of index to future
    index_futures = g.index_futures
    ratio = pd.DataFrame(columns=['indexPrice', 'futurePrice', 'R'])
    for fx in index_futures.index:
        df = get_future_contracts(fx)
        index = index_futures.Index[fx]
        xp = history(1, '1m', 'close', index)[index]
        for dx in df:
            fp = history(1, '1m', 'close', dx)[dx]
            R = xp.iloc[0]/fp.iloc[0]*100 - 100
            ratio.loc[dx] = [xp.iloc[0], fp.iloc[0], R]
    # sorted
    ratio = ratio.sort_values(by='R', ascending=False)
    log.info('\n', ratio)
    # choice the contract
    fc = ratio.index[0]
    g.future_contract = fc
    # buy
    if ratio.R.iloc[0] > 6 and\
        fc not in context.portfolio.positions:
        L = g.leverage
        m = get_security_info(fc).get_contract_multiplier()
        price = history(1, '1m', 'close', fc)[fc].iloc[0]
        Ln = L*context.portfolio.total_value / (m*price)
        n = int(Ln)
        log.info('buy', fc, n)
        order(fc, n)

def Trader_sell(context):
    # sell
    for s in context.portfolio.positions:
        if s != g.future_contract:
            log.info('sell', s)
            order_target(s, 0)
# end
