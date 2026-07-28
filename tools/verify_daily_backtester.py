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


def golden_summary(result_dir: Path, diagnosis: str) -> dict:
    comparison = json.loads(
        (result_dir / "comparison.json").read_text(encoding="utf-8")
    )
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
    report["remaining"] = [
        "align point-in-time market-cap selection and platform execution semantics",
        "explain the remaining 73 platform order errors and persistent suspended holdings",
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
