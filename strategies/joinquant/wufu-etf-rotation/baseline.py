"""五福 7.5 A6 的聚宽因果日频校准基线。

观察日固定为 context.previous_date，次日 09:35 执行。它用于校准 A0--A6 的
日频目标，不包含原策略的动态中文名称池和 A7 分钟确认。
"""

import builtins
import math

import numpy as np
import pandas as pd
from jqdata import *


GLOBAL_POOL = """518880.XSHG 501018.XSHG 161226.XSHE 159985.XSHE 159980.XSHE
513310.XSHG 159518.XSHE 159509.XSHE 513100.XSHG 513520.XSHG 513500.XSHG
159502.XSHE 513400.XSHG 513030.XSHG 513290.XSHG 520830.XSHG 159529.XSHE""".split()

CHINA_POOL = """513090.XSHG 513120.XSHG 513180.XSHG 513330.XSHG 513750.XSHG
159892.XSHE 513190.XSHG 159605.XSHE 513630.XSHG 159323.XSHE 510900.XSHG
513920.XSHG 513970.XSHG 511380.XSHG 512050.XSHG 510500.XSHG 159915.XSHE
510300.XSHG 512100.XSHG 159949.XSHE 588080.XSHG 159967.XSHE 588220.XSHG
563300.XSHG 510760.XSHG 588200.XSHG 515880.XSHG 159981.XSHE 512880.XSHG
513350.XSHG 159326.XSHE 159516.XSHE 159206.XSHE 512480.XSHG 159363.XSHE
159870.XSHE 512400.XSHG 159755.XSHE 588170.XSHG 159992.XSHE 159995.XSHE
512890.XSHG 515220.XSHG 159566.XSHE 159819.XSHE 512800.XSHG 512690.XSHG
515050.XSHG 562500.XSHG 512170.XSHG 517520.XSHG 159869.XSHE 512070.XSHG
159611.XSHE 562800.XSHG 515120.XSHG 512010.XSHG 510880.XSHG 515790.XSHG
515980.XSHG 512660.XSHG 159928.XSHE 512710.XSHG 560860.XSHG 515030.XSHG
159766.XSHE 159218.XSHE 159852.XSHE 516160.XSHG 516150.XSHG 159227.XSHE
159583.XSHE 588790.XSHG 159865.XSHE 512980.XSHG 159851.XSHE 561360.XSHG
561980.XSHG 562590.XSHG 512200.XSHG 159732.XSHE 159667.XSHE 516510.XSHG
159840.XSHE 159998.XSHE 159825.XSHE 512670.XSHG 159883.XSHE 515210.XSHG
515400.XSHG 159256.XSHE 561330.XSHG 515170.XSHG 159638.XSHE 516520.XSHG
513360.XSHG 516190.XSHG""".split()


def initialize(context):
    set_option("avoid_future_data", True)
    set_option("use_real_price", True)
    set_benchmark("510300.XSHG")
    set_slippage(PriceRelatedSlippage(0.0001), type="fund")
    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=0,
            open_commission=0.0001,
            close_commission=0.0001,
            close_today_commission=0.0001,
            min_commission=5,
        ),
        type="fund",
    )
    g.weak = False
    g.weak_anchor = None
    g.weak_lookback = 25
    g.r2_high_streak = 0
    g.r2_low_streak = 0
    run_daily(rebalance, time="09:35")


def weighted_trend(prices, lookback=25):
    values = np.asarray(prices, dtype=float)
    if len(values) < lookback + 1:
        return None
    values = values[-(lookback + 1) :]
    if np.any(~np.isfinite(values)) or np.any(values <= 0):
        return None
    y = np.log(values)
    x = np.arange(len(y), dtype=float)
    weights = np.linspace(1.0, 2.0, len(y))
    regression_weights = weights ** 2
    x_bar = np.sum(regression_weights * x) / np.sum(regression_weights)
    y_bar = np.sum(regression_weights * y) / np.sum(regression_weights)
    dx = x - x_bar
    variance_x = np.sum(regression_weights * dx ** 2)
    if variance_x <= 0:
        return None
    slope = np.sum(regression_weights * dx * (y - y_bar)) / variance_x
    intercept = y_bar - slope * x_bar
    annualized = math.exp(max(-50.0, min(50.0, slope * 250.0))) - 1.0
    predicted = slope * x + intercept
    ss_res = np.sum(weights * (y - predicted) ** 2)
    ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return annualized, r_squared, annualized * r_squared


def laplace_slope(prices):
    values = np.asarray(prices, dtype=float)
    if len(values) < 2:
        return 0.0
    alpha = 1.0 - math.exp(-0.05)
    level = values[0]
    previous = level
    for value in values[1:]:
        previous = level
        level = alpha * value + (1.0 - alpha) * level
    return float(level - previous)


def update_regime(observation_date):
    indexes = ["000300.XSHG", "399101.XSHE", "399006.XSHE", "000510.XSHG"]
    frame = get_price(
        indexes,
        end_date=observation_date,
        count=10,
        frequency="daily",
        fields=["close"],
        panel=False,
    )
    if frame is None or frame.empty:
        return
    pivot = frame.pivot(index="time", columns="code", values="close")
    below = 0
    above = 0
    for code in indexes:
        if code not in pivot or pivot[code].dropna().shape[0] < 10:
            continue
        values = pivot[code].dropna().values[-10:]
        average = float(np.mean(values))
        below += int(values[-1] < average)
        above += int(values[-1] > average)
    today = pd.Timestamp(observation_date).date()
    if g.weak:
        duration = (today - g.weak_anchor).days if g.weak_anchor is not None else 0
        if duration >= 35 or above >= 3:
            g.weak = False
            g.weak_anchor = None
        elif below >= 3:
            g.weak_anchor = today
    elif below >= 3:
        g.weak = True
        g.weak_anchor = today


def mainline_pass(closes, volumes):
    if len(closes) < 31 or len(volumes) < 31:
        return False
    scores = []
    r2_values = []
    volume_ratios = []
    laplace_values = []
    for offset in range(4, -1, -1):
        end = len(closes) - offset
        metric = weighted_trend(closes[:end], 25)
        if metric is None:
            return False
        scores.append(metric[2])
        r2_values.append(metric[1])
        laplace_values.append(laplace_slope(closes[:end]))
        volume_end = len(volumes) - offset
        if volume_end < 6:
            return False
        base = np.mean(volumes[volume_end - 6 : volume_end - 1])
        volume_ratios.append(volumes[volume_end - 1] / base if base > 0 else np.nan)
    finite = builtins.all(np.isfinite(value) for value in volume_ratios)
    growth = scores[-1] / scores[0] if scores[0] > 0 else float("inf")
    return bool(
        finite
        and 5.0 < scores[-1] <= 20.0
        and r2_values[-1] >= 0.85
        and np.mean(r2_values) >= 0.90
        and np.mean(volume_ratios) >= 1.8
        and builtins.sum(scores[index] >= scores[index - 1] for index in range(1, 5)) >= 4
        and builtins.sum(value > 0 for value in laplace_values) >= 5
        and growth >= 2.0
    )


def rebalance(context):
    observation_date = context.previous_date
    update_regime(observation_date)
    pool = GLOBAL_POOL if g.weak else list(dict.fromkeys(GLOBAL_POOL + CHINA_POOL))
    frame = get_price(
        pool,
        end_date=observation_date,
        count=45,
        frequency="daily",
        fields=["close", "volume", "money"],
        panel=False,
    )
    if frame is None or frame.empty:
        return
    close = frame.pivot(index="time", columns="code", values="close")
    volume = frame.pivot(index="time", columns="code", values="volume")
    current_holdings = [code for code, position in context.portfolio.positions.items() if position.total_amount > 0]
    ranked = []
    retained = []
    for code in pool:
        if code not in close or code not in volume:
            continue
        closes = close[code].dropna().values
        volumes = volume[code].dropna().values
        lookback = g.weak_lookback if g.weak else 25
        metric = weighted_trend(closes, lookback)
        if metric is None:
            continue
        annualized, r_squared, score = metric
        loss_ok = len(closes) >= 4 and np.min(closes[-3:] / closes[-4:-1]) >= 0.97
        ma_ok = len(closes) >= 10 and closes[-1] > np.mean(closes[-10:])
        ordinary = annualized > 0 and r_squared > 0.4
        if not g.weak:
            volume_ratio = volumes[-1] / np.mean(volumes[-6:-1]) if len(volumes) >= 6 else np.nan
            ordinary = ordinary and 0 <= score <= 5 and ma_ok and loss_ok and np.isfinite(volume_ratio) and volume_ratio < 1.8
        special = mainline_pass(closes, volumes) and loss_ok and (ma_ok if g.weak else True)
        hold_extension = (
            code in current_holdings
            and score > 20
            and r_squared >= 0.85
            and laplace_slope(closes) > 0
            and loss_ok
            and (ma_ok if g.weak else True)
        )
        if ordinary or special or hold_extension:
            ranked.append((code, score))
            if hold_extension:
                retained.append(code)
    ranked.sort(key=lambda item: (-item[1], item[0]))
    target = None
    if ranked:
        champion_score = ranked[0][1]
        threshold = champion_score * (1.0 if g.weak else 0.9)
        eligible_holdings = [code for code in current_holdings if code in dict(ranked) and dict(ranked)[code] >= threshold]
        target = eligible_holdings[0] if eligible_holdings else ranked[0][0]
    if target is None:
        target = "511880.XSHG"
    for code in list(context.portfolio.positions.keys()):
        if code != target:
            order_target_value(code, 0)
    if target not in context.portfolio.positions:
        order_target_value(target, context.portfolio.available_cash)
