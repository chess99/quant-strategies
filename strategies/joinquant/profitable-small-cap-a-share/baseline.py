"""盈利、流动性和分散化约束的小市值 A 股策略。"""

# ruff: noqa: F403, F405

import builtins
import datetime

import pandas as pd

try:
    from jqdata import *
except ImportError:
    pass


STOCK_COUNT = 20
MINIMUM_LISTING_DAYS = 375
MINIMUM_AVERAGE_MONEY = 10_000_000.0
MAXIMUM_INDUSTRY_COUNT = 4
MINIMUM_QUARTER_ROE = 1.0
MINIMUM_QUARTER_ROA = 0.5
PRESELECT_COUNT = 500
MONEY_LOOKBACK = 20
TARGET_EXPOSURE = 0.95
RISK_OFF_EXPOSURE = 0.50
MARKET_MA_DAYS = 120
BATCH_SIZE = 200


def initialize(context):
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)
    set_benchmark("000985.XSHG")
    set_slippage(PriceRelatedSlippage(0.004))
    log.set_level("order", "error")
    run_monthly(rebalance, -1, time="14:50", reference_security="000985.XSHG")


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


def chunked(values, size):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def is_excluded_board(code):
    return code.endswith(".XBSE") or code.startswith("68") or code.startswith("4") or code.startswith("8")


def rank_candidates(rows, stock_count, maximum_industry_count):
    selected = []
    industry_counts = {}
    for row in sorted(rows, key=lambda item: (item["score"], item["code"])):
        industry = row["industry"]
        count = industry_counts[industry] if industry in industry_counts else 0
        if count >= maximum_industry_count:
            continue
        selected.append(row["code"])
        industry_counts[industry] = count + 1
        if len(selected) >= stock_count:
            break
    return selected


def _historical_universe(observation_date):
    securities = get_all_securities(types=["stock"], date=observation_date)
    cutoff = observation_date - datetime.timedelta(days=MINIMUM_LISTING_DAYS)
    active = securities[
        (securities.start_date <= cutoff) & (securities.end_date >= observation_date)
    ]
    return [code for code in active.index if not is_excluded_board(code)]


def _fundamental_candidates(observation_date, universe):
    data = get_fundamentals(
        query(
            valuation.code,
            valuation.market_cap,
            indicator.roe,
            indicator.roa,
        )
        .filter(
            valuation.code.in_(universe),
            valuation.market_cap > 0,
            indicator.roe >= MINIMUM_QUARTER_ROE,
            indicator.roa >= MINIMUM_QUARTER_ROA,
        )
        .order_by(valuation.market_cap.asc()),
        date=observation_date,
    )
    if data is None or data.empty:
        return pd.DataFrame(columns=["code", "market_cap", "roe", "roa"])
    return data.head(PRESELECT_COUNT).copy()


def _average_money(codes, observation_date):
    result = {}
    for batch in chunked(codes, BATCH_SIZE):
        prices = get_price(
            batch,
            end_date=observation_date,
            count=MONEY_LOOKBACK,
            frequency="daily",
            fields=["money"],
            panel=False,
            fill_paused=False,
        )
        if prices is None or prices.empty:
            continue
        if "code" in prices.columns:
            grouped = prices.groupby("code")["money"].mean()
            for code, value in grouped.items():
                if pd.notna(value):
                    result[code] = float(value)
        elif len(batch) == 1 and "money" in prices.columns:
            value = prices["money"].mean()
            if pd.notna(value):
                result[batch[0]] = float(value)
    return result


def _industry_labels(codes, observation_date):
    raw = get_industry(codes, date=observation_date)
    result = {}
    for code in codes:
        label = "unknown:%s" % code
        item = raw[code] if code in raw else {}
        for key in ("sw_l1", "jq_l1"):
            if key not in item or not item[key]:
                continue
            value = item[key]
            if isinstance(value, dict):
                if "industry_code" in value:
                    label = value["industry_code"]
                elif "industry_name" in value:
                    label = value["industry_name"]
            else:
                label = str(value)
            break
        result[code] = label
    return result


def select_stocks(context):
    observation_date = context.previous_date
    universe = _historical_universe(observation_date)
    fundamentals = _fundamental_candidates(observation_date, universe)
    if fundamentals.empty:
        return []
    codes = fundamentals["code"].tolist()
    average_money = _average_money(codes, observation_date)
    industries = _industry_labels(codes, observation_date)
    current_data = get_current_data()
    rows = []
    for record in fundamentals.itertuples(index=False):
        code = record.code
        snapshot = current_data[code]
        if snapshot.paused or snapshot.is_st:
            continue
        if "ST" in snapshot.name or "*" in snapshot.name or "退" in snapshot.name:
            continue
        if snapshot.last_price >= snapshot.high_limit:
            continue
        if code not in average_money or average_money[code] < MINIMUM_AVERAGE_MONEY:
            continue
        rows.append(
            {
                "code": code,
                "industry": industries[code],
                "score": float(record.market_cap),
            }
        )
    return rank_candidates(rows, STOCK_COUNT, MAXIMUM_INDUSTRY_COUNT)


def _sell_non_targets(context, targets, current_data):
    for code in list(context.portfolio.positions.keys()):
        if code in targets:
            continue
        snapshot = current_data[code]
        if snapshot.paused or snapshot.last_price <= snapshot.low_limit:
            continue
        order_target(code, 0, MarketOrderStyle(snapshot.low_limit))


def _market_exposure(context):
    prices = get_price(
        "000985.XSHG",
        end_date=context.previous_date,
        count=MARKET_MA_DAYS,
        frequency="daily",
        fields=["close"],
        panel=False,
        fill_paused=False,
    )
    if prices is None or len(prices) < MARKET_MA_DAYS:
        return RISK_OFF_EXPOSURE
    closes = pd.to_numeric(prices["close"], errors="coerce").dropna()
    if len(closes) < MARKET_MA_DAYS:
        return RISK_OFF_EXPOSURE
    return TARGET_EXPOSURE if closes.iloc[-1] >= closes.mean() else RISK_OFF_EXPOSURE


def _deployable_value(context, targets, exposure):
    value = context.portfolio.available_cash
    for code in targets:
        if code in context.portfolio.positions:
            value += context.portfolio.positions[code].value
    return value * exposure


def rebalance(context):
    targets = select_stocks(context)
    if not targets:
        log.warn("没有满足点时、质量和流动性门槛的候选，保留现有持仓")
        return
    current_data = get_current_data()
    _sell_non_targets(context, targets, current_data)
    exposure = _market_exposure(context)
    target_value = _deployable_value(context, targets, exposure) / len(targets)
    for code in targets:
        snapshot = current_data[code]
        if snapshot.paused or snapshot.is_st or snapshot.last_price >= snapshot.high_limit:
            continue
        if target_value < snapshot.last_price * 100:
            continue
        order_target_value(
            code,
            target_value,
            MarketOrderStyle(snapshot.high_limit),
        )


def _compatibility_guard():
    return builtins.sum([1]) == 1 and builtins.all([True]) and builtins.any([True])
