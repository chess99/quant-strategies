from pathlib import Path

import numpy as np
import pandas as pd

from quant_research.data.market_verification import build_market_state_crosscheck
from quant_research.data.store import ResearchDataStore


def _write_qlib_feature(
    qlib_root: Path,
    symbol: str,
    field: str,
    values: list[float],
) -> None:
    directory = qlib_root / "features" / symbol.lower()
    directory.mkdir(parents=True, exist_ok=True)
    np.asarray([0.0, *values], dtype="<f4").tofile(directory / f"{field}.day.bin")


def _write_symbol_features(
    qlib_root: Path,
    symbol: str,
    *,
    prices: list[float],
    volumes: list[float],
) -> None:
    for field in ("open", "high", "low", "close"):
        _write_qlib_feature(qlib_root, symbol, field, prices)
    _write_qlib_feature(qlib_root, symbol, "volume", volumes)
    _write_qlib_feature(qlib_root, symbol, "factor", [1.0] * len(prices))


def test_market_state_crosscheck_uses_independent_status_limits_and_qlib(tmp_path):
    store = ResearchDataStore(tmp_path / "store")
    qlib_root = tmp_path / "qlib"
    calendar = pd.DatetimeIndex(["2024-01-02", "2024-01-03", "2024-01-04"])
    (qlib_root / "calendars").mkdir(parents=True)
    (qlib_root / "calendars" / "day.txt").write_text(
        "\n".join(date.strftime("%Y-%m-%d") for date in calendar) + "\n",
        encoding="utf-8",
    )
    _write_symbol_features(
        qlib_root,
        "SH600000",
        prices=[10.0, np.nan, 11.0],
        volumes=[100.0, 0.0, 100.0],
    )
    _write_symbol_features(
        qlib_root,
        "SZ300001",
        prices=[18.0, 20.0, 20.0],
        volumes=[100.0, 100.0, 100.0],
    )
    store.write_parquet(
        "security_master",
        pd.DataFrame(
            {
                "symbol": ["SH600000", "SZ300001"],
                "asset_type": ["stock", "stock"],
                "board": ["main", "chinext"],
            }
        ),
    )
    store.write_parquet(
        "daily_official_status",
        pd.DataFrame(
            {
                "symbol": ["SH600000"] * 3,
                "trade_date": calendar,
                "paused": [False, True, False],
                "is_st": [False, False, False],
            }
        ),
        filename="symbol=SH600000/data.parquet",
    )
    store.write_parquet(
        "daily_official_status",
        pd.DataFrame(
            {
                "symbol": ["SZ300001"] * 3,
                "trade_date": calendar,
                "paused": [False, False, False],
                "is_st": [False, False, False],
            }
        ),
        filename="symbol=SZ300001/data.parquet",
    )
    store.write_parquet(
        "daily_price_limit",
        pd.DataFrame(
            {
                "symbol": ["SH600000", "SH600000"],
                "trade_date": [calendar[0], calendar[2]],
                "high_limit": [11.0, 11.0],
                "low_limit": [9.0, 9.0],
                "is_st": [False, False],
            }
        ),
        filename="symbol=SH600000/data.parquet",
    )
    store.write_parquet(
        "daily_price_limit",
        pd.DataFrame(
            {
                "symbol": ["SZ300001", "SZ300001", "SZ300001"],
                "trade_date": calendar,
                "high_limit": [22.0, 22.0, 22.0],
                "low_limit": [18.0, 18.0, 18.0],
                "is_st": [False, False, False],
            }
        ),
        filename="symbol=SZ300001/data.parquet",
    )
    store.write_json_report("daily_official_status", {"provider": "baostock"})
    store.write_json_report("daily_price_limit", {"provider": "dolt"})

    report = build_market_state_crosscheck(
        store,
        qlib_root=qlib_root,
        symbols=["SH600000", "SZ300001"],
        minimum_paused_agreement=1.0,
        minimum_st_agreement=1.0,
        minimum_limit_bound_agreement=1.0,
    )

    assert report["status"] == "passed"
    assert report["scope"]["symbols_checked"] == 2
    assert report["scope"]["boards"] == {"chinext": 1, "main": 1}
    assert report["comparisons"]["paused"]["agreement_ratio"] == 1.0
    assert report["comparisons"]["st"]["agreement_ratio"] == 1.0
    assert report["comparisons"]["price_bounds"]["agreement_ratio"] == 1.0
    assert report["comparisons"]["one_price_limit"]["event_rows"] == 2
    assert report["comparisons"]["buy_blocked"]["event_rows"] == 1
    assert report["comparisons"]["sell_blocked"]["event_rows"] == 1
    assert all(report["checks"].values())
