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
    / "2026-07-28__monthly-small-cap__local-preflight-v5"
)
OUTPUT = ROOT / "docs" / "local-research" / "daily-backtester-verification.json"
GOLDEN_DIR = (
    ROOT
    / "studies"
    / "joinquant-small-cap-golden-comparison"
    / "results"
    / "2026-07-28__monthly-small-cap__joinquant-golden-v1"
)


def main():
    report = verify_daily_backtester(ROOT, RESULT_DIR)
    comparison = json.loads(
        (GOLDEN_DIR / "comparison.json").read_text(encoding="utf-8")
    )
    golden_manifest = json.loads(
        (GOLDEN_DIR / "manifest.json").read_text(encoding="utf-8")
    )
    report["joinquant_golden_v1"] = {
        "status": comparison["status"],
        "run_id": golden_manifest["run_id"],
        "backtest_id": golden_manifest["joinquant"]["backtest_url"].split("=")[-1],
        "initial_cash": golden_manifest["joinquant"]["initial_cash"],
        "candidate_dates": comparison["joinquant_candidate_dates"],
        "holding_dates": comparison["joinquant_holding_dates"],
        "candidate_overlap": comparison["mean_overlap"]["selected_candidates"],
        "holding_overlap": comparison["mean_overlap"]["holdings"],
        "order_symbol_overlap": comparison["mean_overlap"]["ordered_symbols"],
        "annualized_return": comparison["joinquant_metrics"]["annualized_return"],
        "maximum_drawdown": comparison["joinquant_metrics"]["maximum_drawdown"],
        "annualized_difference": comparison["differences"]["annualized_return"],
        "drawdown_difference": comparison["differences"]["maximum_drawdown"],
        "diagnosis": (
            "JoinQuant rejected STAR Market market orders without a protection price; "
            "corrected source requires a new immutable v2 run"
        ),
        "archive_manifest_sha256": sha256_file(GOLDEN_DIR / "manifest.json"),
        "comparison_sha256": sha256_file(GOLDEN_DIR / "comparison.json"),
    }
    report["remaining"] = [
        "rerun the corrected JoinQuant strategy with STAR Market protection prices "
        "and compact monthly order logs",
        "import the new immutable v2 run with all 54 candidate/holding logs and "
        "aggregate stats",
        "pass >=80% candidate and holding overlap",
        "pass <=3 percentage-point annualized and drawdown differences",
    ]
    OUTPUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if report["local_preflight_status"] != "passed":
        raise SystemExit(1)
    print(OUTPUT)


if __name__ == "__main__":
    main()
