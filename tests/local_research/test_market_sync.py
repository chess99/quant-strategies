from pathlib import Path

import numpy as np
import pandas as pd

from quant_research.data.market_reference import (
    classify_risk_warning_title,
    normalize_risk_warning_events,
)
from quant_research.data.market_sync import (
    build_risk_warning_baselines,
    build_official_status_partitions,
    build_price_limit_partitions,
    read_qlib_symbol_features,
)
from quant_research.data.store import ResearchDataStore


def test_price_limit_csv_is_partitioned_without_splitting_symbols(tmp_path):
    raw_path = tmp_path / "limits.csv"
    pd.DataFrame(
        {
            "tradedate": [
                "2024-01-02",
                "2024-01-03",
                "2024-01-02",
                "2024-01-03",
            ],
            "symbol": ["SH600000", "SH600000", "SZ000001", "SZ000001"],
            "pre_close": [10.0, 10.5, 20.0, 20.1],
            "up_limit": [10.5, 11.03, 22.0, 22.11],
            "down_limit": [9.5, 9.98, 18.0, 18.09],
        }
    ).to_csv(raw_path, index=False)
    store = ResearchDataStore(tmp_path / "store")
    store.write_parquet(
        "security_master",
        pd.DataFrame(
            {
                "symbol": ["SH600000", "SZ000001"],
                "asset_type": ["stock", "stock"],
            }
        ),
    )

    manifest = build_price_limit_partitions(
        store,
        raw_path,
        commit="abc123",
        chunk_rows=3,
    )

    assert manifest.row_count == 4
    assert manifest.coverage["symbols"] == 2
    assert len(manifest.data_files) == 2
    sh = store.read_symbol_partitions("daily_price_limit", ["SH600000"])
    assert len(sh) == 2
    assert sh["trade_date"].is_monotonic_increasing


def test_baostock_status_csv_is_partitioned(tmp_path):
    raw_path = tmp_path / "status.csv"
    pd.DataFrame(
        {
            "tradedate": ["2023-01-03", "2023-01-04"],
            "symbol": ["SH688001", "SH688001"],
            "tradestatus": [1, 0],
            "is_st": [1, 1],
        }
    ).to_csv(raw_path, index=False)
    store = ResearchDataStore(tmp_path / "store")
    store.write_parquet(
        "security_master",
        pd.DataFrame(
            {
                "symbol": ["SH688001"],
                "asset_type": ["stock"],
                "listing_date": [pd.Timestamp("2020-01-01")],
                "delisting_date": [pd.NaT],
            }
        ),
    )

    manifest = build_official_status_partitions(
        store,
        raw_path,
        commit="abc123",
        chunk_rows=1,
    )

    assert manifest.row_count == 2
    assert manifest.coverage["st_rows"] == 2
    assert manifest.coverage["paused_rows"] == 1


def _write_feature(directory: Path, field: str, values: list[float]) -> None:
    payload = np.asarray([1.0, *values], dtype="<f4")
    payload.tofile(directory / f"{field}.day.bin")


def test_qlib_symbol_reader_uses_binary_calendar_offset(tmp_path):
    directory = tmp_path / "features" / "sh600000"
    directory.mkdir(parents=True)
    for field in ("open", "high", "low", "close", "volume", "factor"):
        _write_feature(directory, field, [1.0, 2.0])
    calendar = pd.date_range("2024-01-01", periods=4, freq="D")

    frame = read_qlib_symbol_features(tmp_path, "SH600000", calendar)

    assert frame["trade_date"].tolist() == [
        pd.Timestamp("2024-01-02"),
        pd.Timestamp("2024-01-03"),
    ]
    assert frame["symbol"].tolist() == ["SH600000", "SH600000"]


def test_risk_warning_title_classifier_rejects_forecasts_and_applications():
    assert classify_risk_warning_title("关于公司股票可能被实施退市风险警示的公告") is None
    assert classify_risk_warning_title("关于申请撤销其他风险警示的公告") is None
    assert (
        classify_risk_warning_title(
            "关于公司股票被实施退市风险警示暨停牌的公告"
        )
        is True
    )
    assert classify_risk_warning_title("关于撤销退市风险警示的公告") is False
    assert (
        classify_risk_warning_title(
            "关于撤销退市风险警示并继续实施其他风险警示的公告"
        )
        is True
    )


def test_risk_warning_events_start_after_baseline_and_use_next_session():
    master = pd.DataFrame(
        {
            "symbol": ["SH600234"],
            "asset_type": ["stock"],
        }
    )
    notices = pd.DataFrame(
        {
            "stock_code": ["600234", "600234", "600234"],
            "notice_date": ["2023-06-08", "2024-04-29", "2025-05-17"],
            "title": [
                "关于公司股票被实施其他风险警示的公告",
                "关于股票被实施退市风险警示暨停牌的公告",
                "关于撤销退市风险警示的公告",
            ],
            "art_code": ["old", "on", "off"],
        }
    )
    baselines = pd.DataFrame(
        {
            "symbol": ["SH600234"],
            "effective_from": [pd.Timestamp("2023-06-12")],
            "is_st": [False],
            "st_quality": ["B"],
            "st_source": ["baseline"],
        }
    )
    calendar = pd.DatetimeIndex(
        ["2023-06-09", "2023-06-12", "2024-04-29", "2024-04-30", "2025-05-19"]
    )

    events = normalize_risk_warning_events(
        notices,
        master,
        calendar,
        baselines=baselines,
    )

    assert events["effective_from"].tolist() == [
        pd.Timestamp("2023-06-12"),
        pd.Timestamp("2024-04-30"),
        pd.Timestamp("2025-05-19"),
    ]
    assert events["is_st"].astype(bool).tolist() == [False, True, False]
    assert events["evidence_art_code"].tolist() == [None, "on", "off"]


def test_risk_warning_baselines_carry_official_status_and_seed_new_listing(tmp_path):
    store = ResearchDataStore(tmp_path / "store")
    store.write_parquet(
        "daily_official_status",
        pd.DataFrame(
            {
                "symbol": ["SH600000", "SH600000"],
                "trade_date": pd.to_datetime(["2023-06-08", "2023-06-09"]),
                "paused": [False, False],
                "is_st": [False, True],
                "status_quality": ["B", "B"],
                "st_quality": ["B", "B"],
                "status_source": ["source", "source"],
                "st_source": ["source", "source"],
            }
        ),
        filename="symbol=SH600000/data.parquet",
    )
    master = pd.DataFrame(
        {
            "symbol": ["SH600000", "BJ430001"],
            "asset_type": ["stock", "stock"],
            "listing_date": pd.to_datetime(["1999-11-10", "2023-06-15"]),
        }
    )
    calendar = pd.DatetimeIndex(
        ["2023-06-09", "2023-06-12", "2023-06-15", "2023-06-16"]
    )

    baselines = build_risk_warning_baselines(
        store,
        master,
        calendar,
        official_symbols={"SH600000"},
    )

    sh = baselines[baselines["symbol"] == "SH600000"].iloc[0]
    bj = baselines[baselines["symbol"] == "BJ430001"].iloc[0]
    assert sh["effective_from"] == pd.Timestamp("2023-06-12")
    assert bool(sh["is_st"]) is True
    assert bj["effective_from"] == pd.Timestamp("2023-06-15")
    assert bool(bj["is_st"]) is False
