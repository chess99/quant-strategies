"""按预注册正确性修复首次运行白马股攻防的因果版本。"""

from __future__ import annotations

import argparse
import json
import math
import sys
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
    scheduled_dates,
)
from quant_research.data.store import ResearchDataStore, sha256_file  # noqa: E402
from quant_research.portal import LocalDataPortal, QlibDailyBarSource  # noqa: E402


CANDIDATE_ID = "white-horse-offense-defense"
CANDIDATE_DIR = STUDY_DIR / "results" / CANDIDATE_ID
SOURCE_PATH = (
    ROOT
    / "joinquant_archive"
    / "sources"
    / "聚宽2026年精选"
    / "18国庆节献礼：实例说明白马股攻防转换策略.py"
)
PUBLIC_START = pd.Timestamp("2013-04-11")
PUBLIC_END = pd.Timestamp("2024-10-03")
DATA_END = pd.Timestamp("2026-07-23")
POST_REPLAY_START = pd.Timestamp("2024-10-08")
INITIAL_CASH = 1_000_000.0
HOLDING_COUNT = 5
BUFFER_COUNT = 6

PUBLIC_METRICS = {
    "scenario": "published-public-backtest",
    "period_start": "2013-04-11",
    "period_end": "2024-10-03",
    "total_return": 29.663683815744,
    "annualized_return": 0.35882127132938,
    "maximum_drawdown": 0.23422478839367,
    "sharpe": 1.3764410020899,
    "sortino": 1.9665833572247,
    "turnover": 0.016793770315926,
    "source_vintage_grade": "C",
    "strict_natural_oos": False,
}


def market_temperature(
    index_close: np.ndarray | pd.Series,
    previous_state: str,
) -> tuple[str, dict[str, float]]:
    values = np.asarray(index_close, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 220:
        raise ValueError("market temperature requires 220 closes")
    values = values[-220:]
    spread = float(values.max() - values.min())
    market_height = (
        float(values[-5:].mean() - values.min()) / spread if spread > 0 else 0.5
    )
    recent_gain = float(values[-60:].max() / values.min() - 1.0)
    state = previous_state
    if market_height < 0.20:
        state = "cold"
    elif market_height > 0.90:
        state = "hot"
    elif recent_gain > 0.20:
        state = "warm"
    return state, {
        "market_height": market_height,
        "recent_60d_gain": recent_gain,
    }


def select_candidates(
    features: pd.DataFrame,
    temperature: str,
    *,
    buffer_count: int = BUFFER_COUNT,
) -> pd.DataFrame:
    frame = features.copy()
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
            & frame["pb"].lt(1.0)
            & frame["cash_profit_ratio"].gt(2.0)
            & frame["quarter_roe"].gt(1.5)
            & frame["net_profit_yoy"].gt(-15.0)
        )
        score = frame["quarter_roa"] / frame["pb"]
    elif temperature == "warm":
        mask = (
            common
            & frame["pb"].gt(0.0)
            & frame["pb"].lt(1.0)
            & frame["cash_profit_ratio"].gt(1.0)
            & frame["quarter_roe"].gt(2.0)
            & frame["net_profit_yoy"].gt(0.0)
        )
        score = frame["quarter_roa"] / frame["pb"]
    elif temperature == "hot":
        mask = (
            common
            & frame["pb"].gt(3.0)
            & frame["cash_profit_ratio"].gt(0.5)
            & frame["quarter_roe"].gt(3.0)
            & frame["net_profit_yoy"].gt(20.0)
        )
        score = frame["quarter_roa"]
    else:
        raise ValueError(f"unsupported market temperature: {temperature}")
    selected = frame.loc[mask].copy()
    selected["score"] = pd.to_numeric(score.loc[mask], errors="coerce")
    return (
        selected.dropna(subset=["score"])
        .sort_values(["score", "symbol"], ascending=[False, True])
        .head(buffer_count)
        .reset_index(drop=True)
    )


def latest_visible_features(
    fundamentals: pd.DataFrame,
    valuation: pd.DataFrame,
    state: pd.DataFrame,
    members: list[str],
    observation_date,
) -> pd.DataFrame:
    observation = pd.Timestamp(observation_date).normalize()
    member_set = set(members)
    visible = fundamentals[
        fundamentals["symbol"].isin(member_set)
        & fundamentals["notice_date"].le(observation)
    ].copy()
    if visible.empty:
        return pd.DataFrame()
    visible_versions = (
        visible.sort_values(["report_date", "notice_date"])
        .groupby(["symbol", "report_date"], as_index=False)
        .tail(1)
    )
    latest = (
        visible_versions.sort_values(["report_date", "notice_date"])
        .groupby("symbol", as_index=False)
        .tail(1)
    )
    previous = visible_versions[
        ["symbol", "report_date", "quarter_net_profit"]
    ].copy()
    previous["report_date"] = previous["report_date"] + pd.DateOffset(years=1)
    previous.rename(columns={"quarter_net_profit": "previous_quarter_net_profit"}, inplace=True)
    latest = latest.merge(previous, on=["symbol", "report_date"], how="left")
    previous_profit = pd.to_numeric(latest["previous_quarter_net_profit"], errors="coerce")
    latest["net_profit_yoy"] = (
        pd.to_numeric(latest["quarter_net_profit"], errors="coerce")
        / previous_profit.abs().replace(0.0, np.nan)
        - np.sign(previous_profit)
    ) * 100.0

    recent_valuation = valuation[
        valuation["symbol"].isin(member_set)
        & valuation["trade_date"].between(observation - pd.Timedelta(days=10), observation)
    ]
    recent_valuation = (
        recent_valuation.sort_values("trade_date")
        .groupby("symbol", as_index=False)
        .tail(1)[["symbol", "trade_date", "pb"]]
    )
    snapshot = state[
        state["symbol"].isin(member_set) & state["trade_date"].eq(observation)
    ][["symbol", "paused", "is_st"]]
    result = latest.merge(recent_valuation, on="symbol", how="inner")
    result = result.merge(snapshot, on="symbol", how="inner")
    result = result[~result["paused"].fillna(True) & ~result["is_st"].fillna(True)]
    return result.reset_index(drop=True)


def load_inputs(data_root: Path | None, qlib_dir: Path):
    store = ResearchDataStore(data_root)
    portal = LocalDataPortal(store, QlibDailyBarSource(qlib_dir))
    membership = store.read_parquet("index_membership")
    membership["start_date"] = pd.to_datetime(membership["start_date"]).dt.normalize()
    membership["end_date"] = pd.to_datetime(membership["end_date"]).dt.normalize()
    csi300 = membership[
        membership["index_symbol"].eq("SH000300")
        & membership["start_date"].le(DATA_END)
        & membership["end_date"].ge(PUBLIC_START)
    ].copy()
    symbols = sorted(csi300["symbol"].unique())
    fundamentals = store.read_symbol_partitions(
        "fundamentals_pit",
        symbols,
        columns=[
            "symbol",
            "report_date",
            "notice_date",
            "quarter_operating_cash_flow",
            "quarter_deducted_parent_net_profit",
            "quarter_net_profit",
            "quarter_roe",
            "quarter_roa",
        ],
        strict=False,
    )
    fundamentals["report_date"] = pd.to_datetime(fundamentals["report_date"]).dt.normalize()
    fundamentals["notice_date"] = pd.to_datetime(fundamentals["notice_date"]).dt.normalize()
    valuation = store.read_symbol_partitions(
        "daily_valuation",
        symbols,
        columns=["symbol", "trade_date", "pb"],
        strict=False,
    )
    valuation["trade_date"] = pd.to_datetime(valuation["trade_date"]).dt.normalize()
    state = store.read_symbol_partitions(
        "daily_market_state",
        symbols,
        columns=[
            "symbol",
            "trade_date",
            "paused",
            "is_st",
            "buy_blocked",
            "sell_blocked",
            "status_quality",
            "st_quality",
            "limit_quality",
        ],
        strict=False,
    )
    state["trade_date"] = pd.to_datetime(state["trade_date"]).dt.normalize()
    calendar = portal.calendar(PUBLIC_START, DATA_END)
    bars = portal.bars(
        symbols,
        PUBLIC_START,
        DATA_END,
        fields=("open", "close", "volume"),
        adjustment="pre",
    )
    index_bars = portal.bars(
        "SH000300",
        PUBLIC_START - pd.Timedelta(days=400),
        DATA_END,
        fields=("close",),
        adjustment="pre",
    )
    return store, csi300, fundamentals, valuation, state, calendar, bars, index_bars


def _members(membership: pd.DataFrame, observation_date) -> list[str]:
    observation = pd.Timestamp(observation_date).normalize()
    return sorted(
        membership.loc[
            membership["start_date"].le(observation)
            & membership["end_date"].ge(observation),
            "symbol",
        ].unique()
    )


def run_scenario(
    membership: pd.DataFrame,
    fundamentals: pd.DataFrame,
    valuation: pd.DataFrame,
    state: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    bars: pd.DataFrame,
    index_bars: pd.DataFrame,
    *,
    end_date: pd.Timestamp,
    commission_rate: float,
    slippage_rate: float,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame]]:
    dates = calendar[calendar <= end_date]
    period_bars = bars[bars["trade_date"].isin(dates)]
    period_state = state[state["trade_date"].isin(dates)]
    engine = DailyBacktester(
        period_bars,
        period_state,
        asset_types={symbol: "stock" for symbol in period_bars["symbol"].unique()},
        config=BacktestConfig(
            initial_cash=INITIAL_CASH,
            maximum_volume_ratio=0.01,
            slippage_rate=slippage_rate,
            minimum_state_quality="B",
        ),
        costs=CostModel(
            buy_commission=commission_rate,
            sell_commission=commission_rate,
            minimum_commission=5.0,
        ),
    )
    schedule = scheduled_dates(dates, frequency="monthly", when="first")
    index_close = index_bars.set_index("trade_date")["close"].sort_index()
    temperature = "warm"
    signal_rows = []
    previous_date = None
    for trade_date in dates:
        if trade_date in schedule and previous_date is not None:
            temperature, temperature_diag = market_temperature(
                index_close.loc[:previous_date].tail(220), temperature
            )
            members = _members(membership, previous_date)
            features = latest_visible_features(
                fundamentals,
                valuation,
                state,
                members,
                previous_date,
            )
            candidates = select_candidates(features, temperature, buffer_count=BUFFER_COUNT)
            candidate_symbols = candidates["symbol"].tolist()
            for rank, row in enumerate(candidates.itertuples(index=False), start=1):
                signal_rows.append(
                    {
                        "trade_date": trade_date,
                        "observation_date": previous_date,
                        "temperature": temperature,
                        **temperature_diag,
                        "rank": rank,
                        "buy_eligible": rank <= HOLDING_COUNT,
                        **row._asdict(),
                    }
                )
            for symbol in list(engine.positions):
                if symbol not in candidate_symbols:
                    engine.order_target_value(trade_date, symbol, 0.0, execution="open")
            position_count = len(engine.positions)
            slots = HOLDING_COUNT - position_count
            if slots > 0:
                value = engine.cash / slots
                for symbol in candidate_symbols[:HOLDING_COUNT]:
                    if symbol not in engine.positions:
                        engine.order_value(trade_date, symbol, value, execution="open")
                        if len(engine.positions) >= HOLDING_COUNT:
                            break
        engine.mark_close(trade_date)
        previous_date = trade_date
    metrics = performance_metrics(engine.equity, engine.trades, trading_days=250)
    metrics.update(
        {
            "period_start": dates[0].strftime("%Y-%m-%d"),
            "period_end": dates[-1].strftime("%Y-%m-%d"),
            "commission_rate": commission_rate,
            "slippage_rate": slippage_rate,
            "trade_count": len(engine.trades),
            "rejected_order_count": len(engine.rejections),
            "signal_count": len(pd.DataFrame(signal_rows)["trade_date"].unique())
            if signal_rows
            else 0,
        }
    )
    return metrics, {
        "equity": engine.equity,
        "orders": engine.orders,
        "trades": engine.trades,
        "holdings": engine.holdings,
        "signals": pd.DataFrame(signal_rows),
    }


def slice_metrics(
    equity: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp | None = None,
) -> dict[str, float]:
    trade_dates = pd.to_datetime(equity["trade_date"])
    in_period = trade_dates.ge(start)
    if end is not None:
        in_period &= trade_dates.le(end)
    frame = equity[in_period].copy()
    returns = pd.to_numeric(frame["daily_return"], errors="coerce").fillna(0.0)
    curve = (1.0 + returns).cumprod()
    years = len(returns) / 250.0
    drawdown = curve / curve.cummax() - 1.0
    volatility = returns.std(ddof=1) * math.sqrt(250.0)
    return {
        "total_return": float(curve.iloc[-1] - 1.0),
        "annualized_return": float(curve.iloc[-1] ** (1.0 / years) - 1.0),
        "maximum_drawdown": float(-drawdown.min()),
        "sharpe": float(returns.mean() * 250.0 / volatility) if volatility > 0 else np.nan,
    }


def _row(scenario: str, metrics: dict[str, Any], evidence_scope: str) -> dict[str, Any]:
    return {"scenario": scenario, "evidence_scope": evidence_scope, **metrics}


def run(data_root: Path | None, qlib_dir: Path) -> dict[str, Any]:
    (
        store,
        membership,
        fundamentals,
        valuation,
        state,
        calendar,
        bars,
        index_bars,
    ) = load_inputs(data_root, qlib_dir)
    original_metrics, original_frames = run_scenario(
        membership,
        fundamentals,
        valuation,
        state,
        calendar,
        bars,
        index_bars,
        end_date=PUBLIC_END,
        commission_rate=0.00012,
        slippage_rate=0.0,
    )
    causal_metrics, causal_frames = run_scenario(
        membership,
        fundamentals,
        valuation,
        state,
        calendar,
        bars,
        index_bars,
        end_date=DATA_END,
        commission_rate=0.0003,
        slippage_rate=0.001,
    )
    causal_public = slice_metrics(causal_frames["equity"], PUBLIC_START, PUBLIC_END)
    post_replay = slice_metrics(causal_frames["equity"], POST_REPLAY_START)
    comparison = pd.DataFrame(
        [
            PUBLIC_METRICS,
            _row("local-causal-original-cost", original_metrics, "matched public period"),
            _row("local-causal-baseline-cost", causal_public, "matched public period"),
        ]
    )
    oos = pd.DataFrame(
        [
            {
                "scenario": "current-snapshot-post-publication-replay",
                "source_vintage_grade": "C",
                "strict_natural_oos": False,
                "period_start": POST_REPLAY_START.strftime("%Y-%m-%d"),
                "period_end": DATA_END.strftime("%Y-%m-%d"),
                **post_replay,
            }
        ]
    )
    causal_pass = bool(
        causal_public["annualized_return"] > 0.0
        and causal_public["sharpe"] >= 0.5
        and causal_public["maximum_drawdown"] <= 0.40
    )
    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    raw = CANDIDATE_DIR / "raw"
    raw.mkdir(exist_ok=True)
    comparison.to_csv(
        CANDIDATE_DIR / "original-vs-causal.csv", index=False, encoding="utf-8-sig"
    )
    oos.to_csv(CANDIDATE_DIR / "oos.csv", index=False, encoding="utf-8-sig")
    for label, frame in causal_frames.items():
        frame.to_csv(raw / f"causal-first-run__{label}.csv", index=False)
    for label, frame in original_frames.items():
        frame.to_csv(raw / f"original-cost-matched__{label}.csv", index=False)

    # 首次因果门槛失败时按停止规则保留未运行项，而不是继续调参寻找冠军。
    robustness = pd.DataFrame(
        [
            {
                "experiment": "first-causal-gate",
                "status": "passed" if causal_pass else "failed",
                **causal_public,
            },
            {
                "experiment": "parameter-neighborhood",
                "status": "pending" if causal_pass else "not-run-stop-rule",
                "reason": "first causal gate failed" if not causal_pass else "next iteration",
            },
        ]
    )
    capacity = pd.DataFrame(
        [
            {
                "status": "pending" if causal_pass else "not-run-stop-rule",
                "reason": "requires R2 candidate" if not causal_pass else "next iteration",
            }
        ]
    )
    attribution = pd.DataFrame(
        [
            {
                "analysis_type": "benchmark-comparison",
                "name": "causal-vs-published-annualized-return",
                "value": causal_public["annualized_return"]
                - PUBLIC_METRICS["annualized_return"],
                "note": "difference includes PIT, execution and data-source effects",
            }
        ]
    )
    robustness.to_csv(CANDIDATE_DIR / "robustness.csv", index=False, encoding="utf-8-sig")
    capacity.to_csv(CANDIDATE_DIR / "capacity.csv", index=False, encoding="utf-8-sig")
    attribution.to_csv(CANDIDATE_DIR / "attribution.csv", index=False, encoding="utf-8-sig")

    status = "R1" if causal_pass else "R0"
    scorecard = {
        "schema_version": 1,
        "candidate_id": CANDIDATE_ID,
        "status": status,
        "source_vintage_grade": "C",
        "strict_natural_oos": False,
        "first_causal_run_preserved": True,
        "first_causal_gate_passed": causal_pass,
        "gates": {
            "point_in_time_membership": True,
            "point_in_time_financials": True,
            "executable_order_model": True,
            "causal_performance": causal_pass,
            "credible_oos": False,
        },
        "decision": (
            "continue fixed-parameter robustness at R1"
            if causal_pass
            else "stop current version at R0 under causal-repair stop rule"
        ),
    }
    (CANDIDATE_DIR / "live-readiness-scorecard.json").write_text(
        json.dumps(scorecard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    verdict = "通过首次因果门槛，维持 R1" if causal_pass else "首次因果门槛失败，停止当前版本"
    conclusion = f"""# 白马股攻防：首次因果重建结论

## 结论

**{verdict}**。源码版本为 C，任何发布后回放都不是严格天然 OOS。

## 事实

- 公开回测年化 {PUBLIC_METRICS['annualized_return']:.2%}、最大回撤
  {PUBLIC_METRICS['maximum_drawdown']:.2%}、Sharpe {PUBLIC_METRICS['sharpe']:.2f}。
- 同期本地点时因果版年化 {causal_public['annualized_return']:.2%}、最大回撤
  {causal_public['maximum_drawdown']:.2%}、Sharpe {causal_public['sharpe']:.2f}。
- 当前快照发布后降级回放年化 {post_replay['annualized_return']:.2%}、最大回撤
  {post_replay['maximum_drawdown']:.2%}、Sharpe {post_replay['sharpe']:.2f}。
- 修复严格限定为协议已写明的 PIT 沪深300成分、公告日财务、盘前字段和真实卖出/现金处理；
  温度阈值、财务门槛、持股数和排名缓冲均未调整。

## 推断

- 公开与本地差异不能归因于单一因素，至少混合了成分时点、财务口径、开盘字段、卖出失败和数据源。
- C 级版本证据不能支持 R4；只有首次因果门槛通过时才值得继续做稳健性和容量。

## 决定

{'保持参数冻结并进入稳健性、成本和容量研究。' if causal_pass else '按预注册停止规则，不运行参数邻域寻找补救点；失败结果永久保留。'}
"""
    (CANDIDATE_DIR / "conclusion.md").write_text(conclusion, encoding="utf-8")
    manifests = {}
    for dataset in (
        "index_membership",
        "fundamentals_pit",
        "daily_valuation",
        "daily_market_state",
    ):
        path = store.manifest_path(dataset)
        manifests[dataset] = {"path": str(path), "sha256": sha256_file(path)}
    run_manifest = {
        "schema_version": 1,
        "candidate_id": CANDIDATE_ID,
        "run_id": "first-causal-reconstruction-v1",
        "created_at": "2026-08-25",
        "source_sha256": sha256_file(SOURCE_PATH),
        "engine_sha256": sha256_file(Path(__file__).resolve()),
        "data_manifests": manifests,
        "first_causal_gate_passed": causal_pass,
    }
    (CANDIDATE_DIR / "causal-run-manifest.json").write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
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
    result = run(args.data_root, args.qlib_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
