import json

import pandas as pd

from quant_research.data.store import ResearchDataStore
from quant_research.full_market import build_asof_cross_sections, build_exact_cross_sections


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
