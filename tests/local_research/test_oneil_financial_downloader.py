import importlib.util
import sys
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[2] / "tools" / "download_oneil_financials.py"
SPEC = importlib.util.spec_from_file_location("oneil_financial_downloader", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_select_all_a_universe_excludes_indices_etfs_and_out_of_range_securities():
    master = pd.DataFrame(
        {
            "symbol": [
                "SH600000",
                "SZ300001",
                "SH688001",
                "BJ920001",
                "SH000300",
                "SH510300",
                "SZ000002",
            ],
            "asset_type": ["stock", "stock", "stock", "stock", "stock", "etf", "stock"],
            "board": ["main", "chinext", "star", "beijing", "index", "fund", "main"],
            "start_date": pd.to_datetime(
                [
                    "1999-11-10",
                    "2010-01-01",
                    "2019-07-22",
                    "2021-11-15",
                    "2005-04-08",
                    "2012-05-28",
                    "1991-01-29",
                ]
            ),
            "end_date": pd.to_datetime(
                [
                    "2026-07-24",
                    "2026-07-24",
                    "2026-07-24",
                    "2026-07-24",
                    "2026-07-24",
                    "2026-07-24",
                    "2009-12-31",
                ]
            ),
        }
    )

    result = MODULE.select_all_a_universe(master, "2010-01-01", "2025-12-31")

    assert result == ["BJ920001", "SH600000", "SH688001", "SZ300001"]


def test_load_or_fetch_symbol_uses_seed_cache_without_network(tmp_path, monkeypatch):
    import gzip
    import json

    seed = tmp_path / "seed"
    output = tmp_path / "output"
    seed.mkdir()
    payload = [{"REPORT_DATE": "2024-12-31", "NOTICE_DATE": "2025-03-01"}]
    with gzip.open(seed / "sh600000.json.gz", "wt", encoding="utf-8") as handle:
        json.dump(payload, handle)

    def fail_fetch(_):
        raise AssertionError("network should not be used when the seed cache has the symbol")

    monkeypatch.setattr(MODULE, "fetch_symbol", fail_fetch)
    output.mkdir()

    symbol, rows, cache_source = MODULE.load_or_fetch_symbol(
        "SH600000", output, object(), seed_raw_dirs=(seed,)
    )

    assert symbol == "SH600000"
    assert rows == payload
    assert cache_source == "seed"
    assert not (output / "sh600000.json.gz").exists()
