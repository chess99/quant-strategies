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
    return pd.DataFrame(
        [
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
    )


def completion_audit() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"stage": 0, "status": "complete", "evidence": "593 sources, 445 lineages, 50-family shortlist"},
            {"stage": 1, "status": "complete-with-version-downgrades", "evidence": "three P0 audits; B/C replays and one C data block"},
            {"stage": 2, "status": "complete", "evidence": "three formal families mapped to standard artifacts"},
            {"stage": 3, "status": "complete-for-runnable-candidates", "evidence": "causal/source and concentration decomposition retained"},
            {"stage": 4, "status": "complete-for-deep-candidates", "evidence": "EPO and white suites; formal archives mapped without reranking"},
            {"stage": 5, "status": "complete-with-documented-gaps", "evidence": "three curves, one partial grid, and one missing ADV model"},
            {"stage": 6, "status": "audited-no-candidate-eligible", "evidence": "ETF core control reconciled; all candidates below R2"},
            {"stage": 7, "status": "not-entered-by-rule", "evidence": "no R3 candidate; no frozen paper portfolio"},
            {"stage": 8, "status": "complete-no-eligible-set", "evidence": "zero R2/R3 inputs; no forced portfolio"},
        ]
    )


def main() -> int:
    unified = build_unified_results()
    platform = platform_audit()
    completion = completion_audit()
    eligible = unified[unified["status"].isin(["R2", "R3"])]
    portfolio = pd.DataFrame(
        [
            {
                "status": "not-run-no-eligible-candidates",
                "eligible_candidate_count": len(eligible),
                "required_status": "R2 or R3",
                "decision": "do not propose a 2-4 strategy frozen paper portfolio",
                "correlation_matrix": "not-computed",
                "reason": "all six shortlisted/deep candidates are R0 or R1",
            }
        ]
    )
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
    final = """# 可实盘策略研究：本轮最终判定

## 结论

本轮按预注册执行顺序完成了筛选、P0 审计与回放、两个候选深挖、三个正式策略族证据映射、平台
差距审计和组合资格检查。最终 **R0 1 个、R1 5 个、R2/R3 0 个**。因此当前没有证据支持提出
2—4 个冻结模拟盘组合，也没有策略可以进入小资金实盘。

## 值得保留的研究线索

- 懒人 ETF M4 历史最强，但缺容量、QDII 生产数据、PBO/DSR、平台对照和独立 OOS。
- 白马攻防的参数、成本和延迟结果较稳健，但版本为 C，且预注册容量绝对暴露门槛失败；不能事后
  改成相对口径追溯晋级。
- ETF 动量 + EPO 的降级发布后回放亮眼，但只有 51.9% 参数邻域达到 Sharpe 0.5，保持 R1。
- 盈利质量小市值保留期为正但跑输沪深300，全历史回撤 67.95%、水下 2,308 个交易日。
- 五福 T3 只通过 9/16 项事前门槛，已按停止规则结束历史调参。
- 低风险组合缺少 `399317.XSHE` 历史成分，保持 R0，不擅自更换股票池。

## 平台与组合

`etf-core-rotation` 校准控制证明本地与聚宽价格特征可高度一致，但静态跟踪标的会造成候选与权重
差异；该控制不能替代候选自己的订单对账。由于没有 R2/R3，组合相关性、共同回撤和边际 Sharpe
按规则不计算，避免用一组尚未过关的 R1 策略制造“分散化”假象。

## 后续触发条件

只有出现以下新证据时才重启相应候选：取得缺失的 PIT 数据；按新协议补齐非 Alpha 容量/生产数据；
完成候选自身平台黄金对照；或积累未参与调参的冻结模拟盘/真实前瞻数据。不得继续围绕现有历史收益
搜索参数。
"""
    (STUDY_DIR / "final-assessment.md").write_text(final, encoding="utf-8")
    print(
        json.dumps(
            {
                "candidate_count": len(unified),
                "status_counts": unified["status"].value_counts().to_dict(),
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
