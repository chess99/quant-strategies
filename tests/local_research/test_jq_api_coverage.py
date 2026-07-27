from pathlib import Path

from quant_research.jq_api_audit import audit_joinquant_api_usage


def test_api_audit_classifies_supported_and_migration_required_forms(tmp_path):
    source = tmp_path / "strategy.py"
    source.write_text(
        """
get_price('000300.XSHG', end_date=d, count=20, fields=['close'], panel=False)
history(10, '1d', 'close', ['510300.XSHG'])
get_fundamentals(query(valuation.code), date=d)
get_ticks('000001.XSHE')
""",
        encoding="utf-8",
    )

    report = audit_joinquant_api_usage(tmp_path)

    assert report["files"]["parsed"] == 1
    assert report["target_calls"] == 3
    assert report["classification_counts"] == {
        "supported": 2,
        "migration_required": 1,
    }
    assert report["apis"]["get_fundamentals"]["migration_required_calls"] == 1
    assert report["unsupported_api_calls"]["get_ticks"] == 1


def test_api_audit_records_syntax_errors_without_stopping(tmp_path):
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    report = audit_joinquant_api_usage(Path(tmp_path))

    assert report["files"]["syntax_errors"] == 1
    assert report["syntax_errors"][0]["path"] == "broken.py"
