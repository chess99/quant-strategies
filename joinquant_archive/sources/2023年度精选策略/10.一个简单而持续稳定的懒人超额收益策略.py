# 克隆自聚宽文章：https://www.joinquant.com/post/30467
# 标题：一个简单而持续稳定的懒人超额收益策略
# 作者：Gyro

import numpy as np
import pandas as pd
from jqdata import *

def initialize(context):
    # 初始化系统
    log.set_level('order', 'error')
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)

def after_code_changed(context):
    # 设置参数
    g.index = '000300.XSHG' # 投资指数
    g.stocks = [] # 投资组合
    # 设置定时器
    unschedule_all() # 重置，方便代码升级
    run_monthly(handle_prepare, 1, 'before_open')
    run_daily(handle_trader, 'open')
    run_monthly(report_portoflio, -1, 'after_close')

def handle_prepare(context):
    weight = get_index_weights(g.index) # 提取指数权重
    weight = weight.sort_values(by='weight', ascending=False).head(10)
    log.info('\n', weight)
    g.stocks = weight.index.tolist() 

def handle_trader(context):
    cur_data = get_current_data()
    # 多头卖出
    for s in context.portfolio.positions:
        if s not in g.stocks:
            log.info('sell', s, cur_data[s].name)
            order_target(s, 0)
    # 多头买进
    for s in g.stocks:
        position = 0.095 * context.portfolio.total_value
        if s not in context.portfolio.positions and\
            context.portfolio.available_cash > position:
            log.info('buy', s, cur_data[s].name, int(position))
            order_value(s, position)

def report_portoflio(context):
    # 报告账户
    log.info('total returns', 100*context.portfolio.returns)
    log.info('available cash', context.portfolio.available_cash)
    log.info('total value', context.subportfolios[0].total_value)
    # 分列持仓
    cur_data = get_current_data()
    for s in context.portfolio.positions:
        ps = context.portfolio.positions[s]
        log.info('long', s, cur_data[s].name, ps.total_amount, int(ps.value))
# end
