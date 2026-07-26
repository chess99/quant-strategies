"""欧奈尔思想启发的 A 股质量成长领导者（月频研究候选，聚宽单文件）。

本变体对应本地重建研究 h18：季度利润/营收增长、12-1 价格领导力和最近完整年度
ROE 各占三分之一。突破、硬止损、趋势退出和市场覆盖层均未通过独立消融，因此不保留。
"""

from jqdata import *
import builtins
import math

import numpy as np
import pandas as pd


MODEL = "quality-growth-momentum-h18"
BOARD_LOT = 100
MAX_POSITIONS = 30
MAX_WEIGHT = 0.05
TARGET_EXPOSURE = 0.95
MIN_LISTING_DAYS = 365
MAX_QUARTER_AGE_DAYS = 220
MAX_ANNUAL_AGE_DAYS = 550
LIQUIDITY_KEEP = 0.80
BATCH_SIZE = 200


def initialize(context):
    set_benchmark("000905.XSHG")
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)
    set_order_cost(
        OrderCost(
            open_tax=0.0,
            close_tax=0.001,
            open_commission=0.0003,
            close_commission=0.0003,
            min_commission=5.0,
        ),
        type="stock",
    )
    set_slippage(PriceRelatedSlippage(0.001))
    run_monthly(rebalance, 1, time="open")


def _batch(values, size=BATCH_SIZE):
    values = list(values)
    return [values[index : index + size] for index in range(0, len(values), size)]


def safe_growth(current, base):
    try:
        current = float(current)
        base = float(base)
    except (TypeError, ValueError):
        return float("nan")
    if (
        not math.isfinite(current)
        or not math.isfinite(base)
        or current <= 0.0
        or base <= 0.0
    ):
        return float("nan")
    return current / base - 1.0


def percentile_rank(values):
    numeric = pd.to_numeric(values, errors="coerce")
    if len(numeric) == 0:
        return numeric.astype(float)
    return numeric.rank(method="average", pct=True)


def _financial_history(codes, fields, observation_date, count, interval):
    frames = []
    for group in _batch(codes):
        frame = get_history_fundamentals(
            group,
            fields=fields,
            watch_date=observation_date,
            count=count,
            interval=interval,
        )
        if frame is not None and not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _price_history(codes, observation_date):
    frames = []
    for group in _batch(codes):
        frame = get_price(
            group,
            end_date=observation_date,
            count=252,
            frequency="daily",
            fields=["close", "money"],
            skip_paused=False,
            fq="pre",
            panel=False,
        )
        if frame is not None and not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _quarter_growth(group):
    result = {
        "quarter_report_date": pd.NaT,
        "profit_growth": float("nan"),
        "revenue_growth": float("nan"),
    }
    if group is None or group.empty:
        return result
    frame = group.copy()
    frame["statDate"] = pd.to_datetime(frame["statDate"], errors="coerce")
    frame = (
        frame.dropna(subset=["statDate"])
        .sort_values("statDate")
        .drop_duplicates("statDate", keep="last")
    )
    if frame.empty:
        return result
    latest = frame.iloc[-1]
    latest_date = pd.Timestamp(latest["statDate"])
    prior = frame[frame["statDate"].eq(latest_date - pd.DateOffset(years=1))]
    result["quarter_report_date"] = latest_date
    if prior.empty:
        return result
    prior = prior.iloc[-1]
    result["profit_growth"] = safe_growth(
        latest.get("np_parent_company_owners"),
        prior.get("np_parent_company_owners"),
    )
    result["revenue_growth"] = safe_growth(
        latest.get("total_operating_revenue"),
        prior.get("total_operating_revenue"),
    )
    return result


def _annual_quality(group):
    result = {"annual_report_date": pd.NaT, "annual_roe": float("nan")}
    if group is None or group.empty:
        return result
    frame = group.copy()
    frame["statDate"] = pd.to_datetime(frame["statDate"], errors="coerce")
    frame["roe"] = pd.to_numeric(frame["roe"], errors="coerce")
    frame = (
        frame.dropna(subset=["statDate", "roe"])
        .sort_values("statDate")
        .drop_duplicates("statDate", keep="last")
    )
    if frame.empty:
        return result
    latest = frame.iloc[-1]
    result["annual_report_date"] = pd.Timestamp(latest["statDate"])
    result["annual_roe"] = float(latest["roe"])
    return result


def _price_features(group):
    result = {"momentum_12_1": float("nan"), "amount_20": float("nan")}
    if group is None or group.empty:
        return result
    frame = group.sort_values("time")
    close = pd.to_numeric(frame["close"], errors="coerce")
    money = pd.to_numeric(frame["money"], errors="coerce")
    if close.notna().sum() < 252:
        return result
    old_price = close.iloc[-252]
    recent_price = close.iloc[-21]
    result["momentum_12_1"] = safe_growth(recent_price, old_price)
    result["amount_20"] = float(money.tail(20).mean())
    return result


def select_from_features(features):
    if features is None or features.empty:
        return pd.DataFrame()
    frame = features.copy()
    frame["liquidity_rank"] = percentile_rank(frame["amount_20"])
    frame = frame[
        frame["liquidity_rank"].gt((1.0 - LIQUIDITY_KEEP) + 1.0e-12)
    ].copy()
    frame["profit_rank"] = percentile_rank(frame["profit_growth"])
    frame["revenue_rank"] = percentile_rank(frame["revenue_growth"])
    frame["growth_score"] = (frame["profit_rank"] + frame["revenue_rank"]) / 2.0
    frame["momentum_score"] = percentile_rank(frame["momentum_12_1"])
    frame["quality_score"] = percentile_rank(frame["annual_roe"])
    frame["score"] = (
        frame["growth_score"] + frame["momentum_score"] + frame["quality_score"]
    ) / 3.0
    eligible = frame.dropna(
        subset=["growth_score", "momentum_score", "quality_score"]
    )
    return eligible.sort_values(
        ["score", "code"], ascending=[False, True]
    ).head(MAX_POSITIONS)


def build_candidates(codes, observation_date):
    if not codes:
        return pd.DataFrame()
    quarterly = _financial_history(
        codes,
        [income.np_parent_company_owners, income.total_operating_revenue],
        observation_date,
        8,
        "1q",
    )
    annual = _financial_history(
        codes,
        [indicator.roe],
        observation_date,
        2,
        "1y",
    )
    prices = _price_history(codes, observation_date)
    quarterly_groups = (
        dict(tuple(quarterly.groupby("code")))
        if not quarterly.empty and "code" in quarterly
        else {}
    )
    annual_groups = (
        dict(tuple(annual.groupby("code")))
        if not annual.empty and "code" in annual
        else {}
    )
    price_groups = (
        dict(tuple(prices.groupby("code")))
        if not prices.empty and "code" in prices
        else {}
    )
    rows = []
    observation = pd.Timestamp(observation_date)
    for code in codes:
        quarter = _quarter_growth(quarterly_groups.get(code))
        quality = _annual_quality(annual_groups.get(code))
        price = _price_features(price_groups.get(code))
        quarter_age = (
            (observation - quarter["quarter_report_date"]).days
            if pd.notna(quarter["quarter_report_date"])
            else float("nan")
        )
        annual_age = (
            (observation - quality["annual_report_date"]).days
            if pd.notna(quality["annual_report_date"])
            else float("nan")
        )
        rows.append(
            {
                "code": code,
                "quarter_age_days": quarter_age,
                "annual_age_days": annual_age,
                **quarter,
                **quality,
                **price,
            }
        )
    features = pd.DataFrame(rows)
    features = features[
        pd.to_numeric(features["quarter_age_days"], errors="coerce").le(
            MAX_QUARTER_AGE_DAYS
        )
        & pd.to_numeric(features["annual_age_days"], errors="coerce").le(
            MAX_ANNUAL_AGE_DAYS
        )
    ]
    return select_from_features(features)


def _is_st(snapshot):
    name = str(getattr(snapshot, "name", ""))
    return bool(
        getattr(snapshot, "is_st", False)
        or "ST" in name.upper()
        or "退" in name
    )


def rebalance(context):
    observation_date = context.previous_date
    securities = get_all_securities(types=["stock"], date=observation_date)
    listing_cutoff = pd.Timestamp(observation_date) - pd.Timedelta(days=MIN_LISTING_DAYS)
    current_data = get_current_data()
    tradable = []
    for code, row in securities.iterrows():
        if pd.Timestamp(row["start_date"]) > listing_cutoff:
            continue
        snapshot = current_data[code]
        if getattr(snapshot, "paused", False) or _is_st(snapshot):
            continue
        tradable.append(code)
    candidates = build_candidates(sorted(tradable), observation_date)
    targets = candidates["code"].tolist() if not candidates.empty else []
    target_set = set(targets)

    for code in list(context.portfolio.positions.keys()):
        if code in target_set:
            continue
        snapshot = current_data[code]
        last_price = float(getattr(snapshot, "last_price", float("nan")))
        low_limit = float(getattr(snapshot, "low_limit", float("nan")))
        if getattr(snapshot, "paused", False):
            continue
        if math.isfinite(last_price) and math.isfinite(low_limit):
            if last_price <= low_limit + 1.0e-8:
                continue
        order_target(code, 0)

    if not targets:
        log.info("%s observation=%s candidates=0", MODEL, observation_date)
        return
    total_value = float(context.portfolio.total_value)
    target_weight = min(MAX_WEIGHT, TARGET_EXPOSURE / float(len(targets)))
    target_value = total_value * target_weight
    for code in targets:
        snapshot = current_data[code]
        if getattr(snapshot, "paused", False) or _is_st(snapshot):
            continue
        last_price = float(getattr(snapshot, "last_price", float("nan")))
        high_limit = float(getattr(snapshot, "high_limit", float("nan")))
        if not math.isfinite(last_price) or last_price <= 0.0:
            continue
        if math.isfinite(high_limit) and last_price >= high_limit - 1.0e-8:
            continue
        target_shares = int(target_value // (last_price * BOARD_LOT)) * BOARD_LOT
        if target_shares >= BOARD_LOT:
            order_target(code, target_shares)
    log.info(
        "%s observation=%s universe=%d selected=%d top=%s",
        MODEL,
        observation_date,
        len(tradable),
        len(targets),
        ",".join(targets[:5]),
    )
