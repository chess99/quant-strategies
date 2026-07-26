# 克隆自聚宽文章：https://www.joinquant.com/post/27636
# 标题：【复现】扩散指标择时
# 作者：Hugo2046

'''
N,N1,N2的参数是在全样本找的最优参数 <===后视镜

比研究文档中更为精细的是 统计的每日指数中扩散指标的数量 而非使用某个
时点成分股数据代替的数据

通过性能分析发现使用jqdata的技术指标提取速度实在坑爹....
禁用jqlib 自行计算roc

'''

from tqdm import *
from jqdata import *
#from jqlib.technical_analysis import *

import pandas as pd
import numpy as np

enable_profile()  # 开启性能分析


def initialize(context):

    set_params()
    set_variables()
    set_backtest()

    Preprocessing(context)

    run_daily(Trade, time='open', reference_security='000300.XSHG')


def set_params():

    g.index_symbol = '000300.XSHG'  # 目标指数
    g.target = '510300.XSHG'  # 标的

    g.weight_method = 'mktcap'  # 市值流通加权计算
    g.N = 100
    g.N1 = 90
    g.N2 = 30


def set_variables():

    g.singal = []  # 储存roc的统计个数


def set_backtest():

    set_option("avoid_future_data", True)  # 避免数据
    set_option("use_real_price", True)  # 真实价格交易
    set_benchmark('000300.XSHG')  # 设置基准
    #log.set_level("order", "debuge")
    log.set_level('order', 'error')

########################################################################################

# 每日盘前运行
def before_trading_start(context):

    # 手续费设置
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))

    # 根据不同的时间段设置手续费
    dt = context.current_dt

    if dt > datetime.datetime(2013, 1, 1):
        set_commission(PerTrade(buy_cost=0.0003, sell_cost=0.0013, min_cost=5))

    elif dt > datetime.datetime(2011, 1, 1):
        set_commission(PerTrade(buy_cost=0.001, sell_cost=0.002, min_cost=5))

    elif dt > datetime.datetime(2009, 1, 1):
        set_commission(PerTrade(buy_cost=0.002, sell_cost=0.003, min_cost=5))

    else:
        set_commission(PerTrade(buy_cost=0.003, sell_cost=0.004, min_cost=5))

########################################################################################

# 前序准备
def Preprocessing(context):

    bar_time = context.current_dt.date()

    target_info = get_security_info(g.target)
    
    g.begin_date = target_info.start_date
    
    log.info('标的:%s,标的类型:%s,成立时间:%s' %
             (target_info.name, target_info.type, g.begin_date))

    # 当标的为指数 那么会购买一揽子的成分股 此时使用preprocessing统计前序数据
    if bar_time >= g.begin_date or target_info.type == 'index':

        PrepareData(context)  # 计算前序期


# 数据准备
def PrepareData(context):

    log.info('计算前序期指标....')
    pre_date = context.previous_date

    limit = g.N1 + g.N2  # 前序计算期

    date_range = get_trade_days(end_date=pre_date, count=limit)  # 获取前序时间周期

    if date_range[0] < datetime.date(2005, 1, 1):
        log.info('前序期不足,jqdata最多再2005-01-01')

    roc_indicator = np.zeros(len(date_range))  # 数据储存

    # 设置进度条
    pbar = tqdm(total=len(date_range))
    pbar.set_description("Processing")

    for i, trade in enumerate(date_range):

        pbar.update(1)

        stocks = get_index_stocks(g.index_symbol, date=trade)

        # 获取ROC值 参数为N
        roc_indicator[i] = CalROCSingal(stocks, trade, g.N,
                                        g.weight_method)  # 多头信号是roc大于0

    pbar.close()  # 关闭进度条

    g.singal = roc_indicator  # 储存值全局变量
    
########################################################################################

# 计算储存当日数据
def GetSingal(context):

    if context.current_dt.date() == g.begin_date:

        log.info('当日为%s,begin_date为%s' %
                 (context.current_dt.date(), g.begin_date))

        fast_ma = rolling_average(g.singal, g.N1)  # 第一次平滑
        slow_ma = rolling_average(fast_ma, g.N2)  # 第二次平滑

        #log.info('fast_ma=>%.2f,slow_ma=>%.2f' % (fast_ma[-1], slow_ma[-1]))
        record(fast=fast_ma[-1], slow=slow_ma[-1])
        return fast_ma[-1] > slow_ma[-1]

    else:

        bar_time = context.previous_date
        stocks = get_index_stocks(g.index_symbol, date=bar_time)
        # 获取当日roc指标
        roc_indicator = CalROCSingal(stocks, bar_time, g.N, g.weight_method)
        g.singal = np.append(g.singal, roc_indicator)[1:]  # 更新singal

        # 计算快慢均线
        fast_ma = rolling_average(g.singal, g.N1)  # 第一次平滑
        slow_ma = rolling_average(fast_ma, g.N2)  # 第二次平滑

        #log.info('fast_ma=>%.2f,slow_ma=>%.2f' % (fast_ma[-1], slow_ma[-1]))
        record(fast=fast_ma[-1], slow=slow_ma[-1])
        return fast_ma[-1] > slow_ma[-1]

    
    

########################################################################################

# 获取stocks中roc大于0的个数
def CalROCSingal(stocks: list, watch_date: datetime.date, N: int,
                 weight_method: str) -> int:

    # 使用jqlib获取roc数据
    #roc_ser = pd.Series(
    #    ROC(stocks, watch_date, timeperiod=N, unit='1d', include_now=True))

    # 手动计算
    roc_ser = GetROC(stocks, watch_date, N)

    if weight_method == 'avg':

        return len(roc_ser[roc_ser > 0])  # 多头信号是roc大于0

    elif weight_method == 'mktcap':

        mkt_cap = get_valuation(
            stocks,
            end_date=watch_date,
            fields='circulating_market_cap',
            count=1)

        mkt_cap.set_index('code', inplace=True)
        weights = mkt_cap['circulating_market_cap'] / mkt_cap[
            'circulating_market_cap'].sum()

        mkt_roc = roc_ser[roc_ser>0] * weights
        return np.sum(mkt_roc)



# 手动计算roc
def GetROC(stocks: list, watch_date: datetime.date, N: int) -> pd.Series:

    offset_day = get_trade_days(end_date=watch_date, count=N)[0]

    now = get_price(
        stocks, end_date=watch_date, count=1, fields='close',
        panel=False).set_index('code')
    last = get_price(
        stocks, end_date=offset_day, count=1, fields='close',
        panel=False).set_index('code')

    # N日前不能为na & 不为0
    last = last[~last['close'].isna() & last['close'] != 0]

    return (now['close'] / last['close'] - 1).dropna()  # 返回roc

########################################################################################

# 等价于pd.rolling.mean
def rolling_average(arr: np.array, window: int) -> np.array:

    ret = np.cumsum(arr, dtype=float)

    ret[window:] = ret[window:] - ret[:-window]

    return ret[window - 1:] / window


########################################################################################

def Trade(context):

    bar_time = context.current_dt.date()

    if bar_time >= g.begin_date:

        if len(g.singal) == 0:

            PrepareData(context)

        flag = GetSingal(context)

        #log.info('执行交易,开平仓信号为%s' % flag)

        if flag:

            StockBuy(g.target, context)

        else:

            StockSell(g.target, context)




# 买入操作
def StockBuy(target: str, context):

    everyStocks = context.portfolio.total_value

    if target not in context.portfolio.long_positions:

        log.info('开仓买入%s' % target)

        order_target_value(target, everyStocks)


# 卖出操作
def StockSell(target: str, context):

    if target in context.portfolio.long_positions:

        log.info('平仓卖出%s' % target)

        order_target(target, 0)
