# ruff: noqa: F403, F405
"""基于全国社保基金前十大流通股东披露的聚宽 A 股策略。

策略在一季报、半年报和三季报披露完成后，汇总同一股票的多个社保组合持股，
按披露持股数量乘以前一交易日收盘价排序，选择目标股票等权持有。
"""

from datetime import date

import pandas as pd

try:
    from jqdata import *  # noqa: F403
except ImportError:
    pass


BENCHMARK = "000300.XSHG"
TARGET_COUNT = 10
MIN_LISTING_DAYS = 365
BOARD_LOT = 100


def initialize(context):
    """设置回测参数和一年三次的卖出、买入调度。"""
    set_benchmark(BENCHMARK)
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)
    set_slippage(FixedSlippage(0.002))
    set_order_cost(
        OrderCost(
            close_tax=0.001,
            open_commission=0.0003,
            close_commission=0.0003,
            min_commission=5,
        ),
        type="stock",
    )

    g.stock_count = TARGET_COUNT
    run_monthly(
        sell_before_rebalance,
        monthday=-1,
        time="14:50",
        reference_security=BENCHMARK,
    )
    run_monthly(
        buy_after_disclosure,
        monthday=1,
        time="09:31",
        reference_security=BENCHMARK,
    )


def get_report_date(buy_date):
    """根据买入月份返回当次允许使用的报告期。"""
    month_day = {5: (3, 31), 9: (6, 30), 11: (9, 30)}.get(buy_date.month)
    if month_day is None:
        return None
    return date(buy_date.year, month_day[0], month_day[1])


def aggregate_holdings(rows):
    """保留最新修订记录，并汇总同一股票的多个社保组合持股。"""
    if rows is None or rows.empty:
        return pd.Series(dtype="float64")

    data = rows.copy()
    data["pub_date"] = pd.to_datetime(data["pub_date"])
    data["share_number"] = pd.to_numeric(data["share_number"], errors="coerce")
    data.dropna(
        subset=["code", "shareholder_name", "share_number", "pub_date"],
        inplace=True,
    )
    data.sort_values("pub_date", inplace=True)
    data.drop_duplicates(
        ["code", "shareholder_name"],
        keep="last",
        inplace=True,
    )
    return data.groupby("code")["share_number"].sum()


def rank_holdings(holdings, close_prices, eligible_codes, stock_count):
    """按社保披露持仓市值降序返回前 stock_count 只股票。"""
    eligible = set(eligible_codes)
    market_values = {
        code: float(shares) * float(close_prices[code])
        for code, shares in holdings.items()
        if code in eligible
        and code in close_prices
        and float(close_prices[code]) > 0
    }
    ranked = sorted(market_values.items(), key=lambda item: (-item[1], item[0]))
    return [code for code, _ in ranked[:stock_count]]


def get_social_security_holdings(report_date, buy_date):
    """查询指定报告期且在买入日前已经公告的社保基金持股。"""
    table = finance.STK_SHAREHOLDER_FLOATING_TOP10
    query_object = query(
        table.code,
        table.shareholder_name,
        table.share_number,
        table.pub_date,
    ).filter(
        table.end_date == report_date,
        table.pub_date < buy_date,
        table.shareholder_name.like("%社保基金%"),
    )
    rows = finance.run_query(query_object)
    log.info("社保流通股东原始记录=%d", 0 if rows is None else len(rows))
    return aggregate_holdings(rows)


def get_previous_closes(codes, observation_date):
    """批量取得观察日收盘价并转换为代码到价格的映射。"""
    if not codes:
        return {}

    prices = get_price(
        codes,
        end_date=observation_date,
        count=1,
        frequency="daily",
        fields=["close"],
        skip_paused=False,
        panel=False,
    )
    if prices is None or prices.empty or "close" not in prices.columns:
        return {}

    if "code" not in prices.columns:
        if len(codes) == 1:
            close = prices["close"].dropna()
            return {codes[0]: float(close.iloc[-1])} if not close.empty else {}
        return {}

    latest = prices.dropna(subset=["code", "close"]).drop_duplicates(
        "code",
        keep="last",
    )
    return {
        str(row.code): float(row.close)
        for row in latest[["code", "close"]].itertuples(index=False)
    }


def get_current_snapshot(current_data, code):
    """按聚宽要求用下标触发当前行情的惰性加载。"""
    try:
        return current_data[code]
    except (KeyError, TypeError):
        return None


def filter_stocks(codes, current_data, security_frame, buy_date):
    """剔除不可交易、风险标的、北交所和上市不满一年的股票。"""
    eligible = []
    skipped_market = 0
    skipped_recent = 0
    skipped_risk = 0
    skipped_price = 0
    for code in codes:
        if code.endswith(".XBJ") or code not in security_frame.index:
            skipped_market += 1
            continue

        start_date = pd.Timestamp(security_frame.loc[code, "start_date"]).date()
        if (buy_date - start_date).days < MIN_LISTING_DAYS:
            skipped_recent += 1
            continue

        snapshot = get_current_snapshot(current_data, code)
        if snapshot is None or snapshot.paused or snapshot.is_st:
            skipped_risk += 1
            continue

        name = str(snapshot.name)
        if "ST" in name.upper() or "退" in name:
            skipped_risk += 1
            continue

        if pd.isna(snapshot.last_price) or snapshot.last_price <= 0:
            skipped_price += 1
            continue
        if snapshot.last_price >= snapshot.high_limit:
            skipped_price += 1
            continue

        eligible.append(code)

    log.info(
        "股票过滤：输入=%d，可买=%d，北交所/无证券信息=%d，上市不足一年=%d，"
        "停牌/ST/退市=%d，价格无效/涨停=%d",
        len(codes),
        len(eligible),
        skipped_market,
        skipped_recent,
        skipped_risk,
        skipped_price,
    )
    return eligible


def calculate_target_stocks(context):
    """串联聚宽数据接口，生成本期目标股票。"""
    buy_date = context.current_dt.date()
    report_date = get_report_date(buy_date)
    if report_date is None:
        return []

    holdings = get_social_security_holdings(report_date, buy_date)
    if holdings.empty:
        log.warn("报告期 %s 未查询到已公告的社保基金持股，保持现金", report_date)
        return []

    observation_date = context.previous_date
    codes = list(holdings.index)
    securities = get_all_securities(types=["stock"], date=observation_date)
    current_data = get_current_data()
    eligible = filter_stocks(codes, current_data, securities, buy_date)
    closes = get_previous_closes(eligible, observation_date)
    targets = rank_holdings(
        holdings,
        closes,
        eligible,
        getattr(g, "stock_count", TARGET_COUNT),
    )

    log.info(
        "报告期=%s，聚合股票=%d，过滤后候选=%d，最终目标=%d",
        report_date,
        len(holdings),
        len(eligible),
        len(targets),
    )
    if not targets:
        log.warn("没有可买入目标，保持现金")
    return targets


def sell_before_rebalance(context):
    """在 4、8、10 月最后一个交易日卖出可卖的旧组合。"""
    if context.current_dt.month not in {4, 8, 10}:
        return

    current_data = get_current_data()
    for code in list(context.portfolio.positions.keys()):
        snapshot = get_current_snapshot(current_data, code)
        if (
            snapshot is None
            or snapshot.paused
            or pd.isna(snapshot.last_price)
            or snapshot.last_price <= snapshot.low_limit
        ):
            log.warn("%s 停牌、无行情或跌停，月底暂时无法卖出", code)
            continue
        try:
            order_target_value(code, 0)
        except Exception as error:
            log.error("%s 月底卖出失败：%s", code, error)


def buy_after_disclosure(context):
    """在 5、9、11 月第一个交易日读取完整公告并买入。"""
    if context.current_dt.month not in {5, 9, 11}:
        return

    targets = calculate_target_stocks(context)
    if not targets:
        log.warn("本期没有目标股票，不提交买单")
        return
    adjust_positions(context, targets)


def adjust_positions(context, target_stocks):
    """处理残留旧仓，并把可投资资产等权分配给目标股票。"""
    if not target_stocks:
        return

    current_data = get_current_data()
    target_set = set(target_stocks)
    blocked_residual_value = 0.0

    for code, position in list(context.portfolio.positions.items()):
        if code in target_set:
            continue

        snapshot = get_current_snapshot(current_data, code)
        cannot_sell = (
            snapshot is None
            or snapshot.paused
            or pd.isna(snapshot.last_price)
            or snapshot.last_price <= snapshot.low_limit
        )
        if cannot_sell:
            blocked_residual_value += float(position.value)
            log.warn("%s 仍无法卖出，按残留市值扣减可投资资金", code)
            continue

        try:
            order_target_value(code, 0)
        except Exception as error:
            blocked_residual_value += float(position.value)
            log.error("%s 残留仓位卖出失败：%s", code, error)

    investable_value = max(
        float(context.portfolio.total_value) - blocked_residual_value,
        0.0,
    )
    target_value = investable_value / len(target_stocks)
    log.info(
        "组合总资产=%.2f，受阻残留=%.2f，目标数=%d，单只目标市值=%.2f",
        context.portfolio.total_value,
        blocked_residual_value,
        len(target_stocks),
        target_value,
    )

    for code in target_stocks:
        snapshot = get_current_snapshot(current_data, code)
        if (
            snapshot is None
            or snapshot.paused
            or snapshot.is_st
            or pd.isna(snapshot.last_price)
            or snapshot.last_price <= 0
            or snapshot.last_price >= snapshot.high_limit
        ):
            log.warn("%s 当前不可买入，跳过目标仓位", code)
            continue
        minimum_value = float(snapshot.last_price) * BOARD_LOT
        if target_value < minimum_value:
            log.warn(
                "%s 单只目标市值 %.2f 不足一手 %.2f，跳过买入",
                code,
                target_value,
                minimum_value,
            )
            continue
        try:
            order_target_value(code, target_value)
        except Exception as error:
            log.error("%s 目标仓位下单失败：%s", code, error)
