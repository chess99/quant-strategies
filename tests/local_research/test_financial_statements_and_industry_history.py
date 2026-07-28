from __future__ import annotations

import pandas as pd

from quant_research.data.financial_statements import (
    audit_financial_field_coverage,
    latest_financials_asof,
    normalize_financial_statements,
)
from quant_research.data.industry import normalize_shenwan_history
from quant_research.data.store import ResearchDataStore


def _statement_rows() -> dict[str, list[dict]]:
    keys = {
        "SECUCODE": "600000.SH",
        "REPORT_DATE": "2023-12-31 00:00:00",
        "NOTICE_DATE": "2024-03-30 00:00:00",
        "UPDATE_DATE": "2024-04-01 00:00:00",
        "REPORT_TYPE": "年报",
    }
    return {
        "balance": [
            {
                **keys,
                "TOTAL_ASSETS": 1_000.0,
                "TOTAL_LIABILITIES": 400.0,
                "TOTAL_EQUITY": 600.0,
                "MONETARYFUNDS": 100.0,
                "INVENTORY": 80.0,
                "ACCOUNTS_RECE": 50.0,
                "NOTE_ACCOUNTS_RECE": 70.0,
                "GOODWILL": 20.0,
                "SHORT_LOAN": 30.0,
                "LONG_LOAN": 40.0,
                "NONCURRENT_LIAB_1YEAR": 5.0,
                "BOND_PAYABLE": 10.0,
            }
        ],
        "income": [
            {
                **keys,
                "TOTAL_OPERATE_INCOME": 500.0,
                "OPERATE_INCOME": 480.0,
                "OPERATE_COST": 300.0,
                "OPERATE_PROFIT": 120.0,
                "NETPROFIT": 90.0,
                "PARENT_NETPROFIT": 85.0,
                "DEDUCT_PARENT_NETPROFIT": 80.0,
                "BASIC_EPS": 1.25,
            }
        ],
        "cashflow": [
            {
                **keys,
                "NETCASH_OPERATE": 110.0,
                "CONSTRUCT_LONG_ASSET": 35.0,
            }
        ],
        "indicator": [
            {
                **keys,
                "ROEJQ": 15.0,
                "ZZCJLL": 9.0,
                "XSMLL": 40.0,
                "XSJLL": 18.0,
                "EPSJB": 1.25,
            }
        ],
    }


def test_normalize_financial_statements_merges_tables_and_derives_fields():
    result = normalize_financial_statements("SH600000", _statement_rows())

    assert len(result) == 1
    row = result.iloc[0]
    assert row["revenue"] == 500.0
    assert row["total_assets"] == 1_000.0
    assert row["operating_cash_flow"] == 110.0
    assert row["interest_bearing_debt"] == 85.0
    assert row["free_cash_flow"] == 75.0
    assert row["roe"] == 15.0
    assert row["roa"] == 9.0
    assert row["gross_margin"] == 40.0
    assert row["net_margin"] == 18.0
    assert row["quality_grade"] == "B"


def test_normalize_financial_statements_derives_joinquant_single_quarter_fields():
    q1_keys = {
        "SECUCODE": "600000.SH",
        "REPORT_DATE": "2023-03-31 00:00:00",
        "NOTICE_DATE": "2023-04-20 00:00:00",
        "UPDATE_DATE": "2023-04-20 00:00:00",
        "REPORT_TYPE": "一季报",
    }
    q2_keys = {
        "SECUCODE": "600000.SH",
        "REPORT_DATE": "2023-06-30 00:00:00",
        "NOTICE_DATE": "2023-08-20 00:00:00",
        "UPDATE_DATE": "2023-08-20 00:00:00",
        "REPORT_TYPE": "中报",
    }
    rows = {
        "balance": [
            {
                **q1_keys,
                "TOTAL_ASSETS": 1_000.0,
                "TOTAL_LIABILITIES": 400.0,
                "TOTAL_EQUITY": 600.0,
            },
            {
                **q2_keys,
                "TOTAL_ASSETS": 1_200.0,
                "TOTAL_LIABILITIES": 500.0,
                "TOTAL_EQUITY": 700.0,
            },
        ],
        "income": [
            {
                **q1_keys,
                "TOTAL_OPERATE_INCOME": 420.0,
                "OPERATE_INCOME": 400.0,
                "OPERATE_COST": 240.0,
                "OPERATE_PROFIT": 100.0,
                "NETPROFIT": 80.0,
                "PARENT_NETPROFIT": 75.0,
                "DEDUCT_PARENT_NETPROFIT": 70.0,
                "BASIC_EPS": 0.75,
            },
            {
                **q2_keys,
                "TOTAL_OPERATE_INCOME": 950.0,
                "OPERATE_INCOME": 900.0,
                "OPERATE_COST": 570.0,
                "OPERATE_PROFIT": 215.0,
                "NETPROFIT": 170.0,
                "PARENT_NETPROFIT": 160.0,
                "DEDUCT_PARENT_NETPROFIT": 150.0,
                "BASIC_EPS": 1.60,
            },
        ],
        "cashflow": [
            {**q1_keys, "NETCASH_OPERATE": 100.0, "CONSTRUCT_LONG_ASSET": 30.0},
            {**q2_keys, "NETCASH_OPERATE": 160.0, "CONSTRUCT_LONG_ASSET": 50.0},
        ],
        "indicator": [
            {
                **q1_keys,
                "ROEJQ": 12.0,
                "ZZCJLL": 8.0,
                "XSMLL": 40.0,
                "XSJLL": 20.0,
                "EPSJB": 0.75,
            },
            {
                **q2_keys,
                "ROEJQ": 24.0,
                "ZZCJLL": 16.0,
                "XSMLL": 36.0,
                "XSJLL": 18.9,
                "EPSJB": 1.60,
            },
        ],
    }

    result = normalize_financial_statements("SH600000", rows)
    q1 = result[result["fiscal_quarter"].eq(1)].iloc[0]
    q2 = result[result["fiscal_quarter"].eq(2)].iloc[0]

    assert q1["quarter_operating_cash_flow"] == 100.0
    assert q1["quarter_roe"] == 12.0
    assert q1["quarter_roa"] == 8.0
    assert q2["quarter_revenue"] == 530.0
    assert q2["quarter_operating_revenue"] == 500.0
    assert q2["quarter_operating_cost"] == 330.0
    assert q2["quarter_net_profit"] == 90.0
    assert q2["quarter_parent_net_profit"] == 85.0
    assert q2["quarter_operating_cash_flow"] == 60.0
    assert q2["quarter_gross_margin"] == 34.0
    assert q2["quarter_net_margin"] == 18.0
    assert q2["quarter_roa"] == 90.0 * 2.0 / (1_000.0 + 1_200.0) * 100.0
    assert q2["quarter_roe"] == 85.0 * 2.0 / (600.0 + 700.0) * 100.0


def test_latest_financials_asof_never_exposes_later_notice_or_revision():
    first = normalize_financial_statements("SH600000", _statement_rows())
    revised_rows = _statement_rows()
    for table_rows in revised_rows.values():
        table_rows[0]["NOTICE_DATE"] = "2024-04-20 00:00:00"
        table_rows[0]["UPDATE_DATE"] = "2024-04-21 00:00:00"
    revised_rows["income"][0]["PARENT_NETPROFIT"] = 95.0
    revised = normalize_financial_statements("SH600000", revised_rows)
    data = pd.concat([first, revised], ignore_index=True)

    before = latest_financials_asof(data, "2024-04-10")
    after = latest_financials_asof(data, "2024-04-25")

    assert before.iloc[0]["parent_net_profit"] == 85.0
    assert after.iloc[0]["parent_net_profit"] == 95.0
    assert pd.Timestamp(before.iloc[0]["notice_date"]) <= pd.Timestamp("2024-04-10")
    assert pd.Timestamp(after.iloc[0]["notice_date"]) <= pd.Timestamp("2024-04-25")


def test_financial_field_audit_reports_latest_current_coverage(tmp_path):
    store = ResearchDataStore(tmp_path)
    frame = normalize_financial_statements("SH600000", _statement_rows())
    artifact = store.write_parquet(
        "fundamentals_pit", frame, filename="symbol=SH600000/data.parquet"
    )
    artifact["partition_values"] = {"symbol": "SH600000"}

    audit = audit_financial_field_coverage(store, [artifact], {"SH600000", "SZ000001"})

    assert audit["partition_failures"] == []
    assert audit["fields"]["revenue"]["symbol_coverage_ratio"] == 1.0
    assert audit["fields"]["revenue"]["current_latest_coverage_ratio"] == 0.5


def test_normalize_shenwan_history_builds_level_intervals_without_future_backfill():
    raw = pd.DataFrame(
        {
            "stock_code": ["600000", "600000", "000001"],
            "included_date": ["2010-01-01", "2021-07-30", "2014-02-21"],
            "industry_code": ["480101", "480301", "480101"],
            "updated_at": ["2015-10-27", "2025-12-15", "2024-09-27"],
        }
    )
    master = pd.DataFrame(
        {
            "symbol": ["SH600000", "SZ000001"],
            "listing_date": ["1999-11-10", "1991-04-03"],
            "delisting_date": [pd.NaT, pd.NaT],
        }
    )
    names = {
        "480000": "银行",
        "480100": "银行旧分类",
        "480300": "银行新分类",
    }

    result = normalize_shenwan_history(raw, master, industry_names=names)
    pudong = result[result["symbol"].eq("SH600000")]

    assert set(pudong["classification"]) == {"sw_l1", "sw_l2"}
    old_l2 = pudong[
        pudong["classification"].eq("sw_l2")
        & pudong["industry_code"].eq("480100")
    ].iloc[0]
    new_l2 = pudong[
        pudong["classification"].eq("sw_l2")
        & pudong["industry_code"].eq("480300")
    ].iloc[0]
    assert old_l2["start_date"] == pd.Timestamp("2010-01-01")
    assert old_l2["end_date"] == pd.Timestamp("2021-07-29")
    assert new_l2["start_date"] == pd.Timestamp("2021-07-30")
    assert new_l2["quality_grade"] == "B"
    assert new_l2["industry_name"] == "银行新分类"


def test_shenwan_numeric_code_collision_never_maps_to_index():
    raw = pd.DataFrame(
        {
            "stock_code": ["000905"],
            "included_date": ["2005-01-04"],
            "industry_code": ["420101"],
            "updated_at": ["2025-12-15"],
        }
    )
    master = pd.DataFrame(
        {
            "symbol": ["SH000905", "SZ000905"],
            "asset_type": ["index", "stock"],
            "listing_date": ["2005-01-04", "1999-04-29"],
            "delisting_date": [pd.NaT, pd.NaT],
        }
    )

    result = normalize_shenwan_history(raw, master)

    assert set(result["symbol"]) == {"SZ000905"}
