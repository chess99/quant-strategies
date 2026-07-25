# ruff: noqa: F403, F405
"""欧奈尔 CAN SLIM 风格的 A 股聚宽研究基线。

本策略把可观察的 CAN SLIM 规则拆成点时基本面、相对强度、整理突破、市场状态和
交易纪律。N 的公司叙事与 I 的优质机构持仓没有被伪装成精确数据；当前仅使用
价格新高/整理和 13 周价量吸筹作为明确标注的代理。

文件自包含，可直接复制到聚宽。所有选股信号默认只使用前一交易日及当时已披露数据。
"""

import builtins
import datetime as dt
import math

import numpy as np
import pandas as pd

try:
    from jqdata import *  # noqa: F403
except ImportError:
    pass


BENCHMARK = "000300.XSHG"
MARKET_INDEX = "000001.XSHG"

MARKET_UNKNOWN = "unknown"
MARKET_CORRECTION = "correction"
MARKET_RALLY_ATTEMPT = "rally_attempt"
MARKET_CONFIRMED = "confirmed_uptrend"
MARKET_UNDER_PRESSURE = "uptrend_under_pressure"

MAX_POSITIONS = 6
WATCHLIST_SIZE = 80
MIN_LISTING_DAYS = 365
MIN_AVERAGE_MONEY = 5e7
PRICE_LOOKBACK = 260
MARKET_LOOKBACK = 750
MIN_RS_HISTORY = 253
PRICE_BATCH_SIZE = 300
FUNDAMENTAL_BATCH_SIZE = 300
MAX_REPORT_AGE_DAYS = 240

MIN_CURRENT_EPS_GROWTH = 0.25
MIN_CORE_PROFIT_GROWTH = 0.20
MIN_CURRENT_SALES_GROWTH = 0.20
MIN_ANNUAL_EPS_CAGR = 0.25
MIN_ROE = 0.17
MIN_RS_RATING = 80.0
MIN_INDUSTRY_RS_RATING = 75.0

MIN_BASE_DEPTH = 0.05
MAX_BASE_DEPTH = 0.35
MIN_BREAKOUT_VOLUME_RATIO = 1.40
MAX_BUY_ZONE_EXTENSION = 0.05

FOLLOW_THROUGH_MIN_GAIN = 0.017
FOLLOW_THROUGH_MIN_DAY = 4
DISTRIBUTION_MIN_DROP = 0.002
DISTRIBUTION_WINDOW = 25
MAX_DISTRIBUTION_DAYS = 5

FINAL_POSITION_WEIGHT = 0.15
INITIAL_POSITION_WEIGHT = FINAL_POSITION_WEIGHT * 0.55
SECOND_POSITION_WEIGHT = FINAL_POSITION_WEIGHT * 0.80
HARD_STOP_LOSS = 0.075
FAILED_BREAKOUT_BUFFER = 0.03
PROFIT_TARGET = 0.25
FAST_GAIN = 0.20
FAST_GAIN_DAYS = 21
POWER_HOLD_DAYS = 56
FIRST_ADD_GAIN = 0.025
SECOND_ADD_GAIN = 0.05


def initialize(context):
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
    _ensure_state()
    run_weekly(refresh_watchlist, 1, time="before_open")
    run_daily(daily_trade, time="10:00")


def _ensure_state():
    defaults = {
        "watchlist": [],
        "candidate_meta": {},
        "entry_dates": {},
        "entry_prices": {},
        "entry_pivots": {},
        "pyramid_stages": {},
        "power_hold_until": {},
        "pending_entries": {},
        "pending_pyramids": {},
        "pending_exits": {},
        "market_state": MARKET_UNKNOWN,
        "watchlist_date": None,
    }
    for name, value in defaults.items():
        if not hasattr(g, name):
            setattr(g, name, value.copy() if isinstance(value, (dict, list)) else value)


def _log(level, message, *args):
    logger = globals().get("log")
    method = getattr(logger, level, None) if logger is not None else None
    if method is not None:
        method(message, *args)


def _finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return np.nan
    return number if np.isfinite(number) else np.nan


def _usable_cash(value):
    value = _finite_number(value)
    if not np.isfinite(value) or value <= 0:
        return 0.0
    return value


def _round_buy_target_value(current_value, desired_target_value, current_price):
    """Round only the buy increment down to an A-share 100-share board lot."""
    current_value = _finite_number(current_value)
    desired_target_value = _finite_number(desired_target_value)
    current_price = _finite_number(current_price)
    if (
        not np.isfinite(current_value)
        or current_value < 0
        or not np.isfinite(desired_target_value)
        or not np.isfinite(current_price)
        or current_price <= 0
    ):
        return np.nan
    additional = desired_target_value - current_value
    lot_value = current_price * 100.0
    lots = int(math.floor((additional + 1e-8) / lot_value))
    if lots <= 0:
        return current_value
    return current_value + lots * lot_value


def safe_divide(numerator, denominator):
    numerator = _finite_number(numerator)
    denominator = _finite_number(denominator)
    if (
        not np.isfinite(numerator)
        or not np.isfinite(denominator)
        or abs(denominator) < 1e-12
    ):
        return np.nan
    return numerator / denominator


def safe_growth(latest, previous):
    latest = _finite_number(latest)
    previous = _finite_number(previous)
    if not np.isfinite(latest) or not np.isfinite(previous) or previous <= 0:
        return np.nan
    return latest / previous - 1.0


def compound_growth(latest, oldest, periods):
    latest = _finite_number(latest)
    oldest = _finite_number(oldest)
    periods = _finite_number(periods)
    if (
        not np.isfinite(latest)
        or not np.isfinite(oldest)
        or not np.isfinite(periods)
        or latest <= 0
        or oldest <= 0
        or periods <= 0
    ):
        return np.nan
    return (latest / oldest) ** (1.0 / periods) - 1.0


def _as_ratio(value):
    """Convert JoinQuant percentage-valued fields (for example ROE) to ratios."""
    value = _finite_number(value)
    if not np.isfinite(value):
        return np.nan
    return value / 100.0


def _clip_score(value, lower, upper):
    value = _finite_number(value)
    if not np.isfinite(value) or upper <= lower:
        return 0.0
    return float(np.clip((value - lower) / (upper - lower) * 100.0, 0.0, 100.0))


def _chunked(items, size):
    if size <= 0:
        raise ValueError("size must be positive")
    items = list(items)
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _previous_trade_day(current_date):
    days = get_trade_days(end_date=current_date, count=2)
    if len(days) < 2:
        raise ValueError("at least two trade days are required")
    value = days[-2]
    return value.date() if hasattr(value, "date") else value


def _normalize_price_frame(raw, default_code=None):
    expected = ["time", "code", "open", "close", "high", "low", "volume", "money"]
    if raw is None:
        return pd.DataFrame(columns=expected)
    frame = raw.copy()
    if not isinstance(frame, pd.DataFrame):
        try:
            frame = pd.DataFrame(frame)
        except Exception:
            return pd.DataFrame(columns=expected)
    if not isinstance(frame.index, pd.RangeIndex):
        frame = frame.reset_index()
    if "time" not in frame.columns:
        for candidate in ("index", "level_0", "date", "datetime"):
            if candidate in frame.columns:
                frame = frame.rename(columns={candidate: "time"})
                break
    if "code" not in frame.columns and default_code is not None:
        frame["code"] = default_code
    for column in expected:
        if column not in frame.columns:
            frame[column] = np.nan
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce")
    for column in ("open", "close", "high", "low", "volume", "money"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return (
        frame[expected]
        .dropna(subset=["time", "code"])
        .sort_values(["code", "time"])
        .reset_index(drop=True)
    )


def weighted_relative_strength(close):
    """公开可复现的 IBD RS 代理：最近一季 40%，此前三季各 20%。"""
    clean = pd.to_numeric(pd.Series(close), errors="coerce").dropna()
    if len(clean) < MIN_RS_HISTORY:
        return np.nan
    clean = clean.tail(MIN_RS_HISTORY)
    points = [
        clean.iloc[-1],
        clean.iloc[-64],
        clean.iloc[-127],
        clean.iloc[-190],
        clean.iloc[-253],
    ]
    if not builtins.all(np.isfinite(value) and value > 0 for value in points):
        return np.nan
    quarterly_returns = [
        points[0] / points[1] - 1.0,
        points[1] / points[2] - 1.0,
        points[2] / points[3] - 1.0,
        points[3] / points[4] - 1.0,
    ]
    weights = (0.40, 0.20, 0.20, 0.20)
    return builtins.sum(
        weight * quarterly_return
        for weight, quarterly_return in zip(weights, quarterly_returns)
    )


def _base_inputs(prices):
    frame = _normalize_price_frame(prices)
    if frame.empty:
        return frame
    if frame["code"].nunique() > 1:
        raise ValueError("base analysis requires one security")
    return frame.sort_values("time").reset_index(drop=True)


def analyze_base_setup(prices):
    """识别通用整理枢轴；不声称区分杯柄、双底或平底。"""
    frame = _base_inputs(prices)
    result = {
        "setup_ready": False,
        "pivot": np.nan,
        "base_depth": np.nan,
        "handle_volume_ratio": np.nan,
        "base_quality": 0.0,
        "reasons": [],
    }
    if len(frame) < 67:
        result["reasons"].append("history")
        return result

    prior = frame.iloc[-66:-1].copy()
    pivot_window = prior.tail(55)
    pivot = pd.to_numeric(pivot_window["high"], errors="coerce").max()
    base_high = pd.to_numeric(prior["high"], errors="coerce").max()
    base_low = pd.to_numeric(prior["low"], errors="coerce").min()
    current_close = _finite_number(frame["close"].iloc[-1])
    base_depth = 1.0 - safe_divide(base_low, base_high)

    prior_volume = pd.to_numeric(prior["volume"], errors="coerce")
    handle_volume = prior_volume.tail(10).mean()
    comparison_volume = prior_volume.iloc[-50:-10].mean()
    handle_volume_ratio = safe_divide(handle_volume, comparison_volume)

    reasons = []
    if not np.isfinite(pivot) or pivot <= 0:
        reasons.append("pivot")
    if (
        not np.isfinite(base_depth)
        or base_depth < MIN_BASE_DEPTH
        or base_depth > MAX_BASE_DEPTH
    ):
        reasons.append("base_depth")
    if not np.isfinite(current_close) or current_close < pivot * 0.90:
        reasons.append("too_far_below_pivot")
    if np.isfinite(current_close) and np.isfinite(pivot):
        if current_close > pivot * (1.0 + MAX_BUY_ZONE_EXTENSION):
            reasons.append("extended")

    full_high = pd.to_numeric(frame["high"], errors="coerce").tail(253).max()
    if (
        not np.isfinite(current_close)
        or not np.isfinite(full_high)
        or current_close < full_high * 0.85
    ):
        reasons.append("far_from_high")

    ideal_depth_score = 100.0 - min(abs(base_depth - 0.20) / 0.20 * 100.0, 100.0)
    dry_up_score = (
        _clip_score(1.20 - handle_volume_ratio, 0.0, 0.50)
        if np.isfinite(handle_volume_ratio)
        else 0.0
    )
    base_quality = 0.70 * ideal_depth_score + 0.30 * dry_up_score

    result.update(
        {
            "setup_ready": len(reasons) == 0,
            "pivot": float(pivot) if np.isfinite(pivot) else np.nan,
            "base_depth": float(base_depth) if np.isfinite(base_depth) else np.nan,
            "handle_volume_ratio": (
                float(handle_volume_ratio)
                if np.isfinite(handle_volume_ratio)
                else np.nan
            ),
            "base_quality": float(np.clip(base_quality, 0.0, 100.0)),
            "reasons": reasons,
        }
    )
    return result


def detect_breakout(prices):
    """用最后一个完整交易日判断枢轴突破和 50 日放量。"""
    frame = _base_inputs(prices)
    setup = analyze_base_setup(frame)
    result = dict(setup)
    result["is_breakout"] = False
    result["volume_ratio"] = np.nan
    if len(frame) < 67:
        return result

    prior = frame.iloc[-66:-1]
    pivot = pd.to_numeric(prior.tail(55)["high"], errors="coerce").max()
    close = _finite_number(frame["close"].iloc[-1])
    volume = _finite_number(frame["volume"].iloc[-1])
    average_volume = pd.to_numeric(
        prior.tail(50)["volume"], errors="coerce"
    ).mean()
    volume_ratio = safe_divide(volume, average_volume)

    reasons = [
        reason
        for reason in setup["reasons"]
        if reason not in ("extended", "too_far_below_pivot")
    ]
    if not np.isfinite(close) or not np.isfinite(pivot) or close < pivot:
        reasons.append("below_pivot")
    if np.isfinite(close) and np.isfinite(pivot):
        if close > pivot * (1.0 + MAX_BUY_ZONE_EXTENSION):
            reasons.append("extended")
    if (
        not np.isfinite(volume_ratio)
        or volume_ratio < MIN_BREAKOUT_VOLUME_RATIO
    ):
        reasons.append("volume")

    result.update(
        {
            "is_breakout": len(reasons) == 0,
            "pivot": float(pivot) if np.isfinite(pivot) else np.nan,
            "volume_ratio": (
                float(volume_ratio) if np.isfinite(volume_ratio) else np.nan
            ),
            "reasons": list(dict.fromkeys(reasons)),
        }
    )
    return result


def _accumulation_ratio(frame):
    close = pd.to_numeric(frame["close"], errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    returns = close.pct_change()
    recent_returns = returns.tail(65)
    recent_volume = volume.tail(65)
    up_volume = recent_volume.loc[recent_returns > 0].sum()
    down_volume = recent_volume.loc[recent_returns < 0].sum()
    return safe_divide(up_volume, down_volume)


def _trend_template(frame):
    close = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if len(close) < 220:
        return False
    latest = close.iloc[-1]
    ma50 = close.tail(50).mean()
    ma200 = close.tail(200).mean()
    prior_ma200 = close.iloc[-220:-20].mean()
    high_52w = close.tail(253).max()
    low_52w = close.tail(253).min()
    return bool(
        np.isfinite(latest)
        and latest > ma50
        and ma50 > ma200
        and ma200 >= prior_ma200
        and latest >= high_52w * 0.85
        and latest >= low_52w * 1.30
    )


def build_relative_strength_features(prices, industries=None):
    """在完整流动性股票池中计算可复现的个股与行业 RS 百分位。"""
    prices = _normalize_price_frame(prices)
    if prices.empty:
        return pd.DataFrame()
    industries = industries or {}
    rows = []
    for code, group in prices.groupby("code", sort=False):
        group = group.sort_values("time")
        close = pd.to_numeric(group["close"], errors="coerce").dropna()
        if len(close) < MIN_RS_HISTORY:
            continue
        latest = close.iloc[-1]
        high_52w = close.tail(MIN_RS_HISTORY).max()
        low_52w = close.tail(MIN_RS_HISTORY).min()
        rows.append(
            {
                "code": code,
                "relative_strength_raw": weighted_relative_strength(close),
                "trend_ok": _trend_template(group),
                "near_high": bool(
                    np.isfinite(high_52w)
                    and np.isfinite(low_52w)
                    and latest >= high_52w * 0.85
                    and latest >= low_52w * 1.30
                ),
                "industry": industries.get(code, "未知行业"),
            }
        )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["rs_rating"] = (
        result["relative_strength_raw"].rank(method="average", pct=True) * 100.0
    )
    industry_strength = (
        result.loc[result["industry"] != "未知行业"]
        .groupby("industry")["relative_strength_raw"]
        .median()
    )
    industry_ratings = industry_strength.rank(method="average", pct=True) * 100.0
    result["industry_rs_rating"] = result["industry"].map(industry_ratings).fillna(0.0)
    return result


def build_price_features(prices, industries=None, circulating_caps=None):
    prices = _normalize_price_frame(prices)
    if prices.empty:
        return pd.DataFrame()
    industries = industries or {}
    circulating_caps = circulating_caps or {}
    rows = []
    for code, group in prices.groupby("code", sort=False):
        group = group.sort_values("time")
        close = pd.to_numeric(group["close"], errors="coerce").dropna()
        if len(close) < MIN_RS_HISTORY:
            continue
        setup = analyze_base_setup(group)
        high_52w = pd.to_numeric(group["high"], errors="coerce").tail(253).max()
        low_52w = pd.to_numeric(group["low"], errors="coerce").tail(253).min()
        latest_close = close.iloc[-1]
        rows.append(
            {
                "code": code,
                "relative_strength_raw": weighted_relative_strength(close),
                "average_money_20d": pd.to_numeric(
                    group["money"], errors="coerce"
                ).tail(20).mean(),
                "accumulation_ratio": _accumulation_ratio(group),
                "trend_ok": _trend_template(group),
                "near_high": bool(
                    np.isfinite(high_52w)
                    and np.isfinite(low_52w)
                    and latest_close >= high_52w * 0.85
                    and latest_close >= low_52w * 1.30
                ),
                "latest_close": latest_close,
                "high_52w": high_52w,
                "low_52w": low_52w,
                "setup_ready": setup["setup_ready"],
                "pivot": setup["pivot"],
                "base_depth": setup["base_depth"],
                "base_quality": setup["base_quality"],
                "industry": industries.get(code, "未知行业"),
                "circulating_market_cap": _finite_number(
                    circulating_caps.get(code, np.nan)
                ),
            }
        )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["rs_rating"] = (
        result["relative_strength_raw"].rank(method="average", pct=True) * 100.0
    )
    industry_strength = (
        result.loc[result["industry"] != "未知行业"]
        .groupby("industry")["relative_strength_raw"]
        .median()
    )
    industry_rating = industry_strength.rank(method="average", pct=True) * 100.0
    result["industry_rs_rating"] = result["industry"].map(industry_rating).fillna(0.0)
    result["setup_ready"] = (
        result["setup_ready"]
        & result["trend_ok"]
        & result["near_high"]
        & result["average_money_20d"].ge(MIN_AVERAGE_MONEY)
    )
    return result


def _quarter_number(value):
    value = pd.Timestamp(value)
    return int((value.month - 1) // 3 + 1)


def prepare_quarterly_frame(history):
    """规范聚宽历史财务接口已经拆分好的单季度数据。

    ``get_history_fundamentals(..., interval="1q")`` 返回的利润表流量字段已经是
    单季度值，不能再对半年报、三季报做差，否则会二次拆分。
    """
    if history is None or history.empty:
        return pd.DataFrame()
    frame = history.copy()
    if "code" not in frame.columns or "statDate" not in frame.columns:
        return pd.DataFrame()
    frame["statDate"] = pd.to_datetime(frame["statDate"], errors="coerce")
    frame = (
        frame.dropna(subset=["code", "statDate"])
        .sort_values(["code", "statDate"])
        .drop_duplicates(["code", "statDate"], keep="last")
    )
    for column in (
        "basic_eps",
        "adjusted_profit",
        "np_parent_company_owners",
        "total_operating_revenue",
    ):
        if column not in frame.columns:
            frame[column] = np.nan
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.sort_values(["code", "statDate"]).reset_index(drop=True)


def _core_profit(row):
    return _finite_number(row.get("adjusted_profit", np.nan))


def _quarter_key(value):
    value = pd.Timestamp(value)
    return value.year, _quarter_number(value)


def _previous_quarter_key(key):
    year, quarter = key
    return (year - 1, 4) if quarter == 1 else (year, quarter - 1)


def _year_ago_key(key):
    return key[0] - 1, key[1]


def build_fundamental_features(
    code,
    quarterly_history,
    annual_history,
    observation_date=None,
):
    quarterly = prepare_quarterly_frame(quarterly_history)
    if quarterly.empty:
        return None
    quarterly = quarterly.loc[quarterly["code"] == code].sort_values("statDate")
    if quarterly.empty:
        return None
    quarter_lookup = {
        _quarter_key(row["statDate"]): row
        for _, row in quarterly.iterrows()
    }
    current_key = max(quarter_lookup)
    current = quarter_lookup[current_key]
    current_report_age_days = np.nan
    if observation_date is not None:
        try:
            observation_timestamp = pd.Timestamp(observation_date).normalize()
            current_timestamp = pd.Timestamp(current["statDate"]).normalize()
            current_report_age_days = (
                observation_timestamp - current_timestamp
            ).days
        except Exception:
            current_report_age_days = np.nan
    year_ago = quarter_lookup.get(_year_ago_key(current_key))
    previous_key = _previous_quarter_key(current_key)
    previous = quarter_lookup.get(previous_key)
    previous_year_ago = quarter_lookup.get(_year_ago_key(previous_key))
    if year_ago is None:
        return None

    current_profit = _core_profit(current)
    year_ago_profit = _core_profit(year_ago)
    current_eps = _finite_number(current.get("basic_eps", np.nan))
    year_ago_eps = _finite_number(year_ago.get("basic_eps", np.nan))
    current_eps_growth = safe_growth(current_eps, year_ago_eps)
    core_profit_growth = safe_growth(current_profit, year_ago_profit)
    current_sales_growth = safe_growth(
        current.get("total_operating_revenue", np.nan),
        year_ago.get("total_operating_revenue", np.nan),
    )

    previous_eps_growth = np.nan
    if previous is not None and previous_year_ago is not None:
        previous_eps = _finite_number(previous.get("basic_eps", np.nan))
        previous_year_ago_eps = _finite_number(
            previous_year_ago.get("basic_eps", np.nan)
        )
        previous_eps_growth = safe_growth(previous_eps, previous_year_ago_eps)
    acceleration = (
        current_eps_growth - previous_eps_growth
        if np.isfinite(current_eps_growth)
        and np.isfinite(previous_eps_growth)
        else np.nan
    )

    current_margin = safe_divide(
        current_profit,
        current.get("total_operating_revenue", np.nan),
    )
    year_ago_margin = safe_divide(
        year_ago_profit,
        year_ago.get("total_operating_revenue", np.nan),
    )
    margin_change = (
        current_margin - year_ago_margin
        if np.isfinite(current_margin) and np.isfinite(year_ago_margin)
        else np.nan
    )

    if annual_history is None or annual_history.empty:
        return None
    annual = annual_history.copy()
    annual["statDate"] = pd.to_datetime(annual["statDate"], errors="coerce")
    annual = (
        annual.loc[annual["code"] == code]
        .dropna(subset=["statDate"])
        .sort_values("statDate")
        .drop_duplicates("statDate", keep="last")
        .tail(4)
    )
    if len(annual) < 4:
        return None

    annual_eps = []
    annual_years = []
    for _, row in annual.iterrows():
        eps = _finite_number(row.get("basic_eps", np.nan))
        annual_eps.append(eps)
        annual_years.append(pd.Timestamp(row["statDate"]).year)
    consecutive_years = builtins.all(
        annual_years[index + 1] - annual_years[index] == 1
        for index in range(len(annual_years) - 1)
    )
    positive_annual = builtins.all(
        np.isfinite(value) and value > 0 for value in annual_eps
    )
    annual_increasing = (
        consecutive_years
        and positive_annual
        and builtins.all(
            annual_eps[index + 1] > annual_eps[index]
            for index in range(len(annual_eps) - 1)
        )
    )
    year_span = annual_years[-1] - annual_years[0]
    annual_cagr = compound_growth(annual_eps[-1], annual_eps[0], year_span)
    latest_annual = annual.iloc[-1]
    roe = _as_ratio(latest_annual.get("roe", np.nan))

    return {
        "code": code,
        "current_report_date": current["statDate"],
        "current_report_age_days": current_report_age_days,
        "current_eps_growth": current_eps_growth,
        "core_profit_growth": core_profit_growth,
        "current_sales_growth": current_sales_growth,
        "previous_eps_growth": previous_eps_growth,
        "eps_growth_acceleration": acceleration,
        "current_margin": current_margin,
        "margin_change": margin_change,
        "annual_eps_cagr": annual_cagr,
        "annual_eps_increasing": bool(annual_increasing),
        "roe": roe,
    }


def _candidate_vetoes(row):
    reasons = []
    report_age = _finite_number(row.get("current_report_age_days", np.nan))
    if (
        not np.isfinite(report_age)
        or report_age < 0
        or report_age > MAX_REPORT_AGE_DAYS
    ):
        reasons.append("stale_financials")
    if (
        not np.isfinite(_finite_number(row.get("current_eps_growth")))
        or row.get("current_eps_growth") < MIN_CURRENT_EPS_GROWTH
    ):
        reasons.append("current_eps_growth")
    if (
        not np.isfinite(_finite_number(row.get("core_profit_growth")))
        or row.get("core_profit_growth") < MIN_CORE_PROFIT_GROWTH
    ):
        reasons.append("core_profit_growth")
    if (
        not np.isfinite(_finite_number(row.get("current_sales_growth")))
        or row.get("current_sales_growth") < MIN_CURRENT_SALES_GROWTH
    ):
        reasons.append("current_sales_growth")
    if (
        not np.isfinite(_finite_number(row.get("annual_eps_cagr")))
        or row.get("annual_eps_cagr") < MIN_ANNUAL_EPS_CAGR
    ):
        reasons.append("annual_eps_cagr")
    if not bool(row.get("annual_eps_increasing", False)):
        reasons.append("annual_eps_increasing")
    if (
        not np.isfinite(_finite_number(row.get("roe")))
        or row.get("roe") < MIN_ROE
    ):
        reasons.append("roe")
    if (
        not np.isfinite(_finite_number(row.get("rs_rating")))
        or row.get("rs_rating") < MIN_RS_RATING
    ):
        reasons.append("rs_rating")
    if (
        not np.isfinite(_finite_number(row.get("industry_rs_rating")))
        or row.get("industry_rs_rating") < MIN_INDUSTRY_RS_RATING
    ):
        reasons.append("industry_rs_rating")
    if not bool(row.get("setup_ready", False)):
        reasons.append("base_setup")
    if (
        not np.isfinite(_finite_number(row.get("average_money_20d")))
        or row.get("average_money_20d") < MIN_AVERAGE_MONEY
    ):
        reasons.append("liquidity")
    return reasons


def score_candidates(fundamentals, prices):
    if fundamentals is None or prices is None:
        return pd.DataFrame()
    if fundamentals.empty or prices.empty:
        return pd.DataFrame()
    frame = fundamentals.merge(prices, on="code", how="inner")
    if frame.empty:
        return frame

    market_cap = pd.to_numeric(
        frame.get("circulating_market_cap", pd.Series(np.nan, index=frame.index)),
        errors="coerce",
    )
    frame["supply_percentile"] = (
        market_cap.rank(method="average", ascending=False, pct=True) * 100.0
    ).fillna(50.0)

    rows = []
    for _, row in frame.iterrows():
        reasons = _candidate_vetoes(row)
        current_score = (
            0.50
            * _clip_score(row.get("current_eps_growth"), MIN_CURRENT_EPS_GROWTH, 1.0)
            + 0.20
            * _clip_score(
                row.get("core_profit_growth"),
                MIN_CORE_PROFIT_GROWTH,
                1.0,
            )
            + 0.20
            * _clip_score(
                row.get("current_sales_growth"),
                MIN_CURRENT_SALES_GROWTH,
                0.60,
            )
            + 0.10
            * _clip_score(row.get("eps_growth_acceleration"), -0.20, 0.30)
        )
        annual_score = (
            0.65
            * _clip_score(row.get("annual_eps_cagr"), MIN_ANNUAL_EPS_CAGR, 0.50)
            + 0.35 * _clip_score(row.get("roe"), MIN_ROE, 0.35)
        )
        leader_score = (
            0.70 * _clip_score(row.get("rs_rating"), MIN_RS_RATING, 100.0)
            + 0.30
            * _clip_score(
                row.get("industry_rs_rating"),
                MIN_INDUSTRY_RS_RATING,
                100.0,
            )
        )
        setup_score = (
            0.55 * _finite_number(row.get("base_quality", 0.0))
            + 0.30
            * _clip_score(row.get("accumulation_ratio"), 0.75, 2.0)
            + 0.15 * _finite_number(row.get("supply_percentile", 50.0))
        )
        score = (
            0.30 * current_score
            + 0.25 * annual_score
            + 0.25 * leader_score
            + 0.20 * setup_score
        )
        payload = row.to_dict()
        payload["c_score"] = float(current_score)
        payload["a_score"] = float(annual_score)
        payload["l_score"] = float(leader_score)
        payload["technical_proxy_score"] = float(setup_score)
        payload["score"] = float(np.clip(score, 0.0, 100.0))
        payload["veto_reasons"] = reasons
        payload["eligible"] = len(reasons) == 0
        rows.append(payload)
    ranked = pd.DataFrame(rows)
    return ranked.sort_values(
        ["eligible", "score", "rs_rating"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def classify_market_regime(index_prices):
    """从完整日线重建“调整—反弹尝试—跟进确认”状态。"""
    frame = _normalize_price_frame(index_prices, default_code=MARKET_INDEX)
    result = {
        "state": MARKET_UNKNOWN,
        "follow_through_date": None,
        "rally_start_date": None,
        "rally_low": np.nan,
        "distribution_days": 0,
    }
    if len(frame) < 60:
        return result
    frame = frame.sort_values("time").tail(MARKET_LOOKBACK).reset_index(drop=True)
    close = pd.to_numeric(frame["close"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    if (
        close.isna().any()
        or low.isna().any()
        or volume.isna().any()
        or (close <= 0).any()
        or (volume <= 0).any()
    ):
        return result

    state = MARKET_CORRECTION
    rally_start = None
    rally_low = np.nan
    follow_through = None
    follow_through_index = None
    distribution_indices = []

    for index in range(1, len(frame)):
        daily_return = close.iloc[index] / close.iloc[index - 1] - 1.0
        is_distribution = (
            daily_return <= -DISTRIBUTION_MIN_DROP
            and volume.iloc[index] > volume.iloc[index - 1]
        )

        if state == MARKET_CONFIRMED:
            distribution_indices = [
                prior
                for prior in distribution_indices
                if index - prior < DISTRIBUTION_WINDOW
                and close.iloc[index] < close.iloc[prior] * 1.05
            ]
            if is_distribution:
                distribution_indices.append(index)
            failed_low = (
                np.isfinite(rally_low) and low.iloc[index] < rally_low
            )
            if (
                failed_low
                or len(distribution_indices) >= MAX_DISTRIBUTION_DAYS
            ):
                state = MARKET_CORRECTION
                rally_start = None
                follow_through = None
                follow_through_index = None
            continue

        if state == MARKET_RALLY_ATTEMPT:
            if low.iloc[index] < rally_low:
                state = MARKET_CORRECTION
                rally_start = None
            else:
                day_number = index - rally_start + 1
                if (
                    day_number >= FOLLOW_THROUGH_MIN_DAY
                    and daily_return >= FOLLOW_THROUGH_MIN_GAIN
                    and volume.iloc[index] > volume.iloc[index - 1]
                ):
                    state = MARKET_CONFIRMED
                    follow_through = frame["time"].iloc[index]
                    follow_through_index = index
                    distribution_indices = []
                    continue

        if state == MARKET_CORRECTION and close.iloc[index] > close.iloc[index - 1]:
            state = MARKET_RALLY_ATTEMPT
            rally_start = index
            rally_low = min(low.iloc[index - 1], low.iloc[index])

    if state == MARKET_CONFIRMED and follow_through_index is not None:
        distribution_indices = [
            prior
            for prior in distribution_indices
            if len(frame) - 1 - prior < DISTRIBUTION_WINDOW
            and close.iloc[-1] < close.iloc[prior] * 1.05
        ]
    reported_state = state
    if (
        state == MARKET_CONFIRMED
        and len(distribution_indices) == MAX_DISTRIBUTION_DAYS - 1
    ):
        reported_state = MARKET_UNDER_PRESSURE
    result.update(
        {
            "state": reported_state,
            "follow_through_date": (
                follow_through.date()
                if follow_through is not None and hasattr(follow_through, "date")
                else follow_through
            ),
            "rally_start_date": (
                frame["time"].iloc[rally_start].date()
                if rally_start is not None
                else None
            ),
            "rally_low": float(rally_low) if np.isfinite(rally_low) else np.nan,
            "distribution_days": len(distribution_indices),
        }
    )
    return result


def position_exit_reason(
    current_price,
    average_cost,
    pivot,
    holding_days,
    close_50d_ma,
    volume_ratio,
    market_state,
    power_hold,
    technical_close=None,
):
    current_price = _finite_number(current_price)
    technical_close = _finite_number(technical_close)
    if not np.isfinite(technical_close):
        technical_close = current_price
    average_cost = _finite_number(average_cost)
    pivot = _finite_number(pivot)
    close_50d_ma = _finite_number(close_50d_ma)
    volume_ratio = _finite_number(volume_ratio)
    if (
        np.isfinite(current_price)
        and np.isfinite(average_cost)
        and average_cost > 0
        and current_price <= average_cost * (1.0 - HARD_STOP_LOSS)
    ):
        return "hard_stop"
    if market_state == MARKET_CORRECTION:
        return "market_correction"
    if (
        holding_days <= 10
        and np.isfinite(current_price)
        and np.isfinite(pivot)
        and current_price < pivot * (1.0 - FAILED_BREAKOUT_BUFFER)
    ):
        return "failed_breakout"
    if (
        np.isfinite(technical_close)
        and np.isfinite(close_50d_ma)
        and technical_close < close_50d_ma
        and np.isfinite(volume_ratio)
        and volume_ratio >= 1.20
    ):
        return "fifty_day_break"
    gain = safe_growth(current_price, average_cost)
    if np.isfinite(gain) and gain >= PROFIT_TARGET and not power_hold:
        return "profit_target"
    return None


def pyramid_target(stage, current_price, initial_price, pivot=None):
    stage = int(stage)
    current_weight = (
        FINAL_POSITION_WEIGHT
        if stage >= 3
        else SECOND_POSITION_WEIGHT
        if stage == 2
        else INITIAL_POSITION_WEIGHT
    )
    current_price_value = _finite_number(current_price)
    pivot_value = _finite_number(pivot)
    if (
        np.isfinite(current_price_value)
        and np.isfinite(pivot_value)
        and current_price_value > pivot_value * (1.0 + MAX_BUY_ZONE_EXTENSION)
    ):
        return current_weight, stage
    gain = safe_growth(current_price, initial_price)
    if stage >= 3:
        return FINAL_POSITION_WEIGHT, 3
    if not np.isfinite(gain):
        return current_weight, stage
    if stage == 1 and gain + 1e-12 >= FIRST_ADD_GAIN:
        return SECOND_POSITION_WEIGHT, 2
    if stage == 2 and gain + 1e-12 >= SECOND_ADD_GAIN:
        return FINAL_POSITION_WEIGHT, 3
    return current_weight, stage


def _fetch_universe(observation_date, current_data, min_listing_days=MIN_LISTING_DAYS):
    securities = get_all_securities(["stock"], date=observation_date)
    result = []
    for code, row in securities.iterrows():
        start_date = row.get("start_date")
        if hasattr(start_date, "date"):
            start_date = start_date.date()
        if not isinstance(start_date, dt.date):
            continue
        if (observation_date - start_date).days < min_listing_days:
            continue
        snapshot = current_data[code]
        if snapshot is None or getattr(snapshot, "paused", False):
            continue
        name = str(getattr(snapshot, "name", row.get("display_name", "")))
        if (
            getattr(snapshot, "is_st", False)
            or "ST" in name.upper()
            or "退" in name
        ):
            continue
        result.append(code)
    return result


def _fetch_price_history(
    codes,
    observation_date,
    count=PRICE_LOOKBACK,
    fields=None,
):
    fields = fields or ["open", "close", "high", "low", "volume", "money"]
    frames = []
    for batch in _chunked(codes, PRICE_BATCH_SIZE):
        try:
            raw = get_price(
                batch,
                end_date=observation_date,
                count=count,
                frequency="daily",
                fields=fields,
                skip_paused=False,
                fq="pre",
                panel=False,
            )
            default_code = batch[0] if len(batch) == 1 else None
            normalized = _normalize_price_frame(raw, default_code=default_code)
            if not normalized.empty:
                frames.append(normalized)
        except Exception as exc:
            _log("warning", "price batch failed: %s", exc)
    if not frames:
        return _normalize_price_frame(None)
    return pd.concat(frames, ignore_index=True)


def _fundamental_fields(include_roe=False):
    # JQData appends day/code/statDate to get_history_fundamentals results.
    fields = [
        income.basic_eps,
        indicator.adjusted_profit,
        income.total_operating_revenue,
    ]
    if include_roe:
        fields.append(indicator.roe)
    return fields


def _fetch_quarterly_fundamentals(codes, observation_date):
    frames = []
    for batch in _chunked(codes, FUNDAMENTAL_BATCH_SIZE):
        try:
            frame = get_history_fundamentals(
                batch,
                _fundamental_fields(),
                watch_date=observation_date,
                count=10,
                interval="1q",
            )
            if frame is not None and not frame.empty:
                frames.append(frame)
        except Exception as exc:
            _log("warning", "quarterly fundamentals batch failed: %s", exc)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _fetch_annual_fundamentals(codes, observation_date):
    frames = []
    for batch in _chunked(codes, FUNDAMENTAL_BATCH_SIZE):
        try:
            frame = get_history_fundamentals(
                batch,
                _fundamental_fields(include_roe=True),
                watch_date=observation_date,
                count=4,
                interval="1y",
                stat_by_year=True,
            )
            if frame is not None and not frame.empty:
                frames.append(frame)
        except Exception as exc:
            _log("warning", "annual fundamentals batch failed: %s", exc)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _fetch_circulating_market_caps(codes, observation_date):
    result = {}
    for batch in _chunked(codes, FUNDAMENTAL_BATCH_SIZE):
        try:
            request = query(
                valuation.code,
                valuation.circulating_market_cap,
                valuation.circulating_cap,
                valuation.capitalization,
            ).filter(valuation.code.in_(batch))
            frame = get_fundamentals(request, date=observation_date)
        except Exception as exc:
            _log("warning", "circulating market cap batch failed: %s", exc)
            continue
        if frame is None or frame.empty:
            continue
        for _, row in frame.iterrows():
            result[row["code"]] = _finite_number(
                row.get("circulating_market_cap", np.nan)
            )
    return result


def _industry_name(company):
    company = company if hasattr(company, "get") else {}
    sw_l1 = company.get("sw_l1", {}) or {}
    jq_l1 = company.get("jq_l1", {}) or {}
    name = sw_l1.get("industry_name") or jq_l1.get("industry_name")
    return name or "未知行业"


def _fetch_industries(codes, observation_date):
    result = {}
    for batch in _chunked(codes, FUNDAMENTAL_BATCH_SIZE):
        try:
            payload = get_industry(batch, date=observation_date)
        except Exception as exc:
            _log("warning", "industry batch failed: %s", exc)
            continue
        for code in batch:
            company = payload.get(code, {}) if hasattr(payload, "get") else {}
            result[code] = _industry_name(company)
    return result


def _build_fundamental_frame(codes, quarterly, annual, observation_date=None):
    if quarterly is None or annual is None or quarterly.empty or annual.empty:
        return pd.DataFrame()
    quarterly_groups = {
        code: group.copy() for code, group in quarterly.groupby("code")
    }
    annual_groups = {code: group.copy() for code, group in annual.groupby("code")}
    rows = []
    for code in codes:
        if code not in quarterly_groups or code not in annual_groups:
            continue
        features = build_fundamental_features(
            code,
            quarterly_groups[code],
            annual_groups[code],
            observation_date=observation_date,
        )
        if features is not None:
            rows.append(features)
    return pd.DataFrame(rows)


def _is_buyable(snapshot):
    if snapshot is None or getattr(snapshot, "paused", False):
        return False
    if getattr(snapshot, "is_st", False) or "退" in str(
        getattr(snapshot, "name", "")
    ):
        return False
    price = _finite_number(getattr(snapshot, "last_price", np.nan))
    high_limit = _finite_number(getattr(snapshot, "high_limit", np.nan))
    return (
        np.isfinite(price)
        and np.isfinite(high_limit)
        and price < high_limit - 1e-8
    )


def _is_sellable(snapshot):
    if snapshot is None or getattr(snapshot, "paused", False):
        return False
    price = _finite_number(getattr(snapshot, "last_price", np.nan))
    low_limit = _finite_number(getattr(snapshot, "low_limit", np.nan))
    return (
        np.isfinite(price)
        and np.isfinite(low_limit)
        and price > low_limit + 1e-8
    )


def _liquidity_features(prices):
    prices = _normalize_price_frame(prices)
    if prices.empty:
        return pd.DataFrame(columns=["code", "average_money_20d"])
    rows = []
    for code, group in prices.groupby("code", sort=False):
        money = pd.to_numeric(group["money"], errors="coerce").dropna()
        if money.empty:
            continue
        rows.append(
            {
                "code": code,
                "average_money_20d": money.tail(20).mean(),
            }
        )
    return pd.DataFrame(rows)


def refresh_watchlist(context):
    """周频重建观察池；失败时保留上一份，避免瞬时数据错误清空状态。"""
    _ensure_state()
    try:
        observation_date = _previous_trade_day(context.current_dt.date())
        current_data = get_current_data()
        universe = _fetch_universe(observation_date, current_data)
        liquidity_prices = _fetch_price_history(
            universe,
            observation_date,
            count=20,
            fields=["close", "money"],
        )
        liquidity = _liquidity_features(liquidity_prices)
        liquid_codes = list(
            liquidity.loc[
                liquidity["average_money_20d"].ge(MIN_AVERAGE_MONEY),
                "code",
            ]
        )
        if not liquid_codes:
            _log("warning", "O'Neil watchlist kept: no liquid securities")
            return

        close_prices = _fetch_price_history(
            liquid_codes,
            observation_date,
            count=PRICE_LOOKBACK,
            fields=["close"],
        )
        industries = _fetch_industries(liquid_codes, observation_date)
        relative = build_relative_strength_features(close_prices, industries)
        leaders = relative.loc[
            relative["rs_rating"].ge(MIN_RS_RATING)
            & relative["industry_rs_rating"].ge(MIN_INDUSTRY_RS_RATING)
            & relative["trend_ok"]
            & relative["near_high"]
        ].copy()
        leader_codes = list(leaders["code"])
        if not leader_codes:
            g.watchlist = []
            g.candidate_meta = {}
            g.watchlist_date = observation_date
            _log("info", "O'Neil watchlist %s: no RS leaders", observation_date)
            return

        full_prices = _fetch_price_history(
            leader_codes,
            observation_date,
            count=PRICE_LOOKBACK,
        )
        caps = _fetch_circulating_market_caps(leader_codes, observation_date)
        price_features = build_price_features(
            full_prices,
            industries=industries,
            circulating_caps=caps,
        )
        ranking_columns = [
            "code",
            "relative_strength_raw",
            "rs_rating",
            "industry_rs_rating",
            "industry",
        ]
        price_features = price_features.drop(
            columns=[
                column
                for column in ranking_columns[1:]
                if column in price_features.columns
            ]
        ).merge(leaders[ranking_columns], on="code", how="inner")
        price_candidates = price_features.loc[
            price_features["rs_rating"].ge(MIN_RS_RATING)
            & price_features["industry_rs_rating"].ge(MIN_INDUSTRY_RS_RATING)
            & price_features["setup_ready"]
        ].copy()
        codes = list(price_candidates["code"])
        if not codes:
            g.watchlist = []
            g.candidate_meta = {}
            g.watchlist_date = observation_date
            _log("info", "O'Neil watchlist %s: no price candidates", observation_date)
            return
        quarterly = _fetch_quarterly_fundamentals(codes, observation_date)
        annual = _fetch_annual_fundamentals(codes, observation_date)
        fundamentals = _build_fundamental_frame(
            codes,
            quarterly,
            annual,
            observation_date=observation_date,
        )
        ranked = score_candidates(fundamentals, price_candidates)
        eligible = ranked.loc[ranked["eligible"]].head(WATCHLIST_SIZE)
        g.watchlist = list(eligible["code"])
        g.candidate_meta = {
            row["code"]: row for row in eligible.to_dict("records")
        }
        g.watchlist_date = observation_date
        _log(
            "info",
            "O'Neil watchlist %s universe=%d priced=%d price_candidates=%d "
            "fundamental=%d eligible=%d",
            observation_date,
            len(universe),
            len(relative),
            len(price_candidates),
            len(fundamentals),
            len(eligible),
        )
    except Exception as exc:
        _log("error", "O'Neil watchlist kept after refresh failure: %s", exc)


def _history_by_code(prices):
    if prices is None or prices.empty:
        return {}
    return {
        code: group.sort_values("time").copy()
        for code, group in prices.groupby("code", sort=False)
    }


def _date_value(value, fallback):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return pd.Timestamp(value).date()
    except Exception:
        return fallback


def _sync_position_state(positions, today):
    _ensure_state()
    held = set(positions.keys())
    state_maps = (
        g.entry_dates,
        g.entry_prices,
        g.entry_pivots,
        g.pyramid_stages,
        g.power_hold_until,
    )
    for mapping in state_maps:
        for code in list(mapping.keys()):
            if code not in held:
                mapping.pop(code, None)
    for code, pending in list(g.pending_entries.items()):
        submitted_date = _date_value(pending.get("submitted_date"), today)
        if code not in held and submitted_date < today:
            g.pending_entries.pop(code, None)
    for code, pending in list(g.pending_pyramids.items()):
        if code not in held:
            g.pending_pyramids.pop(code, None)
    for code in list(g.pending_exits.keys()):
        if code not in held:
            g.pending_exits.pop(code, None)
    for code, position in positions.items():
        average_cost = _finite_number(getattr(position, "avg_cost", np.nan))
        pending_entry = g.pending_entries.pop(code, None)
        if code not in g.entry_dates:
            g.entry_dates[code] = (
                _date_value(pending_entry.get("submitted_date"), today)
                if pending_entry is not None
                else today
            )
        if code not in g.entry_prices and np.isfinite(average_cost):
            g.entry_prices[code] = average_cost
        if code not in g.entry_pivots:
            pending_pivot = (
                _finite_number(pending_entry.get("pivot", np.nan))
                if pending_entry is not None
                else np.nan
            )
            if np.isfinite(pending_pivot):
                g.entry_pivots[code] = pending_pivot
            elif np.isfinite(average_cost):
                g.entry_pivots[code] = average_cost
        if code not in g.pyramid_stages:
            g.pyramid_stages[code] = 1
        pending_pyramid = g.pending_pyramids.get(code)
        if pending_pyramid is None:
            continue
        total_amount = _finite_number(getattr(position, "total_amount", np.nan))
        target_amount = _finite_number(pending_pyramid.get("target_amount", np.nan))
        position_value = _finite_number(getattr(position, "value", np.nan))
        target_value = _finite_number(pending_pyramid.get("target_value", np.nan))
        filled = (
            np.isfinite(total_amount)
            and np.isfinite(target_amount)
            and total_amount + 1e-8 >= target_amount
        ) or (
            not np.isfinite(total_amount)
            and np.isfinite(position_value)
            and np.isfinite(target_value)
            and position_value >= target_value * 0.97
        )
        if filled:
            g.pyramid_stages[code] = int(pending_pyramid["next_stage"])
            g.pending_pyramids.pop(code, None)
        elif _date_value(pending_pyramid.get("submitted_date"), today) < today:
            g.pending_pyramids.pop(code, None)


def _position_history_metrics(history):
    if history is None or history.empty:
        return np.nan, np.nan
    close = pd.to_numeric(history["close"], errors="coerce").dropna()
    volume = pd.to_numeric(history["volume"], errors="coerce").dropna()
    ma50 = close.tail(50).mean() if len(close) >= 50 else np.nan
    volume_ratio = (
        safe_divide(volume.iloc[-1], volume.iloc[-51:-1].mean())
        if len(volume) >= 51
        else np.nan
    )
    return ma50, volume_ratio


def _try_target_value(code, target_value, snapshot, increasing):
    if increasing and not _is_buyable(snapshot):
        return None
    if not increasing and not _is_sellable(snapshot):
        return None
    target_value = _finite_number(target_value)
    if not np.isfinite(target_value) or target_value < 0:
        return None
    try:
        return order_target_value(code, target_value)
    except Exception as exc:
        _log("warning", "target order failed for %s: %s", code, exc)
        return None


def _order_is_accepted(order):
    if order is None:
        return False
    status = str(getattr(order, "status", "")).lower()
    if "cancel" in status or "reject" in status:
        return False
    amount = _finite_number(getattr(order, "amount", np.nan))
    filled = _finite_number(getattr(order, "filled", np.nan))
    if np.isfinite(amount) and amount <= 0:
        return np.isfinite(filled) and filled > 0
    return True


def _pending_target_amount(order, current_amount, fallback_target_amount):
    current_amount = _finite_number(current_amount)
    fallback_target_amount = _finite_number(fallback_target_amount)
    order_amount = _finite_number(getattr(order, "amount", np.nan))
    if np.isfinite(current_amount) and np.isfinite(order_amount) and order_amount > 0:
        return current_amount + order_amount
    return fallback_target_amount


def daily_trade(context):
    """先处理退出；有退出尝试的当日不假定现金已释放，也不建立替代仓位。"""
    _ensure_state()
    try:
        today = context.current_dt.date()
        observation_date = _previous_trade_day(today)
        current_data = get_current_data()
        market_prices = _fetch_price_history(
            [MARKET_INDEX],
            observation_date,
            count=MARKET_LOOKBACK,
        )
        market = classify_market_regime(market_prices)
        g.market_state = market["state"]

        positions = context.portfolio.positions
        _sync_position_state(positions, today)
        research_codes = list(
            dict.fromkeys(list(positions.keys()) + list(g.watchlist))
        )
        prices = _fetch_price_history(
            research_codes,
            observation_date,
            count=PRICE_LOOKBACK,
        )
        histories = _history_by_code(prices)

        exit_signals = []
        for code, position in list(positions.items()):
            snapshot = current_data[code]
            history = histories.get(code)
            current_price = _finite_number(
                getattr(snapshot, "last_price", np.nan)
            )
            average_cost = _finite_number(getattr(position, "avg_cost", np.nan))
            entry_date = _date_value(g.entry_dates.get(code), today)
            holding_days = max(0, (today - entry_date).days)
            initial_price = _finite_number(
                g.entry_prices.get(code, average_cost)
            )
            gain = safe_growth(current_price, initial_price)
            if (
                np.isfinite(gain)
                and gain >= FAST_GAIN
                and holding_days <= FAST_GAIN_DAYS
                and code not in g.power_hold_until
            ):
                g.power_hold_until[code] = entry_date + dt.timedelta(
                    days=POWER_HOLD_DAYS
                )
            hold_until = _date_value(g.power_hold_until.get(code), today)
            power_hold = code in g.power_hold_until and today < hold_until
            ma50, volume_ratio = _position_history_metrics(history)
            technical_close = (
                _finite_number(history["close"].iloc[-1])
                if history is not None and not history.empty
                else np.nan
            )
            pending_exit = g.pending_exits.get(code)
            reason = (
                pending_exit.get("reason")
                if pending_exit is not None
                else position_exit_reason(
                    current_price=current_price,
                    technical_close=technical_close,
                    average_cost=average_cost,
                    pivot=g.entry_pivots.get(code, average_cost),
                    holding_days=holding_days,
                    close_50d_ma=ma50,
                    volume_ratio=volume_ratio,
                    market_state=market["state"],
                    power_hold=power_hold,
                )
            )
            if reason is None:
                continue
            if code not in g.pending_exits:
                g.pending_exits[code] = {
                    "triggered_date": today,
                    "reason": reason,
                }
            status = "blocked"
            if _is_sellable(snapshot):
                try:
                    order = order_target_value(code, 0)
                    status = (
                        "submitted"
                        if _order_is_accepted(order)
                        else "rejected"
                    )
                except Exception as exc:
                    status = "failed"
                    _log("warning", "sell failed for %s (%s): %s", code, reason, exc)
            else:
                _log("warning", "sell blocked for %s (%s)", code, reason)
            exit_signals.append((code, reason, status))

        if exit_signals:
            _log(
                "info",
                "O'Neil exits %s market=%s signals=%s",
                observation_date,
                market["state"],
                exit_signals,
            )
            return
        if market["state"] != MARKET_CONFIRMED:
            _log(
                "info",
                "O'Neil no new risk %s market=%s distributions=%d",
                observation_date,
                market["state"],
                market["distribution_days"],
            )
            return

        total_value = _finite_number(context.portfolio.total_value)
        available_cash = _usable_cash(
            getattr(context.portfolio, "available_cash", 0.0)
        )
        if not np.isfinite(total_value) or total_value <= 0:
            return

        for code, position in list(positions.items()):
            if code in g.pending_pyramids:
                continue
            snapshot = current_data[code]
            current_price = _finite_number(
                getattr(snapshot, "last_price", np.nan)
            )
            initial_price = _finite_number(
                g.entry_prices.get(
                    code,
                    getattr(position, "avg_cost", np.nan),
                )
            )
            stage = int(g.pyramid_stages.get(code, 1))
            target_weight, next_stage = pyramid_target(
                stage,
                current_price,
                initial_price,
                pivot=g.entry_pivots.get(code, np.nan),
            )
            if next_stage <= stage:
                continue
            current_value = _finite_number(getattr(position, "value", 0.0))
            target_value = _round_buy_target_value(
                current_value,
                total_value * target_weight,
                current_price,
            )
            additional = target_value - current_value
            if (
                not np.isfinite(additional)
                or additional <= 0
                or additional > available_cash
            ):
                continue
            order = _try_target_value(
                code,
                target_value,
                snapshot,
                increasing=True,
            )
            if _order_is_accepted(order):
                current_amount = _finite_number(
                    getattr(position, "total_amount", np.nan)
                )
                if not np.isfinite(current_amount):
                    current_amount = current_value / current_price
                g.pending_pyramids[code] = {
                    "submitted_date": today,
                    "next_stage": next_stage,
                    "target_value": target_value,
                    "target_amount": _pending_target_amount(
                        order,
                        current_amount,
                        target_value / current_price,
                    ),
                }
                available_cash -= additional

        occupied = set(positions.keys())
        available_slots = max(0, MAX_POSITIONS - len(occupied))
        if available_slots <= 0:
            return
        for code in g.watchlist:
            if code in occupied or available_slots <= 0:
                continue
            history = histories.get(code)
            if history is None or history.empty:
                continue
            breakout = detect_breakout(history)
            if not breakout["is_breakout"]:
                continue
            snapshot = current_data[code]
            if not _is_buyable(snapshot):
                continue
            current_price = _finite_number(
                getattr(snapshot, "last_price", np.nan)
            )
            pivot = _finite_number(breakout["pivot"])
            if (
                not np.isfinite(current_price)
                or not np.isfinite(pivot)
                or current_price < pivot
                or current_price > pivot * (1.0 + MAX_BUY_ZONE_EXTENSION)
            ):
                continue
            target_value = _round_buy_target_value(
                0.0,
                total_value * INITIAL_POSITION_WEIGHT,
                current_price,
            )
            if (
                not np.isfinite(target_value)
                or target_value <= 0
                or target_value > available_cash
            ):
                continue
            order = _try_target_value(
                code,
                target_value,
                snapshot,
                increasing=True,
            )
            if not _order_is_accepted(order):
                continue
            g.pending_entries[code] = {
                "submitted_date": today,
                "submitted_price": current_price,
                "pivot": pivot,
                "target_value": target_value,
                "target_amount": _pending_target_amount(
                    order,
                    0.0,
                    target_value / current_price,
                ),
            }
            available_cash -= target_value
            occupied.add(code)
            available_slots -= 1
            _log(
                "info",
                "O'Neil entry %s code=%s pivot=%.3f price=%.3f score=%.1f",
                observation_date,
                code,
                pivot,
                current_price,
                _finite_number(g.candidate_meta.get(code, {}).get("score", np.nan)),
            )
    except Exception as exc:
        _log("error", "O'Neil daily trade aborted: %s", exc)
