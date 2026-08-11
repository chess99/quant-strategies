# 克隆自聚宽文章：https://www.joinquant.com/post/44563
# 标题：微盘股研究
# 作者：Gyro^.^

import pandas as pd

def initialize(context):
    # 设置系统
    log.set_level('order', 'error') 
    set_option('use_real_price', True) 
    set_option('avoid_future_data', True) 
    g.days = 0 

def after_code_changed(context):
    # 设置策略
    unschedule_all()
    run_daily(iUpdate, time='before_open') 
    run_daily(iTrader, time='9:35') 
    run_daily(iReport, time='after_close') 

def iUpdate(context):
    # 参数
    nchoice = 120
    nposition = 100
    # 全部A股
    dt_last = context.previous_date
    all_stock = get_all_securities('stock', dt_last)
    # 过滤ST
    cdata = get_current_data()
    stocks = [s for s in all_stock.index if not cdata[s].is_st]
    # 小盘股
    df = get_fundamentals(query(
            valuation.code,
            valuation.market_cap,
        ).filter(
            valuation.code.in_(stocks),
            valuation.pb_ratio > 0,
        ).order_by(valuation.market_cap.asc()
        ).limit(nchoice)
        ).dropna().set_index('code')
    # 结果
    g.choice = df.index.tolist()
    g.position_size = 1.0/nposition * context.portfolio.total_value

def iTrader(context):
    # 参量
    choice = g.choice 
    position_size = g.position_size 
    lm_value = 0.8 * position_size 
    hm_value = 1.2 * position_size 
    cdata = get_current_data() 
    # 卖出
    for s in context.portfolio.positions:
        if cdata[s].paused or \
            cdata[s].last_price >= cdata[s].high_limit or \
            cdata[s].last_price <= cdata[s].low_limit:
            continue # 过滤三停
        if s not in choice:
            log.info('sell', s, cdata[s].name)
            order_target(s, 0, MarketOrderStyle(0.99*cdata[s].last_price))
    # 买进
    for s in choice:
        if context.portfolio.available_cash < position_size:
            break
        if cdata[s].paused or \
            cdata[s].last_price >= cdata[s].high_limit or \
            cdata[s].last_price <= cdata[s].low_limit:
            continue # 过滤三停
        if s not in context.portfolio.positions:
            log.info('buy', s, cdata[s].name)
            order_target_value(s, position_size, MarketOrderStyle(1.01*cdata[s].last_price))
        elif context.portfolio.positions[s].value < lm_value:
            log.info('balance+', s, cdata[s].name)
            order_target_value(s, position_size, MarketOrderStyle(1.01*cdata[s].last_price))
        elif context.portfolio.positions[s].value > hm_value:
            log.info('balance-', s, cdata[s].name)
            order_target_value(s, position_size, MarketOrderStyle(0.99*cdata[s].last_price))

def iReport(context):
    # 报告状态
    g.days = g.days + 1
    log.info('  positions', len(context.portfolio.positions))
    log.info('  return %.2f', 100*context.portfolio.returns)
    log.info('  cash %.2f',   context.portfolio.available_cash/10000)
    log.info('  value %.2f',  context.portfolio.total_value/10000)
    log.info('running days', g.days)
# end
