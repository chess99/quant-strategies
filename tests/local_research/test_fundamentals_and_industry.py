import pandas as pd
import pytest

from quant_research.data.contracts import DatasetManifest, QualityGrade
from quant_research.data.fundamentals import (
    latest_fundamentals_asof,
    normalize_financial_cache,
)
from quant_research.data.industry import normalize_current_industry
from quant_research.data.store import ResearchDataStore
from quant_research.portal import DataQualityError, FrameDailyBarSource, LocalDataPortal


def financial_row(symbol, report_date, notice_date, report_type, revenue):
    return {
        "symbol": symbol,
        "report_date": report_date,
        "notice_date": notice_date,
        "report_type": report_type,
        "basic_eps": 1.0,
        "adjusted_profit": 10.0,
        "parent_net_profit": 11.0,
        "revenue": revenue,
        "roe": 12.0,
        "quarter_basic_eps": 0.2,
        "quarter_adjusted_profit": 2.0,
        "quarter_parent_net_profit": 2.2,
        "quarter_revenue": revenue / 4,
        "annual_basic_eps": 1.0 if report_type == "年报" else None,
        "annual_roe": 12.0 if report_type == "年报" else None,
    }


def test_financial_import_quarantines_impossible_notice_dates():
    raw = pd.DataFrame(
        [
            financial_row("SH600000", "2023-12-31", "2024-03-31", "年报", 100.0),
            financial_row("SH600000", "2024-03-31", "1900-01-01", "一季报", 30.0),
        ]
    )

    data, quarantine = normalize_financial_cache(raw)

    assert len(data) == 1
    assert data.loc[0, "fiscal_quarter"] == 4
    assert quarantine.loc[0, "quarantine_reason"].startswith("missing_or_invalid")


def test_latest_fundamentals_respects_announcement_date():
    raw = pd.DataFrame(
        [
            financial_row("SH600000", "2023-12-31", "2024-03-31", "年报", 100.0),
            financial_row("SH600000", "2024-03-31", "2024-04-30", "一季报", 130.0),
        ]
    )
    data, _ = normalize_financial_cache(raw)

    before_notice = latest_fundamentals_asof(data, "2024-04-15")
    after_notice = latest_fundamentals_asof(data, "2024-05-01")
    annual = latest_fundamentals_asof(data, "2024-05-01", annual_only=True)

    assert before_notice.loc[0, "report_date"] == pd.Timestamp("2023-12-31")
    assert after_notice.loc[0, "report_date"] == pd.Timestamp("2024-03-31")
    assert annual.loc[0, "report_date"] == pd.Timestamp("2023-12-31")


def test_current_industry_proxy_never_claims_past_validity():
    raw = pd.DataFrame(
        {"symbol": ["SH600000"], "name": ["浦发银行"], "industry": ["银行Ⅱ"]}
    )

    data = normalize_current_industry(raw, "2026-07-26")

    assert data.loc[0, "industry_name"] == "银行Ⅱ"
    assert data.loc[0, "start_date"] == pd.Timestamp("2026-07-26")
    assert data.loc[0, "quality_grade"] == "C"


def test_industry_portal_rejects_b_quality_and_does_not_backfill_past(tmp_path):
    data = normalize_current_industry(
        pd.DataFrame({"symbol": ["SH600000"], "industry": ["银行Ⅱ"]}),
        "2026-07-26",
    )
    store = ResearchDataStore(tmp_path)
    data_file = store.write_parquet("industry_membership", data)
    store.write_manifest(
        DatasetManifest(
            schema_version=1,
            dataset="industry_membership",
            provider="test",
            quality_grade=QualityGrade.C,
            row_count=len(data),
            columns=list(data.columns),
            data_files=[data_file],
        )
    )
    bars = pd.DataFrame(
        {
            "symbol": ["SH600000"],
            "trade_date": pd.to_datetime(["2025-01-02"]),
            "close": [10.0],
        }
    )
    portal = LocalDataPortal(store, FrameDailyBarSource(bars))

    assert portal.industry("SH600000", "2025-01-02", minimum_quality="C").empty
    with pytest.raises(DataQualityError):
        portal.industry("SH600000", "2026-07-26", minimum_quality="B")
