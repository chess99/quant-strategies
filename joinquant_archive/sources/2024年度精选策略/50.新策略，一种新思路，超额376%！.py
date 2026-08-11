# 克隆自聚宽文章：https://www.joinquant.com/post/40560
# 标题：新策略，一种新思路，超额376%！
# 作者：hello friends

import statsmodels.api as sm
from jqdata import *
from jqfactor import get_factor_values


# 初始化函数
def initialize(context):
    # 设定基准
    set_benchmark('000905.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')

    # 初始化全局变量
    g.stock_num = 8#持股数
    g.limit_days = 20#用来检查最近20天内列表中有涨停的股票

    g.hold_list = []
    g.history_hold_list = []
    g.not_buy_again_list = []
    # 设置交易时间，每天运行
    run_daily(prepare_stock_list, time='9:05', reference_security='000300.XSHG')
    #每天获取g.hold_list已持仓列表、g.not_buy_again_list20天内买过的接下来不买的股的列表、g.high_limit_list昨日涨停列表
    #run_weekly(weekly_adjustment, weekday=1, time='9:30', reference_security='000300.XSHG')
    run_monthly(monthly_adjustment, monthday=1, time='9:30', reference_security='000300.XSHG')
    #每周获取股票列表，去除最近20天内曾经涨停过的和曾经买过的股，去掉下跌趋势明显的
    run_daily(check_limit_up, time='14:00', reference_security='000300.XSHG')
    #把昨日涨停今天没涨停的股票卖出


# 1-1 选股模块
def get_single_factor_list(context, stock_list, jqfactor, sort, p1, p2):
    #这个函数是将股票列表按照选取的因子进行按高或者低排序，返回前p2比例的股票
    # type: (Context, list, str, bool, float, float) -> list
    yesterday = context.previous_date
    s_score = get_factor_values(stock_list, jqfactor, end_date=yesterday, count=1
                                )[jqfactor].iloc[0].dropna().sort_values(ascending=sort)
    return s_score.index[int(p1 * len(stock_list)):int(p2 * len(stock_list))].tolist()


def sorted_by_circulating_market_cap(stock_list, n_limit_top=25):#把股票列表按市值排序 取前25名
    q = query(
        valuation.code,
    ).filter(
        valuation.code.in_(stock_list),
        indicator.eps > 0
    ).order_by(
        valuation.circulating_market_cap.asc()
    ).limit(
        n_limit_top
    )
    return get_fundamentals(q)['code'].tolist()


# 1-2 选股模块：根据营业收入增长率、盈利增长率、PEG等因子找出股票
def get_stock_list(context):
    # type: (Context) -> list
    # 去掉次新股
    by_date = context.previous_date - datetime.timedelta(days=375)
    initial_list = get_all_securities(date=by_date).index.tolist()
    # 去科创，ST
    initial_list = filter_kcb_stock(initial_list)
    initial_list = filter_st_stock(initial_list)

    # 1. 取质量因子扣非利润比的前30%
    sg_list = get_single_factor_list(context, initial_list, 'adjusted_profit_to_total_profit', False, 0, 0.3)
    print('测试sg%s'%len(sg_list))
    # 2. MS 复合增长率, 从大到小的前8%；
    factor_list = [
        'short_term_predicted_earnings_growth',  # 1年预期利润增长率
        'long_term_predicted_earnings_growth',  # 3年预期利润增长率
        'net_profit_growth_rate',  # 净利润增长率
        'earnings_growth',  # 5年盈利增长率
    ]
    factor_values = get_factor_values(sg_list, factor_list, end_date=context.previous_date, count=1)
    df = pd.DataFrame(index=sg_list)
    for factor in factor_list:
        df[factor] = factor_values[factor].iloc[0]

    df['total_score'] = 0.2* df['short_term_predicted_earnings_growth'] + 0.4 * df['long_term_predicted_earnings_growth'] + 0.2 * df[
        'net_profit_growth_rate'] + 0.2 * df['earnings_growth']
    ms_list = df.sort_values(by=['total_score'], ascending=False).index[:int(0.08 * len(df))].tolist()

    print('测试ms%s'%len(ms_list))
    # 3: PEG，升序前20%\TURNOVER_VOLATILITY，升序前90%；再按流通市值升序，取前25名
    peg_list = get_single_factor_list(context, ms_list, 'PEG', True, 0, 0.2)
    peg_list = get_single_factor_list(context, ms_list, 'turnover_volatility', True, 0, 0.8)
    peg_list = sorted_by_circulating_market_cap(peg_list)
    print('测试peg%s'%len(peg_list))
    print('选股结果：',peg_list)
    return peg_list


# 1-3 准备股票池
def prepare_stock_list(context):
    # 获取已持有列表
    g.hold_list = list(context.portfolio.positions)

    # 获取最近一段时间持有过的股票列表
    g.history_hold_list.append(g.hold_list)
    if len(g.history_hold_list) >= g.limit_days:
        g.history_hold_list = g.history_hold_list[-g.limit_days:]
    #
    temp_set = set()
    for hold_list in g.history_hold_list:
        temp_set = temp_set.union(set(hold_list))#通过set.union()去重
    #
    g.not_buy_again_list = list(temp_set)#不买最近20天买过的股票

    # 获取持仓的昨日涨停列表
    g.high_limit_list = []
    if g.hold_list:
        df = get_price(g.hold_list, end_date=context.previous_date, frequency='daily',
                       fields=['close', 'high_limit', 'paused'],
                       count=1, panel=False)
        g.high_limit_list = df.query('close==high_limit and paused==0')['code'].tolist()#paused为0表示不停牌


# 1-4 整体调整持仓  
def monthly_adjustment(context):
    # type: (Context) -> None
    # 获取应买入列表
    target_list = get_stock_list(context)#获取股票列表
    #
    target_list = filter_paused_stock(target_list)
    target_list = filter_limit_stock(context, target_list)

    # target_list中，去除最近20天内曾经涨停过的和曾经买过的股
    recent_limit_up_list = get_recent_limit_up_stock(context, target_list, g.limit_days)
    black_list = list(set(g.not_buy_again_list).intersection(set(recent_limit_up_list)))
    target_list = [stock for stock in target_list if stock not in black_list]

    # 最近20天的MA20的斜率，去掉下跌趋势明显的，即斜率<-2的
    h_ma = history(20 + 20, '1d', 'close', target_list).rolling(window=20).mean().iloc[20:]#df.rolling(window=?).mean()将DF的最近几个窗口（或值）进行滚动求平均
    #上面取最后20行
    X = np.arange(len(h_ma))#生成0、1、...19的数组
    tmp_target_list = []
    for stock in target_list:
        MA_N_Arr = h_ma[stock].values#得到每个股票最近20天的MA20数值
        MA_N_Arr = MA_N_Arr - MA_N_Arr[0]  # 截距归零，理解成标准化
        slope = round(sm.OLS(MA_N_Arr, X).fit().params[0] * 100, 1)# Statsmodels 中 OLS 回归功能sm.OLS(因变量,自变量)，在 OLS之后调用拟合函数 fit()，
        #才进行回归运算，并且得到RegressionResultsWrapper结果，它包含了这组数据进行回归拟合的结果摘要。调用 params 可以查看计算出的回归系数 b0,b1,…,bn。
        #params[0]是为了去除列表，取具体值。sm.OLS(Y,X).fit().summary()可以看总体回归情况
        #print("测试%s"%sm.OLS(MA_N_Arr, X).fit().summary())
        remove_it = False
        if slope < -2:
            if stock not in g.hold_list:
                print('{}下降趋势明显，切勿开仓'.format(stock))
                remove_it = True
        if not remove_it:
            tmp_target_list.append(stock)
    #
    target_list = tmp_target_list
    # 调仓：不在列表，昨日未涨停的持仓票卖出。
    for stock in g.hold_list:
        if (stock not in target_list) and (stock not in g.high_limit_list):
            log.info("卖出[%s]" % stock)
            position = context.portfolio.positions[stock]
            close_position(position)
        else:
            log.info("已持有[%s]" % stock)

    position_count = len(context.portfolio.positions)
    target_num = g.stock_num
    if target_num > position_count:
        value =  context.portfolio.available_cash / (target_num - position_count)
        for stock in target_list:
            if stock not in context.portfolio.positions:
                if open_position(stock, value):
                    if len(context.portfolio.positions) >= g.stock_num:
                        break


# 1-5 调整昨日涨停股票
def check_limit_up(context):
    current_data = get_current_data()
    if g.high_limit_list:#if list: list非0非空，则为true
        for stock in g.high_limit_list:
            if current_data[stock].last_price < current_data[stock].high_limit:
                log.info("[%s]涨停打开，卖出" % stock)
                position = context.portfolio.positions[stock]
                close_position(position)
            else:
                log.info("[%s]涨停，继续持有" % stock)


# 2-1 过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]


# 2-2 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not (
            current_data[stock].is_st or
            'ST' in current_data[stock].name or
            '*' in current_data[stock].name or
            '退' in current_data[stock].name)]


# 2-3 获取最近rencent_days个交易日内有涨停的股票列表
def get_recent_limit_up_stock(context, stock_list, recent_days):
    # type: (Context, list, int) -> list
    yesterday = context.previous_date
    h = get_price(stock_list, end_date=yesterday, frequency='daily', fields=['close', 'high_limit', 'paused'],
                  count=recent_days, panel=False)
    s_limit = h.query('close==high_limit and paused==0').groupby('code')['high_limit'].count()
    return s_limit.index.tolist()


# 2-4 过滤涨停的股票
def filter_limit_stock(context, stock_list):
    # type: (Context, list) -> list
    current_data = get_current_data()
    holdings = list(context.portfolio.positions)
    return [stock for stock in stock_list if (stock in holdings) or
            current_data[stock].low_limit < current_data[stock].last_price < current_data[stock].high_limit]


# 2-6 过滤科创板
def filter_kcb_stock(stock_list):
    return [stock for stock in stock_list if not stock.startswith('68')]


# 3-1 交易模块-自定义下单
def order_target_value_(security, value):
    if value == 0:
        log.debug("Selling out %s" % security)
    else:
        log.debug("Order %s to value %f" % (security, value))
    return order_target_value(security, value)


# 3-2 交易模块-开仓
def open_position(security, value):
    _order = order_target_value_(security, value)
    if _order is not None and _order.filled > 0:
        return True
    return False


# 3-3 交易模块-平仓
def close_position(position):
    security = position.security
    _order = order_target_value_(security, 0)  # 可能会因停牌失败
    if _order is not None:
        if _order.status == OrderStatus.held and _order.filled == _order.amount:
            return True
    return False
