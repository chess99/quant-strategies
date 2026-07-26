# ruff: noqa: F403, F405
"""欧奈尔 CAN SLIM A 股正式候选版。

候选发现采用“成熟增长/景气反转”双通道：前者要求已兑现的 EPS、扣非利润、营收
与年度质量，后者允许利润仍亏，但必须同时出现营收高增长、利润改善或点时可见的
积极业绩预告，以及更高的价格相对强度。入场仍要求规范整理后的枢轴放量突破；
持仓使用小亏退出、盈利加仓和 20/50 日线趋势退出。市场层对上证、沪深300、
创业板和科创50分别判定状态并分配新增风险预算。

文件自包含，可直接复制到聚宽。所有选股信号默认只使用前一交易日及当时已披露数据。
"""

import builtins
import datetime as dt
import math

import numpy as np
import pandas as pd

try:
    from jqdata import *  # noqa: F403
    from jqdata import finance
except ImportError:
    pass


BENCHMARK = "000300.XSHG"
MARKET_INDEX = "000001.XSHG"
MARKET_INDEXES = (
    "000001.XSHG",
    "000300.XSHG",
    "399006.XSHE",
    "000688.XSHG",
)

MARKET_UNKNOWN = "unknown"
MARKET_CORRECTION = "correction"
MARKET_RALLY_ATTEMPT = "rally_attempt"
MARKET_CONFIRMED = "confirmed_uptrend"
MARKET_UNDER_PRESSURE = "uptrend_under_pressure"

MAX_POSITIONS = 6
WATCHLIST_SIZE = 80
ENTRY_DIAGNOSTIC_SAMPLE_SIZE = 8
MIN_LISTING_DAYS = 120
MIN_AVERAGE_MONEY = 5e7
PRICE_LOOKBACK = 260
MARKET_LOOKBACK = 750
MIN_RS_HISTORY = 253
PRICE_BATCH_SIZE = 300
FUNDAMENTAL_BATCH_SIZE = 300
MAX_REPORT_AGE_DAYS = 240

MIN_CURRENT_EPS_GROWTH = 0.20
MIN_CORE_PROFIT_GROWTH = 0.15
MIN_CURRENT_SALES_GROWTH = 0.15
MIN_ANNUAL_EPS_CAGR = 0.12
MIN_ROE = 0.12
MIN_EMERGING_SALES_GROWTH = 0.30
MIN_EMERGING_RS_RATING = 90.0
MIN_POSITIVE_FORECAST_GROWTH = 0.30
MAX_FORECAST_AGE_DAYS = 180
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
TWENTY_DAY_TRAIL_MIN_GAIN = 0.10


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


def _midpoint(first, second):
    values = [
        value
        for value in (_finite_number(first), _finite_number(second))
        if np.isfinite(value)
    ]
    return builtins.sum(values) / float(len(values)) if values else np.nan


def prepare_forecast_features(rows, observation_date):
    """Normalize the latest forecast that was public by ``observation_date``."""
    columns = [
        "code",
        "forecast_pub_date",
        "forecast_end_date",
        "forecast_profit_growth",
        "forecast_profit_mid",
        "forecast_prior_profit",
        "forecast_positive",
        "forecast_turnaround",
    ]
    if rows is None or rows.empty:
        return pd.DataFrame(columns=columns)
    frame = rows.copy()
    required = (
        "code",
        "pub_date",
        "end_date",
        "profit_ratio_min",
        "profit_ratio_max",
        "profit_min",
        "profit_max",
        "profit_last",
    )
    for column in required:
        if column not in frame.columns:
            frame[column] = np.nan
    frame["pub_date"] = pd.to_datetime(frame["pub_date"], errors="coerce")
    frame["end_date"] = pd.to_datetime(frame["end_date"], errors="coerce")
    observation = pd.Timestamp(observation_date).normalize()
    frame = frame.loc[
        frame["code"].notna()
        & frame["pub_date"].notna()
        & frame["pub_date"].le(observation)
        & frame["pub_date"].ge(
            observation - pd.Timedelta(days=MAX_FORECAST_AGE_DAYS)
        )
    ].copy()
    if frame.empty:
        return pd.DataFrame(columns=columns)
    frame = (
        frame.sort_values(["code", "pub_date", "end_date"])
        .drop_duplicates("code", keep="last")
        .reset_index(drop=True)
    )
    output = []
    for _, row in frame.iterrows():
        growth = _midpoint(
            row.get("profit_ratio_min"), row.get("profit_ratio_max")
        )
        growth = growth / 100.0 if np.isfinite(growth) else np.nan
        profit_mid = _midpoint(row.get("profit_min"), row.get("profit_max"))
        prior_profit = _finite_number(row.get("profit_last"))
        positive = bool(np.isfinite(profit_mid) and profit_mid > 0.0)
        turnaround = bool(
            positive and np.isfinite(prior_profit) and prior_profit <= 0.0
        )
        output.append(
            {
                "code": row["code"],
                "forecast_pub_date": row["pub_date"],
                "forecast_end_date": row["end_date"],
                "forecast_profit_growth": growth,
                "forecast_profit_mid": profit_mid,
                "forecast_prior_profit": prior_profit,
                "forecast_positive": positive,
                "forecast_turnaround": turnaround,
            }
        )
    return pd.DataFrame(output, columns=columns)


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

    annual = pd.DataFrame()
    if annual_history is not None and not annual_history.empty:
        annual = annual_history.copy()
        annual["statDate"] = pd.to_datetime(annual["statDate"], errors="coerce")
        annual = (
            annual.loc[annual["code"] == code]
            .dropna(subset=["statDate"])
            .sort_values("statDate")
            .drop_duplicates("statDate", keep="last")
            .tail(4)
        )
    annual_eps = []
    annual_years = []
    for _, row in annual.iterrows():
        eps = _finite_number(row.get("basic_eps", np.nan))
        annual_eps.append(eps)
        annual_years.append(pd.Timestamp(row["statDate"]).year)
    enough_annual = len(annual_eps) >= 3
    consecutive_years = enough_annual and builtins.all(
        annual_years[index + 1] - annual_years[index] == 1
        for index in range(len(annual_years) - 1)
    )
    positive_annual = enough_annual and builtins.all(
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
    year_span = annual_years[-1] - annual_years[0] if enough_annual else 0
    annual_cagr = (
        compound_growth(annual_eps[-1], annual_eps[0], year_span)
        if enough_annual and year_span > 0
        else np.nan
    )
    roe = (
        _as_ratio(annual.iloc[-1].get("roe", np.nan))
        if not annual.empty
        else np.nan
    )

    return {
        "code": code,
        "current_report_date": current["statDate"],
        "current_report_age_days": current_report_age_days,
        "current_eps_growth": current_eps_growth,
        "core_profit_growth": core_profit_growth,
        "current_sales_growth": current_sales_growth,
        "current_profit": current_profit,
        "year_ago_profit": year_ago_profit,
        "previous_eps_growth": previous_eps_growth,
        "eps_growth_acceleration": acceleration,
        "current_margin": current_margin,
        "margin_change": margin_change,
        "annual_eps_cagr": annual_cagr,
        "annual_eps_increasing": bool(annual_increasing),
        "roe": roe,
    }


def classify_fundamental_track(row):
    """Return the auditable fundamental path; do not silently fill missing data."""
    eps_growth = _finite_number(row.get("current_eps_growth", np.nan))
    profit_growth = _finite_number(row.get("core_profit_growth", np.nan))
    sales_growth = _finite_number(row.get("current_sales_growth", np.nan))
    annual_cagr = _finite_number(row.get("annual_eps_cagr", np.nan))
    roe = _finite_number(row.get("roe", np.nan))
    established = (
        np.isfinite(eps_growth)
        and eps_growth >= MIN_CURRENT_EPS_GROWTH
        and np.isfinite(profit_growth)
        and profit_growth >= MIN_CORE_PROFIT_GROWTH
        and np.isfinite(sales_growth)
        and sales_growth >= MIN_CURRENT_SALES_GROWTH
        and np.isfinite(annual_cagr)
        and annual_cagr >= MIN_ANNUAL_EPS_CAGR
        and np.isfinite(roe)
        and roe >= MIN_ROE
    )
    if established:
        return "established_growth"

    current_profit = _finite_number(row.get("current_profit", np.nan))
    year_ago_profit = _finite_number(row.get("year_ago_profit", np.nan))
    realized_improvement = bool(
        np.isfinite(current_profit)
        and np.isfinite(year_ago_profit)
        and current_profit > year_ago_profit
    )
    forecast_growth = _finite_number(
        row.get("forecast_profit_growth", np.nan)
    )
    positive_forecast = (
        bool(row.get("forecast_positive", False))
        and np.isfinite(forecast_growth)
        and forecast_growth >= MIN_POSITIVE_FORECAST_GROWTH
    )
    forecast_improvement = bool(row.get("forecast_turnaround", False)) or (
        positive_forecast
    )
    rs_rating = _finite_number(row.get("rs_rating", np.nan))
    industry_rs = _finite_number(row.get("industry_rs_rating", np.nan))
    emerging = (
        np.isfinite(sales_growth)
        and sales_growth >= MIN_EMERGING_SALES_GROWTH
        and (realized_improvement or forecast_improvement)
        and np.isfinite(rs_rating)
        and rs_rating >= MIN_EMERGING_RS_RATING
        and np.isfinite(industry_rs)
        and industry_rs >= MIN_INDUSTRY_RS_RATING
    )
    return "emerging_leader" if emerging else None


def _candidate_vetoes(row):
    reasons = []
    report_age = _finite_number(row.get("current_report_age_days", np.nan))
    if (
        not np.isfinite(report_age)
        or report_age < 0
        or report_age > MAX_REPORT_AGE_DAYS
    ):
        reasons.append("stale_financials")
    track = classify_fundamental_track(row)
    if track is None:
        reasons.append("fundamental_track")
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
        fundamental_track = classify_fundamental_track(row)
        forecast_score = max(
            _clip_score(
                row.get("forecast_profit_growth"),
                MIN_POSITIVE_FORECAST_GROWTH,
                1.50,
            ),
            100.0 if bool(row.get("forecast_turnaround", False)) else 0.0,
        )
        current_score = (
            0.35
            * _clip_score(row.get("current_eps_growth"), MIN_CURRENT_EPS_GROWTH, 1.0)
            + 0.20
            * _clip_score(
                row.get("core_profit_growth"),
                MIN_CORE_PROFIT_GROWTH,
                1.0,
            )
            + 0.30
            * _clip_score(
                row.get("current_sales_growth"),
                MIN_CURRENT_SALES_GROWTH,
                1.00,
            )
            + 0.15 * forecast_score
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
        payload["fundamental_track"] = fundamental_track
        payload["score"] = float(np.clip(score, 0.0, 100.0))
        payload["veto_reasons"] = reasons
        payload["eligible"] = len(reasons) == 0
        rows.append(payload)
    ranked = pd.DataFrame(rows)
    return ranked.sort_values(
        ["eligible", "score", "rs_rating"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def summarize_candidate_vetoes(ranked):
    """Count veto reason occurrences; reasons are deliberately non-exclusive."""
    counts = {}
    if ranked is None or ranked.empty or "veto_reasons" not in ranked.columns:
        return counts
    for reasons in ranked["veto_reasons"]:
        for reason in reasons or []:
            counts[reason] = counts.get(reason, 0) + 1
    return counts


def classify_market_regime(index_prices):
    """从完整日线重建“调整—反弹尝试—跟进确认”状态。"""
    frame = _normalize_price_frame(index_prices, default_code=MARKET_INDEX)
    result = {
        "state": MARKET_UNKNOWN,
        "follow_through_date": None,
        "rally_start_date": None,
        "rally_low": np.nan,
        "distribution_days": 0,
        "correction_reason": None,
        "transition_distribution_days": 0,
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
    correction_reason = None
    transition_distribution_days = 0

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
                if failed_low and len(distribution_indices) >= MAX_DISTRIBUTION_DAYS:
                    correction_reason = "rally_low_and_distribution_days"
                elif failed_low:
                    correction_reason = "rally_low"
                else:
                    correction_reason = "distribution_days"
                transition_distribution_days = len(distribution_indices)
                state = MARKET_CORRECTION
                rally_start = None
                follow_through = None
                follow_through_index = None
                distribution_indices = []
            continue

        if state == MARKET_RALLY_ATTEMPT:
            if low.iloc[index] < rally_low:
                state = MARKET_CORRECTION
                rally_start = None
                correction_reason = "rally_low"
                transition_distribution_days = 0
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
            correction_reason = None
            transition_distribution_days = 0

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
            "correction_reason": correction_reason,
            "transition_distribution_days": transition_distribution_days,
        }
    )
    return result


def aggregate_market_states(states):
    values = list(states.values()) if hasattr(states, "values") else list(states)
    confirmed_count = builtins.sum(
        1 for state in values if state == MARKET_CONFIRMED
    )
    total_count = len(values)
    if total_count <= 0:
        return {
            "state": MARKET_UNKNOWN,
            "exposure": 0.0,
            "confirmed_count": 0,
            "total_count": 0,
        }
    if confirmed_count >= 3:
        state, exposure = MARKET_CONFIRMED, 1.0
    elif confirmed_count == 2:
        state, exposure = MARKET_CONFIRMED, 0.70
    elif confirmed_count == 1:
        state, exposure = MARKET_UNDER_PRESSURE, 0.35
    else:
        state, exposure = MARKET_CORRECTION, 0.0
    return {
        "state": state,
        "exposure": exposure,
        "confirmed_count": confirmed_count,
        "total_count": total_count,
    }


def classify_market_indexes(index_prices):
    frame = _normalize_price_frame(index_prices)
    details = {}
    states = {}
    for code in MARKET_INDEXES:
        group = frame.loc[frame["code"] == code].copy()
        if group.empty:
            continue
        detail = classify_market_regime(group)
        details[code] = detail
        if detail["state"] != MARKET_UNKNOWN:
            states[code] = detail["state"]
    aggregate = aggregate_market_states(states)
    aggregate["index_states"] = states
    aggregate["index_details"] = details
    aggregate["distribution_days"] = builtins.sum(
        int(detail.get("distribution_days", 0) or 0)
        for detail in details.values()
    )
    aggregate["correction_reason"] = (
        "no_confirmed_index"
        if aggregate["state"] == MARKET_CORRECTION and states
        else None
    )
    aggregate["transition_distribution_days"] = builtins.sum(
        int(detail.get("transition_distribution_days", 0) or 0)
        for detail in details.values()
    )
    return aggregate


def position_exit_reason(
    current_price,
    average_cost,
    pivot,
    holding_days,
    close_20d_ma,
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
    close_20d_ma = _finite_number(close_20d_ma)
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
    gain = safe_growth(current_price, average_cost)
    if (
        np.isfinite(technical_close)
        and np.isfinite(close_20d_ma)
        and technical_close < close_20d_ma
        and np.isfinite(gain)
        and gain >= TWENTY_DAY_TRAIL_MIN_GAIN
        and np.isfinite(volume_ratio)
        and volume_ratio >= 1.20
    ):
        return "twenty_day_break"
    if (
        np.isfinite(technical_close)
        and np.isfinite(close_50d_ma)
        and technical_close < close_50d_ma
        and np.isfinite(volume_ratio)
        and volume_ratio >= 1.20
    ):
        return "fifty_day_break"
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


def _fetch_forecasts(codes, observation_date):
    frames = []
    cutoff = observation_date - dt.timedelta(days=MAX_FORECAST_AGE_DAYS)
    table = finance.STK_FIN_FORCAST
    for batch in _chunked(codes, FUNDAMENTAL_BATCH_SIZE):
        try:
            request = query(
                table.code,
                table.pub_date,
                table.end_date,
                table.profit_ratio_min,
                table.profit_ratio_max,
                table.profit_min,
                table.profit_max,
                table.profit_last,
            ).filter(
                table.code.in_(batch),
                finance.STK_FIN_FORCAST.pub_date <= observation_date,
                table.pub_date >= cutoff,
            )
            frame = finance.run_query(request)
            if frame is not None and not frame.empty:
                frames.append(frame)
        except Exception as exc:
            _log("warning", "forecast batch failed: %s", exc)
    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return prepare_forecast_features(raw, observation_date)


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
    if quarterly is None or quarterly.empty:
        return pd.DataFrame()
    quarterly_groups = {
        code: group.copy() for code, group in quarterly.groupby("code")
    }
    annual_groups = (
        {code: group.copy() for code, group in annual.groupby("code")}
        if annual is not None and not annual.empty
        else {}
    )
    rows = []
    for code in codes:
        if code not in quarterly_groups:
            continue
        features = build_fundamental_features(
            code,
            quarterly_groups[code],
            annual_groups.get(code, pd.DataFrame()),
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
        forecasts = _fetch_forecasts(codes, observation_date)
        if not fundamentals.empty and not forecasts.empty:
            fundamentals = fundamentals.merge(forecasts, on="code", how="left")
        ranked = score_candidates(fundamentals, price_candidates)
        eligible = ranked.loc[ranked["eligible"]].head(WATCHLIST_SIZE)
        veto_counts = summarize_candidate_vetoes(ranked)
        track_counts = (
            eligible["fundamental_track"].value_counts().to_dict()
            if not eligible.empty
            else {}
        )
        g.watchlist = list(eligible["code"])
        g.candidate_meta = {
            row["code"]: row for row in eligible.to_dict("records")
        }
        g.watchlist_date = observation_date
        _log(
            "info",
            "O'Neil watchlist %s universe=%d priced=%d price_candidates=%d "
            "fundamental=%d eligible=%d tracks=%s veto_hits=%s eligible_codes=%s",
            observation_date,
            len(universe),
            len(relative),
            len(price_candidates),
            len(fundamentals),
            len(eligible),
            _format_counts(track_counts),
            _format_counts(veto_counts),
            ",".join(g.watchlist[:ENTRY_DIAGNOSTIC_SAMPLE_SIZE]) or "-",
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
        return np.nan, np.nan, np.nan
    close = pd.to_numeric(history["close"], errors="coerce").dropna()
    volume = pd.to_numeric(history["volume"], errors="coerce").dropna()
    ma20 = close.tail(20).mean() if len(close) >= 20 else np.nan
    ma50 = close.tail(50).mean() if len(close) >= 50 else np.nan
    volume_ratio = (
        safe_divide(volume.iloc[-1], volume.iloc[-51:-1].mean())
        if len(volume) >= 51
        else np.nan
    )
    return ma20, ma50, volume_ratio


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


def _evaluate_entry_candidate(
    code,
    history,
    current_data,
    total_value,
    available_cash,
):
    """Return the first entry blocker without changing portfolio state."""
    result = {
        "code": code,
        "blocker": "missing_history",
        "breakout_reasons": [],
        "history_ready": False,
        "breakout": False,
        "buyable": False,
        "buy_zone": False,
        "board_lot": False,
        "cash_ready": False,
        "pivot": np.nan,
        "current_price": np.nan,
        "target_value": np.nan,
    }
    if history is None or history.empty:
        return result

    result["history_ready"] = True
    breakout = detect_breakout(history)
    result["breakout_reasons"] = list(breakout.get("reasons", []))
    pivot = _finite_number(breakout.get("pivot", np.nan))
    result["pivot"] = pivot
    if not breakout.get("is_breakout", False):
        result["blocker"] = "no_breakout"
        return result

    result["breakout"] = True
    snapshot = current_data[code] if current_data is not None else None
    if snapshot is None or not _is_buyable(snapshot):
        result["blocker"] = "not_buyable"
        return result

    result["buyable"] = True
    current_price = _finite_number(getattr(snapshot, "last_price", np.nan))
    result["current_price"] = current_price
    if not np.isfinite(current_price) or not np.isfinite(pivot):
        result["blocker"] = "invalid_price"
        return result
    if current_price < pivot:
        result["blocker"] = "below_pivot"
        return result
    if current_price > pivot * (1.0 + MAX_BUY_ZONE_EXTENSION):
        result["blocker"] = "extended"
        return result

    result["buy_zone"] = True
    target_value = _round_buy_target_value(
        0.0,
        _finite_number(total_value) * INITIAL_POSITION_WEIGHT,
        current_price,
    )
    result["target_value"] = target_value
    if not np.isfinite(target_value) or target_value <= 0:
        result["blocker"] = "board_lot"
        return result

    result["board_lot"] = True
    if target_value > _usable_cash(available_cash):
        result["blocker"] = "cash"
        return result

    result["cash_ready"] = True
    result["blocker"] = "ready"
    return result


def _summarize_entry_funnel(evaluations):
    """Aggregate monotonic entry stages and explicit first blockers."""
    stages = (
        "history_ready",
        "breakout",
        "buyable",
        "buy_zone",
        "board_lot",
        "cash_ready",
    )
    summary = {"watchlist": len(evaluations)}
    for stage in stages:
        summary[stage] = 0
    blockers = {}
    breakout_reasons = {}
    outcomes = {}
    for evaluation in evaluations:
        for stage in stages:
            if evaluation.get(stage, False):
                summary[stage] += 1
        blocker = evaluation.get("blocker", "unknown")
        blockers[blocker] = blockers.get(blocker, 0) + 1
        if blocker == "no_breakout":
            for reason in evaluation.get("breakout_reasons", []):
                breakout_reasons[reason] = breakout_reasons.get(reason, 0) + 1
        outcome = evaluation.get("outcome")
        if outcome:
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
    summary["blockers"] = blockers
    summary["breakout_reasons"] = breakout_reasons
    summary["outcomes"] = outcomes
    blocker_total = 0
    for count in blockers.values():
        blocker_total += count
    outcome_total = 0
    for count in outcomes.values():
        outcome_total += count
    summary["candidate_gap"] = summary["watchlist"] - blocker_total
    summary["outcome_gap"] = summary["cash_ready"] - outcome_total
    return summary


def _format_counts(counts):
    if not counts:
        return "-"
    return ",".join(
        "%s:%d" % (name, counts[name]) for name in sorted(counts.keys())
    )


def _format_entry_samples(evaluations):
    blocker_priority = {
        "ready": 0,
        "cash": 1,
        "board_lot": 2,
        "extended": 3,
        "below_pivot": 3,
        "invalid_price": 3,
        "not_buyable": 4,
        "no_breakout": 5,
        "missing_history": 6,
        "diagnostic_error": 7,
    }
    ranked = sorted(
        evaluations,
        key=lambda item: blocker_priority.get(item.get("blocker"), 8),
    )
    samples = []
    for evaluation in ranked[:ENTRY_DIAGNOSTIC_SAMPLE_SIZE]:
        blocker = evaluation.get("blocker", "unknown")
        detail = blocker
        reasons = evaluation.get("breakout_reasons", [])
        if blocker == "no_breakout" and reasons:
            detail += "[%s]" % "+".join(reasons)
        elif blocker == "diagnostic_error":
            error = str(evaluation.get("diagnostic_error", "unknown"))
            error = " ".join(error.replace("\r", " ").replace("\n", " ").split())
            detail += "[%s]" % error[:80]
        elif evaluation.get("breakout", False):
            pivot = _finite_number(evaluation.get("pivot", np.nan))
            price = _finite_number(evaluation.get("current_price", np.nan))
            detail += "[pivot=%.3f,price=%.3f]" % (pivot, price)
        samples.append("%s:%s" % (evaluation.get("code", "?"), detail))
    return ";".join(samples) if samples else "-"


def _log_entry_funnel(
    observation_date,
    market_state,
    market_allows_entries,
    watchlist_size,
    already_held,
    evaluations,
    available_slots,
    submitted,
    order_rejected,
):
    summary = _summarize_entry_funnel(evaluations)
    watchlist_gap = watchlist_size - already_held - summary["watchlist"]
    market_ready = summary["cash_ready"] if market_allows_entries else 0
    slot_ready = max(
        0,
        market_ready - summary["outcomes"].get("slot_blocked", 0),
    )
    _log(
        "info",
        "O'Neil entry funnel %s market=%s watchlist=%d already_held=%d candidates=%d "
        "history_ready=%d breakout=%d buyable=%d buy_zone=%d "
        "board_lot=%d cash_ready=%d market_ready=%d slot_ready=%d slots=%d "
        "submitted=%d order_rejected=%d blockers=%s outcomes=%s "
        "watchlist_gap=%d candidate_gap=%d outcome_gap=%d "
        "breakout_reason_hits=%s samples=%s",
        observation_date,
        market_state,
        watchlist_size,
        already_held,
        summary["watchlist"],
        summary["history_ready"],
        summary["breakout"],
        summary["buyable"],
        summary["buy_zone"],
        summary["board_lot"],
        summary["cash_ready"],
        market_ready,
        slot_ready,
        available_slots,
        submitted,
        order_rejected,
        _format_counts(summary["blockers"]),
        _format_counts(summary["outcomes"]),
        watchlist_gap,
        summary["candidate_gap"],
        summary["outcome_gap"],
        _format_counts(summary["breakout_reasons"]),
        _format_entry_samples(evaluations),
    )


def daily_trade(context):
    """先处理退出；有退出尝试的当日不假定现金已释放，也不建立替代仓位。"""
    _ensure_state()
    try:
        today = context.current_dt.date()
        observation_date = _previous_trade_day(today)
        current_data = get_current_data()
        market_prices = _fetch_price_history(
            list(MARKET_INDEXES),
            observation_date,
            count=MARKET_LOOKBACK,
        )
        market = classify_market_indexes(market_prices)
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
            ma20, ma50, volume_ratio = _position_history_metrics(history)
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
                    close_20d_ma=ma20,
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
                "O'Neil exits %s market=%s correction_reason=%s "
                "transition_distributions=%d signals=%s",
                observation_date,
                market["state"],
                market.get("correction_reason") or "-",
                market.get("transition_distribution_days", 0),
                exit_signals,
            )
            return

        total_value = _finite_number(context.portfolio.total_value)
        available_cash = _usable_cash(
            getattr(context.portfolio, "available_cash", 0.0)
        )
        if not np.isfinite(total_value) or total_value <= 0:
            return

        market_exposure = float(market.get("exposure", 0.0))
        market_allows_entries = market_exposure > 0.0
        current_gross = builtins.max(total_value - available_cash, 0.0)
        risk_budget = builtins.max(
            total_value * market_exposure - current_gross,
            0.0,
        )
        if market_allows_entries:
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
                    or additional > risk_budget
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
                    risk_budget -= additional

        occupied = set(positions.keys())
        available_slots = max(0, MAX_POSITIONS - len(occupied))
        initial_available_slots = available_slots
        already_held = 0
        evaluations = []
        submitted = 0
        order_rejected = 0
        for code in g.watchlist:
            if code in occupied:
                already_held += 1
                continue
            history = histories.get(code)
            try:
                evaluation = _evaluate_entry_candidate(
                    code,
                    history,
                    current_data,
                    total_value,
                    available_cash,
                )
            except Exception as exc:
                if market_allows_entries and available_slots > 0:
                    raise
                evaluation = {
                    "code": code,
                    "blocker": "diagnostic_error",
                    "breakout_reasons": [],
                    "history_ready": False,
                    "breakout": False,
                    "buyable": False,
                    "buy_zone": False,
                    "board_lot": False,
                    "cash_ready": False,
                    "pivot": np.nan,
                    "current_price": np.nan,
                    "target_value": np.nan,
                    "diagnostic_error": "%s: %s"
                    % (type(exc).__name__, str(exc)),
                }
            evaluations.append(evaluation)
            if evaluation["blocker"] != "ready":
                continue
            if not market_allows_entries:
                evaluation["outcome"] = "market_blocked"
                continue
            if available_slots <= 0:
                evaluation["outcome"] = "slot_blocked"
                continue
            current_price = evaluation["current_price"]
            pivot = evaluation["pivot"]
            target_value = evaluation["target_value"]
            if target_value > risk_budget:
                evaluation["outcome"] = "risk_budget"
                continue
            snapshot = current_data[code]
            order = _try_target_value(
                code,
                target_value,
                snapshot,
                increasing=True,
            )
            if not _order_is_accepted(order):
                order_rejected += 1
                evaluation["outcome"] = "order_rejected"
                continue
            submitted += 1
            evaluation["outcome"] = "submitted"
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
            risk_budget -= target_value
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

        _log_entry_funnel(
            observation_date,
            market["state"],
            market_allows_entries,
            len(g.watchlist),
            already_held,
            evaluations,
            initial_available_slots,
            submitted,
            order_rejected,
        )
        if not market_allows_entries:
            _log(
                "info",
                "O'Neil no new risk %s market=%s confirmed=%d/%d exposure=%.2f "
                "distributions=%d correction_reason=%s transition_distributions=%d",
                observation_date,
                market["state"],
                market.get("confirmed_count", 0),
                market.get("total_count", 0),
                market_exposure,
                market["distribution_days"],
                market.get("correction_reason") or "-",
                market.get("transition_distribution_days", 0),
            )
            return
    except Exception as exc:
        _log("error", "O'Neil daily trade aborted: %s", exc)
