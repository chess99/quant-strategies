# -*- coding: utf-8 -*-
# ruff: noqa: F403, F405
"""ETF Flow Dislocation v1 — JoinQuant research baseline.

ETF share contraction is used as a mechanical-flow/liquidity-pressure proxy. It is
not proof that the fund directly sold its underlying shares because ETF redemption
may use in-kind delivery or cash substitution.
"""

import builtins
import math
from datetime import timedelta

import numpy as np
import pandas as pd
from jqdata import *
from jqdata import finance


def initialize(context):
    set_option("avoid_future_data", True)
    set_option("use_real_price", True)
    set_benchmark("000300.XSHG")
    set_slippage(PriceRelatedSlippage(0.002), type="fund")
    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=0,
            open_commission=0.0003,
            close_commission=0.0003,
            close_today_commission=0,
            min_commission=5,
        ),
        type="fund",
    )
    log.set_level("order", "error")
    log.set_level("system", "error")

    # Frozen coarse parameters. They are hypotheses, not historical optima.
    g.flow_lookback = 20
    g.return_lookback = 20
    g.reversal_lookback = 3
    g.drawdown_lookback = 60
    g.max_flow_20 = -0.05
    g.max_return_20 = -0.08
    g.max_drawdown_60 = -0.12
    g.min_reversal_3 = 0.0
    g.require_above_ma5 = True

    g.max_positions = 3
    g.active_budget = 0.75
    g.max_single_weight = 0.30
    g.min_listing_calendar_days = 240
    g.min_adv20 = 30_000_000
    g.max_adv_participation = 0.005
    g.min_hold_calendar_days = 10
    g.max_hold_calendar_days = 60
    g.take_profit = 0.15
    g.stop_loss = -0.12
    g.normalized_drawdown = -0.04
    g.normalized_return_20 = 0.08
    g.normalized_flow_20 = 0.05
    g.cash_etf = "511880.XSHG"
    g.min_trade_value = 2000
    g.min_weight_change = 0.03
    g.entry_meta = {}

    g.exclude_keywords = [
        "货币", "现金", "短融", "国债", "政金债", "信用债", "债券", "转债",
        "同业存单", "黄金", "白银", "原油", "商品", "纳指", "纳斯达克", "标普",
        "道琼斯", "日经", "德国", "法国", "沙特", "恒生", "港股", "香港", "中概",
        "H股", "海外", "中韩", "REIT", "Reit", "reit",
    ]

    run_weekly(
        rebalance,
        weekday=1,
        time="10:30",
        reference_security="510300.XSHG",
    )


def rebalance(context):
    as_of = context.previous_date
    universe, adv20 = build_universe(as_of)
    held = [
        code for code, pos in context.portfolio.positions.items()
        if pos.total_amount > 0 and code != g.cash_etf
    ]
    requested = sorted(set(universe + held))
    metrics = compute_metrics(requested, as_of)
    selected = select_assets(context, metrics)
    weights = build_weights(context, selected, metrics, adv20)
    remaining = max(0.0, 1.0 - builtins.sum(weights.values()))
    if remaining > 1e-8:
        weights[g.cash_etf] = remaining
    execute_targets(context, weights)
    refresh_entry_meta(context, selected)


def build_universe(as_of):
    securities = get_all_securities(["etf"], date=as_of)
    min_start = as_of - timedelta(days=g.min_listing_calendar_days)
    raw = []
    for code, row in securities.iterrows():
        try:
            if row["start_date"] > min_start or code == g.cash_etf:
                continue
        except Exception:
            continue
        raw.append(code)

    tracking = tracking_map(raw, as_of)
    preliminary = []
    for code in raw:
        item = tracking.get(code)
        if not item or not item["index_code"]:
            continue
        text = "%s %s" % (securities.loc[code, "display_name"], item["index_name"])
        if builtins.any(keyword in text for keyword in g.exclude_keywords):
            continue
        preliminary.append(code)

    adv, counts = adv20_map(preliminary, as_of)
    liquid = [
        code for code in preliminary
        if counts.get(code, 0) >= 15 and adv.get(code, 0) >= g.min_adv20
    ]

    best = {}
    for code in liquid:
        index_code = tracking[code]["index_code"]
        incumbent = best.get(index_code)
        if incumbent is None or adv.get(code, 0) > adv.get(incumbent, 0):
            best[index_code] = code
    codes = sorted(best.values())
    return codes, {code: adv[code] for code in codes}


def tracking_map(codes, as_of):
    rows = []
    for offset in range(0, len(codes), 250):
        batch = codes[offset:offset + 250]
        q = query(
            finance.FUND_INVEST_TARGET.code,
            finance.FUND_INVEST_TARGET.pub_date,
            finance.FUND_INVEST_TARGET.start_date,
            finance.FUND_INVEST_TARGET.end_date,
            finance.FUND_INVEST_TARGET.traced_index_name,
            finance.FUND_INVEST_TARGET.traced_index_code,
        ).filter(
            finance.FUND_INVEST_TARGET.code.in_(batch),
            finance.FUND_INVEST_TARGET.pub_date <= as_of,
            finance.FUND_INVEST_TARGET.start_date <= as_of,
        ).limit(5000)
        frame = finance.run_query(q)
        if frame is not None and not frame.empty:
            rows.append(frame)
    if not rows:
        return {}

    frame = pd.concat(rows, ignore_index=True)
    frame["pub_date"] = pd.to_datetime(frame["pub_date"], errors="coerce")
    frame["start_date"] = pd.to_datetime(frame["start_date"], errors="coerce")
    frame["end_date"] = pd.to_datetime(frame["end_date"], errors="coerce")
    as_of_ts = pd.Timestamp(as_of)
    frame = frame[(frame["end_date"].isna()) | (frame["end_date"] >= as_of_ts)]
    frame = frame.sort_values(["code", "start_date", "pub_date"])
    frame = frame.groupby("code", as_index=False).tail(1)
    out = {}
    for _, row in frame.iterrows():
        out[row["code"]] = {
            "index_code": row["traced_index_code"],
            "index_name": "" if pd.isna(row["traced_index_name"]) else str(row["traced_index_name"]),
        }
    return out


def adv20_map(codes, as_of):
    adv = {}
    counts = {}
    for offset in range(0, len(codes), 200):
        batch = codes[offset:offset + 200]
        frame = get_price(
            batch,
            end_date=as_of,
            count=20,
            frequency="daily",
            fields=["money"],
            panel=False,
            skip_paused=True,
            fq="pre",
        )
        if frame is None or frame.empty:
            continue
        if "code" not in frame.columns:
            if len(batch) != 1:
                continue
            frame = frame.copy()
            frame["code"] = batch[0]
        grouped = frame.groupby("code")["money"]
        for code, value in grouped.mean().items():
            if pd.notna(value):
                adv[code] = float(value)
        for code, value in grouped.count().items():
            counts[code] = int(value)
    return adv, counts


def price_matrix(codes, as_of):
    pieces = []
    for offset in range(0, len(codes), 200):
        batch = codes[offset:offset + 200]
        frame = get_price(
            batch,
            end_date=as_of,
            count=61,
            frequency="daily",
            fields=["close"],
            panel=False,
            skip_paused=True,
            fq="pre",
        )
        if frame is None or frame.empty:
            continue
        if "code" not in frame.columns:
            if len(batch) != 1:
                continue
            frame = frame.copy()
            frame["code"] = batch[0]
        pieces.append(frame[["time", "code", "close"]])
    if not pieces:
        return pd.DataFrame()
    frame = pd.concat(pieces, ignore_index=True)
    return frame.pivot_table(index="time", columns="code", values="close", aggfunc="last").sort_index()


def share_map(codes, as_of):
    start = as_of - timedelta(days=125)
    rows = []
    for offset in range(0, len(codes), 40):
        batch = codes[offset:offset + 40]
        q = query(
            finance.FUND_SHARE_DAILY.code,
            finance.FUND_SHARE_DAILY.date,
            finance.FUND_SHARE_DAILY.shares,
        ).filter(
            finance.FUND_SHARE_DAILY.code.in_(batch),
            finance.FUND_SHARE_DAILY.date >= start,
            finance.FUND_SHARE_DAILY.date <= as_of,
        ).limit(5000)
        frame = finance.run_query(q)
        if frame is not None and not frame.empty:
            rows.append(frame)
    if not rows:
        return {}
    frame = pd.concat(rows, ignore_index=True)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["shares"] = pd.to_numeric(frame["shares"], errors="coerce")
    frame = frame.dropna(subset=["date", "shares"]).sort_values(["code", "date"])
    result = {}
    for code, group in frame.groupby("code"):
        values = group["shares"].values.astype(float)
        if len(values) >= 21:
            result[code] = values[-21:]
    return result


def compute_metrics(codes, as_of):
    if not codes:
        return pd.DataFrame()
    prices = price_matrix(codes, as_of)
    shares = share_map(codes, as_of)
    rows = []
    for code in codes:
        if code not in prices.columns or code not in shares:
            continue
        close = prices[code].dropna().values.astype(float)
        flow = shares[code]
        if len(close) < 61 or len(flow) < 21:
            continue
        if close[-21] <= 0 or flow[-21] <= 0:
            continue
        ret20 = close[-1] / close[-21] - 1.0
        flow20 = flow[-1] / flow[-21] - 1.0
        reversal3 = close[-1] / close[-4] - 1.0
        drawdown60 = close[-1] / float(np.max(close[-61:])) - 1.0
        above_ma5 = close[-1] >= float(np.mean(close[-5:]))
        daily = close[-21:][1:] / close[-21:][:-1] - 1.0
        vol20 = max(float(np.std(daily, ddof=1) * math.sqrt(252.0)), 0.08)
        rows.append({
            "code": code,
            "flow20": flow20,
            "ret20": ret20,
            "reversal3": reversal3,
            "drawdown60": drawdown60,
            "above_ma5": bool(above_ma5),
            "vol20": vol20,
        })
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows).set_index("code")
    frame["eligible"] = (
        (frame["flow20"] <= g.max_flow_20)
        & (frame["ret20"] <= g.max_return_20)
        & (frame["drawdown60"] <= g.max_drawdown_60)
        & (frame["reversal3"] >= g.min_reversal_3)
    )
    if g.require_above_ma5:
        frame["eligible"] = frame["eligible"] & frame["above_ma5"]
    frame["score"] = (
        0.45 * (-frame["flow20"]).rank(pct=True)
        + 0.35 * (-frame["ret20"]).rank(pct=True)
        + 0.20 * (-frame["drawdown60"]).rank(pct=True)
    )
    return frame


def select_assets(context, metrics):
    current_data = get_current_data()
    held = [
        code for code, pos in context.portfolio.positions.items()
        if pos.total_amount > 0 and code != g.cash_etf
    ]
    selected = []
    for code in held:
        meta = g.entry_meta.get(code)
        held_days = 0 if meta is None else (context.current_dt.date() - meta["date"]).days
        if should_force_exit(code, held_days, current_data):
            continue
        if held_days < g.min_hold_calendar_days or code not in metrics.index:
            selected.append(code)
            continue
        row = metrics.loc[code]
        normalized = (
            row["drawdown60"] > g.normalized_drawdown
            or row["ret20"] > g.normalized_return_20
            or row["flow20"] > g.normalized_flow_20
        )
        if not normalized:
            selected.append(code)

    if not metrics.empty:
        ranked = metrics[metrics["eligible"]].sort_values(["score", "flow20"], ascending=[False, True])
        for code in ranked.index:
            if code not in selected:
                selected.append(code)
            if len(selected) >= g.max_positions:
                break
    return selected[:g.max_positions]


def should_force_exit(code, held_days, current_data):
    if held_days >= g.max_hold_calendar_days:
        return True
    meta = g.entry_meta.get(code)
    if meta is None or meta.get("price", 0) <= 0:
        return False
    try:
        price = float(current_data[code].last_price)
    except Exception:
        return False
    change = price / float(meta["price"]) - 1.0
    return change >= g.take_profit or change <= g.stop_loss


def build_weights(context, selected, metrics, adv20):
    inv_vol = {}
    for code in selected:
        if code in metrics.index:
            inv_vol[code] = 1.0 / max(float(metrics.loc[code, "vol20"]), 0.08)
    total = builtins.sum(inv_vol.values())
    if total <= 0:
        return {}
    weights = {}
    for code, value in inv_vol.items():
        weights[code] = min(g.max_single_weight, g.active_budget * value / total)

    portfolio_value = float(context.portfolio.total_value)
    if portfolio_value > 0:
        for code in list(weights.keys()):
            adv = float(adv20.get(code, 0))
            if adv > 0:
                weights[code] = min(weights[code], adv * g.max_adv_participation / portfolio_value)
            elif code not in context.portfolio.positions:
                weights[code] = 0.0
    return {code: weight for code, weight in weights.items() if weight > 1e-6}


def execute_targets(context, target_weights):
    current_data = get_current_data()
    total_value = float(context.portfolio.total_value)
    target_codes = set(target_weights.keys())
    for code, pos in list(context.portfolio.positions.items()):
        if pos.total_amount > 0 and code not in target_codes and can_trade(code, current_data, False):
            order_target_value(code, 0)
    for code, weight in target_weights.items():
        try:
            current_data[code]
        except Exception:
            continue
        pos = context.portfolio.positions.get(code, None)
        current_value = 0.0 if pos is None else float(pos.value)
        current_weight = current_value / total_value if total_value > 0 else 0.0
        gap = weight - current_weight
        if pos is not None and pos.total_amount > 0 and abs(gap) < g.min_weight_change:
            continue
        target_value = weight * total_value
        if abs(target_value - current_value) < g.min_trade_value:
            continue
        if can_trade(code, current_data, gap > 0):
            order_target_value(code, target_value)


def can_trade(code, current_data, is_buy):
    try:
        snapshot = current_data[code]
        price = snapshot.last_price
        if snapshot.paused or price is None or pd.isna(price) or price <= 0:
            return False
        if is_buy and price >= snapshot.high_limit:
            return False
        if (not is_buy) and price <= snapshot.low_limit:
            return False
        return True
    except Exception:
        return False


def refresh_entry_meta(context, selected):
    current_data = get_current_data()
    held = set(
        code for code, pos in context.portfolio.positions.items()
        if pos.total_amount > 0 and code != g.cash_etf
    )
    for code in list(g.entry_meta.keys()):
        if code not in held and code not in selected:
            del g.entry_meta[code]
    for code in selected:
        if code in g.entry_meta:
            continue
        try:
            price = float(current_data[code].last_price)
        except Exception:
            continue
        if price > 0 and np.isfinite(price):
            g.entry_meta[code] = {"date": context.current_dt.date(), "price": price}
