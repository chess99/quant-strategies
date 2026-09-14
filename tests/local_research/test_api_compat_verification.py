from pathlib import Path

from quant_research.api_compat_verification import _sha256, build_api_compat_verification


def test_committed_api_compat_evidence_is_self_consistent():
    root = Path(__file__).resolve().parents[2]

    report = build_api_compat_verification(root)

    assert report["status"] == "passed"
    assert report["coverage"]["direct_coverage_ratio"] >= 0.85
    assert all(report["checks"].values())


def test_text_evidence_hash_is_stable_across_checkout_line_endings(tmp_path):
    lf = tmp_path / "lf.json"
    crlf = tmp_path / "crlf.json"
    lf.write_bytes(b'{"status": "passed"}\n')
    crlf.write_bytes(b'{"status": "passed"}\r\n')

    assert _sha256(lf) == _sha256(crlf)
