import pandas as pd
import pytest

from quant_research.data.contracts import DatasetManifest, QualityGrade
from quant_research.data.security_master import (
    normalize_symbol,
    read_qlib_instruments,
    to_joinquant_symbol,
    validate_security_master,
)
from quant_research.data.store import ResearchDataStore, sha256_file


def test_quality_grades_are_ordered_and_choose_worst():
    assert QualityGrade.A.meets(QualityGrade.B)
    assert QualityGrade.B.meets("B")
    assert not QualityGrade.C.meets(QualityGrade.B)
    assert QualityGrade.worst([QualityGrade.A, "B", QualityGrade.A]) is QualityGrade.B


def test_symbol_normalization_is_shared_across_asset_types():
    assert normalize_symbol("sh600000") == "SH600000"
    assert normalize_symbol("510300.XSHG") == "SH510300"
    assert normalize_symbol("159915.XSHE") == "SZ159915"
    assert normalize_symbol("430017.XBSE") == "BJ430017"
    assert to_joinquant_symbol("SH510300") == "510300.XSHG"
    with pytest.raises(ValueError, match="unsupported"):
        normalize_symbol("600000")


def test_qlib_security_master_preserves_ended_securities(tmp_path):
    source = tmp_path / "all.txt"
    source.write_text(
        "SH600000\t2000-01-01\t2026-07-23\n"
        "SZ300001\t2009-10-30\t2024-01-15\n"
        "SH000300\t2005-01-04\t2026-07-23\n",
        encoding="utf-8",
    )

    frame = read_qlib_instruments(source)

    assert frame["symbol"].tolist() == ["SH000300", "SH600000", "SZ300001"]
    ended = frame.set_index("symbol").loc["SZ300001"]
    assert ended["end_date"] == pd.Timestamp("2024-01-15")
    assert ended["delisting_date"] == pd.Timestamp("2024-01-15")
    assert not ended["active_at_source_end"]
    assert ended["board"] == "chinext"
    assert frame.set_index("symbol").loc["SH600000", "active_at_source_end"]
    assert frame.set_index("symbol").loc["SH000300", "asset_type"] == "index"


def test_security_master_rejects_duplicate_symbols(tmp_path):
    source = tmp_path / "all.txt"
    source.write_text(
        "SH600000\t2000-01-01\t2026-07-23\n"
        "SH600000\t2001-01-01\t2026-07-23\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unique"):
        read_qlib_instruments(source)


def test_store_writes_parquet_and_hash_bound_manifest(tmp_path):
    store = ResearchDataStore(tmp_path / "data")
    frame = pd.DataFrame(
        {
            "symbol": ["SH600000"],
            "start_date": [pd.Timestamp("2000-01-01")],
        }
    )
    data_file = store.write_parquet("example", frame)
    manifest = DatasetManifest(
        schema_version=1,
        dataset="example",
        provider="fixture",
        quality_grade=QualityGrade.A,
        row_count=1,
        columns=list(frame.columns),
        data_files=[data_file],
    )
    store.write_manifest(manifest)

    restored = store.read_parquet("example")
    payload = store.read_manifest("example")
    path = store.root / payload["data_files"][0]["path"]
    assert restored.loc[0, "symbol"] == "SH600000"
    assert payload["quality_grade"] == "A"
    assert payload["data_files"][0]["sha256"] == sha256_file(path)


def test_security_master_validation_rejects_inverted_dates():
    frame = pd.DataFrame(
        [
            {
                "symbol": "SH600000",
                "exchange": "XSHG",
                "asset_type": "stock",
                "board": "main",
                "start_date": pd.Timestamp("2024-02-01"),
                "end_date": pd.Timestamp("2024-01-01"),
                "listing_date": pd.Timestamp("2024-02-01"),
                "delisting_date": pd.Timestamp("2024-01-01"),
                "active_at_source_end": False,
                "canonical_symbol": "SH600000",
                "lifecycle_status": "delisted",
                "lifecycle_quality": "B",
                "lifecycle_source": "fixture",
                "display_name": None,
                "quality_grade": "B",
                "source": "fixture",
            }
        ]
    )
    with pytest.raises(ValueError, match="later"):
        validate_security_master(frame)
