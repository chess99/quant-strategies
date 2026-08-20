"""五福可交易化 v3 主模型的聚宽固定池迁移工作包。

本文件严格实现 Top3、直接弱市换池、Top5 老持仓名次缓冲和五交易日调仓。
本地归档使用 original_like 历史生命周期代理池；聚宽迁移脚本暂以冻结固定池替代，
因此在完整平台组合仿真前不应把两者视为逐日目标完全相同。
"""

import math
from datetime import date

import numpy as np
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

INDEXES = ["000300.XSHG", "399101.XSHE", "399006.XSHE", "000510.XSHG"]
CASH_ETF = "511880.XSHG"
TOP_K = 3
RANK_BUFFER_EXTRA = 2
REBALANCE_INTERVAL = 5
SCHEDULE_ANCHOR = date(2015, 1, 1)


def initialize(context):
    set_option("avoid_future_data", True)
    set_option("use_real_price", True)
    set_benchmark("510300.XSHG")
    set_slippage(PriceRelatedSlippage(0.0005), type="fund")
    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=0,
            open_commission=0.0005,
            close_commission=0.0005,
            close_today_commission=0.0005,
            min_commission=0,
        ),
        type="fund",
    )
    run_daily(rebalance, time="09:35")


def is_scheduled(context):
    today = context.current_dt.date()
    if today < SCHEDULE_ANCHOR:
        return False
    trade_days = get_trade_days(start_date=SCHEDULE_ANCHOR, end_date=today)
    return len(trade_days) > 0 and (len(trade_days) - 1) % REBALANCE_INTERVAL == 0


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


def regime_flags(observation_date):
    frame = get_price(
        INDEXES,
        end_date=observation_date,
        count=11,
        frequency="daily",
        fields=["close"],
        panel=False,
    )
    if frame is None or frame.empty:
        return False, False
    pivot = frame.pivot(index="time", columns="code", values="close")
    below = 0
    sideways = 0
    for code in INDEXES:
        if code not in pivot:
            continue
        values = pivot[code].dropna().values
        if len(values) < 10:
            continue
        below += int(values[-1] < np.mean(values[-10:]))
        if len(values) >= 11:
            sideways += int(abs(values[-1] / values[-11] - 1.0) < 0.01)
    return below >= 3, sideways >= 3


def select_targets(context, observation_date, weak, choppy):
    available = set(get_all_securities(types=["fund"], date=observation_date).index)
    pool = GLOBAL_POOL if weak else list(dict.fromkeys(GLOBAL_POOL + CHINA_POOL))
    pool = [code for code in pool if code in available]
    frame = get_price(
        pool,
        end_date=observation_date,
        count=35,
        frequency="daily",
        fields=["close", "volume"],
        panel=False,
    )
    if frame is None or frame.empty:
        return [CASH_ETF]
    close = frame.pivot(index="time", columns="code", values="close")
    volume = frame.pivot(index="time", columns="code", values="volume")
    ranked = []
    for code in pool:
        if code not in close or code not in volume:
            continue
        closes = close[code].dropna().values
        volumes = volume[code].dropna().values
        metric = weighted_trend(closes, 25)
        if metric is None or len(closes) < 11 or len(volumes) < 6:
            continue
        annualized, _, score = metric
        ma_ok = closes[-1] > np.mean(closes[-10:])
        loss_ok = np.min(closes[-3:] / closes[-4:-1]) >= 0.97
        prior_volume = np.mean(volumes[-6:-1])
        volume_ratio = volumes[-1] / prior_volume if prior_volume > 0 else np.nan
        divergence_ok = True
        if choppy and len(volumes) >= 6:
            price_change = closes[-1] / closes[-6] - 1.0
            old_volume = np.mean(volumes[-6:-3])
            recent_volume = np.mean(volumes[-3:])
            volume_change = recent_volume / old_volume - 1.0 if old_volume > 0 else np.nan
            divergence_ok = not (
                price_change > 0.02
                and np.isfinite(volume_change)
                and volume_change < -0.10
            )
        passed = bool(
            annualized > 0.0
            and np.isfinite(score)
            and 0.0 <= score <= 5.0
            and ma_ok
            and loss_ok
            and np.isfinite(volume_ratio)
            and volume_ratio < 1.8
            and divergence_ok
        )
        if passed:
            ranked.append((code, annualized))
    ranked.sort(key=lambda item: (-item[1], item[0]))
    if not ranked:
        return [CASH_ETF]
    rank_map = {code: index for index, (code, _) in enumerate(ranked)}
    eligible = set(code for code, _ in ranked[: TOP_K + RANK_BUFFER_EXTRA])
    current = [
        code
        for code, position in context.portfolio.positions.items()
        if position.total_amount > 0 and code != CASH_ETF and code in eligible
    ]
    current.sort(key=lambda code: rank_map[code])
    targets = current[:TOP_K]
    for code, _ in ranked:
        if len(targets) >= TOP_K:
            break
        if code not in targets:
            targets.append(code)
    return sorted(targets, key=lambda code: rank_map[code])


def rebalance(context):
    if not is_scheduled(context):
        return
    observation_date = context.previous_date
    weak, choppy = regime_flags(observation_date)
    targets = select_targets(context, observation_date, weak, choppy)
    current_data = get_current_data()
    target_set = set(targets)
    for code in list(context.portfolio.positions.keys()):
        if code in target_set:
            continue
        snapshot = current_data[code]
        if snapshot.paused or snapshot.last_price <= snapshot.low_limit:
            continue
        order_target_value(code, 0)
    target_value = context.portfolio.total_value / len(targets)
    for code in targets:
        snapshot = current_data[code]
        if snapshot.paused or snapshot.is_st:
            continue
        current_value = (
            context.portfolio.positions[code].value
            if code in context.portfolio.positions
            else 0.0
        )
        if target_value > current_value and snapshot.last_price >= snapshot.high_limit:
            continue
        if target_value < current_value and snapshot.last_price <= snapshot.low_limit:
            continue
        target_shares = int(target_value / snapshot.last_price) // 100 * 100
        order_target(code, target_shares)


def after_code_changed(context):
    return None
