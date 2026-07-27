import json

import pandas as pd

from quant_research.data.store import ResearchDataStore
from quant_research.full_market import (
    build_asof_cross_sections,
    build_exact_cross_sections,
    build_fundamental_cross_sections,
    build_interval_cross_sections,
)


def make_partitioned_dataset(tmp_path):
    store = ResearchDataStore(tmp_path)
    frame = pd.DataFrame(
        {
            "symbol": ["SH600000", "SH600000", "SZ000001"],
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-05", "2024-01-03"]),
            "value": [1.0, 2.0, 3.0],
        }
    )
    files = store.write_partitioned_parquet("example", frame, ["symbol"], filename="data.parquet")
    manifest = {
        "dataset": "example",
        "quality_grade": "B",
        "columns": list(frame.columns),
        "partitioning": {"style": "hive", "columns": ["symbol"]},
        "data_files": files,
    }
    store.manifest_path("example").write_text(json.dumps(manifest), encoding="utf-8")
    return store


def test_asof_cross_sections_use_only_data_visible_at_observation_date(tmp_path):
    store = make_partitioned_dataset(tmp_path)

    result = build_asof_cross_sections(
        store,
        "example",
        ["2024-01-04", "2024-01-05"],
        ["value"],
        maximum_age_days=2,
    )

    rows = result.frame.set_index(["observation_date", "symbol"])
    assert rows.loc[(pd.Timestamp("2024-01-04"), "SH600000"), "value"] == 1.0
    assert rows.loc[(pd.Timestamp("2024-01-05"), "SH600000"), "value"] == 2.0
    assert rows.loc[(pd.Timestamp("2024-01-04"), "SZ000001"), "value"] == 3.0
    assert result.audit["quality_grade"] == "B"
    assert result.audit["failed_symbols"] == []


def test_exact_cross_sections_do_not_backfill_missing_dates(tmp_path):
    store = make_partitioned_dataset(tmp_path)

    result = build_exact_cross_sections(
        store,
        "example",
        ["2024-01-02", "2024-01-03"],
        ["value"],
    )

    assert len(result.frame) == 2
    assert set(result.frame["observation_date"]) == {
        pd.Timestamp("2024-01-02"),
        pd.Timestamp("2024-01-03"),
    }


def test_fundamental_cross_sections_choose_latest_report_visible_by_notice(tmp_path):
    store = ResearchDataStore(tmp_path)
    frame = pd.DataFrame(
        {
            "symbol": ["SH600000"] * 3,
            "report_date": pd.to_datetime(["2023-09-30", "2023-12-31", "2023-09-30"]),
            "notice_date": pd.to_datetime(["2023-10-30", "2024-03-30", "2024-04-10"]),
            "profit": [9.0, 12.0, 10.0],
            "is_annual": [False, True, False],
        }
    )
    files = store.write_partitioned_parquet("fundamentals", frame, ["symbol"])
    store.manifest_path("fundamentals").write_text(
        json.dumps(
            {
                "dataset": "fundamentals",
                "quality_grade": "B",
                "columns": list(frame.columns),
                "partitioning": {"columns": ["symbol"]},
                "data_files": files,
            }
        ),
        encoding="utf-8",
    )

    result = build_fundamental_cross_sections(
        store, "fundamentals", ["2024-03-01", "2024-04-20"], ["profit"]
    )

    rows = result.frame.set_index("observation_date")
    assert rows.loc[pd.Timestamp("2024-03-01"), "profit"] == 9.0
    assert rows.loc[pd.Timestamp("2024-04-20"), "profit"] == 12.0
    assert result.audit["future_notice_rows"] == 0
    annual = build_fundamental_cross_sections(
        store,
        "fundamentals",
        ["2024-04-20"],
        ["profit"],
        annual_only=True,
    )
    assert annual.frame.iloc[0]["profit"] == 12.0


def test_interval_cross_sections_never_use_future_industry_change(tmp_path):
    store = ResearchDataStore(tmp_path)
    frame = pd.DataFrame(
        {
            "symbol": ["SH600000", "SH600000"],
            "classification": ["sw_l1", "sw_l1"],
            "industry_code": ["480000", "490000"],
            "start_date": pd.to_datetime(["2020-01-01", "2024-01-01"]),
            "end_date": pd.to_datetime(["2023-12-31", "2099-12-31"]),
        }
    )
    files = store.write_partitioned_parquet("industry", frame, ["symbol"])
    store.manifest_path("industry").write_text(
        json.dumps(
            {
                "dataset": "industry",
                "quality_grade": "B",
                "columns": list(frame.columns),
                "partitioning": {"columns": ["symbol"]},
                "data_files": files,
            }
        ),
        encoding="utf-8",
    )

    result = build_interval_cross_sections(
        store,
        "industry",
        ["2023-12-29", "2024-01-02"],
        ["classification", "industry_code"],
    )

    assert result.frame["industry_code"].tolist() == ["480000", "490000"]
    assert result.audit["future_interval_rows"] == 0
