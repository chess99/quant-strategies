"""生成迭代 5 日线撮合器机器验收报告。"""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.backtest_verification import verify_daily_backtester  # noqa: E402
from quant_research.data.store import sha256_file  # noqa: E402


RESULT_DIR = (
    ROOT
    / "studies"
    / "joinquant-small-cap-golden-comparison"
    / "results"
    / "2026-07-29__monthly-small-cap__local-preflight-v12"
)
OUTPUT = ROOT / "docs" / "local-research" / "daily-backtester-verification.json"
GOLDEN_V1_DIR = (
    ROOT
    / "studies"
    / "joinquant-small-cap-golden-comparison"
    / "results"
    / "2026-07-28__monthly-small-cap__joinquant-golden-v1"
)
GOLDEN_V2_DIR = (
    ROOT
    / "studies"
    / "joinquant-small-cap-golden-comparison"
    / "results"
    / "2026-07-28__monthly-small-cap__joinquant-golden-v2"
)
TARGET_REPLAY_DIR = (
    ROOT
    / "studies"
    / "joinquant-small-cap-golden-comparison"
    / "results"
    / "2026-07-29__monthly-small-cap__joinquant-golden-replay-v3"
)
AUTONOMOUS_DIR = (
    ROOT
    / "studies"
    / "joinquant-small-cap-golden-comparison"
    / "results"
    / "2026-07-29__monthly-small-cap__joinquant-autonomous-v4"
)


def golden_summary(result_dir: Path, diagnosis: str) -> dict:
    comparison = json.loads((result_dir / "comparison.json").read_text(encoding="utf-8"))
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    return {
        "status": comparison["status"],
        "run_id": manifest["run_id"],
        "backtest_id": manifest["joinquant"]["backtest_url"].split("=")[-1],
        "initial_cash": manifest["joinquant"]["initial_cash"],
        "candidate_dates": comparison["joinquant_candidate_dates"],
        "holding_dates": comparison["joinquant_holding_dates"],
        "candidate_overlap": comparison["mean_overlap"]["selected_candidates"],
        "holding_overlap": comparison["mean_overlap"]["holdings"],
        "order_symbol_overlap": comparison["mean_overlap"]["ordered_symbols"],
        "annualized_return": comparison["joinquant_metrics"]["annualized_return"],
        "maximum_drawdown": comparison["joinquant_metrics"]["maximum_drawdown"],
        "annualized_difference": comparison["differences"]["annualized_return"],
        "drawdown_difference": comparison["differences"]["maximum_drawdown"],
        "diagnosis": diagnosis,
        "archive_manifest_sha256": sha256_file(result_dir / "manifest.json"),
        "comparison_sha256": sha256_file(result_dir / "comparison.json"),
    }


def final_summary(result_dir: Path, *, source_local_run_id: str | None = None) -> dict:
    comparison = json.loads((result_dir / "comparison.json").read_text(encoding="utf-8"))
    manifest = json.loads((result_dir / "manifest.json").read_text(encoding="utf-8"))
    summary = {
        "status": comparison["status"],
        "run_id": manifest["run_id"],
        "backtest_id": manifest["joinquant"]["backtest_url"].split("=")[-1],
        "new_platform_run_required": manifest["joinquant"].get("new_platform_run_required", False),
        "candidate_overlap": comparison["mean_overlap"]["selected_candidates"],
        "holding_overlap": comparison["mean_overlap"]["holdings"],
        "order_symbol_overlap": comparison["mean_overlap"]["ordered_symbols"],
        "local_annualized_return": comparison["local_metrics"]["annualized_return"],
        "joinquant_annualized_return": comparison["joinquant_metrics"]["annualized_return"],
        "annualized_difference": comparison["differences"]["annualized_return"],
        "local_maximum_drawdown": comparison["local_metrics"]["maximum_drawdown"],
        "joinquant_maximum_drawdown": comparison["joinquant_metrics"]["maximum_drawdown"],
        "drawdown_difference": comparison["differences"]["maximum_drawdown"],
        "local_manifest_sha256": manifest["local_manifest_sha256"],
        "archive_manifest_sha256": sha256_file(result_dir / "manifest.json"),
        "comparison_sha256": sha256_file(result_dir / "comparison.json"),
    }
    if source_local_run_id:
        summary["source_local_run_id"] = source_local_run_id
    return summary


def main():
    report = verify_daily_backtester(ROOT, RESULT_DIR)
    report["joinquant_golden_v1"] = golden_summary(
        GOLDEN_V1_DIR,
        "JoinQuant rejected STAR Market market orders without a protection price",
    )
    report["joinquant_golden_v2"] = golden_summary(
        GOLDEN_V2_DIR,
        (
            "protection prices removed the STAR Market rejection and lifted holding "
            "overlap from 69.79% to 77.87%, but valuation selection and platform "
            "execution differences remain material"
        ),
    )
    report["joinquant_target_replay_v3"] = final_summary(
        TARGET_REPLAY_DIR,
        source_local_run_id="2026-07-29__monthly-small-cap__local-jq-target-replay-v2",
    )
    report["joinquant_autonomous_v4"] = final_summary(AUTONOMOUS_DIR)
    report["joinquant_autonomous_v4"]["diagnosis"] = (
        "估值日历和状态有效期语义修复后，自主选股、持仓、撮合与收益回撤全部严格过线"
    )
    final_checks = json.loads((AUTONOMOUS_DIR / "comparison.json").read_text(encoding="utf-8"))[
        "checks"
    ]
    report["checks"]["joinquant_autonomous_thresholds_passed"] = all(final_checks.values())
    report["iteration_status"] = "completed" if all(report["checks"].values()) else "in_progress"
    report["details"]["result_run_id"] = RESULT_DIR.name
    report["remaining"] = (
        []
        if report["iteration_status"] == "completed"
        else ["修复未通过的撮合器或自主黄金对照检查"]
    )
    report["limitations"] = [
        "最终严格结论使用本地点时自主选股，不以聚宽目标回放冒充自主复现。",
        "历史目标回放仅作为隔离撮合差异的中间证据保留。",
    ]
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["iteration_status"] != "completed":
        raise SystemExit(1)
    print(OUTPUT)


if __name__ == "__main__":
    main()
