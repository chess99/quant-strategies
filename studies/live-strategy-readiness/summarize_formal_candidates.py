"""将三个正式策略族的不可变研究归档映射为统一实盘准备度证据。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


STUDY_DIR = Path(__file__).resolve().parent
ROOT = STUDY_DIR.parents[1]
RESULTS = STUDY_DIR / "results"

LAZY_ARCHIVE = (
    ROOT
    / "strategies/joinquant/lazy-etf-regime-switch/backtests"
    / "2026-08-11__causal-experiment-suite__local-etf-2014-2026-v1"
)
PROFIT_ARCHIVE = (
    ROOT
    / "strategies/joinquant/profitable-small-cap-a-share/backtests"
    / "2026-08-02__baseline__local-qlib-2014-2026-v1"
)
WUFU_ARCHIVE = (
    ROOT
    / "strategies/joinquant/wufu-etf-rotation/backtests"
    / "2026-08-21__tradability-v3__local-etf-2015-2026-v1"
)
WUFU_PARENT = (
    ROOT
    / "strategies/joinquant/wufu-etf-rotation/backtests"
    / "2026-08-16__direct-decomposition__local-etf-2015-2026-v1"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_candidate(
    candidate_id: str,
    *,
    audit: str,
    protocol: dict[str, Any],
    comparison: pd.DataFrame,
    robustness: pd.DataFrame,
    oos: pd.DataFrame,
    capacity: pd.DataFrame,
    attribution: pd.DataFrame,
    scorecard: dict[str, Any],
    conclusion: str,
) -> None:
    target = RESULTS / candidate_id
    target.mkdir(parents=True, exist_ok=True)
    (target / "source-audit.md").write_text(audit, encoding="utf-8")
    write_json(target / "protocol.json", protocol)
    comparison.to_csv(target / "original-vs-causal.csv", index=False, encoding="utf-8-sig")
    robustness.to_csv(target / "robustness.csv", index=False, encoding="utf-8-sig")
    oos.to_csv(target / "oos.csv", index=False, encoding="utf-8-sig")
    capacity.to_csv(target / "capacity.csv", index=False, encoding="utf-8-sig")
    attribution.to_csv(target / "attribution.csv", index=False, encoding="utf-8-sig")
    write_json(target / "live-readiness-scorecard.json", scorecard)
    (target / "conclusion.md").write_text(conclusion, encoding="utf-8")


def provenance_protocol(
    candidate_id: str,
    manifests: list[Path],
    *,
    evidence_rule: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "study_id": "live-strategy-readiness",
        "candidate_id": candidate_id,
        "created_at": "2026-08-25",
        "status": "existing-evidence-mapping-no-new-backtest",
        "evidence_rule": evidence_rule,
        "no_new_parameter_selection": True,
        "source_manifests": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": sha256(path),
            }
            for path in manifests
        ],
        "immutability": (
            "The strategy-family archives are referenced by path and hash and are not "
            "copied, rewritten, or treated as new out-of-sample evidence."
        ),
    }


def generate_lazy() -> dict[str, Any]:
    manifest_path = LAZY_ARCHIVE / "manifest.json"
    manifest = read_json(manifest_path)
    raw = LAZY_ARCHIVE / "raw"
    models = pd.read_csv(raw / "model-metrics.csv")
    periods = pd.read_csv(raw / "period-metrics.csv")
    costs = pd.read_csv(raw / "cost-sensitivity.csv")
    replacements = pd.read_csv(raw / "asset-replacements.csv")
    grid = pd.read_csv(raw / "parameter-grid.csv")
    published = read_json(
        ROOT / "joinquant_archive/data/ETF轮动策略/傻瓜模型1.5_backtest.json"
    )["backtests"][0]
    m4 = models.set_index("model").loc["m4"]
    comparison = pd.DataFrame(
        [
            {
                "scenario": "published-community-backtest",
                "period_start": published["configuration"]["start_date"],
                "period_end": published["configuration"]["end_date"],
                "annualized_return": published["stats"]["annual_algo_return"],
                "maximum_drawdown": published["stats"]["max_drawdown"],
                "sharpe": published["stats"]["sharpe"],
                "causal": False,
                "note": "same-day final close used before 14:50 execution",
            },
            {
                "scenario": "local-causal-m4",
                "period_start": manifest["period"]["start"],
                "period_end": manifest["period"]["end"],
                "annualized_return": m4["annualized_return"],
                "maximum_drawdown": m4["maximum_drawdown"],
                "sharpe": m4["sharpe"],
                "causal": True,
                "note": "weekly close signal, next-session open execution",
            },
        ]
    )
    robustness_rows = [
        {
            "experiment": "frozen-causal-baseline",
            "variant": "m4",
            "annualized_return": m4["annualized_return"],
            "maximum_drawdown": m4["maximum_drawdown"],
            "sharpe": m4["sharpe"],
            "trial_count": 1,
        },
        {
            "experiment": "parameter-grid-summary",
            "variant": "3069-combinations",
            "annualized_return": grid["annualized_return"].median(),
            "maximum_drawdown": grid["maximum_drawdown"].median(),
            "sharpe": grid["sharpe"].median(),
            "trial_count": len(grid),
            "positive_return_rate": float(grid["annualized_return"].gt(0).mean()),
            "note": "metrics-only grid; no daily path matrix for valid PBO",
        },
    ]
    for row in costs.itertuples(index=False):
        robustness_rows.append(
            {
                "experiment": "cost-stress",
                "variant": row.cost_case,
                "annualized_return": row.annualized_return,
                "maximum_drawdown": row.maximum_drawdown,
                "sharpe": row.sharpe,
                "trial_count": 1,
            }
        )
    for row in periods[periods["model"].eq("m4")].itertuples(index=False):
        robustness_rows.append(
            {
                "experiment": "period-slice",
                "variant": row.period,
                "annualized_return": row.annualized_return,
                "maximum_drawdown": row.maximum_drawdown,
                "sharpe": row.sharpe,
                "trial_count": 1,
            }
        )
    for row in replacements.itertuples(index=False):
        robustness_rows.append(
            {
                "experiment": "asset-replacement",
                "variant": row.replacement,
                "annualized_return": row.annualized_return,
                "maximum_drawdown": row.maximum_drawdown,
                "sharpe": row.sharpe,
                "trial_count": 1,
            }
        )
    capacity = pd.DataFrame(
        [
            {
                "capital_rmb": capital,
                "status": "not-run-data-gap",
                "reason": "archived engine did not model ADV participation or ETF premium/discount",
            }
            for capital in (200_000, 1_000_000, 2_000_000, 10_000_000)
        ]
    )
    attribution = models[
        ["model", "label", "annualized_return", "maximum_drawdown", "sharpe"]
    ].rename(columns={"model": "name", "label": "note"})
    attribution.insert(0, "analysis_type", "module-ablation")
    scorecard = {
        "schema_version": 1,
        "candidate_id": "lazy-etf-regime-switch",
        "status": "R1",
        "source_vintage_grade": "B",
        "strict_natural_oos": False,
        "source_sha256": manifest["source_sha256"],
        "experiment_count": int(
            manifest["experiment_counts"]["models_and_benchmarks"]
            + manifest["experiment_counts"]["parameter_combinations"]
            + manifest["experiment_counts"]["asset_replacements"]
            + manifest["experiment_counts"]["cost_cases"]
        ),
        "gates": {
            "causal_implementation": True,
            "parameter_neighborhood": True,
            "cost_stress": True,
            "capacity": False,
            "multiple_testing": False,
            "credible_oos": False,
            "platform_alignment": False,
            "production_qdii_data": False,
        },
        "decision": "remain R1 until capacity, PBO/DSR, platform, and production ETF data gaps close",
    }
    protocol = provenance_protocol(
        "lazy-etf-regime-switch",
        [manifest_path],
        evidence_rule="Use M4 frozen archive as historical evidence; do not select M3 or a grid winner.",
    )
    audit = f"""# 懒人 ETF 状态切换：证据审计

- 正式事实源：`strategies/joinquant/lazy-etf-regime-switch/`。
- 因果实验归档：`{manifest_path.relative_to(ROOT).as_posix()}`。
- 冻结源码 SHA-256：`{manifest['source_sha256']}`。
- 社区回测在 14:50 使用当日最终收盘数据，正式 M4 已改为收盘后信号、下一交易日开盘成交。
- 帖子发布于 2026-08-09，现有历史均已被研究者看见；没有可信天然 OOS。
- 归档没有 ADV 容量、QDII 折溢价、PBO/DSR 或完整平台订单对照，不能晋级 R2/R3。
"""
    conclusion = f"""# 懒人 ETF 状态切换：统一结论

## 结论

当前等级：**R1**。严格因果 M4 全期年化 {m4['annualized_return']:.2%}、最大回撤
{m4['maximum_drawdown']:.2%}、Sharpe {m4['sharpe']:.2f}；3,069 组参数均为正收益，历史骨架
并非单点尖峰。

## 限制与决定

全部历史在 2026 年研究时已经可见，且缺少 ADV 容量、QDII 折溢价生产数据、有效 PBO/DSR 和
平台订单级对照。保持 M4 参数冻结，不从 M3 或网格冠军改基线；补齐这些证据前不晋级 R2。
"""
    write_candidate(
        "lazy-etf-regime-switch",
        audit=audit,
        protocol=protocol,
        comparison=comparison,
        robustness=pd.DataFrame(robustness_rows),
        oos=pd.DataFrame(
            [
                {
                    "status": "not-available",
                    "strict_natural_oos": False,
                    "reason": "no unobserved interval after the 2026-08-11 frozen archive",
                }
            ]
        ),
        capacity=capacity,
        attribution=attribution,
        scorecard=scorecard,
        conclusion=conclusion,
    )
    return scorecard


def generate_profit() -> dict[str, Any]:
    manifest_path = PROFIT_ARCHIVE / "manifest.json"
    manifest = read_json(manifest_path)
    metrics = manifest["metrics"]
    stress = manifest["stress_tests"]
    public_archive = read_json(
        ROOT
        / "joinquant_archive/data/2024年度精选策略"
        / "13.5年15倍的收益，年化79.93%，可实盘，拿走不谢！.json"
    )["remote"]["backtests"][0]
    full = metrics["full_2014_2026"]
    published = metrics["published_2019_2023"]
    post = metrics["post_publication"]
    comparison = pd.DataFrame(
        [
            {
                "scenario": "published-community-backtest",
                "annualized_return": public_archive["stats"]["annual_algo_return"],
                "maximum_drawdown": public_archive["stats"]["max_drawdown"],
                "sharpe": public_archive["stats"]["sharpe"],
                "note": "platform claim; intraday limit-up exit not reproducible with daily bars",
            },
            {
                "scenario": "local-published-core",
                "annualized_return": 0.4637,
                "maximum_drawdown": 0.2615,
                "sharpe": None,
                "note": "daily-bar reconstruction of the core small-cap rules",
            },
            {
                "scenario": "local-causal-deployable",
                "annualized_return": published["annualized_return"],
                "maximum_drawdown": published["maximum_drawdown"],
                "sharpe": published["sharpe"],
                "note": "PIT financials, liquidity, industry limit, and risk overlay",
            },
        ]
    )
    robustness = pd.DataFrame(
        [
            {
                "experiment": "full-history",
                "variant": "baseline",
                "annualized_return": full["annualized_return"],
                "maximum_drawdown": full["maximum_drawdown"],
                "sharpe": full["sharpe"],
                "note": f"longest underwater {full['longest_underwater_trading_days']} sessions",
            },
            {
                "experiment": "post-publication",
                "variant": "baseline",
                "annualized_return": post["annualized_return"],
                "maximum_drawdown": post["maximum_drawdown"],
                "sharpe": post["sharpe"],
                "note": "reserved evaluation but implementation was not frozen before interval",
            },
            {
                "experiment": "cost-stress",
                "variant": "double-friction",
                "annualized_return": stress["double_friction"][
                    "post_publication_annualized_return"
                ],
                "maximum_drawdown": stress["double_friction"][
                    "post_publication_maximum_drawdown"
                ],
            },
            {
                "experiment": "holding-count-neighborhood",
                "variant": "15",
                "annualized_return": stress["positions_15"][
                    "post_publication_annualized_return"
                ],
                "maximum_drawdown": stress["positions_15"][
                    "post_publication_maximum_drawdown"
                ],
            },
            {
                "experiment": "holding-count-neighborhood",
                "variant": "20",
                "annualized_return": post["annualized_return"],
                "maximum_drawdown": post["maximum_drawdown"],
                "sharpe": post["sharpe"],
            },
            {
                "experiment": "holding-count-neighborhood",
                "variant": "30",
                "annualized_return": stress["positions_30"][
                    "post_publication_annualized_return"
                ],
                "maximum_drawdown": stress["positions_30"][
                    "post_publication_maximum_drawdown"
                ],
            },
        ]
    )
    capacity = pd.DataFrame(
        [
            {"capital_rmb": 200_000, "status": "not-run"},
            {
                "capital_rmb": 1_000_000,
                "status": "baseline",
                "annualized_return": post["annualized_return"],
                "maximum_drawdown": post["maximum_drawdown"],
                "adv_participation": 0.05,
            },
            {"capital_rmb": 2_000_000, "status": "not-run"},
            {
                "capital_rmb": 5_000_000,
                "status": "supplemental",
                "annualized_return": stress["initial_cash_5m"][
                    "post_publication_annualized_return"
                ],
                "maximum_drawdown": stress["initial_cash_5m"][
                    "post_publication_maximum_drawdown"
                ],
                "adv_participation": 0.05,
            },
            {"capital_rmb": 10_000_000, "status": "not-run"},
        ]
    )
    attribution = pd.DataFrame(
        [
            {
                "analysis_type": "return-source",
                "name": "small-cap-style",
                "value": None,
                "note": "dominant economic exposure identified by module reconstruction",
            },
            {
                "analysis_type": "risk-factor",
                "name": "full-history-drawdown",
                "value": full["maximum_drawdown"],
                "note": "2015-06-12 to 2018-10-16",
            },
            {
                "analysis_type": "data-gap",
                "name": "top-contributor-concentration",
                "value": None,
                "note": "not computed in immutable archive",
            },
        ]
    )
    scorecard = {
        "schema_version": 1,
        "candidate_id": "profitable-small-cap-a-share",
        "status": "R1",
        "source_vintage_grade": "C",
        "strict_natural_oos": False,
        "source_sha256": manifest["source_sha256"],
        "gates": {
            "causal_implementation": True,
            "holding_count_neighborhood": True,
            "double_friction": True,
            "post_publication_positive": True,
            "post_publication_beats_benchmark": False,
            "full_history_drawdown": False,
            "required_capacity_grid": False,
            "multiple_testing": False,
            "platform_alignment": False,
        },
        "decision": "remain R1; positive reserved period does not establish an independent edge",
    }
    protocol = provenance_protocol(
        "profitable-small-cap-a-share",
        [manifest_path],
        evidence_rule="Use the archived 20-stock baseline; do not select a new risk overlay or holding count.",
    )
    audit = f"""# 盈利质量小市值：证据审计

- 正式事实源：`strategies/joinquant/profitable-small-cap-a-share/`。
- 不可变归档：`{manifest_path.relative_to(ROOT).as_posix()}`。
- 冻结源码 SHA-256：`{manifest['source_sha256']}`。
- 原帖发布于 2023-12-14；当前正式基线是后来重建的可部署版本，未在 2023-12-01 前冻结，
  因而“发布后”区间不是该基线的严格天然 OOS。
- 2023-07 后涨跌停状态为 C 级规则推导，尚无聚宽完整黄金对照。
"""
    conclusion = f"""# 盈利质量小市值：统一结论

## 结论

当前等级：**R1**。全期年化 {full['annualized_return']:.2%}、最大回撤
{full['maximum_drawdown']:.2%}、Sharpe {full['sharpe']:.2f}；保留评估期年化
{post['annualized_return']:.2%}、最大回撤 {post['maximum_drawdown']:.2%}、Sharpe
{post['sharpe']:.2f}，同期明显跑输沪深300。

## 决定

持股数邻域、双倍摩擦和500万元场景没有单点崩溃，但 68% 全期回撤、2,308 个交易日水下期、
缺少独立冻结 OOS、完整容量网格、Top贡献归因和平台对照。保持 research 状态，不扩大参数搜索。
"""
    write_candidate(
        "profitable-small-cap-a-share",
        audit=audit,
        protocol=protocol,
        comparison=comparison,
        robustness=robustness,
        oos=pd.DataFrame(
            [
                {
                    "scenario": "reserved-post-publication-evaluation",
                    "period_start": manifest["period"]["post_publication"]["start"],
                    "period_end": manifest["period"]["post_publication"]["end"],
                    "annualized_return": post["annualized_return"],
                    "maximum_drawdown": post["maximum_drawdown"],
                    "sharpe": post["sharpe"],
                    "strict_natural_oos": False,
                    "reason": "deployable implementation was created after the interval began",
                }
            ]
        ),
        capacity=capacity,
        attribution=attribution,
        scorecard=scorecard,
        conclusion=conclusion,
    )
    return scorecard


def generate_wufu() -> dict[str, Any]:
    manifest_path = WUFU_ARCHIVE / "manifest.json"
    parent_path = WUFU_PARENT / "manifest.json"
    manifest = read_json(manifest_path)
    parent = read_json(parent_path)
    raw = WUFU_ARCHIVE / "raw"
    costs = pd.read_csv(raw / "cost-stress.csv")
    capacity = pd.read_csv(raw / "capacity-stress.csv")
    exclusions = pd.read_csv(raw / "contributor-exclusion.csv")
    structure = pd.read_csv(raw / "structural-grid.csv")
    contributions = pd.read_csv(raw / "asset-contributions.csv")
    pbo = read_json(raw / "pbo.json")
    dsr = read_json(raw / "dsr.json")
    walk = read_json(raw / "walk-forward-summary.json")
    primary = manifest["metrics"]["T3_primary"]
    a6 = manifest["metrics"]["A6_top3_reference"]
    public = parent["metrics"]["public_reference"]
    comparison = pd.DataFrame(
        [
            {
                "scenario": "published-platform-reference",
                "annualized_return": public["annual_algo_return"],
                "maximum_drawdown": public["max_drawdown"],
                "sharpe": public["sharpe"],
                "note": "community public result; local dynamic universe is only a lifecycle proxy",
            },
            {
                "scenario": "local-a6-top3",
                "annualized_return": a6["annualized_return"],
                "maximum_drawdown": a6["maximum_drawdown"],
                "sharpe": a6["sharpe"],
                "note": "2bp high-turnover reference",
            },
            {
                "scenario": "local-tradability-v3",
                "annualized_return": primary["annualized_return"],
                "maximum_drawdown": primary["maximum_drawdown"],
                "sharpe": primary["sharpe"],
                "note": "10bp weekly Top3 candidate; failed 7 of 16 gates",
            },
        ]
    )
    robustness_rows = []
    for row in costs.itertuples(index=False):
        robustness_rows.append(
            {
                "experiment": "cost-stress",
                "variant": row.trial,
                "annualized_return": row.annualized_return,
                "maximum_drawdown": row.maximum_drawdown,
                "sharpe": row.sharpe,
            }
        )
    robustness_rows.extend(
        [
            {
                "experiment": "structural-grid-summary",
                "variant": "96-trials",
                "annualized_return": structure["annualized_return"].median(),
                "maximum_drawdown": structure["maximum_drawdown"].median(),
                "sharpe": structure["sharpe"].median(),
                "positive_return_rate": float(
                    structure["annualized_return"].gt(0).mean()
                ),
            },
            {
                "experiment": "multiple-testing",
                "variant": "pbo",
                "pbo": pbo["pbo"],
                "trial_count": pbo["trial_count"],
            },
            {
                "experiment": "multiple-testing",
                "variant": "deflated-sharpe",
                "deflated_sharpe_probability": dsr[
                    "deflated_sharpe_probability"
                ],
                "trial_count": dsr["trial_count"],
            },
            {
                "experiment": "walk-forward",
                "variant": "2019-2026",
                "annualized_return": walk["annualized_return"],
                "maximum_drawdown": walk["maximum_drawdown"],
                "sharpe": walk["sharpe"],
                "worst_year": walk["worst_year"],
            },
        ]
    )
    capacity_out = capacity[
        [
            "initial_cash",
            "adv_participation",
            "annualized_return",
            "maximum_drawdown",
            "sharpe",
            "average_exposure",
        ]
    ].rename(columns={"initial_cash": "capital_rmb"})
    capacity_out = pd.concat(
        [
            capacity_out,
            pd.DataFrame(
                [
                    {
                        "capital_rmb": 2_000_000,
                        "status": "not-run-exact-capital",
                        "note": "nearest archived scenarios are 1m and 5m",
                    }
                ]
            ),
        ],
        ignore_index=True,
    ).sort_values(["capital_rmb", "adv_participation"], na_position="last")
    attribution = contributions.rename(
        columns={
            "symbol": "name",
            "return_contribution": "value",
            "positive_contribution_share": "positive_share",
        }
    )
    attribution.insert(0, "analysis_type", "asset-contribution")
    attribution = attribution[
        [
            "analysis_type",
            "name",
            "value",
            "positive_share",
            "holding_days",
            "average_portfolio_weight",
            "maximum_weight",
        ]
    ]
    for row in exclusions.itertuples(index=False):
        robustness_rows.append(
            {
                "experiment": "contributor-exclusion",
                "variant": row.trial,
                "annualized_return": row.annualized_return,
                "maximum_drawdown": row.maximum_drawdown,
                "sharpe": row.sharpe,
                "cagr_retention": row.cagr_retention,
                "excluded_symbols": row.excluded_symbols,
            }
        )
    scorecard = {
        "schema_version": 1,
        "candidate_id": "wufu-etf-rotation",
        "status": "R1",
        "source_vintage_grade": "C",
        "strict_natural_oos": False,
        "source_sha256": manifest["source_sha256"],
        "experiment_count": manifest["experiment_counts"]["direct_backtests_total"],
        "protocol_gates_passed": manifest["metrics"]["success_gates"]["passed"],
        "protocol_gates_total": manifest["metrics"]["success_gates"]["total"],
        "pbo": pbo["pbo"],
        "deflated_sharpe_probability": dsr["deflated_sharpe_probability"],
        "gates": {
            "causal_lifecycle_universe": True,
            "historical_tracking_target_pit": False,
            "complete_protocol": False,
            "cost_stress": False,
            "primary_capacity": False,
            "contributor_exclusion": False,
            "walk_forward": False,
            "pbo": True,
            "deflated_sharpe": False,
            "credible_oos": False,
            "platform_full_portfolio": False,
        },
        "decision": "stop historical tuning and remain R1 pending independent evidence",
    }
    protocol = provenance_protocol(
        "wufu-etf-rotation",
        [parent_path, manifest_path],
        evidence_rule="Use preregistered T3 as the final historical test; never select a structural-grid or schedule-phase winner.",
    )
    audit = f"""# 五福 ETF 轮动：证据审计

- 正式事实源：`strategies/joinquant/wufu-etf-rotation/`。
- 直接分解与 T3 归档分别为 `{parent_path.relative_to(ROOT).as_posix()}` 和
  `{manifest_path.relative_to(ROOT).as_posix()}`。
- T3 源码 SHA-256：`{manifest['source_sha256']}`；协议 SHA-256：`{manifest['protocol_sha256']}`。
- T3 的本地 `original_like` 仅有生命周期 PIT；ETF 跟踪标的仍来自当前静态字段，不能称为完整因果池。
- A7 只完成事件级分钟校准，没有完整组合净值与成交后 Sharpe 对照。
"""
    conclusion = f"""# 五福 ETF 轮动：统一结论

## 结论

当前等级：**R1**，并停止历史调参。T3 在 10bp 下年化 {primary['annualized_return']:.2%}、
最大回撤 {primary['maximum_drawdown']:.2%}、Sharpe {primary['sharpe']:.2f}，16 项事前门槛仅通过
9 项。

## 决定

20bp 成本、1000万元/0.5% ADV、Top5 删除、最差滚动三年、walk-forward 最差年度和 DSR 均暴露
明显风险。保留全部失败证据，不从96组结构矩阵或五个周频相位挑新冠军；等待独立数据或新经济假设。
"""
    write_candidate(
        "wufu-etf-rotation",
        audit=audit,
        protocol=protocol,
        comparison=comparison,
        robustness=pd.DataFrame(robustness_rows),
        oos=pd.DataFrame(
            [
                {
                    "status": "not-available",
                    "strict_natural_oos": False,
                    "reason": "all 2015-2026 history was visible before T3 assessment",
                }
            ]
        ),
        capacity=capacity_out,
        attribution=attribution,
        scorecard=scorecard,
        conclusion=conclusion,
    )
    return scorecard


def main() -> int:
    scorecards = [generate_lazy(), generate_profit(), generate_wufu()]
    print(json.dumps(scorecards, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
