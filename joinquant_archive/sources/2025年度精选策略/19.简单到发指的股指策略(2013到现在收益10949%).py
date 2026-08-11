# 克隆自聚宽文章：https://www.joinquant.com/post/30480
# 标题：简单到发指的股指策略(2013到现在收益10949%)
# 作者：资金永不眠

# coding=utf-8

"""股指期货交易策略

策略非常简单：
1. 尾盘买入
2. 次日10点卖出
3. 满仓
"""

from jqdata import *


def initialize(context):
    g.code = 'IF'
    g.benchmark = '000300.XSHG'
    set_benchmark(g.benchmark)

    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)

    ### 期货相关设定 ###
    # 设定账户为金融账户
    set_subportfolios([SubPortfolioConfig(
        cash=context.portfolio.starting_cash,
        type='index_futures')])
    # 期货类每笔交易时的手续费是：买入时万分之0.23,卖出时万分之0.23,平今仓为万分之23
    set_order_cost(OrderCost(
        open_commission=0.000023,
        close_commission=0.000023,
        close_today_commission=0.0023
    ), type='index_futures')
    # 设定保证金比例
    set_option('futures_margin_rate', 0.15)

    # 设置期货交易的滑点
    set_slippage(StepRelatedSlippage(2))

    run_daily(buy, time='14:55', reference_security='IF8888.CCFX')
    run_daily(empty, time='10:00', reference_security='IF8888.CCFX')


def buy(context):
    """建仓"""
    code = get_dominant_future(g.code)
    cash = context.portfolio.available_cash/2
    order_target_value(code, cash, side='long')


def empty(context):
    """清仓"""
    for code in context.portfolio.long_positions:
        p = context.portfolio.long_positions[code]
        lots = p.total_amount
        value = p.price * lots
        returns = context.portfolio.returns * 100
        order_target(code, 0, side='long')
        log.debug('==> #平多：%s %d元, 总收益率 %.2f%%' % (code[:-5], value, returns))
