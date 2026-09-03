# ruff: noqa: F403, F405
"""科创50 ETF 固定 MACD(12, 26, 9) 日频择时策略。"""

import builtins

import numpy as np

try:
    from jqdata import *  # noqa: F403
except ImportError:
    pass


def initialize(context):
    """设置固定参数、交易成本和开盘调度。"""

    set_benchmark("588000.XSHG")
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

    g.security = "588000.XSHG"
    g.fast_period = 12
    g.slow_period = 26
    g.signal_period = 9
    g.history_start = "2020-11-16"
    g.target_weight = 0.99

    # 开盘时只能使用上一交易日及更早的完整日线。
    run_daily(rebalance, time="open")


def exponential_moving_average(values, period):
    """复现 pandas ewm(span=period, adjust=False, min_periods=period)。"""

    if period <= 0:
        raise ValueError("EMA 周期必须为正数")
    array = np.asarray(values, dtype=float)
    result = np.full(len(array), np.nan, dtype=float)
    alpha = 2.0 / (period + 1.0)
    ema_value = None
    valid_count = 0

    for index in range(len(array)):
        value = array[index]
        if not np.isfinite(value):
            continue
        if ema_value is None:
            ema_value = value
        else:
            ema_value = alpha * value + (1.0 - alpha) * ema_value
        valid_count += 1
        if valid_count >= period:
            result[index] = ema_value
    return result


def macd_components(close_values, fast=12, slow=26, signal=9):
    """返回 DIFF、DEA 和柱值；参数口径与本仓库研究保持一致。"""

    if fast <= 0 or slow <= fast or signal <= 0:
        raise ValueError("MACD 参数必须满足 0 < fast < slow 且 signal > 0")
    close = np.asarray(close_values, dtype=float)
    fast_ema = exponential_moving_average(close, fast)
    slow_ema = exponential_moving_average(close, slow)
    difference = fast_ema - slow_ema
    signal_line = exponential_moving_average(difference, signal)
    return difference, signal_line, difference - signal_line


def latest_macd_signal(close_values, fast=12, slow=26, signal=9):
    """返回最新持有状态及 DIFF/DEA；数据不足时状态为 None。"""

    difference, signal_line, _ = macd_components(close_values, fast, slow, signal)
    if len(difference) == 0:
        return None, np.nan, np.nan
    latest_difference = difference[-1]
    latest_signal = signal_line[-1]
    if not np.isfinite(latest_difference) or not np.isfinite(latest_signal):
        return None, latest_difference, latest_signal
    return bool(latest_difference > latest_signal), latest_difference, latest_signal


def load_close_history(security, history_start, observation_date):
    """读取上市以来、截至观察日的完整收盘价。"""

    frame = get_price(
        security,
        start_date=history_start,
        end_date=observation_date,
        frequency="daily",
        fields=["close"],
        skip_paused=False,
        fq="pre",
        panel=False,
    )
    if frame is None or frame.empty or "close" not in frame.columns:
        return np.array([], dtype=float)
    return frame["close"].dropna().astype(float).values


def can_buy(snapshot):
    return (
        not snapshot.paused
        and not snapshot.is_st
        and snapshot.last_price > 0
        and snapshot.last_price < snapshot.high_limit
    )


def can_sell(snapshot):
    return (
        not snapshot.paused
        and snapshot.last_price > 0
        and snapshot.last_price > snapshot.low_limit
    )


def affordable_round_lot(budget, price):
    """按 100 份一手向下取整，绝不超过给定预算。"""

    if budget <= 0 or price <= 0 or not np.isfinite(price):
        return 0
    return int(budget / price / 100.0) * 100


def current_amount(context, security):
    positions = context.portfolio.positions
    if security not in positions:
        return 0
    return positions[security].total_amount


def rebalance(context):
    """以上一交易日收盘信号，在下一交易日开盘切换仓位。"""

    observation_date = context.previous_date
    close = load_close_history(g.security, g.history_start, observation_date)
    bullish, difference, signal_line = latest_macd_signal(
        close,
        g.fast_period,
        g.slow_period,
        g.signal_period,
    )
    if bullish is None:
        log.warning("MACD 历史数据不足，保留当前仓位")
        return

    record(
        macd_diff=float(difference),
        macd_dea=float(signal_line),
        target_weight=g.target_weight if bullish else 0.0,
    )

    amount = current_amount(context, g.security)
    current_data = get_current_data()
    snapshot = current_data[g.security]

    if bullish:
        if amount > 0:
            return
        if not can_buy(snapshot):
            log.warning("%s 当前不可买入" % g.security)
            return
        budget = context.portfolio.total_value * g.target_weight
        target_amount = affordable_round_lot(budget, snapshot.last_price)
        if target_amount <= 0:
            log.warning("账户资金不足以买入 100 份 %s" % g.security)
            return
        order_target(g.security, target_amount)
        return

    if amount <= 0:
        return
    if not can_sell(snapshot):
        log.warning("%s 当前不可卖出，将在下一交易日重试" % g.security)
        return
    order_target(g.security, 0)
