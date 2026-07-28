"""聚宽侧全市场小市值黄金对照策略。"""

# ruff: noqa: F403, F405

from jqdata import *
import builtins
import datetime


def initialize(context):
    set_option("avoid_future_data", True)
    set_option("use_real_price", True)
    set_benchmark("000985.XSHG")
    set_slippage(FixedSlippage(0))
    log.set_level("order", "error")
    g.stock_count = 10
    g.minimum_listing_days = 375
    g.capture_month = None
    run_monthly(rebalance, 1, time="open", reference_security="000985.XSHG")


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


def _candidate_codes(context):
    observation_date = context.previous_date
    securities = get_all_securities(types=["stock"], date=observation_date)
    cutoff = observation_date - datetime.timedelta(days=g.minimum_listing_days)
    securities = securities[
        (securities.start_date <= cutoff) & (securities.end_date >= observation_date)
    ]
    universe = {code for code in securities.index if not code.endswith(".XBSE")}
    fundamentals = get_fundamentals(
        query(valuation.code, valuation.market_cap)
        .filter(valuation.market_cap > 0)
        .order_by(valuation.market_cap.asc()),
        date=observation_date,
    )
    current = get_current_data()
    result = []
    for code in fundamentals.code:
        if code not in universe:
            continue
        item = current[code]
        if item.paused or item.is_st or "退" in item.name:
            continue
        result.append(code)
        if len(result) >= 50:
            break
    return result, len(universe)


def _order_record(side, code, order):
    if order is None:
        return "%s,%s,none" % (side, code)
    return "%s,%s,%s,%s,%s" % (
        side,
        code,
        order.amount,
        order.filled,
        order.status,
    )


def rebalance(context):
    execution_date = context.current_dt.strftime("%Y-%m-%d")
    observation_date = context.previous_date.strftime("%Y-%m-%d")
    candidates, universe_count = _candidate_codes(context)
    targets = candidates[: g.stock_count]
    log.info(
        "QR_CANDIDATES|%s|%s|%s|%s|%s"
        % (execution_date, observation_date, universe_count, len(candidates), ",".join(candidates))
    )
    current = get_current_data()
    order_records = []
    for code in sorted(list(context.portfolio.positions.keys())):
        if code not in targets:
            order_records.append(
                _order_record(
                    "sell",
                    code,
                    order_target(
                        code,
                        0,
                        MarketOrderStyle(current[code].low_limit),
                    ),
                )
            )
    if targets:
        target_value = context.portfolio.total_value / len(targets)
        for code in targets:
            order_records.append(
                _order_record(
                    "target",
                    code,
                    order_target_value(
                        code,
                        target_value,
                        MarketOrderStyle(current[code].high_limit),
                    ),
                ),
            )
    log.info("QR_ORDERS|%s|%s" % (execution_date, ";".join(order_records)))
    g.capture_month = context.current_dt.strftime("%Y-%m")


def after_trading_end(context):
    if g.capture_month != context.current_dt.strftime("%Y-%m"):
        return
    execution_date = context.current_dt.strftime("%Y-%m-%d")
    positions = sorted(list(context.portfolio.positions.keys()))
    log.info(
        "QR_HOLDINGS|%s|%s|%s|%.6f"
        % (
            execution_date,
            len(positions),
            ",".join(positions),
            context.portfolio.total_value,
        )
    )
    g.capture_month = None


def _compatibility_guard():
    # 明确使用 builtins，避免 from jqdata import * 覆盖 Python 内建函数。
    return builtins.sum([1]) == 1 and builtins.all([True]) and builtins.any([True])
