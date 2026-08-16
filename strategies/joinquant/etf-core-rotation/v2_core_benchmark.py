# -*- coding: utf-8 -*-
# ruff: noqa: F403, F405
"""Official JoinQuant 40/40/20 strategic-core benchmark for paired V2 calibration."""

import pandas as pd

from jqdata import *


def initialize(context):
    set_option('avoid_future_data', True)
    set_option('use_real_price', True)
    set_slippage(PriceRelatedSlippage(0.002), type='fund')
    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=0,
            open_commission=0.0003,
            close_commission=0.0003,
            close_today_commission=0,
            min_commission=5,
        ),
        type='fund',
    )
    set_benchmark('000300.XSHG')
    log.set_level('order', 'error')
    log.set_level('system', 'error')
    g.core_weights = {
        '510300.XSHG': 0.40,
        '511010.XSHG': 0.40,
        '518880.XSHG': 0.20,
    }
    g.min_weight_change = 0.03
    g.min_trade_value = 2000
    run_weekly(rebalance, weekday=1, time='10:30', reference_security='510300.XSHG')


def rebalance(context):
    current_data = get_current_data()
    total_value = float(context.portfolio.total_value)
    if total_value <= 0:
        return
    for code, weight in g.core_weights.items():
        try:
            snapshot = current_data[code]
        except Exception:
            continue
        if snapshot.paused:
            continue
        price = snapshot.last_price
        if price is None or pd.isna(price) or price <= 0 or price >= snapshot.high_limit:
            continue
        position = context.portfolio.positions.get(code, None)
        current_value = 0.0 if position is None else float(position.value)
        current_weight = current_value / total_value
        if position is not None and position.total_amount > 0:
            if abs(weight - current_weight) < g.min_weight_change:
                continue
        target_value = weight * total_value
        if abs(target_value - current_value) < g.min_trade_value:
            continue
        order_target_value(code, target_value)
