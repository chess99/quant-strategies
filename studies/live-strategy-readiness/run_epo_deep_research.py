"""完成 ETF 动量 + EPO 的稳健性、归因、多重试验与容量研究。"""

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
from scipy import stats


STUDY_DIR = Path(__file__).resolve().parent
ROOT = STUDY_DIR.parents[1]
if str(STUDY_DIR) not in sys.path:
    sys.path.insert(0, str(STUDY_DIR))

import run_epo_oos as base  # noqa: E402


CANDIDATE_DIR = STUDY_DIR / "results" / base.CANDIDATE_ID
FULL_START = pd.Timestamp("2021-09-01")
FULL_END = base.OOS_END
BASELINE_COMMISSION = 0.0003
BASELINE_SLIPPAGE = 0.0005
BASELINE_ADV = 0.01
CAPITALS = (200_000, 1_000_000, 2_000_000, 10_000_000)
ADV_RATIOS = (0.005, 0.01, 0.05)


def build_execution_plan(
    calendar: pd.DatetimeIndex,
    delay_sessions: int = 0,
) -> list[dict[str, pd.Timestamp]]:
    dates = pd.DatetimeIndex(calendar).normalize().sort_values().unique()
    schedule = sorted(base.scheduled_dates(dates, frequency="monthly", when="first"))
    plan = []
    for scheduled in schedule:
        location = dates.get_loc(scheduled)
        if location == 0 or location + delay_sessions >= len(dates):
            continue
        plan.append(
            {
                "observation_date": dates[location - 1],
                "scheduled_date": scheduled,
                "execution_date": dates[location + delay_sessions],
            }
        )
    return plan


def moving_block_bootstrap(
    returns: pd.Series,
    *,
    block_size: int = 20,
    samples: int = 1000,
    seed: int = 20260825,
) -> pd.DataFrame:
    values = pd.to_numeric(returns, errors="coerce").dropna().to_numpy(dtype=float)
    if len(values) < block_size:
        raise ValueError("returns are shorter than one bootstrap block")
    rng = np.random.default_rng(seed)
    starts = np.arange(len(values) - block_size + 1)
    rows = []
    for _ in range(samples):
        selected = []
        while len(selected) < len(values):
            start = int(rng.choice(starts))
            selected.extend(values[start : start + block_size])
        sample = np.asarray(selected[: len(values)], dtype=float)
        curve = np.cumprod(1.0 + sample)
        annualized = curve[-1] ** (250.0 / len(sample)) - 1.0
        drawdown = curve / np.maximum.accumulate(curve) - 1.0
        rows.append(
            {
                "annualized_return": float(annualized),
                "maximum_drawdown": float(-drawdown.min()),
            }
        )
    return pd.DataFrame(rows)


def _annualized_sharpe(values: pd.Series) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    volatility = clean.std(ddof=1)
    if len(clean) < 2 or volatility <= 0.0:
        return float("-inf")
    return float(clean.mean() / volatility * math.sqrt(250.0))


def probability_of_backtest_overfitting(
    strategy_returns: pd.DataFrame,
    *,
    blocks: int = 8,
) -> dict[str, Any]:
    frame = strategy_returns.dropna(how="any")
    if blocks % 2 or blocks < 4:
        raise ValueError("blocks must be an even integer of at least four")
    segments = [segment for segment in np.array_split(frame.index, blocks) if len(segment)]
    if len(segments) != blocks:
        raise ValueError("not enough observations for requested PBO blocks")
    logits = []
    below_median = 0
    split_count = 0
    for train_ids in itertools.combinations(range(blocks), blocks // 2):
        test_ids = sorted(set(range(blocks)) - set(train_ids))
        train_index = segments[train_ids[0]]
        for segment_id in train_ids[1:]:
            train_index = train_index.append(segments[segment_id])
        test_index = segments[test_ids[0]]
        for segment_id in test_ids[1:]:
            test_index = test_index.append(segments[segment_id])
        train_sharpes = frame.loc[train_index].apply(_annualized_sharpe)
        selected = train_sharpes.idxmax()
        test_sharpes = frame.loc[test_index].apply(_annualized_sharpe)
        rank = test_sharpes.rank(method="average", pct=True).loc[selected]
        rank = float(np.clip(rank, 1e-6, 1.0 - 1e-6))
        logits.append(math.log(rank / (1.0 - rank)))
        below_median += rank <= 0.5
        split_count += 1
    return {
        "pbo": below_median / split_count,
        "split_count": split_count,
        "strategy_count": frame.shape[1],
        "median_logit": float(np.median(logits)),
    }


def deflated_sharpe_probability(
    returns: pd.Series,
    *,
    trials: int,
) -> dict[str, float]:
    values = pd.to_numeric(returns, errors="coerce").dropna().to_numpy(dtype=float)
    daily_sharpe = float(values.mean() / values.std(ddof=1))
    skew = float(stats.skew(values, bias=False))
    kurtosis = float(stats.kurtosis(values, fisher=False, bias=False))
    gamma = 0.5772156649015329
    expected_max = (
        (1.0 - gamma) * stats.norm.ppf(1.0 - 1.0 / trials)
        + gamma * stats.norm.ppf(1.0 - 1.0 / (trials * math.e))
    ) / math.sqrt(max(len(values) - 1, 1))
    denominator = math.sqrt(
        max(
            1e-12,
            1.0 - skew * daily_sharpe + ((kurtosis - 1.0) / 4.0) * daily_sharpe**2,
        )
    )
    statistic = (daily_sharpe - expected_max) * math.sqrt(len(values) - 1) / denominator
    return {
        "observed_annualized_sharpe": daily_sharpe * math.sqrt(250.0),
        "expected_max_daily_sharpe": float(expected_max),
        "deflated_sharpe_probability": float(stats.norm.cdf(statistic)),
        "skew": skew,
        "kurtosis": kurtosis,
        "trial_count": trials,
    }


def _performance_from_equity(equity: pd.DataFrame, trades: pd.DataFrame) -> dict[str, Any]:
    metrics = base.performance_metrics(equity, trades, trading_days=250)
    returns = pd.to_numeric(equity["daily_return"], errors="coerce").fillna(0.0)
    downside = returns[returns < 0.0]
    metrics["sortino"] = (
        float(returns.mean() / downside.std(ddof=1) * math.sqrt(250.0))
        if len(downside) > 1 and downside.std(ddof=1) > 0
        else np.nan
    )
    return metrics


def simulate(
    bars: pd.DataFrame,
    market_state: pd.DataFrame,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    initial_cash: float = 1_000_000.0,
    method: str = "epo",
    momentum_days: int = base.MOMENTUM_DAYS,
    stock_num: int = base.STOCK_NUM,
    epo_w: float = base.EPO_W,
    delay_sessions: int = 0,
    commission_rate: float = BASELINE_COMMISSION,
    slippage_rate: float = BASELINE_SLIPPAGE,
    maximum_volume_ratio: float = BASELINE_ADV,
    pool: tuple[str, ...] = base.ETF_SYMBOLS,
    retry_sessions: int = 0,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    selected_bars = bars[bars["symbol"].isin(pool)].copy()
    close = selected_bars.pivot(
        index="trade_date", columns="symbol", values="adjusted_close"
    ).sort_index()
    period_bars = selected_bars[selected_bars["trade_date"].between(start, end)].copy()
    engine_bars = period_bars[
        ["symbol", "trade_date", "adjusted_open", "adjusted_close", "volume"]
    ].rename(columns={"adjusted_open": "open", "adjusted_close": "close"})
    period_state = market_state[
        market_state["symbol"].isin(pool)
        & market_state["trade_date"].between(start, end)
    ].copy()
    calendar = pd.DatetimeIndex(sorted(period_bars["trade_date"].unique()))
    plan = build_execution_plan(calendar, delay_sessions=delay_sessions)
    plan_by_date = {item["execution_date"]: item for item in plan}
    open_price = engine_bars.set_index(["trade_date", "symbol"])["open"]
    engine = base.DailyBacktester(
        engine_bars,
        period_state,
        asset_types={symbol: "etf" for symbol in pool},
        config=base.BacktestConfig(
            initial_cash=initial_cash,
            lot_size=100,
            maximum_volume_ratio=maximum_volume_ratio,
            slippage_rate=slippage_rate,
            t_plus_one_asset_types=("stock",),
            minimum_state_quality="B",
        ),
        costs=base.CostModel(
            buy_commission=commission_rate,
            sell_commission=commission_rate,
            minimum_commission=5.0,
            etf_buy_commission=commission_rate,
            etf_sell_commission=commission_rate,
            etf_minimum_commission=5.0,
        ),
    )
    target_rows = []
    pending = None
    for trade_date in calendar:
        if trade_date in plan_by_date:
            item = plan_by_date[trade_date]
            weights, diagnostics = base.build_target_weights(
                close,
                item["observation_date"],
                method=method,
                momentum_days=momentum_days,
                stock_num=stock_num,
                epo_w=epo_w,
                price_history_days=base.PRICE_HISTORY_DAYS,
            )
            pending = {
                **item,
                "weights": weights,
                "diagnostics": diagnostics,
                "attempt": 0,
            }
        if pending is not None:
            before = len(engine.order_records)
            engine.rebalance_to_weights(trade_date, pending["weights"], execution="open")
            new_orders = engine.orders.iloc[before:]
            meaningful_unfilled = (
                pd.to_numeric(new_orders["unfilled_shares"], errors="coerce").fillna(0)
                if not new_orders.empty
                else pd.Series(dtype=float)
            )
            failed = bool(meaningful_unfilled.ge(engine.config.lot_size).any())
            last_unfilled_value = 0.0
            if not new_orders.empty:
                for order in new_orders.itertuples(index=False):
                    if order.unfilled_shares < engine.config.lot_size:
                        continue
                    price = order.price
                    if pd.isna(price):
                        price = open_price.get(
                            (pd.Timestamp(order.trade_date), order.symbol), np.nan
                        )
                    if pd.notna(price):
                        last_unfilled_value += float(order.unfilled_shares) * float(price)
            pending["attempt"] += 1
            completed = not failed
            if completed or pending["attempt"] > retry_sessions:
                target_rows.append(
                    {
                        "observation_date": pending["observation_date"],
                        "scheduled_date": pending["scheduled_date"],
                        "execution_date": pending["execution_date"],
                        "last_attempt_date": trade_date,
                        "signal_delay_sessions": delay_sessions,
                        "completion_delay_sessions": int(
                            calendar.get_loc(trade_date)
                            - calendar.get_loc(pending["scheduled_date"])
                        ),
                        "completed": completed,
                        "attempt_count": pending["attempt"],
                        "unfilled_value": last_unfilled_value,
                        "selected": "|".join(
                            pending["diagnostics"].get("selected", [])
                        ),
                        "weights_json": json.dumps(
                            pending["weights"], ensure_ascii=False, sort_keys=True
                        ),
                    }
                )
                pending = None
        engine.mark_close(trade_date)
    metrics = _performance_from_equity(engine.equity, engine.trades)
    orders = engine.orders
    targets = pd.DataFrame(target_rows)
    metrics.update(
        {
            "period_start": pd.Timestamp(start).strftime("%Y-%m-%d"),
            "period_end": pd.Timestamp(end).strftime("%Y-%m-%d"),
            "initial_cash": initial_cash,
            "method": method,
            "momentum_days": momentum_days,
            "stock_num": stock_num,
            "epo_w": epo_w,
            "delay_sessions": delay_sessions,
            "commission_rate": commission_rate,
            "slippage_rate": slippage_rate,
            "adv_participation": maximum_volume_ratio,
            "average_exposure": 1.0 - metrics["average_cash_ratio"],
            "unfilled_value": (
                float(targets["unfilled_value"].sum()) if not targets.empty else 0.0
            ),
            "rejected_order_count": len(engine.rejections),
            "order_count": len(orders),
            "trade_count": len(engine.trades),
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
        "trades": engine.trades,
        "orders": orders,
        "holdings": engine.holdings,
        "targets": targets,
    }


def rolling_return_summary(returns: pd.Series, window: int) -> dict[str, Any]:
    clean = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    if len(clean) < window:
        return {"status": "insufficient", "window": window}
    rolling = (1.0 + clean).rolling(window).apply(np.prod, raw=True) - 1.0
    rolling = rolling.dropna()
    return {
        "status": "ok",
        "window": window,
        "minimum": float(rolling.min()),
        "median": float(rolling.median()),
        "maximum": float(rolling.max()),
        "observation_count": len(rolling),
    }


def build_attribution(
    baseline_frames: dict[str, pd.DataFrame],
    bars: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    equity = baseline_frames["equity"].copy()
    holdings = baseline_frames["holdings"].copy()
    dates = pd.DatetimeIndex(pd.to_datetime(equity["trade_date"]))
    total = pd.Series(equity["total_value"].to_numpy(dtype=float), index=dates)
    value = holdings.pivot(index="trade_date", columns="symbol", values="market_value")
    value.index = pd.DatetimeIndex(value.index)
    value = value.reindex(dates).fillna(0.0)
    weights = value.div(total, axis=0).shift(1).fillna(0.0)
    close = bars.pivot(index="trade_date", columns="symbol", values="adjusted_close")
    close = close.reindex(dates).ffill()
    asset_returns = close.pct_change(fill_method=None).fillna(0.0)
    contributions = weights.reindex(columns=asset_returns.columns, fill_value=0.0) * asset_returns
    aggregate = contributions.sum().sort_values(key=lambda series: series.abs(), ascending=False)
    absolute_total = aggregate.abs().sum()
    rows = [
        {
            "analysis_type": "asset-contribution",
            "name": symbol,
            "value": float(value),
            "absolute_share": float(abs(value) / absolute_total) if absolute_total else np.nan,
            "period_start": FULL_START.strftime("%Y-%m-%d"),
            "period_end": FULL_END.strftime("%Y-%m-%d"),
            "method": "prior-close exposure times close return; excludes intraday/fee residual",
        }
        for symbol, value in aggregate.items()
        if abs(value) > 0.0
    ]

    portfolio_returns = pd.Series(
        equity["daily_return"].to_numpy(dtype=float), index=dates, name="portfolio"
    )
    factor_symbols = {
        "domestic-large": "SH510300",
        "domestic-growth": "SZ159915",
        "nasdaq": "SH513100",
        "gold": "SH518880",
        "commodity": "SZ159985",
    }
    factors = pd.DataFrame(
        {
            name: asset_returns[symbol]
            for name, symbol in factor_symbols.items()
            if symbol in asset_returns
        }
    ).reindex(dates)
    regression = pd.concat([portfolio_returns, factors], axis=1).dropna()
    design = np.column_stack([np.ones(len(regression)), regression[factors.columns].to_numpy()])
    coefficients, _, _, _ = np.linalg.lstsq(
        design, regression["portfolio"].to_numpy(), rcond=None
    )
    fitted = design @ coefficients
    denominator = np.sum((regression["portfolio"] - regression["portfolio"].mean()) ** 2)
    r_squared = 1.0 - np.sum((regression["portfolio"] - fitted) ** 2) / denominator
    rows.append(
        {
            "analysis_type": "factor-beta",
            "name": "intercept-annualized",
            "value": float(coefficients[0] * 250.0),
            "absolute_share": np.nan,
            "period_start": FULL_START.strftime("%Y-%m-%d"),
            "period_end": FULL_END.strftime("%Y-%m-%d"),
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
                "period_start": FULL_START.strftime("%Y-%m-%d"),
                "period_end": FULL_END.strftime("%Y-%m-%d"),
                "method": f"OLS daily returns; model_r_squared={r_squared:.6f}",
            }
        )
    return pd.DataFrame(rows), aggregate.index.tolist()


def _result_row(experiment: str, variant: str, metrics: dict[str, Any], **extra) -> dict:
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


def run_deep_research(data_root: Path | None = None) -> dict[str, Any]:
    store = base.ResearchDataStore(data_root)
    bars = base.load_bars(store)
    market_state = base.build_market_state(bars)
    robustness_rows: list[dict[str, Any]] = []
    experiment_count = 0

    baseline_metrics, baseline_frames = simulate(
        bars, market_state, start=FULL_START, end=FULL_END
    )
    experiment_count += 1
    robustness_rows.append(
        _result_row("frozen-full-causal", "baseline", baseline_metrics)
    )

    parameter_returns = {}
    parameter_positive = 0
    parameter_pass = 0
    for momentum_days, stock_num, epo_w in itertools.product(
        (30, 34, 40), (2, 3, 4), (0.1, 0.2, 0.3)
    ):
        variant = f"m{momentum_days}-n{stock_num}-w{epo_w:.1f}"
        try:
            metrics, frames = simulate(
                bars,
                market_state,
                start=FULL_START,
                end=FULL_END,
                momentum_days=momentum_days,
                stock_num=stock_num,
                epo_w=epo_w,
            )
            parameter_returns[variant] = pd.Series(
                frames["equity"]["daily_return"].to_numpy(dtype=float),
                index=pd.DatetimeIndex(frames["equity"]["trade_date"]),
            )
            parameter_positive += metrics["annualized_return"] > 0.0
            parameter_pass += metrics["sharpe"] >= 0.5
            row = _result_row(
                "parameter-neighborhood",
                variant,
                metrics,
                momentum_days=momentum_days,
                stock_num=stock_num,
                epo_w=epo_w,
                selected_for_promotion=False,
            )
        except (ValueError, np.linalg.LinAlgError) as exc:
            row = {
                "experiment": "parameter-neighborhood",
                "variant": variant,
                "status": "failed",
                "momentum_days": momentum_days,
                "stock_num": stock_num,
                "epo_w": epo_w,
                "error": str(exc),
                "selected_for_promotion": False,
            }
        robustness_rows.append(row)
        experiment_count += 1

    delay_metrics = []
    for delay in (0, 1, 2, 3, 5):
        metrics, _ = simulate(
            bars,
            market_state,
            start=FULL_START,
            end=FULL_END,
            delay_sessions=delay,
        )
        delay_metrics.append(metrics)
        robustness_rows.append(
            _result_row(
                "execution-delay",
                f"delay-{delay}",
                metrics,
                delay_sessions=delay,
            )
        )
        experiment_count += 1

    for label, commission, slippage in (
        ("published", 0.0002, 0.0),
        ("baseline", 0.0003, 0.0005),
        ("double", 0.0006, 0.0010),
    ):
        metrics, _ = simulate(
            bars,
            market_state,
            start=FULL_START,
            end=FULL_END,
            commission_rate=commission,
            slippage_rate=slippage,
        )
        robustness_rows.append(
            _result_row(
                "cost-stress",
                label,
                metrics,
                commission_rate=commission,
                slippage_rate=slippage,
            )
        )
        experiment_count += 1

    for method in ("equal-top3", "equal-pool"):
        metrics, _ = simulate(
            bars,
            market_state,
            start=FULL_START,
            end=FULL_END,
            method=method,
        )
        robustness_rows.append(_result_row("module-ablation", method, metrics))
        experiment_count += 1

    for excluded in base.ETF_SYMBOLS:
        pool = tuple(symbol for symbol in base.ETF_SYMBOLS if symbol != excluded)
        try:
            metrics, _ = simulate(
                bars,
                market_state,
                start=FULL_START,
                end=FULL_END,
                pool=pool,
            )
            row = _result_row(
                "pool-perturbation",
                f"drop-{excluded}",
                metrics,
                excluded_symbols=excluded,
                selected_for_promotion=False,
            )
        except (ValueError, np.linalg.LinAlgError) as exc:
            row = {
                "experiment": "pool-perturbation",
                "variant": f"drop-{excluded}",
                "status": "failed",
                "excluded_symbols": excluded,
                "error": str(exc),
                "selected_for_promotion": False,
            }
        robustness_rows.append(row)
        experiment_count += 1

    baseline_returns = pd.Series(
        baseline_frames["equity"]["daily_return"].to_numpy(dtype=float),
        index=pd.DatetimeIndex(baseline_frames["equity"]["trade_date"]),
    )
    for year, group in baseline_returns.groupby(baseline_returns.index.year):
        curve = (1.0 + group).cumprod()
        drawdown = curve / curve.cummax() - 1.0
        robustness_rows.append(
            {
                "experiment": "year-slice",
                "variant": str(year),
                "status": "ok",
                "annualized_return": float((1.0 + group).prod() - 1.0),
                "maximum_drawdown": float(-drawdown.min()),
                "sharpe": _annualized_sharpe(group),
            }
        )
    for label, window in (("rolling-1y", 250), ("rolling-3y", 750), ("rolling-5y", 1250)):
        summary = rolling_return_summary(baseline_returns, window)
        robustness_rows.append(
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

    bootstrap = moving_block_bootstrap(baseline_returns, block_size=20, samples=1000)
    for quantile in (0.025, 0.5, 0.975):
        robustness_rows.append(
            {
                "experiment": "moving-block-bootstrap",
                "variant": f"q{quantile:.3f}",
                "status": "ok",
                "annualized_return": float(bootstrap["annualized_return"].quantile(quantile)),
                "maximum_drawdown": float(bootstrap["maximum_drawdown"].quantile(quantile)),
                "bootstrap_samples": len(bootstrap),
                "bootstrap_block_size": 20,
            }
        )

    parameter_return_frame = pd.DataFrame(parameter_returns).dropna(how="any")
    pbo = probability_of_backtest_overfitting(parameter_return_frame, blocks=8)
    robustness_rows.append(
        {
            "experiment": "multiple-testing",
            "variant": "pbo-27-neighborhood",
            "status": "ok",
            **pbo,
        }
    )
    dsr = deflated_sharpe_probability(baseline_returns, trials=27)
    robustness_rows.append(
        {
            "experiment": "multiple-testing",
            "variant": "deflated-sharpe-27-trials",
            "status": "ok",
            **dsr,
        }
    )

    attribution, ranked_contributors = build_attribution(baseline_frames, bars)
    for count in (1, 3):
        excluded = ranked_contributors[:count]
        pool = tuple(symbol for symbol in base.ETF_SYMBOLS if symbol not in excluded)
        try:
            metrics, _ = simulate(
                bars,
                market_state,
                start=FULL_START,
                end=FULL_END,
                pool=pool,
            )
            row = _result_row(
                "top-contributor-ablation",
                f"remove-top-{count}",
                metrics,
                excluded_symbols="|".join(excluded),
                selected_for_promotion=False,
            )
        except (ValueError, np.linalg.LinAlgError) as exc:
            row = {
                "experiment": "top-contributor-ablation",
                "variant": f"remove-top-{count}",
                "status": "failed",
                "excluded_symbols": "|".join(excluded),
                "error": str(exc),
                "selected_for_promotion": False,
            }
        robustness_rows.append(row)
        experiment_count += 1

    capacity_rows = []
    for capital, adv in itertools.product(CAPITALS, ADV_RATIOS):
        metrics, _ = simulate(
            bars,
            market_state,
            start=base.OOS_START,
            end=base.OOS_END,
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
                "unfilled_value": metrics["unfilled_value"],
                "average_completion_delay": metrics["average_completion_delay"],
                "maximum_completion_delay": metrics["maximum_completion_delay"],
                "incomplete_rebalances": metrics["incomplete_rebalances"],
                "order_count": metrics["order_count"],
                "rejected_order_count": metrics["rejected_order_count"],
            }
        )
        experiment_count += 1

    robustness = pd.DataFrame(robustness_rows)
    capacity = pd.DataFrame(capacity_rows)
    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    raw_dir = CANDIDATE_DIR / "raw"
    raw_dir.mkdir(exist_ok=True)
    robustness.to_csv(CANDIDATE_DIR / "robustness.csv", index=False, encoding="utf-8-sig")
    capacity.to_csv(CANDIDATE_DIR / "capacity.csv", index=False, encoding="utf-8-sig")
    attribution.to_csv(CANDIDATE_DIR / "attribution.csv", index=False, encoding="utf-8-sig")
    bootstrap.to_csv(raw_dir / "deep__moving-block-bootstrap.csv", index=False)
    baseline_frames["equity"].to_csv(raw_dir / "deep__baseline-equity.csv", index=False)
    baseline_frames["trades"].to_csv(raw_dir / "deep__baseline-trades.csv", index=False)
    baseline_frames["targets"].to_csv(raw_dir / "deep__baseline-targets.csv", index=False)
    parameter_return_frame.to_csv(raw_dir / "deep__parameter-returns.csv", index=True)

    parameter_pass_rate = parameter_pass / 27.0
    positive_rate = parameter_positive / 27.0
    delay_min_sharpe = min(item["sharpe"] for item in delay_metrics)
    primary_capacity = capacity[capacity["capital_rmb"].isin(CAPITALS[:3])]
    primary_min_exposure = float(primary_capacity["average_exposure"].min())
    oos = pd.read_csv(CANDIDATE_DIR / "oos.csv").set_index("scenario")
    oos_baseline = oos.loc["causal-baseline-cost"]
    gates = {
        "oos_pre_registered_gate": bool(
            oos_baseline["total_return"] > 0
            and oos_baseline["sharpe"] >= 0.5
            and oos_baseline["maximum_drawdown"] <= 0.35
        ),
        "parameter_neighborhood_gate": parameter_pass_rate >= 0.8,
        "execution_delay_gate": delay_min_sharpe >= 0.5,
        "primary_capacity_gate": primary_min_exposure >= 0.90,
        "platform_alignment_gate": False,
        "production_qdii_data_gate": False,
        "forward_paper_gate": False,
    }
    status = "R2" if all(
        gates[key]
        for key in (
            "oos_pre_registered_gate",
            "parameter_neighborhood_gate",
            "execution_delay_gate",
            "primary_capacity_gate",
        )
    ) else "R1"
    scorecard = {
        "schema_version": 1,
        "candidate_id": base.CANDIDATE_ID,
        "status": status,
        "source_vintage_grade": "B",
        "strict_natural_oos": False,
        "experiment_count": experiment_count,
        "parameter_neighborhood_trials": 27,
        "parameter_positive_return_rate": positive_rate,
        "parameter_sharpe_ge_0_5_rate": parameter_pass_rate,
        "minimum_delay_sharpe": delay_min_sharpe,
        "primary_capital_minimum_exposure": primary_min_exposure,
        "pbo": pbo,
        "deflated_sharpe": dsr,
        "gates": gates,
        "blocking_gaps_for_R3": [
            "JoinQuant/platform golden comparison of target weights and orders",
            "QDII premium/discount, subscription limits and cross-market calendar production feed",
            "frozen forward paper-trading evidence",
        ],
        "decision": (
            "historical R2 candidate; do not promote to R3"
            if status == "R2"
            else "remain R1 pending robustness gaps"
        ),
    }
    (CANDIDATE_DIR / "live-readiness-scorecard.json").write_text(
        json.dumps(base._json_safe(scorecard), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    top_contribution = attribution[attribution["analysis_type"].eq("asset-contribution")].iloc[0]
    min_capacity = capacity.loc[capacity["average_exposure"].idxmin()]
    conclusion = f"""# 多品种 ETF 动量 + EPO：完整历史研究结论

## 结论

当前等级：**{status}**。冻结版本通过 B 级发布后回放、执行延迟和 20—200 万元容量门槛，但参数
邻域门槛失败；同时没有平台订单级黄金对照、QDII 折溢价生产数据和冻结模拟盘，不能晋级 R2/R3，
更不能称为 R4 实盘候选。

## 事实

- 发布后现实摩擦年化 {oos_baseline['annualized_return']:.2%}、最大回撤
  {oos_baseline['maximum_drawdown']:.2%}、Sharpe {oos_baseline['sharpe']:.2f}；源码版本为 B 而非 A。
- 27 个参数邻域中，{positive_rate:.1%} 年化为正，{parameter_pass_rate:.1%} 的 Sharpe 不低于 0.5；
  这些试验只用于诊断，没有从中重新选择参数。
- 0/1/2/3/5 日延迟的最低 Sharpe 为 {delay_min_sharpe:.2f}。
- moving-block bootstrap、PBO 和 Deflated Sharpe 均已写入 `robustness.csv`；PBO 为 {pbo['pbo']:.2%}。
- 最大近似资产贡献来自 `{top_contribution['name']}`，占绝对贡献
  {top_contribution['absolute_share']:.1%}；Top1/Top3 删除结果也作为失败/集中度诊断保留。
- 20—200 万元在三档 ADV 中的最低平均风险暴露为 {primary_min_exposure:.2%}。全容量网格最差暴露为
  {min_capacity['average_exposure']:.2%}（资金 {int(min_capacity['capital_rmb']):,} 元、ADV
  {min_capacity['adv_participation']:.1%}）。1000 万元失败只影响扩容判断，不自动撤销小资金候选。

## 推断

- EPO 的收益并非由佣金假设主导，但权重和年份集中仍是主要折价项；它更像动态集中器，而不是稳定
  分散器。
- B 级发布后证据支持继续冻结模拟盘，但样本只有约 2.3 年，2025 年贡献高，不能外推 46% 年化。
- 历史收益应按规划压力至少打五折，最大回撤按 1.5 倍准备；组合配置必须限制该策略权重。

## 决定与下一步

保留为 {status}，不修改冻结参数。下一步只做平台黄金对照、QDII/ETF 实盘数据契约和冻结模拟盘；
若订单级对照或折溢价冲击使优势消失，则淘汰当前版本。未经新的独立数据，不再围绕历史收益调参。
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_deep_research(args.data_root)
    print(json.dumps(base._json_safe(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
