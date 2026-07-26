# 克隆自聚宽文章：https://www.joinquant.com/post/33683
# 标题：致敬市场(5)--定投ETF之躺平赢
# 作者：Gyro

import pandas as pd
import datetime as dt

def initialize(context):
    log.set_level('order', 'error')
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)

def after_code_changed(context):
    unschedule_all()
    run_weekly(iTrader, 1, time='open')

def iTrader(context):
    # 参数
    index = '399300.XSHE'
    # 过滤，当前在市、一年前上市的基金
    dt_now = context.current_dt.date()
    dt_1y = dt_now - dt.timedelta(days=365)
    all_fund = get_all_securities(['etf', 'lof'], dt_now)
    all_fund = all_fund[all_fund.start_date < dt_1y]
    funds = all_fund.index.tolist()
    # 流动性过滤
    hm = history(21, '1d', 'money', funds).min()
    funds = [s for s in hm.index if hm[s] > 1e6]
    # 历史价格
    h = history(241, '1d', 'close', funds + [index])
    r = np.log(h).diff()[1:]
    rx = r[index] 
    # CAPM
    capm = pd.DataFrame(columns=['alpha', 'beta', 'delta', 'name'])
    for s in funds:
        rs = r[s]
        cm = cov(rs, rx)
        beta = cm[0,1] / cm[1,1]
        z = rs - beta*rx
        alpha = 24000*z.mean()
        delta = 1550 *z.std()
        if alpha > 0 and 0.9 < beta < 1.1 and delta < 10:
            capm.loc[s] = [alpha, beta, delta, all_fund.display_name[s]]
    # 
    capm = capm.sort_values(by='alpha', ascending=False).head(10)
    funds = capm.index.tolist()
    log.info('\n', capm)
    # 
    cdata = get_current_data()
    for s in context.portfolio.positions:
        if s not in funds:
            log.info('sell', cdata[s].name)
            order_target(s, 0)
    # 
    psize = 0.05 * context.portfolio.total_value
    for s in funds[:5]:
        if context.portfolio.available_cash < psize:
            break
        log.info('buy', s, cdata[s].name)
        order_value(s, psize)
# end
