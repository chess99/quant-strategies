"""聚宽侧全市场价值质量黄金对照策略。"""

# ruff: noqa: F403, F405

from jqdata import *
import builtins
import datetime
import pandas as pd


def initialize(context):
    set_option("avoid_future_data", True)
    set_option("use_real_price", True)
    set_benchmark("000300.XSHG")
    set_slippage(FixedSlippage(0.002))
    log.set_level("order", "error")
    g.holdings = 20
    g.maximum_per_industry = 3
    g.minimum_listing_days = 375
    g.capture_month = None
    run_monthly(rebalance, 1, time="open", reference_security="000300.XSHG")


def before_trading_start(context):
    tax = 0.0005 if context.current_dt.date() >= datetime.date(2023, 8, 28) else 0.001
    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=tax,
            open_commission=0.0003,
            close_commission=0.0003,
            close_today_commission=0,
            min_commission=5,
        ),
        type="stock",
    )


def _chunks(values, size):
    for position in range(0, len(values), size):
        yield values[position : position + size]


def _industry_map(codes, observation_date):
    result = {}
    for batch in _chunks(codes, 300):
        payload = get_industry(batch, date=observation_date)
        for code in batch:
            entry = payload.get(code) or {}
            sw_l1 = entry.get("sw_l1") or {}
            industry_code = sw_l1.get("industry_code") or sw_l1.get("industry_name")
            if industry_code:
                result[code] = str(industry_code)
    return result


def _fundamentals(codes, observation_date):
    frames = []
    for batch in _chunks(codes, 300):
        frame = get_fundamentals(
            query(
                valuation.code,
                valuation.market_cap,
                valuation.pe_ratio,
                valuation.pb_ratio,
                valuation.ps_ratio,
                indicator.roe,
                indicator.roa,
                indicator.gross_profit_margin,
                indicator.net_profit_margin,
                balance.total_assets,
                balance.total_liability,
                cash_flow.net_operate_cash_flow,
            ).filter(valuation.code.in_(batch)),
            date=observation_date,
        )
        if frame is not None and not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame()
    data = pd.concat(frames, ignore_index=True)
    data.rename(
        columns={
            "code": "symbol",
            "pe_ratio": "pe_ttm",
            "pb_ratio": "pb",
            "ps_ratio": "ps",
            "total_liability": "total_liabilities",
            "net_operate_cash_flow": "operating_cash_flow",
        },
        inplace=True,
    )
    return data


def _rank_within_industry(frame, column, ascending):
    global_rank = frame[column].rank(pct=True, ascending=ascending)
    industry_size = frame.groupby("industry_code")[column].transform("count")
    industry_rank = frame.groupby("industry_code")[column].rank(
        pct=True, ascending=ascending
    )
    return industry_rank.where(industry_size >= 5, global_rank)


def _score(data):
    numeric = [
        "pe_ttm",
        "pb",
        "ps",
        "roe",
        "roa",
        "gross_profit_margin",
        "net_profit_margin",
        "total_assets",
        "total_liabilities",
        "operating_cash_flow",
    ]
    for column in numeric:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data["debt_to_assets"] = data["total_liabilities"] / data["total_assets"]
    data = data[
        data["pe_ttm"].between(0.01, 100.0)
        & data["pb"].between(0.01, 20.0)
        & data["ps"].between(0.01, 30.0)
        & data["roe"].between(0.0, 100.0)
        & data["roa"].between(0.0, 100.0)
        & data["gross_profit_margin"].between(-100.0, 100.0)
        & data["net_profit_margin"].between(0.0, 100.0)
        & (data["total_assets"] > 0.0)
        & data["debt_to_assets"].between(0.0, 1.5)
        & (data["operating_cash_flow"] > 0.0)
        & data["industry_code"].notnull()
    ].copy()
    if data.empty:
        return data
    for column in ("pe_ttm", "pb", "ps"):
        data[column + "_score"] = _rank_within_industry(data, column, False)
    for column in ("roe", "roa", "gross_profit_margin", "net_profit_margin"):
        data[column + "_score"] = _rank_within_industry(data, column, True)
    data["leverage_score"] = _rank_within_industry(data, "debt_to_assets", False)
    data["value_score"] = data[["pe_ttm_score", "pb_score", "ps_score"]].mean(axis=1)
    data["quality_score"] = data[
        [
            "roe_score",
            "roa_score",
            "gross_profit_margin_score",
            "net_profit_margin_score",
            "leverage_score",
        ]
    ].mean(axis=1)
    data["score"] = 0.5 * data["value_score"] + 0.5 * data["quality_score"]
    return data.sort_values(["score", "symbol"], ascending=[False, True])


def _candidates(context):
    observation_date = context.previous_date
    securities = get_all_securities(types=["stock"], date=observation_date)
    cutoff = observation_date - datetime.timedelta(days=g.minimum_listing_days)
    securities = securities[
        (securities.start_date <= cutoff) & (securities.end_date >= observation_date)
    ]
    universe = sorted(
        code for code in securities.index if not code.endswith(".XBSE")
    )
    current = get_current_data()
    eligible = []
    for code in universe:
        item = current[code]
        if item.paused or item.is_st or "退" in item.name:
            continue
        eligible.append(code)
    industries = _industry_map(eligible, observation_date)
    data = _fundamentals(eligible, observation_date)
    if data.empty:
        return [], 0, len(universe)
    data = data[data["symbol"].isin(eligible)].copy()
    data["industry_code"] = data["symbol"].map(industries)
    ranked = _score(data)
    targets = []
    counts = {}
    for row in ranked.itertuples(index=False):
        industry = str(row.industry_code)
        if counts.get(industry, 0) >= g.maximum_per_industry:
            continue
        targets.append(row.symbol)
        counts[industry] = counts.get(industry, 0) + 1
        if len(targets) == g.holdings:
            break
    return targets, len(ranked), len(universe)


def _log_order(execution_date, side, code, order):
    if order is None:
        log.info("QR_ORDER|%s|%s|%s|none" % (execution_date, side, code))
        return
    log.info(
        "QR_ORDER|%s|%s|%s|%s|%s|%s"
        % (execution_date, side, code, order.amount, order.filled, order.status)
    )


def rebalance(context):
    execution_date = context.current_dt.strftime("%Y-%m-%d")
    observation_date = context.previous_date.strftime("%Y-%m-%d")
    targets, candidate_count, universe_count = _candidates(context)
    log.info(
        "QR_CANDIDATES|%s|%s|%s|%s|%s"
        % (
            execution_date,
            observation_date,
            universe_count,
            candidate_count,
            ",".join(targets),
        )
    )
    for code in sorted(list(context.portfolio.positions.keys())):
        if code not in targets:
            _log_order(execution_date, "sell", code, order_target(code, 0))
    if targets:
        target_value = context.portfolio.total_value / len(targets)
        for code in targets:
            _log_order(
                execution_date,
                "target",
                code,
                order_target_value(code, target_value),
            )
    g.capture_month = context.current_dt.strftime("%Y-%m")


def after_trading_end(context):
    if g.capture_month != context.current_dt.strftime("%Y-%m"):
        return
    execution_date = context.current_dt.strftime("%Y-%m-%d")
    positions = sorted(list(context.portfolio.positions.keys()))
    log.info(
        "QR_HOLDINGS|%s|%s|%s|%.6f"
        % (execution_date, len(positions), ",".join(positions), context.portfolio.total_value)
    )
    g.capture_month = None


def _compatibility_guard():
    return builtins.sum([1]) == 1 and builtins.all([True]) and builtins.any([True])
