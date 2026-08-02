"""原帖可由日线忠实表达的核心规则；仅用于复现对照。"""

# ruff: noqa: F403, F405

import builtins
import datetime

import pandas as pd

try:
    from jqdata import *
except ImportError:
    pass


STOCK_COUNT = 10
MINIMUM_LISTING_DAYS = 250
MAXIMUM_PRICE = 10.0
MINIMUM_QUARTER_ROE = 0.15
MINIMUM_QUARTER_ROA = 0.10
BATCH_SIZE = 300


def initialize(context):
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)
    set_benchmark("000300.XSHG")
    set_slippage(PriceRelatedSlippage(0.004))
    log.set_level("order", "error")
    run_monthly(rebalance, -1, time="14:50", reference_security="000300.XSHG")


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


def historical_universe(observation_date):
    securities = get_all_securities(types=["stock"], date=observation_date)
    cutoff = observation_date - datetime.timedelta(days=MINIMUM_LISTING_DAYS)
    active = securities[
        (securities.start_date <= cutoff) & (securities.end_date >= observation_date)
    ]
    return [
        code
        for code in active.index
        if not code.endswith(".XBSE")
        and not code.startswith("68")
        and not code.startswith("4")
        and not code.startswith("8")
    ]


def observation_closes(codes, observation_date):
    result = {}
    for batch in chunked(codes, BATCH_SIZE):
        frame = get_price(
            batch,
            end_date=observation_date,
            count=1,
            frequency="daily",
            fields=["close"],
            panel=False,
            fill_paused=False,
        )
        if frame is None or frame.empty:
            continue
        if "code" in frame.columns:
            for row in frame.itertuples(index=False):
                result[row.code] = float(row.close)
        elif len(batch) == 1 and "close" in frame.columns:
            value = frame["close"].iloc[-1]
            if pd.notna(value):
                result[batch[0]] = float(value)
    return result


def select_stocks(context):
    observation_date = context.previous_date
    universe = historical_universe(observation_date)
    fundamentals = get_fundamentals(
        query(valuation.code, valuation.market_cap, indicator.roe, indicator.roa)
        .filter(
            valuation.code.in_(universe),
            valuation.market_cap > 0,
            indicator.roe >= MINIMUM_QUARTER_ROE,
            indicator.roa >= MINIMUM_QUARTER_ROA,
        )
        .order_by(valuation.market_cap.asc()),
        date=observation_date,
    )
    if fundamentals is None or fundamentals.empty:
        return []
    codes = fundamentals.head(600)["code"].tolist()
    closes = observation_closes(codes, observation_date)
    current_data = get_current_data()
    result = []
    for code in codes:
        snapshot = current_data[code]
        if snapshot.paused or snapshot.is_st:
            continue
        if "ST" in snapshot.name or "*" in snapshot.name or "退" in snapshot.name:
            continue
        if code not in closes or closes[code] >= MAXIMUM_PRICE:
            continue
        if snapshot.last_price >= snapshot.high_limit:
            continue
        result.append(code)
        if len(result) >= STOCK_COUNT:
            break
    return result


def rebalance(context):
    targets = select_stocks(context)
    if not targets:
        return
    current_data = get_current_data()
    for code in list(context.portfolio.positions.keys()):
        if code in targets:
            continue
        snapshot = current_data[code]
        if not snapshot.paused and snapshot.last_price > snapshot.low_limit:
            order_target(code, 0, MarketOrderStyle(snapshot.low_limit))
    target_value = context.portfolio.total_value / len(targets)
    for code in targets:
        snapshot = current_data[code]
        if snapshot.paused or snapshot.is_st or snapshot.last_price >= snapshot.high_limit:
            continue
        if target_value < snapshot.last_price * 100:
            continue
        order_target_value(code, target_value, MarketOrderStyle(snapshot.high_limit))


def _compatibility_guard():
    return builtins.sum([1]) == 1 and builtins.all([True]) and builtins.any([True])
