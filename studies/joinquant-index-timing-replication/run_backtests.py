"""使用本地 Qlib 日线数据复现三份聚宽沪深300择时策略。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


STUDY_DIR = Path(__file__).resolve().parent
ROOT = STUDY_DIR.parents[1]
DEFAULT_QLIB_DIR = Path("D:/code/_open-source/_data/qlib/cn_data")
DEFAULT_RUN_ID = "local-qlib-comparison-v1"
TRADING_DAYS_PER_YEAR = 250.0


@dataclass(frozen=True)
class TradingCosts:
    buy_commission: float = 0.0
    sell_commission: float = 0.0
    sell_tax: float = 0.0
    minimum_commission: float = 0.0
    slippage: float = 0.0


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    name: str
    signal_kind: str
    symbol: str
    start_date: str
    end_date: str
    initial_cash: float
    source_path: str
    post_url: str
    execution_field: str
    costs: TradingCosts
    jq_total_return: float
    jq_annualized_return: float
    jq_benchmark_total_return: float
    jq_benchmark_annualized_return: float
    jq_max_drawdown: float
    jq_sharpe: float


STRATEGIES = (
    StrategySpec(
        strategy_id="macd-market-timing",
        name="MACD——大盘择时",
        signal_kind="macd",
        symbol="SZ399300",
        start_date="2005-07-01",
        end_date="2018-02-01",
        initial_cash=10_000_000.0,
        source_path="joinquant_archive/sources/2020年度精选策略/76 MACD——大盘择时.py",
        post_url="https://www.joinquant.com/post/11102",
        execution_field="open",
        costs=TradingCosts(),
        jq_total_return=11.08913827,
        jq_annualized_return=0.22534374,
        jq_benchmark_total_return=3.83210157,
        jq_benchmark_annualized_return=0.13706185,
        jq_max_drawdown=0.30022293,
        jq_sharpe=0.96858476409965,
    ),
    StrategySpec(
        strategy_id="rsrs-standard",
        name="RSRS——大盘择时",
        signal_kind="rsrs-standard",
        symbol="SH000300",
        start_date="2008-07-01",
        end_date="2018-02-01",
        initial_cash=100_000_000.0,
        source_path="joinquant_archive/sources/2020年度精选策略/93 RSRS——大盘择时.py",
        post_url="https://www.joinquant.com/post/11115",
        execution_field="open",
        costs=TradingCosts(
            buy_commission=0.0003,
            sell_commission=0.0003,
            sell_tax=0.001,
            minimum_commission=5.0,
        ),
        jq_total_return=3.03761235,
        jq_annualized_return=0.16102088,
        jq_benchmark_total_return=0.52083642,
        jq_benchmark_annualized_return=0.04587126,
        jq_max_drawdown=0.29143794,
        jq_sharpe=0.70643443962257,
    ),
    StrategySpec(
        strategy_id="rsrs-volume-right-skew",
        name="RSRS 成交量加权右偏标准分",
        signal_kind="rsrs-volume-right-skew",
        symbol="SH000300",
        start_date="2014-01-01",
        end_date="2020-05-13",
        initial_cash=10_000_000.0,
        source_path=(
            "joinquant_archive/sources/2025年度精选策略/"
            "67.RSRS择时改进-【成交量加权-钝化-右偏】.py"
        ),
        post_url="https://www.joinquant.com/post/27399",
        execution_field="open",
        costs=TradingCosts(
            buy_commission=0.0003,
            sell_commission=0.0003,
            sell_tax=0.001,
            minimum_commission=5.0,
            slippage=0.00246,
        ),
        jq_total_return=2.65363086,
        jq_annualized_return=0.23259567,
        jq_benchmark_total_return=0.7030909,
        jq_benchmark_annualized_return=0.089734,
        jq_max_drawdown=0.1422977,
        jq_sharpe=1.1611795796101,
    ),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rolling_weighted_rsrs(
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    window: int,
) -> tuple[pd.Series, pd.Series]:
    """计算带截距的成交量加权 high~low 回归斜率及加权 R²。"""
    high_values = high.to_numpy(dtype=float)
    low_values = low.to_numpy(dtype=float)
    volume_values = volume.to_numpy(dtype=float)
    beta = np.full(len(high), np.nan, dtype=float)
    r_squared = np.full(len(high), np.nan, dtype=float)

    for end in range(window - 1, len(high)):
        start = end - window + 1
        y = high_values[start : end + 1]
        x = low_values[start : end + 1]
        weights = volume_values[start : end + 1]
        valid = (
            np.isfinite(x)
            & np.isfinite(y)
            & np.isfinite(weights)
            & (weights >= 0.0)
        )
        if valid.sum() != window or weights.sum() <= 0.0:
            continue
        weights = weights / weights.sum()
        x_mean = float(np.sum(weights * x))
        y_mean = float(np.sum(weights * y))
        x_centered = x - x_mean
        y_centered = y - y_mean
        denominator = float(np.sum(weights * x_centered * x_centered))
        if denominator <= 0.0:
            continue
        slope = float(np.sum(weights * x_centered * y_centered) / denominator)
        intercept = y_mean - slope * x_mean
        fitted = intercept + slope * x
        residual_sum = float(np.sum(weights * (y - fitted) ** 2))
        total_sum = float(np.sum(weights * y_centered**2))
        beta[end] = slope
        r_squared[end] = (
            1.0 - residual_sum / total_sum if total_sum > 0.0 else np.nan
        )

    return (
        pd.Series(beta, index=high.index, name="beta"),
        pd.Series(r_squared, index=high.index, name="r_squared"),
    )


def macd_signal(close: pd.Series, fast: int = 9, slow: int = 24) -> pd.Series:
    """复现源码实际使用的 MACD 主线；signalperiod 不影响买卖条件。"""
    fast_ema = close.ewm(span=fast, adjust=False, min_periods=fast).mean()
    slow_ema = close.ewm(span=slow, adjust=False, min_periods=slow).mean()
    return (fast_ema - slow_ema).rename("signal")


def standard_rsrs_signal(
    high: pd.Series,
    low: pd.Series,
    regression_window: int = 18,
    zscore_window: int = 480,
) -> pd.Series:
    covariance = low.rolling(regression_window).cov(high)
    variance = low.rolling(regression_window).var()
    beta = covariance / variance.replace(0.0, np.nan)
    rolling_mean = beta.rolling(zscore_window).mean()
    rolling_std = beta.rolling(zscore_window).std(ddof=1)
    return ((beta - rolling_mean) / rolling_std.replace(0.0, np.nan)).rename(
        "signal"
    )


def volume_right_skew_rsrs_signal(
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    regression_window: int = 18,
    zscore_window: int = 200,
) -> pd.Series:
    beta, r_squared = rolling_weighted_rsrs(
        high,
        low,
        volume,
        window=regression_window,
    )
    rolling_mean = beta.rolling(zscore_window).mean()
    rolling_std = beta.rolling(zscore_window).std(ddof=0)
    zscore = (beta - rolling_mean) / rolling_std.replace(0.0, np.nan)
    return (zscore * beta * r_squared).rename("signal")


def threshold_target(
    signal: pd.Series,
    buy: float,
    sell: float,
) -> pd.Series:
    """将观察日信号转成下一交易日目标仓位，避免同日未来数据。"""
    state = 0.0
    observation_targets = []
    for value in signal:
        if np.isfinite(value):
            if value > buy:
                state = 1.0
            elif value < sell:
                state = 0.0
        observation_targets.append(state)
    return (
        pd.Series(observation_targets, index=signal.index, dtype=float)
        .shift(1)
        .fillna(0.0)
        .rename("target")
    )


def build_target(frame: pd.DataFrame, signal_kind: str) -> tuple[pd.Series, pd.Series]:
    if signal_kind == "macd":
        signal = macd_signal(frame["close"])
        return signal, threshold_target(signal, buy=0.0, sell=0.0)
    if signal_kind == "rsrs-standard":
        signal = standard_rsrs_signal(frame["high"], frame["low"])
        return signal, threshold_target(signal, buy=0.7, sell=-0.7)
    if signal_kind == "rsrs-volume-right-skew":
        signal = volume_right_skew_rsrs_signal(
            frame["high"],
            frame["low"],
            frame["volume"],
        )
        return signal, threshold_target(signal, buy=0.85, sell=-0.85)
    raise ValueError(f"unsupported signal kind: {signal_kind}")


def _buy_all(cash: float, price: float, costs: TradingCosts) -> tuple[float, float]:
    if not np.isfinite(price) or price <= 0.0 or cash <= 0.0:
        return 0.0, cash
    execution_price = price * (1.0 + costs.slippage)
    units = cash / (execution_price * (1.0 + costs.buy_commission))
    gross = units * execution_price
    commission = max(gross * costs.buy_commission, costs.minimum_commission)
    if gross + commission > cash:
        units = max(cash - costs.minimum_commission, 0.0) / execution_price
        gross = units * execution_price
        commission = max(gross * costs.buy_commission, costs.minimum_commission)
    return units, max(cash - gross - commission, 0.0)


def simulate_all_in_out(
    frame: pd.DataFrame,
    target: pd.Series,
    initial_cash: float,
    costs: TradingCosts,
    execution_field: str = "open",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if execution_field not in frame:
        raise ValueError(f"missing execution field: {execution_field}")
    cash = float(initial_cash)
    units = 0.0
    equity_rows = []
    trade_rows = []
    target = target.reindex(frame.index).ffill().fillna(0.0)

    for date, row in frame.iterrows():
        desired = float(target.loc[date])
        execution_price = float(row[execution_field])
        gross_traded = 0.0
        if desired >= 0.5 and units <= 0.0:
            units, cash = _buy_all(cash, execution_price, costs)
            if units > 0.0:
                gross_traded = units * execution_price
                trade_rows.append(
                    {
                        "date": date,
                        "side": "buy",
                        "market_price": execution_price,
                        "execution_price": execution_price * (1.0 + costs.slippage),
                        "units": units,
                        "gross_traded": gross_traded,
                    }
                )
        elif desired < 0.5 and units > 0.0:
            slipped_price = execution_price * (1.0 - costs.slippage)
            gross = units * slipped_price
            commission = max(
                gross * costs.sell_commission,
                costs.minimum_commission,
            )
            tax = gross * costs.sell_tax
            cash += gross - commission - tax
            gross_traded = units * execution_price
            trade_rows.append(
                {
                    "date": date,
                    "side": "sell",
                    "market_price": execution_price,
                    "execution_price": slipped_price,
                    "units": units,
                    "gross_traded": gross_traded,
                }
            )
            units = 0.0

        close = float(row["close"])
        market_value = units * close if np.isfinite(close) else 0.0
        equity_rows.append(
            {
                "date": date,
                "equity": cash + market_value,
                "cash": cash,
                "market_value": market_value,
                "position": float(units > 0.0),
                "gross_traded": gross_traded,
            }
        )

    equity = pd.DataFrame(equity_rows).set_index("date")
    trades = pd.DataFrame(trade_rows)
    return equity, trades


def calculate_performance(
    equity: pd.DataFrame,
    initial_cash: float,
) -> dict:
    values = equity["equity"].astype(float)
    returns = values.pct_change(fill_method=None)
    returns.iloc[0] = values.iloc[0] / initial_cash - 1.0
    total_return = values.iloc[-1] / initial_cash - 1.0
    periods = len(values)
    annualized_return = (
        (1.0 + total_return) ** (TRADING_DAYS_PER_YEAR / periods) - 1.0
        if total_return > -1.0
        else -1.0
    )
    running_max = values.cummax()
    drawdown = values / running_max - 1.0
    max_drawdown = float(-drawdown.min())
    volatility = float(returns.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR))
    sharpe = (
        float(returns.mean() / returns.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR))
        if returns.std(ddof=1) > 0.0
        else np.nan
    )
    underwater = drawdown < -1e-12
    longest_underwater = 0
    current = 0
    for is_underwater in underwater:
        current = current + 1 if is_underwater else 0
        longest_underwater = max(longest_underwater, current)
    turnover = (
        float(equity["gross_traded"].sum() / values.mean())
        if values.mean() > 0.0
        else np.nan
    )
    return {
        "trading_days": periods,
        "total_return": float(total_return),
        "annualized_return": float(annualized_return),
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "annualized_volatility": volatility,
        "turnover": turnover,
        "longest_underwater_trading_days": int(longest_underwater),
        "average_cash_ratio": float((equity["cash"] / values).mean()),
    }


def benchmark_metrics(frame: pd.DataFrame) -> tuple[pd.Series, dict]:
    benchmark = (frame["close"] / float(frame["open"].iloc[0])).rename(
        "benchmark_value"
    )
    benchmark_equity = pd.DataFrame(
        {
            "equity": benchmark,
            "cash": 0.0,
            "gross_traded": 0.0,
        },
        index=frame.index,
    )
    return benchmark, calculate_performance(benchmark_equity, initial_cash=1.0)


def load_qlib_frames(
    qlib_dir: Path,
    symbols: tuple[str, ...],
    start_date: str,
    end_date: str,
) -> tuple[dict[str, pd.DataFrame], dict]:
    import qlib
    from qlib.data import D

    qlib_dir = qlib_dir.resolve()
    qlib.init(
        provider_uri=str(qlib_dir),
        region="cn",
        kernels=1,
        joblib_backend="threading",
    )
    prefix = "$"
    fields = [
        prefix + "open",
        prefix + "high",
        prefix + "low",
        prefix + "close",
        prefix + "volume",
        prefix + "factor",
    ]
    data = D.features(
        list(symbols),
        fields,
        start_time=start_date,
        end_time=end_date,
        freq="day",
    )
    frames = {}
    for symbol in symbols:
        frame = data.xs(symbol, level="instrument").copy()
        frame.columns = [column.removeprefix("$") for column in frame.columns]
        frame.index = pd.DatetimeIndex(frame.index).normalize()
        frame = frame.sort_index()
        if frame[["open", "high", "low", "close"]].isna().any(axis=None):
            raise ValueError(f"{symbol} contains missing OHLC rows")
        frames[symbol] = frame
    fingerprint = {
        "provider_uri": str(qlib_dir),
        "qlib_version": qlib.__version__,
        "requested_start": start_date,
        "requested_end": end_date,
        "symbols": list(symbols),
        "rows": {symbol: int(len(frame)) for symbol, frame in frames.items()},
        "first_date": {
            symbol: frame.index.min().strftime("%Y-%m-%d")
            for symbol, frame in frames.items()
        },
        "last_date": {
            symbol: frame.index.max().strftime("%Y-%m-%d")
            for symbol, frame in frames.items()
        },
    }
    return frames, fingerprint


def run_strategy(
    spec: StrategySpec,
    full_frame: pd.DataFrame,
    execution_field: str | None = None,
) -> dict:
    execution_field = execution_field or spec.execution_field
    signal, target = build_target(full_frame, spec.signal_kind)
    mask = (full_frame.index >= spec.start_date) & (full_frame.index <= spec.end_date)
    frame = full_frame.loc[mask].copy()
    if frame.empty:
        raise ValueError(f"{spec.strategy_id} has no rows in requested period")
    period_target = target.reindex(frame.index)
    equity, trades = simulate_all_in_out(
        frame,
        period_target,
        initial_cash=spec.initial_cash,
        costs=spec.costs,
        execution_field=execution_field,
    )
    equity["signal"] = signal.reindex(frame.index)
    equity["target"] = period_target
    benchmark, benchmark_result = benchmark_metrics(frame)
    equity["benchmark_value"] = benchmark
    metrics = calculate_performance(equity, initial_cash=spec.initial_cash)
    metrics.update(
        {
            "trade_count": int(len(trades)),
            "benchmark_total_return": benchmark_result["total_return"],
            "benchmark_annualized_return": benchmark_result["annualized_return"],
            "annualized_return_delta_pp": (
                metrics["annualized_return"] - spec.jq_annualized_return
            )
            * 100.0,
            "max_drawdown_delta_pp": (
                metrics["max_drawdown"] - spec.jq_max_drawdown
            )
            * 100.0,
            "sharpe_delta": metrics["sharpe"] - spec.jq_sharpe,
            "benchmark_annualized_delta_pp": (
                benchmark_result["annualized_return"]
                - spec.jq_benchmark_annualized_return
            )
            * 100.0,
        }
    )
    metrics["comparison"] = (
        "接近"
        if abs(metrics["annualized_return_delta_pp"]) <= 5.0
        and abs(metrics["max_drawdown_delta_pp"]) <= 5.0
        else "存在实质差异"
    )
    return {
        "spec": spec,
        "execution_field": execution_field,
        "equity": equity,
        "trades": trades,
        "metrics": metrics,
    }


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    return value


def _percent(value: float) -> str:
    return f"{value:.2%}"


def _number(value: float) -> str:
    return f"{value:.2f}" if np.isfinite(value) else "N/A"


def comparison_rows(results: list[dict]) -> pd.DataFrame:
    rows = []
    for result in results:
        spec = result["spec"]
        metrics = result["metrics"]
        rows.append(
            {
                "strategy_id": spec.strategy_id,
                "name": spec.name,
                "execution_field": result["execution_field"],
                "start_date": spec.start_date,
                "end_date": spec.end_date,
                "jq_total_return": spec.jq_total_return,
                "local_total_return": metrics["total_return"],
                "jq_annualized_return": spec.jq_annualized_return,
                "local_annualized_return": metrics["annualized_return"],
                "annualized_return_delta_pp": metrics["annualized_return_delta_pp"],
                "jq_max_drawdown": spec.jq_max_drawdown,
                "local_max_drawdown": metrics["max_drawdown"],
                "max_drawdown_delta_pp": metrics["max_drawdown_delta_pp"],
                "jq_sharpe": spec.jq_sharpe,
                "local_sharpe": metrics["sharpe"],
                "sharpe_delta": metrics["sharpe_delta"],
                "jq_benchmark_annualized_return": (
                    spec.jq_benchmark_annualized_return
                ),
                "local_benchmark_annualized_return": (
                    metrics["benchmark_annualized_return"]
                ),
                "benchmark_annualized_delta_pp": (
                    metrics["benchmark_annualized_delta_pp"]
                ),
                "trade_count": metrics["trade_count"],
                "turnover": metrics["turnover"],
                "comparison": metrics["comparison"],
            }
        )
    return pd.DataFrame(rows)


def build_report(
    primary_results: list[dict],
    sensitivity_result: dict,
    run_id: str,
    qlib_fingerprint: dict,
) -> str:
    table = [
        "| 策略 | 聚宽年化 | 本地年化 | 差值 | 聚宽回撤 | 本地回撤 | 差值 | 聚宽 Sharpe | 本地 Sharpe | 判断 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for result in primary_results:
        spec = result["spec"]
        metrics = result["metrics"]
        table.append(
            f"| {spec.name} | {_percent(spec.jq_annualized_return)} | "
            f"{_percent(metrics['annualized_return'])} | "
            f"{metrics['annualized_return_delta_pp']:+.2f} pp | "
            f"{_percent(spec.jq_max_drawdown)} | "
            f"{_percent(metrics['max_drawdown'])} | "
            f"{metrics['max_drawdown_delta_pp']:+.2f} pp | "
            f"{_number(spec.jq_sharpe)} | {_number(metrics['sharpe'])} | "
            f"{metrics['comparison']} |"
        )

    benchmark_table = [
        "| 策略区间 | 聚宽基准年化 | Qlib 基准年化 | 差值 |",
        "|---|---:|---:|---:|",
    ]
    for result in primary_results:
        spec = result["spec"]
        metrics = result["metrics"]
        benchmark_table.append(
            f"| {spec.name} | {_percent(spec.jq_benchmark_annualized_return)} | "
            f"{_percent(metrics['benchmark_annualized_return'])} | "
            f"{metrics['benchmark_annualized_delta_pp']:+.2f} pp |"
        )

    close_metrics = sensitivity_result["metrics"]
    open_result = next(
        result
        for result in primary_results
        if result["spec"].strategy_id == "rsrs-volume-right-skew"
    )
    open_metrics = open_result["metrics"]
    close_delta = (
        close_metrics["annualized_return"] - open_metrics["annualized_return"]
    ) * 100.0
    close_drawdown_delta = (
        close_metrics["max_drawdown"] - open_metrics["max_drawdown"]
    ) * 100.0
    close_note = (
        f"改进 RSRS 若改为下一交易日收盘成交，年化为 "
        f"{_percent(close_metrics['annualized_return'])}、最大回撤为 "
        f"{_percent(close_metrics['max_drawdown'])}；相对开盘成交分别变化 "
        f"{close_delta:+.2f} 和 {close_drawdown_delta:+.2f} 个百分点。"
    )

    close_matches = sum(
        result["metrics"]["comparison"] == "接近" for result in primary_results
    )
    conclusion = (
        f"按预先冻结的 ±5 个百分点标准，{close_matches}/"
        f"{len(primary_results)} 份策略能够近似复现。"
    )
    return f"""# 聚宽指数择时策略本地 Qlib 复现

运行标识：`{run_id}`

## 结论

{conclusion}

本次结果只检验固定源码在独立日线数据上的可复现性，没有调参。策略结果与聚宽
差异较大时，先检查数据、执行时点和统计口径，不把差异自动解释为策略失效。

## 主结果

{chr(10).join(table)}

## 基准对照

{chr(10).join(benchmark_table)}

基准差值反映行情源、首日买入价、年化天数和聚宽统计口径的综合差异。若基准已经
明显不一致，策略收益差值不能全部归因于信号。

## 执行时点敏感性

{close_note}

## 事实

- 数据目录：`{qlib_fingerprint['provider_uri']}`
- Qlib 版本：`{qlib_fingerprint['qlib_version']}`
- 行情：`SH000300` 与 `SZ399300`，日线 OHLCV
- 数据预热：{qlib_fingerprint['requested_start']} 至 {qlib_fingerprint['requested_end']}
- 信号使用上一交易日及以前数据，主结果下一交易日开盘成交。
- 成本按帖子源码显式设置；MACD 源码未设置成本，本地按零成本。
- `000300.XSHG`/`399300.XSHE` 被视为无跟踪误差的可交易指数代理。

## 推断

- 年化和回撤同时接近，才说明信号大致可跨数据源复现。
- 年化差异大、但基准接近，优先怀疑指标实现、成交时点或源代码与网页回测并非
  完全同一版本。
- 成交量加权 RSRS 对指数成交量口径最敏感；其差异不能直接外推到普通 RSRS。
- 即使能够复现，也只说明历史计算一致，不证明未来有效或可实盘交易。

## 局限

- Qlib 数据没有 14:00 分钟行情；改进 RSRS 只能用次日开盘和次日收盘作边界近似。
- 聚宽 Sharpe 的无风险利率及首日收益处理未完全公开，本地使用零无风险利率和
  每年 250 个交易日。
- 指数不可直接交易，真实 ETF 会产生跟踪误差、申赎影响和不同成交量。
- MACD 的 TA-Lib EMA 初始化与 pandas EMA 在样本最初阶段略有差异；预热约半年后
  影响应快速衰减。
"""


def archive_results(
    primary_results: list[dict],
    sensitivity_result: dict,
    qlib_fingerprint: dict,
    run_id: str,
    archived_at: str,
) -> Path:
    target = STUDY_DIR / "results" / f"{archived_at}__{run_id}"
    if target.exists():
        raise FileExistsError(f"result directory already exists: {target}")
    raw_dir = target / "raw"
    raw_dir.mkdir(parents=True)

    comparison = comparison_rows(primary_results + [sensitivity_result])
    comparison.to_csv(raw_dir / "comparison.csv", index=False, encoding="utf-8")
    for result in primary_results + [sensitivity_result]:
        suffix = (
            result["spec"].strategy_id
            if result["execution_field"] == result["spec"].execution_field
            else f"{result['spec'].strategy_id}__{result['execution_field']}-execution"
        )
        result["equity"].reset_index().to_csv(
            raw_dir / f"{suffix}__equity.csv",
            index=False,
            encoding="utf-8",
        )
        result["trades"].to_csv(
            raw_dir / f"{suffix}__trades.csv",
            index=False,
            encoding="utf-8",
        )

    engine_target = target / "engine.py"
    shutil.copy2(Path(__file__).resolve(), engine_target)
    strategy_records = []
    for result in primary_results:
        spec = result["spec"]
        source = ROOT / spec.source_path
        strategy_records.append(
            {
                "spec": _json_safe(asdict(spec)),
                "source_sha256": sha256_file(source),
                "execution_field": result["execution_field"],
                "local_metrics": _json_safe(result["metrics"]),
            }
        )
    manifest = {
        "schema_version": 1,
        "study_id": "joinquant-index-timing-replication",
        "run_id": run_id,
        "archived_at": archived_at,
        "engine": "local-qlib-daily-index-timing-v1",
        "engine_file": "engine.py",
        "engine_sha256": sha256_file(engine_target),
        "qlib": qlib_fingerprint,
        "success_threshold_pp": 5.0,
        "strategies": strategy_records,
        "sensitivity": {
            "strategy_id": sensitivity_result["spec"].strategy_id,
            "execution_field": sensitivity_result["execution_field"],
            "metrics": _json_safe(sensitivity_result["metrics"]),
        },
        "artifacts": {
            "comparison": "raw/comparison.csv",
            "report": "report.md",
        },
    }
    (target / "manifest.json").write_text(
        json.dumps(_json_safe(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (target / "report.md").write_text(
        build_report(
            primary_results,
            sensitivity_result,
            run_id,
            qlib_fingerprint,
        ),
        encoding="utf-8",
    )
    return target


def parse_args():
    parser = argparse.ArgumentParser(
        description="使用本地 Qlib 数据复现三份聚宽沪深300择时策略"
    )
    parser.add_argument("--qlib-dir", type=Path, default=DEFAULT_QLIB_DIR)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument(
        "--archived-at",
        default=pd.Timestamp.today().strftime("%Y-%m-%d"),
    )
    parser.add_argument("--no-archive", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbols = tuple(sorted({spec.symbol for spec in STRATEGIES}))
    frames, fingerprint = load_qlib_frames(
        args.qlib_dir,
        symbols=symbols,
        start_date="2005-01-04",
        end_date=max(spec.end_date for spec in STRATEGIES),
    )
    primary_results = [
        run_strategy(spec, frames[spec.symbol]) for spec in STRATEGIES
    ]
    improved_spec = next(
        spec for spec in STRATEGIES if spec.strategy_id == "rsrs-volume-right-skew"
    )
    sensitivity_result = run_strategy(
        improved_spec,
        frames[improved_spec.symbol],
        execution_field="close",
    )
    comparison = comparison_rows(primary_results + [sensitivity_result])
    print(comparison.to_string(index=False))
    if not args.no_archive:
        target = archive_results(
            primary_results,
            sensitivity_result,
            fingerprint,
            run_id=args.run_id,
            archived_at=args.archived_at,
        )
        print(f"结果已归档：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
