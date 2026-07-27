import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_research.data.audit import (
    audit_normalized_dataset,
    audit_qlib_daily_features,
)
from quant_research.data.calendar import (
    build_trading_calendar,
    read_qlib_calendar,
)
from quant_research.data.contracts import (
    DataQualityError,
    DatasetManifest,
    QualityGrade,
    require_quality,
)
from quant_research.data.store import ResearchDataStore


def _write_feature(directory: Path, field: str, values, start_index=0):
    directory.mkdir(parents=True, exist_ok=True)
    payload = np.asarray([start_index, *values], dtype="<f4")
    payload.tofile(directory / f"{field}.day.bin")


def test_calendar_build_preserves_order_and_hashes_source(tmp_path):
    source = tmp_path / "day.txt"
    source.write_text("2024-01-02\n2024-01-03\n2024-01-05\n", encoding="utf-8")
    store = ResearchDataStore(tmp_path / "data")

    frame, manifest = build_trading_calendar(source, store)

    assert frame["session_index"].tolist() == [0, 1, 2]
    assert frame["trade_date"].tolist() == list(
        pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-05"])
    )
    assert manifest.primary_key == ["trade_date"]
    assert manifest.date_fields == {"trade_date": "交易所开放日"}
    assert store.read_manifest("trading_calendar")["source_files"][0]["sha256"]


@pytest.mark.parametrize(
    "payload, message",
    [
        ("2024-01-02\n2024-01-02\n", "unique"),
        ("2024-01-03\n2024-01-02\n", "increasing"),
    ],
)
def test_calendar_rejects_duplicate_or_reversed_dates(tmp_path, payload, message):
    source = tmp_path / "day.txt"
    source.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        read_qlib_calendar(source)


def test_quality_gate_rejects_dataset_below_strategy_requirement():
    require_quality("fixture", QualityGrade.B, QualityGrade.B)
    with pytest.raises(DataQualityError, match="fixture"):
        require_quality("fixture", QualityGrade.C, QualityGrade.B)


def test_partitioned_parquet_records_partition_values(tmp_path):
    store = ResearchDataStore(tmp_path / "data")
    frame = pd.DataFrame(
        {
            "symbol": ["SH600000", "SH600000"],
            "trade_date": pd.to_datetime(["2023-01-03", "2024-01-02"]),
            "year": [2023, 2024],
            "close": [10.0, 11.0],
        }
    )

    files = store.write_partitioned_parquet(
        "prices",
        frame,
        partition_columns=["year"],
    )

    assert [item["partition_values"] for item in files] == [
        {"year": 2023},
        {"year": 2024},
    ]
    assert files[0]["path"].startswith("normalized/prices/year=2023/")


def test_qlib_feature_audit_streams_symbols_and_reports_findings(tmp_path):
    qlib_root = tmp_path / "qlib"
    feature_root = qlib_root / "features"
    calendar_path = qlib_root / "calendars" / "day.txt"
    calendar_path.parent.mkdir(parents=True)
    calendar_path.write_text(
        "2024-01-02\n2024-01-03\n2024-01-04\n", encoding="utf-8"
    )
    values = {
        "open": [1.0, 1.1, 1.2],
        "high": [1.1, 1.2, 1.3],
        "low": [0.9, 1.0, 1.1],
        "close": [1.0, 1.1, 1.2],
        "factor": [1.0, 1.0, 1.0],
        "change": [np.nan, 0.1, 0.09],
        "volume": [100.0, 120.0, 130.0],
        "amount": [1000.0, 1320.0, 1560.0],
    }
    for field, field_values in values.items():
        _write_feature(feature_root / "sh600000", field, field_values)
    for field, field_values in values.items():
        _write_feature(feature_root / "sh999999", field, field_values)

    master = pd.DataFrame(
        {
            "symbol": ["SH600000"],
            "start_date": [pd.Timestamp("2024-01-02")],
            "end_date": [pd.Timestamp("2024-01-04")],
        }
    )
    report = audit_qlib_daily_features(qlib_root, master)

    assert report["expected_instruments"] == 1
    assert report["successful_instruments"] == 1
    assert report["failed_instruments"] == 0
    assert report["unknown_feature_symbols"] == ["SH999999"]
    assert report["total_finite_close_observations"] == 3
    assert report["checks"]["ohlc_violation_count"] == 0


def test_normalized_dataset_audit_detects_duplicate_and_unknown_symbol(tmp_path):
    store = ResearchDataStore(tmp_path / "data")
    frame = pd.DataFrame(
        {
            "symbol": ["SH600000", "SH600000", "SH999999"],
            "trade_date": pd.to_datetime(
                ["2024-01-02", "2024-01-02", "2024-01-03"]
            ),
            "close": [10.0, 10.0, 11.0],
        }
    )
    data_file = store.write_parquet("fixture_daily", frame)
    manifest = DatasetManifest(
        schema_version=2,
        dataset="fixture_daily",
        provider="fixture",
        quality_grade=QualityGrade.B,
        row_count=3,
        columns=list(frame.columns),
        data_files=[data_file],
        primary_key=["symbol", "trade_date"],
        date_fields={"trade_date": "交易日"},
    )
    store.write_manifest(manifest)
    master = pd.DataFrame(
        {
            "symbol": ["SH600000"],
            "start_date": [pd.Timestamp("2024-01-01")],
            "end_date": [pd.Timestamp("2024-12-31")],
        }
    )

    report = audit_normalized_dataset(store, "fixture_daily", master)

    assert report["row_count"]["actual"] == 3
    assert report["duplicate_primary_keys"] == 1
    assert report["unknown_symbols"] == ["SH999999"]
    assert report["primary_key_sorted"] is True
    assert report["symbol_coverage"]["covered_symbols"] == 1
    assert report["symbol_coverage"]["coverage_ratio"] == 1.0
    assert report["status"] == "failed"
    json.dumps(report)


def test_candidate_dataset_can_report_unverified_symbols_without_passing_as_known(
    tmp_path,
):
    store = ResearchDataStore(tmp_path / "data")
    frame = pd.DataFrame({"symbol": ["SH510300", "SH599999"]})
    data_file = store.write_parquet("etf_candidates", frame)
    manifest = DatasetManifest(
        schema_version=1,
        dataset="etf_candidates",
        provider="fixture",
        quality_grade=QualityGrade.B,
        row_count=2,
        columns=list(frame.columns),
        data_files=[data_file],
        primary_key=["symbol"],
        checks={"allows_unverified_candidates": True},
    )
    store.write_manifest(manifest)
    master = pd.DataFrame(
        {
            "symbol": ["SH510300"],
            "asset_type": ["etf"],
            "start_date": [pd.Timestamp("2024-01-01")],
            "end_date": [pd.Timestamp("2024-12-31")],
        }
    )

    report = audit_normalized_dataset(store, "etf_candidates", master)

    assert report["unknown_symbols"] == ["SH599999"]
    assert report["unknown_symbols_permitted"] == ["SH599999"]
    assert report["status"] == "passed"
