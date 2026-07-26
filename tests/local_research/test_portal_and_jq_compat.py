import pandas as pd
import pytest

from quant_research.data.contracts import DatasetManifest, QualityGrade
from quant_research.data.store import ResearchDataStore
from quant_research.jq_compat import JoinQuantCompat
from quant_research.portal import (
    DataQualityError,
    FrameDailyBarSource,
    LocalDataPortal,
    PointInTimeError,
)


def save_dataset(store, name, frame, quality):
    data_file = store.write_parquet(name, frame)
    store.write_manifest(
        DatasetManifest(
            schema_version=1,
            dataset=name,
            provider="test",
            quality_grade=QualityGrade(quality),
            row_count=len(frame),
            columns=list(frame.columns),
            data_files=[data_file],
        )
    )


@pytest.fixture
def portal(tmp_path):
    store = ResearchDataStore(tmp_path)
    master = pd.DataFrame(
        {
            "symbol": ["SH600000", "SZ000001"],
            "exchange": ["XSHG", "XSHE"],
            "asset_type": ["stock", "stock"],
            "board": ["main", "main"],
            "start_date": pd.to_datetime(["2000-01-01", "2000-01-01"]),
            "end_date": pd.to_datetime(["2030-01-01", "2030-01-01"]),
            "display_name": ["浦发银行", "平安银行"],
            "quality_grade": ["B", "B"],
            "source": ["test", "test"],
        }
    )
    save_dataset(store, "security_master", master, "B")
    membership = pd.DataFrame(
        {
            "index_symbol": ["SH000300", "SH000300"],
            "symbol": ["SH600000", "SZ000001"],
            "start_date": pd.to_datetime(["2020-01-01", "2024-01-03"]),
            "end_date": pd.to_datetime(["2030-01-01", "2030-01-01"]),
        }
    )
    save_dataset(store, "index_membership", membership, "B")
    state = pd.DataFrame(
        {
            "symbol": ["SH600000"],
            "trade_date": pd.to_datetime(["2024-01-03"]),
            "paused": [False],
            "is_st": pd.array([pd.NA], dtype="boolean"),
            "raw_close": [10.2],
            "high_limit": [11.0],
            "low_limit": [9.0],
        }
    )
    save_dataset(store, "daily_market_state", state, "C")
    valuation = pd.DataFrame(
        {
            "symbol": ["SH600000", "SH600000"],
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-04"]),
            "market_cap": [100.0, 999.0],
            "pb": [1.0, 9.0],
        }
    )
    save_dataset(store, "daily_valuation", valuation, "B")
    bars = pd.DataFrame(
        {
            "symbol": ["SH600000", "SH600000", "SH600000"],
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
            "open": [10.0, 10.1, 10.2],
            "high": [10.2, 10.3, 10.4],
            "low": [9.9, 10.0, 10.1],
            "close": [10.1, 10.2, 10.3],
            "volume": [100_000.0, 110_000.0, 120_000.0],
            "money": [1_000_000.0, 1_100_000.0, 1_200_000.0],
        }
    )
    return LocalDataPortal(store, FrameDailyBarSource(bars))


def test_portal_queries_are_point_in_time_and_never_backfill_future(portal):
    with pytest.raises(PointInTimeError):
        portal.instruments(None)

    valuation = portal.valuation("SH600000", "2024-01-03", fields=["market_cap", "pb"])

    assert valuation.loc[0, "trade_date"] == pd.Timestamp("2024-01-02")
    assert valuation.loc[0, "market_cap"] == 100.0
    assert portal.index_members("SH000300", "2024-01-02") == ["SH600000"]


def test_quality_gate_rejects_c_dataset_when_strategy_requires_b(portal):
    with pytest.raises(DataQualityError, match="quality C is below required B"):
        portal.market_snapshot("2024-01-03", minimum_quality="B")


def test_joinquant_compat_supports_history_and_lazy_current_data(portal):
    api = JoinQuantCompat(portal, observation_date="2024-01-03")

    history = api.attribute_history("SH600000", 2, fields=["close", "volume"])
    current = api.get_current_data()

    assert history.index.tolist() == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
    assert history["close"].tolist() == [10.1, 10.2]
    assert len(current) == 0
    assert current["SH600000"].is_st is None
    assert len(current) == 1
    with pytest.raises(TypeError, match="lazy"):
        current.get("SH600000")


def test_joinquant_compat_requires_fixed_observation_date(portal):
    api = JoinQuantCompat(portal)

    with pytest.raises(PointInTimeError):
        api.get_price("SH600000")
