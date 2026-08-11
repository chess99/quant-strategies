# 克隆自聚宽文章：https://www.joinquant.com/post/24591
# 标题：“开弓”ETF轮动模型——改
# 作者：jqz1226

# 克隆自聚宽文章：https://www.joinquant.com/post/24563
# 标题：借鉴鼎级版主明镜台“开弓”ETF轮动模型
# 作者：purplefire

# 导入函数库
import pandas as pd
import talib
from jqdata import *


# 初始化函数，设定基准等等
def initialize(context):
    # 基准:中证500
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 设定成交量比例
    # set_option('order_volume_ratio', 1)
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')
    # 交易手续费
    # set_order_cost(OrderCost(close_tax=0.0, open_commission=0.000025, close_commission=0.000025, min_commission=1),
    #                type='etf')

    g.stocks = ['510050.XSHG', '510500.XSHG', '159901.XSHE', '159902.XSHE', '159915.XSHE']  # , '512880.XSHG']
    # g.num_to_buy = 1  # 持仓的只数
    g.codes = ''  # 要买入的etf

    # 运行函数, 按周运行，在每周第一个交易日运行
    run_daily(tkdk, time='9:35')  # 跳空低开未上拉就止损
    run_daily(tkdk, time='10:30')  #
    run_daily(tkdk, time='13:00')  #
    run_daily(tkdk, time='14:00')  #
    run_daily(chenk_stocks, time='14:25')  # 选股
    run_daily(trade, time='14:30')  # 交易


def chenk_stocks(context):
    jz_pj = {}
    for sec in g.stocks:
        close_sec1w = get_bars(sec, count=9, unit='1w', include_now=True, fields=['close'])['close']
        if len(close_sec1w) >= 9:
            # 周涨幅：1周，2周，3周，4周，8周
            wzf1 = close_sec1w[-1] / close_sec1w[-2] - 1
            wzf2 = close_sec1w[-1] / close_sec1w[-3] - 1
            wzf3 = close_sec1w[-1] / close_sec1w[-4] - 1
            wzf4 = close_sec1w[-1] / close_sec1w[-5] - 1
            wzf5 = close_sec1w[-1] / close_sec1w[-9] - 1
            # 计算评分
            cp = wzf1 * 0.4 + wzf2 * 0.2 + wzf3 * 0.15 + wzf4 * 0.2 + wzf5 * 0.05
            jz_pj[sec] = cp
    # 按评分从高到低排序，选择前g.num_to_buy名
    # g.codes 要买入的etf
    g.codes = pd.Series(jz_pj).sort_values(ascending=False).index[0]


# 跳空低开止损
def tkdk(context):
    for stock in context.portfolio.positions:
        bars = get_bars(stock, count=6, unit='1d', include_now=True, fields=['close', 'low', 'high'])
        #
        ma5 = bars['close'][-5:].mean()  # 今天的ma5
        ma5_r1 = bars['close'][-6:-1].mean()  # 昨天的ma5
        llv5_r1 = bars['low'][-6:-1].min()  # 过去5天的最低价
        last_low = bars['low'][-2]  # 昨日最低
        now_high = bars['high'][-1]  # 今天最高
        now_close = bars['close'][-1]  # 当前价位
        #
        if now_close < ma5 < ma5_r1 and (now_close / now_high < 0.975 or now_close < llv5_r1) and now_high <= last_low:
            log.info('跳空低开止损：%s, 当前价:%.3f, 今日最高: %.3f, 今日ma5: %.3f, 昨最低价: %.3f, 昨日ma5: %.3f, 昨日LLV5: %.3f' %
                     (stock, now_close, now_high, ma5, last_low, ma5_r1, llv5_r1))
            order_target(stock, 0)


# 交易
def trade(context):
    # 只考虑持仓一个品种，入选一个品种的情形
    # 1. 新入选的品种是否符合买入条件
    code1 = g.codes
    #
    close = get_bars(code1, count=120, unit='1d', include_now=True, fields=['close'])['close']
    #
    ma5 = close[-5:].mean()
    ma5_r1 = close[-6:-1].mean()
    ma10 = close[-10:].mean()
    ma12 = close[-12:].mean()
    ma12_r1 = close[-13:-1].mean()
    ma20 = close[-20:].mean()
    #
    ma120 = close.mean()
    bias2 = (close[-1] - ma12) / ma12 * 100
    bias2_r1 = (close[-2] - ma12_r1) / ma12_r1 * 100
    ema12 = talib.EMA(close, 12)

    # code1强势，可追涨
    code1_strong = (ma20 < ma10 < ma5 < close[-1] and
                    bias2 > bias2_r1 and
                    ema12[-1] >= ema12[-2] and
                    close[-1] / ma5 < 1.1 and
                    (close[-1] > ma120 or (close[-1] < ma120 and ma5 > ma5_r1)))

    # code1超跌，可抄底
    code1_weak = (close[-1] / ma5 < 0.88)

    # code1违背了类型2的持仓条件
    code1_type2_bad = (close[-1] < close[-2])

    # code1违背了类型1的持仓条件
    code1_type1_bad = (close[-1] < ma10 and close[-2] < ma10) or \
                      close[-1] / ma5 >= 1.1 or \
                      (ema12[-1] < ema12[-2] and ema12[-1] / ema12[-2] < 0.997)
    # 卖出
    if len(context.portfolio.positions) > 0:  # 有持仓
        stock = list(context.portfolio.positions.keys())[0]  # 持仓的唯一一只etf的代码
        if stock != code1:
            if code1_strong or code1_weak:
                log.info('新品:%s符合买入条件，卖出：%s' % (code1, stock))
                order_target(stock, 0)
        else:  # stock == code1
            if g.ordertype == 2 and code1_type2_bad:
                log.info('类型2止损:%s' % stock)
                order_target(stock, 0)
            if g.ordertype == 1:
                if code1_type1_bad or close[-1] / context.portfolio.positions[stock].avg_cost < 0.95:
                    log.info('类型1止损:%s' % stock)
                    order_target(stock, 0)

    # 买入
    if len(context.portfolio.positions) > 0:
        return  # 有票就不再买了
    else:
        if code1_weak:  # 超跌，抄底
            log.info('类型2买入:%s' % code1)
            order_value(code1, context.portfolio.available_cash)
            g.ordertype = 2
        elif code1_strong:  # 强势，追涨
            log.info('类型1买入:%s' % code1)
            order_value(code1, context.portfolio.available_cash)
            g.ordertype = 1
