"""华创2019 CANSLIM 可得数据版（月频，聚宽单文件）。

缺失的机构持有数和北向持股不使用价量代理替代，因此本文件不是研报精确复刻。
"""

from jqdata import *
import builtins
import math

import numpy as np
import pandas as pd


MODEL = "huachuang-2019-available"
INSTITUTIONAL_FILTER = "unavailable-not-proxied"
BOARD_LOT = 100
MAX_POSITIONS = 20
MIN_AVERAGE_MONEY = 50_000_000.0
MIN_EPS_GROWTH = 0.18
MIN_REVENUE_GROWTH = 0.25
MIN_ANNUAL_CAGR = 0.15
MIN_RPS = 80.0
MIN_HIGH_PROXIMITY = 0.95
MAX_REPORT_AGE_DAYS = 240


def initialize(context):
    set_benchmark("000300.XSHG")
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)
    set_order_cost(
        OrderCost(
            open_tax=0.0,
            close_tax=0.0,
            open_commission=0.0013,
            close_commission=0.0013,
            min_commission=0.0,
        ),
        type="stock",
    )
    set_slippage(FixedSlippage(0.002))
    run_monthly(rebalance, 1, time="open")


def safe_growth(current, base):
    try:
        current = float(current)
        base = float(base)
    except (TypeError, ValueError):
        return float("nan")
    if (
        not math.isfinite(current)
        or not math.isfinite(base)
        or base <= 0.0
    ):
        return float("nan")
    return current / base - 1.0


def percentile_rank(values):
    numeric = pd.to_numeric(values, errors="coerce")
    if len(numeric) == 0:
        return numeric.astype(float)
    return numeric.rank(method="max") / float(len(numeric)) * 100.0


def _batch(values, size):
    values = list(values)
    return [values[index : index + size] for index in range(0, len(values), size)]


def _financial_history(codes, fields, observation_date, count, interval):
    frames = []
    for group in _batch(codes, 200):
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
    for group in _batch(codes, 200):
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
        "report_date": pd.NaT,
        "eps_growth": float("nan"),
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
    prior_date = latest_date - pd.DateOffset(years=1)
    prior = frame.loc[frame["statDate"].eq(prior_date)]
    result["report_date"] = latest_date
    if prior.empty:
        return result
    prior = prior.iloc[-1]
    result["eps_growth"] = safe_growth(
        latest.get("basic_eps"), prior.get("basic_eps")
    )
    result["revenue_growth"] = safe_growth(
        latest.get("total_operating_revenue"),
        prior.get("total_operating_revenue"),
    )
    return result


def _annual_path(group):
    result = {"annual_cagr": float("nan"), "annual_positive_path": False}
    if group is None or group.empty:
        return result
    frame = group.copy()
    frame["statDate"] = pd.to_datetime(frame["statDate"], errors="coerce")
    frame["profit"] = pd.to_numeric(
        frame["np_parent_company_owners"], errors="coerce"
    )
    frame = (
        frame.dropna(subset=["statDate", "profit"])
        .sort_values("statDate")
        .drop_duplicates("statDate", keep="last")
        .tail(5)
    )
    if len(frame) < 5:
        return result
    values = frame["profit"].to_numpy(dtype=float)
    if (
        not np.isfinite(values).all()
        or (values <= 0.0).any()
        or not (np.diff(values) > 0.0).all()
    ):
        return result
    result["annual_cagr"] = float(
        (values[-1] / values[0]) ** (1.0 / 4.0) - 1.0
    )
    result["annual_positive_path"] = True
    return result


def _price_features(group):
    result = {
        "return_12m": float("nan"),
        "high_proximity": float("nan"),
        "liquid": False,
    }
    if group is None or group.empty:
        return result
    frame = group.sort_values("time")
    close = pd.to_numeric(frame["close"], errors="coerce").dropna()
    money = pd.to_numeric(frame["money"], errors="coerce")
    if len(close) < 211:
        return result
    high = float(close.tail(252).max())
    result["return_12m"] = (
        safe_growth(close.iloc[-1], close.iloc[-252])
        if len(close) >= 252
        else float("nan")
    )
    result["high_proximity"] = (
        float(close.iloc[-1]) / high
        if math.isfinite(high) and high > 0.0
        else float("nan")
    )
    average_money = float(money.tail(20).mean())
    result["liquid"] = bool(
        math.isfinite(average_money) and average_money >= MIN_AVERAGE_MONEY
    )
    return result


def build_candidates(codes, observation_date):
    if not codes:
        return pd.DataFrame()
    quarterly = _financial_history(
        codes,
        [
            income.basic_eps,
            income.np_parent_company_owners,
            income.total_operating_revenue,
        ],
        observation_date,
        8,
        "1q",
    )
    annual = _financial_history(
        codes,
        [income.np_parent_company_owners],
        observation_date,
        5,
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
    for code in codes:
        quarter = _quarter_growth(quarterly_groups.get(code))
        annual_path = _annual_path(annual_groups.get(code))
        price = _price_features(price_groups.get(code))
        report_age = (
            (pd.Timestamp(observation_date) - quarter["report_date"]).days
            if pd.notna(quarter["report_date"])
            else float("nan")
        )
        rows.append(
            {
                "code": code,
                "report_age_days": report_age,
                **quarter,
                **annual_path,
                **price,
            }
        )
    frame = pd.DataFrame(rows).set_index("code", drop=False)
    frame["rps"] = percentile_rank(frame["return_12m"])
    mask = (
        frame["liquid"].fillna(False).astype(bool)
        & pd.to_numeric(frame["report_age_days"], errors="coerce").le(
            MAX_REPORT_AGE_DAYS
        )
        & pd.to_numeric(frame["eps_growth"], errors="coerce").ge(
            MIN_EPS_GROWTH
        )
        & pd.to_numeric(frame["revenue_growth"], errors="coerce").ge(
            MIN_REVENUE_GROWTH
        )
        & pd.to_numeric(frame["annual_cagr"], errors="coerce").ge(
            MIN_ANNUAL_CAGR
        )
        & frame["annual_positive_path"].fillna(False).astype(bool)
        & pd.to_numeric(frame["rps"], errors="coerce").ge(MIN_RPS)
        & pd.to_numeric(frame["high_proximity"], errors="coerce").ge(
            MIN_HIGH_PROXIMITY
        )
    )
    frame["score"] = (
        frame["rps"].fillna(0.0) * 0.50
        + percentile_rank(frame["eps_growth"]).fillna(0.0) * 0.25
        + percentile_rank(frame["revenue_growth"]).fillna(0.0) * 0.25
    )
    selected = frame.loc[mask].copy()
    selected.index.name = None
    return selected.sort_values(
        ["score", "code"], ascending=[False, True]
    ).head(MAX_POSITIONS)


def _is_st(snapshot):
    name = str(getattr(snapshot, "name", ""))
    return bool(
        getattr(snapshot, "is_st", False)
        or "ST" in name.upper()
        or "退" in name
    )


def rebalance(context):
    observation_date = context.previous_date
    universe = sorted(
        set(
            get_index_stocks("000300.XSHG", date=observation_date)
            + get_index_stocks("000905.XSHG", date=observation_date)
        )
    )
    current_data = get_current_data()
    tradable = []
    for code in universe:
        snapshot = current_data[code]
        if getattr(snapshot, "paused", False) or _is_st(snapshot):
            continue
        tradable.append(code)
    candidates = build_candidates(tradable, observation_date)
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
        return
    total_value = float(context.portfolio.total_value)
    target_weight = min(0.05, 1.0 / float(len(targets)))
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
        if target_shares < BOARD_LOT:
            continue
        order_target(code, target_shares)
