import pandas as pd
import pytest

from quant_research.data.contracts import DatasetManifest, QualityGrade
from quant_research.data.store import ResearchDataStore
from quant_research.jq_compat import JoinQuantCompat
from quant_research.portal import (
    CapabilityError,
    CompositeDailyBarSource,
    DataQualityError,
    FrameDailyBarSource,
    LocalDataPortal,
    PartitionedDailyBarSource,
    PointInTimeError,
    QlibDailyBarSource,
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


def save_symbol_partitions(store, name, frame, quality):
    files = store.write_partitioned_parquet(name, frame, ["symbol"])
    store.write_manifest(
        DatasetManifest(
            schema_version=2,
            dataset=name,
            provider="test-partitioned",
            quality_grade=QualityGrade(quality),
            row_count=len(frame),
            columns=list(frame.columns),
            data_files=files,
            partitioning={"style": "hive", "columns": ["symbol"]},
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
            "is_st": [False],
            "raw_close": [10.2],
            "high_limit": [11.0],
            "low_limit": [9.0],
            "status_quality": ["B"],
            "st_quality": ["B"],
            "limit_quality": ["B"],
        }
    )
    save_symbol_partitions(store, "daily_market_state", state, "C")
    valuation = pd.DataFrame(
        {
            "symbol": ["SH600000", "SH600000"],
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-04"]),
            "market_cap": [100.0, 999.0],
            "pe_ttm": [8.0, 9.0],
            "pb": [1.0, 9.0],
            "ps": [2.0, 3.0],
        }
    )
    save_symbol_partitions(store, "daily_valuation", valuation, "B")
    fundamentals = pd.DataFrame(
        {
            "symbol": ["SH600000", "SH600000"],
            "report_date": pd.to_datetime(["2023-06-30", "2023-09-30"]),
            "notice_date": pd.to_datetime(["2023-08-30", "2024-01-04"]),
            "cash": [10.0, 99.0],
            "interest_bearing_debt": [30.0, 999.0],
            "free_cash_flow": [5.0, 99.0],
            "ebit": [20.0, 99.0],
        }
    )
    save_symbol_partitions(store, "fundamentals_pit", fundamentals, "B")
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
    assert valuation.attrs["quant_research_provenance"]["provider"] == "test-partitioned"
    assert portal.last_query_provenance["manifest_sha256"]
    assert portal.index_members("SH000300", "2024-01-02") == ["SH600000"]


def test_value_metrics_derive_point_in_time_ev_fcf_and_ev_to_ebit(portal):
    result = portal.value_metrics("SH600000", "2024-01-03")

    assert result.loc[0, "market_cap"] == 100.0
    assert result.loc[0, "enterprise_value"] == 120.0
    assert result.loc[0, "free_cash_flow"] == 5.0
    assert result.loc[0, "ev_to_ebit"] == 6.0
    assert result.loc[0, "pe_ttm"] == 8.0
    assert result.loc[0, "pb"] == 1.0
    assert result.loc[0, "ps"] == 2.0
    provenance = result.attrs["quant_research_provenance"]
    assert provenance["observation_date"] == "2024-01-03"
    assert provenance["quality_grade"] == "B"
    assert provenance["enforced_minimum_quality"] == "B"
    assert provenance["formulae"]["enterprise_value"] == (
        "market_cap + interest_bearing_debt - cash"
    )


def test_value_metrics_do_not_fill_missing_components_with_zero(portal):
    fundamentals = pd.DataFrame(
        {
            "symbol": ["SH600000"],
            "report_date": pd.to_datetime(["2023-06-30"]),
            "notice_date": pd.to_datetime(["2023-08-30"]),
            "cash": [10.0],
            "interest_bearing_debt": [pd.NA],
            "free_cash_flow": [5.0],
            "ebit": [0.0],
        }
    )
    save_symbol_partitions(portal.store, "fundamentals_pit", fundamentals, "B")

    result = portal.value_metrics("SH600000", "2024-01-03")

    assert pd.isna(result.loc[0, "enterprise_value"])
    assert pd.isna(result.loc[0, "ev_to_ebit"])


def test_market_snapshot_accepts_b_components_in_aggregate_c_dataset(portal):
    result = portal.market_snapshot("2024-01-03", minimum_quality="B")

    assert result["symbol"].tolist() == ["SH600000"]
    provenance = result.attrs["quant_research_provenance"]
    assert provenance["quality_grade"] == "C"
    assert provenance["enforced_minimum_quality"] == "B"
    assert provenance["component_quality_columns"] == [
        "status_quality",
        "st_quality",
        "limit_quality",
    ]
    assert provenance["component_quality_gate_passed"] is True


def test_market_snapshot_rejects_component_below_required_quality(portal):
    manifest = portal.store.read_manifest("daily_market_state")
    state = pd.read_parquet(portal.store.root / manifest["data_files"][0]["path"])
    state.loc[:, "st_quality"] = "C"
    save_symbol_partitions(portal.store, "daily_market_state", state, "C")

    with pytest.raises(
        DataQualityError,
        match=r"SH600000.*2024-01-03.*st_quality=C.*required B",
    ):
        portal.market_snapshot("2024-01-03", minimum_quality="B")


def test_market_snapshot_rejects_missing_component_quality_column(portal):
    manifest = portal.store.read_manifest("daily_market_state")
    state = pd.read_parquet(portal.store.root / manifest["data_files"][0]["path"]).drop(
        columns="limit_quality"
    )
    save_symbol_partitions(portal.store, "daily_market_state", state, "C")

    with pytest.raises(
        DataQualityError,
        match=r"missing component quality columns.*limit_quality",
    ):
        portal.market_snapshot("2024-01-03", minimum_quality="B")


def test_joinquant_compat_supports_history_and_lazy_current_data(portal):
    api = JoinQuantCompat(portal, observation_date="2024-01-03")

    history = api.attribute_history("SH600000", 2, fields=["close", "volume"])
    current = api.get_current_data()

    assert history.index.tolist() == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
    assert history["close"].tolist() == [10.1, 10.2]
    assert len(current) == 0
    assert current["SH600000"].is_st is False
    assert len(current) == 1
    with pytest.raises(TypeError, match="lazy"):
        current.get("SH600000")


def test_current_data_uses_point_in_time_name_instead_of_master_current_name(portal):
    events = pd.DataFrame(
        {
            "symbol": ["SH600000", "SH600000"],
            "effective_from": pd.to_datetime(["2000-01-01", "2025-01-01"]),
            "display_name": ["浦发银行", "浦发退"],
            "st_quality": ["A", "A"],
        }
    )
    save_dataset(portal.store, "st_name_events", events, "A")
    master_path = portal.store.normalized_path("security_master")
    master = pd.read_parquet(master_path)
    master.loc[master["symbol"].eq("SH600000"), "display_name"] = "浦发退"
    master.to_parquet(master_path, index=False)

    current = JoinQuantCompat(
        portal,
        observation_date="2024-01-03",
    ).get_current_data()["SH600000"]

    assert current.name == "浦发银行"
    assert current.name_quality == "A"


def test_joinquant_compat_requires_fixed_observation_date(portal):
    api = JoinQuantCompat(portal)

    with pytest.raises(PointInTimeError):
        api.get_price("SH600000")


def test_joinquant_codes_count_history_and_partitioned_queries(portal):
    api = JoinQuantCompat(portal, observation_date="2024-01-03")

    prices = api.get_price(
        ["600000.XSHG"],
        end_date="2024-01-03",
        count=2,
        fields=["close"],
        panel=False,
    )
    history = api.history(
        2,
        "1d",
        "close",
        ["600000.XSHG"],
    )

    assert prices.index.names == ["trade_date", "symbol"]
    assert prices.index.get_level_values("symbol").unique().tolist() == ["600000.XSHG"]
    assert history.columns.tolist() == ["600000.XSHG"]
    assert history.iloc[:, 0].tolist() == [10.1, 10.2]
    assert api.get_index_stocks("000300.XSHG", date="2024-01-02") == ["600000.XSHG"]


def test_missing_partition_returns_empty_and_unsupported_panel_is_explicit(portal):
    assert portal.valuation("SZ000001", "2024-01-03").empty
    api = JoinQuantCompat(portal, observation_date="2024-01-03")
    with pytest.raises(Exception, match="Panel"):
        api.get_price("600000.XSHG", panel=True)


def test_composite_daily_source_routes_etf_to_partitioned_store(tmp_path):
    store = ResearchDataStore(tmp_path)
    master = pd.DataFrame({"symbol": ["SH600000", "SH510300"], "asset_type": ["stock", "etf"]})
    store.write_parquet("security_master", master)
    store.write_parquet(
        "trading_calendar",
        pd.DataFrame({"trade_date": pd.to_datetime(["2024-01-02"])}),
    )
    etf = pd.DataFrame(
        {
            "symbol": ["SH510300"],
            "trade_date": pd.to_datetime(["2024-01-02"]),
            "close": [4.0],
            "adjusted_close": [4.1],
        }
    )
    save_symbol_partitions(store, "etf_daily", etf, "B")
    stock = pd.DataFrame(
        {
            "symbol": ["SH600000"],
            "trade_date": pd.to_datetime(["2024-01-02"]),
            "close": [10.0],
        }
    )
    source = CompositeDailyBarSource(
        store,
        FrameDailyBarSource(stock),
        {"etf": PartitionedDailyBarSource(store, "etf_daily")},
    )

    frame = source.load(
        ["SH600000", "SH510300"],
        "2024-01-02",
        "2024-01-02",
        ["close"],
        "pre",
    )

    assert frame.set_index("symbol")["close"].to_dict() == {
        "SH600000": 10.0,
        "SH510300": 4.1,
    }


def test_qlib_provenance_has_content_version_and_source_hashes(tmp_path):
    root = tmp_path / "qlib"
    (root / "calendars").mkdir(parents=True)
    (root / "instruments").mkdir(parents=True)
    (root / "calendars" / "day.txt").write_text("2024-01-02\n", encoding="utf-8")
    (root / "instruments" / "all.txt").write_text(
        "SH600000\t2024-01-02\t2024-01-02\n", encoding="utf-8"
    )

    provenance = QlibDailyBarSource(root)._build_provenance()

    assert provenance["data_version"]
    assert len(provenance["source_files"]) == 2
    assert all(item["sha256"] for item in provenance["source_files"])


def test_portal_bars_bind_platform_audit_manifest(portal):
    portal.store.write_json_report("platform_coverage", {"status": "passed"})

    frame = portal.bars("SH600000", "2024-01-02", "2024-01-03")

    provenance = frame.attrs["quant_research_provenance"]
    assert provenance["platform_audit"]["sha256"]
    assert portal.last_query_provenance == provenance


def test_retired_security_paused_rows_and_missing_fields_are_explicit(tmp_path):
    store = ResearchDataStore(tmp_path)
    master = pd.DataFrame(
        {
            "symbol": ["SH600000", "SZ000001"],
            "asset_type": ["stock", "stock"],
            "start_date": pd.to_datetime(["2020-01-01", "2020-01-01"]),
            "end_date": pd.to_datetime(["2030-01-01", "2023-12-31"]),
        }
    )
    save_dataset(store, "security_master", master, "B")
    bars = pd.DataFrame(
        {
            "symbol": ["SH600000", "SH600000"],
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "close": [10.0, None],
            "volume": [1000.0, 0.0],
        }
    )
    portal = LocalDataPortal(store, FrameDailyBarSource(bars))

    assert portal.instruments("2024-01-02")["symbol"].tolist() == ["SH600000"]
    visible = portal.bars(
        "SH600000",
        "2024-01-02",
        "2024-01-03",
        fields=["close", "volume"],
        skip_paused=True,
    )
    assert visible["trade_date"].tolist() == [pd.Timestamp("2024-01-02")]
    with pytest.raises(CapabilityError, match="unavailable"):
        portal.bars("SH600000", "2024-01-02", "2024-01-03", fields=["vwap"])


def test_query_dsl_and_statdate_have_actionable_migration_errors(portal):
    api = JoinQuantCompat(portal, observation_date="2024-01-03")

    with pytest.raises(CapabilityError, match="query DSL"):
        api.get_fundamentals(object(), date="2024-01-03")
    with pytest.raises(CapabilityError, match="statDate"):
        api.get_fundamentals(["600000.XSHG"], statDate="2023")


def test_joinquant_financial_aliases_use_single_quarter_semantics(portal):
    fundamentals = pd.DataFrame(
        {
            "symbol": ["SH600000"],
            "report_date": pd.to_datetime(["2023-09-30"]),
            "notice_date": pd.to_datetime(["2023-10-30"]),
            "roe": [15.0],
            "quarter_roe": [4.0],
            "quarter_gross_margin": [32.0],
            "quarter_net_margin": [8.0],
            "quarter_operating_cash_flow": [120.0],
            "total_liabilities": [500.0],
        }
    )
    save_symbol_partitions(portal.store, "fundamentals_pit", fundamentals, "B")
    api = JoinQuantCompat(portal, observation_date="2024-01-03")

    result = api.get_fundamentals(
        ["600000.XSHG"],
        fields=[
            "roe",
            "gross_profit_margin",
            "net_profit_margin",
            "net_operate_cash_flow",
            "total_liability",
        ],
    )

    assert result.loc[0, "roe"] == 4.0
    assert result.loc[0, "gross_profit_margin"] == 32.0
    assert result.loc[0, "net_profit_margin"] == 8.0
    assert result.loc[0, "net_operate_cash_flow"] == 120.0
    assert result.loc[0, "total_liability"] == 500.0
