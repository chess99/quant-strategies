# 克隆自聚宽文章：https://www.joinquant.com/post/45654
# 标题：回报社区——基于Gyro老师策略的思考
# 作者：琼楼

#https://www.joinquant.com/view/community/detail/45f88aadf6fd346fccfc4f5237ab6c78

def initialize(context):
    set_benchmark('399300.XSHE')
    log.set_level('order', 'error')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0001, close_commission=0.0001, min_commission=0), type='stock')

def after_code_changed(context):
    g.last_update_month = 0
    g.choicenum = 100
    g.weight = {}

def before_trading_start(context):
    def sum_func(X):
        return X[0] + (X[1] + X[2] + X[3])/3
    # monthly update
    '''
    if g.last_update_month == context.current_dt.month:
        return
    g.last_update_month = context.current_dt.month
    '''
    # all stocks
    stk_sh = get_index_stocks('000001.XSHG')
    stk_sz = get_index_stocks('399106.XSHE')
    allstocks = stk_sh + stk_sz
    # stock pool
    df = get_fundamentals(query(
            valuation.code,
            valuation.market_cap,
            valuation.pb_ratio,
            valuation.pe_ratio,
            valuation.pcf_ratio,
        ).filter(
            valuation.code.in_(allstocks),
            valuation.pb_ratio>0,
            valuation.pe_ratio>0,
            valuation.pcf_ratio>0,
        )).dropna()
    # small - valuable
    df['point'] = df[['market_cap', 'pb_ratio', 'pe_ratio', 'pcf_ratio']] \
        .rank().T.apply(sum_func)
    df = df.sort_index(by='point').head(g.choicenum)
    stocks = list(df['code'])
    # weight
    #g.weight = dict(zip(stocks, ones(g.choicenum)/g.choicenum))
    g.weight = dict(zip(stocks, generate_arithmetic_series(g.choicenum)))

def generate_arithmetic_series(n):
    if n != 1:
        common_difference =  2/(n - 1)/n
        series = [(n-i-1) * common_difference for i in range(n)]
        return series
    else:
        return [1]

def handle_data(context, data):
    current_data = get_current_data()
    # sell
    for stock in context.portfolio.positions.keys():
        if stock not in g.weight:
            log.info('sell out ', stock)
            order_target(stock, 0);
    # buy
    for stock in g.weight.keys():
        position = g.weight[stock] * context.portfolio.total_value
        if stock not in context.portfolio.positions:
            log.info('buy ', stock)
            order_target_value(stock, position)
        else:
            t = context.portfolio.long_positions[stock].transact_time
            p = get_price(stock,count=1,end_date = t)['open'][0]
            np = current_data[stock].day_open
            if (np/p>1.1 and context.portfolio.long_positions[stock].value>position) or (np/p<0.9 and context.portfolio.long_positions[stock].value<position):
                log.info('动态调仓  ', stock)
                order_target_value(stock, position)
# end
