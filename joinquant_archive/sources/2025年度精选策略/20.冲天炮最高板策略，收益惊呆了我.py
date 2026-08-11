# 克隆自聚宽文章：https://www.joinquant.com/post/29356
# 标题：冲天炮最高板策略，收益惊呆了我
# 作者：jqz1226

# from kuanke.user_space_api import *
from jqdata import *
from sklearn.linear_model import LinearRegression


# 初始化程序, 整个回测只运行一次
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')

    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)

    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')

    # 每天买入股票数量
    g.daily_buy_count = 1

    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5),
                   type='stock')

    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    run_daily(market_open, time='every_bar', reference_security='000300.XSHG')


def market_open(context):
    # type: (Context) -> NoReturn
    curr_data = get_current_data()
    hour = context.current_dt.hour
    minute = context.current_dt.minute

    # ------------------处理卖出-------------------
    if minute > 50 and hour == 14:
        for security in context.portfolio.positions:
            closeable_amount = context.portfolio.positions[security].closeable_amount
            if closeable_amount > 0 and curr_data[security].last_price < curr_data[security].high_limit:  # 尾盘未涨停
                order_target(security, 0)  # 卖出
                log.info("卖出： %s %s" % (curr_data[security].name, security))

    # 每天只买这么多个
    if len(g.today_bought_stocks) >= g.daily_buy_count:
        return
    # 涨停板数量>3
    if not (fit_linear(3) > 0 and g.max_zt_days > 2):
        return
    if hour < 11 and len(g.today_bought_stocks) < g.daily_buy_count:  # 冲天炮龙头
        for security in g.buy_list:
            if security not in context.portfolio.positions:  # 排除重复买
                # 计算今天还需要买入的股票数量
                need_count = g.daily_buy_count - len(g.today_bought_stocks)
                buy_cash = context.portfolio.available_cash
                if need_count:
                    buy_cash = context.portfolio.available_cash / need_count

                if buy_cash > (curr_data[security].last_price * 500):
                    # 买入这么多现金的股票
                    result = order_value(security, buy_cash)
                    if result is not None:
                        g.today_bought_stocks.add(security)
                        log.info("买入： %s %s" % (curr_data[security].name, security))


# 直线拟合
def fit_linear(count):
    """
    count:拟合天数
    """
    security = '000001.XSHG'
    df = history(count=count, unit='1d', field='close', security_list=security, df=True, skip_paused=False, fq='pre')
    model = LinearRegression()
    x_train = np.arange(0, len(df[security])).reshape(-1, 1)
    y_train = df[security].values.reshape(-1, 1)
    # print(x_train,y_train)

    model.fit(x_train, y_train)

    # # 计算出拟合的最小二乘法方程
    # # y = mx + c
    # c = model.intercept_
    m = model.coef_
    # c1 = round(float(c), 2)
    m1 = round(float(m), 2)
    # print("最小二乘法方程 : y = {} + {}x".format(c1,m1))
    return m1


def before_market_open(context):
    # type: (Context) -> NoReturn
    end_dt = context.previous_date
    review_days = 10
    #
    g.today_bought_stocks = set()
    #     获取交易日
    trd_days = get_trade_days(end_date=end_dt, count=1 + 60)
    #     获取60个交易日之前前上市股票
    stock_list = get_all_securities('stock', trd_days[0]).index.tolist()
    #
    curr_data = get_current_data()
    stock_list = [stock for stock in stock_list if not (
            # (curr_data[stock].day_open == curr_data[stock].low_limit) or
            curr_data[stock].paused or
            curr_data[stock].is_st or
            ('ST' in curr_data[stock].name) or
            ('*' in curr_data[stock].name) or
            ('退' in curr_data[stock].name) or
            (stock.startswith('688'))
    )]

    #     获取数据，停牌股价亦满足：收盘价==涨停价
    df = get_price(stock_list, end_date=end_dt, count=1 + review_days,
                   fields=['close', 'low', 'high_limit', 'paused'],
                   panel=False)
    #     涨停条件: 非一字漲停
    cond = (df.close == df.high_limit)   # & (df.low < df.high_limit)
    df = df[cond].set_index('time')

    #     缩短日期的时间段至所需天数及其前10天
    trd_days = trd_days[-review_days - 1:]
    #     给日期计数
    day_count = pd.Series(range(len(trd_days)), index=trd_days)
    df['day_count'] = day_count

    #     重置index
    df = df.reset_index()
    #     连板数
    ups = []
    #     股票，连板数
    stock, preday_count = '', 0
    for index, row in df.iterrows():
        #    非同一股票，或日期不连续：
        if row.code != stock or row.day_count - preday_count != 1:
            ups += [1 - row.paused]
            stock = row.code
        #   同一股票，且日期连续
        else:
            ups += [ups[-1] + 1 - row.paused]
        preday_count = row.day_count
    #
    df['ups'] = pd.Series(ups, dtype=np.uint8)
    #    去除停牌日期
    df = df[df.paused == 0]
    
    # 非一字涨停最大连扳数, 以及相应的股票列表
    g.max_zt_days = df[df.day_count == review_days].ups.max()
    g.buy_list = df[(df.day_count == review_days) & (df.ups == g.max_zt_days)]['code'].tolist()
    if len(g.buy_list):
        log.info('_' * 30)
        log.info('股票池：%d 最高板：%d' % (len(g.buy_list), g.max_zt_days))
        log.info(g.buy_list)
