# -*- coding: utf-8 -*-
# ruff: noqa: F403, F405
"""ETF Core Rotation v2 — 40/40/20 战略底仓上的条件式动量增强。"""

import builtins
import numpy as np
import pandas as pd
from datetime import timedelta

from jqdata import *
from jqdata import finance


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
    log.set_level('strategy', 'info')

    g.core_weights = {
        '510300.XSHG': 0.40,
        '511010.XSHG': 0.40,
        '518880.XSHG': 0.20,
    }
    g.active_sleeve = 0.30
    g.active_single_symbol_cap = 0.15
    g.lookbacks = (63, 126, 252)
    g.minimum_excess_horizons = 2
    g.minimum_dispersion_iqr = 0.10
    g.top_k = 3
    g.rank_buffer = 2
    g.corr_lookback = 60
    g.max_pair_corr = 0.90
    g.min_history_bars = 253
    g.min_listing_calendar_days = 300
    g.liquidity_lookback = 20
    g.min_adv20 = 20_000_000
    g.min_liquidity_observations = 15
    g.max_adv_participation = 0.005
    g.min_trade_value = 2000
    g.min_weight_change = 0.03
    g.gold_etf = '518880.XSHG'
    g.hurdle_bond = '511010.XSHG'
    g.cash_etf = '511880.XSHG'
    g.defensive_bond_etfs = ['511010.XSHG', '511260.XSHG']
    g.exclude_keywords = [
        '货币', '现金', '短融', '国债', '政金债', '信用债', '债券', '转债',
        '同业存单', '城投债', '地方债', '公司债',
        '黄金', '白银', '原油', '豆粕', '商品',
        '纳指', '纳斯达克', '标普', '道琼斯', '日经', '德国', '法国', '沙特',
        '恒生', '港股', '香港', '中概', 'H股', '海外', '中韩',
        'REIT', 'Reit', 'reit',
    ]
    g.last_rebalance_date = None
    g.last_selected = []
    g.last_universe = []
    g.last_adv20 = {}
    run_weekly(rebalance, weekday=1, time='10:30', reference_security='510300.XSHG')
    log.info('ETF Core Rotation v2 初始化完成')


def rebalance(context):
    as_of = context.previous_date
    if g.last_rebalance_date == as_of:
        return
    g.last_rebalance_date = as_of
    universe, adv20 = build_risk_universe(as_of)
    g.last_universe = universe
    g.last_adv20 = adv20
    ranked = pd.DataFrame()
    selected = []
    diagnostics = {
        'dispersion_iqr': np.nan,
        'dispersion_gate_open': False,
        'excess_pass_count': 0,
    }
    if universe:
        metrics, close_matrix = compute_risk_metrics(universe, as_of)
        if metrics is not None and not metrics.empty:
            ranked = rank_candidates(metrics)
            ranked, diagnostics = add_conditional_gates(ranked, as_of)
            if diagnostics['dispersion_gate_open']:
                passed = ranked[ranked['excess_pass']].copy()
                selected = select_assets_with_buffer(passed, close_matrix)
    active_weights = build_active_weights(selected, ranked, context, adv20)
    target_weights = compose_core_and_active(active_weights)
    g.last_selected = list(selected)
    log.info(
        'V2 signal=%s | universe=%d | excess_pass=%d | dispersion=%.4f | active=%.1f%%'
        % (
            as_of,
            len(universe),
            diagnostics['excess_pass_count'],
            diagnostics['dispersion_iqr']
            if np.isfinite(diagnostics['dispersion_iqr']) else -1.0,
            100 * builtins.sum(active_weights.values()),
        )
    )
    log_selection(ranked, selected, target_weights, adv20)
    execute_target_weights(context, target_weights)


def build_risk_universe(as_of):
    try:
        sec_df = get_all_securities(['etf'], date=as_of)
    except Exception as error:
        log.error('get_all_securities 失败: %s' % error)
        return [], {}
    if sec_df is None or sec_df.empty:
        return [], {}
    min_start = as_of - timedelta(days=g.min_listing_calendar_days)
    excluded = set(g.defensive_bond_etfs + [g.cash_etf])
    raw_codes = []
    for code, row in sec_df.iterrows():
        try:
            start_date = row['start_date']
            if start_date is None or start_date > min_start or code in excluded:
                continue
            raw_codes.append(code)
        except Exception:
            continue
    tracking = get_point_in_time_tracking_map(raw_codes, as_of)
    if not tracking:
        return [], {}
    prelim = []
    meta = {}
    for code in raw_codes:
        info = tracking.get(code)
        if not info:
            continue
        traced_code = info.get('traced_index_code')
        traced_name = info.get('traced_index_name') or ''
        if not traced_code or pd.isna(traced_code):
            continue
        display_name = ''
        try:
            display_name = str(sec_df.loc[code, 'display_name'])
        except Exception:
            pass
        if builtins.any(
            keyword in ('%s %s' % (display_name, traced_name))
            for keyword in g.exclude_keywords
        ):
            continue
        prelim.append(code)
        meta[code] = {'traced_index_code': str(traced_code)}
    if g.gold_etf in sec_df.index:
        try:
            if sec_df.loc[g.gold_etf, 'start_date'] <= min_start:
                prelim.append(g.gold_etf)
                meta[g.gold_etf] = {'traced_index_code': 'SPECIAL_GOLD'}
        except Exception:
            pass
    prelim = sorted(set(prelim))
    if not prelim:
        return [], {}
    adv20, counts = get_adv(prelim, as_of, g.liquidity_lookback)
    liquid = [
        code
        for code in prelim
        if counts.get(code, 0) >= g.min_liquidity_observations
        and adv20.get(code, 0) >= g.min_adv20
    ]
    best_by_index = {}
    for code in liquid:
        key = meta[code]['traced_index_code']
        old = best_by_index.get(key)
        if old is None or adv20.get(code, 0) > adv20.get(old, 0):
            best_by_index[key] = code
    final_codes = sorted(set(best_by_index.values()))
    return final_codes, {code: adv20[code] for code in final_codes if code in adv20}


def get_point_in_time_tracking_map(codes, as_of):
    rows = []
    for offset in range(0, len(codes), 300):
        batch = codes[offset:offset + 300]
        try:
            query_object = query(
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
            frame = finance.run_query(query_object)
            if frame is not None and not frame.empty:
                rows.append(frame)
        except Exception as error:
            log.warning('FUND_INVEST_TARGET 查询失败 batch=%d: %s' % (offset, error))
    if not rows:
        return {}
    frame = pd.concat(rows, ignore_index=True)
    for column in ('start_date', 'pub_date', 'end_date'):
        frame[column] = pd.to_datetime(frame[column], errors='coerce')
    as_of_timestamp = pd.Timestamp(as_of)
    frame = frame[(frame['end_date'].isna()) | (frame['end_date'] >= as_of_timestamp)]
    frame = frame.sort_values(['code', 'start_date', 'pub_date'])
    frame = frame.groupby('code', as_index=False).tail(1)
    out = {}
    for _, row in frame.iterrows():
        out[row['code']] = {
            'traced_index_code': row['traced_index_code'],
            'traced_index_name': row['traced_index_name'],
        }
    return out


def get_adv(codes, as_of, lookback):
    adv = {}
    counts = {}
    for offset in range(0, len(codes), 200):
        batch = codes[offset:offset + 200]
        try:
            frame = get_price(
                batch,
                end_date=as_of,
                count=lookback,
                frequency='daily',
                fields=['money'],
                panel=False,
                skip_paused=True,
                fq='pre',
            )
            if frame is None or frame.empty:
                continue
            if 'code' not in frame.columns:
                if len(batch) != 1:
                    continue
                frame = frame.copy()
                frame['code'] = batch[0]
            grouped = frame.groupby('code')['money']
            for code, value in grouped.mean().items():
                if pd.notna(value):
                    adv[code] = float(value)
            for code, value in grouped.count().items():
                counts[code] = int(value)
        except Exception as error:
            log.warning('ADV 获取失败 batch=%d: %s' % (offset, error))
    return adv, counts


def compute_risk_metrics(codes, as_of):
    count = max(g.lookbacks) + 5
    close_matrix = get_close_matrix(codes, as_of, count)
    if close_matrix is None or close_matrix.empty:
        return pd.DataFrame(), close_matrix
    rows = []
    for code in codes:
        if code not in close_matrix.columns:
            continue
        history = close_matrix[code].dropna()
        if len(history) < g.min_history_bars:
            continue
        prices = history.values.astype(float)
        returns = {}
        valid = True
        for lookback in g.lookbacks:
            if len(prices) <= lookback or prices[-lookback - 1] <= 0:
                valid = False
                break
            returns[lookback] = float(prices[-1] / prices[-lookback - 1] - 1.0)
        if not valid:
            continue
        rows.append(
            {
                'code': code,
                'r63': returns[63],
                'r126': returns[126],
                'r252': returns[252],
            }
        )
    if not rows:
        return pd.DataFrame(), close_matrix
    return pd.DataFrame(rows).set_index('code'), close_matrix


def get_close_matrix(codes, as_of, count):
    pieces = []
    for offset in range(0, len(codes), 200):
        batch = codes[offset:offset + 200]
        try:
            frame = get_price(
                batch,
                end_date=as_of,
                count=count,
                frequency='daily',
                fields=['close'],
                panel=False,
                skip_paused=True,
                fq='pre',
            )
            if frame is None or frame.empty:
                continue
            if 'code' not in frame.columns:
                if len(batch) != 1:
                    continue
                frame = frame.copy()
                frame['code'] = batch[0]
            pieces.append(frame[['time', 'code', 'close']])
        except Exception as error:
            log.warning('价格矩阵获取失败 batch=%d: %s' % (offset, error))
    if not pieces:
        return pd.DataFrame()
    frame = pd.concat(pieces, ignore_index=True)
    return frame.pivot_table(
        index='time', columns='code', values='close', aggfunc='last'
    ).sort_index()


def rank_candidates(metrics):
    frame = metrics.copy()
    frame['p63'] = frame['r63'].rank(pct=True, method='average')
    frame['p126'] = frame['r126'].rank(pct=True, method='average')
    frame['p252'] = frame['r252'].rank(pct=True, method='average')
    frame['score'] = (frame['p63'] + frame['p126'] + frame['p252']) / 3.0
    frame = frame.sort_values(['score', 'r126'], ascending=False)
    frame['rank'] = np.arange(1, len(frame) + 1)
    return frame


def defensive_hurdles(as_of):
    matrix = get_close_matrix([g.hurdle_bond, g.cash_etf], as_of, max(g.lookbacks) + 5)
    hurdles = {}
    for lookback in g.lookbacks:
        values = [0.0]
        for code in (g.hurdle_bond, g.cash_etf):
            if code not in matrix.columns:
                continue
            history = matrix[code].dropna()
            if len(history) <= lookback:
                continue
            value = float(history.iloc[-1] / history.iloc[-lookback - 1] - 1.0)
            if np.isfinite(value):
                values.append(value)
        hurdles[lookback] = max(values)
    return hurdles


def add_conditional_gates(ranked, as_of):
    frame = ranked.copy()
    hurdles = defensive_hurdles(as_of)
    flags = []
    for lookback in g.lookbacks:
        column = 'excess_%d' % lookback
        frame[column] = frame['r%d' % lookback] > hurdles.get(lookback, 0.0)
        flags.append(column)
    frame['excess_count'] = frame[flags].sum(axis=1)
    frame['excess_pass'] = frame['excess_count'] >= g.minimum_excess_horizons
    values = frame['r126'].dropna()
    dispersion = (
        float(values.quantile(0.75) - values.quantile(0.25))
        if len(values) >= 4 else np.nan
    )
    open_gate = np.isfinite(dispersion) and dispersion >= g.minimum_dispersion_iqr
    return frame, {
        'dispersion_iqr': dispersion,
        'dispersion_gate_open': bool(open_gate),
        'excess_pass_count': int(frame['excess_pass'].sum()),
    }


def select_assets_with_buffer(passed, close_matrix):
    if passed is None or passed.empty:
        return []
    rank_map = passed['rank'].to_dict()
    keep = [
        code
        for code in g.last_selected
        if code in rank_map and rank_map[code] <= g.top_k + g.rank_buffer
    ]
    keep.sort(key=lambda code: rank_map[code])
    selected = []
    for code in keep:
        if len(selected) >= g.top_k:
            break
        if correlation_ok(code, selected, close_matrix):
            selected.append(code)
    for code in passed.index:
        if len(selected) >= g.top_k:
            break
        if code not in selected and correlation_ok(code, selected, close_matrix):
            selected.append(code)
    return selected


def correlation_ok(candidate, selected, close_matrix):
    if not selected:
        return True
    if candidate not in close_matrix.columns:
        return False
    for old in selected:
        if old not in close_matrix.columns:
            continue
        pair = close_matrix[[candidate, old]].pct_change().dropna().tail(g.corr_lookback)
        if len(pair) < 40:
            continue
        correlation = pair.corr().iloc[0, 1]
        if pd.notna(correlation) and correlation > g.max_pair_corr:
            return False
    return True


def build_active_weights(selected, ranked, context, adv20):
    if not selected:
        return {}
    equal = min(g.active_sleeve / len(selected), g.active_single_symbol_cap)
    portfolio_value = float(context.portfolio.total_value)
    weights = {}
    for code in selected:
        weight = equal
        if portfolio_value > 0:
            adv = float(adv20.get(code, 0.0))
            weight = min(weight, adv * g.max_adv_participation / portfolio_value)
        if weight > 1e-6:
            weights[code] = weight
    return weights


def compose_core_and_active(active_weights):
    allocated = min(1.0, builtins.sum(active_weights.values()))
    target = {
        code: weight * (1.0 - allocated)
        for code, weight in g.core_weights.items()
    }
    for code, weight in active_weights.items():
        target[code] = target.get(code, 0.0) + weight
    total = builtins.sum(target.values())
    if total > 0 and abs(total - 1.0) < 1e-8:
        target = {code: weight / total for code, weight in target.items()}
    return target


def execute_target_weights(context, target_weights):
    current_data = get_current_data()
    total_value = float(context.portfolio.total_value)
    if total_value <= 0:
        return
    target_weights = {
        code: max(0.0, float(weight))
        for code, weight in target_weights.items()
        if weight > 1e-6
    }
    target_codes = set(target_weights)
    for code, position in list(context.portfolio.positions.items()):
        if position.total_amount > 0 and code not in target_codes:
            if can_trade(code, current_data, is_buy=False):
                order_target_value(code, 0)
    for code, weight in target_weights.items():
        try:
            current_data[code]
        except Exception:
            continue
        position = context.portfolio.positions.get(code, None)
        current_value = 0.0 if position is None else float(position.value)
        current_weight = current_value / total_value
        gap = weight - current_weight
        if position is not None and position.total_amount > 0 and abs(gap) < g.min_weight_change:
            continue
        target_value = weight * total_value
        if abs(target_value - current_value) < g.min_trade_value:
            continue
        if can_trade(code, current_data, is_buy=(gap > 0)):
            order_target_value(code, target_value)


def can_trade(code, current_data, is_buy):
    try:
        snapshot = current_data[code]
        if snapshot.paused:
            return False
        price = snapshot.last_price
        if price is None or pd.isna(price) or price <= 0:
            return False
        if is_buy and price >= snapshot.high_limit:
            return False
        if (not is_buy) and price <= snapshot.low_limit:
            return False
        return True
    except Exception:
        return False


def log_selection(ranked, selected, target_weights, adv20):
    log.info('V2 主动资产: %s' % selected)
    for code in selected:
        if code not in ranked.index:
            continue
        row = ranked.loc[code]
        log.info(
            '%s | rank=%d score=%.3f | 3m=%+.2f%% 6m=%+.2f%% 12m=%+.2f%% '
            '| excess=%d | ADV20=%.2f亿'
            % (
                code,
                int(row['rank']),
                row['score'],
                100 * row['r63'],
                100 * row['r126'],
                100 * row['r252'],
                int(row['excess_count']),
                adv20.get(code, 0) / 1e8,
            )
        )
    pretty = ', '.join(
        '%s=%.1f%%' % (code, 100 * weight)
        for code, weight in sorted(target_weights.items())
    )
    log.info('V2 目标权重: %s' % pretty)
