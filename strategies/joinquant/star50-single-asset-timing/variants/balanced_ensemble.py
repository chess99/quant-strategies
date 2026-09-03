# ruff: noqa: F403, F405
"""科创50 ETF 固定三机制平衡型低换手择时策略。"""

import builtins
import math

import numpy as np
import pandas as pd

try:
    from jqdata import *  # noqa: F403
except ImportError:
    pass


def initialize(context):
    """设置冻结参数、交易成本和开盘调度。"""

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
    g.history_start = "2020-11-16"
    g.rebalance_threshold = 0.10
    g.pending_target_weight = None
    g.insufficient_history_warned = False

    run_daily(rebalance, time="open")


def apply_rebalance_threshold(target_values, threshold, maximum_weight=0.99):
    """复现冻结研究的目标仓位最小变化阈值。"""

    values = np.asarray(target_values, dtype=float)
    if threshold <= 0.0:
        clean = values.copy()
        clean[~np.isfinite(clean)] = 0.0
        return np.clip(clean, 0.0, maximum_weight)

    held = None
    output = []
    for desired in values:
        if not np.isfinite(desired):
            desired = 0.0
        desired = min(max(float(desired), 0.0), maximum_weight)
        if held is None or desired <= 1e-12 or held <= 1e-12:
            held = desired
        elif abs(desired - held) >= threshold:
            held = desired
        output.append(held)
    return np.asarray(output, dtype=float)


def risk_core_targets(
    close_values,
    trend_period=200,
    volatility_period=60,
    target_volatility=0.15,
    maximum_weight=0.99,
):
    """计算未经调仓阈值过滤的连续风险核心目标。"""

    close = pd.Series(np.asarray(close_values, dtype=float))
    moving_average = close.rolling(
        trend_period,
        min_periods=trend_period,
    ).mean()
    realized_volatility = (
        close.pct_change()
        .rolling(volatility_period, min_periods=volatility_period)
        .std(ddof=1)
        * math.sqrt(252.0)
    )
    raw = (target_volatility / realized_volatility.replace(0.0, np.nan)).clip(
        lower=0.0,
        upper=maximum_weight,
    )
    return raw.where(close > moving_average, 0.0).fillna(0.0).values


def exponential_moving_average(values, period):
    """复现研究中的pandas EWM口径。"""

    return (
        pd.Series(np.asarray(values, dtype=float))
        .ewm(span=period, adjust=False, min_periods=period)
        .mean()
        .values
    )


def macd_gate(close_values, fast=12, slow=26, signal=9):
    """返回固定MACD开启状态，开启为1，关闭为0。"""

    close = np.asarray(close_values, dtype=float)
    difference = exponential_moving_average(close, fast) - exponential_moving_average(
        close,
        slow,
    )
    signal_line = exponential_moving_average(difference, signal)
    return (difference > signal_line).astype(float)


def average_true_range(frame, period=20):
    """按Wilder EWM口径计算ATR。"""

    prices = frame[["high", "low", "close"]].astype(float).reset_index(drop=True)
    previous_close = prices["close"].shift(1)
    true_range = pd.concat(
        [
            prices["high"] - prices["low"],
            (prices["high"] - previous_close).abs(),
            (prices["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return (
        true_range.ewm(
            alpha=1.0 / period,
            adjust=False,
            min_periods=period,
        )
        .mean()
        .values
    )


def stateful_gate(entry_values, exit_values):
    """根据进入和退出条件生成0/1持有状态。"""

    state = 0.0
    output = []
    for entry, exit_signal in zip(entry_values, exit_values):
        if state <= 0.0 and bool(entry):
            state = 1.0
        elif state > 0.0 and bool(exit_signal):
            state = 0.0
        output.append(state)
    return np.asarray(output, dtype=float)


def keltner_gate(frame, period=20, multiplier=2.0):
    """返回固定Keltner突破状态。"""

    prices = frame[["high", "low", "close"]].astype(float).reset_index(drop=True)
    close = prices["close"].values
    middle = exponential_moving_average(close, period)
    upper = middle + multiplier * average_true_range(prices, period)
    return stateful_gate(close > upper, close < middle)


def fixed_ensemble_raw_targets(frame):
    """固定等权合成风险核心、MACD覆盖和Keltner覆盖。"""

    prices = frame[["high", "low", "close"]].astype(float).reset_index(drop=True)
    close = prices["close"].values
    core = risk_core_targets(close)
    macd_overlay = core * (0.25 + 0.75 * macd_gate(close))
    keltner_overlay = core * (0.25 + 0.75 * keltner_gate(prices))
    return (core + macd_overlay + keltner_overlay) / 3.0


def balanced_ensemble_targets(frame, rebalance_threshold=0.10):
    """计算固定三机制组合并应用10个百分点调仓阈值。"""

    raw = fixed_ensemble_raw_targets(frame)
    return apply_rebalance_threshold(raw, rebalance_threshold, 0.99)


def latest_target_weights(frame):
    """返回观察日目标与前一观察日目标；历史不足时返回空状态。"""

    if frame is None or len(frame) < 200:
        return None, None
    targets = balanced_ensemble_targets(frame)
    previous = targets[-2] if len(targets) >= 2 else None
    return float(targets[-1]), None if previous is None else float(previous)


def load_price_history(security, history_start, observation_date):
    """读取上市以来、截至观察日的完整OHLC。"""

    frame = get_price(
        security,
        start_date=history_start,
        end_date=observation_date,
        frequency="daily",
        fields=["high", "low", "close"],
        skip_paused=False,
        fq="pre",
        panel=False,
    )
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["high", "low", "close"])
    required = {"high", "low", "close"}
    if not required.issubset(frame.columns):
        return pd.DataFrame(columns=["high", "low", "close"])
    return frame.sort_index()[["high", "low", "close"]].dropna().astype(float)


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
    """按100份一手向下取整，绝不超过给定预算。"""

    if budget <= 0 or price <= 0 or not np.isfinite(price):
        return 0
    return int(budget / price / 100.0) * 100


def current_amount(context, security):
    positions = context.portfolio.positions
    if security not in positions:
        return 0
    return positions[security].total_amount


def should_submit_order(current_shares, target_weight, previous_target_weight):
    """目标变化时下单；受阻的首次建仓和清仓继续重试。"""

    if previous_target_weight is None:
        return True
    if abs(target_weight - previous_target_weight) > 1e-12:
        return True
    if target_weight <= 1e-12:
        return current_shares > 0
    return current_shares <= 0


def rebalance(context):
    """以上一交易日冻结目标，在下一交易日开盘调仓。"""

    observation_date = context.previous_date
    frame = load_price_history(g.security, g.history_start, observation_date)
    target_weight, previous_target_weight = latest_target_weights(frame)
    if target_weight is None:
        if not g.insufficient_history_warned:
            log.warning("平衡型目标历史数据不足，至少需要200个交易日；热身期不交易")
            g.insufficient_history_warned = True
        return
    g.insufficient_history_warned = False

    record(target_weight=float(target_weight))

    amount = current_amount(context, g.security)
    if should_submit_order(amount, target_weight, previous_target_weight):
        g.pending_target_weight = target_weight
    if g.pending_target_weight is None:
        return

    current_data = get_current_data()
    snapshot = current_data[g.security]
    price = float(snapshot.last_price)
    target_amount = affordable_round_lot(
        context.portfolio.total_value * g.pending_target_weight,
        price,
    )
    if target_amount == amount:
        g.pending_target_weight = None
        return

    if target_amount > amount and not can_buy(snapshot):
        log.warning("%s 当前不可买入，将在下一交易日重试" % g.security)
        return
    if target_amount < amount and not can_sell(snapshot):
        log.warning("%s 当前不可卖出，将在下一交易日重试" % g.security)
        return

    order = order_target(g.security, target_amount)
    if order is not None:
        g.pending_target_weight = None
