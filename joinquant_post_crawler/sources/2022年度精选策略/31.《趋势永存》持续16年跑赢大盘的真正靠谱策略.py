# 克隆自聚宽文章：https://www.joinquant.com/post/36489
# 标题：《趋势永存》持续16年跑赢大盘的真正靠谱策略
# 作者：Ahfu

# 克隆自聚宽文章：https://www.joinquant.com/post/26035
# 标题：读《趋势永存：打败市场的动量策略》后的回测经历
# 作者：慕长风

from jqdata import *
import talib
import numpy as np


def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 规避未来数据
    set_option('avoid_future_data', True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 设置交易成本
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003,
                             close_commission=0.0003, min_commission=5), type='stock')
    # 初始化各类全局变量
    initial_config()
    # 每周交易一次
    run_weekly(trade, weekday=3, time='9:32')
    # 每两周调仓一次（根据波动风险率调整股票仓位）
    run_weekly(adjust_position, weekday=3, time='9:35')


def initial_config():
    log.set_level('order', 'error')
    g.index = "399300.XSHE"   #沪深300指数
    g.stock_momentum_day = 90
    g.stock_mean_day = 100
    g.index_mean_day = 200
    g.ATR_day = 20
    g.gap_threshold = 0.15  # 跳空缺口
    g.rank_threshold = 60   #取指数成分股前N支
    g.risk_factor = 0.001  # 每只股票风险因子，可用于控制持股数量
    g.position_threshold = 0.1  # 仓位差异阈值，按百分比计算
    g.cash_threshold = 500  # 可用资金阈值，低于该值不进行买入操作
    g.two_weekly = True #两周调仓一次

def trade(context):
    stock_hold = set(context.portfolio.positions.keys())
    stock_pool = get_stock_pool()

    # 卖出不符合要求的持仓
    for stock in stock_hold:
        if stock not in stock_pool or (not good_stock(stock)):   # 如果股票低于100日均线或者有15%的跳空上涨缺口，good_stock返回False，根据策略应该卖出
            order_target_value(stock, 0)
            log.info("%s 已不符合要求，平仓！" % stock)

    # 买入新的符合要求的股票
    if good_market_sentiment():
        for stock in stock_pool:
            cash = get_expected_position(stock, context)   #根据波动风险大小计算相应持仓
            if context.portfolio.available_cash > cash:
                result = order_target_value(stock, cash)
                if not result == None:
                    log.info("已买入 %s，金额：%f" %(stock,cash))
            else:
                return
    else:
        log.info("当前熊市，不买入任何股票")
        return

    # 按风险系数进行头寸再平衡（每两周进行一次）
def adjust_position(context):
    if g.two_weekly :
        stock_hold = set(context.portfolio.positions.keys())
        for stock in stock_hold:
            diff_value_rotio, now_value, expected_value = get_diff_position(stock, context)
            if diff_value_rotio > g.position_threshold :
                if context.portfolio.available_cash > expected_value-now_value :
                    result = order_target_value(stock, expected_value) 
                    if not result == None:
                        log.info("%s 已调仓，原市值 %f，现市值 %f" %(stock,now_value,expected_value))
                else:
                    log.info("%s 应该调仓，但无空闲资金" % stock )    
        g.two_weekly = False
    else:
        g.two_weekly = True   
        

    # 对g.index指数成分股按分数排序，倒序取前g.rank_threshold，然后过滤掉有问题的票（低于100日均线或者有15%的跳空上涨缺口）
def get_stock_pool():
    stock_rank = sorted([(stock, get_score(stock)) for stock in get_index_stocks(g.index)], key=lambda x: x[1], reverse=True)
    stock_pool_top = tuple(rank[0] for rank in stock_rank)[:g.rank_threshold]
    filtered_stock_pool = list(filter(good_stock, stock_pool_top))
    return filtered_stock_pool

    # 指数g.index低于g.index_mean_day日均线，则不再买入任何股票（书上策略是标普500指数低于200日均线）
def good_market_sentiment():
    close_data = attribute_history(
        g.index, g.index_mean_day, '1d', ['close']).close
    current_price = close_data[-1]
    average_price = close_data.mean()
    if current_price > average_price:
        return True
    else:
        return False


    # 根据ATR和风险因子计算股票的期望仓位
def get_expected_position(stock, context):
    data = attribute_history(stock, g.ATR_day+1, '1d',['high', 'low', 'close'])
    if np.any(data.isnull()):
        ATR = 1
    else:
        ATR = talib.ATR(data.high, data.low, data.close, timeperiod=g.ATR_day)[-1]
    stock_price = data.close[-1]
    expected_position = context.portfolio.total_value * g.risk_factor * stock_price / ATR
    return expected_position


    # 股票当前仓位、期望仓位、及两者的差异率
def get_diff_position(stock, context):
    expected_position = get_expected_position(stock, context)
    now_position = context.portfolio.positions[stock].value
    return abs(now_position / expected_position - 1), now_position, expected_position


    # 基于股票年化收益和判定系数打分
def get_score(stock):
    data = attribute_history(stock, g.stock_momentum_day, '1d', ['close'])
    y = data['log'] = np.log(data.close)
    x = data['num'] = np.arange(data.log.size)
    slope, intercept = np.polyfit(x, y, 1)
    annualized_returns = math.pow(math.exp(slope), 250) - 1
    r_squared = 1 - (sum((y - (slope * x + intercept))**2) / ((len(y) - 1) * np.var(y, ddof=1)))
    return annualized_returns * r_squared


    # 判断股票是否符合要求（当前价格高于g.stock_mean_day日均线、g.stock_mean_day日内无15%的跳空上涨缺口（A股有涨停机制，因此计算两天的跳空上涨幅度之和）
def good_stock(stock):
    data = attribute_history(stock, g.stock_mean_day, '1d', ['low', 'high', 'close'])
    data['gap'] = data.low / data.high.shift(2) - 1
    max_gap = data.gap.max()
    current_price = data.close[-1]
    average_price = data.close.mean()
    if current_price < average_price or max_gap > g.gap_threshold:
        return False
    else:
        return True
