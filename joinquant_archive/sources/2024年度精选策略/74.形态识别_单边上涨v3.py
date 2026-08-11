# 克隆自聚宽文章：https://www.joinquant.com/post/45406
# 标题：形态识别_单边上涨v3
# 作者：伺底而动

# 克隆自聚宽文章：https://www.joinquant.com/post/37594
# 标题：主观辅助策略_形态识别_单边上涨
# 作者：说好的下次一定

# 导入函数库
from jqdata import *
import pandas as pd
import numpy as np
import talib as ta
import statsmodels.api as sm

# 本代码为加速版，n天一调仓而不是每天调仓，运行的更快

# 初始化函数

def initialize(context):
    ### 股票相关设定 ###
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)

    log.set_level('order', 'error')

    set_slippage(FixedSlippage(0.002))
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，
    # 卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001,
                             open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    # 计数器
    g.counter = 0
    # 模型参数
    # 判断全天均匀上涨,OLS的R方最小值
    g.arg_rsquared_min = 0.8
    # 收盘价涨幅下限
    g.arg_close_rate = 0.052
    # 成交量回看天数
    g.arg_volume_days = 5
    # 成交量大于days均值的倍数
    g.arg_volume_multi = 2
    # 持仓股票的最大数目
    g.arg_buy_max = 10
    # 买入时要达到的比例
    g.buy_min_ratio = 0.4
    # 单只股票持仓时间
    g.arg_hold_max = 20
    # 持仓日数记录
    g.hold_days = g.arg_hold_max - 1

    # 选择股票
    g.stocks = []
    g.choice = 1000
    
    # 空闲资金买入黄金ETF
    # g.etf = ""
    g.etf = "518880.XSHG"
    # g.etf = "511010.XSHG"

    g.hold_list = []  # 当前持仓的全部股票
    g.yesterday_HL_list = []  # 记录持仓中昨日涨停的股票

    # 运行函数（reference_security为运行时间的参考标的；
    # 传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
    # 开盘前运行
    run_daily(before_market_open, time='before_open')
    run_daily(trade, time='14:55')
    run_daily(check_limit_up, time='14:00',
              reference_security='000852.XSHG')

# 开盘前运行函数


def before_market_open(context):
    # if g.hold_days < g.arg_hold_max:
    #     return
    
    yesterday = context.previous_date

    # 获取已持有列表
    g.hold_list = [s for s in context.portfolio.positions]

    # 获取昨日涨停列表
    if g.hold_list != []:
        df = get_price(g.hold_list, end_date=yesterday, frequency='daily', fields=[
                       'close', 'high_limit'], count=1, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        g.yesterday_HL_list = list(df.code)
    else:
        g.yesterday_HL_list = []

    # 股票池
    # stocks = get_all_securities(date=yesterday).index.tolist()

    # 获取股票代码并按市值排序
    fundamentals_data = get_fundamentals(query(valuation.code, valuation.market_cap).order_by(
        valuation.market_cap.asc()).filter(valuation.market_cap < 160).limit(g.choice))
    stocks = list(fundamentals_data['code'])

    # 各种过滤
    current_data = get_current_data()
    stocks = [s for s in stocks if not current_data[s].paused
                and not current_data[s].is_st
                and 'N' not in current_data[s].name
                and '退' not in current_data[s].name
                and current_data[s].low_limit < current_data[s].day_open < current_data[s].high_limit
                and s[0] != '4' and s[0] != '8' and s[:2] != '68' \
                # and s[:2] != '30' \
                and s not in g.hold_list]
    
    g.stocks = [stock for stock in stocks if yesterday - get_security_info(stock).start_date > datetime.timedelta(days=250)]

    log.info('股票数量{}'.format(len(g.stocks)))
    
def get_stocks(context):
    current_data = get_current_data()

    stock_chosen = []
    stock_chosen_mom = []
    # 逐股票操作：选股
    for stock in g.stocks:
        # 获得历史成交量的均值
        history_data = attribute_history(stock, unit='1d',
                                 count=g.arg_volume_days, 
                                 fields=['open', 'close', 'volume'])
        history_volume = np.mean(history_data['volume'])

        # 如果有空值，排除
        if np.isnan(history_volume):
            continue

        # 查询行情数据
        df_stock_data = get_price(stock,
                                  start_date=context.current_dt.replace(
                                      hour=9, minute=30, second=0),
                                  end_date=context.current_dt,
                                  frequency='1m',
                                  fields=['open', 'close', 'high', 'volume'])

        # 成交量大于前arg日均值,否则排除
        if df_stock_data['volume'].sum() < g.arg_volume_multi*history_volume:
            continue

        # 收盘收益率大于下限，否则排除
        if (current_data[stock].last_price - current_data[stock].day_open)/(
                current_data[stock].day_open) < g.arg_close_rate:
            continue

        # 当天最后一分钟时涨停，排除
        if current_data[stock].high_limit <= df_stock_data['high'].iloc[-1]:
            continue

        # 进行OLS回归，用R方判别单边上涨
        Y = df_stock_data['close'].values
        X = sm.add_constant(np.arange(Y.shape[0]))
        ols_result = sm.OLS(Y, X).fit()
        flag_keep_up = (ols_result.rsquared > g.arg_rsquared_min
                        ) & (ols_result.params[1] > 0)

        # 斜率为正且R方满足要求，计入
        if not flag_keep_up:
            continue

        # 走到最后一步了，代表前面都满足，加入选股列表
        stock_chosen.append(stock)

        # 动量测算,用上一天的收益率来计算
        stock_chosen_mom.append((history_data['close'].iloc[-1] -
                                 history_data['open'].iloc[-1])/(
            history_data['open'].iloc[-1]))
    
    # 如果选出了股，按动量反转排名，全仓平均买入前max个
    # 按照动量最小的前max个下标来选取股票买入
    stocks = []    
    for i in np.argsort(stock_chosen_mom)[:g.arg_buy_max]:
        stocks.append(stock_chosen[i])
        
    log.info(f"可选 {stocks}")
        
    return stocks

# 分钟运行函数
def trade(context):
    g.hold_days += 1
    if g.hold_days < g.arg_hold_max:
        return
    
    stocks = get_stocks(context)

    # 逐股票操作：卖出，先卖再买才有钱
    if context.portfolio.positions:
        for stock in context.portfolio.positions.keys():
            # if stock in stocks:
            #     continue
            
            if stock == g.etf:
                continue

            order_target_value(stock, 0)
    
    # 低于个数就不买
    count_min = int(g.buy_min_ratio * g.arg_buy_max)
    if len(stocks) < count_min:
        if g.etf:
            order_value(g.etf, context.portfolio.available_cash)
        return

    val = context.portfolio.total_value / \
        (g.arg_buy_max - len(context.portfolio.positions))

    for stock in stocks:
        if len(context.portfolio.positions) >= g.arg_buy_max:
            break
        
        # 资金不够卖出黄金ETF
        if g.etf and context.portfolio.available_cash < val and g.etf in context.portfolio.positions:
            order_value(g.etf, -val)

        # 因为可能会隔天重复选股，不要紧，有钱的话继续买一份，之后按照最后一天选择的日期卖出
        order_value(stock, val)

    if len(context.portfolio.positions) > 0:
        g.hold_days = 0

    # 空闲资金买入黄金ETF
    if g.etf:
        order_value(g.etf, context.portfolio.available_cash)


def check_limit_up(context):
    now_time = context.current_dt

    # 对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
    for stock in g.yesterday_HL_list:
        current_data = get_price(stock, end_date=now_time, frequency='1m', fields=[
                                    'close', 'high_limit'], skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True)
        if current_data.iloc[0, 0] < current_data.iloc[0, 1]:
            log.info("[%s]涨停打开，卖出" % (stock))
            order_value(stock, 0)
        else:
            log.info("[%s]涨停，继续持有" % (stock))
            
    if g.etf:
        order_value(g.etf, context.portfolio.available_cash)
                
