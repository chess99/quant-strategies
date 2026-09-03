# ruff: noqa: F403, F405
"""科创50 ETF 风险型低换手技术择时策略。"""

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
    g.trend_period = 200
    g.volatility_period = 60
    g.target_volatility = 0.15
    g.rebalance_threshold = 0.05
    g.maximum_weight = 0.99
    g.pending_target_weight = None

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
    rebalance_threshold=0.05,
    maximum_weight=0.99,
):
    """按完整收盘价历史计算风险核心及低换手目标。"""

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
    target = raw.where(close > moving_average, 0.0).fillna(0.0)
    return apply_rebalance_threshold(
        target.to_numpy(),
        rebalance_threshold,
        maximum_weight,
    )


def latest_target_weights(close_values):
    """返回观察日目标与前一观察日目标；历史不足时返回空状态。"""

    close = np.asarray(close_values, dtype=float)
    if len(close) < 200:
        return None, None
    targets = risk_core_targets(close)
    previous = targets[-2] if len(targets) >= 2 else None
    return float(targets[-1]), None if previous is None else float(previous)


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
    return frame.sort_index()["close"].dropna().astype(float).values


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
    close = load_close_history(g.security, g.history_start, observation_date)
    target_weight, previous_target_weight = latest_target_weights(close)
    if target_weight is None:
        log.warning("风险目标历史数据不足，保留当前仓位")
        return

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
