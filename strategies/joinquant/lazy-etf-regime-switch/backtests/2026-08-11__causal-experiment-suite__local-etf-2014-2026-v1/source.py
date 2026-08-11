"""懒人 ETF 跨资产状态切换：严格因果的聚宽周频基线。"""

import builtins

import numpy as np
import pandas as pd

try:
    from jqdata import *  # noqa: F403
except ImportError:
    pass


def initialize(context):
    set_benchmark("513100.XSHG")
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)
    log.set_level("order", "error")
    set_slippage(PriceRelatedSlippage(0.0002))
    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=0,
            open_commission=0.0003,
            close_commission=0.0003,
            min_commission=5,
        ),
        type="fund",
    )

    g.gem_etf = "159915.XSHE"
    g.nasdaq_etf = "513100.XSHG"
    g.gold_etf = "518880.XSHG"
    g.gem_index = "399006.XSHE"
    g.cci_period = 14
    g.cci_threshold = 130
    g.ma_period = 45

    # 每周首个交易日开盘运行；context.previous_date 是上一周最后交易日。
    run_weekly(rebalance, weekday=1, time="open")


def calc_close_cci(close_values, period=14):
    """原策略仅用周收盘价计算的非标准 CCI。"""

    values = np.asarray(close_values, dtype=float)
    if len(values) < period:
        return 0.0
    sample = values[-period:]
    mean = float(np.mean(sample))
    mean_deviation = float(np.mean(np.abs(sample - mean)))
    if mean_deviation == 0:
        return 0.0
    return float((sample[-1] - mean) / (0.015 * mean_deviation))


def above_ma(close_values, period=45):
    values = np.asarray(close_values, dtype=float)
    if len(values) < period:
        return False
    return bool(values[-1] > np.mean(values[-period:]))


def get_weekly_close(security, bar_count, end_date):
    """只读取观察日及更早日线，并聚合成交易周收盘价。"""

    frame = get_price(
        security,
        end_date=end_date,
        frequency="daily",
        fields=["close"],
        count=bar_count * 8,
        skip_paused=False,
        panel=False,
    )
    if frame is None or frame.empty:
        return np.array([])
    frame = frame.copy()
    frame.index = pd.to_datetime(frame.index)
    weekly = frame["close"].resample("W-FRI").last().dropna()
    return weekly.values


def select_target(observation_date):
    needed = builtins.max(g.cci_period, g.ma_period) + 5
    gem_close = get_weekly_close(g.gem_index, needed, observation_date)
    if calc_close_cci(gem_close, g.cci_period) > g.cci_threshold:
        return g.gem_etf

    nasdaq_close = get_weekly_close(g.nasdaq_etf, needed, observation_date)
    if above_ma(nasdaq_close, g.ma_period):
        return g.nasdaq_etf

    gold_close = get_weekly_close(g.gold_etf, needed, observation_date)
    if above_ma(gold_close, g.ma_period):
        return g.gold_etf
    return None


def can_sell(snapshot):
    return not snapshot.paused and snapshot.last_price > snapshot.low_limit


def can_buy(snapshot):
    return (
        not snapshot.paused
        and not snapshot.is_st
        and snapshot.last_price < snapshot.high_limit
        and snapshot.last_price > 0
    )


def positive_positions(context):
    return [
        code
        for code in context.portfolio.positions
        if context.portfolio.positions[code].total_amount > 0
    ]


def rebalance(context):
    """用上一交易日收盘信号，在本周首个交易日开盘切换。"""

    observation_date = context.previous_date
    target = select_target(observation_date)
    current = positive_positions(context)
    if len(current) == 1 and current[0] == target:
        return

    current_data = get_current_data()
    for code in current:
        if code == target:
            continue
        snapshot = current_data[code]
        if not can_sell(snapshot):
            log.warning("无法卖出 %s，取消本次切换" % code)
            return
        order_target(code, 0)

    remaining = [code for code in positive_positions(context) if code != target]
    if remaining:
        log.warning("旧持仓未清空，取消买入新标的")
        return
    if target is None:
        return

    snapshot = current_data[target]
    if not can_buy(snapshot):
        log.warning("目标 ETF %s 当前不可买入" % target)
        return
    target_value = context.portfolio.total_value * 0.99
    if target_value >= snapshot.last_price * 100:
        order_target_value(target, target_value)

