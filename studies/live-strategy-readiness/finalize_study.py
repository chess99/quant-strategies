"""生成统一结果、平台审计、组合判定和执行顺序完成性审计。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STUDY_DIR = Path(__file__).resolve().parent
ROOT = STUDY_DIR.parents[1]
RESULTS = STUDY_DIR / "results"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(candidate: str, name: str) -> pd.DataFrame:
    return pd.read_csv(RESULTS / candidate / name)


def match(frame: pd.DataFrame, **conditions) -> pd.Series | None:
    selected = frame
    for column, value in conditions.items():
        selected = selected[selected[column].astype(str).eq(str(value))]
    return None if selected.empty else selected.iloc[0]


def number(row: pd.Series | None, field: str) -> float | None:
    if row is None or field not in row or pd.isna(row[field]):
        return None
    return float(row[field])


def minimum_capacity_exposure(candidate: str, capitals: tuple[int, ...]) -> float | None:
    frame = read_csv(candidate, "capacity.csv")
    if "average_exposure" not in frame:
        return None
    capital = pd.to_numeric(frame["capital_rmb"], errors="coerce")
    exposure = pd.to_numeric(frame["average_exposure"], errors="coerce")
    values = exposure[capital.isin(capitals)].dropna()
    return float(values.min()) if not values.empty else None


def capacity_exposure(
    candidate: str,
    capital_rmb: int,
    *,
    adv_participation: float = 0.005,
) -> float | None:
    frame = read_csv(candidate, "capacity.csv")
    if "average_exposure" not in frame or "adv_participation" not in frame:
        return None
    capital = pd.to_numeric(frame["capital_rmb"], errors="coerce")
    adv = pd.to_numeric(frame["adv_participation"], errors="coerce")
    exposure = pd.to_numeric(frame["average_exposure"], errors="coerce")
    selected = exposure[capital.eq(capital_rmb) & adv.eq(adv_participation)].dropna()
    return float(selected.iloc[0]) if not selected.empty else None


def source_hash(candidate: str) -> str | None:
    scorecard_path = RESULTS / candidate / "live-readiness-scorecard.json"
    if scorecard_path.exists():
        value = read_json(scorecard_path).get("source_sha256")
        if value:
            return value
    protocol_path = RESULTS / candidate / "protocol.json"
    if protocol_path.exists():
        return read_json(protocol_path).get("frozen_source", {}).get("sha256")
    return None


GENERIC_CANDIDATE_NOTES = {
    "csi300-drawdown-bond-switch": {
        "risk": "CSI300 equity beta with drawdown-triggered bond switch",
        "gap": "weak B-grade post-publication return; no candidate platform export",
        "action": "stop historical tuning; retain as a low-turnover control",
    },
    "csi300-ma10-60-cash": {
        "risk": "CSI300 trend beta with large cash allocation",
        "gap": "B-grade post-publication Sharpe is near zero; no platform export",
        "action": "stop this disclosed parameter version",
    },
    "csi300-pe-smart-dca": {
        "risk": "CSI300 valuation timing and contribution timing",
        "gap": "public-window valuation proxy failed calibration",
        "action": "do not open the reserved window or replace the valuation series",
    },
    "csi300-volume-rsrs": {
        "risk": "CSI300 market beta with volume-conditioned RSRS timing",
        "gap": "B-grade post-publication Sharpe 0.24 and 38.48% drawdown",
        "action": "stop; do not tune the disclosed optimum on failed OOS",
    },
    "dynamic-volume-etf-rotation": {
        "risk": "daily ETF trend and volume-switch timing",
        "gap": "causal daily reconstruction failed public-window calibration",
        "action": "stop before opening the post-publication window",
    },
    "ebit-ev-value": {
        "risk": "A-share value and financial statement availability",
        "gap": "historical source universe and public CAGR were not reproduced",
        "action": "stop before opening the post-publication window",
    },
    "gac-zscore-mean-reversion": {
        "risk": "single-stock concentration and mean-reversion timing",
        "gap": "post-publication return and Sharpe are negative; drawdown 58.37%",
        "action": "stop; do not change stock or thresholds on observed OOS",
    },
    "stock-bond-volatility-balance": {
        "risk": "CSI300 and bond inverse-volatility allocation",
        "gap": "low post-publication return and no candidate platform export",
        "action": "retain as a defensive control; do not optimize on OOS",
    },
}


def preferred_oos_row(candidate: str) -> pd.Series | None:
    path = RESULTS / candidate / "oos.csv"
    if not path.is_file():
        return None
    frame = pd.read_csv(path)
    if "annualized_return" not in frame:
        return None
    numeric = pd.to_numeric(frame["annualized_return"], errors="coerce")
    frame = frame[numeric.notna()].copy()
    if frame.empty:
        return None
    if "scenario" in frame:
        priorities = (
            "causal-baseline-cost",
            "rsrs-baseline-cost",
            "zscore-baseline-cost",
            "parent-causal-baseline-cost",
        )
        for scenario in priorities:
            selected = frame[frame["scenario"].eq(scenario)]
            if not selected.empty:
                return selected.iloc[0]
    return frame.iloc[0]


def preferred_double_cost_row(candidate: str) -> pd.Series | None:
    path = RESULTS / candidate / "oos.csv"
    if path.is_file():
        frame = pd.read_csv(path)
        if "scenario" in frame:
            selected = frame[
                frame["scenario"].astype(str).str.contains("double", case=False)
            ]
            if not selected.empty:
                return selected.iloc[0]
    robustness_path = RESULTS / candidate / "robustness.csv"
    if robustness_path.is_file():
        frame = pd.read_csv(robustness_path)
        if {"experiment", "variant"}.issubset(frame.columns):
            selected = frame[
                frame["experiment"].eq("cost-stress")
                & frame["variant"].astype(str).str.contains("double", case=False)
            ]
            if not selected.empty:
                return selected.iloc[0]
    return None


def scalar_diagnostic(value: Any, key: str) -> float | None:
    if isinstance(value, dict):
        value = value.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def longest_underwater_from_equity(path: Path) -> int:
    frame = pd.read_csv(path)
    values = pd.to_numeric(frame["total_value"], errors="raise")
    underwater = values.div(values.cummax()).sub(1.0).lt(0.0)
    groups = underwater.ne(underwater.shift()).cumsum()
    return int(underwater.groupby(groups).sum().max())


def generic_candidate_row(candidate: str) -> dict[str, Any]:
    score = read_json(RESULTS / candidate / "live-readiness-scorecard.json")
    notes = GENERIC_CANDIDATE_NOTES[candidate]
    oos = preferred_oos_row(candidate)
    double = preferred_double_cost_row(candidate)
    post = score.get("post_publication_oos", {})
    return {
        "candidate_id": candidate,
        "status": score["status"],
        "source_vintage_grade": score.get("source_vintage_grade"),
        "source_sha256": score.get("source_sha256"),
        "original_source_sha256": score.get("source_sha256"),
        "causal_source_sha256": score.get("source_sha256"),
        "strict_natural_oos": bool(score.get("strict_natural_oos", False)),
        "oos_evidence_grade": (
            f"{score.get('source_vintage_grade', 'unknown')}-downgraded"
            if oos is not None
            else "not-opened-calibration-failed"
        ),
        "oos_start": post.get("period_start")
        or (oos.get("period_start") if oos is not None else None),
        "oos_end": post.get("period_end")
        or (oos.get("period_end") if oos is not None else None),
        "oos_cagr": post.get("annualized_return")
        if "annualized_return" in post
        else number(oos, "annualized_return"),
        "oos_max_drawdown": post.get("maximum_drawdown")
        if "maximum_drawdown" in post
        else number(oos, "maximum_drawdown"),
        "oos_sharpe": post.get("sharpe")
        if "sharpe" in post
        else number(oos, "sharpe"),
        "oos_longest_underwater_days": number(
            oos, "longest_underwater_trading_days"
        ),
        "double_cost_cagr": number(double, "annualized_return"),
        "double_cost_max_drawdown": number(double, "maximum_drawdown"),
        "double_cost_sharpe": number(double, "sharpe"),
        "primary_capacity_min_exposure": minimum_capacity_exposure(
            candidate, (200_000, 1_000_000, 2_000_000)
        ),
        "capacity_10m_0_5pct_exposure": capacity_exposure(candidate, 10_000_000),
        "pbo": scalar_diagnostic(score.get("pbo"), "pbo"),
        "deflated_sharpe_probability": scalar_diagnostic(
            score.get("deflated_sharpe"), "deflated_sharpe_probability"
        ),
        "trial_count": score.get("experiment_count"),
        "core_risk_exposure": notes["risk"],
        "correlation_status": "not-eligible-for-portfolio",
        "key_data_gap": notes["gap"],
        "next_action": notes["action"],
        "stop_reason": score.get("stop_reason") or score.get("decision"),
        "platform_status": "not-run-stopped-before-R2",
        "production_data_status": "not-required-below-R2",
    }


def build_unified_results() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    low = read_json(RESULTS / "low-risk-medium-return/protocol.json")
    rows.append(
        {
            "candidate_id": "low-risk-medium-return",
            "status": "R0",
            "source_vintage_grade": "C",
            "source_sha256": low["frozen_source"]["sha256"],
            "original_source_sha256": low["frozen_source"]["sha256"],
            "strict_natural_oos": False,
            "oos_evidence_grade": "C-data-blocked",
            "published_cagr": low["public_backtest"]["annual_return"],
            "published_max_drawdown": low["public_backtest"]["max_drawdown"],
            "published_sharpe": low["public_backtest"]["sharpe"],
            "core_risk_exposure": "small-cap + urban-investment bond + gold + S&P500",
            "key_data_gap": "399317.XSHE PIT membership and frozen 2024 source vintage",
            "next_action": "obtain PIT membership or preregister a new universe candidate",
            "stop_reason": "causal reconstruction is data-blocked; no alpha substitution allowed",
        }
    )

    epo_id = "multi-asset-etf-momentum-epo"
    epo_score = read_json(RESULTS / epo_id / "live-readiness-scorecard.json")
    epo_rob = read_csv(epo_id, "robustness.csv")
    epo_oos = read_csv(epo_id, "oos.csv")
    epo_attr = read_csv(epo_id, "attribution.csv")
    epo_full = match(epo_rob, experiment="frozen-full-causal", variant="baseline")
    epo_post = match(epo_oos, scenario="causal-baseline-cost")
    epo_double = match(epo_rob, experiment="cost-stress", variant="double")
    epo_contrib = epo_attr[epo_attr["analysis_type"].eq("asset-contribution")]
    epo_top = epo_contrib.iloc[0]
    epo_beta = epo_attr[epo_attr["analysis_type"].eq("factor-beta")]
    rows.append(
        {
            "candidate_id": epo_id,
            "status": epo_score["status"],
            "source_vintage_grade": epo_score["source_vintage_grade"],
            "source_sha256": source_hash(epo_id),
            "original_source_sha256": source_hash(epo_id),
            "causal_source_sha256": source_hash(epo_id),
            "strict_natural_oos": False,
            "oos_evidence_grade": "B-downgraded",
            "oos_start": epo_post["period_start"],
            "oos_end": epo_post["period_end"],
            "full_cagr": number(epo_full, "annualized_return"),
            "full_max_drawdown": number(epo_full, "maximum_drawdown"),
            "full_sharpe": number(epo_full, "sharpe"),
            "oos_cagr": number(epo_post, "annualized_return"),
            "oos_max_drawdown": number(epo_post, "maximum_drawdown"),
            "oos_sharpe": number(epo_post, "sharpe"),
            "oos_longest_underwater_days": number(
                epo_post, "longest_underwater_trading_days"
            ),
            "double_cost_cagr": number(epo_double, "annualized_return"),
            "double_cost_max_drawdown": number(epo_double, "maximum_drawdown"),
            "double_cost_sharpe": number(epo_double, "sharpe"),
            "primary_capacity_min_exposure": minimum_capacity_exposure(
                epo_id, (200_000, 1_000_000, 2_000_000)
            ),
            "capacity_10m_0_5pct_exposure": minimum_capacity_exposure(
                epo_id, (10_000_000,)
            ),
            "capacity_200k_exposure": capacity_exposure(epo_id, 200_000),
            "capacity_1m_exposure": capacity_exposure(epo_id, 1_000_000),
            "capacity_2m_exposure": capacity_exposure(epo_id, 2_000_000),
            "capacity_10m_exposure": capacity_exposure(epo_id, 10_000_000),
            "pbo": epo_score["pbo"]["pbo"],
            "deflated_sharpe_probability": epo_score["deflated_sharpe"][
                "deflated_sharpe_probability"
            ],
            "trial_count": epo_score["experiment_count"],
            "top1_contribution_share": epo_top["absolute_share"],
            "top3_contribution_share": float(epo_contrib.head(3)["absolute_share"].sum()),
            "core_risk_exposure": "dynamic ETF concentration; "
            + "; ".join(
                f"{row['name']}={float(row['value']):.3f}"
                for _, row in epo_beta.iterrows()
                if row["name"] != "intercept-annualized"
            ),
            "correlation_status": "not-computed-no-R2-R3-set",
            "key_data_gap": "platform orders; QDII premium/discount and cross-market production feed",
            "next_action": "no more historical tuning; platform/data work only if research resumes",
            "stop_reason": "only 51.9% of the 27-neighbor grid reached Sharpe 0.5",
        }
    )

    white_id = "white-horse-offense-defense"
    white_score = read_json(RESULTS / white_id / "live-readiness-scorecard.json")
    white_rob = read_csv(white_id, "robustness.csv")
    white_oos = read_csv(white_id, "oos.csv").iloc[0]
    white_attr = read_csv(white_id, "attribution.csv")
    white_full = match(white_rob, experiment="frozen-full-causal", variant="baseline")
    white_double = match(white_rob, experiment="cost-stress", variant="double")
    white_contrib = white_attr[
        white_attr["analysis_type"].eq("stock-contribution")
    ]
    white_top = white_contrib.iloc[0]
    white_beta = white_attr[white_attr["analysis_type"].eq("factor-beta")]
    rows.append(
        {
            "candidate_id": white_id,
            "status": white_score["status"],
            "source_vintage_grade": white_score["source_vintage_grade"],
            "source_sha256": source_hash(white_id),
            "original_source_sha256": source_hash(white_id),
            "causal_source_sha256": read_json(
                RESULTS / white_id / "deep-run-manifest.json"
            )["engine_sha256"],
            "strict_natural_oos": False,
            "oos_evidence_grade": "C-downgraded",
            "oos_start": white_oos["period_start"],
            "oos_end": white_oos["period_end"],
            "full_cagr": number(white_full, "annualized_return"),
            "full_max_drawdown": number(white_full, "maximum_drawdown"),
            "full_sharpe": number(white_full, "sharpe"),
            "oos_cagr": float(white_oos["annualized_return"]),
            "oos_max_drawdown": float(white_oos["maximum_drawdown"]),
            "oos_sharpe": float(white_oos["sharpe"]),
            "double_cost_cagr": number(white_double, "annualized_return"),
            "double_cost_max_drawdown": number(white_double, "maximum_drawdown"),
            "double_cost_sharpe": number(white_double, "sharpe"),
            "primary_capacity_min_exposure": white_score[
                "primary_capital_minimum_exposure"
            ],
            "primary_capacity_exposure_retention": white_score[
                "primary_capital_minimum_exposure_retention"
            ],
            "capacity_10m_0_5pct_exposure": minimum_capacity_exposure(
                white_id, (10_000_000,)
            ),
            "capacity_200k_exposure": capacity_exposure(white_id, 200_000),
            "capacity_1m_exposure": capacity_exposure(white_id, 1_000_000),
            "capacity_2m_exposure": capacity_exposure(white_id, 2_000_000),
            "capacity_10m_exposure": capacity_exposure(white_id, 10_000_000),
            "pbo": white_score["pbo"]["pbo"],
            "deflated_sharpe_probability": white_score["deflated_sharpe"][
                "deflated_sharpe_probability"
            ],
            "trial_count": white_score["experiment_count"],
            "top1_contribution_share": white_top["absolute_share"],
            "top3_contribution_share": float(
                white_contrib.head(3)["absolute_share"].sum()
            ),
            "core_risk_exposure": "; ".join(
                f"{row['name']}={float(row['value']):.3f}"
                for _, row in white_beta.iterrows()
                if row["name"] != "intercept-annualized"
            ),
            "correlation_status": "not-computed-no-R2-R3-set",
            "key_data_gap": "C-grade source; platform orders; production PIT financial contract",
            "next_action": "new preregistered relative-capacity protocol before any R2 reassessment",
            "stop_reason": "preregistered absolute capacity gate failed; no post-hoc promotion",
        }
    )

    lazy_id = "lazy-etf-regime-switch"
    lazy_score = read_json(RESULTS / lazy_id / "live-readiness-scorecard.json")
    lazy_rob = read_csv(lazy_id, "robustness.csv")
    lazy_full = match(lazy_rob, experiment="frozen-causal-baseline", variant="m4")
    lazy_stress = match(lazy_rob, experiment="cost-stress", variant="slippage-10bp")
    rows.append(
        {
            "candidate_id": lazy_id,
            "status": lazy_score["status"],
            "source_vintage_grade": lazy_score["source_vintage_grade"],
            "source_sha256": lazy_score["source_sha256"],
            "causal_source_sha256": lazy_score["source_sha256"],
            "strict_natural_oos": False,
            "oos_evidence_grade": "none",
            "full_cagr": number(lazy_full, "annualized_return"),
            "full_max_drawdown": number(lazy_full, "maximum_drawdown"),
            "full_sharpe": number(lazy_full, "sharpe"),
            "double_cost_cagr": number(lazy_stress, "annualized_return"),
            "double_cost_max_drawdown": number(lazy_stress, "maximum_drawdown"),
            "double_cost_sharpe": number(lazy_stress, "sharpe"),
            "trial_count": lazy_score["experiment_count"],
            "core_risk_exposure": "Nasdaq beta + GEM breakout overlay + gold defense",
            "correlation_status": "not-computed-no-R2-R3-set",
            "key_data_gap": "ADV capacity; QDII production data; daily-path PBO; platform orders",
            "next_action": "keep M4 frozen; fill non-alpha data and execution gaps only",
            "stop_reason": "no independent OOS and incomplete mandatory robustness suite",
        }
    )

    profit_id = "profitable-small-cap-a-share"
    profit_score = read_json(RESULTS / profit_id / "live-readiness-scorecard.json")
    profit_rob = read_csv(profit_id, "robustness.csv")
    profit_oos = read_csv(profit_id, "oos.csv").iloc[0]
    profit_full = match(profit_rob, experiment="full-history", variant="baseline")
    profit_double = match(
        profit_rob, experiment="cost-stress", variant="double-friction"
    )
    rows.append(
        {
            "candidate_id": profit_id,
            "status": profit_score["status"],
            "source_vintage_grade": profit_score["source_vintage_grade"],
            "source_sha256": profit_score["source_sha256"],
            "causal_source_sha256": profit_score["source_sha256"],
            "strict_natural_oos": False,
            "oos_evidence_grade": "C-reserved-not-frozen",
            "oos_start": profit_oos["period_start"],
            "oos_end": profit_oos["period_end"],
            "full_cagr": number(profit_full, "annualized_return"),
            "full_max_drawdown": number(profit_full, "maximum_drawdown"),
            "full_sharpe": number(profit_full, "sharpe"),
            "full_longest_underwater_days": 2308,
            "oos_cagr": float(profit_oos["annualized_return"]),
            "oos_max_drawdown": float(profit_oos["maximum_drawdown"]),
            "oos_sharpe": float(profit_oos["sharpe"]),
            "oos_longest_underwater_days": 200,
            "double_cost_cagr": number(profit_double, "annualized_return"),
            "double_cost_max_drawdown": number(profit_double, "maximum_drawdown"),
            "core_risk_exposure": "small-cap and liquidity premium with quality/risk overlays",
            "correlation_status": "not-computed-no-R2-R3-set",
            "key_data_gap": "10m capacity; Top contribution; platform full path; C-grade post-2023 limits",
            "next_action": "stop deployment if continued benchmark underperformance; platform audit only",
            "stop_reason": "67.95% full drawdown and reserved period underperformed CSI300",
        }
    )

    wufu_id = "wufu-etf-rotation"
    wufu_score = read_json(RESULTS / wufu_id / "live-readiness-scorecard.json")
    wufu_rob = read_csv(wufu_id, "robustness.csv")
    wufu_full = match(wufu_rob, experiment="cost-stress", variant="cost_10bp")
    wufu_double = match(wufu_rob, experiment="cost-stress", variant="cost_20bp")
    wufu_attr = read_csv(wufu_id, "attribution.csv")
    wufu_capacity = read_csv(wufu_id, "capacity.csv")
    ten_m_half_pct = wufu_capacity.loc[
        pd.to_numeric(wufu_capacity["capital_rmb"], errors="coerce").eq(10_000_000)
        & pd.to_numeric(wufu_capacity["adv_participation"], errors="coerce").eq(0.005),
        "average_exposure",
    ].iloc[0]
    rows.append(
        {
            "candidate_id": wufu_id,
            "status": wufu_score["status"],
            "source_vintage_grade": wufu_score["source_vintage_grade"],
            "source_sha256": wufu_score["source_sha256"],
            "causal_source_sha256": wufu_score["source_sha256"],
            "strict_natural_oos": False,
            "oos_evidence_grade": "none",
            "full_cagr": number(wufu_full, "annualized_return"),
            "full_max_drawdown": number(wufu_full, "maximum_drawdown"),
            "full_sharpe": number(wufu_full, "sharpe"),
            "full_longest_underwater_days": 875,
            "double_cost_cagr": number(wufu_double, "annualized_return"),
            "double_cost_max_drawdown": number(wufu_double, "maximum_drawdown"),
            "double_cost_sharpe": number(wufu_double, "sharpe"),
            "primary_capacity_min_exposure": minimum_capacity_exposure(
                wufu_id, (200_000, 1_000_000, 2_000_000)
            ),
            "capacity_10m_0_5pct_exposure": float(ten_m_half_pct),
            "capacity_200k_exposure": capacity_exposure(wufu_id, 200_000),
            "capacity_1m_exposure": capacity_exposure(wufu_id, 1_000_000),
            "capacity_2m_exposure": capacity_exposure(wufu_id, 2_000_000),
            "capacity_10m_exposure": capacity_exposure(wufu_id, 10_000_000),
            "pbo": wufu_score["pbo"],
            "deflated_sharpe_probability": wufu_score[
                "deflated_sharpe_probability"
            ],
            "trial_count": wufu_score["experiment_count"],
            "top1_contribution_share": float(wufu_attr.iloc[0]["positive_share"]),
            "top3_contribution_share": float(wufu_attr.head(3)["positive_share"].sum()),
            "core_risk_exposure": "Nasdaq/S&P500/commodity/gold rotation; static tracking labels",
            "correlation_status": "not-computed-no-R2-R3-set",
            "key_data_gap": "historical PIT tracking target; full platform portfolio; independent OOS",
            "next_action": "wait for independent data; do not select a grid or phase winner",
            "stop_reason": "7/16 protocol gates failed, including DSR, capacity, and concentration",
        }
    )

    for candidate in GENERIC_CANDIDATE_NOTES:
        rows.append(generic_candidate_row(candidate))

    safe_id = "multi-asset-etf-momentum-epo-safe"
    safe_score = read_json(RESULTS / safe_id / "live-readiness-scorecard.json")
    safe_rob = read_csv(safe_id, "robustness.csv")
    safe_attr = read_csv(safe_id, "attribution.csv")
    safe_audit = read_json(RESULTS / safe_id / "platform-production-audit.json")
    safe_full = match(safe_rob, experiment="safe-full-causal", variant="baseline")
    safe_double = match(safe_rob, experiment="cost-stress", variant="double")
    safe_post = match(
        read_csv("multi-asset-etf-momentum-epo", "oos.csv"),
        scenario="causal-baseline-cost",
    )
    safe_contrib = safe_attr[safe_attr["analysis_type"].eq("asset-contribution")]
    safe_beta = safe_attr[safe_attr["analysis_type"].eq("factor-beta")]
    safe_top = safe_contrib.iloc[0]
    rows.append(
        {
            "candidate_id": safe_id,
            "status": safe_score["status"],
            "source_vintage_grade": safe_score["source_vintage_grade"],
            "source_sha256": read_json(RESULTS / safe_id / "safe-run-manifest.json")[
                "source_sha256"
            ],
            "original_source_sha256": read_json(
                RESULTS / safe_id / "safe-run-manifest.json"
            )["source_sha256"],
            "causal_source_sha256": read_json(
                RESULTS / safe_id / "safe-run-manifest.json"
            )["engine_sha256"],
            "formal_source_sha256": safe_audit["formal_source_sha256"],
            "strict_natural_oos": False,
            "oos_evidence_grade": "B-downgraded-path-preserved",
            "oos_start": safe_post["period_start"],
            "oos_end": safe_post["period_end"],
            "full_cagr": number(safe_full, "annualized_return"),
            "full_max_drawdown": number(safe_full, "maximum_drawdown"),
            "full_sharpe": number(safe_full, "sharpe"),
            "full_longest_underwater_days": longest_underwater_from_equity(
                RESULTS / safe_id / "raw/safe__baseline-equity.csv"
            ),
            "oos_cagr": number(safe_post, "annualized_return"),
            "oos_max_drawdown": number(safe_post, "maximum_drawdown"),
            "oos_sharpe": number(safe_post, "sharpe"),
            "oos_longest_underwater_days": number(
                safe_post, "longest_underwater_trading_days"
            ),
            "double_cost_cagr": number(safe_double, "annualized_return"),
            "double_cost_max_drawdown": number(
                safe_double, "maximum_drawdown"
            ),
            "double_cost_sharpe": number(safe_double, "sharpe"),
            "primary_capacity_min_exposure": minimum_capacity_exposure(
                safe_id, (200_000, 1_000_000, 2_000_000)
            ),
            "capacity_10m_0_5pct_exposure": capacity_exposure(
                safe_id, 10_000_000
            ),
            "capacity_200k_exposure": capacity_exposure(safe_id, 200_000),
            "capacity_1m_exposure": capacity_exposure(safe_id, 1_000_000),
            "capacity_2m_exposure": capacity_exposure(safe_id, 2_000_000),
            "capacity_10m_exposure": capacity_exposure(safe_id, 10_000_000),
            "pbo": safe_score["pbo"]["pbo"],
            "deflated_sharpe_probability": safe_score["deflated_sharpe"][
                "deflated_sharpe_probability"
            ],
            "trial_count": safe_score["experiment_count"],
            "top1_contribution_share": safe_top["absolute_share"],
            "top3_contribution_share": float(
                safe_contrib.head(3)["absolute_share"].sum()
            ),
            "core_risk_exposure": "dynamic ETF concentration; "
            + "; ".join(
                f"{row['name']}={float(row['value']):.3f}"
                for _, row in safe_beta.iterrows()
                if row["name"] != "intercept-annualized"
            ),
            "correlation_status": "computed-against-simple-core-only",
            "key_data_gap": "real JoinQuant export; six QDII production fields; forward paper evidence",
            "next_action": "obtain non-alpha platform/data evidence; do not tune history",
            "stop_reason": None,
            "platform_status": "local-source-preflight-passed",
            "production_data_status": safe_audit["production_data"]["status"],
        }
    )

    result = pd.DataFrame(rows)
    for column in (
        "published_cagr",
        "published_max_drawdown",
        "published_sharpe",
        "full_cagr",
        "full_max_drawdown",
        "full_sharpe",
        "full_longest_underwater_days",
        "oos_cagr",
        "oos_max_drawdown",
        "oos_sharpe",
        "oos_longest_underwater_days",
        "double_cost_cagr",
        "double_cost_max_drawdown",
        "double_cost_sharpe",
        "primary_capacity_min_exposure",
        "primary_capacity_exposure_retention",
        "capacity_10m_0_5pct_exposure",
        "capacity_200k_exposure",
        "capacity_1m_exposure",
        "capacity_2m_exposure",
        "capacity_10m_exposure",
        "pbo",
        "deflated_sharpe_probability",
        "trial_count",
        "top1_contribution_share",
        "top3_contribution_share",
    ):
        if column not in result:
            result[column] = np.nan
    for column in (
        "original_source_sha256",
        "causal_source_sha256",
        "frozen_source_sha256",
        "oos_evidence_grade",
        "formal_source_sha256",
        "platform_status",
        "production_data_status",
    ):
        if column not in result:
            result[column] = None
    return result


def platform_audit() -> pd.DataFrame:
    control = read_json(
        ROOT
        / "strategies/joinquant/etf-core-rotation/backtests"
        / "2026-08-16__platform-calibration-and-source-decomposition__local-jq-2014-2026-v2"
        / "raw/platform-comparison.json"
    )
    rows = [
            {
                "candidate_id": "etf-core-rotation-calibration-control",
                "candidate_status": "control",
                "platform_status": "directionally-reconciled",
                "matched_observation_dates": control["matched_dates"],
                "mean_universe_jaccard": control["mean_universe_jaccard"],
                "selected_exact_match_ratio": control["selected_exact_match_ratio"],
                "mean_target_weight_l1": control["mean_target_weight_l1"],
                "evidence": "Research replay plus official 2014-2026 JoinQuant backtest",
                "gap": "static local tracking_target versus platform PIT FUND_INVEST_TARGET",
            },
            {
                "candidate_id": "low-risk-medium-return",
                "candidate_status": "R0",
                "platform_status": "blocked-before-comparison",
                "gap": "missing local 399317.XSHE PIT membership",
            },
            {
                "candidate_id": "multi-asset-etf-momentum-epo",
                "candidate_status": "R1",
                "platform_status": "not-run",
                "gap": "parameter neighborhood failed; order-level and QDII comparison absent",
            },
            {
                "candidate_id": "white-horse-offense-defense",
                "candidate_status": "R1",
                "platform_status": "not-run",
                "gap": "C-grade source and failed preregistered capacity gate",
            },
            {
                "candidate_id": "lazy-etf-regime-switch",
                "candidate_status": "R1",
                "platform_status": "not-run",
                "gap": "no order/weight golden comparison and no QDII production feed",
            },
            {
                "candidate_id": "profitable-small-cap-a-share",
                "candidate_status": "R1",
                "platform_status": "not-run",
                "gap": "archive explicitly requires full JoinQuant path reconciliation",
            },
            {
                "candidate_id": "wufu-etf-rotation",
                "candidate_status": "R1",
                "platform_status": "partial-minute-events-only",
                "gap": "A7 lacks complete portfolio equity/order comparison",
            },
        ]
    safe_audit = read_json(
        RESULTS / "multi-asset-etf-momentum-epo-safe/platform-production-audit.json"
    )
    safe_preflight = safe_audit["local_source_preflight"]
    rows.append(
        {
            "candidate_id": "multi-asset-etf-momentum-epo-safe",
            "candidate_status": "R2",
            "platform_status": "local-source-preflight-passed",
            "matched_observation_dates": safe_preflight[
                "matched_observation_dates"
            ],
            "selected_exact_match_ratio": safe_preflight[
                "exact_target_match_rate"
            ],
            "mean_target_weight_l1": safe_preflight["mean_target_weight_l1"],
            "local_exact_target_match_ratio": safe_preflight[
                "exact_target_match_rate"
            ],
            "real_joinquant_export_present": False,
            "eligible_for_R3": False,
            "evidence": "28-date local formal-source parity against frozen R2 targets",
            "gap": "real JoinQuant order/trade/equity export and QDII feeds absent",
        }
    )
    existing = {row["candidate_id"] for row in rows}
    unified = build_unified_results()
    for row in unified.itertuples(index=False):
        if row.candidate_id in existing:
            continue
        rows.append(
            {
                "candidate_id": row.candidate_id,
                "candidate_status": row.status,
                "platform_status": "not-run-stopped-before-R2",
                "real_joinquant_export_present": False,
                "eligible_for_R3": False,
                "gap": row.key_data_gap,
            }
        )
    return pd.DataFrame(rows)


def completion_audit() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"stage": 0, "status": "complete", "evidence": "593 sources, 445 lineages, 50-family shortlist"},
            {"stage": 1, "status": "complete-with-version-downgrades", "evidence": "P0 plus later B/C first-read replays; no C evidence called strict OOS"},
            {"stage": 2, "status": "complete", "evidence": "formal families mapped and the sole R2 candidate promoted to a research family"},
            {"stage": 3, "status": "complete-for-runnable-candidates", "evidence": "causal/source, factor and concentration decomposition retained"},
            {"stage": 4, "status": "complete-for-deep-candidates", "evidence": "safe EPO completed 66 preregistered runs; failures retained"},
            {"stage": 5, "status": "complete-for-R2", "evidence": "20m/100m/200m/10m capacity curve and delay/cost stress complete"},
            {"stage": 6, "status": "complete-with-external-blocker", "evidence": "28/28 local source targets exact; real JoinQuant export and QDII feeds absent"},
            {"stage": 7, "status": "not-entered-by-rule", "evidence": "no R3 candidate; frozen paper trading must not start"},
            {"stage": 8, "status": "complete-single-R2-no-portfolio", "evidence": "one R2 analyzed against simple core; no independent 2-4 candidate set"},
        ]
    )


def return_metrics(returns: pd.Series) -> dict[str, float]:
    clean = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    curve = (1.0 + clean).cumprod()
    volatility = clean.std(ddof=1)
    return {
        "cagr": float(curve.iloc[-1] ** (250.0 / len(clean)) - 1.0),
        "maximum_drawdown": float(-(curve / curve.cummax() - 1.0).min()),
        "sharpe": float(clean.mean() / volatility * np.sqrt(250.0))
        if volatility > 0.0
        else np.nan,
    }


def build_portfolio_analysis(unified: pd.DataFrame) -> pd.DataFrame:
    eligible = unified[unified["status"].isin(["R2", "R3"])]
    safe_path = RESULTS / "multi-asset-etf-momentum-epo-safe/raw/safe__oos-equity.csv"
    core_path = (
        RESULTS
        / "multi-asset-etf-momentum-epo/raw/equal-pool-baseline-cost__equity.csv"
    )
    safe = pd.read_csv(safe_path)[["trade_date", "daily_return"]].rename(
        columns={"daily_return": "candidate"}
    )
    core = pd.read_csv(core_path)[["trade_date", "daily_return"]].rename(
        columns={"daily_return": "simple_core"}
    )
    aligned = safe.merge(core, on="trade_date", validate="one_to_one")
    candidate = pd.to_numeric(aligned["candidate"], errors="raise")
    simple_core = pd.to_numeric(aligned["simple_core"], errors="raise")
    blend = 0.5 * candidate + 0.5 * simple_core
    candidate_metrics = return_metrics(candidate)
    core_metrics = return_metrics(simple_core)
    blend_metrics = return_metrics(blend)
    candidate_curve = (1.0 + candidate).cumprod()
    core_curve = (1.0 + simple_core).cumprod()
    shared_underwater = (
        candidate_curve.lt(candidate_curve.cummax())
        & core_curve.lt(core_curve.cummax())
    ).mean()
    return pd.DataFrame(
        [
            {
                "status": "analyzed-single-r2-no-multi-strategy-portfolio",
                "eligible_candidate_count": len(eligible),
                "eligible_candidates": "|".join(eligible["candidate_id"]),
                "required_status": "R2 or R3",
                "analysis_period_start": aligned["trade_date"].iloc[0],
                "analysis_period_end": aligned["trade_date"].iloc[-1],
                "aligned_trading_days": len(aligned),
                "simple_core": "13-ETF equal weight with baseline costs",
                "simple_core_return_correlation": float(
                    candidate.corr(simple_core)
                ),
                "shared_underwater_day_ratio": float(shared_underwater),
                "candidate_historical_cagr": candidate_metrics["cagr"],
                "candidate_historical_max_drawdown": candidate_metrics[
                    "maximum_drawdown"
                ],
                "candidate_historical_sharpe": candidate_metrics["sharpe"],
                "simple_core_cagr": core_metrics["cagr"],
                "simple_core_max_drawdown": core_metrics["maximum_drawdown"],
                "simple_core_sharpe": core_metrics["sharpe"],
                "candidate_plus_core_cagr": blend_metrics["cagr"],
                "candidate_plus_core_max_drawdown": blend_metrics[
                    "maximum_drawdown"
                ],
                "candidate_plus_core_sharpe": blend_metrics["sharpe"],
                "marginal_sharpe_vs_core": blend_metrics["sharpe"]
                - core_metrics["sharpe"],
                "proposed_frozen_portfolio": False,
                "decision": "retain one R2 for platform/data evidence; do not manufacture a 2-4 strategy portfolio",
                "reason": "only one eligible lineage and it still lacks R3 platform and production evidence",
            }
        ]
    )


def main() -> int:
    unified = build_unified_results()
    platform = platform_audit()
    completion = completion_audit()
    eligible = unified[unified["status"].isin(["R2", "R3"])]
    portfolio = build_portfolio_analysis(unified)
    unified.to_csv(STUDY_DIR / "unified-results.csv", index=False, encoding="utf-8-sig")
    platform.to_csv(
        STUDY_DIR / "platform-golden-audit.csv", index=False, encoding="utf-8-sig"
    )
    portfolio.to_csv(
        STUDY_DIR / "portfolio-analysis.csv", index=False, encoding="utf-8-sig"
    )
    completion.to_csv(
        STUDY_DIR / "completion-audit.csv", index=False, encoding="utf-8-sig"
    )
    safe = unified[
        unified["candidate_id"].eq("multi-asset-etf-momentum-epo-safe")
    ].iloc[0]
    portfolio_row = portfolio.iloc[0]
    status_counts = unified["status"].value_counts().to_dict()
    final = f"""# 可实盘策略研究：本轮最终判定

## 结论

本轮按预注册执行顺序完成了 593 份来源筛选、P0 与后续候选首次回放、因果重建、稳健性、成本、
容量、平台源码预检、生产数据合同和组合资格检查。统一纳入 15 个候选：**R0 {status_counts.get('R0', 0)}
个、R1 {status_counts.get('R1', 0)} 个、R2 {status_counts.get('R2', 0)} 个、R3—R5 0 个**。

唯一 R2 是 `multi-asset-etf-momentum-epo-safe`。它是“值得继续补平台与生产证据的历史候选”，
不是冻结模拟盘或小资金实盘候选。当前仍不提出 2—4 个冻结组合，也不启动实盘。

## 唯一 R2：为什么保留

- 收益来源：34 日跨资产趋势先选前三名，再由 EPO 动态分配；因子暴露同时包含黄金、商品、海外
  科技和 A 股成长，但权重会阶段性高度集中。
- 证据边界：B 级发布后窗口年化 {safe['oos_cagr']:.2%}、最大回撤
  {safe['oos_max_drawdown']:.2%}、Sharpe {safe['oos_sharpe']:.2f}；缺少发布前源码哈希，因此不称
  严格天然 OOS。安全回退没有使用该窗口选参，并保持 28/28 个原目标不变。
- 稳健性：27/27 参数邻域完成、全部正收益且 Sharpe 不低于 0.5；回退占比 1.02%，PBO
  {safe['pbo']:.2%}，Deflated Sharpe 概率 {safe['deflated_sharpe_probability']:.2%}。
- 执行与容量：0—5 日延迟最低 Sharpe 0.84；20—200 万元最低平均风险暴露
  {safe['primary_capacity_min_exposure']:.2%}。1000 万元、0.5% ADV 下平均暴露
  {safe['capacity_10m_0_5pct_exposure']:.2%}，显示容量衰减但不是小资金硬伤。

## 平台和生产边界

- 正式聚宽源码已建立；同一份本地行情输入下，28/28 个冻结目标完全一致，平均/最大目标权重 L1
  差异为 0。这是源码预检，不是真实聚宽黄金对照。
- 候选自己的聚宽目标、订单、拒单、成交、费用和净值导出仍不存在，不能用 ETF core 控制组替代。
- 13/13 只 ETF 有历史 OHLCV 和成交额，但 `513100.XSHG`、`159740.XSHE` 缺 IOPV/NAV、
  折溢价、申赎状态与额度、境外市场会话和汇率生产数据，必须失败关闭。
- 没有 R3，因此阶段 7 按规则不启动；冻结模拟盘证据为零。

## 组合分析

合格集合只有一个独立谱系。R2 与 13 只 ETF 简单等权核心的日收益相关性为
{portfolio_row['simple_core_return_correlation']:.3f}，共同水下日占比
{portfolio_row['shared_underwater_day_ratio']:.1%}。50/50 诊断组合的 Sharpe 为
{portfolio_row['candidate_plus_core_sharpe']:.2f}，相比简单核心边际变化
{portfolio_row['marginal_sharpe_vs_core']:+.2f}；这只能说明与简单核心的边际关系，不能把一个候选和
一个基准包装成“2—4 个策略组合”。

## 资金规划压力

- 历史年化只实现 50%：全期参考年化从 {safe['full_cagr']:.2%} 折为
  {safe['full_cagr'] * 0.5:.2%}；这不是收益预测。
- 最大回撤放大 1.5 倍：发布后参考回撤从 {safe['oos_max_drawdown']:.2%} 放大到
  {safe['oos_max_drawdown'] * 1.5:.2%}。
- 双倍摩擦：全期年化 {safe['double_cost_cagr']:.2%}、最大回撤
  {safe['double_cost_max_drawdown']:.2%}、Sharpe {safe['double_cost_sharpe']:.2f}。
- 全期最长水下 {int(safe['full_longest_underwater_days'])} 个交易日；发布后最长水下
  {int(safe['oos_longest_underwater_days'])} 个交易日。

## 后续触发条件

下一步只允许补非 Alpha 证据：取得候选自身真实聚宽导出；接入并观测 QDII 与实时报价数据合同；
全部 R3 门槛通过后冻结源码和哈希，再开始前瞻模拟盘。任何资产池、信号或权重规则变化都必须成为
新候选重新预注册，不能继续围绕已观察历史收益搜索参数。
"""
    (STUDY_DIR / "final-assessment.md").write_text(final, encoding="utf-8")
    print(
        json.dumps(
            {
                "candidate_count": len(unified),
                "status_counts": status_counts,
                "eligible_portfolio_candidates": len(eligible),
                "decision": portfolio.iloc[0]["decision"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
