"""系统比较科创 50 ETF 单标的技术择时家族。"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import shutil
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


def _find_repo_root(path: Path) -> Path:
    for candidate in (path, *path.parents):
        if (candidate / "src" / "quant_research").is_dir():
            return candidate
    raise RuntimeError("无法找到仓库根目录")


SOURCE_PATH = Path(__file__).resolve()
ROOT = _find_repo_root(SOURCE_PATH.parent)
STUDY_DIR = ROOT / "studies" / "star50-single-asset-timing"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.backtest import (  # noqa: E402
    BacktestConfig,
    CostModel,
    DailyBacktester,
    performance_metrics,
)


SYMBOL = "SH588000"
TARGET_WEIGHT = 0.99
INITIAL_CASH = 1_000_000.0
TRADING_DAYS = 252
BASE_COMMISSION = 0.0003
BASE_SLIPPAGE = 0.0002
STRESS_SLIPPAGES = (0.0010, 0.0020)
WARMUP_SESSIONS = 252
INITIAL_TRAIN_SESSIONS = 504
TEST_SESSIONS = 63
MINIMUM_FINAL_TEST_SESSIONS = 21
FAMILY_ORDER = (
    "sma-price",
    "ema-price",
    "dual-ma",
    "macd-cross",
    "trix",
    "adx-dmi",
    "aroon",
    "supertrend",
    "tsmom-monthly",
    "donchian",
    "bollinger-breakout",
    "keltner-breakout",
    "rsi-reversion",
    "stochastic-reversion",
    "cci-reversion",
    "bollinger-reversion",
    "mfi-reversion",
    "obv-trend",
    "vol-target-trend",
    "indicator-vote",
)
FAMILY_LABELS = {
    "sma-price": "价格 / SMA 趋势",
    "ema-price": "价格 / EMA 趋势",
    "dual-ma": "快慢均线交叉",
    "macd-cross": "MACD 交叉",
    "trix": "TRIX 趋势",
    "adx-dmi": "ADX + DMI 趋势强度",
    "aroon": "Aroon 趋势时点",
    "supertrend": "Supertrend ATR 趋势",
    "tsmom-monthly": "月频时间序列动量",
    "donchian": "Donchian 突破",
    "bollinger-breakout": "布林带突破",
    "keltner-breakout": "Keltner 突破",
    "rsi-reversion": "RSI 反转",
    "stochastic-reversion": "随机指标反转",
    "cci-reversion": "CCI 反转",
    "bollinger-reversion": "布林带反转",
    "mfi-reversion": "MFI 量价反转",
    "obv-trend": "OBV 量价趋势",
    "vol-target-trend": "波动率目标趋势",
    "indicator-vote": "多指标趋势投票",
}


@dataclass(frozen=True)
class StrategyConfig:
    family: str
    name: str
    params: dict
    canonical: bool = False


@dataclass
class SimulationResult:
    name: str
    equity: pd.DataFrame
    trades: pd.DataFrame
    orders: pd.DataFrame
    decisions: pd.DataFrame
    metrics: dict


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _value_slug(value) -> str:
    if isinstance(value, float):
        return f"{value:g}".replace("-", "m").replace(".", "p")
    return str(value).replace("-", "m")


def _register_family(
    configs: list[StrategyConfig],
    family: str,
    variants: list[dict],
    canonical: dict,
) -> None:
    for params in variants:
        suffix = "-".join(
            f"{key}-{_value_slug(value)}" for key, value in sorted(params.items())
        )
        configs.append(
            StrategyConfig(
                family=family,
                name=f"{family}__{suffix}",
                params=params,
                canonical=params == canonical,
            )
        )


def build_configs() -> list[StrategyConfig]:
    configs: list[StrategyConfig] = []
    _register_family(
        configs,
        "sma-price",
        [{"period": value} for value in (50, 100, 150, 200, 250)],
        {"period": 200},
    )
    _register_family(
        configs,
        "ema-price",
        [{"period": value} for value in (50, 100, 150, 200, 250)],
        {"period": 200},
    )
    _register_family(
        configs,
        "dual-ma",
        [
            {"fast": 10, "slow": 50},
            {"fast": 20, "slow": 60},
            {"fast": 20, "slow": 100},
            {"fast": 50, "slow": 100},
            {"fast": 50, "slow": 200},
            {"fast": 100, "slow": 200},
        ],
        {"fast": 50, "slow": 200},
    )
    _register_family(
        configs,
        "macd-cross",
        [
            {"fast": 8, "slow": 21, "signal": 5},
            {"fast": 8, "slow": 21, "signal": 9},
            {"fast": 12, "slow": 26, "signal": 9},
            {"fast": 16, "slow": 34, "signal": 9},
            {"fast": 16, "slow": 34, "signal": 12},
        ],
        {"fast": 12, "slow": 26, "signal": 9},
    )
    _register_family(
        configs,
        "trix",
        [
            {"period": period, "signal": signal}
            for period in (9, 15, 30)
            for signal in (5, 9)
        ],
        {"period": 15, "signal": 9},
    )
    _register_family(
        configs,
        "adx-dmi",
        [
            {"period": period, "threshold": threshold}
            for period in (10, 14, 20)
            for threshold in (20, 25, 30)
        ],
        {"period": 14, "threshold": 25},
    )
    _register_family(
        configs,
        "aroon",
        [
            {"period": period, "threshold": threshold}
            for period in (14, 25, 50)
            for threshold in (60, 70, 80)
        ],
        {"period": 25, "threshold": 70},
    )
    _register_family(
        configs,
        "supertrend",
        [
            {"period": period, "multiplier": multiplier}
            for period in (7, 10, 14)
            for multiplier in (2.0, 3.0)
        ],
        {"period": 10, "multiplier": 3.0},
    )
    _register_family(
        configs,
        "tsmom-monthly",
        [{"lookback": value} for value in (63, 126, 189, 252)],
        {"lookback": 252},
    )
    _register_family(
        configs,
        "donchian",
        [
            {"entry": 20, "exit": 10},
            {"entry": 55, "exit": 20},
            {"entry": 100, "exit": 40},
            {"entry": 120, "exit": 40},
            {"entry": 200, "exit": 80},
        ],
        {"entry": 120, "exit": 40},
    )
    _register_family(
        configs,
        "bollinger-breakout",
        [
            {"period": period, "width": width}
            for period in (20, 50)
            for width in (1.0, 1.5, 2.0)
        ],
        {"period": 20, "width": 2.0},
    )
    _register_family(
        configs,
        "keltner-breakout",
        [
            {"period": period, "multiplier": multiplier}
            for period in (20, 40)
            for multiplier in (1.5, 2.0, 2.5)
        ],
        {"period": 20, "multiplier": 2.0},
    )
    _register_family(
        configs,
        "rsi-reversion",
        [
            {"period": 2, "entry": 10, "exit": 70},
            {"period": 2, "entry": 15, "exit": 70},
            {"period": 5, "entry": 20, "exit": 60},
            {"period": 5, "entry": 25, "exit": 60},
            {"period": 14, "entry": 30, "exit": 50},
            {"period": 14, "entry": 35, "exit": 55},
        ],
        {"period": 5, "entry": 25, "exit": 60},
    )
    _register_family(
        configs,
        "stochastic-reversion",
        [
            {"period": period, "entry": entry, "exit": 100 - entry}
            for period in (5, 9, 14)
            for entry in (20, 30)
        ],
        {"period": 14, "entry": 20, "exit": 80},
    )
    _register_family(
        configs,
        "cci-reversion",
        [
            {"period": period, "entry": entry, "exit": 0}
            for period in (10, 20, 40)
            for entry in (-100, -150)
        ],
        {"period": 20, "entry": -100, "exit": 0},
    )
    _register_family(
        configs,
        "bollinger-reversion",
        [
            {"period": period, "width": width}
            for period in (10, 20, 30)
            for width in (1.5, 2.0, 2.5)
        ],
        {"period": 20, "width": 2.0},
    )
    _register_family(
        configs,
        "mfi-reversion",
        [
            {"period": period, "entry": entry, "exit": exit_level}
            for period, entry, exit_level in (
                (7, 20, 60),
                (7, 30, 70),
                (14, 20, 60),
                (14, 30, 70),
                (21, 20, 60),
                (21, 30, 70),
            )
        ],
        {"period": 14, "entry": 20, "exit": 60},
    )
    _register_family(
        configs,
        "obv-trend",
        [
            {"obv_period": obv_period, "price_period": price_period}
            for obv_period in (10, 20, 50)
            for price_period in (50, 100)
        ],
        {"obv_period": 20, "price_period": 100},
    )
    _register_family(
        configs,
        "vol-target-trend",
        [
            {
                "trend_period": trend_period,
                "vol_period": vol_period,
                "target_vol": target_vol,
            }
            for trend_period in (100, 200)
            for vol_period in (20, 60)
            for target_vol in (0.15, 0.20)
        ],
        {"trend_period": 200, "vol_period": 20, "target_vol": 0.20},
    )
    _register_family(
        configs,
        "indicator-vote",
        [{"threshold": value} for value in (2, 3, 4)],
        {"threshold": 3},
    )
    if {config.family for config in configs} != set(FAMILY_ORDER):
        raise AssertionError("技术家族注册不完整")
    return configs


def execution_target(observation: pd.Series, delay: int = 1) -> pd.Series:
    if delay < 1:
        raise ValueError("成交延迟必须至少为一个交易日")
    return observation.astype(float).shift(delay).fillna(0.0).rename("target_weight")


def _ema(values: pd.Series, period: int) -> pd.Series:
    return values.astype(float).ewm(span=period, adjust=False, min_periods=period).mean()


def _wilder(values: pd.Series, period: int) -> pd.Series:
    return values.astype(float).ewm(
        alpha=1.0 / period,
        adjust=False,
        min_periods=period,
    ).mean()


def true_range(frame: pd.DataFrame) -> pd.Series:
    previous_close = frame["close"].shift(1)
    return pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def average_true_range(frame: pd.DataFrame, period: int) -> pd.Series:
    return _wilder(true_range(frame), period)


def wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    change = close.astype(float).diff()
    gain = change.clip(lower=0.0)
    loss = -change.clip(upper=0.0)
    average_gain = _wilder(gain, period)
    average_loss = _wilder(loss, period)
    relative_strength = average_gain / average_loss.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + relative_strength)
    rsi = rsi.mask((average_loss == 0.0) & (average_gain > 0.0), 100.0)
    rsi = rsi.mask((average_loss == 0.0) & (average_gain == 0.0), 50.0)
    return rsi.rename("rsi")


def dmi_adx(
    frame: pd.DataFrame,
    period: int = 14,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    upward = frame["high"].diff()
    downward = -frame["low"].diff()
    positive_dm = upward.where((upward > downward) & (upward > 0.0), 0.0)
    negative_dm = downward.where((downward > upward) & (downward > 0.0), 0.0)
    atr = _wilder(true_range(frame), period)
    positive_di = 100.0 * _wilder(positive_dm, period) / atr.replace(0.0, np.nan)
    negative_di = 100.0 * _wilder(negative_dm, period) / atr.replace(0.0, np.nan)
    denominator = (positive_di + negative_di).replace(0.0, np.nan)
    dx = 100.0 * (positive_di - negative_di).abs() / denominator
    adx = _wilder(dx, period)
    return adx.rename("adx"), positive_di.rename("positive_di"), negative_di.rename(
        "negative_di"
    )


def money_flow_index(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    raw_flow = typical * frame["volume"].astype(float)
    direction = typical.diff()
    positive = raw_flow.where(direction > 0.0, 0.0).rolling(period).sum()
    negative = raw_flow.where(direction < 0.0, 0.0).rolling(period).sum()
    ratio = positive / negative.replace(0.0, np.nan)
    mfi = 100.0 - 100.0 / (1.0 + ratio)
    mfi = mfi.mask((negative == 0.0) & (positive > 0.0), 100.0)
    mfi = mfi.mask((negative == 0.0) & (positive == 0.0), 50.0)
    return mfi.rename("mfi")


def aroon(frame: pd.DataFrame, period: int = 25) -> tuple[pd.Series, pd.Series]:
    def latest_argmax(values):
        return 100.0 * (int(np.argmax(values)) + 1) / period

    def latest_argmin(values):
        return 100.0 * (int(np.argmin(values)) + 1) / period

    up = frame["high"].rolling(period, min_periods=period).apply(latest_argmax, raw=True)
    down = frame["low"].rolling(period, min_periods=period).apply(latest_argmin, raw=True)
    return up.rename("aroon_up"), down.rename("aroon_down")


def commodity_channel_index(frame: pd.DataFrame, period: int = 20) -> pd.Series:
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    mean = typical.rolling(period, min_periods=period).mean()
    deviation = typical.rolling(period, min_periods=period).apply(
        lambda values: float(np.mean(np.abs(values - np.mean(values)))),
        raw=True,
    )
    return ((typical - mean) / (0.015 * deviation.replace(0.0, np.nan))).rename("cci")


def macd_components(
    close: pd.Series,
    fast: int,
    slow: int,
    signal: int,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    difference = _ema(close, fast) - _ema(close, slow)
    signal_line = difference.ewm(
        span=signal,
        adjust=False,
        min_periods=signal,
    ).mean()
    return difference, signal_line, difference - signal_line


def _stateful_target(entry: pd.Series, exit_signal: pd.Series) -> pd.Series:
    state = 0.0
    targets = []
    for date in entry.index:
        if state == 0.0 and bool(entry.loc[date]):
            state = TARGET_WEIGHT
        elif state > 0.0 and bool(exit_signal.loc[date]):
            state = 0.0
        targets.append(state)
    return pd.Series(targets, index=entry.index, dtype=float, name="target_weight")


def _monthly_sampled_target(raw_target: pd.Series) -> pd.Series:
    dates = pd.DatetimeIndex(raw_target.index)
    last_sessions = pd.Series(dates, index=dates.to_period("M")).groupby(level=0).max()
    sampled = pd.Series(np.nan, index=dates, dtype=float)
    selected_dates = pd.DatetimeIndex(last_sessions.to_numpy())
    sampled.loc[selected_dates] = raw_target.reindex(selected_dates).to_numpy()
    return sampled.ffill().fillna(0.0)


def _weekly_sampled_target(raw_target: pd.Series) -> pd.Series:
    dates = pd.DatetimeIndex(raw_target.index)
    last_sessions = pd.Series(dates, index=dates.to_period("W-FRI")).groupby(level=0).max()
    sampled = pd.Series(np.nan, index=dates, dtype=float)
    selected_dates = pd.DatetimeIndex(last_sessions.to_numpy())
    sampled.loc[selected_dates] = raw_target.reindex(selected_dates).to_numpy()
    return sampled.ffill().fillna(0.0)


def _supertrend_target(frame: pd.DataFrame, period: int, multiplier: float) -> pd.Series:
    atr = average_true_range(frame, period)
    midpoint = (frame["high"] + frame["low"]) / 2.0
    basic_upper = midpoint + multiplier * atr
    basic_lower = midpoint - multiplier * atr
    final_upper = np.full(len(frame), np.nan)
    final_lower = np.full(len(frame), np.nan)
    state = 0.0
    targets = np.zeros(len(frame))
    close = frame["close"].to_numpy(dtype=float)
    for index in range(len(frame)):
        if not np.isfinite(basic_upper.iloc[index]):
            continue
        if index == 0 or not np.isfinite(final_upper[index - 1]):
            final_upper[index] = basic_upper.iloc[index]
            final_lower[index] = basic_lower.iloc[index]
        else:
            final_upper[index] = (
                basic_upper.iloc[index]
                if basic_upper.iloc[index] < final_upper[index - 1]
                or close[index - 1] > final_upper[index - 1]
                else final_upper[index - 1]
            )
            final_lower[index] = (
                basic_lower.iloc[index]
                if basic_lower.iloc[index] > final_lower[index - 1]
                or close[index - 1] < final_lower[index - 1]
                else final_lower[index - 1]
            )
        if index > 0:
            if close[index] > final_upper[index - 1]:
                state = TARGET_WEIGHT
            elif close[index] < final_lower[index - 1]:
                state = 0.0
        targets[index] = state
    return pd.Series(targets, index=frame.index, name="target_weight")


def _donchian_target(frame: pd.DataFrame, entry_window: int, exit_window: int) -> pd.Series:
    upper = frame["high"].rolling(entry_window).max().shift(1)
    lower = frame["low"].rolling(exit_window).min().shift(1)
    return _stateful_target(frame["close"] > upper, frame["close"] < lower)


def generate_target(frame: pd.DataFrame, config: StrategyConfig) -> pd.Series:
    close = frame["close"].astype(float)
    params = config.params
    family = config.family
    if family == "sma-price":
        target = (close > close.rolling(params["period"]).mean()).astype(float) * TARGET_WEIGHT
    elif family == "ema-price":
        target = (close > _ema(close, params["period"])).astype(float) * TARGET_WEIGHT
    elif family == "dual-ma":
        target = (
            close.rolling(params["fast"]).mean() > close.rolling(params["slow"]).mean()
        ).astype(float) * TARGET_WEIGHT
    elif family == "macd-cross":
        difference, signal_line, _ = macd_components(
            close,
            params["fast"],
            params["slow"],
            params["signal"],
        )
        target = (difference > signal_line).astype(float) * TARGET_WEIGHT
    elif family == "trix":
        first = _ema(close, params["period"])
        second = _ema(first, params["period"])
        third = _ema(second, params["period"])
        trix_value = third.pct_change()
        signal_line = _ema(trix_value, params["signal"])
        target = (trix_value > signal_line).astype(float) * TARGET_WEIGHT
    elif family == "adx-dmi":
        adx, positive_di, negative_di = dmi_adx(frame, params["period"])
        target = (
            (adx >= params["threshold"]) & (positive_di > negative_di)
        ).astype(float) * TARGET_WEIGHT
    elif family == "aroon":
        up, down = aroon(frame, params["period"])
        target = ((up >= params["threshold"]) & (up > down)).astype(float) * TARGET_WEIGHT
    elif family == "supertrend":
        target = _supertrend_target(frame, params["period"], params["multiplier"])
    elif family == "tsmom-monthly":
        raw = (close > close.shift(params["lookback"])).astype(float) * TARGET_WEIGHT
        target = _monthly_sampled_target(raw)
    elif family == "donchian":
        target = _donchian_target(frame, params["entry"], params["exit"])
    elif family == "bollinger-breakout":
        middle = close.rolling(params["period"]).mean()
        deviation = close.rolling(params["period"]).std(ddof=1)
        upper = middle + params["width"] * deviation
        target = _stateful_target(close > upper, close < middle)
    elif family == "keltner-breakout":
        middle = _ema(close, params["period"])
        upper = middle + params["multiplier"] * average_true_range(frame, params["period"])
        target = _stateful_target(close > upper, close < middle)
    elif family == "rsi-reversion":
        rsi = wilder_rsi(close, params["period"])
        target = _stateful_target(rsi < params["entry"], rsi > params["exit"])
    elif family == "stochastic-reversion":
        low = frame["low"].rolling(params["period"]).min()
        high = frame["high"].rolling(params["period"]).max()
        stochastic = 100.0 * (close - low) / (high - low).replace(0.0, np.nan)
        target = _stateful_target(
            stochastic < params["entry"],
            stochastic > params["exit"],
        )
    elif family == "cci-reversion":
        cci = commodity_channel_index(frame, params["period"])
        target = _stateful_target(cci < params["entry"], cci > params["exit"])
    elif family == "bollinger-reversion":
        middle = close.rolling(params["period"]).mean()
        deviation = close.rolling(params["period"]).std(ddof=1)
        lower = middle - params["width"] * deviation
        target = _stateful_target(close < lower, close >= middle)
    elif family == "mfi-reversion":
        mfi = money_flow_index(frame, params["period"])
        target = _stateful_target(mfi < params["entry"], mfi > params["exit"])
    elif family == "obv-trend":
        obv = (np.sign(close.diff()).fillna(0.0) * frame["volume"]).cumsum()
        target = (
            (obv > obv.rolling(params["obv_period"]).mean())
            & (close > close.rolling(params["price_period"]).mean())
        ).astype(float) * TARGET_WEIGHT
    elif family == "vol-target-trend":
        trend = close > close.rolling(params["trend_period"]).mean()
        realized = close.pct_change().rolling(params["vol_period"]).std(ddof=1) * math.sqrt(
            TRADING_DAYS
        )
        raw = (params["target_vol"] / realized.replace(0.0, np.nan)).clip(
            lower=0.0,
            upper=TARGET_WEIGHT,
        )
        raw = raw.where(trend, 0.0).fillna(0.0)
        target = _weekly_sampled_target(raw)
    elif family == "indicator-vote":
        sma_vote = close > close.rolling(200).mean()
        ema_vote = _ema(close, 50) > _ema(close, 200)
        difference, signal_line, _ = macd_components(close, 12, 26, 9)
        macd_vote = difference > signal_line
        donchian_vote = _donchian_target(frame, 120, 40) > 0.0
        adx, positive_di, negative_di = dmi_adx(frame, 14)
        adx_vote = (adx >= 25.0) & (positive_di > negative_di)
        votes = pd.concat(
            [sma_vote, ema_vote, macd_vote, donchian_vote, adx_vote],
            axis=1,
        ).sum(axis=1)
        target = (votes >= params["threshold"]).astype(float) * TARGET_WEIGHT
    else:
        raise ValueError(f"未知技术家族：{family}")
    return target.astype(float).clip(lower=0.0, upper=TARGET_WEIGHT).fillna(0.0).rename(
        config.name
    )


def _standardize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "日期": "date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
    }
    return frame.rename(columns=aliases)


def normalize_cross_checked_data(
    primary: pd.DataFrame,
    verification: pd.DataFrame,
) -> pd.DataFrame:
    east = _standardize_columns(primary).copy()
    west = _standardize_columns(verification).copy()
    required = {"date", "open", "high", "low", "close", "volume"}
    for name, source in (("主行情源", east), ("独立核验源", west)):
        missing = required.difference(source.columns)
        if missing:
            raise ValueError(f"{name}数据缺少字段：{sorted(missing)}")
        source["date"] = pd.to_datetime(source["date"]).dt.normalize()
    merged = east[list(required)].merge(
        west[list(required)],
        on="date",
        suffixes=("_primary", "_verification"),
        how="inner",
        validate="one_to_one",
    ).sort_values("date")
    if len(merged) < 250:
        raise ValueError("交叉核验后的共同交易日不足")
    price_errors = []
    for field in ("open", "high", "low", "close"):
        left = pd.to_numeric(merged[f"{field}_primary"], errors="raise")
        right = pd.to_numeric(merged[f"{field}_verification"], errors="raise")
        relative = (left - right).abs() / right.abs().replace(0.0, np.nan)
        price_errors.append(float(relative.max()))
    maximum_error = max(price_errors)
    if maximum_error > 0.01:
        raise ValueError(f"OHLC 交叉核验差异过大：{maximum_error:.4%}")
    primary_volume = pd.to_numeric(merged["volume_primary"], errors="raise") * 100.0
    verification_volume = pd.to_numeric(merged["volume_verification"], errors="raise")
    volume_error = (
        (primary_volume - verification_volume).abs()
        / verification_volume.replace(0.0, np.nan)
    ).median()
    if not np.isfinite(volume_error) or volume_error > 0.02:
        raise ValueError(f"成交量交叉核验差异过大：{volume_error:.4%}")
    primary_sorted = east.sort_values("date").copy()
    primary_output_volume = pd.to_numeric(primary_sorted["volume"], errors="raise") * 100.0
    output = pd.DataFrame(
        {
            "symbol": SYMBOL,
            "trade_date": primary_sorted["date"],
            "open": pd.to_numeric(primary_sorted["open"], errors="raise"),
            "high": pd.to_numeric(primary_sorted["high"], errors="raise"),
            "low": pd.to_numeric(primary_sorted["low"], errors="raise"),
            "close": pd.to_numeric(primary_sorted["close"], errors="raise"),
            "volume": primary_output_volume,
            "amount": pd.to_numeric(primary_sorted["close"], errors="raise")
            * primary_output_volume,
        }
    ).set_index("trade_date")
    if output.index.duplicated().any() or not output.index.is_monotonic_increasing:
        raise ValueError("交叉核验结果日期异常")
    if not np.isfinite(output[["open", "high", "low", "close", "volume"]]).all().all():
        raise ValueError("交叉核验结果含非有限值")
    output.attrs["maximum_ohlc_relative_error"] = maximum_error
    output.attrs["median_volume_relative_error"] = float(volume_error)
    output.attrs["cross_checked_common_sessions"] = int(len(merged))
    output.attrs["verification_missing_sessions"] = int(len(east) - len(merged))
    latest_common_date = pd.Timestamp(merged["date"].max()).normalize()
    latest_primary_date = pd.Timestamp(primary_sorted["date"].max()).normalize()
    latest_verification_date = pd.Timestamp(west["date"].max()).normalize()
    output.attrs["latest_common_date"] = latest_common_date.strftime("%Y-%m-%d")
    output.attrs["latest_primary_date"] = latest_primary_date.strftime("%Y-%m-%d")
    output.attrs["latest_verification_date"] = latest_verification_date.strftime("%Y-%m-%d")
    output.attrs["latest_session_cross_checked"] = bool(
        latest_primary_date == latest_common_date
    )
    output.attrs["source"] = "Tencent qfq cross-checked with Yahoo adjusted daily data"
    output.attrs["amount_quality"] = "close_times_volume_proxy_not_used_by_signals"
    return output


def _fetch_json(url: str, params: dict) -> dict:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{url}?{query}",
        headers={"User-Agent": "Mozilla/5.0 (compatible; star50-research/1.0)"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_tencent_qfq(end: pd.Timestamp) -> pd.DataFrame:
    rows = []
    batch_start = pd.Timestamp("2020-11-01")
    while batch_start <= end:
        batch_end = min(batch_start + pd.DateOffset(years=2) - pd.Timedelta(days=1), end)
        payload = _fetch_json(
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
            {
                "param": (
                    f"sh588000,day,{batch_start:%Y-%m-%d},{batch_end:%Y-%m-%d},640,qfq"
                )
            },
        )
        instrument = payload.get("data", {}).get("sh588000", {})
        batch = instrument.get("qfqday") or instrument.get("day") or []
        rows.extend(batch)
        batch_start = batch_end + pd.Timedelta(days=1)
    # 腾讯长区间查询偶尔会静默漏掉最后一个已完成交易日，而较短尾窗能够返回。
    # 固定追加一年重叠尾窗并按日期保留最后一条，避免把接口分页行为误当成休市。
    recent_payload = _fetch_json(
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
        {
            "param": "sh588000,day,,,30,qfq",
            # 该接口的边缘缓存可能在收盘后仍返回前一交易日；仅尾窗绕过旧缓存。
            "_": str(pd.Timestamp.now(tz="UTC").value),
        },
    )
    recent_instrument = recent_payload.get("data", {}).get("sh588000", {})
    recent_batch = recent_instrument.get("qfqday") or recent_instrument.get("day") or []
    recent_dates = [
        pd.Timestamp(row[0]).normalize()
        for row in recent_batch
        if pd.Timestamp(row[0]).normalize() <= end
    ]
    if recent_dates:
        latest_date = max(recent_dates)
        # 无日期尾窗的最新一行可能只保留两位小数；再按确切日期获取三位精度。
        exact_payload = _fetch_json(
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
            {
                "param": (
                    f"sh588000,day,{latest_date:%Y-%m-%d},"
                    f"{latest_date:%Y-%m-%d},640,qfq"
                ),
                "_": str(pd.Timestamp.now(tz="UTC").value),
            },
        )
        exact_instrument = exact_payload.get("data", {}).get("sh588000", {})
        exact_batch = exact_instrument.get("qfqday") or exact_instrument.get("day") or []
        if not exact_batch:
            raise ValueError("腾讯行情源无法返回最新日精确 OHLC")
        rows.extend(exact_batch)
    if not rows:
        raise ValueError("腾讯行情源未返回 588000 日线")
    frame = pd.DataFrame(rows, columns=["date", "open", "close", "high", "low", "volume"])
    return frame.drop_duplicates("date", keep="last")


def _fetch_yahoo_adjusted(end: pd.Timestamp) -> pd.DataFrame:
    start_seconds = int(pd.Timestamp("2020-11-01", tz="UTC").timestamp())
    end_seconds = int((end + pd.Timedelta(days=1)).tz_localize("UTC").timestamp())
    payload = _fetch_json(
        "https://query1.finance.yahoo.com/v8/finance/chart/588000.SS",
        {
            "period1": start_seconds,
            "period2": end_seconds,
            "interval": "1d",
            "events": "div,splits",
            "includeAdjustedClose": "true",
        },
    )
    results = payload.get("chart", {}).get("result") or []
    if not results:
        raise ValueError("Yahoo 行情源未返回 588000 日线")
    result = results[0]
    quote = result["indicators"]["quote"][0]
    adjusted_close = pd.Series(result["indicators"]["adjclose"][0]["adjclose"], dtype=float)
    raw_close = pd.Series(quote["close"], dtype=float)
    adjustment = adjusted_close / raw_close
    dates = (
        pd.to_datetime(result["timestamp"], unit="s", utc=True)
        .tz_convert("Asia/Shanghai")
        .tz_localize(None)
        .normalize()
    )
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": pd.Series(quote["open"], dtype=float) * adjustment,
            "high": pd.Series(quote["high"], dtype=float) * adjustment,
            "low": pd.Series(quote["low"], dtype=float) * adjustment,
            "close": adjusted_close,
            "volume": pd.Series(quote["volume"], dtype=float),
        }
    )
    frame = frame.dropna(subset=["open", "high", "low", "close", "volume"])
    return frame.loc[frame["volume"] > 0].copy()


def fetch_market_data(end_date=None) -> pd.DataFrame:
    end = pd.Timestamp.today().normalize() if end_date is None else pd.Timestamp(end_date)
    primary = _fetch_tencent_qfq(end)
    verification = _fetch_yahoo_adjusted(end)
    return normalize_cross_checked_data(primary, verification)


def load_input_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"symbol", "trade_date", "open", "high", "low", "close", "volume", "amount"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"归档输入缺少字段：{sorted(missing)}")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.normalize()
    frame = frame.sort_values("trade_date").set_index("trade_date")
    frame.attrs["source"] = "archived cross-checked input"
    return frame


def _engine_inputs(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    bars = frame.reset_index()[
        ["trade_date", "symbol", "open", "high", "low", "close", "volume"]
    ]
    state = bars[["trade_date", "symbol"]].copy()
    previous_close = bars.groupby("symbol")["close"].shift(1)
    opening_gap = bars["open"] / previous_close - 1.0
    state["paused"] = bars["volume"].le(0.0)
    state["is_st"] = False
    state["buy_blocked"] = opening_gap.ge(0.195)
    state["sell_blocked"] = opening_gap.le(-0.195)
    state["status_quality"] = "C"
    state["st_quality"] = "C"
    state["limit_quality"] = "C"
    return bars, state


def _metrics_from_returns(returns: pd.Series) -> dict:
    values = pd.to_numeric(returns, errors="raise").fillna(0.0)
    if values.empty:
        raise ValueError("收益序列为空")
    curve = (1.0 + values).cumprod()
    total_return = float(curve.iloc[-1] - 1.0)
    years = len(values) / TRADING_DAYS
    annualized = float(curve.iloc[-1] ** (1.0 / years) - 1.0)
    volatility = float(values.std(ddof=1) * math.sqrt(TRADING_DAYS))
    sharpe = float(values.mean() * TRADING_DAYS / volatility) if volatility > 0 else np.nan
    downside = float(values.clip(upper=0.0).std(ddof=1) * math.sqrt(TRADING_DAYS))
    sortino = float(values.mean() * TRADING_DAYS / downside) if downside > 0 else np.nan
    full_curve = pd.concat([pd.Series([1.0]), curve.reset_index(drop=True)], ignore_index=True)
    drawdown = full_curve / full_curve.cummax() - 1.0
    maximum_drawdown = float(-drawdown.min())
    underwater = drawdown < -1e-12
    longest = current = 0
    for flag in underwater:
        current = current + 1 if flag else 0
        longest = max(longest, current)
    return {
        "trading_days": int(len(values)),
        "total_return": total_return,
        "annualized_return": annualized,
        "maximum_drawdown": maximum_drawdown,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": annualized / maximum_drawdown if maximum_drawdown > 0 else np.nan,
        "annualized_volatility": volatility,
        "longest_underwater_trading_days": int(longest),
    }


def simulate_target(
    name: str,
    frame: pd.DataFrame,
    observation_target: pd.Series,
    start_date,
    end_date=None,
    commission: float = BASE_COMMISSION,
    slippage: float = BASE_SLIPPAGE,
    delay: int = 1,
    execution: str = "open",
) -> SimulationResult:
    observation = observation_target.reindex(frame.index).ffill().fillna(0.0)
    desired = execution_target(observation, delay)
    start = pd.Timestamp(start_date)
    end = frame.index.max() if end_date is None else pd.Timestamp(end_date)
    calendar = pd.DatetimeIndex(frame.index[(frame.index >= start) & (frame.index <= end)])
    if calendar.empty:
        raise ValueError("模拟区间为空")
    bars, market_state = _engine_inputs(frame)
    engine = DailyBacktester(
        bars=bars,
        market_state=market_state,
        asset_types={SYMBOL: "etf"},
        config=BacktestConfig(
            initial_cash=INITIAL_CASH,
            maximum_volume_ratio=0.10,
            slippage_rate=slippage,
            minimum_state_quality="C",
        ),
        costs=CostModel(
            etf_buy_commission=commission,
            etf_sell_commission=commission,
            etf_minimum_commission=5.0,
        ),
    )
    last_weight = None
    decisions = []

    def target_provider(_, trade_date):
        nonlocal last_weight
        weight = float(desired.loc[trade_date])
        if last_weight is None or not math.isclose(weight, last_weight, abs_tol=1e-12):
            decisions.append(
                {
                    "model": name,
                    "execution_date": trade_date,
                    "target_weight": weight,
                    "execution": execution,
                    "delay": delay,
                }
            )
            last_weight = weight
            return {} if weight <= 0.0 else {SYMBOL: weight}
        return None

    engine.run(calendar, target_provider, frequency="daily", when="first", execution=execution)
    equity = engine.equity.copy()
    trades = engine.trades.copy()
    metrics = performance_metrics(equity, trades, trading_days=TRADING_DAYS)
    metrics["calmar"] = (
        metrics["annualized_return"] / metrics["maximum_drawdown"]
        if metrics["maximum_drawdown"] > 0.0
        else np.nan
    )
    exposure = equity["positions_value"] / equity["total_value"].replace(0.0, np.nan)
    metrics["average_exposure"] = float(exposure.mean())
    metrics["invested_session_ratio"] = float(equity["positions_value"].gt(0.0).mean())
    metrics["filled_trade_count"] = int(len(trades))
    metrics["rejected_order_count"] = int(len(engine.rejections))
    maximum_participation = 0.0
    if not trades.empty:
        volume = frame["volume"]
        for trade in trades.itertuples(index=False):
            daily_volume = float(volume.loc[pd.Timestamp(trade.trade_date)])
            if daily_volume > 0.0:
                maximum_participation = max(
                    maximum_participation,
                    float(trade.filled_shares) / daily_volume,
                )
    metrics["maximum_volume_participation"] = maximum_participation
    return SimulationResult(
        name=name,
        equity=equity,
        trades=trades,
        orders=engine.orders.copy(),
        decisions=pd.DataFrame(decisions),
        metrics=metrics,
    )


def _sharpe(values: pd.Series) -> float:
    returns = pd.to_numeric(values, errors="coerce").dropna()
    standard_deviation = float(returns.std(ddof=1))
    if standard_deviation <= 1e-12:
        mean = float(returns.mean())
        return math.copysign(1e9, mean) if mean != 0.0 else -1e9
    return float(returns.mean() / standard_deviation * math.sqrt(TRADING_DAYS))


def select_walk_forward_targets(
    returns: pd.DataFrame,
    targets: pd.DataFrame,
    initial_train_sessions: int = INITIAL_TRAIN_SESSIONS,
    test_sessions: int = TEST_SESSIONS,
    rolling_train_sessions: int | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    if not returns.index.equals(targets.index):
        raise ValueError("walk-forward 收益与目标日期不一致")
    if list(returns.columns) != list(targets.columns):
        raise ValueError("walk-forward 收益与目标配置不一致")
    dates = pd.DatetimeIndex(returns.index)
    combined = pd.Series(0.0, index=dates, dtype=float, name="selected_target")
    rows = []
    test_start_position = initial_train_sessions
    fold = 1
    while test_start_position < len(dates):
        remaining = len(dates) - test_start_position
        if remaining < MINIMUM_FINAL_TEST_SESSIONS:
            break
        test_end_position = min(len(dates) - 1, test_start_position + test_sessions - 1)
        train_start_position = (
            0
            if rolling_train_sessions is None
            else max(0, test_start_position - rolling_train_sessions)
        )
        train = returns.iloc[train_start_position:test_start_position]
        scores = {column: _sharpe(train[column]) for column in returns.columns}
        changes = {
            column: int(targets.iloc[train_start_position:test_start_position][column].diff().ne(0).sum())
            for column in returns.columns
        }
        winner = max(
            returns.columns,
            key=lambda column: (scores[column], -changes[column], column),
        )
        selection_date = dates[test_start_position - 1]
        test_start = dates[test_start_position]
        test_end = dates[test_end_position]
        combined.loc[selection_date:test_end] = targets.loc[selection_date:test_end, winner]
        rows.append(
            {
                "fold": fold,
                "selection_date": selection_date,
                "train_start": dates[train_start_position],
                "train_end": selection_date,
                "test_start": test_start,
                "test_end": test_end,
                "test_sessions": int(test_end_position - test_start_position + 1),
                "selected_config": winner,
                "train_sharpe": scores[winner],
                "train_target_changes": changes[winner],
            }
        )
        fold += 1
        test_start_position = test_end_position + 1
    if not rows:
        raise ValueError("数据不足以构造 walk-forward")
    return pd.DataFrame(rows), combined


def _sharpe_by_trial(return_matrix: np.ndarray) -> np.ndarray:
    means = np.nanmean(return_matrix, axis=1)
    standard_deviation = np.nanstd(return_matrix, axis=1, ddof=1)
    return np.divide(
        means,
        standard_deviation,
        out=np.full_like(means, np.nan),
        where=standard_deviation > 0.0,
    ) * math.sqrt(TRADING_DAYS)


def compute_pbo(
    return_matrix: np.ndarray,
    dates: pd.DatetimeIndex,
    trial_names: list[str],
    partitions: int = 8,
) -> tuple[pd.DataFrame, dict]:
    blocks = [
        np.asarray(block, dtype=int)
        for block in np.array_split(np.arange(len(dates)), partitions)
    ]
    rows = []
    for split, train_blocks in enumerate(
        itertools.combinations(range(partitions), partitions // 2),
        start=1,
    ):
        test_blocks = tuple(index for index in range(partitions) if index not in train_blocks)
        train_index = np.concatenate([blocks[index] for index in train_blocks])
        test_index = np.concatenate([blocks[index] for index in test_blocks])
        train_sharpe = _sharpe_by_trial(return_matrix[:, train_index])
        test_sharpe = _sharpe_by_trial(return_matrix[:, test_index])
        winner = int(np.nanargmax(train_sharpe))
        winner_oos = float(test_sharpe[winner])
        finite = test_sharpe[np.isfinite(test_sharpe)]
        percentile = float((np.sum(finite < winner_oos) + 0.5) / len(finite))
        percentile = min(max(percentile, 1e-12), 1.0 - 1e-12)
        rows.append(
            {
                "split": split,
                "train_blocks": ";".join(map(str, train_blocks)),
                "test_blocks": ";".join(map(str, test_blocks)),
                "selected_trial": trial_names[winner],
                "is_sharpe": float(train_sharpe[winner]),
                "oos_sharpe": winner_oos,
                "oos_percentile": percentile,
                "logit": math.log(percentile / (1.0 - percentile)),
                "below_oos_median": bool(percentile <= 0.5),
            }
        )
    frame = pd.DataFrame(rows)
    return frame, {
        "method": f"CSCV approximation: {partitions} contiguous blocks",
        "trial_count": int(return_matrix.shape[0]),
        "trading_days": int(return_matrix.shape[1]),
        "split_count": int(len(frame)),
        "pbo": float(frame["below_oos_median"].mean()),
        "median_selected_oos_percentile": float(frame["oos_percentile"].median()),
    }


def deflated_sharpe_probability(
    returns: np.ndarray,
    all_trial_returns: np.ndarray,
) -> dict:
    observed = np.asarray(returns, dtype=float)
    observed = observed[np.isfinite(observed)]
    trial_daily_sharpes = _sharpe_by_trial(all_trial_returns) / math.sqrt(TRADING_DAYS)
    trial_daily_sharpes = trial_daily_sharpes[np.isfinite(trial_daily_sharpes)]
    observed_daily_sharpe = float(observed.mean() / observed.std(ddof=1))
    trial_count = int(len(trial_daily_sharpes))
    euler_gamma = 0.5772156649015329
    if trial_count > 1:
        expected_z = (1.0 - euler_gamma) * stats.norm.ppf(
            1.0 - 1.0 / trial_count
        ) + euler_gamma * stats.norm.ppf(1.0 - 1.0 / (trial_count * math.e))
        expected_max = float(
            np.mean(trial_daily_sharpes)
            + np.std(trial_daily_sharpes, ddof=1) * expected_z
        )
    else:
        expected_max = 0.0
    skewness = float(stats.skew(observed, bias=False))
    kurtosis = float(stats.kurtosis(observed, fisher=False, bias=False))
    denominator = math.sqrt(
        max(
            1e-12,
            1.0
            - skewness * observed_daily_sharpe
            + (kurtosis - 1.0) * observed_daily_sharpe**2 / 4.0,
        )
    )
    statistic = (
        (observed_daily_sharpe - expected_max)
        * math.sqrt(max(1, len(observed) - 1))
        / denominator
    )
    return {
        "trial_count": trial_count,
        "observations": int(len(observed)),
        "observed_annualized_sharpe": observed_daily_sharpe * math.sqrt(TRADING_DAYS),
        "expected_maximum_annualized_sharpe_under_null": expected_max
        * math.sqrt(TRADING_DAYS),
        "skewness": skewness,
        "pearson_kurtosis": kurtosis,
        "deflated_sharpe_probability": float(stats.norm.cdf(statistic)),
    }


def _moving_block_indices(
    length: int,
    block_length: int,
    repetitions: int,
    seed: int,
):
    if length < block_length:
        raise ValueError("收益序列短于 bootstrap 区块")
    rng = np.random.default_rng(seed)
    blocks_needed = int(math.ceil(length / block_length))
    offsets = np.arange(block_length)
    for _ in range(repetitions):
        starts = rng.integers(0, length, size=blocks_needed)
        yield ((starts[:, None] + offsets[None, :]) % length).ravel()[:length]


def moving_block_comparison(
    differences: np.ndarray,
    block_length: int,
    repetitions: int,
    seed: int,
) -> dict:
    values = np.asarray(differences, dtype=float)
    values = values[np.isfinite(values)]
    observed = float(values.mean())
    centered = values - observed
    sampled = []
    null_sampled = []
    for indices in _moving_block_indices(len(values), block_length, repetitions, seed):
        sampled.append(float(values[indices].mean()))
        null_sampled.append(float(centered[indices].mean()))
    sampled_array = np.asarray(sampled)
    null_array = np.asarray(null_sampled)
    return {
        "block_length": block_length,
        "repetitions": repetitions,
        "annualized_mean_excess": observed * TRADING_DAYS,
        "ci_low": float(np.quantile(sampled_array, 0.025) * TRADING_DAYS),
        "ci_high": float(np.quantile(sampled_array, 0.975) * TRADING_DAYS),
        "p_value": float((1 + np.count_nonzero(null_array >= observed)) / (repetitions + 1)),
    }


def holm_adjusted_pvalues(raw: dict[str, float]) -> dict[str, float]:
    ordered = sorted(raw.items(), key=lambda item: item[1])
    previous = 0.0
    adjusted = {}
    for rank, (name, value) in enumerate(ordered):
        candidate = min(1.0, (len(ordered) - rank) * float(value))
        previous = max(previous, candidate)
        adjusted[name] = previous
    return adjusted


def white_reality_check(
    excess_returns: pd.DataFrame,
    block_length: int = 20,
    repetitions: int = 2000,
    seed: int = 20260901,
) -> dict:
    matrix = excess_returns.to_numpy(dtype=float)
    observed_means = np.nanmean(matrix, axis=0)
    observed_max = float(np.nanmax(observed_means))
    centered = matrix - observed_means
    null_maxima = []
    for indices in _moving_block_indices(len(matrix), block_length, repetitions, seed):
        null_maxima.append(float(np.nanmax(np.nanmean(centered[indices], axis=0))))
    null_array = np.asarray(null_maxima)
    return {
        "block_length": block_length,
        "repetitions": repetitions,
        "best_family": str(excess_returns.columns[int(np.nanargmax(observed_means))]),
        "observed_best_annualized_mean_excess": observed_max * TRADING_DAYS,
        "p_value": float((1 + np.count_nonzero(null_array >= observed_max)) / (repetitions + 1)),
    }


def _slice_returns(result: SimulationResult, start, end) -> pd.Series:
    equity = result.equity.copy()
    equity["trade_date"] = pd.to_datetime(equity["trade_date"])
    selected = equity[equity["trade_date"].between(pd.Timestamp(start), pd.Timestamp(end))]
    return selected.set_index("trade_date")["daily_return"].astype(float)


def _regime_labels(frame: pd.DataFrame) -> pd.DataFrame:
    close = frame["close"]
    sma = close.rolling(200).mean()
    slope = sma.pct_change(20)
    trend = pd.Series("transition", index=frame.index, dtype=object)
    trend[(close > sma) & (slope > 0.0)] = "uptrend"
    trend[(close < sma) & (slope < 0.0)] = "downtrend"
    realized = close.pct_change().rolling(20).std(ddof=1) * math.sqrt(TRADING_DAYS)
    volatility = pd.Series("normal-vol", index=frame.index, dtype=object)
    volatility[realized > 0.35] = "high-vol"
    return pd.DataFrame(
        {
            "trend_regime": trend.shift(1),
            "volatility_regime": volatility.shift(1),
        }
    )


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def run_study(frame: pd.DataFrame) -> dict:
    if len(frame) <= WARMUP_SESSIONS + INITIAL_TRAIN_SESSIONS:
        raise ValueError("科创 50 ETF 历史不足以执行预注册 walk-forward")
    configs = build_configs()
    evaluation_start = pd.Timestamp(frame.index[WARMUP_SESSIONS])
    evaluation_dates = pd.DatetimeIndex(frame.index[frame.index >= evaluation_start])
    targets = {config.name: generate_target(frame, config) for config in configs}
    full_results = {}
    config_rows = []
    for index, config in enumerate(configs, start=1):
        print(f"[配置 {index}/{len(configs)}] {config.name}", flush=True)
        result = simulate_target(
            config.name,
            frame,
            targets[config.name],
            evaluation_start,
        )
        full_results[config.name] = result
        config_rows.append(
            {
                "family": config.family,
                "config": config.name,
                "canonical": config.canonical,
                "params": json.dumps(config.params, ensure_ascii=False, sort_keys=True),
                **result.metrics,
            }
        )
    config_metrics = pd.DataFrame(config_rows)
    returns_frame = pd.DataFrame(
        {
            name: result.equity.set_index("trade_date")["daily_return"].reindex(
                evaluation_dates
            )
            for name, result in full_results.items()
        },
        index=evaluation_dates,
    ).fillna(0.0)
    targets_frame = pd.DataFrame(
        {name: target.reindex(evaluation_dates).fillna(0.0) for name, target in targets.items()},
        index=evaluation_dates,
    )
    buy_hold_target = pd.Series(TARGET_WEIGHT, index=frame.index, name="buy-hold")

    family_results = {}
    rolling_results = {}
    family_targets = {}
    expanding_selections = []
    rolling_selections = []
    fold_rows = []
    first_oos = None
    last_oos = None
    for index, family in enumerate(FAMILY_ORDER, start=1):
        print(f"[家族 {index}/{len(FAMILY_ORDER)}] {family} walk-forward", flush=True)
        names = [config.name for config in configs if config.family == family]
        family_return_matrix = returns_frame[names]
        family_target_matrix = targets_frame[names]
        selections, combined = select_walk_forward_targets(
            family_return_matrix,
            family_target_matrix,
            rolling_train_sessions=None,
        )
        rolling_selection, rolling_combined = select_walk_forward_targets(
            family_return_matrix,
            family_target_matrix,
            rolling_train_sessions=INITIAL_TRAIN_SESSIONS,
        )
        selections.insert(0, "family", family)
        rolling_selection.insert(0, "family", family)
        expanding_selections.append(selections)
        rolling_selections.append(rolling_selection)
        start = pd.Timestamp(selections.iloc[0]["test_start"])
        end = pd.Timestamp(selections.iloc[-1]["test_end"])
        first_oos = start if first_oos is None else max(first_oos, start)
        last_oos = end if last_oos is None else min(last_oos, end)
        family_targets[family] = combined
        family_result = simulate_target(
            f"walk-forward__{family}",
            frame,
            combined,
            start,
            end,
        )
        rolling_result = simulate_target(
            f"rolling-walk-forward__{family}",
            frame,
            rolling_combined,
            start,
            end,
        )
        family_results[family] = family_result
        rolling_results[family] = rolling_result
        for row in selections.itertuples(index=False):
            fold_metrics = _metrics_from_returns(
                _slice_returns(family_result, row.test_start, row.test_end)
            )
            fold_rows.append(
                {
                    "family": family,
                    "fold": row.fold,
                    "test_start": row.test_start,
                    "test_end": row.test_end,
                    "selected_config": row.selected_config,
                    **fold_metrics,
                }
            )
    selection_frame = pd.concat(expanding_selections, ignore_index=True)
    rolling_selection_frame = pd.concat(rolling_selections, ignore_index=True)
    fold_metrics = pd.DataFrame(fold_rows)
    assert first_oos is not None and last_oos is not None
    buy_hold_oos = simulate_target(
        "buy-hold-oos",
        frame,
        buy_hold_target,
        first_oos,
        last_oos,
    )
    buy_hold_full = simulate_target(
        "buy-hold-full",
        frame,
        buy_hold_target,
        evaluation_start,
    )

    bh_full_returns = buy_hold_full.equity.set_index("trade_date")["daily_return"]
    for row_index, row in config_metrics.iterrows():
        exposure = float(row["average_exposure"])
        scaled = bh_full_returns * exposure / TARGET_WEIGHT
        matched = _metrics_from_returns(scaled)
        config_metrics.loc[row_index, "exposure_matched_beta_annualized"] = matched[
            "annualized_return"
        ]
        config_metrics.loc[row_index, "timing_value_add"] = (
            row["annualized_return"] - matched["annualized_return"]
        )

    canonical_rows = [
        {"family": "buy-hold", "label": "买入持有", **buy_hold_full.metrics}
    ]
    canonical_equity = [buy_hold_full.equity.assign(family="buy-hold")]
    canonical_trades = [buy_hold_full.trades.assign(family="buy-hold")]
    for family in FAMILY_ORDER:
        config = next(item for item in configs if item.family == family and item.canonical)
        result = full_results[config.name]
        canonical_rows.append(
            {
                "family": family,
                "label": FAMILY_LABELS[family],
                "config": config.name,
                **result.metrics,
            }
        )
        canonical_equity.append(result.equity.assign(family=family, config=config.name))
        if not result.trades.empty:
            canonical_trades.append(result.trades.assign(family=family, config=config.name))
    canonical_metrics = pd.DataFrame(canonical_rows)

    family_metric_rows = []
    for family in FAMILY_ORDER:
        metrics = family_results[family].metrics.copy()
        rolling_metrics = rolling_results[family].metrics
        folds = fold_metrics[fold_metrics["family"].eq(family)]
        family_metric_rows.append(
            {
                "family": family,
                "label": FAMILY_LABELS[family],
                **metrics,
                "positive_fold_ratio": float(folds["total_return"].gt(0.0).mean()),
                "worst_fold_return": float(folds["total_return"].min()),
                "rolling_annualized_return": rolling_metrics["annualized_return"],
                "rolling_maximum_drawdown": rolling_metrics["maximum_drawdown"],
                "rolling_sharpe": rolling_metrics["sharpe"],
            }
        )
    family_metrics = pd.DataFrame(family_metric_rows)

    print("[统计] CSCV/PBO 与 Deflated Sharpe", flush=True)
    full_return_matrix = returns_frame.to_numpy(dtype=float).T
    global_pbo_splits, global_pbo = compute_pbo(
        full_return_matrix,
        evaluation_dates,
        list(returns_frame.columns),
    )
    family_pbo_rows = []
    family_pbo_splits = []
    dsr_rows = []
    for family in FAMILY_ORDER:
        names = [config.name for config in configs if config.family == family]
        matrix = returns_frame[names].to_numpy(dtype=float).T
        splits, summary = compute_pbo(matrix, evaluation_dates, names)
        splits.insert(0, "family", family)
        family_pbo_splits.append(splits)
        family_pbo_rows.append({"family": family, **summary})
        sharpes = _sharpe_by_trial(matrix)
        best_index = int(np.nanargmax(sharpes))
        dsr_rows.append(
            {
                "family": family,
                "selected_config": names[best_index],
                **deflated_sharpe_probability(matrix[best_index], matrix),
            }
        )
    global_best_index = int(np.nanargmax(_sharpe_by_trial(full_return_matrix)))
    global_dsr = {
        "selected_config": list(returns_frame.columns)[global_best_index],
        **deflated_sharpe_probability(
            full_return_matrix[global_best_index],
            full_return_matrix,
        ),
    }
    family_pbo = pd.DataFrame(family_pbo_rows)
    dsr = pd.DataFrame(dsr_rows)

    print("[统计] 参数平原、bootstrap 与 Reality Check", flush=True)
    surface_rows = []
    for family in FAMILY_ORDER:
        rows = config_metrics[config_metrics["family"].eq(family)]
        surface_rows.append(
            {
                "family": family,
                "config_count": int(len(rows)),
                "positive_annualized_ratio": float(rows["annualized_return"].gt(0.0).mean()),
                "beats_exposure_matched_beta_ratio": float(rows["timing_value_add"].gt(0.0).mean()),
                "median_annualized_return": float(rows["annualized_return"].median()),
                "minimum_annualized_return": float(rows["annualized_return"].min()),
                "maximum_annualized_return": float(rows["annualized_return"].max()),
                "median_timing_value_add": float(rows["timing_value_add"].median()),
            }
        )
    surface = pd.DataFrame(surface_rows)
    bh_oos_returns = buy_hold_oos.equity.set_index("trade_date")["daily_return"]
    oos_return_frame = pd.DataFrame(
        {
            family: result.equity.set_index("trade_date")["daily_return"].reindex(
                bh_oos_returns.index
            )
            for family, result in family_results.items()
        },
        index=bh_oos_returns.index,
    ).fillna(0.0)
    excess_frame = oos_return_frame.sub(bh_oos_returns, axis=0)
    bootstrap_rows = []
    raw_primary_pvalues = {}
    for family_index, family in enumerate(FAMILY_ORDER):
        for block_length in (20, 60):
            comparison = moving_block_comparison(
                excess_frame[family].to_numpy(),
                block_length,
                2000,
                20260901 + family_index * 10 + block_length,
            )
            bootstrap_rows.append({"family": family, **comparison})
            if block_length == 20:
                raw_primary_pvalues[family] = comparison["p_value"]
    adjusted = holm_adjusted_pvalues(raw_primary_pvalues)
    for row in bootstrap_rows:
        row["holm_p_value"] = adjusted[row["family"]] if row["block_length"] == 20 else np.nan
    bootstrap = pd.DataFrame(bootstrap_rows)
    reality_checks = {
        "block_20": white_reality_check(excess_frame, 20, 2000, 20260901),
        "block_60": white_reality_check(excess_frame, 60, 2000, 20260961),
    }

    print("[稳健性] 成本与成交时点", flush=True)
    robustness_rows = []
    robustness_results = {}
    for family in FAMILY_ORDER:
        target = family_targets[family]
        for case, slippage, delay, execution in (
            ("base", BASE_SLIPPAGE, 1, "open"),
            ("slippage-10bp", 0.0010, 1, "open"),
            ("slippage-20bp", 0.0020, 1, "open"),
            ("next-close", BASE_SLIPPAGE, 1, "close"),
            ("second-next-open", BASE_SLIPPAGE, 2, "open"),
        ):
            if case == "base":
                result = family_results[family]
            else:
                result = simulate_target(
                    f"{case}__{family}",
                    frame,
                    target,
                    first_oos,
                    last_oos,
                    slippage=slippage,
                    delay=delay,
                    execution=execution,
                )
            robustness_results[(family, case)] = result
            robustness_rows.append({"family": family, "case": case, **result.metrics})
    robustness = pd.DataFrame(robustness_rows)

    print("[诊断] 市场状态、事件与当前信号", flush=True)
    regimes = _regime_labels(frame).reindex(bh_oos_returns.index)
    regime_rows = []
    regime_return_sources = {"buy-hold": bh_oos_returns, **{
        family: oos_return_frame[family] for family in FAMILY_ORDER
    }}
    for model, model_returns in regime_return_sources.items():
        for column in ("trend_regime", "volatility_regime"):
            for regime, indices in regimes.groupby(column).groups.items():
                selected = model_returns.reindex(indices).dropna()
                if selected.empty:
                    continue
                regime_rows.append(
                    {
                        "model": model,
                        "dimension": column,
                        "regime": regime,
                        **_metrics_from_returns(selected),
                    }
                )
    regime_metrics = pd.DataFrame(regime_rows)

    underlying_returns = frame["close"].pct_change().reindex(bh_oos_returns.index)
    event_dates = pd.concat(
        [
            underlying_returns.nlargest(5).rename("underlying_return"),
            underlying_returns.nsmallest(5).rename("underlying_return"),
        ]
    ).sort_index()
    event_rows = []
    for date, underlying_return in event_dates.items():
        for model, model_returns in regime_return_sources.items():
            event_rows.append(
                {
                    "trade_date": date,
                    "model": model,
                    "underlying_return": underlying_return,
                    "model_return": model_returns.loc[date],
                }
            )
    event_metrics = pd.DataFrame(event_rows)

    current_rows = []
    for family in FAMILY_ORDER:
        names = [config.name for config in configs if config.family == family]
        training = returns_frame[names]
        scores = {name: _sharpe(training[name]) for name in names}
        selected = max(names, key=lambda name: (scores[name], name))
        target = float(targets[selected].iloc[-1])
        series = targets[selected]
        changes = series.ne(series.shift(1))
        last_change = series.index[changes].max()
        current_rows.append(
            {
                "family": family,
                "selected_config_using_all_history": selected,
                "training_sharpe": scores[selected],
                "observation_date": frame.index.max(),
                "next_session_target_weight": target,
                "last_signal_change": last_change,
            }
        )
    current_signals = pd.DataFrame(current_rows)

    family_metrics = family_metrics.merge(surface, on="family", how="left")
    family_metrics = family_metrics.merge(
        family_pbo[["family", "pbo"]], on="family", how="left"
    )
    family_metrics = family_metrics.merge(
        dsr[["family", "deflated_sharpe_probability"]], on="family", how="left"
    )
    primary_bootstrap = bootstrap[bootstrap["block_length"].eq(20)][
        ["family", "p_value", "holm_p_value", "ci_low", "ci_high"]
    ]
    family_metrics = family_metrics.merge(primary_bootstrap, on="family", how="left")
    bh_metrics = buy_hold_oos.metrics
    robustness_lookup = robustness.set_index(["family", "case"])
    regime_lookup = regime_metrics[
        regime_metrics["dimension"].eq("trend_regime")
        & regime_metrics["model"].isin(FAMILY_ORDER)
    ]
    gate_rows = []
    reality_passed = reality_checks["block_20"]["p_value"] < 0.10
    for row in family_metrics.itertuples(index=False):
        return_risk = bool(
            row.annualized_return > bh_metrics["annualized_return"]
            and row.sharpe > bh_metrics["sharpe"]
            and bh_metrics["maximum_drawdown"] - row.maximum_drawdown >= 0.10
        )
        folds_pass = bool(row.positive_fold_ratio >= 0.70 and row.worst_fold_return >= -0.20)
        rolling_pass = bool(row.rolling_annualized_return > 0.0)
        stress_pass = bool(
            robustness_lookup.loc[(row.family, "slippage-20bp"), "annualized_return"] > 0.0
            and robustness_lookup.loc[
                (row.family, "second-next-open"), "annualized_return"
            ]
            > 0.0
        )
        statistics_pass = bool(row.holm_p_value < 0.10 and reality_passed)
        mining_pass = bool(
            row.positive_annualized_ratio >= 0.60
            and row.pbo < 0.25
            and row.deflated_sharpe_probability >= 0.90
        )
        family_regimes = regime_lookup[regime_lookup["model"].eq(row.family)]
        regime_pass = bool(family_regimes["total_return"].ge(0.0).sum() >= 2)
        candidate = all(
            (
                return_risk,
                folds_pass,
                rolling_pass,
                stress_pass,
                statistics_pass,
                mining_pass,
                regime_pass,
            )
        )
        gate_rows.append(
            {
                "family": row.family,
                "return_risk": return_risk,
                "folds": folds_pass,
                "rolling": rolling_pass,
                "stress": stress_pass,
                "multiple_testing": statistics_pass,
                "mining_risk": mining_pass,
                "regimes": regime_pass,
                "candidate": candidate,
            }
        )
    gates = pd.DataFrame(gate_rows)

    return {
        "configs": configs,
        "evaluation_start": evaluation_start,
        "first_oos": first_oos,
        "last_oos": last_oos,
        "targets": targets,
        "full_results": full_results,
        "config_metrics": config_metrics,
        "canonical_metrics": canonical_metrics,
        "canonical_equity": pd.concat(canonical_equity, ignore_index=True),
        "canonical_trades": pd.concat(canonical_trades, ignore_index=True),
        "family_results": family_results,
        "rolling_results": rolling_results,
        "family_targets": family_targets,
        "family_metrics": family_metrics,
        "buy_hold_oos": buy_hold_oos,
        "selection_frame": selection_frame,
        "rolling_selection_frame": rolling_selection_frame,
        "fold_metrics": fold_metrics,
        "global_pbo_splits": global_pbo_splits,
        "global_pbo": global_pbo,
        "family_pbo_splits": pd.concat(family_pbo_splits, ignore_index=True),
        "family_pbo": family_pbo,
        "family_dsr": dsr,
        "global_dsr": global_dsr,
        "surface": surface,
        "bootstrap": bootstrap,
        "reality_checks": reality_checks,
        "robustness": robustness,
        "robustness_results": robustness_results,
        "regime_metrics": regime_metrics,
        "event_metrics": event_metrics,
        "current_signals": current_signals,
        "gates": gates,
    }


def _percent(value) -> str:
    return "—" if value is None or not np.isfinite(value) else f"{value:.2%}"


def _number(value) -> str:
    return "—" if value is None or not np.isfinite(value) else f"{value:.2f}"


def _gate(value) -> str:
    return "通过" if bool(value) else "失败"


def build_report(bundle: dict, frame: pd.DataFrame) -> str:
    family_metrics = bundle["family_metrics"].sort_values(
        ["sharpe", "annualized_return"], ascending=False
    )
    canonical = bundle["canonical_metrics"].set_index("family")
    gates = bundle["gates"].set_index("family")
    robustness = bundle["robustness"].set_index(["family", "case"])
    current = bundle["current_signals"].set_index("family")
    candidates = bundle["gates"].loc[bundle["gates"]["candidate"], "family"].tolist()
    best = family_metrics.iloc[0]
    bh = bundle["buy_hold_oos"].metrics
    lines = [
        "# 科创 50 ETF 单标的技术择时完整研究",
        "",
        "## 结论",
        "",
        f"数据覆盖 {frame.index.min().date()} 至 {frame.index.max().date()}，共 {len(frame):,} 个交易日；"
        f"252 日预热后从 {bundle['evaluation_start'].date()} 开始描述，滚动样本外为 "
        f"{bundle['first_oos'].date()} 至 {bundle['last_oos'].date()}。",
    ]
    if candidates:
        lines.append(
            "通过全部事前门槛的技术家族为："
            + "、".join(FAMILY_LABELS[family] for family in candidates)
            + "。它们只能进入独立策略簇设计，尚不是实盘结论。"
        )
    else:
        lines.append("20 个技术家族中没有任何一个同时通过全部事前门槛。")
    lines.extend(
        [
            f"滚动样本外 Sharpe 最高的是 {FAMILY_LABELS[best['family']]}：年化 "
            f"{_percent(best['annualized_return'])}、最大回撤 {_percent(best['maximum_drawdown'])}、"
            f"Sharpe {_number(best['sharpe'])}；同期买入持有分别为 "
            f"{_percent(bh['annualized_return'])}、{_percent(bh['maximum_drawdown'])}、"
            f"{_number(bh['sharpe'])}。",
            f"20 日区块 White Reality Check 的 p 值为 "
            f"{bundle['reality_checks']['block_20']['p_value']:.4f}；全局 CSCV/PBO 为 "
            f"{_percent(bundle['global_pbo']['pbo'])}。短历史与多重试验仍是核心约束。",
            "",
            "## 滚动样本外家族比较",
            "",
            "| 家族 | 年化 | 最大回撤 | Sharpe | Calmar | 正收益季度 | 最差季度 | Rolling年化 | Holm p |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in family_metrics.itertuples(index=False):
        lines.append(
            f"| {FAMILY_LABELS[row.family]} | {_percent(row.annualized_return)} | "
            f"{_percent(row.maximum_drawdown)} | {_number(row.sharpe)} | {_number(row.calmar)} | "
            f"{_percent(row.positive_fold_ratio)} | {_percent(row.worst_fold_return)} | "
            f"{_percent(row.rolling_annualized_return)} | {row.holm_p_value:.4f} |"
        )
    lines.extend(
        [
            "",
            "## 全历史中心参数描述",
            "",
            "以下结果只描述常见参数，不参与家族胜者选择。",
            "",
            "| 家族 | 年化 | 最大回撤 | Sharpe | 平均暴露 | 换手 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for family in ("buy-hold", *FAMILY_ORDER):
        row = canonical.loc[family]
        label = "买入持有" if family == "buy-hold" else FAMILY_LABELS[family]
        lines.append(
            f"| {label} | {_percent(row['annualized_return'])} | "
            f"{_percent(row['maximum_drawdown'])} | {_number(row['sharpe'])} | "
            f"{_percent(row['average_exposure'])} | {_number(row['turnover'])} |"
        )
    lines.extend(
        [
            "",
            "## 过拟合与参数稳定性",
            "",
            "| 家族 | 参数数 | 正年化比例 | 跑赢暴露匹配Beta | PBO | DSR概率 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in family_metrics.sort_values("family").itertuples(index=False):
        lines.append(
            f"| {FAMILY_LABELS[row.family]} | {int(row.config_count)} | "
            f"{_percent(row.positive_annualized_ratio)} | "
            f"{_percent(row.beats_exposure_matched_beta_ratio)} | {_percent(row.pbo)} | "
            f"{_percent(row.deflated_sharpe_probability)} |"
        )
    lines.extend(
        [
            "",
            "## 成本与执行压力",
            "",
            "| 家族 | 基础年化 | 10bp滑点 | 20bp滑点 | 下一收盘 | 再延迟一日开盘 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for family in FAMILY_ORDER:
        lines.append(
            f"| {FAMILY_LABELS[family]} | "
            f"{_percent(robustness.loc[(family, 'base'), 'annualized_return'])} | "
            f"{_percent(robustness.loc[(family, 'slippage-10bp'), 'annualized_return'])} | "
            f"{_percent(robustness.loc[(family, 'slippage-20bp'), 'annualized_return'])} | "
            f"{_percent(robustness.loc[(family, 'next-close'), 'annualized_return'])} | "
            f"{_percent(robustness.loc[(family, 'second-next-open'), 'annualized_return'])} |"
        )
    lines.extend(
        [
            "",
            "## 事前门槛",
            "",
            "| 家族 | 收益风险 | 季度稳定 | Rolling | 压力 | 多重检验 | 挖掘风险 | 状态覆盖 | 候选 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for family in FAMILY_ORDER:
        row = gates.loc[family]
        lines.append(
            f"| {FAMILY_LABELS[family]} | {_gate(row['return_risk'])} | {_gate(row['folds'])} | "
            f"{_gate(row['rolling'])} | {_gate(row['stress'])} | "
            f"{_gate(row['multiple_testing'])} | {_gate(row['mining_risk'])} | "
            f"{_gate(row['regimes'])} | {_gate(row['candidate'])} |"
        )
    long_count = int(current["next_session_target_weight"].gt(0.0).sum())
    average_target = float(current["next_session_target_weight"].mean())
    lines.extend(
        [
            "",
            "## 最新观察日信号快照",
            "",
            f"最新观察日为 {frame.index.max().date()}。20 个家族使用全部可见历史重新选参后，"
            f"有 {long_count} 个给出非零目标，家族平均目标仓位为 {_percent(average_target)}。"
            "该快照是研究诊断，不是样本外收益的一部分。",
            "",
            "| 家族 | 全历史所选参数 | 下一交易日目标 | 最近信号变化 |",
            "|---|---|---:|---|",
        ]
    )
    for family in FAMILY_ORDER:
        row = current.loc[family]
        lines.append(
            f"| {FAMILY_LABELS[family]} | `{row['selected_config_using_all_history']}` | "
            f"{_percent(row['next_session_target_weight'])} | "
            f"{pd.Timestamp(row['last_signal_change']).date()} |"
        )
    lines.extend(
        [
            "",
            "## 事实、解释与操作原则",
            "",
            "- 事实：只有 ETF 上市后的真实日线进入研究；没有拼接上市前代理历史。",
            "- 事实：walk-forward 每季度只用过去数据选家族参数，季度边界的参数切换包含真实成本。",
            "- 解释：全历史中心参数适合了解工具特性；决定能否操作必须以滚动样本外、压力成本和"
            "多重检验为主。",
            "- 操作原则：若没有家族通过全部门槛，不应从全历史表里挑最高收益参数直接交易；"
            "更合理的是继续冻结协议积累新数据，或只把通过多数稳健性但未通过统计门槛的家族放入模拟盘。",
            "- 限制：免费日线不含完整证券状态字段；成交模拟仅用成交量及开盘相对昨收推断暂停和涨跌停，"
            "状态质量标为 C 级。连续前复权价格适合收益研究，"
            "但不是逐公司行为股数账本。",
            "- 限制：约六年总历史、约两年半滚动样本外不足以证明跨周期优势；PBO、DSR 和 Reality Check"
            "只能量化风险，不能创造不存在的数据。",
            "",
            "## 完整证据",
            "",
            f"`raw/` 保存输入快照、{len(bundle['configs'])} 组参数、20 个家族的 expanding/rolling 选择、季度结果、"
            "净值、成交、PBO/DSR、bootstrap、Reality Check、压力测试、状态归因、极端日与当前信号。",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    output = frame.copy()
    for column in output.columns:
        if output[column].map(lambda value: isinstance(value, dict)).any():
            output[column] = output[column].map(
                lambda value: json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True)
                if isinstance(value, dict)
                else value
            )
    output.to_csv(path, index=False, encoding="utf-8")


def _write_json(value, path: Path) -> None:
    path.write_text(
        json.dumps(_json_safe(value), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def archive_result(
    bundle: dict,
    frame: pd.DataFrame,
    archived_at: str,
    run_id: str,
) -> Path:
    target = STUDY_DIR / "results" / f"{archived_at}__walk-forward-technical-families__{run_id}"
    if target.exists():
        raise FileExistsError(f"结果目录已存在，拒绝覆盖：{target}")
    raw = target / "raw"
    raw.mkdir(parents=True)
    shutil.copy2(SOURCE_PATH, target / "source.py")
    _write_csv(frame.reset_index(), raw / "input-sh588000.csv")
    registry = pd.DataFrame(
        [
            {
                "family": config.family,
                "config": config.name,
                "canonical": config.canonical,
                "params": json.dumps(config.params, ensure_ascii=False, sort_keys=True),
            }
            for config in bundle["configs"]
        ]
    )
    _write_csv(registry, raw / "config-registry.csv")
    _write_csv(bundle["config_metrics"], raw / "all-config-metrics.csv")
    _write_csv(bundle["canonical_metrics"], raw / "canonical-metrics.csv")
    _write_csv(bundle["canonical_equity"], raw / "canonical-equity.csv")
    _write_csv(bundle["canonical_trades"], raw / "canonical-trades.csv")
    _write_csv(bundle["family_metrics"], raw / "walk-forward-family-metrics.csv")
    _write_csv(bundle["selection_frame"], raw / "walk-forward-selections.csv")
    _write_csv(bundle["rolling_selection_frame"], raw / "rolling-walk-forward-selections.csv")
    _write_csv(bundle["fold_metrics"], raw / "walk-forward-fold-metrics.csv")
    family_equity = pd.concat(
        [result.equity.assign(family=family) for family, result in bundle["family_results"].items()],
        ignore_index=True,
    )
    family_trades = pd.concat(
        [
            result.trades.assign(family=family)
            for family, result in bundle["family_results"].items()
            if not result.trades.empty
        ],
        ignore_index=True,
    )
    family_decisions = pd.concat(
        [
            result.decisions.assign(family=family)
            for family, result in bundle["family_results"].items()
            if not result.decisions.empty
        ],
        ignore_index=True,
    )
    _write_csv(family_equity, raw / "walk-forward-equity.csv")
    _write_csv(family_trades, raw / "walk-forward-trades.csv")
    _write_csv(family_decisions, raw / "walk-forward-decisions.csv")
    _write_csv(bundle["surface"], raw / "parameter-surface-summary.csv")
    _write_csv(bundle["global_pbo_splits"], raw / "global-pbo-splits.csv")
    _write_json(bundle["global_pbo"], raw / "global-pbo-summary.json")
    _write_csv(bundle["family_pbo_splits"], raw / "family-pbo-splits.csv")
    _write_csv(bundle["family_pbo"], raw / "family-pbo-summary.csv")
    _write_csv(bundle["family_dsr"], raw / "family-dsr.csv")
    _write_json(bundle["global_dsr"], raw / "global-dsr.json")
    _write_csv(bundle["bootstrap"], raw / "bootstrap-comparison.csv")
    _write_json(bundle["reality_checks"], raw / "white-reality-check.json")
    _write_csv(bundle["robustness"], raw / "robustness.csv")
    _write_csv(bundle["regime_metrics"], raw / "regime-metrics.csv")
    _write_csv(bundle["event_metrics"], raw / "extreme-day-metrics.csv")
    _write_csv(bundle["current_signals"], raw / "current-signals.csv")
    _write_csv(bundle["gates"], raw / "candidate-gates.csv")
    (target / "report.md").write_text(build_report(bundle, frame), encoding="utf-8")

    artifacts = {}
    for path in sorted(target.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            artifacts[path.relative_to(target).as_posix()] = {
                "sha256": file_sha256(path),
                "bytes": path.stat().st_size,
            }
    manifest = {
        "schema_version": 2,
        "study_id": "star50-single-asset-timing",
        "archived_at": archived_at,
        "run_id": run_id,
        "symbol": SYMBOL,
        "data": {
            "source": frame.attrs.get("source", "archived cross-checked input"),
            "input_file": "raw/input-sh588000.csv",
            "input_sha256": artifacts["raw/input-sh588000.csv"]["sha256"],
            "start": frame.index.min(),
            "end": frame.index.max(),
            "sessions": len(frame),
            "maximum_ohlc_relative_error": frame.attrs.get(
                "maximum_ohlc_relative_error"
            ),
            "median_volume_relative_error": frame.attrs.get(
                "median_volume_relative_error"
            ),
            "cross_checked_common_sessions": frame.attrs.get(
                "cross_checked_common_sessions"
            ),
            "verification_missing_sessions": frame.attrs.get(
                "verification_missing_sessions"
            ),
            "amount_quality": frame.attrs.get("amount_quality"),
        },
        "protocol": {
            "warmup_sessions": WARMUP_SESSIONS,
            "initial_train_sessions": INITIAL_TRAIN_SESSIONS,
            "test_sessions": TEST_SESSIONS,
            "evaluation_start": bundle["evaluation_start"],
            "walk_forward_start": bundle["first_oos"],
            "walk_forward_end": bundle["last_oos"],
            "family_count": len(FAMILY_ORDER),
            "config_count": len(bundle["configs"]),
        },
        "execution": {
            "signal": "observation close and earlier",
            "fill": "next trading day open",
            "initial_cash": INITIAL_CASH,
            "maximum_target_weight": TARGET_WEIGHT,
            "lot_size": 100,
            "maximum_volume_ratio": 0.10,
        },
        "costs": {
            "etf_commission": BASE_COMMISSION,
            "minimum_commission": 5.0,
            "base_slippage": BASE_SLIPPAGE,
            "stress_slippages": STRESS_SLIPPAGES,
            "stamp_tax": 0.0,
        },
        "statistics": {
            "pbo": bundle["global_pbo"],
            "global_dsr": bundle["global_dsr"],
            "white_reality_check": bundle["reality_checks"],
            "bootstrap_repetitions": 2000,
            "bootstrap_blocks": [20, 60],
            "multiple_testing": "Holm",
        },
        "candidate_families": bundle["gates"].loc[
            bundle["gates"]["candidate"], "family"
        ].tolist(),
        "source_file": "source.py",
        "source_sha256": file_sha256(target / "source.py"),
        "artifacts": artifacts,
    }
    _write_json(manifest, target / "manifest.json")
    return target


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--archived-at", default=None)
    parser.add_argument("--run-id", default="tencent-yahoo-2020-2026-v1")
    parser.add_argument("--no-archive", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    frame = load_input_csv(args.input_csv) if args.input_csv else fetch_market_data(args.end_date)
    bundle = run_study(frame)
    columns = [
        "family",
        "annualized_return",
        "maximum_drawdown",
        "sharpe",
        "positive_fold_ratio",
        "holm_p_value",
    ]
    print(bundle["family_metrics"][columns].sort_values("sharpe", ascending=False).to_string(index=False))
    if not args.no_archive:
        archived_at = args.archived_at or pd.Timestamp.today().date().isoformat()
        target = archive_result(bundle, frame, archived_at, args.run_id)
        print(f"归档完成：{target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
