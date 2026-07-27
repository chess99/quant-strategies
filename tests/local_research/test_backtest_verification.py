from pathlib import Path

from quant_research.backtest_verification import verify_daily_backtester


ROOT = Path(__file__).resolve().parents[2]
RESULT_DIR = (
    ROOT
    / "studies"
    / "joinquant-small-cap-golden-comparison"
    / "results"
    / "2026-07-27__monthly-small-cap__local-preflight-v4"
)


def test_iteration_five_local_preflight_machine_verification_passes():
    report = verify_daily_backtester(ROOT, RESULT_DIR)

    assert report["local_preflight_status"] == "passed"
    assert report["iteration_status"] == "in_progress"
    assert all(report["checks"].values())
