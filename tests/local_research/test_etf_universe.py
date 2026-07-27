import pandas as pd

from quant_research.data.etf_universe import (
    build_etf_candidates,
    build_etf_master,
    classify_etf,
    etf_security_supplemental,
    normalize_current_etf_lists,
    summarize_etf_coverage,
)
from quant_research.data.etf_sync import normalize_eastmoney_etf_profile
from quant_research.data.etf_sync import sync_etf_daily
from quant_research.data.store import ResearchDataStore


def test_current_etf_union_requires_a_real_latest_trade_date():
    sina = pd.DataFrame(
        {
            "代码": ["sh510300"],
            "名称": ["沪深300ETF"],
        }
    )
    ths = pd.DataFrame(
        {
            "基金代码": ["510300", "159915", "158000"],
            "基金名称": ["沪深300ETF", "创业板ETF", "待上市ETF"],
            "最新-交易日": ["2026-07-24", "2026-07-24", None],
            "基金类型": ["股票型", "股票型", "股票型"],
        }
    )

    current = normalize_current_etf_lists(sina, ths)

    assert set(current.loc[current["expected_active"], "symbol"]) == {
        "SH510300",
        "SZ159915",
    }
    pending = current.set_index("symbol").loc["SZ158000"]
    assert not pending["expected_active"]
    assert pending["in_ths"]


def test_candidate_pool_keeps_historical_exchange_records():
    current = pd.DataFrame(
        {
            "symbol": ["SH510300"],
            "display_name": ["沪深300ETF"],
            "expected_active": [True],
            "in_sina": [True],
            "in_ths": [True],
            "latest_trade_date": [pd.Timestamp("2026-07-24")],
            "reported_fund_type": ["股票型"],
        }
    )
    fund_names = pd.DataFrame(
        {
            "基金代码": ["510300", "159901", "003765"],
            "基金简称": ["沪深300ETF", "深100ETF", "创业板ETF发起式联接A"],
            "基金类型": ["指数型-股票", "指数型-股票", "指数型-股票"],
        }
    )
    historical = pd.DataFrame(
        {
            "基金代码": ["510300", "510190"],
            "基金简称": ["沪深300ETF", "历史ETF"],
            "ETF类型": ["股票", "股票"],
            "统计日期": ["2020-01-31", "2014-01-31"],
        }
    )

    candidates = build_etf_candidates(current, fund_names, historical)

    assert set(candidates["symbol"]) == {"SH510190", "SH510300", "SZ159901"}
    old = candidates.set_index("symbol").loc["SH510190"]
    assert old["seen_in_historical_exchange_snapshot"]
    assert not old["expected_active"]


def test_etf_classification_covers_supported_research_categories():
    assert classify_etf("货币型-普通货币", "银华日利ETF", "") == "money"
    assert classify_etf("指数型-固收", "国债ETF", "十年期国债指数") == "bond"
    assert classify_etf("指数型-其他", "黄金ETF", "黄金现货") == "commodity"
    assert (
        classify_etf("指数型-海外股票", "纳指ETF", "纳斯达克100指数")
        == "cross_border"
    )
    assert (
        classify_etf("指数型-股票", "半导体ETF", "中证半导体产业指数")
        == "sector_equity"
    )
    assert (
        classify_etf("指数型-股票", "沪深300ETF", "沪深300指数")
        == "broad_equity"
    )


def test_master_distinguishes_active_delisted_pending_and_failed():
    candidates = pd.DataFrame(
        {
            "symbol": ["SH510300", "SH510190", "SZ158000", "SZ159999"],
            "code": ["510300", "510190", "158000", "159999"],
            "exchange": ["XSHG", "XSHG", "XSHE", "XSHE"],
            "display_name": ["沪深300ETF", "历史ETF", "待上市ETF", "失败ETF"],
            "reported_fund_type": [
                "指数型-股票",
                "指数型-股票",
                "指数型-股票",
                "指数型-股票",
            ],
            "expected_active": [True, False, False, True],
            "in_sina": [True, False, False, True],
            "in_ths": [True, False, True, False],
            "seen_in_historical_exchange_snapshot": [True, True, False, False],
            "candidate_sources": [
                "sina|ths",
                "sse-history",
                "ths",
                "sina",
            ],
        }
    )
    profiles = pd.DataFrame(
        {
            "symbol": ["SH510300", "SH510190", "SZ158000"],
            "fund_full_name": ["沪深300交易型基金", "历史交易型基金", "待上市基金"],
            "inception_date": pd.to_datetime(
                ["2012-05-04", "2010-01-01", "2026-08-01"]
            ),
            "tracking_target": ["沪深300指数", "历史指数", "待上市指数"],
            "profile_status": ["success", "success", "success"],
        }
    )
    bar_status = pd.DataFrame(
        {
            "symbol": ["SH510300", "SH510190", "SZ158000", "SZ159999"],
            "status": ["success", "success", "empty", "failed"],
            "first_trade_date": pd.to_datetime(
                ["2012-05-28", "2010-02-01", None, None]
            ),
            "last_trade_date": pd.to_datetime(
                ["2026-07-24", "2018-06-29", None, None]
            ),
            "row_count": [3400, 1200, 0, 0],
            "error": [None, None, None, "timeout"],
        }
    )

    master = build_etf_master(
        candidates,
        profiles,
        bar_status,
        source_end=pd.Timestamp("2026-07-24"),
    ).set_index("symbol")

    assert master.loc["SH510300", "lifecycle_status"] == "active"
    assert master.loc["SH510190", "lifecycle_status"] == "delisted"
    assert master.loc["SZ158000", "lifecycle_status"] == "prelisting"
    assert master.loc["SZ159999", "lifecycle_status"] == "download_failed"
    assert master.loc["SH510300", "listing_date"] == pd.Timestamp("2012-05-28")
    assert master.loc["SH510190", "delisting_date"] == pd.Timestamp("2018-06-29")


def test_coverage_denominator_is_the_cross_source_active_union():
    master = pd.DataFrame(
        {
            "symbol": ["SH510300", "SZ159915", "SH510190"],
            "expected_active": [True, True, False],
            "bar_status": ["success", "failed", "success"],
            "lifecycle_status": ["active", "download_failed", "delisted"],
            "etf_category": ["broad_equity", "broad_equity", "sector_equity"],
            "first_trade_date": pd.to_datetime(
                ["2012-05-28", None, "2010-01-01"]
            ),
            "last_trade_date": pd.to_datetime(
                ["2026-07-24", None, "2018-06-29"]
            ),
        }
    )

    summary = summarize_etf_coverage(master)

    assert summary["current_expected"] == 2
    assert summary["current_with_daily_history"] == 1
    assert summary["current_coverage_ratio"] == 0.5
    assert summary["historical_or_delisted_candidates"] == 1


def test_eastmoney_profile_extracts_inception_and_tracking_target():
    raw = pd.DataFrame(
        {
            "基金全称": ["华泰柏瑞沪深300交易型开放式指数证券投资基金"],
            "基金类型": ["指数型-股票"],
            "成立日期/规模": ["2012年05月04日 / 329.686亿份"],
            "跟踪标的": ["沪深300指数"],
        }
    )

    profile = normalize_eastmoney_etf_profile("SH510300", raw)

    assert profile["fund_full_name"] == raw.loc[0, "基金全称"]
    assert profile["reported_fund_type"] == "指数型-股票"
    assert profile["inception_date"] == pd.Timestamp("2012-05-04")
    assert profile["tracking_target"] == "沪深300指数"


def test_daily_sync_checkpoints_partitioned_files_and_resumes(tmp_path):
    class Provider:
        def __init__(self):
            self.quote_calls = 0

        def quotes(self, symbol):
            self.quote_calls += 1
            return pd.DataFrame(
                {
                    "date": ["2024-01-02", "2024-01-03"],
                    "open": [1.0, 1.01],
                    "high": [1.02, 1.03],
                    "low": [0.99, 1.0],
                    "close": [1.01, 1.02],
                    "volume": [1000, 1100],
                    "amount": [1010, 1122],
                }
            )

        def dividends(self, symbol):
            return pd.DataFrame(columns=["日期", "累计分红"])

        def profile(self, symbol):
            return pd.DataFrame(
                {
                    "基金全称": [f"{symbol}基金"],
                    "基金类型": ["指数型-股票"],
                    "成立日期/规模": ["2023年12月01日 / 1.0亿份"],
                    "跟踪标的": ["沪深300指数"],
                }
            )

    store = ResearchDataStore(tmp_path / "data")
    candidates = pd.DataFrame({"symbol": ["SH510300", "SZ159915"]})
    provider = Provider()

    statuses, profiles, manifest = sync_etf_daily(
        store,
        candidates,
        provider=provider,
        workers=1,
        attempts=1,
        checkpoint_every=1,
    )
    resumed, _, _ = sync_etf_daily(
        store,
        candidates,
        provider=provider,
        workers=1,
        attempts=1,
        checkpoint_every=1,
    )

    assert provider.quote_calls == 2
    assert set(statuses["status"]) == {"success"}
    assert len(profiles) == 2
    assert manifest.partitioning == {"style": "hive", "columns": ["symbol"]}
    assert len(resumed) == 2
    assert store.normalized_path(
        "etf_daily", "symbol=SH510300/data.parquet"
    ).is_file()


def test_etf_security_supplemental_keeps_verified_delisted_products():
    frame = pd.DataFrame(
        {
            "symbol": ["SH510300", "SH510190", "SZ158000"],
            "exchange": ["XSHG", "XSHG", "XSHE"],
            "display_name": ["沪深300ETF", "历史ETF", "候选ETF"],
            "inception_date": pd.to_datetime(
                ["2012-05-04", "2010-01-01", None]
            ),
            "first_trade_date": pd.to_datetime(
                ["2012-05-28", "2010-02-01", None]
            ),
            "last_trade_date": pd.to_datetime(
                ["2026-07-24", "2018-06-29", None]
            ),
            "bar_status": ["success", "success", "empty"],
            "lifecycle_status": ["active", "delisted", "unverified_candidate"],
            "source": ["fixture", "fixture", "fixture"],
        }
    )

    supplemental = etf_security_supplemental(
        frame, source_end=pd.Timestamp("2026-07-24")
    ).set_index("symbol")

    assert set(supplemental.index) == {"SH510300", "SH510190"}
    assert supplemental.loc["SH510300", "active_at_source_end"]
    assert (
        supplemental.loc["SH510190", "delisting_date"]
        == pd.Timestamp("2018-06-29")
    )
