"""校准并回放基于市场 PE 偏离度的沪深300 ETF 弹性定投。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
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

from quant_research.data.store import ResearchDataStore  # noqa: E402


CANDIDATE_ID = "csi300-pe-smart-dca"
CANDIDATE_DIR = STUDY_DIR / "results" / CANDIDATE_ID
SOURCE_PATH = (
    ROOT
    / "joinquant_archive"
    / "sources"
    / "2025年度精选策略"
    / "53.基于大盘PE标准差偏离度的聪明基金定投策略.py"
)
SYMBOL = "SH510300"
CALIBRATION_START = pd.Timestamp("2012-06-01")
CALIBRATION_END = pd.Timestamp("2019-12-26")
OOS_START = pd.Timestamp("2020-01-02")
OOS_END = pd.Timestamp("2026-07-24")
INITIAL_CASH = 100_000.0
MONTHLY_FLOW = 5_000.0
VALUATION_WINDOW = 2_500
NORMAL_WEEKS = 50.0

PUBLIC_METRICS = {
    "annualized_return": 0.1325133659203,
    "maximum_drawdown": 0.2100312627198,
    "sharpe": 0.62969797858226,
    "action_count": 73,
}
CALIBRATION_TOLERANCES = {
    "annualized_return": 0.05,
    "maximum_drawdown": 0.05,
    "sharpe": 0.20,
    "action_count_relative": 0.25,
}


@dataclass(frozen=True)
class CostAssumptions:
    commission_rate: float
    minimum_commission: float
    sell_tax_rate: float = 0.0
    slippage_rate: float = 0.0
    fixed_slippage_yuan: float = 0.0
    adv_participation: float = 1.0


SOURCE_COST = CostAssumptions(
    commission_rate=0.0003,
    minimum_commission=5.0,
    sell_tax_rate=0.001,
    fixed_slippage_yuan=0.02,
    adv_participation=1.0,
)
REALISTIC_COST = CostAssumptions(
    commission_rate=0.0003,
    minimum_commission=5.0,
    slippage_rate=0.0002,
    adv_participation=0.01,
)
DOUBLE_COST = CostAssumptions(
    commission_rate=0.0006,
    minimum_commission=10.0,
    slippage_rate=0.0004,
    adv_participation=0.01,
)


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


def _normalize_market_pe(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.shape[1] < 4:
        raise ValueError("index PE response must contain at least four columns")
    lowered = {str(column).lower(): column for column in raw.columns}
    date_column = lowered.get("date", raw.columns[0])
    # stock_index_pe_lg 的第四列是 addLyrPe，即指数静态总市盈率；不使用等权或中位数列。
    pe_column = lowered.get("addlyrpe", raw.columns[3])
    frame = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(raw[date_column], errors="raise"),
            "pe_average": pd.to_numeric(raw[pe_column], errors="coerce"),
        }
    )
    frame["trade_date"] = frame["trade_date"].dt.normalize()
    frame = frame.dropna().sort_values("trade_date")
    frame = frame[frame["pe_average"].gt(0)]
    if frame.duplicated("trade_date").any():
        raise ValueError("market PE response contains duplicate dates")
    return frame.reset_index(drop=True)


def load_market_pe(
    store: ResearchDataStore,
    *,
    through: pd.Timestamp,
    refresh: bool = False,
) -> tuple[pd.Series, dict[str, Any]]:
    cutoff = pd.Timestamp(through).normalize()
    target = (
        store.raw_dir
        / "legulegu"
        / "index_pe"
        / f"csi300_static_total__through_{cutoff.strftime('%Y-%m-%d')}.csv"
    )
    if refresh or not target.is_file():
        import akshare as ak

        downloaded = _normalize_market_pe(ak.stock_index_pe_lg(symbol="沪深300"))
        downloaded = downloaded[downloaded["trade_date"].le(cutoff)]
        if downloaded.empty or downloaded["trade_date"].max() < cutoff - pd.Timedelta(days=10):
            raise ValueError("market PE data does not reach the requested cutoff")
        _atomic_csv(downloaded, target)
    frame = pd.read_csv(target, parse_dates=["trade_date"])
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.normalize()
    frame = frame[frame["trade_date"].le(cutoff)].sort_values("trade_date")
    if len(frame) < VALUATION_WINDOW:
        raise ValueError("market PE history is shorter than the frozen 2500 observations")
    series = frame.set_index("trade_date")["pe_average"].astype(float)
    evidence = {
        "provider": "Legulegu via AkShare stock_index_pe_lg(symbol='沪深300'), addLyrPe",
        "path": str(target),
        "sha256": sha256_file(target),
        "first_date": series.index.min().strftime("%Y-%m-%d"),
        "last_date": series.index.max().strftime("%Y-%m-%d"),
        "row_count": len(series),
    }
    return series, evidence


def load_etf_bars(store: ResearchDataStore, through: pd.Timestamp) -> pd.DataFrame:
    columns = [
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
    ]
    bars = store.read_symbol_partitions(
        "etf_daily", [SYMBOL], columns=columns, strict=True
    )
    bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.normalize()
    bars = bars[bars["trade_date"].between(CALIBRATION_START, through)].copy()
    bars = bars.sort_values("trade_date").drop_duplicates("trade_date")
    required = ["adjusted_open", "adjusted_close", "volume", "amount"]
    if bars[required].isna().any().any():
        raise ValueError("SH510300 bars contain missing execution fields")
    return bars.reset_index(drop=True)


def valuation_state(
    pe: pd.Series,
    observation_date,
    *,
    window: int = VALUATION_WINDOW,
) -> dict[str, float]:
    observation = pd.Timestamp(observation_date).normalize()
    visible = pd.to_numeric(pe.loc[pe.index <= observation], errors="coerce").dropna()
    visible = visible[visible.gt(0)].tail(window)
    if len(visible) < window:
        raise ValueError("insufficient point-in-time PE observations")
    transformed = np.log10(visible.astype(float))
    center = float(transformed.median())
    standard_deviation = float(transformed.std(ddof=1))
    return {
        "observation_date": observation,
        "now": float(transformed.iloc[-1]),
        "center": center,
        "standard_deviation": standard_deviation,
        "upper": center + 0.05 * standard_deviation,
        "lower": center - 0.25 * standard_deviation,
    }


def target_weeks(
    now: float,
    upper: float,
    lower: float,
    *,
    normal_weeks: float = NORMAL_WEEKS,
) -> tuple[float, str]:
    if now > upper:
        weeks = normal_weeks / (((upper - now) / upper) * 100.0)
        return float(weeks), "sell"
    if now < lower:
        weeks = normal_weeks * (1.0 - ((lower - now) / lower) * 5.0)
        return float(max(1.0, weeks)), "buy"
    return float(normal_weeks), "normal"


def penultimate_weekly_dates(trading_dates) -> set[pd.Timestamp]:
    dates = pd.DatetimeIndex(pd.to_datetime(list(trading_dates))).normalize()
    groups = pd.Series(dates, index=dates.to_period("W-FRI")).groupby(level=0)
    selected = []
    for _, values in groups:
        week = pd.DatetimeIndex(values.to_numpy()).sort_values()
        if len(week) >= 2:
            selected.append(pd.Timestamp(week[-2]))
    return set(selected)


def _first_weekly_dates(trading_dates) -> set[pd.Timestamp]:
    dates = pd.DatetimeIndex(pd.to_datetime(list(trading_dates))).normalize()
    values = pd.Series(dates, index=dates.to_period("W-FRI")).groupby(level=0).first()
    return set(pd.DatetimeIndex(values.to_numpy()).normalize())


def _sixth_monthly_dates(trading_dates) -> set[pd.Timestamp]:
    dates = pd.DatetimeIndex(pd.to_datetime(list(trading_dates))).normalize()
    result = set()
    for _, values in pd.Series(dates, index=dates.to_period("M")).groupby(level=0):
        month = pd.DatetimeIndex(values.to_numpy()).sort_values()
        if len(month) >= 6:
            result.add(pd.Timestamp(month[5]))
    return result


def cash_flow_adjusted_returns(
    equity: pd.DataFrame,
    *,
    initial_cash: float = INITIAL_CASH,
) -> pd.Series:
    previous = float(initial_cash)
    returns = []
    for row in equity.itertuples(index=False):
        flow = float(row.external_flow)
        total = float(row.total_value)
        returns.append((total - flow) / previous - 1.0 if previous > 0 else np.nan)
        previous = total
    return pd.Series(returns, index=equity.index, dtype=float)


def _performance_metrics(
    equity: pd.DataFrame,
    orders: pd.DataFrame,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, Any]:
    scored = equity[equity["trade_date"].between(start, end)].copy()
    if scored.empty:
        raise ValueError("scored equity period is empty")
    returns = pd.to_numeric(scored["daily_return"], errors="raise").fillna(0.0)
    curve = (1.0 + returns).cumprod()
    years = max(len(returns) / 250.0, 1.0 / 250.0)
    annualized = float(curve.iloc[-1] ** (1.0 / years) - 1.0)
    volatility = float(returns.std(ddof=1) * math.sqrt(250.0))
    sharpe = float(returns.mean() * 250.0 / volatility) if volatility > 0 else np.nan
    drawdown = curve / curve.cummax() - 1.0
    underwater = drawdown.lt(-1e-12)
    groups = underwater.ne(underwater.shift()).cumsum()
    longest = int(underwater.groupby(groups).sum().max())
    relevant_orders = orders[orders["trade_date"].between(start, end)] if not orders.empty else orders
    return {
        "period_start": scored["trade_date"].min().strftime("%Y-%m-%d"),
        "period_end": scored["trade_date"].max().strftime("%Y-%m-%d"),
        "trading_days": len(scored),
        "total_return": float(curve.iloc[-1] - 1.0),
        "annualized_return": annualized,
        "maximum_drawdown": float(-drawdown.min()),
        "sharpe": sharpe,
        "annualized_volatility": volatility,
        "longest_underwater_trading_days": longest,
        "average_exposure": float(scored["exposure"].mean()),
        "ending_total_value": float(scored["total_value"].iloc[-1]),
        "net_contributions": float(scored["external_flow"].sum()),
        "action_count": int(len(relevant_orders)),
        "filled_action_count": int(relevant_orders["filled_shares"].gt(0).sum()) if not relevant_orders.empty else 0,
        "total_fees": float(relevant_orders["fees"].sum()) if not relevant_orders.empty else 0.0,
        "unfilled_value": float(relevant_orders["unfilled_value"].sum()) if not relevant_orders.empty else 0.0,
    }


def _trade_price(raw_open: float, side: str, costs: CostAssumptions) -> float:
    direction = 1.0 if side == "buy" else -1.0
    return float(
        raw_open * (1.0 + direction * costs.slippage_rate)
        + direction * costs.fixed_slippage_yuan
    )


def simulate(
    bars: pd.DataFrame,
    pe: pd.Series,
    *,
    scenario: str,
    rule: str,
    costs: CostAssumptions,
    initial_cash: float = INITIAL_CASH,
    monthly_flow: float = MONTHLY_FLOW,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    data = bars.set_index("trade_date").sort_index()
    calendar = pd.DatetimeIndex(data.index).sort_values().unique()
    rebalance_dates = penultimate_weekly_dates(calendar)
    first_week_dates = _first_weekly_dates(calendar)
    flow_dates = _sixth_monthly_dates(calendar)
    previous_date = None
    thresholds = None
    cash = float(initial_cash)
    shares = 0
    net_contributions = float(initial_cash)
    equity_rows = []
    order_rows = []
    signal_rows = []

    for trade_date in calendar:
        row = data.loc[trade_date]
        external_flow = 0.0
        if trade_date in flow_dates:
            cash += monthly_flow
            external_flow = float(monthly_flow)
            net_contributions += monthly_flow

        if trade_date in first_week_dates and previous_date is not None:
            try:
                thresholds = valuation_state(pe, previous_date)
            except ValueError:
                thresholds = None

        if trade_date in rebalance_dates and previous_date is not None and thresholds is not None:
            current = valuation_state(pe, previous_date)
            if rule == "valuation":
                weeks, mode = target_weeks(
                    current["now"], thresholds["upper"], thresholds["lower"]
                )
            elif rule == "fixed-50-week-dca":
                weeks, mode = NORMAL_WEEKS, "fixed"
            elif rule == "invest-all-cash-weekly":
                weeks, mode = 1.0, "invest-all"
            else:
                raise ValueError(f"unknown rule: {rule}")

            open_price = float(row["adjusted_open"])
            position_value = shares * open_price
            if weeks < 0:
                target_value = max(0.0, position_value + position_value / weeks)
            else:
                target_value = position_value + cash / weeks
            target_shares = max(0, int(target_value / open_price) // 100 * 100)
            requested = abs(target_shares - shares)
            side = "buy" if target_shares > shares else "sell"
            filled = 0
            fees = 0.0
            gross = 0.0
            unfilled_value = 0.0
            if requested > 0:
                capacity = int(float(row["volume"]) * costs.adv_participation)
                capacity = max(0, capacity // 100 * 100)
                filled = min(requested, capacity)
                if side == "sell" and requested == shares:
                    filled = min(requested, capacity)
                else:
                    filled = filled // 100 * 100
                price = _trade_price(open_price, side, costs)
                if side == "buy":
                    while filled > 0:
                        gross = filled * price
                        commission = max(costs.minimum_commission, gross * costs.commission_rate)
                        fees = commission
                        if gross + fees <= cash + 1e-9:
                            break
                        filled -= 100
                    if filled > 0:
                        gross = filled * price
                        fees = max(costs.minimum_commission, gross * costs.commission_rate)
                        cash -= gross + fees
                        shares += filled
                elif filled > 0:
                    gross = filled * price
                    fees = max(costs.minimum_commission, gross * costs.commission_rate)
                    fees += gross * costs.sell_tax_rate
                    cash += gross - fees
                    shares -= filled
                unfilled_value = max(0, requested - filled) * open_price
                order_rows.append(
                    {
                        "scenario": scenario,
                        "trade_date": trade_date,
                        "observation_date": previous_date,
                        "side": side,
                        "mode": mode,
                        "requested_shares": requested,
                        "filled_shares": filled,
                        "unfilled_shares": requested - filled,
                        "price": price,
                        "gross_value": gross,
                        "fees": fees,
                        "unfilled_value": unfilled_value,
                    }
                )
            signal_rows.append(
                {
                    "scenario": scenario,
                    "trade_date": trade_date,
                    "observation_date": previous_date,
                    "threshold_observation_date": thresholds["observation_date"],
                    "now": current["now"],
                    "upper": thresholds["upper"],
                    "lower": thresholds["lower"],
                    "target_weeks": weeks,
                    "mode": mode,
                    "target_shares": target_shares,
                    "actual_shares_after": shares,
                }
            )

        total = cash + shares * float(row["adjusted_close"])
        previous_total = (
            float(equity_rows[-1]["total_value"]) if equity_rows else float(initial_cash)
        )
        daily_return = (total - external_flow) / previous_total - 1.0
        equity_rows.append(
            {
                "scenario": scenario,
                "trade_date": trade_date,
                "cash": cash,
                "shares": shares,
                "positions_value": shares * float(row["adjusted_close"]),
                "total_value": total,
                "external_flow": external_flow,
                "net_contributions": net_contributions,
                "daily_return": daily_return,
                "exposure": shares * float(row["adjusted_close"]) / total if total > 0 else np.nan,
            }
        )
        previous_date = pd.Timestamp(trade_date)

    equity = pd.DataFrame(equity_rows)
    orders = pd.DataFrame(order_rows)
    signals = pd.DataFrame(signal_rows)
    return equity, orders, signals


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


def calibration_decision(metrics: dict[str, Any]) -> dict[str, Any]:
    differences = {
        "annualized_return": abs(metrics["annualized_return"] - PUBLIC_METRICS["annualized_return"]),
        "maximum_drawdown": abs(metrics["maximum_drawdown"] - PUBLIC_METRICS["maximum_drawdown"]),
        "sharpe": abs(metrics["sharpe"] - PUBLIC_METRICS["sharpe"]),
        "action_count_relative": abs(metrics["action_count"] - PUBLIC_METRICS["action_count"]) / PUBLIC_METRICS["action_count"],
    }
    checks = {
        "annualized_return": differences["annualized_return"] <= CALIBRATION_TOLERANCES["annualized_return"],
        "maximum_drawdown": differences["maximum_drawdown"] <= CALIBRATION_TOLERANCES["maximum_drawdown"],
        "sharpe": differences["sharpe"] <= CALIBRATION_TOLERANCES["sharpe"],
        "action_count": differences["action_count_relative"] <= CALIBRATION_TOLERANCES["action_count_relative"],
    }
    return {
        "calibration_passed": bool(all(checks.values())),
        "source_vintage_after": "B" if all(checks.values()) else "C",
        "checks": checks,
        "differences": differences,
        "post_publication_performance_calculated": False,
        "parameter_selection_used": False,
    }


def _write_calibration(
    store: ResearchDataStore,
    pe_evidence: dict[str, Any],
    metrics: dict[str, Any],
    equity: pd.DataFrame,
    orders: pd.DataFrame,
    signals: pd.DataFrame,
) -> dict[str, Any]:
    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    raw = CANDIDATE_DIR / "raw"
    raw.mkdir(exist_ok=True)
    decision = calibration_decision(metrics)
    row = {"scenario": "local-source-cost-calibration", **metrics}
    pd.DataFrame([row]).to_csv(
        CANDIDATE_DIR / "version-calibration.csv", index=False, encoding="utf-8-sig"
    )
    comparison = pd.DataFrame(
        [
            {"scenario": "published-joinquant", **PUBLIC_METRICS},
            row,
        ]
    )
    comparison.to_csv(
        CANDIDATE_DIR / "original-vs-causal.csv", index=False, encoding="utf-8-sig"
    )
    equity.to_csv(raw / "version-calibration__equity.csv", index=False, encoding="utf-8")
    orders.to_csv(raw / "version-calibration__orders.csv", index=False, encoding="utf-8")
    signals.to_csv(raw / "version-calibration__signals.csv", index=False, encoding="utf-8")
    (CANDIDATE_DIR / "version-calibration-decision.json").write_text(
        json.dumps(_json_safe(decision), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    etf_manifest = store.manifest_path("etf_daily")
    manifest = {
        "schema_version": 1,
        "study_id": "live-strategy-readiness",
        "candidate_id": CANDIDATE_ID,
        "run_id": "public-window-version-calibration-v1",
        "created_at": "2026-08-25",
        "period": {"start": "2012-06-01", "end": "2019-12-26"},
        "source_path": SOURCE_PATH.relative_to(ROOT).as_posix(),
        "source_sha256": sha256_file(SOURCE_PATH),
        "engine_path": Path(__file__).resolve().relative_to(ROOT).as_posix(),
        "engine_sha256": sha256_file(Path(__file__).resolve()),
        "data": {
            "etf_daily_manifest": str(etf_manifest),
            "etf_daily_manifest_sha256": sha256_file(etf_manifest),
            "valuation": pe_evidence,
        },
        "post_publication_data_used": False,
        "parameter_fitting_used": False,
        "public_metrics": PUBLIC_METRICS,
        "local_metrics": metrics,
        "decision": decision,
    }
    (CANDIDATE_DIR / "version-calibration-manifest.json").write_text(
        json.dumps(_json_safe(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return decision


def run_calibration(
    data_root: Path | None = None,
    *,
    refresh_pe: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    store = ResearchDataStore(data_root)
    pe, pe_evidence = load_market_pe(store, through=CALIBRATION_END, refresh=refresh_pe)
    bars = load_etf_bars(store, CALIBRATION_END)
    equity, orders, signals = simulate(
        bars,
        pe,
        scenario="source-cost-calibration",
        rule="valuation",
        costs=SOURCE_COST,
    )
    metrics = _performance_metrics(
        equity, orders, start=CALIBRATION_START, end=CALIBRATION_END
    )
    decision = _write_calibration(
        store, pe_evidence, metrics, equity, orders, signals
    )
    return metrics, decision


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--stage", choices=("calibration",), default="calibration")
    parser.add_argument("--refresh-pe", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    metrics, decision = run_calibration(args.data_root, refresh_pe=args.refresh_pe)
    print(
        json.dumps(
            _json_safe({"metrics": metrics, "decision": decision}),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
