"""完成白马股攻防候选的预注册稳健性、执行、容量与归因研究。"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STUDY_DIR = Path(__file__).resolve().parent
ROOT = STUDY_DIR.parents[1]
if str(STUDY_DIR) not in sys.path:
    sys.path.insert(0, str(STUDY_DIR))

import run_epo_deep_research as diagnostics  # noqa: E402
import run_white_horse_causal as base  # noqa: E402


CANDIDATE_DIR = STUDY_DIR / "results" / base.CANDIDATE_ID
BASELINE_COMMISSION = 0.0003
BASELINE_SLIPPAGE = 0.001
BASELINE_ADV = 0.01
CAPITALS = (200_000, 1_000_000, 2_000_000, 10_000_000)
ADV_RATIOS = (0.005, 0.01, 0.05)
PARAMETER_VALUES = tuple(
    itertools.product((4, 5, 6), (0.9, 1.0, 1.1), (0.9, 1.0, 1.1))
)


def select_candidates(
    features: pd.DataFrame,
    temperature: str,
    *,
    holding_count: int = base.HOLDING_COUNT,
    valuation_scale: float = 1.0,
    quality_scale: float = 1.0,
    excluded_symbols: frozenset[str] = frozenset(),
) -> pd.DataFrame:
    frame = features[~features["symbol"].isin(excluded_symbols)].copy()
    adjusted = pd.to_numeric(
        frame["quarter_deducted_parent_net_profit"], errors="coerce"
    )
    cash_flow = pd.to_numeric(frame["quarter_operating_cash_flow"], errors="coerce")
    frame["cash_profit_ratio"] = cash_flow / adjusted.replace(0.0, np.nan)
    common = adjusted.gt(0.0) & cash_flow.gt(0.0)
    if temperature == "cold":
        mask = (
            common
            & frame["pb"].gt(0.0)
            & frame["pb"].lt(1.0 * valuation_scale)
            & frame["cash_profit_ratio"].gt(2.0 * quality_scale)
            & frame["quarter_roe"].gt(1.5 * quality_scale)
            & frame["net_profit_yoy"].gt(-15.0 / quality_scale)
        )
        score = frame["quarter_roa"] / frame["pb"]
    elif temperature == "warm":
        mask = (
            common
            & frame["pb"].gt(0.0)
            & frame["pb"].lt(1.0 * valuation_scale)
            & frame["cash_profit_ratio"].gt(1.0 * quality_scale)
            & frame["quarter_roe"].gt(2.0 * quality_scale)
            & frame["net_profit_yoy"].gt(0.0)
        )
        score = frame["quarter_roa"] / frame["pb"]
    elif temperature == "hot":
        mask = (
            common
            & frame["pb"].gt(3.0 * valuation_scale)
            & frame["cash_profit_ratio"].gt(0.5 * quality_scale)
            & frame["quarter_roe"].gt(3.0 * quality_scale)
            & frame["net_profit_yoy"].gt(20.0 * quality_scale)
        )
        score = frame["quarter_roa"]
    else:
        raise ValueError(f"unsupported market temperature: {temperature}")
    selected = frame.loc[mask].copy()
    selected["score"] = pd.to_numeric(score.loc[mask], errors="coerce")
    buffer_count = max(base.BUFFER_COUNT, holding_count + 1)
    return (
        selected.dropna(subset=["score"])
        .sort_values(["score", "symbol"], ascending=[False, True])
        .head(buffer_count)
        .reset_index(drop=True)
    )


def build_signal_cache(
    membership: pd.DataFrame,
    fundamentals: pd.DataFrame,
    valuation: pd.DataFrame,
    state: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    index_bars: pd.DataFrame,
) -> dict[pd.Timestamp, dict[str, Any]]:
    dates = pd.DatetimeIndex(calendar).normalize().sort_values().unique()
    schedule = base.scheduled_dates(dates, frequency="monthly", when="first")
    index_close = index_bars.set_index("trade_date")["close"].sort_index()
    temperature = "warm"
    signals: dict[pd.Timestamp, dict[str, Any]] = {}
    for position, trade_date in enumerate(dates):
        if trade_date not in schedule or position == 0:
            continue
        observation_date = dates[position - 1]
        temperature, temperature_diag = base.market_temperature(
            index_close.loc[:observation_date].tail(220), temperature
        )
        members = base._members(membership, observation_date)
        features = base.latest_visible_features(
            fundamentals, valuation, state, members, observation_date
        )
        signals[trade_date] = {
            "scheduled_date": trade_date,
            "observation_date": observation_date,
            "temperature": temperature,
            "temperature_diagnostics": temperature_diag,
            "features": features,
        }
    return signals


def build_execution_map(
    calendar: pd.DatetimeIndex,
    signals: dict[pd.Timestamp, dict[str, Any]],
    *,
    delay_sessions: int = 0,
    random_delays: dict[pd.Timestamp, int] | None = None,
) -> dict[pd.Timestamp, dict[str, Any]]:
    dates = pd.DatetimeIndex(calendar).normalize().sort_values().unique()
    result = {}
    for scheduled_date, signal in signals.items():
        delay = (
            int(random_delays[scheduled_date])
            if random_delays is not None
            else delay_sessions
        )
        location = dates.get_loc(scheduled_date)
        if location + delay >= len(dates):
            continue
        execution_date = dates[location + delay]
        result[execution_date] = {**signal, "execution_delay_sessions": delay}
    return result


def _unfilled_value(orders: pd.DataFrame) -> float:
    if orders.empty or "unfilled_shares" not in orders:
        return 0.0
    shares = pd.to_numeric(orders["unfilled_shares"], errors="coerce").fillna(0.0)
    prices = pd.to_numeric(orders["price"], errors="coerce").fillna(0.0)
    return float((shares * prices).sum())


def _performance(equity: pd.DataFrame, trades: pd.DataFrame) -> dict[str, Any]:
    metrics = base.performance_metrics(equity, trades, trading_days=250)
    returns = pd.to_numeric(equity["daily_return"], errors="coerce").fillna(0.0)
    downside = returns[returns < 0.0]
    metrics["sortino"] = (
        float(returns.mean() / downside.std(ddof=1) * math.sqrt(250.0))
        if len(downside) > 1 and downside.std(ddof=1) > 0.0
        else np.nan
    )
    return metrics


def simulate(
    bars: pd.DataFrame,
    state: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    signals: dict[pd.Timestamp, dict[str, Any]],
    *,
    initial_cash: float = base.INITIAL_CASH,
    holding_count: int = base.HOLDING_COUNT,
    valuation_scale: float = 1.0,
    quality_scale: float = 1.0,
    delay_sessions: int = 0,
    random_delays: dict[pd.Timestamp, int] | None = None,
    commission_rate: float = BASELINE_COMMISSION,
    slippage_rate: float = BASELINE_SLIPPAGE,
    maximum_volume_ratio: float = BASELINE_ADV,
    forced_temperature: str | None = None,
    equal_weight: bool = False,
    excluded_symbols: frozenset[str] = frozenset(),
    retry_sessions: int = 0,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    engine = base.DailyBacktester(
        bars,
        state,
        asset_types={symbol: "stock" for symbol in bars["symbol"].unique()},
        config=base.BacktestConfig(
            initial_cash=initial_cash,
            maximum_volume_ratio=maximum_volume_ratio,
            slippage_rate=slippage_rate,
            minimum_state_quality="B",
        ),
        costs=base.CostModel(
            buy_commission=commission_rate,
            sell_commission=commission_rate,
            minimum_commission=5.0,
        ),
    )
    execution_map = build_execution_map(
        calendar,
        signals,
        delay_sessions=delay_sessions,
        random_delays=random_delays,
    )
    target_rows = []
    pending: dict[str, Any] | None = None
    for trade_date in calendar:
        if trade_date in execution_map:
            signal = execution_map[trade_date]
            temperature = forced_temperature or signal["temperature"]
            candidates = select_candidates(
                signal["features"],
                temperature,
                holding_count=holding_count,
                valuation_scale=valuation_scale,
                quality_scale=quality_scale,
                excluded_symbols=excluded_symbols,
            )
            candidate_symbols = candidates["symbol"].tolist()
            if equal_weight:
                target_symbols = candidate_symbols[:holding_count]
                weight = 1.0 / len(target_symbols) if target_symbols else 0.0
                target_weights = {symbol: weight for symbol in target_symbols}
                engine.rebalance_to_weights(trade_date, target_weights, execution="open")
                pending = None
            else:
                pending = {
                    **signal,
                    "execution_date": trade_date,
                    "temperature_used": temperature,
                    "candidate_symbols": candidate_symbols,
                    "sell_symbols": [
                        symbol
                        for symbol in engine.positions
                        if symbol not in candidate_symbols
                    ],
                    "buy_targets": {},
                    "attempt": 0,
                }
        if pending is not None:
            for symbol in list(pending["sell_symbols"]):
                if symbol in engine.positions:
                    engine.order_target_value(trade_date, symbol, 0.0, execution="open")
            slots = holding_count - len(engine.positions)
            missing = [
                symbol
                for symbol in pending["candidate_symbols"][:holding_count]
                if symbol not in engine.positions
                and symbol not in pending["buy_targets"]
            ]
            if slots > 0 and missing:
                target_value = engine.cash / slots
                for symbol in missing[:slots]:
                    pending["buy_targets"][symbol] = target_value
            for symbol, target_value in pending["buy_targets"].items():
                engine.order_target_value(
                    trade_date, symbol, target_value, execution="open"
                )
            pending["attempt"] += 1
            sell_complete = all(
                symbol not in engine.positions for symbol in pending["sell_symbols"]
            )
            buy_complete = all(
                symbol in engine.positions for symbol in pending["buy_targets"]
            )
            completed = sell_complete and buy_complete
            if completed or pending["attempt"] > retry_sessions:
                target_rows.append(
                    {
                        "observation_date": pending["observation_date"],
                        "scheduled_date": pending["scheduled_date"],
                        "execution_date": pending["execution_date"],
                        "last_attempt_date": trade_date,
                        "temperature": pending["temperature_used"],
                        "execution_delay_sessions": pending[
                            "execution_delay_sessions"
                        ],
                        "completion_delay_sessions": int(
                            pd.DatetimeIndex(calendar).get_loc(trade_date)
                            - pd.DatetimeIndex(calendar).get_loc(
                                pending["scheduled_date"]
                            )
                        ),
                        "attempt_count": pending["attempt"],
                        "completed": completed,
                        "candidate_count": len(pending["candidate_symbols"]),
                        "candidates": "|".join(pending["candidate_symbols"]),
                    }
                )
                pending = None
        engine.mark_close(trade_date)
    metrics = _performance(engine.equity, engine.trades)
    targets = pd.DataFrame(target_rows)
    metrics.update(
        {
            "initial_cash": initial_cash,
            "holding_count": holding_count,
            "valuation_scale": valuation_scale,
            "quality_scale": quality_scale,
            "delay_sessions": delay_sessions,
            "commission_rate": commission_rate,
            "slippage_rate": slippage_rate,
            "adv_participation": maximum_volume_ratio,
            "average_exposure": 1.0 - metrics["average_cash_ratio"],
            "unfilled_value": _unfilled_value(engine.orders),
            "order_count": len(engine.orders),
            "trade_count": len(engine.trades),
            "rejected_order_count": len(engine.rejections),
            "average_completion_delay": (
                float(targets["completion_delay_sessions"].mean())
                if not targets.empty
                else np.nan
            ),
            "maximum_completion_delay": (
                int(targets["completion_delay_sessions"].max())
                if not targets.empty
                else 0
            ),
            "incomplete_rebalances": (
                int((~targets["completed"]).sum()) if not targets.empty else 0
            ),
        }
    )
    return metrics, {
        "equity": engine.equity,
        "orders": engine.orders,
        "trades": engine.trades,
        "holdings": engine.holdings,
        "targets": targets,
    }


def _result_row(
    experiment: str,
    variant: str,
    metrics: dict[str, Any],
    **extra,
) -> dict[str, Any]:
    return {
        "experiment": experiment,
        "variant": variant,
        "status": "ok",
        "annualized_return": metrics.get("annualized_return"),
        "maximum_drawdown": metrics.get("maximum_drawdown"),
        "sharpe": metrics.get("sharpe"),
        "sortino": metrics.get("sortino"),
        "turnover": metrics.get("turnover"),
        "average_cash_ratio": metrics.get("average_cash_ratio"),
        **extra,
    }


def benchmark_metrics(index_bars: pd.DataFrame) -> tuple[dict[str, Any], pd.Series]:
    close = index_bars.set_index("trade_date")["close"].sort_index()
    close = close.loc[base.PUBLIC_START : base.DATA_END]
    returns = close.pct_change(fill_method=None).fillna(0.0)
    curve = (1.0 + returns).cumprod()
    drawdown = curve / curve.cummax() - 1.0
    volatility = returns.std(ddof=1) * math.sqrt(250.0)
    years = len(returns) / 250.0
    return (
        {
            "annualized_return": float(curve.iloc[-1] ** (1.0 / years) - 1.0),
            "maximum_drawdown": float(-drawdown.min()),
            "sharpe": (
                float(returns.mean() * 250.0 / volatility)
                if volatility > 0.0
                else np.nan
            ),
        },
        returns,
    )


def build_attribution(
    frames: dict[str, pd.DataFrame],
    bars: pd.DataFrame,
    index_bars: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    equity = frames["equity"]
    dates = pd.DatetimeIndex(pd.to_datetime(equity["trade_date"]))
    total = pd.Series(equity["total_value"].to_numpy(dtype=float), index=dates)
    holdings = frames["holdings"].pivot(
        index="trade_date", columns="symbol", values="market_value"
    )
    holdings.index = pd.DatetimeIndex(holdings.index)
    weights = holdings.reindex(dates).fillna(0.0).div(total, axis=0).shift(1).fillna(0.0)
    close = bars.pivot(index="trade_date", columns="symbol", values="close")
    close = close.reindex(dates).ffill()
    asset_returns = close.pct_change(fill_method=None).fillna(0.0)
    contributions = weights.reindex(columns=asset_returns.columns, fill_value=0.0) * asset_returns
    aggregate = contributions.sum().sort_values(
        key=lambda series: series.abs(), ascending=False
    )
    absolute_total = aggregate.abs().sum()
    rows = [
        {
            "analysis_type": "stock-contribution",
            "name": symbol,
            "value": float(value),
            "absolute_share": (
                float(abs(value) / absolute_total) if absolute_total else np.nan
            ),
            "method": "prior-close exposure times close return; excludes fee residual",
        }
        for symbol, value in aggregate.items()
        if abs(value) > 0.0
    ]
    portfolio_returns = pd.Series(
        equity["daily_return"].to_numpy(dtype=float), index=dates, name="portfolio"
    )
    factors = index_bars.pivot(
        index="trade_date", columns="symbol", values="close"
    ).sort_index()
    factors = factors.pct_change(fill_method=None).reindex(dates)
    factors = factors.rename(
        columns={
            "SH000300": "large-cap",
            "SH000905": "mid-small-cap",
            "SZ399006": "growth",
        }
    )
    regression = pd.concat([portfolio_returns, factors], axis=1).dropna()
    if not regression.empty and len(factors.columns) > 0:
        design = np.column_stack(
            [np.ones(len(regression)), regression[factors.columns].to_numpy()]
        )
        coefficients, _, _, _ = np.linalg.lstsq(
            design, regression["portfolio"].to_numpy(), rcond=None
        )
        fitted = design @ coefficients
        denominator = np.sum(
            (regression["portfolio"] - regression["portfolio"].mean()) ** 2
        )
        r_squared = (
            1.0
            - np.sum((regression["portfolio"] - fitted) ** 2) / denominator
            if denominator > 0.0
            else np.nan
        )
        rows.append(
            {
                "analysis_type": "factor-beta",
                "name": "intercept-annualized",
                "value": float(coefficients[0] * 250.0),
                "absolute_share": np.nan,
                "method": f"OLS daily returns; model_r_squared={r_squared:.6f}",
            }
        )
        for name, coefficient in zip(factors.columns, coefficients[1:]):
            rows.append(
                {
                    "analysis_type": "factor-beta",
                    "name": name,
                    "value": float(coefficient),
                    "absolute_share": np.nan,
                    "method": f"OLS daily returns; model_r_squared={r_squared:.6f}",
                }
            )
    return pd.DataFrame(rows), aggregate.index.tolist()


def _period_row(
    experiment: str,
    variant: str,
    returns: pd.Series,
) -> dict[str, Any]:
    curve = (1.0 + returns).cumprod()
    drawdown = curve / curve.cummax() - 1.0
    sharpe = diagnostics._annualized_sharpe(returns)
    return {
        "experiment": experiment,
        "variant": variant,
        "status": "ok",
        "annualized_return": float(curve.iloc[-1] ** (250.0 / len(curve)) - 1.0),
        "maximum_drawdown": float(-drawdown.min()),
        "sharpe": sharpe if np.isfinite(sharpe) else np.nan,
    }


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def run_deep_research(
    data_root: Path | None = None,
    qlib_dir: Path = Path("D:/code/_open-source/_data/qlib/cn_data"),
) -> dict[str, Any]:
    (
        store,
        membership,
        fundamentals,
        valuation,
        state,
        calendar,
        bars,
        csi300_bars,
    ) = base.load_inputs(data_root, qlib_dir)
    portal = base.LocalDataPortal(store, base.QlibDailyBarSource(qlib_dir))
    factor_bars = portal.bars(
        ["SH000300", "SH000905", "SZ399006"],
        base.PUBLIC_START - pd.Timedelta(days=10),
        base.DATA_END,
        fields=("close",),
        adjustment="pre",
    )
    signals = build_signal_cache(
        membership, fundamentals, valuation, state, calendar, csi300_bars
    )
    rows: list[dict[str, Any]] = []
    experiment_count = 0

    baseline_metrics, baseline_frames = simulate(bars, state, calendar, signals)
    rows.append(_result_row("frozen-full-causal", "baseline", baseline_metrics))
    experiment_count += 1

    parameter_returns = {}
    parameter_positive = 0
    parameter_pass = 0
    for holding_count, valuation_scale, quality_scale in PARAMETER_VALUES:
        variant = f"h{holding_count}-v{valuation_scale:.1f}-q{quality_scale:.1f}"
        metrics, frames = simulate(
            bars,
            state,
            calendar,
            signals,
            holding_count=holding_count,
            valuation_scale=valuation_scale,
            quality_scale=quality_scale,
        )
        returns = pd.Series(
            frames["equity"]["daily_return"].to_numpy(dtype=float),
            index=pd.DatetimeIndex(frames["equity"]["trade_date"]),
        )
        parameter_returns[variant] = returns
        parameter_positive += metrics["annualized_return"] > 0.0
        parameter_pass += metrics["sharpe"] >= 0.5
        rows.append(
            _result_row(
                "parameter-neighborhood",
                variant,
                metrics,
                holding_count=holding_count,
                valuation_scale=valuation_scale,
                quality_scale=quality_scale,
                selected_for_promotion=False,
            )
        )
        experiment_count += 1

    delay_metrics = []
    for delay in (0, 1, 2, 3, 5):
        metrics, _ = simulate(
            bars, state, calendar, signals, delay_sessions=delay
        )
        delay_metrics.append(metrics)
        rows.append(
            _result_row(
                "execution-delay",
                f"delay-{delay}",
                metrics,
                delay_sessions=delay,
            )
        )
        experiment_count += 1

    for name, commission, slippage in (
        ("original", 0.00012, 0.0),
        ("baseline", BASELINE_COMMISSION, BASELINE_SLIPPAGE),
        ("double", 0.0006, 0.002),
    ):
        metrics, _ = simulate(
            bars,
            state,
            calendar,
            signals,
            commission_rate=commission,
            slippage_rate=slippage,
        )
        rows.append(
            _result_row(
                "cost-stress",
                name,
                metrics,
                commission_rate=commission,
                slippage_rate=slippage,
            )
        )
        experiment_count += 1

    warm_metrics, _ = simulate(
        bars, state, calendar, signals, forced_temperature="warm"
    )
    rows.append(_result_row("simple-baseline", "always-warm", warm_metrics))
    experiment_count += 1
    equal_metrics, _ = simulate(
        bars, state, calendar, signals, equal_weight=True
    )
    rows.append(
        _result_row("simple-baseline", "equal-weight-top-candidates", equal_metrics)
    )
    experiment_count += 1
    csi_metrics, csi_returns = benchmark_metrics(csi300_bars)
    rows.append(_result_row("simple-baseline", "csi300-buy-hold", csi_metrics))
    experiment_count += 1

    baseline_returns = pd.Series(
        baseline_frames["equity"]["daily_return"].to_numpy(dtype=float),
        index=pd.DatetimeIndex(baseline_frames["equity"]["trade_date"]),
    )
    for year, group in baseline_returns.groupby(baseline_returns.index.year):
        rows.append(_period_row("year-slice", str(year), group))
    for label, window in (("rolling-1y", 250), ("rolling-3y", 750), ("rolling-5y", 1250)):
        summary = diagnostics.rolling_return_summary(baseline_returns, window)
        rows.append(
            {
                "experiment": "rolling-window",
                "variant": label,
                "status": summary["status"],
                "rolling_minimum_return": summary.get("minimum"),
                "rolling_median_return": summary.get("median"),
                "rolling_maximum_return": summary.get("maximum"),
                "rolling_observation_count": summary.get("observation_count", 0),
            }
        )
    for endpoint in pd.to_datetime(
        ["2018-12-31", "2020-12-31", "2022-12-31", "2024-12-31", "2026-07-23"]
    ):
        subset = baseline_returns.loc[:endpoint]
        rows.append(
            _period_row(
                "expanding-fixed-baseline", endpoint.strftime("%Y-%m-%d"), subset
            )
        )

    bootstrap = diagnostics.moving_block_bootstrap(
        baseline_returns, block_size=20, samples=1000, seed=20260825
    )
    for quantile in (0.025, 0.5, 0.975):
        rows.append(
            {
                "experiment": "moving-block-bootstrap",
                "variant": f"q{quantile:.3f}",
                "status": "ok",
                "annualized_return": float(
                    bootstrap["annualized_return"].quantile(quantile)
                ),
                "maximum_drawdown": float(
                    bootstrap["maximum_drawdown"].quantile(quantile)
                ),
                "bootstrap_samples": len(bootstrap),
                "bootstrap_block_size": 20,
            }
        )

    return_frame = pd.DataFrame(parameter_returns).dropna(how="any")
    pbo = diagnostics.probability_of_backtest_overfitting(return_frame, blocks=8)
    rows.append(
        {
            "experiment": "multiple-testing",
            "variant": "pbo-27-neighborhood",
            "status": "ok",
            **pbo,
        }
    )
    dsr = diagnostics.deflated_sharpe_probability(baseline_returns, trials=27)
    rows.append(
        {
            "experiment": "multiple-testing",
            "variant": "deflated-sharpe-27-trials",
            "status": "ok",
            **dsr,
        }
    )

    rng = np.random.default_rng(20260825)
    signal_dates = sorted(signals)
    placebo_sharpes = []
    for trial in range(10):
        random_delays = {
            date: int(delay)
            for date, delay in zip(
                signal_dates, rng.integers(0, 6, size=len(signal_dates))
            )
        }
        metrics, _ = simulate(
            bars,
            state,
            calendar,
            signals,
            random_delays=random_delays,
        )
        placebo_sharpes.append(metrics["sharpe"])
        rows.append(
            _result_row(
                "placebo-random-delay",
                f"trial-{trial + 1:02d}",
                metrics,
                selected_for_promotion=False,
            )
        )
        experiment_count += 1

    attribution, contributors = build_attribution(
        baseline_frames, bars, factor_bars
    )
    top_ablation = {}
    for count in (1, 3):
        excluded = frozenset(contributors[:count])
        metrics, _ = simulate(
            bars,
            state,
            calendar,
            signals,
            excluded_symbols=excluded,
        )
        top_ablation[count] = metrics
        rows.append(
            _result_row(
                "top-contributor-ablation",
                f"remove-top-{count}",
                metrics,
                excluded_symbols="|".join(sorted(excluded)),
                selected_for_promotion=False,
            )
        )
        experiment_count += 1

    baseline_exposure = 1.0 - baseline_metrics["average_cash_ratio"]
    capacity_rows = []
    for capital, adv in itertools.product(CAPITALS, ADV_RATIOS):
        metrics, _ = simulate(
            bars,
            state,
            calendar,
            signals,
            initial_cash=float(capital),
            maximum_volume_ratio=adv,
            retry_sessions=5,
        )
        capacity_rows.append(
            {
                "capital_rmb": capital,
                "adv_participation": adv,
                "annualized_return": metrics["annualized_return"],
                "maximum_drawdown": metrics["maximum_drawdown"],
                "sharpe": metrics["sharpe"],
                "average_exposure": metrics["average_exposure"],
                "exposure_retention_vs_frozen": (
                    metrics["average_exposure"] / baseline_exposure
                ),
                "unfilled_value": metrics["unfilled_value"],
                "average_completion_delay": metrics["average_completion_delay"],
                "maximum_completion_delay": metrics["maximum_completion_delay"],
                "incomplete_rebalances": metrics["incomplete_rebalances"],
                "order_count": metrics["order_count"],
                "rejected_order_count": metrics["rejected_order_count"],
            }
        )
        experiment_count += 1

    robustness = pd.DataFrame(rows)
    capacity = pd.DataFrame(capacity_rows)
    raw = CANDIDATE_DIR / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    robustness.to_csv(CANDIDATE_DIR / "robustness.csv", index=False, encoding="utf-8-sig")
    capacity.to_csv(CANDIDATE_DIR / "capacity.csv", index=False, encoding="utf-8-sig")
    attribution.to_csv(CANDIDATE_DIR / "attribution.csv", index=False, encoding="utf-8-sig")
    bootstrap.to_csv(raw / "deep__moving-block-bootstrap.csv", index=False)
    return_frame.to_csv(raw / "deep__parameter-returns.csv", index=True)
    baseline_frames["equity"].to_csv(raw / "deep__baseline-equity.csv", index=False)
    baseline_frames["trades"].to_csv(raw / "deep__baseline-trades.csv", index=False)
    baseline_frames["targets"].to_csv(raw / "deep__baseline-targets.csv", index=False)

    positive_rate = parameter_positive / len(PARAMETER_VALUES)
    parameter_pass_rate = parameter_pass / len(PARAMETER_VALUES)
    minimum_delay_sharpe = min(item["sharpe"] for item in delay_metrics)
    primary_capacity = capacity[capacity["capital_rmb"].isin(CAPITALS[:3])]
    primary_minimum_exposure = float(primary_capacity["average_exposure"].min())
    primary_minimum_retention = float(
        primary_capacity["exposure_retention_vs_frozen"].min()
    )
    gates = {
        "first_causal_gate": True,
        "point_in_time_membership": True,
        "point_in_time_financials": True,
        "executable_order_model": True,
        "parameter_positive_return_gate": positive_rate >= 2.0 / 3.0,
        "parameter_sharpe_gate": parameter_pass_rate >= 2.0 / 3.0,
        "execution_delay_gate": minimum_delay_sharpe >= 0.5,
        "primary_capacity_gate": primary_minimum_exposure >= 0.90,
        "simple_baseline_gate": bool(
            baseline_metrics["annualized_return"] > csi_metrics["annualized_return"]
            and baseline_metrics["sharpe"] > csi_metrics["sharpe"]
        ),
        "credible_oos_gate": False,
        "platform_alignment_gate": False,
    }
    historical_gates = (
        "parameter_positive_return_gate",
        "parameter_sharpe_gate",
        "execution_delay_gate",
        "primary_capacity_gate",
        "simple_baseline_gate",
    )
    status = "R2" if all(gates[name] for name in historical_gates) else "R1"
    scorecard = {
        "schema_version": 1,
        "candidate_id": base.CANDIDATE_ID,
        "status": status,
        "source_vintage_grade": "C",
        "strict_natural_oos": False,
        "first_causal_run_preserved": True,
        "first_causal_gate_passed": True,
        "experiment_count": experiment_count,
        "parameter_neighborhood_trials": len(PARAMETER_VALUES),
        "parameter_positive_return_rate": positive_rate,
        "parameter_sharpe_ge_0_5_rate": parameter_pass_rate,
        "minimum_delay_sharpe": minimum_delay_sharpe,
        "primary_capital_minimum_exposure": primary_minimum_exposure,
        "frozen_baseline_average_exposure": baseline_exposure,
        "primary_capital_minimum_exposure_retention": primary_minimum_retention,
        "capacity_gate_interpretation": (
            "The preregistered >=90% absolute-exposure gate is retained as failed. "
            "It conflates the strategy's intentional cash state with execution loss; "
            "the post-result relative-retention diagnostic does not change promotion."
        ),
        "placebo_random_delay_minimum_sharpe": min(placebo_sharpes),
        "pbo": pbo,
        "deflated_sharpe": dsr,
        "gates": gates,
        "blocking_gaps_for_R3": [
            "source vintage is C and does not supply credible natural OOS",
            "JoinQuant/platform golden comparison is not complete",
            "production financial-data timestamp and failure contracts are not frozen",
            "frozen forward paper-trading evidence is absent",
        ],
        "blocking_gap_for_R2": (
            "preregistered absolute capacity gate failed; any replacement with a "
            "relative-exposure gate requires a new protocol and may not retroactively "
            "promote this run"
        ),
        "decision": (
            "historical R2 candidate; do not promote to R3"
            if status == "R2"
            else "remain R1; do not select a neighborhood winner"
        ),
    }
    (CANDIDATE_DIR / "live-readiness-scorecard.json").write_text(
        json.dumps(_json_safe(scorecard), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    top = attribution[attribution["analysis_type"].eq("stock-contribution")].iloc[0]
    worst_capacity = capacity.loc[capacity["average_exposure"].idxmin()]
    conclusion = f"""# 白马股攻防：完整历史研究结论

## 结论

当前等级：**{status}**。因果重建后的冻结基线完成了预注册稳健性、成本、执行延迟、容量、归因和
多重试验诊断；源码版本仍为 C，发布后回放不是严格天然 OOS，且没有平台订单级对照，因此最高
只能到 R2，不能称为冻结模拟盘或实盘候选。

## 事实

- 全期冻结因果版年化 {baseline_metrics['annualized_return']:.2%}、最大回撤
  {baseline_metrics['maximum_drawdown']:.2%}、Sharpe {baseline_metrics['sharpe']:.2f}；沪深300买入持有
  年化 {csi_metrics['annualized_return']:.2%}、最大回撤 {csi_metrics['maximum_drawdown']:.2%}、
  Sharpe {csi_metrics['sharpe']:.2f}。
- 27 个参数邻域中，{positive_rate:.1%} 年化为正，{parameter_pass_rate:.1%} 的 Sharpe 不低于 0.5；
  邻域只用于诊断，没有从中选择替代参数。
- 0/1/2/3/5 日延迟最低 Sharpe 为 {minimum_delay_sharpe:.2f}；10 个随机延迟安慰剂最低 Sharpe 为
  {min(placebo_sharpes):.2f}。
- PBO 为 {pbo['pbo']:.2%}，Deflated Sharpe 概率为
  {dsr['deflated_sharpe_probability']:.2%}；bootstrap 与滚动窗口完整保存在机器结果中。
- 最大近似股票贡献来自 `{top['name']}`，占绝对贡献 {top['absolute_share']:.1%}；删除 Top1 后年化
  {top_ablation[1]['annualized_return']:.2%}，删除 Top3 后年化 {top_ablation[3]['annualized_return']:.2%}。
- 20—200 万元容量网格最低平均风险暴露为 {primary_minimum_exposure:.2%}。全网格最差暴露为
  {worst_capacity['average_exposure']:.2%}（资金 {int(worst_capacity['capital_rmb']):,} 元、ADV
  {worst_capacity['adv_participation']:.1%}）。冻结基线自身平均暴露仅 {baseline_exposure:.2%}，小资金
  最低暴露保留率为 {primary_minimum_retention:.2%}；预注册的 90% 绝对暴露门槛混入了策略主动现金，
  但该门槛仍按失败保留，不能在看过结果后改成相对口径并追溯晋级。

## 推断

- 公开年化 35.88% 不能作为实盘预期；点时与真实执行修复后的收益档位明显更低。
- C 级发布后回放只能支持继续研究，不能提供 R4 所需的独立前瞻证据。
- 历史年化应至少按五折做资金规划，最大回撤按 1.5 倍准备；贡献集中度决定组合权重上限。

## 决定与下一步

保留为 {status}，不修改冻结参数。若继续容量研究，应先用新协议冻结“相对基线暴露保留率”口径；
本次结果不得因事后修订门槛而晋级。之后还需平台黄金对照、生产财务数据契约和冻结模拟盘；若平台
订单或前瞻执行否定优势，则淘汰当前版本。
"""
    (CANDIDATE_DIR / "conclusion.md").write_text(conclusion, encoding="utf-8")

    manifest = {
        "schema_version": 1,
        "candidate_id": base.CANDIDATE_ID,
        "run_id": "deep-research-v1",
        "created_at": "2026-08-25",
        "engine_path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
        "engine_sha256": base.sha256_file(Path(__file__).resolve()),
        "source_sha256": base.sha256_file(base.SOURCE_PATH),
        "protocol_sha256": base.sha256_file(CANDIDATE_DIR / "deep-protocol.json"),
        "experiment_count": experiment_count,
        "artifacts": [
            "robustness.csv",
            "capacity.csv",
            "attribution.csv",
            "live-readiness-scorecard.json",
            "conclusion.md",
        ],
    }
    (CANDIDATE_DIR / "deep-run-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return scorecard


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument(
        "--qlib-dir",
        type=Path,
        default=Path("D:/code/_open-source/_data/qlib/cn_data"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_deep_research(args.data_root, args.qlib_dir)
    print(json.dumps(_json_safe(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
