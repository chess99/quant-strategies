# ruff: noqa: F403, F405
"""多资产 ETF 动量 + EPO：带确定性等权安全回退的聚宽月频基线。"""

import builtins
import math

import numpy as np
import pandas as pd

try:
    from jqdata import *  # noqa: F403
except ImportError:
    pass


ETF_POOL = (
    "518880.XSHG",
    "159985.XSHE",
    "513100.XSHG",
    "510300.XSHG",
    "159915.XSHE",
    "159992.XSHE",
    "515700.XSHG",
    "510150.XSHG",
    "515790.XSHG",
    "515880.XSHG",
    "512720.XSHG",
    "512660.XSHG",
    "159740.XSHE",
)
MOMENTUM_DAYS = 34
STOCK_NUM = 3
EPO_W = 0.2
PRICE_HISTORY_DAYS = 1200


def initialize(context):
    set_benchmark("000300.XSHG")
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)
    set_slippage(PriceRelatedSlippage(0.0005))
    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=0,
            open_commission=0.0003,
            close_commission=0.0003,
            close_today_commission=0,
            min_commission=5,
        ),
        type="fund",
    )
    log.set_level("order", "error")
    run_monthly(rebalance, 1, time="open")


def momentum_score(close, days=MOMENTUM_DAYS):
    values = pd.to_numeric(close, errors="coerce").dropna().tail(days).values.astype(float)
    if len(values) != days or np.any(values <= 0.0):
        return float("nan")
    y = np.log(values)
    x = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    denominator = float(np.sum((y - y.mean()) ** 2))
    if denominator <= 0.0:
        return float("nan")
    r_squared = 1.0 - float(np.sum((y - fitted) ** 2)) / denominator
    return float((math.exp(slope * 250.0) - 1.0) * r_squared)


def epo_weights(returns, w=EPO_W):
    """复现冻结 anchored/endogenous EPO；lambda 在该分支中不参与计算。"""

    if returns.empty or returns.shape[1] == 0:
        raise ValueError("EPO returns must not be empty")
    covariance = returns.cov()
    variances = np.diag(covariance.values.astype(float))
    if not np.isfinite(variances).all() or np.any(variances <= 0.0):
        raise ValueError("EPO covariance contains non-positive variance")
    correlation = returns.corr().values.astype(float)
    if not np.isfinite(correlation).all():
        raise ValueError("EPO correlation contains non-finite values")
    identity = np.eye(len(variances))
    diagonal_variance = np.diag(variances)
    standard_deviation = np.diag(np.sqrt(variances))
    shrunk_correlation = (1.0 - w) * correlation + w * identity
    shrunk_covariance = standard_deviation @ shrunk_correlation @ standard_deviation
    inverse = np.linalg.solve(shrunk_covariance, identity)
    signal = returns.mean().values.astype(float)
    anchor = (1.0 / variances) / np.sum(1.0 / variances)
    numerator = float(np.sqrt(anchor.T @ shrunk_covariance @ anchor))
    denominator = float(
        np.sqrt(signal.T @ inverse @ shrunk_covariance @ inverse @ signal)
    )
    if denominator <= 0.0 or not np.isfinite(denominator):
        raise ValueError("EPO endogenous gamma denominator is invalid")
    gamma = numerator / denominator
    raw = inverse @ ((1.0 - w) * gamma * signal + w * diagonal_variance @ anchor)
    clipped = np.clip(raw, 0.0, None)
    if clipped.sum() <= 0.0:
        raise ValueError("EPO produced no positive weights")
    return pd.Series(clipped / clipped.sum(), index=returns.columns, dtype=float)


def build_target_weights(
    close,
    observation_date,
    momentum_days=MOMENTUM_DAYS,
    stock_num=STOCK_NUM,
    epo_w=EPO_W,
    price_history_days=PRICE_HISTORY_DAYS,
):
    observation = pd.Timestamp(observation_date).normalize()
    history = close.loc[close.index <= observation]
    if history.empty:
        return {}, {"observation_date": observation.strftime("%Y-%m-%d"), "reason": "no_history"}
    available = [
        symbol
        for symbol in close.columns
        if history[symbol].notna().any()
        and pd.notna(history[symbol].dropna().index.max())
        and history[symbol].dropna().index.max() == history.index[-1]
    ]
    scores = {
        symbol: momentum_score(history[symbol], momentum_days) for symbol in available
    }
    ranked = sorted(
        (
            (symbol, score)
            for symbol, score in scores.items()
            if np.isfinite(score) and score > 0.0
        ),
        key=lambda item: (-item[1], item[0]),
    )
    selected = [symbol for symbol, _ in ranked[:stock_num]]
    diagnostics = {
        "observation_date": observation.strftime("%Y-%m-%d"),
        "selected": selected,
        "scores": {
            symbol: float(score) if np.isfinite(score) else None
            for symbol, score in scores.items()
        },
        "fallback_used": False,
    }
    if not selected:
        weights = {}
    else:
        price_window = history[selected].tail(price_history_days).ffill()
        returns = price_window.pct_change(fill_method=None).dropna(how="any")
        if len(returns) < 60:
            weights = {}
            diagnostics["reason"] = "insufficient_common_returns"
        else:
            try:
                weights = epo_weights(returns, w=epo_w).to_dict()
            except ValueError as exc:
                if str(exc) != "EPO produced no positive weights":
                    raise
                weights = {symbol: 1.0 / len(selected) for symbol in selected}
                diagnostics["fallback_used"] = True
                diagnostics["fallback_reason"] = str(exc)
            diagnostics["common_return_days"] = len(returns)
    diagnostics["weights"] = {
        symbol: float(weight) for symbol, weight in weights.items()
    }
    return weights, diagnostics


def normalize_close_frame(raw):
    if raw is None:
        return pd.DataFrame()
    if isinstance(raw, pd.DataFrame):
        frame = raw.copy()
        if {"time", "code", "close"}.issubset(frame.columns):
            frame["time"] = pd.to_datetime(frame["time"])
            return frame.pivot(index="time", columns="code", values="close").sort_index()
        if {"date", "code", "close"}.issubset(frame.columns):
            frame["date"] = pd.to_datetime(frame["date"])
            return frame.pivot(index="date", columns="code", values="close").sort_index()
        if "close" not in frame.columns:
            frame.index = pd.to_datetime(frame.index)
            return frame.sort_index()
    close = raw["close"]
    if isinstance(close, pd.Series):
        close = close.to_frame()
    close = close.copy()
    close.index = pd.to_datetime(close.index)
    return close.sort_index()


def target_weights_for_date(observation_date):
    raw = get_price(
        list(ETF_POOL),
        end_date=observation_date,
        count=PRICE_HISTORY_DAYS,
        frequency="daily",
        fields=["close"],
        skip_paused=False,
        fq="pre",
        panel=False,
    )
    close = normalize_close_frame(raw)
    return build_target_weights(close, observation_date)


def can_sell(snapshot):
    return (
        not snapshot.paused
        and snapshot.last_price > 0
        and snapshot.last_price > snapshot.low_limit
    )


def can_buy(snapshot):
    return (
        not snapshot.paused
        and not snapshot.is_st
        and snapshot.last_price > 0
        and snapshot.last_price < snapshot.high_limit
    )


def positive_positions(context):
    return [
        code
        for code in context.portfolio.positions
        if context.portfolio.positions[code].total_amount > 0
    ]


def rebalance(context):
    """上一交易日生成信号；卖出路径不可执行时整次调仓失败关闭。"""

    target_weights, diagnostics = target_weights_for_date(context.previous_date)
    log.info(
        "EPO_TARGET observation=%s selected=%s weights=%s fallback=%s"
        % (
            diagnostics.get("observation_date"),
            diagnostics.get("selected"),
            target_weights,
            diagnostics.get("fallback_used"),
        )
    )
    current = positive_positions(context)
    current_data = get_current_data()
    sells = [code for code in current if code not in target_weights]
    for code in sells:
        snapshot = current_data[code]
        if not can_sell(snapshot):
            log.warning("无法卖出 %s，取消本次全部调仓" % code)
            return
    for code in sells:
        if order_target_value(code, 0) is None:
            log.warning("卖出 %s 下单失败，取消本次买入" % code)
            return

    total_value = float(context.portfolio.total_value)
    for code, weight in sorted(target_weights.items()):
        snapshot = current_data[code]
        if not can_buy(snapshot):
            log.warning("目标 ETF %s 当前不可买入，保留对应现金" % code)
            continue
        target_value = total_value * float(weight)
        if target_value < snapshot.last_price * 100:
            log.warning("目标 ETF %s 金额不足一手，保留对应现金" % code)
            continue
        order_target_value(code, target_value)


def frozen_weight_sum(weights):
    """供平台预检日志使用，避免 jqdata 覆盖内建 sum。"""

    return builtins.sum(weights.values())
