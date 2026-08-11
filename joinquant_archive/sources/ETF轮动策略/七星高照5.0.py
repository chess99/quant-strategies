# 克隆自聚宽文章：https://www.joinquant.com/post/67371
# 标题：小改七星高照5.0
# 作者：futures hh

# 克隆自聚宽文章：https://www.joinquant.com/post/67348
# 标题：七星高照5.0最终版2年7.7倍
# 作者：弈剑

import numpy as np
import math
import pandas as pd
from jqdata import *
from datetime import time  # 新增：实时止损需要用到time模块

# ================== 【全局静态常量】==================

ETF_POOL_DEF = [
    # 境外
    "159941.XSHE", #纳指ETF
    "159509.XSHE", #纳指科技ETF
    "513500.XSHG", #标普500ETF
    "513520.XSHG", #日经ETF
    "513030.XSHG", #德国ETF
    "513080.XSHG", #法国ETF
    "159100.XSHE", #巴西ETF
    "159329.XSHE", #沙特ETF
    # 商品
    "518880.XSHG", #黄金ETF
    "159980.XSHE", #有色ETF
    "161226.XSHE", #白银ETF
    "159985.XSHE", #豆粕ETF
    "159981.XSHE", #能源化工ETF
    "501018.XSHG", #南方原油LOF
    # 债券
    "511090.XSHG", #30年国债ETF
    # 国内
    "513130.XSHG", #恒生科技ETF
    "520500.XSHG", #恒生创新药ETF
    "513970.XSHG", #消费ETF
    "513690.XSHG", #港股红利ETF
    "159915.XSHE", #创业板ETF
    "563300.XSHG", #中证2000ETF
    "563360.XSHG", #中证A500ETF
    "510410.XSHG", #资源ETF
    "515210.XSHG", #钢铁ETF
    "562800.XSHG", #稀有金属ETF
    "159928.XSHE", #中证消费ETF
    "512690.XSHG", #中证酒ETF
    "159992.XSHE", #创新药ETF
    "588220.XSHG", #科创100ETF
    "159819.XSHE", #人工智能ETF
    "159851.XSHE", #金融科技ETF
    "159326.XSHE", #电网设备ETF
    "515030.XSHG", #新能源车ETF
    "516160.XSHG", #新能源ETF
    "512710.XSHG", #军工ETF
    "515220.XSHG", #煤炭ETF
    "512880.XSHG", #证券ETF
    "159378.XSHE", #通用航空ETF
    "159206.XSHE", #卫星ETF
    "516510.XSHG", #云计算ETF
    "515050.XSHG", #5GETF
    "512170.XSHG", #医疗ETF
    "159870.XSHE", #化工ETF
    "159611.XSHE", #电力ETF
    "159995.XSHE", #芯片ETF
    "515790.XSHG", #光伏ETF
    "159755.XSHE", #电池ETF
    "515000.XSHG", #科技ETF
    "562500.XSHG", #机器人ETF
]

# ============== 策略参数默认值（_DEF后缀） ==============

# 动量计算参数
HOLDINGS_NUM_DEF = 1          # 持仓ETF数量
LOOKBACK_DAYS_DEF = 24        # 长期动量计算周期
DEFENSIVE_ETF_DEF = "511880.XSHG"  # 防御性ETF（货币ETF）
MIN_MONEY_DEF = 5000          # 最小交易金额

# 风险控制参数
STOP_LOSS_DEF = 0.95          # 固定百分比止损线（下跌5%止损）
LOSS_DEF = 0.965              # 近3日跌幅止损线

# 成交量过滤参数
ENABLE_VOLUME_CHECK_DEF = True # 是否启用成交量过滤
VOLUME_LOOKBACK_DEF = 5       # 成交量历史参考天数
VOLUME_THRESHOLD_DEF = 2.5    # 放量阈值（大于设定值视为放量）
VOLUME_RETURN_LIMIT_DEF = 1   # 年化收益率过滤阈值

# R²筛选参数
USE_R2_FILTER_DEF = True     # 是否启用R²筛选
R2_MIN_THRESHOLD_DEF = 0.4    # R²最低阈值（0.3≤R²≤1）

# 得分阈值
MIN_SCORE_THRESHOLD_DEF = 0.0 # 最低得分阈值
MAX_SCORE_THRESHOLD_DEF = 5.0 # 最高得分阈值

# =================== 【初始化函数】 =====================

def initialize(context):
    
    g.context = context
    
    # ============== 赋值全局常量到g变量 ==============
    g.etf_pool = ETF_POOL_DEF  # 引用全局ETF池常量
    
    # 设置日志级别
    log.set_level('order', 'error')
    log.set_level('system', 'error')
    log.set_level('strategy', 'info')
    
    # ================ 聚宽环境初始化 =================
    # 开启「避免未来数据」功能
    set_option("avoid_future_data", True)
    # 开启「使用真实价格」功能
    set_option("use_real_price", True)
    
    # 设置滑点
    set_slippage(PriceRelatedSlippage(0.0001), type="fund")
    
    # 设置交易成本:ETF交易成本较低
    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=0,
            open_commission=0.0002,
            close_commission=0.0002,
            close_today_commission=0,
            min_commission=5,
        ),
        type="fund",
    )

    # 设置参考基准
    set_benchmark("000300.XSHG")  
    
    # ===== 赋值策略参数到g变量（引用_DEF后缀的全局常量） =====
    # 动量计算参数
    g.lookback_days = LOOKBACK_DAYS_DEF
    g.holdings_num = HOLDINGS_NUM_DEF
    g.defensive_etf = DEFENSIVE_ETF_DEF
    g.min_money = MIN_MONEY_DEF
    
    # 风险控制参数
    g.stop_loss = STOP_LOSS_DEF
    g.loss = LOSS_DEF
    g.stopped_etfs = set()  # 新增：标记已止损的ETF，避免重复止损
    
    # 成交量过滤参数
    g.enable_volume_check = ENABLE_VOLUME_CHECK_DEF
    g.volume_lookback = VOLUME_LOOKBACK_DEF
    g.volume_threshold = VOLUME_THRESHOLD_DEF
    g.volume_return_limit = VOLUME_RETURN_LIMIT_DEF

    # R²筛选参数赋值
    g.use_r2_filter = USE_R2_FILTER_DEF
    g.r2_min_threshold = R2_MIN_THRESHOLD_DEF
    
    # 得分阈值
    g.min_score_threshold = MIN_SCORE_THRESHOLD_DEF
    g.max_score_threshold = MAX_SCORE_THRESHOLD_DEF
    
    # ================ 持仓管理 ================
    g.positions = {}  # 记录持仓
   
    # ================ 交易调度 ================
    # 每天开盘后检查持仓
    run_daily(check_positions, time='09:25')
    # 新增：每分钟执行一次止损检查（实时止损）
    run_daily(check_stop_loss_minutely, time='every_bar')
    # 执行卖出操作
    run_daily(etf_sell_trade, time='14:00')
    # 执行买入操作
    run_daily(etf_buy_trade, time='14:01')
    
    # ================ 打印初始化信息 ================
    log.info(f"""策略参数初始化完成:
    - ETF池大小: {len(g.etf_pool)} 只ETF | 动量周期: {g.lookback_days} 天 | 成交量过滤: {'启用' if g.enable_volume_check else '禁用'} | 防御ETF: {g.defensive_etf}
    - 实时止损功能已启用 | 止损阈值: {g.stop_loss}（下跌{(1-g.stop_loss)*100}%触发）
""")

# ============ 持仓检查 ===============
def check_positions(context):
    """每日开盘后检查持仓状态"""
    current_data = get_current_data()
    for security in context.portfolio.positions:
        position = context.portfolio.positions[security]
        if position.total_amount > 0:
            security_name = get_security_name(security)
            log.debug(f"📊 持仓检查: {security} {security_name}, 数量: {position.total_amount}, 成本: {position.avg_cost:.3f}, 当前价: {position.price:.3f}")
            if current_data[security].paused:
                log.info(f"⚠️ {security} {security_name} 今日停牌")

# ================== 新增：盘中实时止损（每分钟检查）==================
def check_stop_loss_minutely(context):
    """
    分钟级实时止损（替换原固定时间止损）
    只要持仓亏损达到阈值，立刻卖出，不用等到收盘前
    """
    # 只在交易时段（9:30-11:30, 13:00-15:00）执行
    current_time = context.current_dt.time()
    if not ((time(9, 30) <= current_time <= time(11, 30)) or 
        (time(13, 00) <= current_time <= time(15, 00))):
        return
    
    # 只检查策略里的ETF + 防御ETF
    check_secs = [s for s in context.portfolio.positions if s in g.etf_pool or s == g.defensive_etf]
    
    for security in check_secs:
        try:
            pos = context.portfolio.positions[security]
            if pos.total_amount <= 0:
                continue
                
            current_price = pos.price
            cost_price = pos.avg_cost
            security_name = get_security_name(security)
            
            ## 1. 成本价防护
            if cost_price <= 0:
                continue
                
            # 2. 排除当日买入的标的（T+1）
            if pos.closeable_amount <= 0:
                continue  # 当天买入的，直接跳过止损检查
                
            # 3. 计算止损阈值（加0.1%缓冲，避免临时击穿）
            stop_loss_price = cost_price * g.stop_loss * 1.001
            loss_pct = (current_price / cost_price - 1) * 100
            
            # 4. 仅当触发止损时才执行清仓
            if current_price <= stop_loss_price:
                success = smart_order_target_value(security, 0, context)
                if success:
                    g.stopped_etfs.add(security)  # 标记已止损
                    log.info(f"🚨 【实时止损成功】盘中止损卖出：{security} {security_name} | 成本：{cost_price:.3f} | 当前价：{current_price:.3f} | 亏损：{loss_pct:.2f}%")
                else:
                    log.error(f"🚨 【实时止损失败】盘中止损失败：{security} {security_name} | 亏损：{loss_pct:.2f}% | 无法卖出")
                    
        except Exception as e:
            log.error(f"🚨 【实时止损检查失败】{security}：{e}")

# ==================== 卖出函数 ====================
def etf_sell_trade(context):
    """
    卖出函数（修改：移除固定时间止损逻辑，保留非目标持仓卖出）
    功能：卖出不在目标列表中的持仓（止损由实时止损函数处理）
    """
    log.info("======================== 卖出操作开始 ========================")
    
    # 获取当前持仓
    current_positions = list(context.portfolio.positions.keys())
    
    # 如果没有持仓，直接返回
    if not current_positions:
        log.info("当前无持仓，无需卖出")
        log.info("======================== 卖出操作完成 ========================")
        return
    
    # 获取符合条件的ETF排名
    ranked_etfs = get_ranked_etfs(context)
    
    # 确定目标ETF
    target_etf = None
    if ranked_etfs and ranked_etfs[0]['score'] >= g.min_score_threshold:
        target_etf = ranked_etfs[0]['etf']
        log.debug(f"📌 选中进攻型目标ETF：{target_etf} {get_security_name(target_etf)}")
    else:
        log.info("⚠️ 无符合条件的进攻型ETF，检查防御ETF是否可用")
    
    # 检查防御ETF是否可用
    defensive_etf_available = False
    if target_etf is None:
        defensive_etf_available = check_defensive_etf_available(context)
        if defensive_etf_available:
            target_etf = g.defensive_etf
            log.info(f"📌 切换到防御ETF：{target_etf} {get_security_name(target_etf)}")
        else:
            log.info("⚠️ 防御ETF不可用，本次无目标ETF")
    
    # 构建目标ETF列表
    target_etfs = [target_etf] if target_etf else []
    target_etfs_set = set(target_etfs)
    
    # ============== 仅保留：卖出不在目标列表中的持仓 ==============
    # 重新获取持仓（避免止损操作后数据不一致）
    latest_positions = list(context.portfolio.positions.keys())
    for security in latest_positions:
        # 只处理策略关注的标的（ETF池 + 防御ETF）
        if (security in g.etf_pool or security == g.defensive_etf)  and security not in target_etfs_set:
            position = context.portfolio.positions[security]
            if position.total_amount > 0:
                # 提前定义标的名称，复用
                security_name = get_security_name(security)
                success = smart_order_target_value(security, 0, context)
                if success:
                    log.debug(f"📤 卖出不在目标列表的持仓: {security} {security_name}")
                else:
                    log.warning(f"❌ 卖出失败：{security} {security_name}，非目标持仓未清仓")
                   
    log.info("======================== 卖出操作完成 ========================")

# ==================== 获取ETF排名函数 ====================
def get_ranked_etfs(context):
    """
    获取符合条件的ETF排名
    返回结果：应用所有过滤条件，返回满足条件的ETF列表，按得分降序
    """
    etf_metrics = []
    
    # 可选：先进行均线过滤（减少计算量）
    filtered_pool = g.etf_pool
    
    current_data = get_current_data()
    for etf in filtered_pool:
        # ========== 新增：停牌过滤 ==========
        if current_data[etf].paused:
            log.debug(f"{etf}: 今日停牌，跳过计算")
            continue

        metrics = calculate_momentum_metrics(context, etf)
        if metrics is not None:
            # 过滤掉得分异常的ETF
            if 0 < metrics['score'] < g.max_score_threshold:
                etf_metrics.append(metrics)
            else: 
                log.debug(f"⚠️ {etf} 得分不满足要求！")
                
    # 按得分降序排序
    etf_metrics.sort(key=lambda x: x['score'], reverse=True)
    return etf_metrics

# ==================== 动量指标计算函数 ====================
def calculate_momentum_metrics(context, etf):
    """
    计算ETF的动量指标，整合所有过滤条件
    返回包含各项指标和过滤结果的字典
    """
    try:
        # 获取历史价格数据加20天缓冲，避免数据切片/缺失导致计算不足
        lookback = g.lookback_days + 20
        prices = attribute_history(etf, lookback, '1d', ['close', 'high'])
        current_data = get_current_data()
        
        if prices.empty or len(prices) < g.lookback_days:
            log.debug(f"{etf}: 历史数据为空或数据不足（仅{len(prices)}天），跳过计算")
            return None
        
        # 获取当前价格并添加到价格序列中
        current_price = current_data[etf].last_price
        if current_price <= 0:
            log.debug(f"{etf}: 实时价格异常（{current_price}），跳过计算")
            return None
        price_series = np.append(prices["close"].values, current_price)
        
        # 过滤近3日单日大跌的ETF，避免后续复杂计算
        if len(price_series) >= 4:
            # 加除零防护：避免价格为0导致除零错误
            day1_prev = price_series[-2] if price_series[-2] > 0 else 1
            day2_prev = price_series[-3] if price_series[-3] > 0 else 1
            day3_prev = price_series[-4] if price_series[-4] > 0 else 1
            
            day1_ratio = price_series[-1] / day1_prev
            day2_ratio = price_series[-2] / day2_prev
            day3_ratio = price_series[-3] / day3_prev
            
            min_ratio = min(day1_ratio, day2_ratio, day3_ratio)
            max_loss_percent = (1 - min_ratio) * 100
            threshold_percent = (1 - g.loss) * 100
            
            if min_ratio < g.loss:
                log.debug(f"⚠️ {etf} 近3日单日最大跌幅{max_loss_percent:.2f}% > {threshold_percent:.2f}%阈值，直接过滤")
                return None  # 直接返回None，彻底终止后续计算
       
        # ========== 成交量过滤检查 ==========
        if g.enable_volume_check and len(price_series) > g.lookback_days:
            volume_ratio = get_volume_ratio(context, etf)
            volume_annualized = get_annualized_returns(price_series,g.lookback_days)
            if volume_ratio is not None:
                if volume_annualized > g.volume_return_limit:
                    log.debug(f"{etf}: 成交量放大{volume_ratio:.2f}倍且折合年化收益{volume_annualized:.2f}超过设置值{g.volume_return_limit}，属于“高位放量”，过滤掉")
                    return None

        # ========== 长期动量计算 ==========
        # 使用最后g.lookback_days+1天的数据
        recent_price_series = price_series[-(g.lookback_days + 1):]
        y = np.log(recent_price_series)
        x = np.arange(len(y))
        weights = np.linspace(1, 2, len(y))  # 加权回归，近期权重更高
        
        # ========== 计算年化收益率 ==========
        slope, intercept = np.polyfit(x, y, 1, w=weights)
        annualized_returns = math.exp(slope * 250) - 1

        # ========== 计算R²（拟合优度）==========
        ss_res = np.sum(weights * (y - (slope * x + intercept)) ** 2)
        ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
        r_squared = 1 - ss_res / ss_tot if ss_tot else 0
        
        # ========== R²过滤检查 ==========
        if g.use_r2_filter:
            if not (g.r2_min_threshold <= r_squared <= 1):
                log.debug(f"{etf}: R²={r_squared:.4f} 不在[{g.r2_min_threshold}, 1]范围内，过滤掉")
                return None
        
        # 综合得分 = 年化收益率 * 趋势稳定性
        score = annualized_returns * r_squared
        
        # ========== 短期风控过滤 ==========
        if len(price_series) >= 4:
            day1_ratio = price_series[-1] / price_series[-2]
            day2_ratio = price_series[-2] / price_series[-3]
            day3_ratio = price_series[-3] / price_series[-4]
            
            if min(day1_ratio, day2_ratio, day3_ratio) < g.loss:
                score = 0
                log.debug(f"⚠️ {etf} 近3日有单日跌幅超设定值，已排除")
        
        # 返回ETF的全维度计算指标字典（核心数据输出，供后续排序/买入逻辑使用）
        return {
            # ========== 基础标识信息 ==========
            'etf': etf,# ETF标的代码
            'current_price': current_price,# ETF实时价格
            
            # ========== 核心动量指标（策略筛选核心） ==========
            'slope': slope,# 对数回归斜率
            'annualized_returns': annualized_returns,# 长期年化收益率
            'r_squared': r_squared,  # 趋势拟合优度R²
            'score': score,# 综合得分（年化收益×R²，策略选标的核心依据）
        }
        
    except Exception as e:
        log.warning(f"计算{etf}动量指标时出错: {e}")
        return None

# ==================== 成交量过滤函数 ====================
def get_volume_ratio(context, security, lookback_days=None, threshold=None):
    """
    计算成交量比值（当日成交量/历史平均成交量）
    返回：若放量（>threshold）则返回比值，否则返回None
    """
    if lookback_days is None:
        lookback_days = g.volume_lookback
    if threshold is None:
        threshold = g.volume_threshold
    
    try:
        # 1. 获取历史成交量（N天平均）
        hist_data = attribute_history(security, lookback_days, '1d', ['volume'])
        if hist_data.empty or len(hist_data) < lookback_days:
            log.debug(f"{security}: 历史成交量数据不足")
            return None
        
        avg_volume = hist_data['volume'].mean()
        
        # 2. 获取当日实时成交量（分钟数据累加）
        today = context.current_dt.date()
        df_vol = get_price(
            security,
            start_date=today,
            end_date=context.current_dt,
            frequency='1m',
            fields=['volume'],
            skip_paused=False,
            fq='pre',
            panel=True,
            fill_paused=False
        )
        
        if df_vol is None or df_vol.empty:
            log.debug(f"{security}: 当日成交量数据为空")
            return None
        
        current_volume = df_vol['volume'].sum()
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        # 3. 超过阈值视为放量
        etf_name = get_security_name(security)
        if volume_ratio > threshold:
            log.debug(f"⚠️ {security}-{etf_name}: 成交量比值 {volume_ratio:.2f} > 阈值 {threshold}")
            return volume_ratio
        else:
            log.debug(f"{security}-{etf_name}: 成交量比值 {volume_ratio:.2f} <= 阈值 {threshold}")
            return None
            
    except Exception as e:
        log.warning(f"成交量检测失败 {security}: {e}")
        return None

# =================== 计算年化收益 ===================
def get_annualized_returns(price_series,lookback_days):
    # 使用最后g.lookback_days+1天的数据
    recent_price_series = price_series[-(lookback_days + 1):]
    y = np.log(recent_price_series)
    x = np.arange(len(y))
    weights = np.linspace(1, 2, len(y))  # 加权回归，近期权重更高
    
    # 计算年化收益率
    slope, intercept = np.polyfit(x, y, 1, w=weights)
    annualized_returns = math.exp(slope * 250) - 1
    return annualized_returns

# ==================== 买入函数 ====================
def etf_buy_trade(context):
    """
    买入函数（修复版：加入浮点容差，避免因佣金估算误差导致无法买入）
    功能：买入符合条件的ETF，确保资金充足且无其他持仓干扰
    """
    log.info("======================== 买入操作开始 ========================")
    
    # 获取符合条件的ETF排名
    ranked_etfs = get_ranked_etfs(context)
    
    # 记录所有ETF的指标（用于调试）
    if ranked_etfs:
        log.info("========================== 排名前五 ==========================")
        for idx, metrics in enumerate(ranked_etfs[:5], start=1):  
            etf_name = get_security_name(metrics['etf'])
            annualized_pct = metrics['annualized_returns'] * 100
            log.info(f"{idx}. {metrics['etf']} {etf_name}: 动量得分={metrics['score']:.4f}|年化收益={annualized_pct:.2f}%|R²={metrics['r_squared']:.4f}")
    
    # 确定目标ETF
    target_etf = None
    if ranked_etfs and ranked_etfs[0]['score'] >= g.min_score_threshold:
        target_etf = ranked_etfs[0]['etf']
        top_metrics = ranked_etfs[0]
        etf_name = get_security_name(target_etf)
        log.debug(f"🎯 选择排名第一: {target_etf} {etf_name}，得分: {top_metrics['score']:.4f}")
    else:
        # 防御模式
        if check_defensive_etf_available(context):
            target_etf = g.defensive_etf
            etf_name = get_security_name(target_etf)
            log.info(f"🛡️ 进入防御模式，选择防御ETF: {target_etf} {etf_name}")
        else:
            log.info("💤 进入空仓模式，无符合条件的ETF且防御ETF不可用")
    
    # 如果没有目标ETF，直接返回
    if target_etf is None:
        log.info("无目标ETF，保持空仓")
        return
    
    # ========== 关键修复：确保所有其他持仓已清空 ==========
    # 获取当前所有持仓（仅限于策略关注标的）
    current_positions = list(context.portfolio.positions.keys())
    current_etf_positions = [pos for pos in current_positions if pos in g.etf_pool or pos == g.defensive_etf]
    
    # 找出所有不是目标ETF的持仓
    other_positions = [pos for pos in current_etf_positions if pos != target_etf]
    if other_positions:
        # 检查这些持仓是否仍有余额（可能部分卖出，但未清空）
        for pos in other_positions:
            position = context.portfolio.positions[pos]
            if position.total_amount > 0:
                log.info(f"⚠️ 尚有其他持仓 {get_security_name(pos)} 未卖出，等待卖出完成后再买入新标的")
                log.info("======================== 买入操作完成 ========================")
                return
    
    # ========== 资金充足性检查与动态调整（加入容差） ==========
    total_value = context.portfolio.total_value
    target_value = total_value  # 初始目标为满仓
    
    # 获取当前目标ETF的持仓市值
    current_value = 0
    if target_etf in context.portfolio.positions:
        position = context.portfolio.positions[target_etf]
        if position.total_amount > 0:
            current_value = position.total_amount * position.price
    
    # 计算需要新增的现金（买入所需）
    need_cash = max(0, target_value - current_value)
    available_cash = context.portfolio.available_cash
    
    # 定义佣金计算函数，与 smart_order_target_value 保持一致
    def calc_commission(amount):
        return max(5, amount * 0.0002)
    
    if need_cash > 0:
        estimated_commission = calc_commission(need_cash)
        total_required = need_cash + estimated_commission
        
        # 使用容差判断现金是否充足（允许微小误差）
        if total_required > available_cash + 1e-6:
            log.info(f"⚠️ 可用现金不足：需要 {total_required:.2f}，实际可用 {available_cash:.2f}，尝试调整目标市值")
            
            # 计算最大可买入金额（不含佣金），使得 买入金额 + 佣金 ≤ 可用现金
            # 对于大额（佣金按比例），解方程：x + 0.0002x ≤ available_cash → x ≤ available_cash / 1.0002
            # 对于小额（佣金固定5元），则 x ≤ available_cash - 5
            if available_cash > 25000 + 5:  # 粗略判断，确保进入比例佣金分支
                max_buy_cash = available_cash / 1.0002
                # 微调以确保总需求不超过可用现金（避免浮点误差）
                max_buy_cash = max_buy_cash * 0.999999  # 减小极小量
            else:
                max_buy_cash = available_cash - 5
                if max_buy_cash < 0:
                    max_buy_cash = 0
            
            # 新的目标市值 = 当前持仓市值 + 最大可买入金额
            new_target = current_value + max_buy_cash
            
            # 确保新目标不超过原始总资产（通常不会，因为现金不足）
            if new_target < target_value - 1e-6:
                log.info(f"⚖️ 调整目标市值：从 {target_value:.2f} 降至 {new_target:.2f}，新增现金需求 {max_buy_cash:.2f}")
                target_value = new_target
                need_cash = max_buy_cash
            else:
                log.info("调整后目标未变，无法买入")
                log.info("======================== 买入操作完成 ========================")
                return
            
            # 二次验证调整后的资金需求（同样使用容差）
            if need_cash > 0:
                new_commission = calc_commission(need_cash)
                if need_cash + new_commission > available_cash + 1e-6:
                    log.info("⚠️ 调整后仍现金不足，放弃买入")
                    log.info("======================== 买入操作完成 ========================")
                    return
        else:
            log.debug(f"资金充足，可直接买入，需现金 {need_cash:.2f}")
    else:
        log.debug("无需新增现金")
    
    # 判断是否需要调仓（5%容差）
    if abs(current_value - target_value) > target_value * 0.05 or current_value == 0:
        success = smart_order_target_value(target_etf, target_value, context)
        if success:
            etf_name = get_security_name(target_etf)
            action = "买入" if current_value < target_value else "调仓"
            log.debug(f"📦 {action}: {target_etf} {etf_name}，目标金额: {target_value:.2f}")
    else:
        log.debug("持仓市值与目标接近，无需调仓")
    
    log.info("======================== 买入操作完成 ========================")

# ==================== 辅助函数 ====================
def get_security_name(security):
    """获取证券名称"""
    current_data = get_current_data()
    return current_data[security].name

def check_defensive_etf_available(context):
    """检查防御ETF是否可交易"""
    current_data = get_current_data()
    defensive_etf = g.defensive_etf

    if current_data[defensive_etf].paused:
        log.info(f"防御性ETF {defensive_etf} 今日停牌")
        return False
        
    if current_data[defensive_etf].last_price >= current_data[defensive_etf].high_limit:
        log.info(f"防御性ETF {defensive_etf} 当前涨停")
        return False
        
    if current_data[defensive_etf].last_price <= current_data[defensive_etf].low_limit:
        log.info(f"防御性ETF {defensive_etf} 当前跌停")
        return False
        
    return True

def smart_order_target_value(security, target_value, context):
    """
    智能下单函数（修复版：增加现金检查及佣金预估）
    """
    current_data = get_current_data()
    
    # 检查标的是否停牌
    if current_data[security].paused:
        log.info(f"{security} {get_security_name(security)}: 今日停牌，跳过交易")
        return False

    # 检查涨停
    if current_data[security].last_price >= current_data[security].high_limit:
        log.info(f"{security} {get_security_name(security)}: 当前涨停，跳过买入")
        return False

    # 检查跌停
    if current_data[security].last_price <= current_data[security].low_limit:
        log.info(f"{security} {get_security_name(security)}: 当前跌停，跳过卖出")
        return False

    # 获取当前价格
    current_price = current_data[security].last_price
    if current_price == 0:
        log.info(f"{security} {get_security_name(security)}: 当前价格为0，跳过交易")
        return False

    # 计算目标数量
    target_amount = int(target_value / current_price)
    
    # 对于ETF，按100股整数倍调整
    target_amount = (target_amount // 100) * 100
    if target_amount <= 0 and target_value > 0:
        target_amount = 100
    
    # 获取当前持仓
    current_position = context.portfolio.positions.get(security, None)
    current_amount = current_position.total_amount if current_position else 0
    
    # 计算需要调整的数量
    amount_diff = target_amount - current_amount
    
    # 检查最小交易金额
    trade_value = abs(amount_diff) * current_price
    if 0 < trade_value < g.min_money:
        log.info(f"{security} {get_security_name(security)}: 交易金额{trade_value:.2f}小于最小交易额{g.min_money}，跳过交易")
        return False

    # 检查T+1限制
    if amount_diff < 0:  # 卖出操作
        closeable_amount = current_position.closeable_amount if current_position else 0
        if closeable_amount == 0:
            log.info(f"{security} {get_security_name(security)}: 当天买入不可卖出(T+1)")
            return False
        amount_diff = -min(abs(amount_diff), closeable_amount)

    # ========== 新增：买入操作的现金检查（考虑佣金） ==========
    
    if amount_diff > 0:
        required_cash = amount_diff * current_price
        estimated_commission = max(5, required_cash * 0.0002)
        total_required = required_cash + estimated_commission
        available_cash = context.portfolio.available_cash
        if total_required > available_cash + 1e-6:  # 加入容差
            log.info(f"⚠️ {security} {get_security_name(security)}: 现金不足（含佣金），需要 {total_required:.2f}，可用 {available_cash:.2f}，跳过买入")
            return False
        
    # 执行下单
    if amount_diff != 0:
        order_result = order(security, amount_diff)
        if order_result:
            # 更新持仓记录
            g.positions[security] = target_amount

            security_name = get_security_name(security)
            if amount_diff > 0:
                log.info(f"📥 买入 {security} {security_name}，数量: {amount_diff}，价格: {current_price:.3f}")
            else:
                log.info(f"📤 卖出 {security} {security_name}，数量: {abs(amount_diff)}，价格: {current_price:.3f}")
            return True
        else:
            log.warning(f"下单失败: {security} {get_security_name(security)}，数量: {amount_diff}")
            return False
    
    return False

# ==================== 主交易函数（保持兼容性） ====================
def trade(context):
    """主交易函数，为了兼容性保留"""
    # 在原有策略二中，trade函数调用了etf_trade
    # 现在我们已经拆分为两个函数，这里可以保持为空或调用买入函数
    pass