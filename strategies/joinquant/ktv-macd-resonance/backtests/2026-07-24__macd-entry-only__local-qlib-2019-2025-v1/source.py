# ruff: noqa: F403, F405
"""KTV + MACD 共振透明代理版（聚宽日线策略）。

KTV 原始公式没有可信公开源码，本文件不复刻或冒充所谓“口罩股哥原版”：
V = 14 日 Stochastic RSI，K = V 的 3 日 EMA，T = K 的 3 日 EMA。
全部信号使用前一交易日收盘数据，在下一交易日开盘后执行。
"""

import builtins
from datetime import date

import numpy as np
import pandas as pd

try:
    from jqdata import *  # noqa: F403
except ImportError:
    pass


BENCHMARK = "000300.XSHG"
UNIVERSE_INDEXES = ("000300.XSHG", "000905.XSHG")
MAX_POSITIONS = 10
TARGET_GROSS_EXPOSURE = 0.95
MIN_LISTING_DAYS = 250
MIN_AVERAGE_MONEY = 5.0e7
HISTORY_COUNT = 160
MIN_SIGNAL_ROWS = 125
PRICE_BATCH_SIZE = 200
BOARD_LOT = 100
HARD_STOP_LOSS = 0.08

RSI_PERIOD = 14
STOCH_PERIOD = 14
K_SMOOTH = 3
T_SMOOTH = 3
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9


def initialize(context):
    """设置成本、反未来数据选项和日线执行计划。"""
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

    g.half_reduced = set()
    run_daily(
        manage_positions,
        time="09:31",
        reference_security=BENCHMARK,
    )
    run_weekly(
        scan_entries,
        weekday=1,
        time="09:35",
        reference_security=BENCHMARK,
    )


def _finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return np.nan
    return number if np.isfinite(number) else np.nan


def get_current_snapshot(current_data, code):
    """用下标触发聚宽 current_data 惰性映射加载。"""
    try:
        return current_data[code]
    except (KeyError, TypeError):
        return None


def calculate_rsi(close, period=RSI_PERIOD):
    """计算 Wilder RSI；无涨跌的窗口按中性值 50 处理。"""
    values = pd.to_numeric(pd.Series(close), errors="coerce")
    change = values.diff()
    gain = change.clip(lower=0.0)
    loss = -change.clip(upper=0.0)
    average_gain = gain.ewm(
        alpha=1.0 / period,
        adjust=False,
        min_periods=period,
    ).mean()
    average_loss = loss.ewm(
        alpha=1.0 / period,
        adjust=False,
        min_periods=period,
    ).mean()
    relative_strength = average_gain / average_loss.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + relative_strength)
    rsi = rsi.mask((average_loss == 0.0) & (average_gain > 0.0), 100.0)
    rsi = rsi.mask((average_loss == 0.0) & (average_gain == 0.0), 50.0)
    return rsi


def calculate_ktv(
    close,
    rsi_period=RSI_PERIOD,
    stoch_period=STOCH_PERIOD,
    k_smooth=K_SMOOTH,
    t_smooth=T_SMOOTH,
):
    """返回透明代理 K/T/V：Stochastic RSI 及两层 EMA 平滑。"""
    rsi = calculate_rsi(close, period=rsi_period)
    rolling_low = rsi.rolling(stoch_period, min_periods=stoch_period).min()
    rolling_high = rsi.rolling(stoch_period, min_periods=stoch_period).max()
    width = rolling_high - rolling_low
    v = 100.0 * (rsi - rolling_low) / width.replace(0.0, np.nan)
    v = v.mask((width == 0.0) & rsi.notna(), 50.0).clip(0.0, 100.0)
    k = v.ewm(span=k_smooth, adjust=False, min_periods=1).mean().clip(0.0, 100.0)
    t = k.ewm(span=t_smooth, adjust=False, min_periods=1).mean().clip(0.0, 100.0)
    return pd.DataFrame({"k": k, "t": t, "v": v}, index=rsi.index)


def calculate_macd(
    close,
    fast=MACD_FAST,
    slow=MACD_SLOW,
    signal=MACD_SIGNAL,
):
    """计算标准 MACD；柱值采用 DIFF - DEA，不额外乘 2。"""
    values = pd.to_numeric(pd.Series(close), errors="coerce")
    fast_ema = values.ewm(span=fast, adjust=False, min_periods=fast).mean()
    slow_ema = values.ewm(span=slow, adjust=False, min_periods=slow).mean()
    diff = fast_ema - slow_ema
    dea = diff.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame(
        {
            "diff": diff,
            "dea": dea,
            "macd_hist": diff - dea,
        },
        index=values.index,
    )


def build_indicator_frame(price_frame):
    """由单只股票的历史行情构建策略判断所需的完整指标表。"""
    frame = price_frame.copy()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["money"] = pd.to_numeric(frame["money"], errors="coerce")
    frame.sort_index(inplace=True)
    frame["ma20"] = frame["close"].rolling(20, min_periods=20).mean()
    frame["ma60"] = frame["close"].rolling(60, min_periods=60).mean()
    frame["ma120"] = frame["close"].rolling(120, min_periods=120).mean()
    return frame.join(calculate_ktv(frame["close"])).join(
        calculate_macd(frame["close"])
    )


def crossed_up_recent(first, second, lookback=3):
    """判断 first 是否在最近 lookback 根已完成 K 线内上穿 second。"""
    left = pd.to_numeric(pd.Series(first), errors="coerce")
    right = pd.to_numeric(pd.Series(second), errors="coerce")
    crosses = (left > right) & (left.shift(1) <= right.shift(1))
    return bool(builtins.any(crosses.tail(lookback).fillna(False)))


def crossed_down_recent(first, second, lookback=3):
    """判断 first 是否在最近 lookback 根已完成 K 线内下穿 second。"""
    left = pd.to_numeric(pd.Series(first), errors="coerce")
    right = pd.to_numeric(pd.Series(second), errors="coerce")
    crosses = (left < right) & (left.shift(1) >= right.shift(1))
    return bool(builtins.any(crosses.tail(lookback).fillna(False)))


def _last_values(frame, column, count):
    if column not in frame:
        return pd.Series(dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").dropna().tail(count)


def _moderate_volume(frame, lower=0.80, upper=1.80):
    money = _last_values(frame, "money", 20)
    if len(money) < 20 or money.mean() <= 0:
        return False
    ratio = money.tail(5).mean() / money.mean()
    return bool(lower <= ratio <= upper and money.mean() >= MIN_AVERAGE_MONEY)


def _not_in_downtrend(frame):
    """排除均线空头和仍快速下行的标的，但容许低位企稳。"""
    if len(frame) < 65:
        return False
    latest = frame.iloc[-1]
    ma20 = _finite_number(latest.get("ma20"))
    ma60 = _finite_number(latest.get("ma60"))
    ma60_five_days_ago = _finite_number(frame["ma60"].iloc[-6])
    if not builtins.all(
        np.isfinite(value) for value in (ma20, ma60, ma60_five_days_ago)
    ):
        return False
    return bool(ma20 >= ma60 * 0.97 and ma60 >= ma60_five_days_ago * 0.98)


def _stage_low_not_falling_knife(frame):
    """把“阶段低位”定义为距 60 日高点至少 15%，且已离开 60 日最低点。"""
    close = _last_values(frame, "close", 60)
    if len(close) < 60:
        return False
    latest = close.iloc[-1]
    return bool(
        latest <= close.max() * 0.85
        and latest >= close.min() * 1.01
    )


def _green_histogram_shrinking(frame):
    hist = _last_values(frame, "macd_hist", 3)
    if len(hist) < 3:
        return False
    return bool(
        builtins.all(hist < 0.0)
        and hist.iloc[-1] > hist.iloc[-2] > hist.iloc[-3]
    )


def _macd_crossed_up_recent(frame):
    return crossed_up_recent(frame["diff"], frame["dea"], lookback=3)


def is_left_entry(frame):
    """低位抄底代理：阶段低位、KTV 金叉、MACD 转强和温和放量同时成立。"""
    if frame is None or len(frame) < MIN_SIGNAL_ROWS:
        return False
    v = _last_values(frame, "v", 5)
    oversold_recently = len(v) == 5 and v.min() <= 20.0
    ktv_cross = crossed_up_recent(frame["k"], frame["t"], lookback=3)
    macd_turning = _green_histogram_shrinking(frame) or _macd_crossed_up_recent(frame)
    return bool(
        oversold_recently
        and ktv_cross
        and macd_turning
        and _not_in_downtrend(frame)
        and _stage_low_not_falling_knife(frame)
        and _moderate_volume(frame)
    )


def _bull_trend(frame):
    if len(frame) < MIN_SIGNAL_ROWS:
        return False
    latest = frame.iloc[-1]
    ma20 = _finite_number(latest.get("ma20"))
    ma60 = _finite_number(latest.get("ma60"))
    ma120 = _finite_number(latest.get("ma120"))
    old_ma60 = _finite_number(frame["ma60"].iloc[-6])
    if not builtins.all(
        np.isfinite(value) for value in (ma20, ma60, ma120, old_ma60)
    ):
        return False
    return bool(ma20 > ma60 > ma120 and ma60 > old_ma60)


def _red_histogram_reexpanding(frame):
    hist = _last_values(frame, "macd_hist", 3)
    if len(hist) < 3:
        return False
    return bool(
        builtins.all(hist > 0.0)
        and hist.iloc[-3] > hist.iloc[-2]
        and hist.iloc[-1] > hist.iloc[-2]
    )


def is_right_entry(frame):
    """趋势中继代理：多头均线、T 线上回升、零轴上 MACD 再扩张。"""
    if frame is None or len(frame) < MIN_SIGNAL_ROWS:
        return False
    latest = frame.iloc[-1]
    diff = _finite_number(latest.get("diff"))
    dea = _finite_number(latest.get("dea"))
    t_value = _finite_number(latest.get("t"))
    ktv_support = (
        np.isfinite(t_value)
        and t_value >= 50.0
        and crossed_up_recent(frame["k"], frame["t"], lookback=3)
    )
    macd_bull = np.isfinite(diff) and np.isfinite(dea) and diff > dea and dea > 0.0
    return bool(
        _bull_trend(frame)
        and ktv_support
        and macd_bull
        and _red_histogram_reexpanding(frame)
        and _moderate_volume(frame)
    )


def entry_signal(frame):
    """返回可解释的买点类型与排序分，右侧中继优先。"""
    if is_right_entry(frame):
        latest = frame.iloc[-1]
        trend_gap = (_finite_number(latest["ma20"]) / _finite_number(latest["ma60"])) - 1.0
        score = 200.0 + min(max(trend_gap, 0.0), 0.20) * 100.0
        return {"kind": "right", "score": score}
    if is_left_entry(frame):
        drawdown = 1.0 - frame["close"].iloc[-1] / frame["close"].tail(60).max()
        score = 100.0 + min(max(drawdown, 0.0), 0.50) * 100.0
        return {"kind": "left", "score": score}
    return None


def _resonance_full_exit(frame):
    if len(frame) < 3:
        return False
    latest = frame.iloc[-1]
    k_below_t = builtins.all(
        frame["k"].tail(2).values < frame["t"].tail(2).values
    )
    return bool(
        k_below_t
        and _finite_number(latest.get("diff")) < _finite_number(latest.get("dea"))
        and _finite_number(latest.get("macd_hist")) < 0.0
    )


def _trend_invalid(frame):
    if len(frame) < MIN_SIGNAL_ROWS:
        return False
    close_below_ma60 = builtins.all(
        frame["close"].tail(2).values < frame["ma60"].tail(2).values
    )
    latest = frame.iloc[-1]
    return bool(
        close_below_ma60
        and _finite_number(latest.get("ma20")) < _finite_number(latest.get("ma60"))
    )


def _take_profit_signal(frame):
    if len(frame) < 6:
        return False
    hist = _last_values(frame, "macd_hist", 3)
    hist_shrinking = (
        len(hist) == 3
        and builtins.all(hist > 0.0)
        and hist.iloc[-1] < hist.iloc[-2] < hist.iloc[-3]
    )
    return bool(
        _last_values(frame, "k", 5).max() >= 80.0
        and crossed_down_recent(frame["k"], frame["t"], lookback=2)
        and hist_shrinking
    )


def exit_decision(frame, avg_cost=None, half_reduced=False):
    """返回 full、half 或 None；硬止损和趋势失效优先于分批止盈。"""
    if frame is None or frame.empty:
        return None
    latest_close = _finite_number(frame["close"].iloc[-1])
    cost = _finite_number(avg_cost)
    hard_stop = (
        np.isfinite(cost)
        and cost > 0.0
        and np.isfinite(latest_close)
        and latest_close <= cost * (1.0 - HARD_STOP_LOSS)
    )
    if hard_stop or _resonance_full_exit(frame) or _trend_invalid(frame):
        return "full"
    if not half_reduced and _take_profit_signal(frame):
        return "half"
    return None


def _normalize_price_frame(raw, single_code=None):
    if raw is None or not isinstance(raw, pd.DataFrame) or raw.empty:
        return pd.DataFrame(columns=["time", "code", "close", "money"])
    frame = raw.copy()
    if isinstance(frame.index, pd.MultiIndex) or frame.index.name is not None:
        frame = frame.reset_index()
    elif "time" not in frame.columns:
        frame = frame.reset_index().rename(columns={"index": "time"})
    if "date" in frame.columns and "time" not in frame.columns:
        frame.rename(columns={"date": "time"}, inplace=True)
    if "code" not in frame.columns:
        if single_code is None:
            return pd.DataFrame(columns=["time", "code", "close", "money"])
        frame["code"] = single_code
    if "money" not in frame.columns:
        frame["money"] = np.nan
    required = ["time", "code", "close", "money"]
    if not builtins.all(column in frame.columns for column in required):
        return pd.DataFrame(columns=required)
    frame = frame[required].copy()
    frame["time"] = pd.to_datetime(frame["time"], errors="coerce")
    frame.dropna(subset=["time", "code"], inplace=True)
    return frame


def _chunks(values, size):
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start : start + size]


def fetch_price_frames(codes, observation_date, count=HISTORY_COUNT):
    """分批取得观察日及以前的行情，返回 code -> 指标表。"""
    normalized = []
    for batch in _chunks(codes, PRICE_BATCH_SIZE):
        try:
            raw = get_price(
                batch,
                end_date=observation_date,
                count=count,
                frequency="daily",
                fields=["close", "money"],
                skip_paused=False,
                fq="pre",
                panel=False,
            )
            normalized.append(
                _normalize_price_frame(
                    raw,
                    single_code=batch[0] if len(batch) == 1 else None,
                )
            )
        except Exception as error:
            log.warn("行情批次读取失败，跳过该批：%s", error)
    if not normalized:
        return {}
    prices = pd.concat(normalized, ignore_index=True)
    result = {}
    for code, group in prices.groupby("code"):
        group = group.sort_values("time").drop_duplicates("time", keep="last")
        group = group.set_index("time")[["close", "money"]]
        if len(group) >= MIN_SIGNAL_ROWS:
            result[str(code)] = build_indicator_frame(group)
    return result


def historical_universe(observation_date):
    """使用观察日的沪深300和中证500成分，避免读取今天的成分股。"""
    codes = set()
    for index_code in UNIVERSE_INDEXES:
        try:
            codes.update(get_index_stocks(index_code, date=observation_date))
        except Exception as error:
            log.warn("%s 历史成分读取失败：%s", index_code, error)
    if not codes:
        return []
    securities = get_all_securities(types=["stock"], date=observation_date)
    eligible = []
    for code in sorted(codes):
        if code.endswith(".XBJ") or code not in securities.index:
            continue
        start_date = securities.loc[code, "start_date"]
        if hasattr(start_date, "date"):
            start_date = start_date.date()
        if not isinstance(start_date, date):
            continue
        if (observation_date - start_date).days < MIN_LISTING_DAYS:
            continue
        eligible.append(code)
    return eligible


def _is_buyable(snapshot):
    if snapshot is None or getattr(snapshot, "paused", False):
        return False
    name = str(getattr(snapshot, "name", ""))
    if getattr(snapshot, "is_st", False) or "ST" in name.upper() or "退" in name:
        return False
    price = _finite_number(getattr(snapshot, "last_price", np.nan))
    high_limit = _finite_number(getattr(snapshot, "high_limit", np.nan))
    return bool(
        np.isfinite(price)
        and price > 0.0
        and np.isfinite(high_limit)
        and price < high_limit - 1.0e-8
    )


def _is_sellable(snapshot):
    if snapshot is None or getattr(snapshot, "paused", False):
        return False
    price = _finite_number(getattr(snapshot, "last_price", np.nan))
    low_limit = _finite_number(getattr(snapshot, "low_limit", np.nan))
    return bool(
        np.isfinite(price)
        and np.isfinite(low_limit)
        and price > low_limit + 1.0e-8
    )


def manage_positions(context):
    """每天用前一交易日收盘信号管理止损、退出和首次减半。"""
    positions = context.portfolio.positions
    if not positions:
        return
    observation_date = context.previous_date
    price_frames = fetch_price_frames(list(positions.keys()), observation_date)
    current_data = get_current_data()
    active_codes = set(positions.keys())
    g.half_reduced.intersection_update(active_codes)

    for code, position in list(positions.items()):
        frame = price_frames.get(code)
        if frame is None:
            log.warn("%s 历史行情不足，今日不执行退出判断", code)
            continue
        decision = exit_decision(
            frame,
            avg_cost=getattr(position, "avg_cost", None),
            half_reduced=code in g.half_reduced,
        )
        if decision is None:
            continue
        snapshot = get_current_snapshot(current_data, code)
        if not _is_sellable(snapshot):
            log.warn("%s 出现 %s 信号但停牌或跌停，暂缓卖出", code, decision)
            continue
        try:
            if decision == "full":
                order_target(code, 0)
                g.half_reduced.discard(code)
                log.info("%s 全额退出：观察日=%s", code, observation_date)
            else:
                current_amount = int(getattr(position, "total_amount", 0))
                target_amount = int((current_amount * 0.5) // BOARD_LOT) * BOARD_LOT
                if target_amount >= BOARD_LOT and target_amount < current_amount:
                    order_target(code, target_amount)
                    g.half_reduced.add(code)
                    log.info("%s 首次减半：观察日=%s", code, observation_date)
        except Exception as error:
            log.error("%s 执行 %s 失败：%s", code, decision, error)


def scan_entries(context):
    """每周扫描透明共振买点，按右侧优先、信号强度排序开新仓。"""
    positions = context.portfolio.positions
    available_slots = MAX_POSITIONS - len(positions)
    if available_slots <= 0:
        return
    observation_date = context.previous_date
    universe = historical_universe(observation_date)
    candidates = [code for code in universe if code not in positions]
    price_frames = fetch_price_frames(candidates, observation_date)

    signals = []
    for code, frame in price_frames.items():
        signal = entry_signal(frame)
        if signal is not None:
            signals.append((code, signal["kind"], signal["score"]))
    signals.sort(key=lambda item: (-item[2], item[0]))
    if not signals:
        log.info("观察日 %s 没有 KTV+MACD 透明代理共振信号", observation_date)
        return

    current_data = get_current_data()
    slot_value = (
        float(context.portfolio.total_value)
        * TARGET_GROSS_EXPOSURE
        / MAX_POSITIONS
    )
    remaining_cash = float(context.portfolio.available_cash)
    bought = []
    for code, kind, score in signals:
        if len(bought) >= available_slots:
            break
        snapshot = get_current_snapshot(current_data, code)
        if not _is_buyable(snapshot):
            continue
        price = _finite_number(getattr(snapshot, "last_price", np.nan))
        budget = min(slot_value, remaining_cash * 0.98)
        amount = int((budget / price) // BOARD_LOT) * BOARD_LOT
        if amount < BOARD_LOT:
            continue
        try:
            order_target(code, amount)
            remaining_cash -= amount * price
            bought.append(code)
            g.half_reduced.discard(code)
            log.info(
                "%s 新开仓 %d 股，类型=%s，分数=%.2f，观察日=%s",
                code,
                amount,
                kind,
                score,
                observation_date,
            )
        except Exception as error:
            log.error("%s 买入失败：%s", code, error)

    log.info(
        "透明代理扫描：观察日=%s，股票池=%d，完整行情=%d，共振=%d，买入=%s",
        observation_date,
        len(universe),
        len(price_frames),
        len(signals),
        bought,
    )
