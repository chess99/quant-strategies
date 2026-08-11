# 克隆自聚宽文章：https://www.joinquant.com/post/77576
# 标题：懒人etf轮动策略
# 作者：yukida

# 傻瓜模型 1.5 — 聚宽（JoinQuant）回测策略
# 逻辑：每周五收盘前执行一次调仓
#   1. 创业板周CCI(14) > 130  →  持有创业板ETF（159915）
#   2. 否则 纳指在45周均线上  →  持有纳指ETF（513100）
#   3. 否则 黄金在45周均线上  →  持有黄金ETF（518880）
#   4. 以上均不满足           →  清仓持现金
 
import numpy as np
import pandas as pd
 
 
# ══════════════════════════════════════════════
# 初始化
# ══════════════════════════════════════════════
def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    log.set_level('order', 'error')
    set_slippage(PriceRelatedSlippage(0.0002))
    set_order_cost(
        OrderCost(open_tax=0, close_tax=0.001,
                  open_commission=0.0003, close_commission=0.0003,
                  min_commission=5),
        type='fund'
    )
 
    g.gem_etf    = '159915.XSHE'   # 创业板ETF
    g.nasdaq_etf = '513100.XSHG'   # 纳指ETF
    g.gold_etf   = '518880.XSHG'   # 黄金ETF
 
    g.gem_index    = '399006.XSHE'  # 创业板指（算CCI）
    g.nasdaq_proxy = '513100.XSHG'  # 纳指ETF（算均线）
    g.gold_proxy   = '518880.XSHG'  # 黄金ETF（算均线）
 
    g.cci_period = 14
    g.cci_thresh = 130
    g.ma_period  = 45
 
    # 记录当前持仓标的，避免重复下单
    g.current_holding = None
 
    run_weekly(rebalance, weekday=5, time='14:50')
 
 
# ══════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════
 
def get_weekly_close(security, bar_count, end_date):
    """取日线数据，按交易周（W-FRI）聚合为周收盘价序列"""
    df = get_price(
        security,
        end_date=end_date,
        frequency='daily',
        fields=['close'],
        count=bar_count * 8,
        skip_paused=False,
        panel=False
    )
    if df.empty:
        return np.array([])
    df.index = pd.to_datetime(df.index)
    weekly = df['close'].resample('W-FRI').last().dropna()
    return weekly.values
 
 
def calc_cci(close_arr, period=14):
    """用收盘价近似TP计算CCI"""
    if len(close_arr) < period:
        return 0.0
    tp = close_arr[-period:]
    ma = np.mean(tp)
    mean_dev = np.mean(np.abs(tp - ma))
    if mean_dev == 0:
        return 0.0
    return (tp[-1] - ma) / (0.015 * mean_dev)
 
 
def above_ma(close_arr, period=45):
    """判断最新收盘是否在period周均线上"""
    if len(close_arr) < period:
        return False
    return close_arr[-1] > np.mean(close_arr[-period:])
 
 
def switch_to(context, target_etf):
    """
    切换持仓到目标ETF。
    关键：若已持有目标ETF则跳过，不产生交易。
    """
    if g.current_holding == target_etf:
        log.info(f"  → 持仓不变，继续持有 {target_etf}，跳过")
        return
 
    # 卖出其他仓位
    for s in list(context.portfolio.positions):
        if context.portfolio.positions[s].total_amount > 0 and s != target_etf:
            order_target(s, 0)
 
    # 买入目标
    order_target_value(target_etf, context.portfolio.total_value * 0.99)
    g.current_holding = target_etf
    log.info(f"  → 切换到 {target_etf}")
 
 
def close_all(context):
    """清仓"""
    if g.current_holding is None:
        log.info("  → 已是空仓，跳过")
        return
    for s in list(context.portfolio.positions):
        if context.portfolio.positions[s].total_amount > 0:
            order_target(s, 0)
    g.current_holding = None
    log.info("  → 清仓，持有现金")
 
 
# ══════════════════════════════════════════════
# 调仓主逻辑（每周五 14:50）
# ══════════════════════════════════════════════
 
def rebalance(context):
    today = context.current_dt.date()
    log.info(f"[{today}] 开始调仓，当前持仓={g.current_holding}")
 
    need_bars = max(g.cci_period, g.ma_period) + 5
 
    # 条件1：创业板周CCI > 130
    gem_close = get_weekly_close(g.gem_index, need_bars, today)
    cci_val   = calc_cci(gem_close, g.cci_period)
    log.info(f"  创业板CCI({g.cci_period}周) = {cci_val:.2f}")
 
    if cci_val > g.cci_thresh:
        switch_to(context, g.gem_etf)
        return
 
    # 条件2：纳指在45周均线上
    nas_close = get_weekly_close(g.nasdaq_proxy, need_bars, today)
    nas_above = above_ma(nas_close, g.ma_period)
    log.info(f"  纳指 收盘={nas_close[-1]:.3f}  45周均={np.mean(nas_close[-g.ma_period:]):.3f}  在线上={nas_above}")
 
    if nas_above:
        switch_to(context, g.nasdaq_etf)
        return
 
    # 条件3：黄金在45周均线上
    gold_close = get_weekly_close(g.gold_proxy, need_bars, today)
    gold_above = above_ma(gold_close, g.ma_period)
    log.info(f"  黄金 收盘={gold_close[-1]:.3f}  45周均={np.mean(gold_close[-g.ma_period:]):.3f}  在线上={gold_above}")
 
    if gold_above:
        switch_to(context, g.gold_etf)
        return
 
    # 条件4：持现金
    close_all(context)
 