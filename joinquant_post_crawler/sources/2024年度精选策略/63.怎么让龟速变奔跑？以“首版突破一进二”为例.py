# 克隆自聚宽文章：https://www.joinquant.com/post/45733
# 标题：怎么让龟速变奔跑？以“首版突破一进二”为例
# 作者：jqz1226

# 克隆自聚宽文章：https://www.joinquant.com/post/45724
# 标题：首版突破、一进二
# 作者：klaus5

from datetime import timedelta

from jqdata import *


def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_option("match_by_signal", True)  # # 强制撮合

    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')

    g.help_stock = {}  # dict：{股票代码：今日涨停价}
    g.max_stock_num = 20  # 持仓20只

    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    run_daily(market_run, time='every_bar', reference_security='000300.XSHG')


def market_run(context):
    # type: (Context) -> None
    time_now = context.current_dt.strftime('%H:%M:%S')
    if time_now <= '09:31:00':
        return

    # 1. 买入
    cash = context.portfolio.available_cash
    # 时间必须是9:32及以后，确保有2分钟的数据
    if cash > 5000 and len(context.portfolio.positions) < g.max_stock_num:
        bars = get_bars(list(g.help_stock.keys()), count=2, unit='1m', fields=['close'],
                        include_now=True, end_dt=context.current_dt)  # 过去2分钟的收盘价
        for stock in g.help_stock:
            if stock in context.portfolio.positions:
                continue
            close2m = bars[stock]['close']
            # 上一分钟没有涨停，本分钟涨停了
            if close2m[-2] < close2m[-1] == g.help_stock[stock]:
                function_buy(context, stock)

    # 2.卖出
    holdings = [s for s in context.portfolio.positions if context.portfolio.positions[s].closeable_amount > 0]
    if not holdings:
        return

    # 昨日数据
    df_pre = get_price(holdings, count=1, end_date=context.previous_date, frequency='daily',
                       fields=['close', 'high_limit'], panel=False).set_index('code')

    # 今天数据
    today_start = context.current_dt.replace(hour=9, minute=31, second=0)
    df_all_day = get_price(holdings, start_date=today_start, end_date=context.current_dt,
                           frequency='1m', fields=['high', 'close', 'high_limit'], panel=False)
    # 今日目前最高价
    s_high_today = df_all_day.groupby('code')['high'].max()
    # 今日目前涨停的分钟数
    s_count_limit_all_day = df_all_day.groupby('code').apply(lambda x: (x.close == x.high_limit).sum())
    # 今天前10分钟涨停的分钟数
    s_count_limit_first_10m = df_all_day.groupby('code').apply(lambda x: (x.close == x.high_limit)[:10].sum())

    curr_data = get_current_data()
    for stock in holdings:
        current_price = curr_data[stock].last_price
        day_open_price = curr_data[stock].day_open
        day_high_limit = curr_data[stock].high_limit
        day_low_limit = curr_data[stock].low_limit
        if current_price <= day_low_limit:  # 已经跌停，卖不掉了
            continue

        # 昨日收盘价，昨日涨停价
        pre_close = df_pre['close'][stock]
        pre_high_limit = df_pre['high_limit'][stock]

        # 今日数据
        high_all_day = s_high_today[stock]  # 今天最高价
        count_limit_all_day = s_count_limit_all_day[stock]
        count_limit_before10 = s_count_limit_first_10m[stock]
        # 成本数据
        cost = context.portfolio.positions[stock].avg_cost
        if current_price >= cost * 2:
            order_target(stock, 0)
        elif current_price < cost * 0.92 and current_price < day_open_price and pre_close == pre_high_limit:
            order_target(stock, 0)
        elif (current_price < cost * 0.97 and current_price < day_open_price and time_now >= '09:35:00' and
              pre_close < pre_high_limit):
            order_target(stock, 0)
        elif day_high_limit * 0.96 > current_price and time_now >= '14:30:00':
            order_target(stock, 0)
        elif (high_all_day == day_high_limit and count_limit_all_day > 30 and current_price < day_high_limit and
              day_open_price < day_high_limit * 0.95 and count_limit_before10 >= 2):
            order_target(stock, 0)
        elif pre_close * 0.97 > day_open_price > current_price and pre_close < pre_high_limit:
            order_target(stock, 0)
        elif pre_close * 0.99 > day_open_price > current_price:
            order_target(stock, 0)
        elif pre_close * 1.045 < day_open_price < day_high_limit and current_price < high_all_day * 0.97:
            order_target(stock, 0)
        elif day_open_price > pre_close * 1.045 and current_price < day_open_price and time_now <= '09:33:00':
            order_target(stock, 0)
        elif (high_all_day > pre_close * 1.045 and day_open_price < pre_close * 1.03 and
              high_all_day > day_open_price * 1.03 and current_price < high_all_day and
              current_price <= cost * 1.1 and time_now <= '09:40:00'):
            order_target(stock, 0)


def function_buy(context, stock):
    # type: (Context, str) -> None
    open_cash = 0
    stock_owner = context.portfolio.positions
    if len(stock_owner) < 20:
        open_cash = context.portfolio.available_cash / (20 - len(stock_owner))

    if stock not in stock_owner and open_cash > 5000:
        order_value(stock, open_cash)


def before_market_open(context):
    # type: (Context) -> None
    g.pre_holdings = list(context.portfolio.positions)  # 已经持仓的票

    # 过滤次新股
    by_date = context.previous_date - timedelta(days=30)
    stock_list = list(get_all_securities(['stock'], date=by_date).index)

    # 过滤ST、停牌，创业板、科创板
    current_data = get_current_data()
    stock_list = [code for code in stock_list if not (
            code.startswith(('3', '68', '4', '8'))
            or current_data[code].is_st
            or current_data[code].paused
    )]

    # 过滤掉：流通市值>=150
    stock_list = get_fundamentals(
        query(
            valuation.code
        ).filter(
            valuation.code.in_(stock_list),
            valuation.circulating_market_cap < 150
        )
    )['code'].tolist()

    # 选出可以打板的股票
    g.help_stock = pick_high_limit(context, stock_list)


def pick_high_limit(context, stocks):
    # type: (Context, list) -> dict
    end_date = context.previous_date
    df_pre = get_price(stocks, end_date=end_date, frequency='daily',
                       fields=['close', 'high_limit'], count=1, panel=False
                       ).query('close < high_limit').set_index('code')  # 昨日未涨停
    s_pre_close = df_pre['close']
    stock_list = df_pre.index.tolist()

    df_day_300 = get_price(stock_list, end_date=end_date, frequency='daily',
                           fields=['close'], count=300, panel=False)
    s_high_300 = df_day_300.groupby('code')['close'].apply(lambda x: x.max())  # 过去300个交易日close的最大值
    # 过去300个交易日close的振幅
    s_rate_300 = df_day_300.groupby('code')['close'].apply(lambda x: x.max() / x.min() - 1)

    s_high_50 = df_day_300.groupby('code')['close'].apply(lambda x: x[-50:].max())  # 过去50个交易日close的最大值

    s_high_10 = df_day_300.groupby('code')['close'].apply(lambda x: x[-10:].max())  # 过去10个交易日close的最大值
    # 过去10个交易日close的振幅
    s_rate_10 = df_day_300.groupby('code')['close'].apply(lambda x: x[-10:].max() / x[-10:].min() - 1)

    target_list = pd.DataFrame(
        {'pre_close': s_pre_close, 'high_300': s_high_300, 'rate_300': s_rate_300,
         'high_50': s_high_50, 'high_10': s_high_10, 'rate_10': s_rate_10
         }
    ).dropna().query(
        'pre_close * 1.2 > high_300 and pre_close * 1.2 > high_50 and pre_close * 1.1 > high_10 and '
        'rate_300 < 2 and rate_10 <= 0.5'
    ).index.tolist()

    # dict：{股票代码：今日涨停价}
    dict_high_limit = get_price(target_list, end_date=context.current_dt, fields=['high_limit'],
                                count=1, panel=False).set_index('code')['high_limit'].to_dict()
    return dict_high_limit
