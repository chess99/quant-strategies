# 克隆自聚宽文章：https://www.joinquant.com/post/30024
# 标题：iAlpha 基金投资策略
# 作者：Gyro

# 克隆自聚宽文章：https://www.joinquant.com/post/30024
# 标题：iAlpha 基金投资策略
# 作者：Gyro

def after_code_changed(context):
    # 设置定时器
    run_monthly(handle_trader, 11, '9:35')
    # 投资参数
    g.funds = [
        '511260.XSHG', # 国泰十年国债 ETF
        '518880.XSHG', # 华安黄金 ETF
        '513500.XSHG', # 博时标普500 ETF
        '513100.XSHG', # 国泰纳指100 ETF
        '513050.XSHG', # 易方达中概互联50 ETF
        '159928.XSHE', # 汇添富中证消费 ETF
        '512010.XSHG', # 易方达沪深300医药 ETF
        '512770.XSHG', # 华夏战略新兴 ETF
        ] # 基金列表

def handle_trader(context):
    # init variable
    cur_data = get_current_data()
    position = context.portfolio.total_value / len(g.funds)
    # sell
    for s in context.portfolio.positions:
        if s not in g.funds:
            log.info('sell', s, cur_data[s].name)
            order_target_value(s, 0)
    # buy or rebalance
    for s in g.funds:
        if s not in context.portfolio.positions:
            delta = position
        else:
            delta = position - context.portfolio.positions[s].value
        if abs(delta) > max(0.1*position, 100*cur_data[s].last_price) and\
            context.portfolio.available_cash > delta and not cur_data[s].paused:
            log.info('buy', s, cur_data[s].name, delta)
            order_value(s, delta)
# end
