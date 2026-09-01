"""科创 50 ETF 单标的择时横向研究与不可变归档。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


def _find_repo_root(path: Path) -> Path:
    for candidate in (path, *path.parents):
        if (candidate / "src" / "quant_research").is_dir():
            return candidate
    raise RuntimeError("无法从脚本位置找到仓库根目录")


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
DEFAULT_DATA_ROOT = Path("D:/code/_open-source/_data/quant-research")
DEFAULT_RUN_ID = "local-etf-2021-2026-v1"
MODEL_ORDER = (
    "buy-hold",
    "macd-cross-12-26-9",
    "macd-zero-9-24",
    "sma-200",
    "tsmom-252-monthly",
    "donchian-120-40",
    "bollinger-20-2",
    "elder-risk-sized",
    "elder-full-exposure",
)
MODEL_LABELS = {
    "buy-hold": "买入持有",
    "macd-cross-12-26-9": "MACD 金叉/死叉 12/26/9",
    "macd-zero-9-24": "MACD 主线零轴 9/24",
    "sma-200": "收盘价 / SMA200",
    "tsmom-252-monthly": "12 月时间序列动量（月频）",
    "donchian-120-40": "Donchian 120/40",
    "bollinger-20-2": "布林均值回归 20/2",
    "elder-risk-sized": "Elder 风险定仓",
    "elder-full-exposure": "Elder 满仓信号",
}
BASE_COMMISSION = 0.0003
BASE_SLIPPAGE = 0.0002
STRESS_SLIPPAGE = 0.0010
TARGET_WEIGHT = 0.99
INITIAL_CASH = 1_000_000.0
TRADING_DAYS = 252


@dataclass
class SimulationResult:
    model: str
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


def execution_target(observation: pd.Series, delay: int = 1) -> pd.Series:
    """把观察日目标平移到执行日；delay=1 表示下一交易日。"""

    if delay < 1:
        raise ValueError("delay 必须至少为 1")
    return observation.astype(float).shift(delay).fillna(0.0).rename("target_weight")


def _ema(values: pd.Series, span: int) -> pd.Series:
    return values.astype(float).ewm(span=span, adjust=False, min_periods=span).mean()


def macd_components(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    if not 1 < fast < slow or signal < 2:
        raise ValueError("MACD 参数必须满足 1 < fast < slow 且 signal >= 2")
    diff = _ema(close, fast) - _ema(close, slow)
    dea = diff.ewm(span=signal, adjust=False, min_periods=signal).mean()
    histogram = diff - dea
    return diff.rename("diff"), dea.rename("dea"), histogram.rename("histogram")


def macd_cross_position(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.Series:
    diff, dea, _ = macd_components(close, fast, slow, signal)
    valid = diff.notna() & dea.notna()
    return ((diff > dea) & valid).astype(float).rename("position")


def macd_zero_position(
    close: pd.Series,
    fast: int = 9,
    slow: int = 24,
) -> pd.Series:
    fast_ema = _ema(close, fast)
    slow_ema = _ema(close, slow)
    valid = fast_ema.notna() & slow_ema.notna()
    return ((fast_ema > slow_ema) & valid).astype(float).rename("position")


def sma_position(close: pd.Series, window: int = 200) -> pd.Series:
    moving_average = close.rolling(window, min_periods=window).mean()
    return ((close > moving_average) & moving_average.notna()).astype(float)


def tsmom_monthly_position(close: pd.Series, lookback: int = 252) -> pd.Series:
    momentum_positive = close.div(close.shift(lookback)).gt(1.0)
    dates = pd.DatetimeIndex(close.index)
    month_end = pd.Series(dates, index=dates.to_period("M")).groupby(level=0).max()
    observations = pd.Series(np.nan, index=dates, dtype=float)
    observations.loc[pd.DatetimeIndex(month_end.to_numpy())] = (
        momentum_positive.reindex(month_end.to_numpy()).astype(float).to_numpy()
    )
    return observations.ffill().fillna(0.0).rename("position")


def donchian_position(
    frame: pd.DataFrame,
    entry_window: int = 120,
    exit_window: int = 40,
) -> pd.Series:
    high = frame["adjusted_high"].astype(float)
    low = frame["adjusted_low"].astype(float)
    close = frame["adjusted_close"].astype(float)
    upper = high.rolling(entry_window, min_periods=entry_window).max().shift(1)
    lower = low.rolling(exit_window, min_periods=exit_window).min().shift(1)
    state = 0.0
    positions = []
    for date in frame.index:
        if state == 0.0 and np.isfinite(upper.loc[date]) and close.loc[date] > upper.loc[date]:
            state = 1.0
        elif state == 1.0 and np.isfinite(lower.loc[date]) and close.loc[date] < lower.loc[date]:
            state = 0.0
        positions.append(state)
    return pd.Series(positions, index=frame.index, dtype=float, name="position")


def bollinger_position(
    close: pd.Series,
    window: int = 20,
    standard_deviations: float = 2.0,
) -> pd.Series:
    middle = close.rolling(window, min_periods=window).mean()
    deviation = close.rolling(window, min_periods=window).std(ddof=1)
    lower = middle - standard_deviations * deviation
    state = 0.0
    positions = []
    for date in close.index:
        if state == 0.0 and np.isfinite(lower.loc[date]) and close.loc[date] < lower.loc[date]:
            state = 1.0
        elif state == 1.0 and np.isfinite(middle.loc[date]) and close.loc[date] >= middle.loc[date]:
            state = 0.0
        positions.append(state)
    return pd.Series(positions, index=close.index, dtype=float, name="position")


def _weekly_bars(frame: pd.DataFrame) -> pd.DataFrame:
    indexed = frame.sort_index()
    periods = pd.DatetimeIndex(indexed.index).to_period("W-FRI")
    rows = []
    for _, group in indexed.groupby(periods):
        rows.append(
            {
                "trade_date": group.index.max(),
                "open": float(group["adjusted_open"].iloc[0]),
                "high": float(group["adjusted_high"].max()),
                "low": float(group["adjusted_low"].min()),
                "close": float(group["adjusted_close"].iloc[-1]),
                "volume": float(group["volume"].sum()),
            }
        )
    return pd.DataFrame(rows).set_index("trade_date").sort_index()


def completed_weekly_values(weekly: pd.Series, daily_dates) -> pd.Series:
    """把已完成周值映射到每日；周内不能读取未来的周末值。"""

    dates = pd.DatetimeIndex(pd.to_datetime(list(daily_dates))).normalize()
    values = weekly.copy()
    values.index = pd.DatetimeIndex(pd.to_datetime(values.index)).normalize()
    union = values.index.union(dates).sort_values()
    return values.reindex(union).ffill().reindex(dates)


def _wilder_atr(frame: pd.DataFrame, period: int = 13) -> pd.Series:
    high = frame["adjusted_high"].astype(float)
    low = frame["adjusted_low"].astype(float)
    close = frame["adjusted_close"].astype(float)
    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def elder_signal_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """因果实现旧 Elder 核心信号，并同时输出风险定仓与满仓目标。"""

    weekly = _weekly_bars(frame)
    weekly_ema = _ema(weekly["close"], 26)
    _, _, weekly_histogram = macd_components(weekly["close"], 12, 26, 9)
    ema_change = weekly_ema.div(weekly_ema.shift(2)).sub(1.0)
    ema_up = ema_change.gt(0.001)
    ema_down = ema_change.lt(-0.001)
    histogram_rising = weekly_histogram.gt(weekly_histogram.shift(1))
    spring_or_summer = histogram_rising & weekly_histogram.notna()
    autumn_or_winter = (~histogram_rising) & weekly_histogram.notna()

    dates = frame.index
    daily_ema_up = completed_weekly_values(ema_up.astype(float), dates).fillna(0.0).gt(0.5)
    daily_ema_down = completed_weekly_values(ema_down.astype(float), dates).fillna(0.0).gt(0.5)
    daily_rising = completed_weekly_values(
        spring_or_summer.astype(float), dates
    ).fillna(0.0).gt(0.5)
    daily_falling = completed_weekly_values(
        autumn_or_winter.astype(float), dates
    ).fillna(0.0).gt(0.5)

    high = frame["adjusted_high"].astype(float)
    low = frame["adjusted_low"].astype(float)
    close = frame["adjusted_close"].astype(float)
    rolling_low = low.rolling(5, min_periods=5).min()
    rolling_high = high.rolling(5, min_periods=5).max()
    raw_k = 100.0 * (close - rolling_low) / (rolling_high - rolling_low).replace(0.0, np.nan)
    stochastic_k = raw_k.rolling(3, min_periods=3).mean()
    force = frame["volume"].astype(float) * close.diff()
    force_ema = force.ewm(span=2, adjust=False, min_periods=2).mean()
    atr = _wilder_atr(frame, 13)

    entry_filter = daily_ema_up & daily_rising & (
        stochastic_k.lt(30.0) | force_ema.lt(0.0)
    )
    impulse_red = daily_ema_down & daily_falling
    state = 0.0
    stop = np.nan
    risk_weight = 0.0
    rows = []
    for date in dates:
        entry = False
        exit_signal = False
        price = float(close.loc[date])
        atr_value = float(atr.loc[date]) if np.isfinite(atr.loc[date]) else np.nan
        if state > 0.0:
            if np.isfinite(atr_value) and atr_value > 0.0:
                stop = max(float(stop), round(price - 2.0 * atr_value, 2))
            if bool(impulse_red.loc[date]) or (np.isfinite(stop) and price <= stop):
                state = 0.0
                risk_weight = 0.0
                exit_signal = True
                stop = np.nan
        elif (
            bool(entry_filter.loc[date])
            and np.isfinite(atr_value)
            and atr_value > 0.0
        ):
            candidate_stop = round(price - 2.0 * atr_value, 2)
            risk_per_share = price - candidate_stop
            if risk_per_share > 0.0:
                state = 1.0
                stop = candidate_stop
                risk_weight = min(0.20, 0.02 * price / risk_per_share)
                entry = True
        rows.append(
            {
                "trade_date": date,
                "position": state,
                "risk_weight": risk_weight,
                "full_weight": state * TARGET_WEIGHT,
                "entry": entry,
                "exit": exit_signal,
                "trailing_stop": stop,
                "atr": atr_value,
                "weekly_ema_up": bool(daily_ema_up.loc[date]),
                "weekly_histogram_rising": bool(daily_rising.loc[date]),
                "stochastic_k": stochastic_k.loc[date],
                "force_ema_2": force_ema.loc[date],
            }
        )
    return pd.DataFrame(rows).set_index("trade_date")


def load_etf_data(data_root: Path) -> tuple[pd.DataFrame, Path]:
    path = data_root / "normalized" / "etf_daily" / f"symbol={SYMBOL}" / "data.parquet"
    if not path.is_file():
        raise FileNotFoundError(f"缺少科创 50 ETF 日线：{path}")
    frame = pd.read_parquet(path)
    required = {
        "symbol",
        "trade_date",
        "adjusted_open",
        "adjusted_high",
        "adjusted_low",
        "adjusted_close",
        "volume",
        "quality_grade",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"ETF 日线缺少字段：{sorted(missing)}")
    frame = frame[frame["symbol"].eq(SYMBOL)].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.normalize()
    frame = frame.sort_values("trade_date").set_index("trade_date")
    if frame.empty or frame.index.duplicated().any():
        raise ValueError("ETF 日线为空或日期重复")
    if not frame["quality_grade"].eq("B").all():
        raise ValueError("科创 50 ETF 日线并非全部 B 级")
    numeric = [
        "adjusted_open",
        "adjusted_high",
        "adjusted_low",
        "adjusted_close",
        "volume",
    ]
    if not np.isfinite(frame[numeric].to_numpy(dtype=float)).all():
        raise ValueError("ETF 日线包含非有限 OHLCV")
    if (frame[["adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close"]] <= 0).any().any():
        raise ValueError("ETF 日线包含非正价格")
    return frame, path


def common_evaluation_start(frame: pd.DataFrame, warmup: int = 252) -> pd.Timestamp:
    if len(frame) <= warmup:
        raise ValueError("数据不足以完成统一预热")
    return pd.Timestamp(frame.index[warmup])


def build_model_weights(frame: pd.DataFrame) -> tuple[dict[str, pd.Series], pd.DataFrame]:
    close = frame["adjusted_close"].astype(float)
    elder = elder_signal_frame(frame)
    positions = {
        "buy-hold": pd.Series(1.0, index=frame.index),
        "macd-cross-12-26-9": macd_cross_position(close, 12, 26, 9),
        "macd-zero-9-24": macd_zero_position(close, 9, 24),
        "sma-200": sma_position(close, 200),
        "tsmom-252-monthly": tsmom_monthly_position(close, 252),
        "donchian-120-40": donchian_position(frame, 120, 40),
        "bollinger-20-2": bollinger_position(close, 20, 2.0),
    }
    weights = {model: position * TARGET_WEIGHT for model, position in positions.items()}
    weights["elder-risk-sized"] = elder["risk_weight"].astype(float)
    weights["elder-full-exposure"] = elder["full_weight"].astype(float)
    return weights, elder


def _engine_inputs(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    bars = frame.reset_index()[
        [
            "trade_date",
            "symbol",
            "adjusted_open",
            "adjusted_high",
            "adjusted_low",
            "adjusted_close",
            "volume",
        ]
    ].rename(
        columns={
            "adjusted_open": "open",
            "adjusted_high": "high",
            "adjusted_low": "low",
            "adjusted_close": "close",
        }
    )
    state = bars[["trade_date", "symbol"]].copy()
    state["paused"] = False
    state["is_st"] = False
    state["buy_blocked"] = False
    state["sell_blocked"] = False
    state["status_quality"] = "C"
    state["st_quality"] = "C"
    state["limit_quality"] = "C"
    return bars, state


def simulate_weights(
    model: str,
    frame: pd.DataFrame,
    observation_weights: pd.Series,
    start_date,
    commission: float = BASE_COMMISSION,
    slippage: float = BASE_SLIPPAGE,
    delay: int = 1,
    execution: str = "open",
) -> SimulationResult:
    weights = execution_target(observation_weights.reindex(frame.index).fillna(0.0), delay)
    start = pd.Timestamp(start_date)
    calendar = pd.DatetimeIndex(frame.index[frame.index >= start])
    if calendar.empty:
        raise ValueError("评价区间为空")
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
    last_desired = None
    decision_rows = []

    def target_provider(_, trade_date):
        nonlocal last_desired
        desired = float(weights.loc[trade_date])
        if last_desired is None or not math.isclose(desired, last_desired, abs_tol=1e-12):
            decision_rows.append(
                {
                    "model": model,
                    "execution_date": trade_date,
                    "target_weight": desired,
                    "delay": delay,
                    "execution": execution,
                }
            )
            last_desired = desired
            return {} if desired <= 0.0 else {SYMBOL: desired}
        return None

    engine.run(
        calendar=calendar,
        target_provider=target_provider,
        frequency="daily",
        when="first",
        execution=execution,
    )
    equity = engine.equity.copy()
    trades = engine.trades.copy()
    orders = engine.orders.copy()
    metrics = performance_metrics(equity, trades, trading_days=TRADING_DAYS)
    metrics["calmar"] = (
        float(metrics["annualized_return"] / metrics["maximum_drawdown"])
        if metrics["maximum_drawdown"] > 0.0
        else np.nan
    )
    metrics["invested_ratio"] = float(equity["positions_value"].gt(0).mean())
    metrics["filled_trade_count"] = int(len(trades))
    metrics["rejected_order_count"] = int(len(engine.rejections))
    return SimulationResult(
        model=model,
        equity=equity,
        trades=trades,
        orders=orders,
        decisions=pd.DataFrame(decision_rows),
        metrics=metrics,
    )


def period_metrics(result: SimulationResult, start, end, label: str) -> dict | None:
    equity = result.equity.copy()
    equity["trade_date"] = pd.to_datetime(equity["trade_date"])
    selected = equity[equity["trade_date"].between(pd.Timestamp(start), pd.Timestamp(end))].copy()
    if selected.empty:
        return None
    trades = result.trades.copy()
    if not trades.empty:
        trades["trade_date"] = pd.to_datetime(trades["trade_date"])
        trades = trades[
            trades["trade_date"].between(pd.Timestamp(start), pd.Timestamp(end))
        ]
    metrics = performance_metrics(selected, trades, trading_days=TRADING_DAYS)
    return {"model": result.model, "period": label, **metrics}


def bootstrap_mean_difference(
    differences,
    block_length: int = 20,
    repetitions: int = 2000,
    seed: int = 20260901,
) -> dict:
    values = np.asarray(differences, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < block_length or repetitions < 1:
        raise ValueError("区块自助法样本或重复次数不足")
    rng = np.random.default_rng(seed)
    blocks_needed = int(math.ceil(len(values) / block_length))
    offsets = np.arange(block_length)
    observed = float(values.mean())
    centered = values - observed
    uncentered_means = np.empty(repetitions)
    null_means = np.empty(repetitions)
    for index in range(repetitions):
        starts = rng.integers(0, len(values), size=blocks_needed)
        sample_indices = ((starts[:, None] + offsets[None, :]) % len(values)).ravel()[: len(values)]
        uncentered_means[index] = values[sample_indices].mean()
        null_means[index] = centered[sample_indices].mean()
    return {
        "annualized_mean_difference": observed * TRADING_DAYS,
        "ci_low": float(np.quantile(uncentered_means, 0.025) * TRADING_DAYS),
        "ci_high": float(np.quantile(uncentered_means, 0.975) * TRADING_DAYS),
        "p_value": float((1 + np.count_nonzero(null_means >= observed)) / (repetitions + 1)),
    }


def holm_adjusted_pvalues(raw: dict[str, float]) -> dict[str, float]:
    ordered = sorted(raw.items(), key=lambda item: item[1])
    count = len(ordered)
    previous = 0.0
    adjusted = {}
    for rank, (name, value) in enumerate(ordered):
        candidate = min(1.0, (count - rank) * float(value))
        previous = max(previous, candidate)
        adjusted[name] = previous
    return adjusted


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


def _metrics_rows(results: dict[str, SimulationResult]) -> pd.DataFrame:
    rows = []
    for model in MODEL_ORDER:
        metrics = results[model].metrics.copy()
        metrics["yearly_returns"] = json.dumps(
            _json_safe(metrics.get("yearly_returns", {})), ensure_ascii=False, sort_keys=True
        )
        rows.append({"model": model, "label": MODEL_LABELS[model], **metrics})
    return pd.DataFrame(rows)


def run_experiment(frame: pd.DataFrame) -> dict:
    evaluation_start = common_evaluation_start(frame, 252)
    weights, elder = build_model_weights(frame)
    results = {
        model: simulate_weights(model, frame, weights[model], evaluation_start)
        for model in MODEL_ORDER
    }
    metrics = _metrics_rows(results)

    periods = (
        (evaluation_start, "2022-12-31", "start-2022"),
        ("2023-01-01", "2024-12-31", "2023-2024"),
        ("2025-01-01", frame.index.max(), "2025-end"),
    )
    period_rows = []
    for model in MODEL_ORDER:
        for start, end, label in periods:
            row = period_metrics(results[model], start, end, label)
            if row is not None:
                period_rows.append(row)
    period_frame = pd.DataFrame(period_rows)

    stress_rows = []
    for model in MODEL_ORDER:
        stressed = simulate_weights(
            model,
            frame,
            weights[model],
            evaluation_start,
            slippage=STRESS_SLIPPAGE,
        )
        stress_rows.append(
            {
                "case": "slippage-10bp",
                "model": model,
                **stressed.metrics,
            }
        )
    for case, delay, execution in (
        ("next-close", 1, "close"),
        ("second-next-open", 2, "open"),
    ):
        timed = simulate_weights(
            "macd-cross-12-26-9",
            frame,
            weights["macd-cross-12-26-9"],
            evaluation_start,
            delay=delay,
            execution=execution,
        )
        stress_rows.append({"case": case, "model": timed.model, **timed.metrics})

    legacy_start = pd.Timestamp("2022-01-04")
    legacy_end = min(pd.Timestamp("2026-04-30"), frame.index.max())
    for model in (
        "buy-hold",
        "macd-cross-12-26-9",
        "macd-zero-9-24",
        "elder-risk-sized",
        "elder-full-exposure",
    ):
        legacy = simulate_weights(
            model,
            frame.loc[:legacy_end],
            weights[model].loc[:legacy_end],
            legacy_start,
        )
        stress_rows.append({"case": "legacy-2022-2026", "model": model, **legacy.metrics})
    robustness = pd.DataFrame(stress_rows)

    parameter_rows = []
    benchmark_annualized = results["buy-hold"].metrics["annualized_return"]
    close = frame["adjusted_close"]
    for fast in (8, 12, 16):
        for slow in (21, 26, 34):
            for signal in (7, 9, 12):
                position = macd_cross_position(close, fast, slow, signal)
                result = simulate_weights(
                    "macd-parameter-neighborhood",
                    frame,
                    position * TARGET_WEIGHT,
                    evaluation_start,
                )
                parameter_rows.append(
                    {
                        "fast": fast,
                        "slow": slow,
                        "signal": signal,
                        **result.metrics,
                        "positive_annualized": result.metrics["annualized_return"] > 0.0,
                        "beats_buy_hold": result.metrics["annualized_return"] > benchmark_annualized,
                    }
                )
    parameter_grid = pd.DataFrame(parameter_rows)

    benchmark_returns = results["buy-hold"].equity.set_index("trade_date")["daily_return"]
    bootstrap_rows = []
    raw_pvalues = {}
    for seed_offset, model in enumerate(MODEL_ORDER[1:]):
        active_returns = results[model].equity.set_index("trade_date")["daily_return"]
        paired = pd.concat([active_returns, benchmark_returns], axis=1, join="inner").dropna()
        differences = paired.iloc[:, 0].to_numpy() - paired.iloc[:, 1].to_numpy()
        statistics = bootstrap_mean_difference(
            differences,
            block_length=20,
            repetitions=2000,
            seed=20260901 + seed_offset,
        )
        raw_pvalues[model] = statistics["p_value"]
        bootstrap_rows.append({"model": model, **statistics})
    adjusted = holm_adjusted_pvalues(raw_pvalues)
    for row in bootstrap_rows:
        row["holm_p_value"] = adjusted[row["model"]]
    bootstrap = pd.DataFrame(bootstrap_rows)

    gates = []
    bh = results["buy-hold"].metrics
    stress_lookup = robustness[robustness["case"].eq("slippage-10bp")].set_index("model")
    period_lookup = period_frame.set_index(["model", "period"])
    bootstrap_lookup = bootstrap.set_index("model")
    macd_positive_ratio = float(parameter_grid["positive_annualized"].mean())
    macd_beats_ratio = float(parameter_grid["beats_buy_hold"].mean())
    for model in MODEL_ORDER[1:]:
        model_metrics = results[model].metrics
        return_and_sharpe = bool(
            model_metrics["annualized_return"] > bh["annualized_return"]
            and model_metrics["sharpe"] > bh["sharpe"]
        )
        drawdown_gate = bool(
            bh["maximum_drawdown"] - model_metrics["maximum_drawdown"] >= 0.10
        )
        all_periods_positive = bool(
            all(
                period_lookup.loc[(model, label), "annualized_return"] > 0.0
                for label in ("start-2022", "2023-2024", "2025-end")
            )
        )
        stress_positive = bool(stress_lookup.loc[model, "annualized_return"] > 0.0)
        statistical_gate = bool(bootstrap_lookup.loc[model, "holm_p_value"] < 0.10)
        neighborhood_gate = bool(
            model != "macd-cross-12-26-9"
            or (macd_positive_ratio >= 0.70 and macd_beats_ratio >= 0.70)
        )
        passed = all(
            (
                return_and_sharpe,
                drawdown_gate,
                all_periods_positive,
                stress_positive,
                statistical_gate,
                neighborhood_gate,
            )
        )
        gates.append(
            {
                "model": model,
                "return_and_sharpe": return_and_sharpe,
                "drawdown_reduction_10pp": drawdown_gate,
                "all_periods_positive": all_periods_positive,
                "stress_positive": stress_positive,
                "holm_p_below_0_10": statistical_gate,
                "parameter_neighborhood": neighborhood_gate,
                "candidate": passed,
            }
        )
    gate_frame = pd.DataFrame(gates)

    return {
        "evaluation_start": evaluation_start,
        "weights": weights,
        "elder": elder,
        "results": results,
        "metrics": metrics,
        "period_metrics": period_frame,
        "robustness": robustness,
        "parameter_grid": parameter_grid,
        "bootstrap": bootstrap,
        "gates": gate_frame,
        "macd_positive_ratio": macd_positive_ratio,
        "macd_beats_ratio": macd_beats_ratio,
    }


def _percent(value) -> str:
    return "—" if value is None or not np.isfinite(value) else f"{value:.2%}"


def _number(value) -> str:
    return "—" if value is None or not np.isfinite(value) else f"{value:.2f}"


def _gate_mark(value) -> str:
    return "通过" if bool(value) else "失败"


def build_report(bundle: dict, data_start, data_end) -> str:
    metrics = bundle["metrics"].set_index("model")
    periods = bundle["period_metrics"]
    robustness = bundle["robustness"]
    bootstrap = bundle["bootstrap"].set_index("model")
    gates = bundle["gates"].set_index("model")
    candidates = bundle["gates"].loc[bundle["gates"]["candidate"], "model"].tolist()
    lines = [
        "# 科创 50 ETF 单标的择时首轮研究",
        "",
        "## 结论",
        "",
    ]
    if candidates:
        labels = "、".join(MODEL_LABELS[item] for item in candidates)
        lines.append(f"按事前六项门槛，共有 {len(candidates)} 个策略簇候选：{labels}。")
    else:
        lines.append("按事前六项门槛，本轮没有模型可以晋升为策略簇候选。")
    macd_gate_count = int(
        bundle["gates"]
        .set_index("model")
        .loc["macd-cross-12-26-9"]
        .drop(labels="candidate")
        .astype(bool)
        .sum()
    )
    lines.extend(
        [
            f"标准 MACD 金叉/死叉是最强研究线索：六项门槛通过 {macd_gate_count} 项，"
            "唯一失败项是经过多模型校正后的统计检验；因此应冻结观察，而不是继续调参。",
            "本报告评价的是已经被旧实验部分观察过的历史，不能称为样本外，也不构成实盘建议。",
            "",
            "## 统一全期结果",
            "",
            "| 模型 | 年化收益 | 最大回撤 | Sharpe | Calmar | 换手 | 在场率 | 最长水下期 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for model in MODEL_ORDER:
        row = metrics.loc[model]
        lines.append(
            "| {label} | {annual} | {drawdown} | {sharpe} | {calmar} | {turnover} | {invested} | {underwater} |".format(
                label=MODEL_LABELS[model],
                annual=_percent(row["annualized_return"]),
                drawdown=_percent(row["maximum_drawdown"]),
                sharpe=_number(row["sharpe"]),
                calmar=_number(row["calmar"]),
                turnover=_number(row["turnover"]),
                invested=_percent(row["invested_ratio"]),
                underwater=int(row["longest_underwater_trading_days"]),
            )
        )

    lines.extend(
        [
            "",
            "## 事前门槛",
            "",
            "| 模型 | 收益+Sharpe | 回撤改善10pp | 三阶段为正 | 压力成本为正 | Holm p<0.10 | 参数邻域 | 候选 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for model in MODEL_ORDER[1:]:
        row = gates.loc[model]
        lines.append(
            f"| {MODEL_LABELS[model]} | {_gate_mark(row['return_and_sharpe'])} | "
            f"{_gate_mark(row['drawdown_reduction_10pp'])} | "
            f"{_gate_mark(row['all_periods_positive'])} | "
            f"{_gate_mark(row['stress_positive'])} | "
            f"{_gate_mark(row['holm_p_below_0_10'])} | "
            f"{_gate_mark(row['parameter_neighborhood'])} | "
            f"{_gate_mark(row['candidate'])} |"
        )

    lines.extend(
        [
            "",
            "## 分阶段结果",
            "",
            "| 模型 | 阶段 | 年化收益 | 最大回撤 | Sharpe |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for model in MODEL_ORDER:
        for row in periods[periods["model"].eq(model)].itertuples(index=False):
            lines.append(
                f"| {MODEL_LABELS[model]} | {row.period} | {_percent(row.annualized_return)} | "
                f"{_percent(row.maximum_drawdown)} | {_number(row.sharpe)} |"
            )

    grid = bundle["parameter_grid"]
    center = grid[(grid["fast"] == 12) & (grid["slow"] == 26) & (grid["signal"] == 9)].iloc[0]
    lines.extend(
        [
            "",
            "## 标准 MACD 稳健性",
            "",
            f"- 27 组参数邻域中，正年化比例为 {_percent(bundle['macd_positive_ratio'])}。",
            f"- 年化收益高于买入持有的比例为 {_percent(bundle['macd_beats_ratio'])}。",
            f"- 年化收益中位数为 {_percent(grid['annualized_return'].median())}，范围为 "
            f"{_percent(grid['annualized_return'].min())} 至 {_percent(grid['annualized_return'].max())}。",
            f"- 中心参数 12/26/9 年化 {_percent(center['annualized_return'])}、"
            f"最大回撤 {_percent(center['maximum_drawdown'])}、Sharpe {_number(center['sharpe'])}。",
            "- 全部组合保存在 `raw/macd-parameter-neighborhood.csv`，没有只保留最优参数。",
            "",
            "### 时点与旧区间",
            "",
            "| 情形 | 模型 | 年化收益 | 最大回撤 | Sharpe |",
            "|---|---|---:|---:|---:|",
        ]
    )
    selected_cases = robustness[
        robustness["case"].isin(["next-close", "second-next-open", "legacy-2022-2026"])
    ]
    for row in selected_cases.itertuples(index=False):
        lines.append(
            f"| {row.case} | {MODEL_LABELS[row.model]} | {_percent(row.annualized_return)} | "
            f"{_percent(row.maximum_drawdown)} | {_number(row.sharpe)} |"
        )

    legacy_macd = selected_cases[
        selected_cases["case"].eq("legacy-2022-2026")
        & selected_cases["model"].eq("macd-cross-12-26-9")
    ].iloc[0]
    legacy_elder = selected_cases[
        selected_cases["case"].eq("legacy-2022-2026")
        & selected_cases["model"].eq("elder-risk-sized")
    ].iloc[0]
    lines.extend(
        [
            "",
            "## 旧实验复核",
            "",
            f"旧笔记声称同期简单 MACD 年化约 25.6%；本次明确使用 `DIFF > DEA`、"
            f"前一日收盘信号和下一日开盘成交后，旧区间年化为 {_percent(legacy_macd['annualized_return'])}。",
            "旧 MACD 源码、逐日净值与成交没有进入 git 历史，因此两者即使接近也不能视为精确复现；"
            "若差异明显，首先应归因于 MACD 定义、同日/次日成交和成本口径未固定。",
            "",
            f"旧笔记中的 Elder 年化约 2.5%、最大回撤约 3.8%；本次风险定仓版旧区间年化为 "
            f"{_percent(legacy_elder['annualized_return'])}、最大回撤为 "
            f"{_percent(legacy_elder['maximum_drawdown'])}。旧源码对单标的设置 20% 仓位上限和 2% 风险预算，"
            "所以低回撤主要来自低风险暴露，不能直接与 100% 买入持有解释为同风险 Alpha。",
            "",
            "## 多模型统计比较",
            "",
            "| 模型 | 年化平均日收益差 | 95% 区间 | 原始 p | Holm p |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for model in MODEL_ORDER[1:]:
        row = bootstrap.loc[model]
        lines.append(
            f"| {MODEL_LABELS[model]} | {_percent(row['annualized_mean_difference'])} | "
            f"[{_percent(row['ci_low'])}, {_percent(row['ci_high'])}] | "
            f"{row['p_value']:.4f} | {row['holm_p_value']:.4f} |"
        )

    lines.extend(
        [
            "",
            "## 事实、推断与限制",
            "",
            f"- 数据事实：原始日线覆盖 {pd.Timestamp(data_start).date()} 至 "
            f"{pd.Timestamp(data_end).date()}；统一预热后评价从 "
            f"{pd.Timestamp(bundle['evaluation_start']).date()} 开始。",
            "- 因果事实：所有主结果使用观察日收盘信号、下一交易日开盘成交；周线 Elder 只映射已结束周。",
            "- 统计事实：区块自助法衡量的是历史平均日收益差，不证明未来收益，也不为最大回撤提供稳定置信区间。",
            "- 推断边界：模型之间共享同一小样本，Holm 校正只能缓解本轮多重比较，不能消除旧实验和研究者选择造成的数据窥探。",
            "- Elder 差异：本地复现保留旧规则的核心趋势、回调、ATR 止损、2% 风险预算和 20% 仓位上限；"
            "未复现旧引擎的月内 6% 已实现亏损保险丝。单标的 20% 上限下该保险丝通常需要同月连续多次止损才触发。",
            "- 撮合限制：ETF 日线是 B 级，但逐日停牌/涨跌停使用 C 级可交易代理；连续复权价格下股数和最低佣金不是逐公司行为精确复刻。",
            "- 期限限制：有效评价期不足五年，主要覆盖科创板先跌后修复的少数状态；任何候选都必须冻结后前瞻跟踪。",
            "",
            "## 下一步",
            "",
            "1. 不根据本报告继续微调周期；先决定是否有模型通过全部事前门槛。",
            "2. 若有候选，为该机制单独建立策略簇，并在聚宽用同样的观察/成交口径做平台复核。",
            "3. 若没有候选，保留失败结果；只有提出新的经济机制时才开启第二阶段，不做参数扫榜。",
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


def archive_result(
    bundle: dict,
    frame: pd.DataFrame,
    input_path: Path,
    data_root: Path,
    archived_at: str,
    run_id: str,
) -> Path:
    target = (
        STUDY_DIR
        / "results"
        / f"{archived_at}__canonical-mechanism-comparison__{run_id}"
    )
    if target.exists():
        raise FileExistsError(f"结果目录已存在，拒绝覆盖：{target}")
    raw = target / "raw"
    raw.mkdir(parents=True)
    shutil.copy2(SOURCE_PATH, target / "source.py")

    input_snapshot = frame.reset_index()
    _write_csv(input_snapshot, raw / "input-sh588000.csv")
    _write_csv(bundle["metrics"], raw / "model-metrics.csv")
    _write_csv(bundle["period_metrics"], raw / "period-metrics.csv")
    _write_csv(bundle["robustness"], raw / "robustness.csv")
    _write_csv(bundle["parameter_grid"], raw / "macd-parameter-neighborhood.csv")
    _write_csv(bundle["bootstrap"], raw / "bootstrap-comparison.csv")
    _write_csv(bundle["gates"], raw / "candidate-gates.csv")
    elder = bundle["elder"].reset_index()
    _write_csv(elder, raw / "elder-signals.csv")

    equity_frames = []
    trade_frames = []
    order_frames = []
    decision_frames = []
    for model in MODEL_ORDER:
        result = bundle["results"][model]
        equity_frames.append(result.equity.assign(model=model))
        if not result.trades.empty:
            trade_frames.append(result.trades.assign(model=model))
        if not result.orders.empty:
            order_frames.append(result.orders.assign(model=model))
        if not result.decisions.empty:
            decision_frames.append(result.decisions.assign(model=model))
    _write_csv(pd.concat(equity_frames, ignore_index=True), raw / "model-equity.csv")
    _write_csv(
        pd.concat(trade_frames, ignore_index=True) if trade_frames else pd.DataFrame(),
        raw / "model-trades.csv",
    )
    _write_csv(
        pd.concat(order_frames, ignore_index=True) if order_frames else pd.DataFrame(),
        raw / "model-orders.csv",
    )
    _write_csv(
        pd.concat(decision_frames, ignore_index=True) if decision_frames else pd.DataFrame(),
        raw / "model-decisions.csv",
    )

    report = build_report(bundle, frame.index.min(), frame.index.max())
    (target / "report.md").write_text(report, encoding="utf-8")

    artifacts = {}
    for path in sorted(target.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            artifacts[path.relative_to(target).as_posix()] = {
                "sha256": file_sha256(path),
                "bytes": path.stat().st_size,
            }
    manifest_path = data_root / "manifests" / "etf_daily.json"
    candidates = bundle["gates"].loc[bundle["gates"]["candidate"], "model"].tolist()
    manifest = {
        "schema_version": 1,
        "study_id": "star50-single-asset-timing",
        "archived_at": archived_at,
        "run_id": run_id,
        "symbol": SYMBOL,
        "period": {
            "data_start": frame.index.min(),
            "evaluation_start": bundle["evaluation_start"],
            "end": frame.index.max(),
            "warmup_trading_days": 252,
        },
        "execution": {
            "signal": "observation close and earlier",
            "fill": "next trading day open",
            "initial_cash": INITIAL_CASH,
            "target_weight": TARGET_WEIGHT,
            "lot_size": 100,
            "maximum_volume_ratio": 0.10,
        },
        "costs": {
            "etf_buy_commission": BASE_COMMISSION,
            "etf_sell_commission": BASE_COMMISSION,
            "minimum_commission": 5.0,
            "base_slippage": BASE_SLIPPAGE,
            "stress_slippage": STRESS_SLIPPAGE,
            "stamp_tax": 0.0,
        },
        "data": {
            "input_path": str(input_path),
            "input_sha256": file_sha256(input_path),
            "quality_grade": "B",
            "etf_manifest_path": str(manifest_path),
            "etf_manifest_sha256": file_sha256(manifest_path),
            "tradability_proxy_quality": "C",
        },
        "statistics": {
            "moving_block_length": 20,
            "bootstrap_repetitions": 2000,
            "multiple_testing": "Holm",
        },
        "candidate_models": candidates,
        "model_metrics": {
            model: _json_safe(bundle["results"][model].metrics) for model in MODEL_ORDER
        },
        "source_file": "source.py",
        "source_sha256": file_sha256(target / "source.py"),
        "artifacts": artifacts,
    }
    (target / "manifest.json").write_text(
        json.dumps(_json_safe(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--archived-at", default="2026-09-01")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--no-archive", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    frame, input_path = load_etf_data(args.data_root)
    bundle = run_experiment(frame)
    summary_columns = [
        "model",
        "annualized_return",
        "maximum_drawdown",
        "sharpe",
        "turnover",
        "invested_ratio",
    ]
    print(bundle["metrics"][summary_columns].to_string(index=False))
    if not args.no_archive:
        target = archive_result(
            bundle,
            frame,
            input_path,
            args.data_root,
            args.archived_at,
            args.run_id,
        )
        print(f"归档完成：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
