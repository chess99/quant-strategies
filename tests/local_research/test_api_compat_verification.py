from pathlib import Path

from quant_research.api_compat_verification import build_api_compat_verification


def test_committed_api_compat_evidence_is_self_consistent():
    root = Path(__file__).resolve().parents[2]

    report = build_api_compat_verification(root)

    assert report["status"] == "passed"
    assert report["coverage"]["direct_coverage_ratio"] >= 0.85
    assert all(report["checks"].values())
