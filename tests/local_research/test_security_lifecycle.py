import pandas as pd

from quant_research.data.security_lifecycle import (
    SecurityLifecycleSnapshot,
    enrich_security_lifecycle,
    sync_security_lifecycle_snapshot,
)
from quant_research.data.security_master import read_qlib_instruments
from quant_research.data.store import ResearchDataStore


def _snapshot():
    return SecurityLifecycleSnapshot(
        as_of="2026-07-27",
        source_files=[],
        tables={
            "current_a": pd.DataFrame([["600000", "浦发银行"]]),
            "sh_main": pd.DataFrame(
                [["600000", "浦发银行", "", "", "", "1999-11-10"]]
            ),
            "sh_star": pd.DataFrame(columns=range(6)),
            "sz_a": pd.DataFrame(
                [
                    ["主板", "001872", "招商港口", "2018-12-26"],
                    ["创业板", "302132", "中航成飞", "2010-08-27"],
                ]
            ),
            "bj_a": pd.DataFrame(
                [["920242", "建邦科技", "", "", "2020-07-27"]]
            ),
            "sh_delisted": pd.DataFrame(columns=range(4)),
            "sz_delisted": pd.DataFrame(
                [["000005", "ST星源", "1990-12-10", "2024-04-26"]]
            ),
        },
    )


def test_lifecycle_enrichment_uses_official_dates_and_code_migrations(tmp_path):
    source = tmp_path / "all.txt"
    source.write_text(
        "SH600000\t2000-01-04\t2026-07-23\n"
        "SZ000005\t2000-01-04\t2024-04-25\n"
        "SZ000022\t2000-01-04\t2018-12-20\n"
        "SZ300114\t2010-08-27\t2025-02-14\n"
        "BJ837242\t2020-07-27\t2025-09-30\n",
        encoding="utf-8",
    )
    frame = enrich_security_lifecycle(read_qlib_instruments(source), _snapshot())
    by_symbol = frame.set_index("symbol")

    assert by_symbol.loc["SH600000", "listing_date"] == pd.Timestamp("1999-11-10")
    assert by_symbol.loc["SH600000", "lifecycle_status"] == "active"
    assert by_symbol.loc["SZ000005", "delisting_date"] == pd.Timestamp("2024-04-26")
    assert by_symbol.loc["SZ000005", "lifecycle_quality"] == "A"
    assert by_symbol.loc["SZ000022", "canonical_symbol"] == "SZ001872"
    assert by_symbol.loc["SZ000022", "listing_date"] == pd.Timestamp("1993-05-05")
    assert by_symbol.loc["SZ300114", "canonical_symbol"] == "SZ302132"
    assert by_symbol.loc["BJ837242", "canonical_symbol"] == "BJ920242"
    assert set(frame["lifecycle_quality"]) <= {"A", "B"}


def test_lifecycle_snapshot_is_saved_as_immutable_raw_files(tmp_path):
    class Provider:
        def fetch(self):
            return _snapshot().tables

    store = ResearchDataStore(tmp_path / "data")
    snapshot = sync_security_lifecycle_snapshot(
        store,
        provider=Provider(),
        as_of="2026-07-27",
    )

    assert len(snapshot.source_files) == 7
    assert all(
        (store.root / item["path"]).is_file() for item in snapshot.source_files
    )
