"""校准沪深300成交量加权 RSRS；通过前不计算发布后收益。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
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
from quant_research.portal import QlibDailyBarSource  # noqa: E402


CANDIDATE_ID = "csi300-volume-rsrs"
CANDIDATE_DIR = STUDY_DIR / "results" / CANDIDATE_ID
PROTOCOL_PATH = CANDIDATE_DIR / "protocol.json"
SOURCE_PATH = (
    ROOT
    / "joinquant_archive"
    / "sources"
    / "2025年度精选策略"
    / "67.RSRS择时改进-【成交量加权-钝化-右偏】.py"
)
SIGNAL_SYMBOL = "SH000300"
CALIBRATION_SYMBOL = SIGNAL_SYMBOL
REGRESSION_DAYS = 18
STANDARDIZATION_DAYS = 200
BUY_THRESHOLD = 0.85
SELL_THRESHOLD = -0.85
WARMUP_START = pd.Timestamp("2005-05-01")
PUBLIC_START = pd.Timestamp("2014-01-02")
PUBLIC_END = pd.Timestamp("2020-05-13")
INITIAL_CASH = 10_000_000.0
PUBLIC_COMPLETED_POSITIONS = 13
PUBLIC_METRICS = {
    "annualized_return": 0.23259566768476,
    "maximum_drawdown": 0.14229769578185,
    "sharpe": 1.1611795796101,
}


@dataclass(frozen=True)
class FixedSellTaxCostModel(CostModel):
    fixed_sell_tax: float = 0.001

    def stamp_tax_rate(self, asset_type: str, side: str, trade_date) -> float:
        return self.fixed_sell_tax if side == "sell" else 0.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_protocol() -> dict[str, Any]:
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def weighted_slope_r_squared(
    low: np.ndarray,
    high: np.ndarray,
    volume: np.ndarray,
) -> tuple[float, float]:
    x = np.asarray(low, dtype=float)
    y = np.asarray(high, dtype=float)
    raw_weights = np.asarray(volume, dtype=float)
    if len(x) != len(y) or len(x) != len(raw_weights) or len(x) < 2:
        return float("nan"), float("nan")
    valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(raw_weights) & (raw_weights >= 0)
    if valid.sum() < 2 or raw_weights[valid].sum() <= 0:
        return float("nan"), float("nan")
    x = x[valid]
    y = y[valid]
    weights = raw_weights[valid] / raw_weights[valid].sum()
    x_mean = float(np.sum(weights * x))
    y_mean = float(np.sum(weights * y))
    denominator = float(np.sum(weights * np.square(x - x_mean)))
    if denominator <= 0:
        return float("nan"), float("nan")
    beta = float(np.sum(weights * (x - x_mean) * (y - y_mean)) / denominator)
    intercept = y_mean - beta * x_mean
    fitted = intercept + beta * x
    residual = float(np.sum(weights * np.square(y - fitted)))
    total = float(np.sum(weights * np.square(y - y_mean)))
    r_squared = 1.0 - residual / total if total > 0 else float("nan")
    return beta, r_squared


def build_rsrs_features(bars: pd.DataFrame) -> pd.DataFrame:
    required = {"trade_date", "high", "low", "close", "volume"}
    missing = required.difference(bars.columns)
    if missing:
        raise ValueError(f"signal bars missing columns: {sorted(missing)}")
    frame = bars[list(required)].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.normalize()
    frame = frame.sort_values("trade_date").drop_duplicates("trade_date").reset_index(drop=True)
    for column in ("high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    betas = np.full(len(frame), np.nan, dtype=float)
    r_squared = np.full(len(frame), np.nan, dtype=float)
    for end in range(REGRESSION_DAYS - 1, len(frame)):
        start = end - REGRESSION_DAYS + 1
        beta, fit = weighted_slope_r_squared(
            frame["low"].iloc[start : end + 1].to_numpy(),
            frame["high"].iloc[start : end + 1].to_numpy(),
            frame["volume"].iloc[start : end + 1].to_numpy(),
        )
        betas[end] = beta
        r_squared[end] = fit
    frame["beta"] = betas
    frame["weighted_r_squared"] = r_squared
    beta_series = pd.Series(betas)
    rolling_mean = beta_series.rolling(
        STANDARDIZATION_DAYS, min_periods=STANDARDIZATION_DAYS
    ).mean()
    rolling_std = beta_series.rolling(
        STANDARDIZATION_DAYS, min_periods=STANDARDIZATION_DAYS
    ).std(ddof=0)
    frame["zscore"] = (beta_series - rolling_mean) / rolling_std
    frame["score"] = frame["zscore"] * frame["beta"] * frame["weighted_r_squared"]
    return frame


def hysteresis_positions(scores: pd.Series) -> pd.Series:
    state = 0
    output = []
    for value in pd.to_numeric(scores, errors="coerce"):
        if np.isfinite(value):
            if value > BUY_THRESHOLD and state == 0:
                state = 1
            elif value < SELL_THRESHOLD and state == 1:
                state = 0
        output.append(state)
    return pd.Series(output, index=scores.index, dtype=int)


def build_target_map(
    features: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> tuple[dict[pd.Timestamp, int], pd.DataFrame]:
    score_by_date = features.set_index("trade_date")["score"]
    state = 0
    previous_date = None
    targets: dict[pd.Timestamp, int] = {}
    rows = []
    for trade_date in calendar:
        score = float("nan") if previous_date is None else score_by_date.get(previous_date, np.nan)
        previous_state = state
        if np.isfinite(score):
            if score > BUY_THRESHOLD and state == 0:
                state = 1
            elif score < SELL_THRESHOLD and state == 1:
                state = 0
        targets[pd.Timestamp(trade_date)] = state
        rows.append(
            {
                "trade_date": pd.Timestamp(trade_date),
                "observation_date": previous_date,
                "score": score,
                "target_position": state,
                "signal_transition": state - previous_state,
            }
        )
        previous_date = pd.Timestamp(trade_date)
    return targets, pd.DataFrame(rows)


def build_market_state(bars: pd.DataFrame) -> pd.DataFrame:
    state = bars[["symbol", "trade_date", "volume"]].copy()
    state["paused"] = state["volume"].fillna(0).le(0)
    state["is_st"] = False
    state["buy_blocked"] = False
    state["sell_blocked"] = False
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


def run_public_calibration(
    bars: pd.DataFrame,
    targets: dict[pd.Timestamp, int],
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    period = bars[bars["trade_date"].between(PUBLIC_START, PUBLIC_END)].copy()
    engine_bars = period[["symbol", "trade_date", "open", "close", "volume"]]
    engine = DailyBacktester(
        engine_bars,
        build_market_state(period),
        asset_types={CALIBRATION_SYMBOL: "fund"},
        config=BacktestConfig(
            initial_cash=INITIAL_CASH,
            lot_size=100,
            maximum_volume_ratio=0.002,
            slippage_rate=0.00246,
            t_plus_one_asset_types=("stock",),
            minimum_state_quality="B",
        ),
        costs=FixedSellTaxCostModel(
            buy_commission=0.0003,
            sell_commission=0.0003,
            minimum_commission=5.0,
        ),
    )
    calendar = pd.DatetimeIndex(sorted(period["trade_date"].unique()))
    previous_target = 0
    for trade_date in calendar:
        target = targets[pd.Timestamp(trade_date)]
        if target != previous_target:
            engine.rebalance_to_weights(
                trade_date,
                {CALIBRATION_SYMBOL: 1.0} if target else {},
                execution="open",
            )
        engine.mark_close(trade_date)
        previous_target = target
    metrics = performance_metrics(engine.equity, engine.trades, trading_days=250)
    sell_count = 0 if engine.trades.empty else int(engine.trades["side"].eq("sell").sum())
    metrics.update(
        {
            "completed_positions": sell_count,
            "trade_count": len(engine.trades),
            "order_count": len(engine.orders),
            "rejected_order_count": len(engine.rejections),
            "period_start": str(PUBLIC_START.date()),
            "period_end": str(PUBLIC_END.date()),
        }
    )
    return metrics, {
        "equity": engine.equity,
        "orders": engine.orders,
        "trades": engine.trades,
        "holdings": engine.holdings,
    }


def evaluate_calibration(local: dict[str, Any]) -> dict[str, Any]:
    gates = load_protocol()["public_calibration"]["gates"]
    gaps = {
        "annualized_return": abs(local["annualized_return"] - PUBLIC_METRICS["annualized_return"]),
        "maximum_drawdown": abs(local["maximum_drawdown"] - PUBLIC_METRICS["maximum_drawdown"]),
        "sharpe": abs(local["sharpe"] - PUBLIC_METRICS["sharpe"]),
        "completed_position_relative": abs(
            local["completed_positions"] - PUBLIC_COMPLETED_POSITIONS
        )
        / PUBLIC_COMPLETED_POSITIONS,
    }
    passed = {
        "annualized_return": gaps["annualized_return"]
        <= gates["annualized_return_absolute_gap_max"],
        "maximum_drawdown": gaps["maximum_drawdown"]
        <= gates["maximum_drawdown_absolute_gap_max"],
        "sharpe": gaps["sharpe"] <= gates["sharpe_absolute_gap_max"],
        "completed_positions": gaps["completed_position_relative"]
        <= gates["completed_position_relative_gap_max"],
    }
    pass_count = sum(passed.values())
    unlocked = (
        pass_count >= gates["minimum_pass_count"]
        and passed["annualized_return"]
        and passed["sharpe"]
    )
    return {
        "unlocked": bool(unlocked),
        "pass_count": int(pass_count),
        "gates_passed": passed,
        "gaps": gaps,
        "local": {key: local[key] for key in (*PUBLIC_METRICS, "completed_positions")},
        "public": {**PUBLIC_METRICS, "completed_positions": PUBLIC_COMPLETED_POSITIONS},
        "post_publication_performance_calculated": False,
    }


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


def write_outputs(
    provenance: dict[str, Any],
    metrics: dict[str, Any],
    decision: dict[str, Any],
    target_frame: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
) -> None:
    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    raw_dir = CANDIDATE_DIR / "raw"
    raw_dir.mkdir(exist_ok=True)
    row = {key: value for key, value in metrics.items() if key != "yearly_returns"}
    row["scenario"] = "index-source-cost-calibration"
    row["yearly_returns_json"] = json.dumps(metrics["yearly_returns"], sort_keys=True)
    pd.DataFrame([row]).to_csv(
        CANDIDATE_DIR / "version-calibration.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(
        [
            {
                "scenario": "published-public-backtest",
                **PUBLIC_METRICS,
                "completed_positions": PUBLIC_COMPLETED_POSITIONS,
            },
            row,
        ]
    ).to_csv(CANDIDATE_DIR / "original-vs-causal.csv", index=False, encoding="utf-8-sig")
    for label, frame in {**frames, "signals": target_frame}.items():
        frame.to_csv(
            raw_dir / f"version-calibration__{label}.csv", index=False, encoding="utf-8"
        )
    (CANDIDATE_DIR / "version-calibration-decision.json").write_text(
        json.dumps(_json_safe(decision), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "candidate_id": CANDIDATE_ID,
        "run_id": "public-window-index-calibration-v1",
        "created_at": "2026-08-25",
        "source_path": SOURCE_PATH.relative_to(ROOT).as_posix(),
        "source_sha256": sha256_file(SOURCE_PATH),
        "engine_path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
        "engine_sha256": sha256_file(Path(__file__).resolve()),
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "data_provenance": provenance,
        "post_publication_performance_calculated": False,
        "decision": decision,
        "limitations": load_protocol()["known_limitations"],
    }
    (CANDIDATE_DIR / "version-calibration-manifest.json").write_text(
        json.dumps(_json_safe(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run() -> dict[str, Any]:
    source = QlibDailyBarSource()
    bars = source.load(
        [SIGNAL_SYMBOL],
        WARMUP_START,
        PUBLIC_END,
        ["open", "high", "low", "close", "volume"],
        "pre",
    )
    bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.normalize()
    features = build_rsrs_features(bars)
    calendar = pd.DatetimeIndex(
        sorted(bars.loc[bars["trade_date"].between(PUBLIC_START, PUBLIC_END), "trade_date"].unique())
    )
    targets, target_frame = build_target_map(features, calendar)
    metrics, frames = run_public_calibration(bars, targets)
    decision = evaluate_calibration(metrics)
    write_outputs(source.last_provenance or {}, metrics, decision, target_frame, frames)
    return decision


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    decision = run()
    print(json.dumps(_json_safe(decision), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
