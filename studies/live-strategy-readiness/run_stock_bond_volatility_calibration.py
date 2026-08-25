"""在公开窗口内校准“股债波动平衡”的当前源码版本。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STUDY_DIR = Path(__file__).resolve().parent
ROOT = STUDY_DIR.parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.backtest import (  # noqa: E402
    BacktestConfig,
    CostModel,
    DailyBacktester,
    performance_metrics,
)
from quant_research.data.store import ResearchDataStore  # noqa: E402


CANDIDATE_ID = "stock-bond-volatility-balance"
CANDIDATE_DIR = STUDY_DIR / "results" / CANDIDATE_ID
SOURCE_PATH = (
    ROOT
    / "joinquant_archive"
    / "sources"
    / "2025年度精选策略"
    / "7.股债波动平衡.py"
)
CALIBRATION_START = pd.Timestamp("2014-06-01")
CALIBRATION_END = pd.Timestamp("2020-07-31")
INITIAL_CASH = 100_000.0
VOLATILITY_WINDOW = 40
DRIFT_THRESHOLD = 0.05
CASH_TRIGGER = 200.0

JQ_SYMBOLS = (
    "161005.XSHE",
    "163412.XSHE",
    "511010.XSHG",
    "513100.XSHG",
    "513500.XSHG",
    "518880.XSHG",
    "159928.XSHE",
    "512010.XSHG",
)
PRIOR_WEIGHTS = pd.Series(
    [15.0, 20.0, 2.0, 15.0, 7.5, 4.0, 25.0, 20.0],
    index=JQ_SYMBOLS,
    dtype=float,
)


def to_local_symbol(symbol: str) -> str:
    code, exchange = symbol.upper().split(".")
    return ("SH" if exchange == "XSHG" else "SZ") + code


LOCAL_SYMBOLS = tuple(to_local_symbol(symbol) for symbol in JQ_SYMBOLS)
PRIOR_WEIGHTS_LOCAL = pd.Series(
    PRIOR_WEIGHTS.to_numpy(), index=LOCAL_SYMBOLS, dtype=float
)
LOF_SYMBOLS = ("SZ161005", "SZ163412")
LOCAL_ETF_SYMBOLS = tuple(symbol for symbol in LOCAL_SYMBOLS if symbol not in LOF_SYMBOLS)

PUBLIC_BACKTEST = {
    "scenario": "published-public-backtest",
    "evidence_scope": "public in-sample aggregate",
    "period_start": "2014-06-01",
    "period_end": "2020-07-31",
    "initial_cash": 100_000.0,
    "total_return": 1.1875873187,
    "annualized_return": 0.1388660779521,
    "maximum_drawdown": 0.084382235325559,
    "sharpe": 1.4417718336376,
    "sortino": 1.8255568944958,
    "comparable_to_local": True,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_csv(frame: pd.DataFrame, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(handle)
    Path(temporary_name).unlink(missing_ok=True)
    try:
        frame.to_csv(temporary_name, index=False, encoding="utf-8")
        Path(temporary_name).replace(target)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _provider_symbol(local_symbol: str) -> str:
    return local_symbol[:2].lower() + local_symbol[2:]


def load_lof_bars(
    store: ResearchDataStore,
    local_symbol: str,
    *,
    refresh: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    provider_symbol = _provider_symbol(local_symbol)
    raw_path = store.raw_dir / "sina" / "fund_etf" / f"{local_symbol}.csv"
    adjusted_path = (
        store.raw_dir / "tencent" / "fund_hfq_daily" / f"{local_symbol}.csv"
    )
    if refresh or not raw_path.is_file() or not adjusted_path.is_file():
        import akshare as ak

        raw = ak.fund_etf_hist_sina(symbol=provider_symbol)
        adjusted = ak.stock_zh_a_hist_tx(
            symbol=provider_symbol,
            start_date="20000101",
            end_date="20260825",
            adjust="hfq",
            timeout=20,
        )
        _atomic_csv(raw, raw_path)
        _atomic_csv(adjusted, adjusted_path)
    raw = pd.read_csv(raw_path, parse_dates=["date"])
    adjusted = pd.read_csv(adjusted_path, parse_dates=["date"])
    raw["date"] = pd.to_datetime(raw["date"]).dt.normalize()
    adjusted["date"] = pd.to_datetime(adjusted["date"]).dt.normalize()
    required_raw = {"date", "open", "high", "low", "close", "volume", "amount"}
    required_adjusted = {"date", "open", "high", "low", "close"}
    if missing := required_raw.difference(raw.columns):
        raise ValueError(f"Sina LOF data is missing columns: {sorted(missing)}")
    if missing := required_adjusted.difference(adjusted.columns):
        raise ValueError(f"Tencent LOF data is missing columns: {sorted(missing)}")
    merged = raw[list(required_raw)].merge(
        adjusted[list(required_adjusted)],
        on="date",
        how="inner",
        suffixes=("", "_adjusted"),
        validate="one_to_one",
    )
    frame = pd.DataFrame(
        {
            "symbol": local_symbol,
            "trade_date": merged["date"],
            "open": pd.to_numeric(merged["open"], errors="raise"),
            "high": pd.to_numeric(merged["high"], errors="raise"),
            "low": pd.to_numeric(merged["low"], errors="raise"),
            "close": pd.to_numeric(merged["close"], errors="raise"),
            "volume": pd.to_numeric(merged["volume"], errors="raise"),
            "amount": pd.to_numeric(merged["amount"], errors="raise"),
            "adjusted_open": pd.to_numeric(
                merged["open_adjusted"], errors="raise"
            ),
            "adjusted_close": pd.to_numeric(
                merged["close_adjusted"], errors="raise"
            ),
        }
    ).sort_values("trade_date")
    if frame["trade_date"].max() < CALIBRATION_END:
        raise ValueError(f"LOF data for {local_symbol} does not reach calibration end")
    evidence = {
        "symbol": local_symbol,
        "raw_provider": "Sina via akshare.fund_etf_hist_sina",
        "adjusted_provider": "Tencent via akshare.stock_zh_a_hist_tx(hfq)",
        "raw_path": str(raw_path),
        "raw_sha256": sha256_file(raw_path),
        "adjusted_path": str(adjusted_path),
        "adjusted_sha256": sha256_file(adjusted_path),
        "first_date": frame["trade_date"].min().strftime("%Y-%m-%d"),
        "last_date": frame["trade_date"].max().strftime("%Y-%m-%d"),
        "row_count": len(frame),
    }
    return frame.reset_index(drop=True), evidence


def load_bars(
    store: ResearchDataStore,
    *,
    refresh_lof: bool = False,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    local = store.read_symbol_partitions(
        "etf_daily",
        LOCAL_ETF_SYMBOLS,
        columns=[
            "symbol",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "adjusted_open",
            "adjusted_close",
        ],
        strict=True,
    )
    local["trade_date"] = pd.to_datetime(local["trade_date"]).dt.normalize()
    lof_frames = []
    evidence = []
    for symbol in LOF_SYMBOLS:
        frame, item = load_lof_bars(store, symbol, refresh=refresh_lof)
        lof_frames.append(frame)
        evidence.append(item)
    bars = pd.concat([local, *lof_frames], ignore_index=True)
    bars = bars[bars["symbol"].isin(LOCAL_SYMBOLS)]
    return bars.sort_values(["trade_date", "symbol"]).reset_index(drop=True), evidence


def annualized_volatility(close: pd.Series) -> float:
    values = pd.to_numeric(close, errors="coerce").dropna().tail(VOLATILITY_WINDOW)
    if len(values) < 3 or (values <= 0).any():
        return float("nan")
    returns = np.log(values / values.shift(1)).dropna()
    if len(returns) < 2:
        return float("nan")
    mean = float(returns.mean())
    standard_deviation = float(returns.std(ddof=1))
    if not np.isfinite(standard_deviation) or standard_deviation <= 0.0:
        return float("nan")
    clipped = returns.clip(
        lower=mean - 3.0 * standard_deviation,
        upper=mean + 3.0 * standard_deviation,
    )
    return float(clipped.std(ddof=1) * math.sqrt(250.0) * 100.0)


def target_weights(
    close: pd.DataFrame,
    observation_date,
) -> tuple[dict[str, float], dict[str, Any]]:
    observation = pd.Timestamp(observation_date).normalize()
    history = close.loc[close.index <= observation]
    volatilities = {
        symbol: annualized_volatility(history[symbol])
        for symbol in LOCAL_SYMBOLS
        if symbol in history
        and history[symbol].dropna().index.max()
        == observation
    }
    raw = {
        symbol: float(PRIOR_WEIGHTS_LOCAL[symbol] / volatility**2)
        for symbol, volatility in volatilities.items()
        if np.isfinite(volatility) and volatility > 0.0
    }
    total = sum(raw.values())
    weights = {symbol: value / total for symbol, value in raw.items()} if total > 0 else {}
    diagnostics = {
        "observation_date": observation.strftime("%Y-%m-%d"),
        "volatilities": {
            symbol: float(value) if np.isfinite(value) else None
            for symbol, value in volatilities.items()
        },
        "weights": weights,
    }
    return weights, diagnostics


def build_market_state(raw_bars: pd.DataFrame) -> pd.DataFrame:
    state = raw_bars[["symbol", "trade_date", "open", "high", "low", "close", "volume"]].copy()
    state["previous_close"] = state.groupby("symbol")["close"].shift(1)
    state["paused"] = state["volume"].fillna(0).le(0)
    state["is_st"] = False
    state["buy_blocked"] = (
        state["open"].div(state["previous_close"]).ge(1.095)
        & state["low"].div(state["previous_close"]).ge(1.095)
    )
    state["sell_blocked"] = (
        state["open"].div(state["previous_close"]).le(0.905)
        & state["high"].div(state["previous_close"]).le(0.905)
    )
    state["status_quality"] = "B"
    state["st_quality"] = "B"
    state["limit_quality"] = "B"
    return state[
        [
            "symbol",
            "trade_date",
            "paused",
            "is_st",
            "buy_blocked",
            "sell_blocked",
            "status_quality",
            "st_quality",
            "limit_quality",
        ]
    ]


def actual_weights(engine: DailyBacktester, trade_date) -> dict[str, float]:
    total = engine.total_value(trade_date, field="open")
    if total <= 0.0:
        return {}
    weights = {}
    for symbol, position in engine.positions.items():
        bar = engine._bar(trade_date, symbol)
        if bar is None or not engine._valid_price(bar.get("open")):
            continue
        weights[symbol] = position.shares * float(bar["open"]) / total
    return weights


def drift_l1(actual: dict[str, float], target: dict[str, float]) -> float:
    return float(
        sum(abs(actual.get(symbol, 0.0) - target.get(symbol, 0.0)) for symbol in set(actual) | set(target))
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def run_calibration(
    bars: pd.DataFrame,
    market_state: pd.DataFrame,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    close = bars.pivot(
        index="trade_date", columns="symbol", values="adjusted_close"
    ).sort_index()
    period_bars = bars[
        bars["trade_date"].between(CALIBRATION_START, CALIBRATION_END)
    ].copy()
    engine_bars = period_bars[
        ["symbol", "trade_date", "adjusted_open", "adjusted_close", "volume"]
    ].rename(columns={"adjusted_open": "open", "adjusted_close": "close"})
    period_state = market_state[
        market_state["trade_date"].between(CALIBRATION_START, CALIBRATION_END)
    ].copy()
    calendar = pd.DatetimeIndex(sorted(period_bars["trade_date"].unique()))
    engine = DailyBacktester(
        engine_bars,
        period_state,
        asset_types={symbol: "etf" for symbol in LOCAL_SYMBOLS},
        config=BacktestConfig(
            initial_cash=INITIAL_CASH,
            lot_size=100,
            maximum_volume_ratio=1.0,
            slippage_rate=0.0,
            t_plus_one_asset_types=("etf",),
            minimum_state_quality="B",
        ),
        costs=CostModel(
            buy_commission=0.0003,
            sell_commission=0.0003,
            minimum_commission=5.0,
            etf_buy_commission=0.0003,
            etf_sell_commission=0.0003,
            etf_minimum_commission=5.0,
        ),
    )
    target_rows = []
    previous_date = None
    for trade_date in calendar:
        should_observe = previous_date is not None and (
            not engine.positions or pd.Timestamp(trade_date).weekday() == 4
        )
        if should_observe:
            weights, diagnostics = target_weights(close, previous_date)
            actual = actual_weights(engine, trade_date)
            drift = drift_l1(actual, weights)
            rebalance = bool(weights) and (
                engine.cash > CASH_TRIGGER or drift > DRIFT_THRESHOLD
            )
            target_rows.append(
                {
                    "trade_date": pd.Timestamp(trade_date),
                    "observation_date": pd.Timestamp(previous_date),
                    "rebalance": rebalance,
                    "cash_before": engine.cash,
                    "drift_l1": drift,
                    "available_count": len(weights),
                    "weights_json": json.dumps(weights, sort_keys=True),
                    "volatilities_json": json.dumps(
                        diagnostics["volatilities"], sort_keys=True
                    ),
                }
            )
            if rebalance:
                engine.rebalance_to_weights(trade_date, weights, execution="open")
        engine.mark_close(trade_date)
        previous_date = trade_date
    equity = engine.equity
    metrics = performance_metrics(equity, engine.trades, trading_days=250)
    returns = pd.to_numeric(equity["daily_return"], errors="coerce").fillna(0.0)
    downside = returns[returns < 0.0]
    sortino = (
        returns.mean() * 250.0 / (downside.std(ddof=1) * math.sqrt(250.0))
        if len(downside) > 1 and downside.std(ddof=1) > 0
        else float("nan")
    )
    metrics.update(
        {
            "scenario": "current-source-local-calibration",
            "evidence_scope": "public in-sample version calibration",
            "period_start": CALIBRATION_START.strftime("%Y-%m-%d"),
            "period_end": CALIBRATION_END.strftime("%Y-%m-%d"),
            "initial_cash": INITIAL_CASH,
            "sortino": float(sortino),
            "trade_count": len(engine.trades),
            "order_count": len(engine.orders),
            "rejected_order_count": len(engine.rejections),
            "total_fees": (
                float(pd.to_numeric(engine.fees_ledger["total_fees"]).sum())
                if not engine.fees_ledger.empty
                else 0.0
            ),
            "annual_return_absolute_difference": abs(
                metrics["annualized_return"] - PUBLIC_BACKTEST["annualized_return"]
            ),
            "max_drawdown_absolute_difference": abs(
                metrics["maximum_drawdown"] - PUBLIC_BACKTEST["maximum_drawdown"]
            ),
            "sharpe_absolute_difference": abs(
                metrics["sharpe"] - PUBLIC_BACKTEST["sharpe"]
            ),
            "parameter_fitting_used": False,
            "post_publication_data_used": False,
        }
    )
    frames = {
        "equity": equity,
        "trades": engine.trades,
        "orders": engine.orders,
        "holdings": engine.holdings,
        "targets": pd.DataFrame(target_rows),
    }
    return metrics, frames


def write_outputs(
    store: ResearchDataStore,
    lof_evidence: list[dict[str, Any]],
    metrics: dict[str, Any],
    frames: dict[str, pd.DataFrame],
) -> None:
    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    raw_dir = CANDIDATE_DIR / "raw"
    raw_dir.mkdir(exist_ok=True)
    row = {key: value for key, value in metrics.items() if key != "yearly_returns"}
    row["yearly_returns_json"] = json.dumps(
        metrics["yearly_returns"], ensure_ascii=False, sort_keys=True
    )
    pd.DataFrame([row]).to_csv(
        CANDIDATE_DIR / "version-calibration.csv",
        index=False,
        encoding="utf-8-sig",
    )
    comparison = pd.concat(
        [
            pd.DataFrame([PUBLIC_BACKTEST]),
            pd.DataFrame([row]).assign(comparable_to_local=True),
        ],
        ignore_index=True,
        sort=False,
    )
    comparison.to_csv(
        CANDIDATE_DIR / "original-vs-causal.csv",
        index=False,
        encoding="utf-8-sig",
    )
    for label, frame in frames.items():
        frame.to_csv(
            raw_dir / f"version-calibration__{label}.csv",
            index=False,
            encoding="utf-8",
        )
    data_manifests = {}
    for dataset in ("etf_daily", "etf_master"):
        path = store.manifest_path(dataset)
        data_manifests[dataset] = {"path": str(path), "sha256": sha256_file(path)}
    passed = (
        metrics["annual_return_absolute_difference"] <= 0.03
        and metrics["max_drawdown_absolute_difference"] <= 0.03
        and metrics["sharpe_absolute_difference"] <= 0.30
    )
    manifest = {
        "schema_version": 1,
        "study_id": "live-strategy-readiness",
        "candidate_id": CANDIDATE_ID,
        "run_id": "public-window-version-calibration-v1",
        "created_at": "2026-08-25",
        "period": {
            "start": CALIBRATION_START.strftime("%Y-%m-%d"),
            "end": CALIBRATION_END.strftime("%Y-%m-%d"),
        },
        "source_path": SOURCE_PATH.relative_to(ROOT).as_posix(),
        "source_sha256": sha256_file(SOURCE_PATH),
        "engine_path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
        "engine_sha256": sha256_file(Path(__file__).resolve()),
        "data_manifests": data_manifests,
        "lof_data": lof_evidence,
        "frozen_parameters": {
            "fund_pool": list(JQ_SYMBOLS),
            "prior_weights": PRIOR_WEIGHTS.tolist(),
            "volatility_window_days": VOLATILITY_WINDOW,
            "drift_l1_threshold": DRIFT_THRESHOLD,
            "cash_trigger_rmb": CASH_TRIGGER,
        },
        "post_publication_data_used": False,
        "parameter_fitting_used": False,
        "success_criteria": {
            "annual_return_absolute_difference_max": 0.03,
            "max_drawdown_absolute_difference_max": 0.03,
            "sharpe_absolute_difference_max": 0.30,
        },
        "calibration_passed": passed,
        "artifacts": {
            "calibration": "version-calibration.csv",
            "comparison": "original-vs-causal.csv",
            "raw_pattern": "raw/version-calibration__{equity,trades,orders,holdings,targets}.csv",
        },
        "limitations": [
            "six ETF histories and two LOF histories use different B-grade providers",
            "512010.XSHG is unavailable before its 2015-08-04 listing",
            "public aggregate metrics do not expose target weights or order-level comparison",
            "source did not declare costs; local calibration uses 3bp commission and RMB 5 minimum",
        ],
        "public_backtest": PUBLIC_BACKTEST,
        "local_result": _json_safe(metrics),
    }
    (CANDIDATE_DIR / "version-calibration-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run(
    data_root: Path | None = None,
    *,
    refresh_lof: bool = False,
) -> dict[str, Any]:
    store = ResearchDataStore(data_root)
    bars, lof_evidence = load_bars(store, refresh_lof=refresh_lof)
    market_state = build_market_state(bars)
    metrics, frames = run_calibration(bars, market_state)
    write_outputs(store, lof_evidence, metrics, frames)
    return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--refresh-lof", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    metrics = run(args.data_root, refresh_lof=args.refresh_lof)
    summary = {
        key: metrics[key]
        for key in (
            "annualized_return",
            "maximum_drawdown",
            "sharpe",
            "annual_return_absolute_difference",
            "max_drawdown_absolute_difference",
            "sharpe_absolute_difference",
        )
    }
    print(json.dumps(_json_safe(summary), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
