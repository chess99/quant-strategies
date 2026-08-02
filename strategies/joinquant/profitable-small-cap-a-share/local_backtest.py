"""本地复现原帖并比较偏实盘小市值变体。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.backtest import (  # noqa: E402
    BacktestConfig,
    CostModel,
    DailyBacktester,
    build_delisting_actions,
    performance_metrics,
)
from quant_research.data.store import ResearchDataStore, sha256_file  # noqa: E402
from quant_research.full_market import (  # noqa: E402
    build_asof_cross_sections,
    build_event_cross_sections,
    build_exact_cross_sections,
)
from quant_research.portal import LocalDataPortal, QlibDailyBarSource  # noqa: E402


FAMILY = Path(__file__).resolve().parent
STUDY_ROOT = ROOT / "studies" / "profitable-small-cap-rebuild"
DEFAULT_DATA_ROOT = Path("D:/code/_open-source/_data/quant-research")
DEFAULT_QLIB_ROOT = Path("D:/code/_open-source/_data/qlib/cn_data")
PRESELECT_COUNT = 500
MINIMUM_LISTING_DAYS = 375
POST_PUBLICATION_START = pd.Timestamp("2023-12-01")


class ExperimentConfig:
    def __init__(
        self,
        name,
        stock_count,
        minimum_quarter_roe,
        minimum_quarter_roa,
        maximum_price=None,
        minimum_average_money=0.0,
        maximum_industry_count=99,
        minimum_market_cap=0.0,
        target_exposure=0.95,
        risk_ma_days=None,
        risk_off_exposure=0.5,
        slippage_rate=0.004,
        cost_multiplier=1.0,
        initial_cash=None,
    ):
        self.name = name
        self.stock_count = int(stock_count)
        self.minimum_quarter_roe = float(minimum_quarter_roe)
        self.minimum_quarter_roa = float(minimum_quarter_roa)
        self.maximum_price = None if maximum_price is None else float(maximum_price)
        self.minimum_average_money = float(minimum_average_money)
        self.maximum_industry_count = int(maximum_industry_count)
        self.minimum_market_cap = float(minimum_market_cap)
        self.target_exposure = float(target_exposure)
        self.risk_ma_days = risk_ma_days
        self.risk_off_exposure = float(risk_off_exposure)
        self.slippage_rate = float(slippage_rate)
        self.cost_multiplier = float(cost_multiplier)
        self.initial_cash = initial_cash

    def to_dict(self):
        return dict(self.__dict__)


def experiment_configs():
    practical = {
        "minimum_quarter_roe": 1.0,
        "minimum_quarter_roa": 0.5,
        "maximum_price": None,
        "minimum_average_money": 10_000_000,
    }
    return [
        ExperimentConfig(
            "published-core", 10, 0.15, 0.10, maximum_price=10,
            minimum_average_money=0, maximum_industry_count=10,
            target_exposure=1.0,
        ),
        ExperimentConfig(
            "quality-liquid-10", 10, 1.0, 0.5, maximum_price=10,
            minimum_average_money=10_000_000, maximum_industry_count=3,
        ),
        ExperimentConfig("practical-15", 15, maximum_industry_count=3, **practical),
        ExperimentConfig("practical-20", 20, maximum_industry_count=4, **practical),
        ExperimentConfig("practical-30", 30, maximum_industry_count=6, **practical),
        ExperimentConfig(
            "liquid-20", 20, 1.0, 0.5, maximum_price=None,
            minimum_average_money=20_000_000, maximum_industry_count=4,
        ),
        ExperimentConfig(
            "market-cap-floor-20", 20, 1.0, 0.5, maximum_price=None,
            minimum_average_money=10_000_000, maximum_industry_count=4,
            minimum_market_cap=2_000_000_000,
        ),
        ExperimentConfig(
            "risk-scaled-20", 20, maximum_industry_count=4,
            risk_ma_days=120, risk_off_exposure=0.5, **practical,
        ),
        ExperimentConfig(
            "risk-scaled-15", 15, maximum_industry_count=3,
            risk_ma_days=120, risk_off_exposure=0.5, **practical,
        ),
        ExperimentConfig(
            "risk-scaled-30", 30, maximum_industry_count=6,
            risk_ma_days=120, risk_off_exposure=0.5, **practical,
        ),
        ExperimentConfig(
            "risk-scaled-20-double-friction", 20, maximum_industry_count=4,
            risk_ma_days=120, risk_off_exposure=0.5,
            slippage_rate=0.008, cost_multiplier=2.0, **practical,
        ),
        ExperimentConfig(
            "risk-scaled-20-5m", 20, maximum_industry_count=4,
            risk_ma_days=120, risk_off_exposure=0.5,
            initial_cash=5_000_000, **practical,
        ),
        ExperimentConfig(
            "risk-60-cash-20", 20, maximum_industry_count=4,
            risk_ma_days=60, risk_off_exposure=0.0, **practical,
        ),
        ExperimentConfig(
            "risk-60-quarter-20", 20, maximum_industry_count=4,
            risk_ma_days=60, risk_off_exposure=0.25, **practical,
        ),
        ExperimentConfig(
            "risk-120-cash-20", 20, maximum_industry_count=4,
            risk_ma_days=120, risk_off_exposure=0.0, **practical,
        ),
        ExperimentConfig(
            "risk-120-quarter-20", 20, maximum_industry_count=4,
            risk_ma_days=120, risk_off_exposure=0.25, **practical,
        ),
        ExperimentConfig(
            "risk-200-cash-20", 20, maximum_industry_count=4,
            risk_ma_days=200, risk_off_exposure=0.0, **practical,
        ),
        ExperimentConfig(
            "risk-200-quarter-20", 20, maximum_industry_count=4,
            risk_ma_days=200, risk_off_exposure=0.25, **practical,
        ),
        ExperimentConfig(
            "practical-20-double-friction", 20, maximum_industry_count=4,
            slippage_rate=0.008, cost_multiplier=2.0, **practical,
        ),
        ExperimentConfig(
            "practical-20-5m", 20, maximum_industry_count=4,
            initial_cash=5_000_000, **practical,
        ),
    ]


def select_candidates(frame: pd.DataFrame, config: ExperimentConfig):
    selected = frame[frame["eligible_base"].eq(True)].copy()
    selected = selected[
        pd.to_numeric(selected["quarter_roe"], errors="coerce").ge(
            config.minimum_quarter_roe
        )
        & pd.to_numeric(selected["quarter_roa"], errors="coerce").ge(
            config.minimum_quarter_roa
        )
        & pd.to_numeric(selected["average_money"], errors="coerce").ge(
            config.minimum_average_money
        )
        & pd.to_numeric(selected["market_cap"], errors="coerce").ge(
            config.minimum_market_cap
        )
    ]
    if config.maximum_price is not None:
        selected = selected[
            pd.to_numeric(selected["raw_close"], errors="coerce").lt(config.maximum_price)
        ]
    selected = selected.sort_values(["market_cap", "symbol"], kind="stable")
    result = []
    counts = {}
    for row in selected.itertuples(index=False):
        industry = row.industry
        count = counts.get(industry, 0)
        if count >= config.maximum_industry_count:
            continue
        result.append(row.symbol)
        counts[industry] = count + 1
        if len(result) >= config.stock_count:
            break
    return result


def dataset_provenance(store, dataset):
    manifest = store.read_manifest(dataset)
    path = store.manifest_path(dataset)
    return {
        "dataset": dataset,
        "provider": manifest.get("provider"),
        "quality_grade": manifest.get("quality_grade"),
        "row_count": manifest.get("row_count"),
        "manifest_sha256": sha256_file(path),
    }


def monthly_last_schedule(portal, start_date, end_date):
    padded = portal.calendar(pd.Timestamp(start_date) - pd.Timedelta(days=40), end_date)
    calendar = padded[padded >= pd.Timestamp(start_date)]
    execution_dates = pd.Series(calendar, index=calendar.to_period("M")).groupby(level=0).last()
    rows = []
    for execution_date in execution_dates:
        position = padded.get_loc(execution_date)
        rows.append(
            {
                "execution_date": execution_date,
                "observation_date": padded[position - 1],
            }
        )
    return calendar, pd.DataFrame(rows)


def _snapshot_key(store, schedule):
    payload = {
        "schedule": schedule.astype(str).to_dict(orient="records"),
        "manifests": {
            name: sha256_file(store.manifest_path(name))
            for name in (
                "security_master",
                "daily_valuation",
                "daily_market_state",
                "fundamentals_pit",
                "industry_membership",
                "st_name_events",
                "delisting_events",
            )
        },
        "preselect_count": PRESELECT_COUNT,
        "minimum_listing_days": MINIMUM_LISTING_DAYS,
        "qlib_money_unit": "tushare_thousand_rmb_to_rmb_v1",
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return digest[:16], payload


def build_fundamental_snapshots(store, observation_dates):
    dates = pd.DatetimeIndex(observation_dates).normalize().sort_values().unique()
    manifest = store.read_manifest("fundamentals_pit")
    fields = [
        "symbol", "report_date", "notice_date", "quarter_roe", "quarter_roa", "quality_grade"
    ]
    frames = []
    failures = []
    for artifact in manifest["data_files"]:
        symbol = artifact["partition_values"]["symbol"]
        try:
            source = pd.read_parquet(store.root / artifact["path"], columns=fields)
            source["report_date"] = pd.to_datetime(source["report_date"]).dt.normalize()
            source["notice_date"] = pd.to_datetime(source["notice_date"]).dt.normalize()
            source = source[source["notice_date"].le(dates.max())]
            rows = []
            for date in dates:
                visible = source[source["notice_date"].le(date)]
                if visible.empty:
                    continue
                latest = visible.sort_values(["report_date", "notice_date"]).iloc[-1]
                rows.append(
                    {
                        "observation_date": date,
                        "symbol": symbol,
                        "report_date": latest["report_date"],
                        "notice_date": latest["notice_date"],
                        "quarter_roe": latest["quarter_roe"],
                        "quarter_roa": latest["quarter_roa"],
                        "fundamental_quality": latest["quality_grade"],
                    }
                )
            if rows:
                frames.append(pd.DataFrame(rows))
        except Exception as exc:
            failures.append({"symbol": symbol, "error": "%s: %s" % (type(exc).__name__, exc)})
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    audit = {
        "dataset": "fundamentals_pit",
        "observation_date_count": len(dates),
        "successful_symbols": int(frame["symbol"].nunique()) if not frame.empty else 0,
        "matched_rows": len(frame),
        "failed_symbols": failures,
        "future_notice_rows": int(frame["notice_date"].gt(frame["observation_date"]).sum())
        if not frame.empty else 0,
    }
    return frame, audit


def build_industry_snapshots(store, symbols, observation_dates):
    dates = pd.DatetimeIndex(observation_dates).normalize().sort_values().unique()
    selected = set(symbols)
    manifest = store.read_manifest("industry_membership")
    frames = []
    for artifact in manifest["data_files"]:
        symbol = artifact["partition_values"]["symbol"]
        if symbol not in selected:
            continue
        source = pd.read_parquet(
            store.root / artifact["path"],
            columns=["symbol", "industry_code", "classification", "start_date", "end_date"],
        )
        source = source[source["classification"].eq("sw_l1")].copy()
        source["start_date"] = pd.to_datetime(source["start_date"]).dt.normalize()
        source["end_date"] = pd.to_datetime(source["end_date"]).dt.normalize()
        rows = []
        for date in dates:
            visible = source[source["start_date"].le(date) & source["end_date"].ge(date)]
            industry = "unknown:%s" % symbol
            if not visible.empty:
                industry = str(visible.sort_values("start_date").iloc[-1]["industry_code"])
            rows.append({"observation_date": date, "symbol": symbol, "industry": industry})
        frames.append(pd.DataFrame(rows))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_or_build_cross_sections(store, portal, schedule, cache_root):
    key, payload = _snapshot_key(store, schedule)
    cache_dir = cache_root / key
    cross_path = cache_dir / "monthly-cross-sections.parquet"
    bars_path = cache_dir / "preselected-bars.parquet"
    audit_path = cache_dir / "audit.json"
    if cross_path.is_file() and bars_path.is_file() and audit_path.is_file():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        if audit.get("key_payload") == payload:
            return pd.read_parquet(cross_path), pd.read_parquet(bars_path), audit["audits"]

    observation_dates = schedule["observation_date"].tolist()
    execution_dates = schedule["execution_date"].tolist()
    valuation_result = build_asof_cross_sections(
        store,
        "daily_valuation",
        observation_dates,
        ["market_cap", "close", "quality_grade"],
        maximum_age_days=10,
    )
    state_result = build_exact_cross_sections(
        store,
        "daily_market_state",
        execution_dates,
        [
            "paused", "is_st", "buy_blocked", "sell_blocked", "raw_close",
            "high_limit", "low_limit", "status_quality", "st_quality", "limit_quality",
        ],
    )
    fundamentals, fundamental_audit = build_fundamental_snapshots(store, observation_dates)
    names_result = build_event_cross_sections(
        store, "st_name_events", execution_dates, ["display_name", "st_quality"]
    )
    delisting_result = build_event_cross_sections(
        store, "delisting_events", execution_dates, ["is_delisting", "quality_grade"]
    )
    master = store.read_parquet("security_master")
    master = master[master["asset_type"].eq("stock")].copy()
    master["start_date"] = pd.to_datetime(master["start_date"]).dt.normalize()
    master["end_date"] = pd.to_datetime(master["end_date"]).dt.normalize()

    schedule_map = schedule.set_index("observation_date")["execution_date"]
    valuation = valuation_result.frame.rename(columns={"close": "raw_close"}).copy()
    valuation["execution_date"] = valuation["observation_date"].map(schedule_map)
    state = state_result.frame.rename(columns={"observation_date": "execution_date"})
    state.drop(columns=["raw_close"], inplace=True)
    names = names_result.frame.rename(
        columns={"observation_date": "execution_date", "st_quality": "name_quality"}
    )
    delisting = delisting_result.frame.rename(
        columns={"observation_date": "execution_date", "quality_grade": "delisting_quality"}
    )
    cross = valuation.merge(state, on=["execution_date", "symbol"], how="left")
    cross = cross.merge(fundamentals, on=["observation_date", "symbol"], how="left")
    cross = cross.merge(
        names[["execution_date", "symbol", "display_name", "name_quality"]],
        on=["execution_date", "symbol"], how="left",
    )
    cross = cross.merge(
        delisting[["execution_date", "symbol", "is_delisting", "delisting_quality"]],
        on=["execution_date", "symbol"], how="left",
    )
    cross = cross.merge(
        master[["symbol", "exchange", "start_date", "end_date"]],
        on="symbol", how="left", validate="many_to_one",
    )
    listed_cutoff = cross["observation_date"] - pd.to_timedelta(MINIMUM_LISTING_DAYS, unit="D")
    cross["state_quality_ab"] = cross[
        ["status_quality", "st_quality", "limit_quality"]
    ].isin(["A", "B"]).all(axis=1)
    cross["eligible_base"] = (
        cross["start_date"].le(listed_cutoff)
        & cross["end_date"].ge(cross["observation_date"])
        & cross["exchange"].isin(["XSHG", "XSHE"])
        & ~cross["symbol"].str.startswith("SH68")
        & pd.to_numeric(cross["market_cap"], errors="coerce").gt(0)
        & cross["paused"].eq(False)
        & cross["is_st"].eq(False)
        & ~cross["buy_blocked"].eq(True)
        & ~cross["display_name"].fillna("").str.contains(r"ST|\*|退", case=False, regex=True)
        & ~cross["is_delisting"].eq(True)
    )
    preselected = []
    for date, group in cross.groupby("observation_date", sort=True):
        eligible = group[
            group["eligible_base"]
            & pd.to_numeric(group["quarter_roe"], errors="coerce").ge(0.10)
            & pd.to_numeric(group["quarter_roa"], errors="coerce").ge(0.05)
        ].sort_values(["market_cap", "symbol"], kind="stable").head(PRESELECT_COUNT)
        preselected.append(eligible)
    cross = pd.concat(preselected, ignore_index=True)
    symbols = sorted(cross["symbol"].unique())
    padded_start = pd.Timestamp(schedule["observation_date"].min()) - pd.Timedelta(days=60)
    bars = portal.bars(
        symbols,
        padded_start,
        schedule["execution_date"].max(),
        fields=("open", "close", "volume", "money"),
        adjustment="pre",
    ).sort_values(["symbol", "trade_date"])
    bars["average_money"] = bars.groupby("symbol")["money"].transform(
        lambda series: series.rolling(20, min_periods=15).mean()
    )
    money = bars[bars["trade_date"].isin(observation_dates)][
        ["symbol", "trade_date", "average_money"]
    ].rename(columns={"trade_date": "observation_date"})
    cross = cross.merge(money, on=["observation_date", "symbol"], how="left")
    industries = build_industry_snapshots(store, symbols, observation_dates)
    cross = cross.merge(industries, on=["observation_date", "symbol"], how="left")
    cross["industry"] = cross["industry"].fillna(
        cross["symbol"].map(lambda value: "unknown:%s" % value)
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    cross.to_parquet(cross_path, index=False)
    bars.to_parquet(bars_path, index=False)
    audits = {
        "valuation": valuation_result.audit,
        "monthly_state": state_result.audit,
        "fundamentals": fundamental_audit,
        "names": names_result.audit,
        "delisting": delisting_result.audit,
        "preselected_unique_symbols": len(symbols),
    }
    audit_path.write_text(
        json.dumps({"key_payload": payload, "audits": audits}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return cross, bars, audits


def build_targets(cross, schedule, config):
    targets = {}
    rows = []
    for item in schedule.itertuples(index=False):
        frame = cross[cross["observation_date"].eq(item.observation_date)]
        symbols = select_candidates(frame, config)
        targets[item.execution_date] = symbols
        for rank, symbol in enumerate(symbols, start=1):
            rows.append(
                {
                    "experiment": config.name,
                    "execution_date": item.execution_date,
                    "observation_date": item.observation_date,
                    "symbol": symbol,
                    "rank": rank,
                }
            )
    return targets, pd.DataFrame(rows)


def risk_exposure_by_date(portal, schedule, config):
    default = {row.execution_date: config.target_exposure for row in schedule.itertuples(index=False)}
    if config.risk_ma_days is None:
        return default
    start = schedule["observation_date"].min() - pd.Timedelta(days=config.risk_ma_days * 2)
    bars = portal.bars(
        ["SH000985"], start, schedule["observation_date"].max(), fields=("close",), adjustment="pre"
    ).sort_values("trade_date")
    bars["moving_average"] = bars["close"].rolling(config.risk_ma_days).mean()
    indexed = bars.set_index("trade_date")
    result = {}
    for row in schedule.itertuples(index=False):
        if row.observation_date not in indexed.index:
            result[row.execution_date] = config.target_exposure
            continue
        point = indexed.loc[row.observation_date]
        risk_on = pd.notna(point["moving_average"]) and point["close"] >= point["moving_average"]
        result[row.execution_date] = (
            config.target_exposure if risk_on else config.risk_off_exposure
        )
    return result


def _segment_metrics(equity, trades, start_date, end_date):
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    segment = equity[equity["trade_date"].between(start, end)].copy()
    if segment.empty:
        return {}
    if trades.empty or "trade_date" not in trades:
        segment_trades = pd.DataFrame()
    else:
        segment_trades = trades[trades["trade_date"].between(start, end)].copy()
    return performance_metrics(segment, segment_trades, trading_days=250)


def run_experiment(config, cross, preselected_bars, store, portal, calendar, schedule, args):
    targets, selections = build_targets(cross, schedule, config)
    symbols = sorted({symbol for values in targets.values() for symbol in values})
    bars = preselected_bars[
        preselected_bars["symbol"].isin(symbols)
        & preselected_bars["trade_date"].isin(calendar)
    ][["symbol", "trade_date", "open", "close", "volume"]].copy()
    state_result = build_exact_cross_sections(
        store,
        "daily_market_state",
        calendar,
        [
            "paused", "is_st", "buy_blocked", "sell_blocked",
            "status_quality", "st_quality", "limit_quality",
        ],
        symbols=symbols,
    )
    state = state_result.frame.rename(columns={"observation_date": "trade_date"})
    actions = build_delisting_actions(
        store.read_parquet("delisting_events"), store.read_parquet("security_master"), bars
    )
    initial_cash = config.initial_cash or args.initial_cash
    engine = DailyBacktester(
        bars,
        state,
        asset_types={symbol: "stock" for symbol in symbols},
        config=BacktestConfig(
            initial_cash=initial_cash,
            maximum_volume_ratio=0.05,
            slippage_rate=config.slippage_rate,
            allow_unknown_st=False,
            minimum_state_quality="C",
        ),
        costs=CostModel(
            buy_commission=0.0003 * config.cost_multiplier,
            sell_commission=0.0003 * config.cost_multiplier,
            minimum_commission=5.0 * config.cost_multiplier,
        ),
        corporate_actions=actions,
    )
    exposures = risk_exposure_by_date(portal, schedule, config)
    for date in calendar:
        if date in targets:
            selected = targets[date]
            exposure = exposures[date]
            weights = {symbol: exposure / len(selected) for symbol in selected} if selected else {}
            engine.rebalance_to_weights(date, weights, execution="close")
        engine.mark_close(date)
    full = performance_metrics(engine.equity, engine.trades, trading_days=250)
    segments = {
        "pre_2019": _segment_metrics(engine.equity, engine.trades, args.start_date, "2018-12-31"),
        "published_2019_2023": _segment_metrics(
            engine.equity, engine.trades, "2019-01-01", "2023-11-30"
        ),
        "post_publication": _segment_metrics(
            engine.equity, engine.trades, POST_PUBLICATION_START, args.end_date
        ),
    }
    return {
        "config": config,
        "metrics": full,
        "segments": segments,
        "equity": engine.equity,
        "trades": engine.trades,
        "orders": engine.orders,
        "rejections": engine.rejections,
        "holdings": engine.holdings,
        "selections": selections,
        "state_audit": state_result.audit,
    }


def flatten_result(result):
    row = {"experiment": result["config"].name, **result["config"].to_dict()}
    for prefix, metrics in [("full", result["metrics"]), *result["segments"].items()]:
        for key in (
            "total_return", "annualized_return", "maximum_drawdown", "sharpe",
            "annualized_volatility", "turnover", "average_cash_ratio",
            "longest_underwater_trading_days",
        ):
            row["%s_%s" % (prefix, key)] = metrics.get(key, math.nan)
    row["trade_count"] = len(result["trades"])
    row["rejection_count"] = len(result["rejections"])
    return row


def build_report(comparison, args):
    display = comparison[
        [
            "experiment", "published_2019_2023_annualized_return",
            "published_2019_2023_maximum_drawdown", "post_publication_annualized_return",
            "post_publication_maximum_drawdown", "full_annualized_return",
            "full_maximum_drawdown", "trade_count", "rejection_count",
        ]
    ].copy()
    for column in display.columns:
        if "return" in column or "drawdown" in column:
            display[column] = display[column].map(
                lambda value: "" if pd.isna(value) else "%.2f%%" % (value * 100)
            )
    return """# 盈利质量小市值本地研究矩阵

## 事实

- 区间：{start} 至 {end}；月末收盘调仓，信号只使用前一交易日或更早记录。
- 原帖发布后样本外从 2023-12-01 开始，参数定义在查看该区间结果之前冻结。
- 行情为 Qlib 连续复权日线，估值和财务为本地点时 B 级数据。
- 2023-07 以后免费涨跌停状态为 C 级规则推导，因此发布后结果是探索证据。
- 所有实验使用股票手续费、历史印花税、100 股整数手、T+1、涨跌停拒单、
  5% 日成交量上限和完整现金/成交账本。

## 对照结果

{table}

## 解释边界

- `published-core` 复现低价、宽松季度 ROE/ROA、10 只最小市值和月末调仓；
  日线无法忠实复现原帖 14:00 涨停开板卖出，因此没有伪造该日内规则。
- 本地与聚宽财务供应商、复权和成交时刻不同；原帖收益只能判断是否方向接近，
  不能仅靠累计收益宣称逐笔复现。
- `post_publication` 是真正的时间样本外，但状态质量较低；应在聚宽重新跑最终源码确认。
""".format(start=args.start_date, end=args.end_date, table=display.to_markdown(index=False))


def run(args):
    store = ResearchDataStore(args.data_root)
    portal = LocalDataPortal(store, QlibDailyBarSource(args.qlib_root))
    calendar, schedule = monthly_last_schedule(portal, args.start_date, args.end_date)
    cache_root = store.snapshot_dir / "profitable-small-cap-rebuild"
    cross, preselected_bars, snapshot_audits = load_or_build_cross_sections(
        store, portal, schedule, cache_root
    )
    configs = experiment_configs()
    if args.experiments:
        requested = set(args.experiments.split(","))
        configs = [config for config in configs if config.name in requested]
        missing = requested.difference(config.name for config in configs)
        if missing:
            raise ValueError("unknown experiments: %s" % sorted(missing))
    result_dir = STUDY_ROOT / "results" / args.run_id
    if result_dir.exists():
        raise FileExistsError("immutable result directory exists: %s" % result_dir)
    raw_dir = result_dir / "raw"
    raw_dir.mkdir(parents=True)
    results = []
    for config in configs:
        result = run_experiment(
            config, cross, preselected_bars, store, portal, calendar, schedule, args
        )
        results.append(result)
        prefix = config.name
        for suffix, frame in (
            ("equity", result["equity"]),
            ("trades", result["trades"]),
            ("orders", result["orders"]),
            ("rejections", result["rejections"]),
            ("holdings", result["holdings"]),
            ("selections", result["selections"]),
        ):
            frame.to_csv(raw_dir / ("%s__%s.csv" % (prefix, suffix)), index=False)
    comparison = pd.DataFrame([flatten_result(result) for result in results])
    comparison.to_csv(raw_dir / "comparison.csv", index=False)
    cross.to_csv(raw_dir / "monthly-candidates.csv", index=False)
    schedule.to_csv(raw_dir / "schedule.csv", index=False)
    shutil.copy2(Path(__file__), result_dir / "source.py")
    shutil.copy2(FAMILY / "baseline.py", result_dir / "platform-candidate.py")
    shutil.copy2(ROOT / "src" / "quant_research" / "backtest.py", result_dir / "engine.py")
    manifest = {
        "schema_version": 1,
        "platform": "local-qlib",
        "study": "profitable-small-cap-rebuild",
        "run_id": args.run_id,
        "period": {"start": args.start_date, "end": args.end_date},
        "post_publication_start": str(POST_PUBLICATION_START.date()),
        "initial_cash": args.initial_cash,
        "experiments": [result["config"].to_dict() for result in results],
        "comparison": comparison.to_dict(orient="records"),
        "data_provenance": [
            dataset_provenance(store, name)
            for name in (
                "security_master", "daily_valuation", "daily_market_state",
                "fundamentals_pit", "industry_membership", "st_name_events", "delisting_events",
            )
        ],
        "snapshot_audits": snapshot_audits,
        "source_sha256": sha256_file(result_dir / "source.py"),
        "platform_candidate_sha256": sha256_file(result_dir / "platform-candidate.py"),
        "engine_sha256": sha256_file(result_dir / "engine.py"),
        "limitations": [
            "post-2023-06 market state is C-grade rule-derived exploratory evidence",
            "continuous adjusted prices stand in for a full corporate-action event feed",
            "published 14:00 intraday limit-open exit is not represented in daily bars",
        ],
    }
    (result_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (result_dir / "report.md").write_text(
        build_report(comparison, args), encoding="utf-8"
    )
    return result_dir


def parse_args():
    parser = argparse.ArgumentParser(description="复现并验证盈利质量小市值策略")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--qlib-root", type=Path, default=DEFAULT_QLIB_ROOT)
    parser.add_argument("--start-date", default="2014-01-02")
    parser.add_argument("--end-date", default="2026-07-23")
    parser.add_argument("--initial-cash", type=float, default=1_000_000)
    parser.add_argument("--experiments", default=None)
    parser.add_argument(
        "--run-id", default="2026-08-02__research-matrix__local-qlib-2014-2026-v1"
    )
    return parser.parse_args()


if __name__ == "__main__":
    print(run(parse_args()))
