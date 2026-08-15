# -*- coding: utf-8 -*-
# ruff: noqa: F403, F405
"""
ETF Core Rotation v1 — JoinQuant / 聚宽

设计目标：
1) 时点化 ETF 池，避免未来上市标的泄漏；
2) 多周期动量集成，不依赖单一最佳参数；
3) 横截面排名 + 时间序列绝对动量门控；
4) Top-K 分散 + 近重复资产相关性约束；
5) 逆波动率权重 + 组合波动率目标；
6) 排名缓冲降低换手；
7) 流动性与容量约束；
8) 风险资产不足时自动转入国债 ETF / 货币 ETF；
9) 不使用盘中预测、不使用人工牛熊市规则、不使用固定止损。

说明：
- v1 主风险池只纳入境内股票指数 ETF，并额外加入黄金 ETF 518880。
- 主动排除跨境/QDII/LOF，以避免溢价、时区和申购额度等额外风险。
- ETF 分类通过“跟踪指数 + 关键词排除”完成；实盘前请检查日志中的实际池。
"""

import builtins
import math
import numpy as np
import pandas as pd
from datetime import timedelta

from jqdata import *
from jqdata import finance


# ============================================================
# 初始化
# ============================================================
def initialize(context):
    set_option('avoid_future_data', True)
    set_option('use_real_price', True)

    # PriceRelatedSlippage 的参数是双边价差；0.002 => 单边约 10bp。
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

    # ---------- 核心研究参数：故意保持少而粗 ----------
    g.lookbacks = (63, 126, 252)       # 约 3/6/12 个月
    g.min_positive_horizons = 2        # 至少 2/3 周期自身收益为正
    g.top_k = 3                         # 最多 3 个风险资产
    g.rank_buffer = 2                   # 原持仓排名 <= top_k+2 可继续保留
    g.corr_lookback = 60
    g.max_pair_corr = 0.90              # 只排除近重复暴露

    g.vol_lookback = 60
    g.target_portfolio_vol = 0.18       # 年化波动目标；不加杠杆
    g.max_single_risk_weight = 0.40     # 单风险资产上限
    g.vol_floor = 0.08                  # 避免低波资产得到异常高权重

    # ---------- 可交易性 ----------
    g.min_history_bars = 253
    g.min_listing_calendar_days = 300
    g.liquidity_lookback = 20
    g.min_adv20 = 20_000_000            # 2000 万元/日
    g.min_liquidity_observations = 15
    g.max_adv_participation = 0.005      # 目标市值不超过 ADV20 的 0.5%
    g.min_trade_value = 2000
    g.min_weight_change = 0.03           # 小于 3pct 的权重漂移不主动交易

    # ---------- 特殊资产 ----------
    g.gold_etf = '518880.XSHG'
    g.defensive_bond_etfs = ['511010.XSHG', '511260.XSHG']
    g.cash_etf = '511880.XSHG'

    # v1 主池只做境内股票 ETF；以下类别从动态 ETF 池排除。
    g.exclude_keywords = [
        # 固收 / 现金
        '货币', '现金', '短融', '国债', '政金债', '信用债', '债券', '转债',
        '同业存单', '城投债', '地方债', '公司债',
        # 商品（黄金单独作为特例加入）
        '黄金', '白银', '原油', '豆粕', '商品',
        # 跨境 / QDII：v1 暂不纳入
        '纳指', '纳斯达克', '标普', '道琼斯', '日经', '德国', '法国', '沙特',
        '恒生', '港股', '香港', '中概', 'H股', '海外', '中韩',
        # 其他不希望混入风险池的类型
        'REIT', 'Reit', 'reit',
    ]

    # 缓存，仅用于减少同一调仓日重复请求。
    g.last_rebalance_date = None
    g.last_universe = []
    g.last_adv20 = {}
    g.last_metrics = None

    # 周频足以匹配 3/6/12 月信号，同时显著降低换手。
    run_weekly(rebalance, weekday=1, time='10:30', reference_security='510300.XSHG')

    log.info('ETF Core Rotation v1 初始化完成')


# ============================================================
# 主流程
# ============================================================
def rebalance(context):
    as_of = context.previous_date
    if g.last_rebalance_date == as_of:
        return
    g.last_rebalance_date = as_of

    log.info('=' * 80)
    log.info('ETF Core Rotation | rebalance=%s | signal_asof=%s' % (
        context.current_dt.strftime('%Y-%m-%d %H:%M'), as_of))

    # 1) 时点化风险池
    universe, adv20 = build_risk_universe(as_of)
    g.last_universe = universe
    g.last_adv20 = adv20

    if not universe:
        log.warning('风险池为空，全部转入防御资产')
        target_weights = build_defensive_only_weights(as_of)
        execute_target_weights(context, target_weights)
        return

    # 2) 计算多周期动量、绝对动量门控、波动率
    metrics, close_matrix = compute_risk_metrics(universe, as_of)
    g.last_metrics = metrics

    if metrics is None or metrics.empty:
        log.warning('没有 ETF 获得足够历史数据，全部转入防御资产')
        target_weights = build_defensive_only_weights(as_of)
        execute_target_weights(context, target_weights)
        return

    # 3) 横截面多周期排名
    ranked = rank_candidates(metrics)
    passed = ranked[ranked['abs_pass']].copy()

    log.info('风险池=%d | 数据有效=%d | 绝对动量通过=%d' % (
        len(universe), len(ranked), len(passed)))

    # 4) 排名缓冲 + 相关性去重，选 Top-K
    selected = select_assets_with_buffer(context, passed, close_matrix)

    # 5) 逆波动率 + 单资产上限 + 组合波动率目标 + 容量上限
    risk_weights = build_risk_weights(selected, ranked, close_matrix, context, adv20)

    # 6) 剩余仓位进入防御资产
    target_weights = add_defensive_sleeve(risk_weights, as_of)

    # 7) 执行
    log_selection(ranked, selected, target_weights, adv20)
    execute_target_weights(context, target_weights)


# ============================================================
# Universe：时点化、流动性、跟踪指数去重
# ============================================================
def build_risk_universe(as_of):
    try:
        sec_df = get_all_securities(['etf'], date=as_of)
    except Exception as e:
        log.error('get_all_securities 失败: %s' % e)
        return [], {}

    if sec_df is None or sec_df.empty:
        return [], {}

    # 上市时间 + 特殊防御资产排除
    min_start = as_of - timedelta(days=g.min_listing_calendar_days)
    raw_codes = []
    for code, row in sec_df.iterrows():
        try:
            start_date = row['start_date']
            if start_date is None or start_date > min_start:
                continue
            if code in set(g.defensive_bond_etfs + [g.cash_etf]):
                continue
            raw_codes.append(code)
        except Exception:
            continue

    if not raw_codes:
        return [], {}

    # 获取 ETF 的“跟踪指数”时点记录。
    tracking = get_point_in_time_tracking_map(raw_codes, as_of)
    if not tracking:
        log.warning('未获得 ETF 跟踪指数映射')
        return [], {}

    # 只保留有明确跟踪指数、且符合 v1 资产类型约束的 ETF。
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

        text = '%s %s' % (display_name, traced_name)
        if builtins.any(k in text for k in g.exclude_keywords):
            continue

        prelim.append(code)
        meta[code] = {
            'traced_index_code': str(traced_code),
            'traced_index_name': str(traced_name),
            'display_name': display_name,
        }

    # 黄金作为显式跨资产分散器加入；仍要求已经上市。
    if g.gold_etf in sec_df.index:
        try:
            if sec_df.loc[g.gold_etf, 'start_date'] <= min_start:
                prelim.append(g.gold_etf)
                meta[g.gold_etf] = {
                    'traced_index_code': 'SPECIAL_GOLD',
                    'traced_index_name': '黄金',
                    'display_name': str(sec_df.loc[g.gold_etf, 'display_name']),
                }
        except Exception:
            pass

    prelim = sorted(set(prelim))
    if not prelim:
        return [], {}

    # ADV20 流动性。
    adv20, counts = get_adv(prelim, as_of, g.liquidity_lookback)
    liquid = [
        c for c in prelim
        if counts.get(c, 0) >= g.min_liquidity_observations
        and adv20.get(c, 0) >= g.min_adv20
    ]

    # 对同一个跟踪指数只保留 ADV20 最大的一只 ETF。
    best_by_index = {}
    for code in liquid:
        idx = meta[code]['traced_index_code']
        old = best_by_index.get(idx)
        if old is None or adv20.get(code, 0) > adv20.get(old, 0):
            best_by_index[idx] = code

    final_codes = sorted(set(best_by_index.values()))
    final_adv = {c: adv20[c] for c in final_codes if c in adv20}

    log.info('Universe: 全部ETF=%d | 初筛=%d | 流动性通过=%d | 跟踪指数去重后=%d' % (
        len(sec_df), len(prelim), len(liquid), len(final_codes)))
    return final_codes, final_adv


def get_point_in_time_tracking_map(codes, as_of):
    rows = []
    batch_size = 300
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        try:
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
            df = finance.run_query(q)
            if df is not None and not df.empty:
                rows.append(df)
        except Exception as e:
            log.warning('FUND_INVEST_TARGET 查询失败 batch=%d: %s' % (i, e))

    if not rows:
        return {}

    df = pd.concat(rows, ignore_index=True)
    df['start_date'] = pd.to_datetime(df['start_date'], errors='coerce')
    df['pub_date'] = pd.to_datetime(df['pub_date'], errors='coerce')
    df['end_date'] = pd.to_datetime(df['end_date'], errors='coerce')
    as_of_ts = pd.Timestamp(as_of)
    df = df[(df['end_date'].isna()) | (df['end_date'] >= as_of_ts)]

    # 若历史上同一 ETF 更换过跟踪指数，取 as_of 时点最新生效的一条。
    df = df.sort_values(['code', 'start_date', 'pub_date'])
    df = df.groupby('code', as_index=False).tail(1)

    out = {}
    for _, row in df.iterrows():
        out[row['code']] = {
            'traced_index_code': row['traced_index_code'],
            'traced_index_name': row['traced_index_name'],
        }
    return out


def get_adv(codes, as_of, lookback):
    adv = {}
    counts = {}
    batch_size = 200
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        try:
            df = get_price(
                batch,
                end_date=as_of,
                count=lookback,
                frequency='daily',
                fields=['money'],
                panel=False,
                skip_paused=True,
                fq='pre',
            )
            if df is None or df.empty:
                continue
            if 'code' not in df.columns:
                if len(batch) == 1:
                    df = df.copy()
                    df['code'] = batch[0]
                else:
                    continue
            grp = df.groupby('code')['money']
            means = grp.mean()
            cnts = grp.count()
            for c, v in means.items():
                if pd.notna(v):
                    adv[c] = float(v)
            for c, v in cnts.items():
                counts[c] = int(v)
        except Exception as e:
            log.warning('ADV 获取失败 batch=%d: %s' % (i, e))
    return adv, counts


# ============================================================
# Signal：3/6/12 月多周期动量 + 时间序列绝对动量
# ============================================================
def compute_risk_metrics(codes, as_of):
    count = max(max(g.lookbacks) + 5, g.vol_lookback + 5, g.corr_lookback + 5)
    close_matrix = get_close_matrix(codes, as_of, count)
    if close_matrix is None or close_matrix.empty:
        return pd.DataFrame(), close_matrix

    rows = []
    for code in codes:
        if code not in close_matrix.columns:
            continue
        s = close_matrix[code].dropna()
        if len(s) < g.min_history_bars:
            continue
        px = s.values.astype(float)
        if px[-1] <= 0:
            continue

        rets = {}
        valid = True
        for lb in g.lookbacks:
            if len(px) < lb + 1 or px[-lb - 1] <= 0:
                valid = False
                break
            rets[lb] = float(px[-1] / px[-lb - 1] - 1.0)
        if not valid:
            continue

        daily = pd.Series(px).pct_change().dropna().tail(g.vol_lookback)
        if len(daily) < max(40, int(g.vol_lookback * 0.8)):
            continue
        vol = float(daily.std(ddof=1) * math.sqrt(252))
        if not np.isfinite(vol) or vol <= 0:
            continue

        positive_count = builtins.sum(1 for lb in g.lookbacks if rets[lb] > 0)
        rows.append({
            'code': code,
            'r63': rets[63],
            'r126': rets[126],
            'r252': rets[252],
            'positive_count': positive_count,
            'abs_pass': positive_count >= g.min_positive_horizons,
            'vol60': max(vol, g.vol_floor),
        })

    if not rows:
        return pd.DataFrame(), close_matrix

    metrics = pd.DataFrame(rows).set_index('code')
    return metrics, close_matrix


def get_close_matrix(codes, as_of, count):
    pieces = []
    batch_size = 200
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        try:
            df = get_price(
                batch,
                end_date=as_of,
                count=count,
                frequency='daily',
                fields=['close'],
                panel=False,
                skip_paused=True,
                fq='pre',
            )
            if df is None or df.empty:
                continue
            if 'code' not in df.columns:
                if len(batch) == 1:
                    df = df.copy()
                    df['code'] = batch[0]
                else:
                    continue
            pieces.append(df[['time', 'code', 'close']])
        except Exception as e:
            log.warning('价格矩阵获取失败 batch=%d: %s' % (i, e))

    if not pieces:
        return pd.DataFrame()
    df = pd.concat(pieces, ignore_index=True)
    pivot = df.pivot_table(index='time', columns='code', values='close', aggfunc='last')
    return pivot.sort_index()


def rank_candidates(metrics):
    df = metrics.copy()
    # 用横截面百分位做集成，避免不同周期收益尺度直接相加。
    df['p63'] = df['r63'].rank(pct=True, method='average')
    df['p126'] = df['r126'].rank(pct=True, method='average')
    df['p252'] = df['r252'].rank(pct=True, method='average')
    df['score'] = (df['p63'] + df['p126'] + df['p252']) / 3.0
    df = df.sort_values(['score', 'r126'], ascending=False)
    df['rank'] = np.arange(1, len(df) + 1)
    return df


# ============================================================
# Selection：排名缓冲 + 相关性约束
# ============================================================
def select_assets_with_buffer(context, passed, close_matrix):
    if passed is None or passed.empty:
        return []

    ranked_codes = list(passed.index)
    rank_map = passed['rank'].to_dict()

    defensive = set(g.defensive_bond_etfs + [g.cash_etf])
    held_risk = [
        c for c, p in context.portfolio.positions.items()
        if p.total_amount > 0 and c not in defensive
    ]

    # 原持仓只要绝对动量仍通过、且没有掉出 top_k+buffer，就允许留下。
    keep = [
        c for c in held_risk
        if c in rank_map and rank_map[c] <= g.top_k + g.rank_buffer
    ]
    keep.sort(key=lambda c: rank_map[c])

    selected = []
    for c in keep:
        if len(selected) >= g.top_k:
            break
        if correlation_ok(c, selected, close_matrix):
            selected.append(c)

    for c in ranked_codes:
        if len(selected) >= g.top_k:
            break
        if c in selected:
            continue
        if correlation_ok(c, selected, close_matrix):
            selected.append(c)

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
        corr = pair.corr().iloc[0, 1]
        if pd.notna(corr) and corr > g.max_pair_corr:
            return False
    return True


# ============================================================
# Portfolio：逆波动率 + 波动率目标 + 容量
# ============================================================
def build_risk_weights(selected, ranked, close_matrix, context, adv20):
    if not selected:
        return {}

    inv_vol = {}
    for c in selected:
        vol = float(ranked.loc[c, 'vol60'])
        inv_vol[c] = 1.0 / max(vol, g.vol_floor)

    total = builtins.sum(inv_vol.values())
    if total <= 0:
        return {}
    raw = {c: v / total for c, v in inv_vol.items()}

    # 单资产上限。若资产不足 3 只，剩余风险预算自然留给防御资产。
    capped = cap_weights_without_forced_redistribution(raw, g.max_single_risk_weight)

    # 组合波动率缩放：只减风险，不加杠杆。
    port_vol = estimate_portfolio_vol(capped, close_matrix)
    vol_scale = 1.0
    if port_vol is not None and port_vol > 0:
        vol_scale = min(1.0, g.target_portfolio_vol / port_vol)
    scaled = {c: w * vol_scale for c, w in capped.items()}

    # 容量约束：目标持仓不超过 ADV20 的指定比例。
    portfolio_value = float(context.portfolio.total_value)
    if portfolio_value > 0:
        for c in list(scaled.keys()):
            adv = float(adv20.get(c, 0))
            if adv <= 0:
                scaled[c] = 0.0
                continue
            cap_weight = adv * g.max_adv_participation / portfolio_value
            scaled[c] = min(scaled[c], max(0.0, cap_weight))

    return {c: w for c, w in scaled.items() if w > 1e-6}


def cap_weights_without_forced_redistribution(weights, cap):
    # 先做一次温和再分配；如果资产数不足，允许总和 < 1，剩余进入防御仓。
    w = dict(weights)
    for _ in range(5):
        over = [c for c, x in w.items() if x > cap]
        if not over:
            break
        excess = builtins.sum(w[c] - cap for c in over)
        for c in over:
            w[c] = cap
        under = [c for c, x in w.items() if x < cap - 1e-12]
        room = builtins.sum(cap - w[c] for c in under)
        if not under or room <= 0 or excess <= 0:
            break
        distribute = min(excess, room)
        room_map = {c: cap - w[c] for c in under}
        room_sum = builtins.sum(room_map.values())
        for c in under:
            w[c] += distribute * room_map[c] / room_sum
    return w


def estimate_portfolio_vol(weights, close_matrix):
    codes = [c for c, w in weights.items() if w > 0 and c in close_matrix.columns]
    if not codes:
        return None
    rets = close_matrix[codes].pct_change().dropna(how='all').tail(g.vol_lookback)
    rets = rets.dropna()
    if len(rets) < 40:
        return None
    cov = rets.cov().values * 252.0
    w = np.array([weights[c] for c in codes], dtype=float)
    variance = float(np.dot(w, np.dot(cov, w)))
    if variance <= 0 or not np.isfinite(variance):
        return None
    return math.sqrt(variance)


# ============================================================
# Defensive sleeve
# ============================================================
def add_defensive_sleeve(risk_weights, as_of):
    risk_sum = builtins.sum(risk_weights.values())
    remaining = max(0.0, 1.0 - risk_sum)
    out = dict(risk_weights)
    if remaining <= 1e-6:
        return out

    defensive = choose_defensive_asset(as_of)
    out[defensive] = out.get(defensive, 0.0) + remaining
    return normalize_small_error(out)


def build_defensive_only_weights(as_of):
    return {choose_defensive_asset(as_of): 1.0}


def choose_defensive_asset(as_of):
    # 5Y / 10Y 国债 ETF 中，若中期趋势为正，选择 3/6 月平均收益更强者；否则货币 ETF。
    available = []
    try:
        sec_df = get_all_securities(['etf'], date=as_of)
        for c in g.defensive_bond_etfs:
            if c in sec_df.index:
                available.append(c)
    except Exception:
        available = []

    if not available:
        return g.cash_etf

    close = get_close_matrix(available, as_of, 135)
    best_code = None
    best_score = -1e9
    for c in available:
        if c not in close.columns:
            continue
        s = close[c].dropna()
        if len(s) < 127:
            continue
        px = s.values.astype(float)
        r63 = px[-1] / px[-64] - 1.0
        r126 = px[-1] / px[-127] - 1.0
        score = 0.5 * r63 + 0.5 * r126
        if score > 0 and score > best_score:
            best_score = score
            best_code = c

    return best_code if best_code is not None else g.cash_etf


def normalize_small_error(weights):
    total = builtins.sum(weights.values())
    if total <= 0:
        return {g.cash_etf: 1.0}
    # 只有浮点误差时归一化；不要把风险仓因为容量/波动约束产生的余量重新放大。
    if abs(total - 1.0) < 1e-8:
        return {c: w / total for c, w in weights.items()}
    return weights


# ============================================================
# Execution
# ============================================================
def execute_target_weights(context, target_weights):
    current_data = get_current_data()
    total_value = float(context.portfolio.total_value)
    if total_value <= 0:
        return

    target_weights = {c: max(0.0, float(w)) for c, w in target_weights.items() if w > 1e-6}
    target_codes = set(target_weights.keys())

    # 先清理目标外持仓。
    for c, pos in list(context.portfolio.positions.items()):
        if pos.total_amount <= 0:
            continue
        if c not in target_codes:
            if can_trade(c, current_data, is_buy=False):
                order_target_value(c, 0)

    # 再按目标权重调整。小幅漂移不交易，降低手续费和无意义换手。
    for c, w in target_weights.items():
        try:
            current_data[c]
        except Exception:
            continue
        pos = context.portfolio.positions.get(c, None)
        current_value = 0.0 if pos is None else float(pos.value)
        current_w = current_value / total_value if total_value > 0 else 0.0
        gap = w - current_w

        if pos is not None and pos.total_amount > 0 and abs(gap) < g.min_weight_change:
            continue

        target_value = w * total_value
        trade_value = abs(target_value - current_value)
        if trade_value < g.min_trade_value:
            continue

        if can_trade(c, current_data, is_buy=(gap > 0)):
            order_target_value(c, target_value)


def can_trade(code, current_data, is_buy):
    try:
        d = current_data[code]
        if d.paused:
            return False
        px = d.last_price
        if px is None or pd.isna(px) or px <= 0:
            return False
        if is_buy and px >= d.high_limit:
            return False
        if (not is_buy) and px <= d.low_limit:
            return False
        return True
    except Exception:
        return False


# ============================================================
# Logging
# ============================================================
def log_selection(ranked, selected, target_weights, adv20):
    log.info('最终风险资产: %s' % selected)
    for c in selected:
        if c not in ranked.index:
            continue
        r = ranked.loc[c]
        log.info(
            '%s | rank=%d score=%.3f | 3m=%+.2f%% 6m=%+.2f%% 12m=%+.2f%% '
            '| vol60=%.2f%% | ADV20=%.2f亿' % (
                c,
                int(r['rank']),
                r['score'],
                100 * r['r63'],
                100 * r['r126'],
                100 * r['r252'],
                100 * r['vol60'],
                adv20.get(c, 0) / 1e8,
            )
        )

    pretty = ', '.join('%s=%.1f%%' % (c, 100 * w) for c, w in sorted(target_weights.items()))
    log.info('目标权重: %s' % pretty)
