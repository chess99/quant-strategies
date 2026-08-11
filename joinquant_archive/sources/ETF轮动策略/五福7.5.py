# 克隆自聚宽文章：https://www.joinquant.com/post/76820
# 标题：五福7.5五年半750倍，可，shi盘半年仅15%
# 作者：烟花三月ETF

# 克隆自聚宽文章：https://www.joinquant.com/post/76820
# 标题：五福7.5五年半750倍，可，shi盘半年仅15%
# 作者：烟花三月ETF

# 克隆自聚宽文章：https://www.joinquant.com/post/76292
# 标题：五福 V7 研究尝试｜五年半 263 倍 年化186%
# 作者：索拉尔

# 克隆自聚宽文章：https://www.joinquant.com/post/75715
# 标题：最新五福v7.3横空出世？：站在巨人的肩膀上看世界（自仿版）
# 作者：fafa_18

# 克隆自聚宽文章：https://www.joinquant.com/post/75568
# 标题：五福 ETF 轮动五年迭代：谁才是五年收益之王？
# 作者：NappyQuanter

# STRATEGY_NAME=五福v1.1-择时执行-H72-H78a-merge-B
# SOURCE_BASE=五福V5-opt2v4-H72-H78a-merge-B, https://www.joinquant.com/post/75568
# SOURCE_TIMING=五福5.2日内趋势准确版/日内趋势加强版, https://www.joinquant.com/post/75511
# VERSION_NOTE:
# - 以 H72/H78a merge-B 为底座，完整保留 H72 动态窗口、H78a 走弱期 R² 过滤、
#   B型主线、主线持仓延续、RegimeP0、动态池150等逻辑。
# - 合入择时五福执行层：13:10 计算目标并卖出，买入改为 13:10/13:40/14:10/14:40
#   趋势复检，14:55 强制买入剩余待买标的。
# - 不合入防追高硬过滤；该模块已验证效果不佳，只能作为日志观察，不进入交易逻辑。
import numpy as np
import math
import pandas as pd
import json
from jqdata import *
from datetime import datetime, date, timedelta
# QMT实盘代码
from jqmt import *
order = push_order(order)
order_target = push_order_target(order_target)
order_value = push_order_value(order_value)
order_target_value = push_order_target_value(order_target_value)

def initialize(context):
    set_option("avoid_future_data", True)
    set_option("use_real_price", True)
    set_slippage(PriceRelatedSlippage(0.0001), type="fund")
    set_order_cost(OrderCost(open_tax=0, close_tax=0, open_commission=0.0001,
                              close_commission=0.0001, close_today_commission=0.0001,
                              min_commission=5), type="fund")
    log.set_level('order', 'error')
    log.set_level('system', 'error')
    log.set_level('strategy', 'info')
    log.info("[机制测试] C06_C03加入V6.6强弱市过滤 | 仅修改普通候选池过滤切换")
    log.info("【五福v1.1】择时执行 + opt2_v4 + H72 + H78a 方案B(MA+R²) 启动！")

    # ==================== ETF池定义 ====================
    # 全球/海外ETF池（含大宗商品和海外市场ETF）
    g.global_etf_pool = [
#大宗商品ETF：
        '518880.XSHG',  # (黄金ETF) [ETF]-日均成交额：51.35亿元-上市日期：2013-07-29
        '501018.XSHG',  # (南方原油) [LOF]-日均成交额：24.38亿元-上市日期：2016-06-28
        '161226.XSHE',  # (国投白银LOF) [LOF]-日均成交额：5.44亿元-上市日期：2015-08-17
        '159985.XSHE',  # (豆粕ETF华夏) [ETF]-日均成交额：4.63亿元-上市日期：2019-12-05
        '159980.XSHE',  # (有色ETF大成) [ETF]-日均成交额：3.84亿元-上市日期：2019-12-24
#海外ETF：       
        '513310.XSHG',  # (中韩芯片) [ETF]-日均成交额：59.37亿元-上市日期：2022-12-22
        '159518.XSHE',  # (标普油气ETF嘉实) [ETF]-日均成交额：27.93亿元-上市日期：2023-11-15
        '159509.XSHE',  # (纳指科技ETF景顺) [ETF]-日均成交额：7.24亿元-上市日期：2023-08-08
        '513100.XSHG',  # (纳指ETF) [ETF]-日均成交额：5.02亿元-上市日期：2013-05-15
        '513520.XSHG',  # (日经ETF) [ETF]-日均成交额：3.72亿元-上市日期：2019-06-25
        '513500.XSHG',  # (标普500) [ETF]-日均成交额：2.89亿元-上市日期：2014-01-15
        '159502.XSHE',  # (标普生物科技ETF嘉实) [ETF]-日均成交额：1.80亿元-上市日期：2024-01-10
        '513400.XSHG',  # (道琼斯) [ETF]-日均成交额：1.70亿元-上市日期：2024-02-02
        '513030.XSHG',  # (德国ETF) [ETF]-日均成交额：0.95亿元-上市日期：2014-09-05
        '513290.XSHG',  # (纳指生物) [ETF]-日均成交额：0.78亿元-上市日期：2022-08-29
        '520830.XSHG',  # (沙特ETF) [ETF]-日均成交额：0.62亿元-上市日期：2024-07-16
        '159529.XSHE',  # (标普消费ETF景顺) [ETF]-日均成交额：0.50亿元-上市日期：2024-02-02
    ]
    # 中国ETF池（含港股、指数、行业ETF）
    g.china_etf_pool = [
#港股ETF：
        '513090.XSHG',  # (香港证券) [ETF]-日均成交额：54.24亿元-上市日期：2020-03-26
        '513120.XSHG',  # (HK创新药) [ETF]-日均成交额：52.34亿元-上市日期：2022-07-12
        '513180.XSHG',  # (恒指科技) [ETF]-日均成交额：36.66亿元-上市日期：2021-05-25
        '513330.XSHG',  # (恒生互联) [ETF]-日均成交额：20.45亿元-上市日期：2021-02-08
        '513750.XSHG',  # (港股非银) [ETF]-日均成交额：9.55亿元-上市日期：2023-11-27
        '159892.XSHE',  # (恒生医药ETF华夏) [ETF]-日均成交额：7.90亿元-上市日期：2021-10-19
        '513190.XSHG',  # (H股金融) [ETF]-日均成交额：3.74亿元-上市日期：2023-10-11
        '159605.XSHE',  # (中概互联ETF广发) [ETF]-日均成交额：3.19亿元-上市日期：2021-12-02
        '513630.XSHG',  # (香港红利) [ETF]-日均成交额：2.84亿元-上市日期：2023-12-08
        '159323.XSHE',  # (港股通汽车ETF华夏) [ETF]-日均成交额：1.98亿元-上市日期：2025-01-08
        '510900.XSHG',  # (恒生中国) [ETF]-日均成交额：1.46亿元-上市日期：2012-10-22
        '513920.XSHG',  # (央企40) [ETF]-日均成交额：1.38亿元-上市日期：2024-01-05
        '513970.XSHG',  # (恒生消费) [ETF]-日均成交额：0.82亿元-上市日期：2023-04-21
#指数ETF：        
        '511380.XSHG',  # (转债ETF) [ETF]-日均成交额：115.92亿元-上市日期：2020-04-07
        '512050.XSHG',  # (A500E) [ETF]-日均成交额：48.05亿元-上市日期：2024-11-15
        '510500.XSHG',  # (500ETF) [ETF]-日均成交额：45.45亿元-上市日期：2013-03-15
        '159915.XSHE',  # (创业板ETF易方达) [ETF]-日均成交额：43.55亿元-上市日期：2011-12-09
        '510300.XSHG',  # (300ETF) [ETF]-日均成交额：34.60亿元-上市日期：2012-05-28
        '512100.XSHG',  # (1000ETF) [ETF]-日均成交额：25.26亿元-上市日期：2016-11-04
        '159949.XSHE',  # (创业板50ETF华安) [ETF]-日均成交额：16.52亿元-上市日期：2016-07-22
        '588080.XSHG',  # (科创板50) [ETF]-日均成交额：13.32亿元-上市日期：2020-11-16
        '159967.XSHE',  # (创业板成长ETF华夏) [ETF]-日均成交额：5.29亿元-上市日期：2019-07-15
        '588220.XSHG',  # (科创100F) [ETF]-日均成交额：5.01亿元-上市日期：2023-09-15
        '563300.XSHG',  # (中证2000) [ETF]-日均成交额：4.13亿元-上市日期：2023-09-14
        '510760.XSHG',  # (上证ETF) [ETF]-日均成交额：1.45亿元-上市日期：2020-09-09
#行业ETF：
        '588200.XSHG',  # (科创芯片) [ETF]-日均成交额：28.07亿元-上市日期：2022-10-26
        '515880.XSHG',  # (通信ETF) [ETF]-日均成交额：22.39亿元-上市日期：2019-09-06
        '159981.XSHE',  # (能源化工ETF建信) [ETF]-日均成交额：21.63亿元-上市日期：2020-01-17
        '512880.XSHG',  # (证券ETF) [ETF]-日均成交额：16.21亿元-上市日期：2016-08-08
        '513350.XSHG',  # (油气ETF) [ETF]-日均成交额：15.66亿元-上市日期：2023-11-28
        '159326.XSHE',  # (电网设备ETF华夏) [ETF]-日均成交额：14.86亿元-上市日期：2024-09-09
        '159516.XSHE',  # (半导体设备ETF国泰) [ETF]-日均成交额：14.23亿元-上市日期：2023-07-27
        '159206.XSHE',  # (卫星ETF永赢) [ETF]-日均成交额：13.87亿元-上市日期：2025-03-14
        '512480.XSHG',  # (半导体) [ETF]-日均成交额：13.07亿元-上市日期：2019-06-12
        '159363.XSHE',  # (创业板人工智能ETF华宝) [ETF]-日均成交额：10.50亿元-上市日期：2024-12-16
        '159870.XSHE',  # (化工ETF鹏华) [ETF]-日均成交额：10.03亿元-上市日期：2021-03-03
        '512400.XSHG',  # (有色ETF) [ETF]-日均成交额：9.97亿元-上市日期：2017-09-01
        '159755.XSHE',  # (电池ETF广发) [ETF]-日均成交额：8.58亿元-上市日期：2021-06-24
        '588170.XSHG',  # (科创半导) [ETF]-日均成交额：7.74亿元-上市日期：2025-04-08
        '159992.XSHE',  # (创新药ETF银华) [ETF]-日均成交额：7.59亿元-上市日期：2020-04-10
        '159995.XSHE',  # (芯片ETF华夏) [ETF]-日均成交额：7.51亿元-上市日期：2020-02-10
        '512890.XSHG',  # (红利低波) [ETF]-日均成交额：6.79亿元-上市日期：2019-01-18
        '515220.XSHG',  # (煤炭ETF) [ETF]-日均成交额：6.44亿元-上市日期：2020-03-02
        '159566.XSHE',  # (储能电池ETF易方达) [ETF]-日均成交额：6.31亿元-上市日期：2024-02-08
        '159819.XSHE',  # (人工智能ETF易方达) [ETF]-日均成交额：6.26亿元-上市日期：2020-09-23
        '512800.XSHG',  # (银行ETF) [ETF]-日均成交额：6.13亿元-上市日期：2017-08-03
        '512690.XSHG',  # (酒ETF) [ETF]-日均成交额：5.99亿元-上市日期：2019-05-06
        '515050.XSHG',  # (5GETF) [ETF]-日均成交额：5.93亿元-上市日期：2019-10-16
        '562500.XSHG',  # (机器人) [ETF]-日均成交额：5.83亿元-上市日期：2021-12-29
        '512170.XSHG',  # (医疗ETF) [ETF]-日均成交额：5.63亿元-上市日期：2019-06-17
        '517520.XSHG',  # (黄金股) [ETF]-日均成交额：5.01亿元-上市日期：2023-11-01
        '159869.XSHE',  # (游戏ETF华夏) [ETF]-日均成交额：4.77亿元-上市日期：2021-03-05
        '512070.XSHG',  # (证券保险) [ETF]-日均成交额：4.61亿元-上市日期：2014-07-18
        '159611.XSHE',  # (电力ETF广发) [ETF]-日均成交额：4.42亿元-上市日期：2022-01-07
        '562800.XSHG',  # (稀有金属) [ETF]-日均成交额：4.39亿元-上市日期：2021-09-27
        '515120.XSHG',  # (创新药) [ETF]-日均成交额：4.34亿元-上市日期：2021-01-04
        '512010.XSHG',  # (医药ETF) [ETF]-日均成交额：4.27亿元-上市日期：2013-10-28
        '510880.XSHG',  # (红利ETF) [ETF]-日均成交额：3.97亿元-上市日期：2007-01-18
        '515790.XSHG',  # (光伏ETF) [ETF]-日均成交额：3.87亿元-上市日期：2020-12-18
        '515980.XSHG',  # (人工智能) [ETF]-日均成交额：3.78亿元-上市日期：2020-02-10
        '512660.XSHG',  # (军工ETF) [ETF]-日均成交额：3.75亿元-上市日期：2016-08-08
        '159928.XSHE',  # (消费ETF汇添富) [ETF]-日均成交额：3.66亿元-上市日期：2013-09-16
        '512710.XSHG',  # (军工龙头) [ETF]-日均成交额：3.60亿元-上市日期：2019-08-26
        '560860.XSHG',  # (工业有色) [ETF]-日均成交额：3.57亿元-上市日期：2023-03-13
        '515030.XSHG',  # (新汽车) [ETF]-日均成交额：3.33亿元-上市日期：2020-03-04
        '159766.XSHE',  # (旅游ETF富国) [ETF]-日均成交额：3.30亿元-上市日期：2021-07-23
        '159218.XSHE',  # (卫星ETF招商) [ETF]-日均成交额：3.21亿元-上市日期：2025-05-22
        '159852.XSHE',  # (软件ETF嘉实) [ETF]-日均成交额：3.19亿元-上市日期：2021-02-09
        '516160.XSHG',  # (新能源) [ETF]-日均成交额：3.07亿元-上市日期：2021-02-04
        '516150.XSHG',  # (稀土基金) [ETF]-日均成交额：3.03亿元-上市日期：2021-03-17
        '159227.XSHE',  # (航空航天ETF华夏) [ETF]-日均成交额：2.98亿元-上市日期：2025-05-16
        '159583.XSHE',  # (通信ETF富国) [ETF]-日均成交额：2.93亿元-上市日期：2024-07-08
        '588790.XSHG',  # (科创智能) [ETF]-日均成交额：2.62亿元-上市日期：2025-01-09
        '159865.XSHE',  # (养殖ETF国泰) [ETF]-日均成交额：2.44亿元-上市日期：2021-03-08
        '512980.XSHG',  # (传媒ETF) [ETF]-日均成交额：2.43亿元-上市日期：2018-01-19
        '159851.XSHE',  # (金融科技ETF华宝) [ETF]-日均成交额：2.27亿元-上市日期：2021-03-19
        '561360.XSHG',  # (石油ETF) [ETF]-日均成交额：2.04亿元-上市日期：2023-10-31
        '561980.XSHG',  # (芯片设备) [ETF]-日均成交额：2.01亿元-上市日期：2023-09-01
        '562590.XSHG',  # (半导材料) [ETF]-日均成交额：1.76亿元-上市日期：2023-10-18
        '512200.XSHG',  # (地产ETF) [ETF]-日均成交额：1.71亿元-上市日期：2017-09-25
        '159732.XSHE',  # (消费电子ETF华夏) [ETF]-日均成交额：1.62亿元-上市日期：2021-08-23
        '159667.XSHE',  # (工业母机ETF国泰) [ETF]-日均成交额：1.58亿元-上市日期：2022-10-26
        '516510.XSHG',  # (云计算) [ETF]-日均成交额：1.49亿元-上市日期：2021-04-07
        '159840.XSHE',  # (锂电池ETF工银) [ETF]-日均成交额：1.42亿元-上市日期：2021-08-20
        '159998.XSHE',  # (计算机ETF天弘) [ETF]-日均成交额：1.30亿元-上市日期：2020-04-13
        '159825.XSHE',  # (农业ETF富国) [ETF]-日均成交额：1.15亿元-上市日期：2020-12-29
        '512670.XSHG',  # (国防ETF) [ETF]-日均成交额：1.12亿元-上市日期：2019-08-01
        '159883.XSHE',  # (医疗器械ETF永赢) [ETF]-日均成交额：1.05亿元-上市日期：2021-04-30
        '515210.XSHG',  # (钢铁ETF) [ETF]-日均成交额：1.01亿元-上市日期：2020-03-02
        '515400.XSHG',  # (大数据) [ETF]-日均成交额：0.94亿元-上市日期：2021-01-20
        '159256.XSHE',  # (创业板软件ETF华夏) [ETF]-日均成交额：0.83亿元-上市日期：2025-08-04
        '561330.XSHG',  # (矿业ETF) [ETF]-日均成交额：0.83亿元-上市日期：2022-11-01
        '515170.XSHG',  # (食品饮料) [ETF]-日均成交额：0.67亿元-上市日期：2021-01-13
        '159638.XSHE',  # (高端装备ETF嘉实) [ETF]-日均成交额：0.56亿元-上市日期：2022-08-12
        '516520.XSHG',  # (智能驾驶) [ETF]-日均成交额：0.47亿元-上市日期：2021-03-01
        '513360.XSHG',  # (教育ETF) [ETF]-日均成交额：0.43亿元-上市日期：2021-06-17
        '516190.XSHG',  # (文娱ETF) [ETF]-日均成交额：0.18亿元-上市日期：2021-09-17
    ]
    # 固定ETF池 = 全球池 + 中国池（正常期使用）
    g.fixed_etf_pool = g.global_etf_pool + g.china_etf_pool

    g.avg_etf_money_threshold = None
    g.filtered_fixed_pool = []
    g.dynamic_etf_pool = []
    g.merged_etf_pool = []
    g.ranked_etfs_result = []
    g.filtered_global_pool = []
    
    g.is_a_share_weak = False
    g.weak_period_ma_lookback = 10
    g.weak_start_date = None
    g.weak_days_count = 0
    g.max_weak_days = 20

    g.holdings_num = 1
    g.defensive_etf = "511880.XSHG"
    g.min_money = 10
    g.target_etfs_list = []
    g.pending_buy_etfs = []
    g.etf_names_dict = {}
    g.cache_date = None
    g.yesterday_close_cache = {}
    g.trend_lookback_minutes = 30
    g.trend_slope_threshold = 0.001
    g.trend_r2_threshold = 0.3

    g.lookback_days = 25
    g.min_score_threshold = 0
    g.max_score_threshold = 5
    g.score_threshold_ratio = 0.9

    g.enable_r2_filter = True
    g.r2_threshold = 0.4
    g.enable_ma_filter = True
    g.ma_lookback = 10
    g.ma_threshold = 1.0
    g.enable_volume_check = True
    g.volume_lookback = 5
    g.volume_threshold = 1.8
    g.enable_loss_filter = True
    g.loss = 0.97
    g.enable_premium_filter = False
    g.max_premium_rate = 30
    g.enable_laplace_filter = False  # ablation §8
    g.laplace_s_param = 0.05
    g.laplace_min_slope = 0.002
    g.dynamic_pool_top_n = 150  # ablation idea-7 §7
    g.liquidity_threshold_divisor = 15000

    g.max_portfolio_value = 0
    g.drawdown_threshold = 0.03
    g.drawdown_records = []
    
    g.use_fixed_stop_loss = False
    g.fixedStopLossThreshold = 0.95
    g.use_pct_stop_loss = False
    g.pct_stop_loss_threshold = 0.95

    # ==================== B型阶梯主线：极端高分前的早期识别 ====================
    # 目标不是追 score>20, 而是在 score 5~20 的早期阶段识别“通信ETF/卫星ETF”式
    # 连续主线趋势。该模型允许满足条件的 ETF 绕过 max_score_threshold=5。
    g.enable_super_mainline = True
    g.mainline_score_min = 5.0
    g.mainline_score_max = 20.0
    g.mainline_days = 5
    g.mainline_min_r2 = 0.85          # 当日 R² 仍要求高位
    g.mainline_min_r2_avg = 0.90      # 极严: 近 5 日趋势拟合质量必须持续高位
    g.mainline_min_volume_avg = 1.8   # 极严: 只接受持续放量的强主线
    g.mainline_min_score_up_days = 4  # 极严: 5 日内 score 必须 4/4 连续抬升
    g.mainline_min_positive_laplace_days = 5
    g.mainline_min_score_growth = 2.0 # 近 5 日 score 至少翻倍, 过滤小波段反弹

    # ==================== B型主线持仓延续 ====================
    # 已经被 B 型主线买入的 ETF, 若 score 突破 mainline_score_max 而原版又拒绝
    # (score > max_score_threshold=5), 默认会被强制踢出. 持仓延续规则避免这种
    # "主升浪正酣却被迫换仓"的情况.
    g.enable_mainline_retain = True
    g.mainline_retain_min_r2 = 0.85         # R² 仍要求高位, 趋势未走完
    g.mainline_retain_min_lap_slope = 0.0   # 拉普拉斯斜率仍为正

    # ==================== Regime P0：仅观测/record，不改交易 ====================
    g.enable_regime_p0 = True
    g.regime_breadth_ma = 20
    g.regime_breadth_high = 0.55
    g.regime_breadth_structural = 0.50
    g.regime_breadth_low = 0.35  # ABLATION: 45%→35%，配合 AND 条件（trend_weak 单独不触发 DEFENSIVE）
    g.regime_liquidity_min_yi = 20000.0
    g.regime_liquidity_lookback = 20
    g.regime_p0_log = []

    # ==================== 优化2：震荡市量价背离过滤 ====================
    g.enable_choppy_detection = True
    g.choppy_lookback = 10
    g.choppy_max_ret = 0.010
    g.is_choppy = False
    g.enable_volume_divergence_filter = True
    g.vd_lookback = 5            # 量价背离检测窗口
    g.vd_price_up_threshold = 0.02  # 价格涨幅>2%
    g.vd_vol_down_threshold = -0.10  # 成交量缩>10%

    # ==================== H72 动态走弱动量窗口 ====================
    g.weak_momentum_lookback = 25
    g.weak_momentum_lookback_base = 25
    g.weak_momentum_lookback_short = 23
    g.enable_dynamic_weak_lookback = True
    g.r2_lookback_for_signal_quality = 25
    g.r2_threshold_for_signal_quality = 0.4
    g.r2_threshold_exit = 0.38
    g.r2_hysteresis_enter_days = 2
    g.r2_hysteresis_exit_days = 2
    g.r2_signal_aggregation = "mean"
    g.r2_dynamic_tag = "H72"
    g.r2_high_streak = 0
    g.r2_low_streak = 0
    g.r2_dyn_days_23 = 0
    g.r2_dyn_days_25 = 0
    g.r2_dyn_switch_count = 0

    # ==================== H78a 走弱期 R² 过滤（方案B：保留 MA + R² 双过滤）====================
    g.enable_weak_r2_filter = True

    set_benchmark("510300.XSHG")
    run_daily(morning_routine, time='09:00')
    run_daily(check_weak_period_daily, time='09:40')
    run_daily(compute_regime_p0_daily, time='11:30')
    run_daily(afternoon_routine, time='13:10')
    run_daily(check_pending_buys_trend, time='13:40')
    run_daily(check_pending_buys_trend, time='14:10')
    run_daily(check_pending_buys_trend, time='14:40')
    run_daily(force_buy_pending, time='14:55')
    run_daily(reset_daily_flags, time='15:10')
    run_daily(minute_level_stop_loss, time='every_bar')
    run_daily(minute_level_pct_stop_loss, time='every_bar')
    
    log.info(f"""
【策略参数初始化完成】
=== ETF池配置 ===
- 全球/海外ETF池: {len(g.global_etf_pool)}只
- 国内ETF池: {len(g.china_etf_pool)}只
- 固定池合计: {len(g.fixed_etf_pool)}只
=== 大A走弱期判定 ===
- MA均线周期: {g.weak_period_ma_lookback}日
- 进入条件: 至少3/4指数低于MA{g.weak_period_ma_lookback}
- 退出条件: 至少3/4指数站上MA{g.weak_period_ma_lookback}
- 最长持续: {g.max_weak_days}个交易日
=== 动量得分过滤 ===
- 周期: {g.lookback_days}天
- 得分阈值: [{g.min_score_threshold}, {g.max_score_threshold}]
- 调仓系数: {g.score_threshold_ratio}
=== 过滤条件 ===
- 正常期 R²过滤: {'启用' if g.enable_r2_filter else '禁用'} (阈值>{g.r2_threshold:.1f})
- 走弱期 均线过滤: {'启用' if g.enable_ma_filter else '禁用'} (MA{g.ma_lookback}×{g.ma_threshold})
- 通用 成交量过滤: {'启用' if g.enable_volume_check else '禁用'} (近{g.volume_lookback}日均量比<{g.volume_threshold:.1f})
- 通用 短期风控: {'启用' if g.enable_loss_filter else '禁用'} (近3日单日跌幅<{1-g.loss:.0%})
- 通用 溢价率过滤: {'启用' if g.enable_premium_filter else '禁用'} (阈值≤{g.max_premium_rate}%)
- 通用 拉普拉斯滤波: {'启用' if g.enable_laplace_filter else '禁用'} (s={g.laplace_s_param}, 斜率≥{g.laplace_min_slope})
=== 止损机制 ===
- 分钟级固定比例止损: {'启用' if g.use_fixed_stop_loss else '禁用'} (成本价×{g.fixedStopLossThreshold:.0%})
- 分钟级当日跌幅止损: {'启用' if g.use_pct_stop_loss else '禁用'} (昨收×{g.pct_stop_loss_threshold:.0%})
=== B型阶梯主线 (放宽版) ===
- 启用: {'是' if g.enable_super_mainline else '否'} | score区间({g.mainline_score_min},{g.mainline_score_max}]
- 近{g.mainline_days}日: R²当前≥{g.mainline_min_r2}, R²均值≥{g.mainline_min_r2_avg}, 量比均值≥{g.mainline_min_volume_avg}
- 近{g.mainline_days}日: score抬升天数≥{g.mainline_min_score_up_days}/{g.mainline_days-1}, 拉普拉斯斜率为正天数≥{g.mainline_min_positive_laplace_days}/{g.mainline_days}
- 近{g.mainline_days}日: score增长倍数≥{g.mainline_min_score_growth}
- 第一步打分行后会追加 [主线诊断] 行, 显示每只 score>5 ETF 卡在哪个条件
=== B型主线持仓延续 ===
- 启用: {'是' if getattr(g, 'enable_mainline_retain', False) else '否'} | 触发条件: 当前持仓 + score>{g.mainline_score_max}
- 保留条件: R²≥{g.mainline_retain_min_r2}, 拉普拉斯斜率>{g.mainline_retain_min_lap_slope}, 其余 (loss/premium/弱市MA) 仍生效
=== 其他配置 ===
- 持仓数量: {g.holdings_num}只
- 防御ETF: {g.defensive_etf}
- 最小交易额: {g.min_money}元
- 基准: 510300.XSHG
""")


def check_weak_period_daily(context):
    check_a_share_weak_period(context)
    if getattr(g, 'enable_choppy_detection', False):
        check_choppy_market(context)
    midday_routine(context)


def check_choppy_market(context):
    """检测4大指数是否处于窄幅震荡（近10日涨跌幅<3%）。"""
    if not getattr(g, 'enable_choppy_detection', False):
        return
    indexes = ['000300.XSHG', '399101.XSHE', '399006.XSHE', '000510.XSHG']
    choppy_count = 0
    details = []
    for code in indexes:
        try:
            df = attribute_history(code, g.choppy_lookback + 1, '1d', ['close'], skip_paused=False)
            if df is None or len(df) < g.choppy_lookback + 1:
                details.append(f"{code}:数据不足")
                continue
            ret_10d = float(df['close'].iloc[-1] / df['close'].iloc[0] - 1)
            details.append(f"{code}:{ret_10d:+.2%}")
            if abs(ret_10d) < g.choppy_max_ret:
                choppy_count += 1
        except Exception:
            details.append(f"{code}:异常")
    was_choppy = bool(getattr(g, 'is_choppy', False))
    g.is_choppy = (choppy_count >= 3)
    if g.is_choppy and not was_choppy:
        log.info(f"🟡 【震荡市检测】{choppy_count}/4 指数近10日涨跌幅<{g.choppy_max_ret:.0%}，进入震荡模式 | {', '.join(details)}")
    elif not g.is_choppy and was_choppy:
        log.info(f"🟢 【震荡市检测】退出震荡模式 | {', '.join(details)}")


def check_volume_price_divergence(hist_closes, hist_volumes, context):
    """检测近5日量价背离：价涨量缩。
    所有市场状态下启用（不限于震荡市）。
    返回 (passed, details_dict) 其中 passed=True 表示通过检查（无背离）。
    """
    if not getattr(g, 'enable_volume_divergence_filter', False):
        return True, {'reason': 'disabled'}
    if hist_closes is None or hist_volumes is None:
        return True, {'reason': 'no_data'}
    if len(hist_closes) < g.vd_lookback + 1 or len(hist_volumes) < g.vd_lookback + 1:
        return True, {'reason': 'insufficient_data'}
    try:
        price_change = float(hist_closes[-1] / hist_closes[-g.vd_lookback - 1] - 1)
        recent_vol = float(np.mean(hist_volumes[-3:]))
        earlier_vol = float(np.mean(hist_volumes[-g.vd_lookback - 1:-3]))
        if earlier_vol <= 0:
            return True, {'reason': 'earlier_vol_zero'}
        vol_change = float(recent_vol / earlier_vol - 1)
        is_divergence = (price_change > g.vd_price_up_threshold and vol_change < g.vd_vol_down_threshold)
        return (not is_divergence), {
            'price_change': price_change,
            'vol_change': vol_change,
            'is_divergence': is_divergence,
            'reason': 'divergence' if is_divergence else 'ok'
        }
    except Exception:
        return True, {'reason': 'error'}


def morning_routine(context):
    log.info("★" * 80)
    log.info("▶️ 【晨间流水线】启动...")
    log.info("【持仓检查】检查当前持仓状态...")
    check_positions(context)    
    log.info("【回撤监控】监控策略回撤...")
    monitor_drawdown(context)
    log.info("【流动性阈值】计算全市场ETF流动性阈值...")
    calculate_global_etf_threshold(context)
    log.info("⏸️ 【晨间流水线】执行完毕！")


def midday_routine(context):
    log.info("★" * 80)
    log.info("▶️ 【早盘流水线】启动...")
    
    if g.is_a_share_weak:
        log.info(f"🔴 【走弱期池更新】仅对全球/海外ETF池进行流动性过滤...")
        filter_global_pool_by_volume(context)
        log.info(f"【走弱期池更新完成】过滤后全球池: {len(g.filtered_global_pool)}只")
    else:
        log.info(f"🟢 【正常期池更新】执行动态池更新、固定池过滤、合并池...")
        log.info("【动态池更新】更新行业ETF动态池（各行业流动性最佳ETF）...")
        update_sector_pool(context)
        log.info("【固定池过滤】过滤固定ETF池流动性...")
        filter_fixed_pool_by_volume(context)
        log.info("【合并池】合并固定池与动态池...")
        daily_merge_etf_pools(context)
        log.info(f"【正常期池更新完成】合并池: {len(g.merged_etf_pool)}只")
    
    log.info("⏸️ 【早盘流水线】执行完毕！")


def afternoon_routine(context):
    log.info("▶️ 【午盘流水线】启动...")
    
    if g.is_a_share_weak:
        if hasattr(g, 'filtered_global_pool') and g.filtered_global_pool:
            g.merged_etf_pool = list(set(g.filtered_global_pool))
        else:
            g.merged_etf_pool = list(set(g.global_etf_pool))
        g.merged_etf_pool.sort()
        log.info(f"🔴 【大A走弱期】使用过滤后全球/海外ETF池，共{len(g.merged_etf_pool)}只")
    else:
        log.info(f"🟢 【大A正常期】使用合并池，共{len(g.merged_etf_pool)}只")
    
    log.info("【动量计算】计算ETF动量得分与排序...")
    calculate_and_log_ranked_etfs(context)
    log.info("【卖出执行】执行卖出操作...")
    execute_sell_trades(context)
    log.info("【买入执行】执行买入操作...")
    execute_buy_trades(context)
    log.info("⏸️ 【午盘流水线】执行完毕！")


def reset_daily_flags(context):
    g.cache_date = None
    g.yesterday_close_cache = {}
    g.pending_buy_etfs = []
    log.info("🔄 收盘缓存重置完成")



# ==================== R²动态走弱动量窗口 H72 enter=2/exit=2 ====================
def adjust_weak_momentum_lookback(context):
    if not getattr(g, "enable_dynamic_weak_lookback", False):
        return
    try:
        etf_pool = g.global_etf_pool
        if not etf_pool:
            return
        lookback_days = g.r2_lookback_for_signal_quality
        end_date = context.previous_date
        r2_values = []
        for etf in etf_pool:
            try:
                df = get_price(
                    etf, end_date=end_date, count=lookback_days + 1,
                    frequency="daily", fields=["close"], panel=False,
                )
                if df is None or df.empty or len(df) < lookback_days + 1:
                    continue
                price_series = df["close"].values
                y = np.log(price_series)
                x = np.arange(len(y))
                weights = np.linspace(1, 2, len(y))
                W = weights ** 2
                W_sum = np.sum(W)
                x_bar = np.sum(W * x) / W_sum
                y_bar = np.sum(W * y) / W_sum
                dx = x - x_bar
                dy = y - y_bar
                variance_x = np.sum(W * dx ** 2)
                if variance_x == 0:
                    continue
                slope = np.sum(W * dx * dy) / variance_x
                intercept = y_bar - slope * x_bar
                y_pred = slope * x + intercept
                ss_res = np.sum(weights * (y - y_pred) ** 2)
                ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
                r_squared = 1 - ss_res / ss_tot if ss_tot else 0
                r2_values.append(r_squared)
            except Exception:
                continue
        if not r2_values:
            return

        agg = getattr(g, "r2_signal_aggregation", "mean")
        if agg == "median":
            pool_r2 = float(np.median(r2_values))
        else:
            pool_r2 = float(np.mean(r2_values))
        thr_hi = g.r2_threshold_for_signal_quality
        thr_lo = getattr(g, "r2_threshold_exit", 0.38)
        need_enter = int(getattr(g, "r2_hysteresis_enter_days", 2))
        need_exit = int(getattr(g, "r2_hysteresis_exit_days", 2))
        tag = getattr(g, "r2_dynamic_tag", "H72")

        if pool_r2 > thr_hi:
            g.r2_high_streak = getattr(g, "r2_high_streak", 0) + 1
            g.r2_low_streak = 0
        elif pool_r2 < thr_lo:
            g.r2_low_streak = getattr(g, "r2_low_streak", 0) + 1
            g.r2_high_streak = 0
        else:
            g.r2_high_streak = 0
            g.r2_low_streak = 0

        old_lookback = g.weak_momentum_lookback
        new_lookback = old_lookback
        reason = "hold"
        if old_lookback == g.weak_momentum_lookback_base and g.r2_high_streak >= need_enter:
            new_lookback = g.weak_momentum_lookback_short
            reason = "enter_23"
        elif old_lookback == g.weak_momentum_lookback_short and g.r2_low_streak >= need_exit:
            new_lookback = g.weak_momentum_lookback_base
            reason = "exit_23"

        switched = new_lookback != old_lookback
        if switched:
            g.weak_momentum_lookback = new_lookback
            g.r2_dyn_switch_count = getattr(g, "r2_dyn_switch_count", 0) + 1

        if g.weak_momentum_lookback == g.weak_momentum_lookback_short:
            g.r2_dyn_days_23 = getattr(g, "r2_dyn_days_23", 0) + 1
        else:
            g.r2_dyn_days_25 = getattr(g, "r2_dyn_days_25", 0) + 1

        if g.is_a_share_weak or switched:
            log.info(
                f"[R2动态{tag}] date={context.current_dt.date()} weak={int(g.is_a_share_weak)} "
                f"pool_r2={pool_r2:.4f} agg={agg} hi={g.r2_high_streak}/{need_enter} "
                f"lo={g.r2_low_streak}/{need_exit} reason={reason} "
                f"lb={g.weak_momentum_lookback} switched={int(switched)} "
                f"d23={getattr(g, 'r2_dyn_days_23', 0)} d25={getattr(g, 'r2_dyn_days_25', 0)} "
                f"sw={getattr(g, 'r2_dyn_switch_count', 0)}"
            )
            try:
                record(r2_avg=pool_r2, r2_weak_lb=float(g.weak_momentum_lookback))
            except Exception:
                pass
    except Exception as e:
        log.info(f"[R2动态{tag}] adjust 异常: {e}")

def check_positions(context):
    current_data = get_current_data()
    for security in context.portfolio.positions:
        position = context.portfolio.positions[security]
        if position.total_amount > 0:
            security_name = get_security_name(security)
            log.info(f"📊 【持仓检查】{security} {security_name}, 数量: {position.total_amount}, 成本: {position.avg_cost:.3f}, 当前价: {position.price:.3f}")
            if current_data[security].paused:
                log.info(f"⚠️ {security} {security_name} 今日停牌")


def monitor_drawdown(context):
    try:
        current_value = context.portfolio.total_value
        if current_value > g.max_portfolio_value:
            g.max_portfolio_value = current_value
        if g.max_portfolio_value > 0:
            current_drawdown = (g.max_portfolio_value - current_value) / g.max_portfolio_value
            if current_drawdown >= g.drawdown_threshold:
                record = {
                    'date': context.current_dt.strftime('%Y-%m-%d'),
                    'drawdown': current_drawdown,
                    'portfolio_value': current_value,
                    'max_value': g.max_portfolio_value,
                    'is_weak': g.is_a_share_weak
                }
                positions_info = []
                for security in context.portfolio.positions:
                    position = context.portfolio.positions[security]
                    if position.total_amount > 0:
                        security_name = get_security_name(security)
                        positions_info.append(f"{security_name}:{position.total_amount}股")
                record['positions'] = positions_info
                g.drawdown_records.append(record)
                log.info(f"【回撤预警】回撤达到 {current_drawdown:.2%} (阈值: {g.drawdown_threshold:.0%})")
                log.info(f"  当前净值: {current_value:,.0f}  |  最高净值: {g.max_portfolio_value:,.0f}")
                log.info(f"  大A状态: {'走弱期' if g.is_a_share_weak else '正常期'}")
                log.info(f"  持仓: {', '.join(positions_info) if positions_info else '空仓'}")
    except Exception as e:
        log.error(f"【回撤监控】计算异常: {e}")


def calculate_global_etf_threshold(context):
    log.info("【全局阈值更新】开始计算全市场ETF流动性门槛")
    try:
        df_etf = get_all_securities(['etf'], date=context.current_dt)
        etf_list = df_etf.index.tolist()
        if not etf_list:
            log.warning("未找到任何场内ETF，使用保守阈值1000万")
            g.avg_etf_money_threshold = 10000000
            return
        log.info(f"全市场ETF总数: {len(etf_list)}只")
        trade_days = get_trade_days(end_date=context.previous_date, count=3)
        start_day = trade_days[0]
        df = get_price(security=etf_list, start_date=start_day, end_date=context.previous_date, frequency='daily', fields=['money'], panel=False, skip_paused=True)
        if df is None or df.empty:
            log.warning("无法获取历史成交额数据，使用保守阈值1000万")
            g.avg_etf_money_threshold = 10000000
            return
        daily_totals = df.groupby('time')['money'].sum()
        daily_counts = df[df['money'] > 0].groupby('time')['code'].nunique()
        for day, money in daily_totals.items():
            count = daily_counts.get(day, 0)
            log.info(f"  {day.date()} 全市场ETF总成交额: {money/1e8:.2f}亿元 ({count}只ETF有成交)")
        if len(daily_totals) < 3:
            log.warning(f"仅有{len(daily_totals)}个有效交易日，使用保守阈值1000万")
            g.avg_etf_money_threshold = 10000000
            return
        avg_total_money = daily_totals.mean()
        threshold = avg_total_money / g.liquidity_threshold_divisor
        g.avg_etf_money_threshold = threshold
        log.info(f"【全局阈值更新完成】近{len(daily_totals)}日全市场ETF日均总成交额={avg_total_money/1e8:.2f}亿元，阈值={threshold/1e4:.0f}万元({threshold:,.0f}元)")
    except Exception as e:
        log.warning(f"计算全局阈值异常: {e}，使用保守阈值1000万")
        g.avg_etf_money_threshold = 10000000


def filter_global_pool_by_volume(context):
    log.info("【全球池过滤】开始执行")
    if getattr(g, 'avg_etf_money_threshold', None) is None:
        log.info("【全球池过滤】阈值未初始化，立即计算")
        calculate_global_etf_threshold(context)
    if not g.global_etf_pool:
        log.info("【全球池过滤】全球池为空，跳过过滤")
        g.filtered_global_pool = []
        return
    dynamic_threshold = g.avg_etf_money_threshold
    log.info(f"【全球池过滤】使用流动性门槛=日均{dynamic_threshold/1e4:.0f}万元")
    end_date = context.previous_date
    TRADE_DAYS_COUNT = 3
    try:
        price_data = get_price(g.global_etf_pool, end_date=end_date, count=TRADE_DAYS_COUNT, frequency='daily', fields=['money'], panel=False)
        if price_data is None or price_data.empty:
            log.warning("【全球池过滤】无法获取成交额数据，使用原始全球池")
            g.filtered_global_pool = g.global_etf_pool[:]
            return
        total_money = price_data.groupby('code')['money'].sum()
        avg_daily_money = total_money / TRADE_DAYS_COUNT
        qualified = avg_daily_money[avg_daily_money > dynamic_threshold]
        new_global_pool = qualified.index.tolist()
        removed = set(g.global_etf_pool) - set(new_global_pool)
        if removed:
            removed_info = []
            for code in removed:
                try:
                    name = getattr(g, 'etf_names_dict', {}).get(code, str(code))
                    money = avg_daily_money.get(code, 0)
                    removed_info.append(f"{name}({code}) {money/1e8:.2f}亿")
                except:
                    removed_info.append(code)
            log.info(f"【全球池过滤】剔除低流动性ETF({len(removed)}只)")
        g.filtered_global_pool = new_global_pool
        sorted_qualified = qualified.sort_values(ascending=False)
        log.info(f"【全球池过滤】保留高流动性ETF({len(new_global_pool)}只)")
    except Exception as e:
        log.warning(f"【全球池过滤】异常: {e}")
        g.filtered_global_pool = g.global_etf_pool[:]


def update_sector_pool(context):
    log.info("【动态池更新】开始执行")
    if g.avg_etf_money_threshold is None:
        log.info("【动态池更新】阈值未初始化，立即计算")
        calculate_global_etf_threshold(context)
    
    FUND_COMPANIES = sorted(list(set([
        '易方达', '广发', '华夏', '华安', '嘉实', '富国', '招商', '鹏华', '南方', '汇添富', '国泰', '平安',
        '银华', '天弘', '建信', '工银', '华泰柏瑞', '博时', '景顺长城', '景顺', '华宝', '申万菱信', '万家', '中欧',
        '兴证全球', '浙商', '诺安', '前海开源', '泰康', '泰达宏利', '农银汇理', '交银', '东方红', '财通', '华商',
        '国联', '永赢', '金鹰', '德邦', '创金合信', '西部利得', '圆信永丰', '泓德', '汇安', '诺德', '恒生前海',
        '华润元大', '大成', '海富通', '摩根', '华泰', '中信', '中银', '兴全', '国信', '长城', '中金', '浙商证券',
        '东海', '东吴', '浦银安盛', '信达澳亚', '中加', '中航', '中融', '中邮', '中庚', '中信保诚', '中信建投',
        '中银国际', '中银证券', '九泰', '交银施罗德', '光大保德信', '兴银', '农银', '国投瑞银', '国海富兰克林',
        '国联安', '国金', '太平', '方正富邦', '民生加银', '汇丰晋信', '银河', '长信', '长安', '长盛', '长江证券', '鹏扬'
    ])), key=len, reverse=True)
    
    NOISE_WORDS = sorted(list(set([
        '6666', '8888', '9999', 'A类', 'AH', 'B', 'BS', 'C', 'C类', 'CS', 'DB', 'E', 'E类',
        'ETF', 'ETF基金', 'ETF联接', 'FG', 'G60', 'GF', 'GT', 'HGS', 'LOF', 'LOF基金', 'LOF联接',
        'SG', 'SZ', 'TF', 'TK', 'WJ', 'YH', 'ZS', 'ZZ', '板块', '策略', '产业', '场内', '场外', '低波',
        '基本面', '基金', '精选', '联接', '联接基金', '量化', '龙头', '民企', '民营', '国企', '央企', '智能',
        '全指', '上市开放式', '指基', '指增', '指数', '指数A', '指数C', '指数ETF', '指数基金', '主题', '增强',
        '上海', '黄', '30', '50', '100', '300', '500', '1000', '2000', '大', '新', '四川', '浙江', '湖北',
    ])), key=len, reverse=True)
    
    SPECIAL_GROUPS = sorted([
        {'name': '香港组', 'keywords': sorted(['恒生', '恒指', '港股', '港股通', 'H股', '香港', '港', 'HKC', 'HK', 'HGS', 'H', '中概', 'HS科技'], key=len, reverse=True),
         'remove_words': sorted(['恒生', '恒指', '港股', '港股通', 'H股', '香港', '港', 'HKC', 'HK', 'HGS', 'H', '中概', 'HS'], key=len, reverse=True)},
        {'name': '科创组', 'keywords': sorted(['科创', '科创板', '科综', 'KC', 'K C', '双创', '科创创业', '创创'], key=len, reverse=True),
         'remove_words': sorted(['科创', '科创板', '科综', 'KC', 'K C', '双创', '科创创业', '创创', '债券', '债汇', '债指', '债沪', '债易', '债基', '债兴', '债摩', '债', 'AAA'], key=len, reverse=True)},
        {'name': '创业组', 'keywords': sorted(['创业板', '创业', '创板', '创成长'], key=len, reverse=True),
         'remove_words': sorted(['创业板', '创业', '创板', '创成长'], key=len, reverse=True)},
        {'name': '美指组', 'keywords': sorted(['标普', '纳指', '纳斯达克'], key=len, reverse=True),
         'remove_words': sorted(['标普', '纳指', '纳斯达克'], key=len, reverse=True)}
    ], key=lambda x: max(len(kw) for kw in x['keywords']), reverse=True)
    
    exclude_keywords = sorted(list(set([
        '300', '500', '1000', '2000', '800', '30', '50', '100', '180', '200',
        '沪深', '中证', '上证', '深证', '深成', 'A50', 'A100', 'A500', '深100',
        '短融', '可转债', '转债', '双债', '利率债', '国债', '地债', '政金债', '国开债', '基准国债', '新综债',
        '信用债', '企业债', '公司债', '城投债', '城投', '美元债', '沪公司债', '科创债', '科债', '科创AAA',
        '自由现金流', '现金流', '现金流E', '现金流基', '现金流TF', '现金流全', '300现金流', '800现金流',
        '货币', '现金', '快线', '快钱', '中银现金', '500现金', '800现金', '现金800', '现金自由', '现金指数',
        '全指现金', '现金全指', 'ESG', 'MSCI', 'MS', '债',
    ])), key=len, reverse=True)
    
    try:
        df_etf = get_all_securities(['etf'])
        etf_list = df_etf.index.tolist()
        g.etf_names_dict = df_etf['display_name'].to_dict()
    except Exception as e:
        log.warning(f"获取全市场ETF列表失败: {e}")
        return
    
    log.info(f"【动态池更新】全市场ETF总数: {len(etf_list)}只")
    normal_etfs = []
    special_etfs = []
    special_group_map = {}
    excluded_count = 0
    
    for code in etf_list:
        try:
            name = g.etf_names_dict.get(code, str(code))
            is_special = False
            matched_group = None
            for group in SPECIAL_GROUPS:
                for kw in group['keywords']:
                    if kw in name:
                        is_special = True
                        matched_group = group['name']
                        break
                if is_special:
                    break
            is_excluded = False
            for k in exclude_keywords:
                if k in name:
                    is_excluded = True
                    excluded_count += 1
                    break
            if not is_excluded:
                if is_special:
                    special_etfs.append(code)
                    special_group_map[code] = matched_group
                else:
                    normal_etfs.append(code)
        except Exception:
            continue
    
    group_counts = {}
    for code in special_etfs:
        group_name = special_group_map.get(code, '未知')
        group_counts[group_name] = group_counts.get(group_name, 0) + 1
    log.info(f"【动态池更新】特别组分布: {group_counts}")
    log.info(f"【动态池更新】进入特别组: {len(special_etfs)}只")
    log.info(f"【动态池更新】进入普通组: {len(normal_etfs)}只")
    log.info(f"【动态池更新】排除ETF: {excluded_count}只")
    
    end_date = context.previous_date
    TRADE_DAYS_COUNT = 3
    dynamic_threshold = g.avg_etf_money_threshold
    
    def filter_by_liquidity(etf_codes, group_name):
        if not etf_codes:
            return pd.Series(dtype=float), 0
        try:
            price_data = get_price(etf_codes, end_date=end_date, count=TRADE_DAYS_COUNT, frequency='daily', fields=['money'], panel=False)
            if price_data is None or price_data.empty:
                return pd.Series(dtype=float), len(etf_codes)
            total_money = price_data.groupby('code')['money'].sum()
            avg_daily_money = total_money / TRADE_DAYS_COUNT
            qualified_series = avg_daily_money[avg_daily_money > dynamic_threshold].sort_values(ascending=False)
            filtered_out = len(etf_codes) - len(qualified_series)
            return qualified_series, filtered_out
        except Exception:
            return pd.Series(dtype=float), len(etf_codes)
    
    normal_qualified, normal_filtered_out = filter_by_liquidity(normal_etfs, "普通组")
    special_qualified, special_filtered_out = filter_by_liquidity(special_etfs, "特别组")
    normal_sorted = normal_qualified.index.tolist()
    special_sorted = special_qualified.index.tolist()
    log.info(f"【动态池更新】特别组流动性过滤: {len(special_etfs)}→{len(special_sorted)}只")    
    log.info(f"【动态池更新】普通组流动性过滤: {len(normal_etfs)}→{len(normal_sorted)}只")
    
    if not normal_sorted and not special_sorted:
        log.warning("【动态池更新】无ETF通过流动性过滤")
        g.dynamic_etf_pool = []
        return
    
    def get_remove_words_for_etf(_, is_special, matched_group_name):
        if not is_special:
            return []
        for group in SPECIAL_GROUPS:
            if group['name'] == matched_group_name:
                return group['remove_words']
        return []
    
    def clean_name(original_name, is_special=False, matched_group_name=None):
        cleaned = original_name
        for company in FUND_COMPANIES:
            cleaned = cleaned.replace(company, '')
        if is_special and matched_group_name:
            for word in get_remove_words_for_etf(original_name, is_special, matched_group_name):
                cleaned = cleaned.replace(word, '')
        for noise in NOISE_WORDS:
            cleaned = cleaned.replace(noise, '')
        return cleaned.strip()
    
    normal_industry_groups = {}
    for code in normal_sorted:
        try:
            original_name = g.etf_names_dict.get(code, str(code))
            money = normal_qualified[code]
            cleaned = clean_name(original_name, is_special=False)
            if cleaned == '':
                continue
            industry_key = cleaned[:2] if len(cleaned) >= 2 else cleaned
            if industry_key not in normal_industry_groups:
                normal_industry_groups[industry_key] = []
            normal_industry_groups[industry_key].append({
                'code': code, 'original_name': original_name, 'cleaned_name': cleaned,
                'money': money, 'group_type': '普通'
            })
        except Exception:
            continue
    
    special_industry_groups = {}
    for code in special_sorted:
        try:
            original_name = g.etf_names_dict.get(code, str(code))
            matched_group = special_group_map.get(code, '未知')
            money = special_qualified[code]
            cleaned = clean_name(original_name, is_special=True, matched_group_name=matched_group)
            if cleaned == '':
                continue
            industry_key = cleaned[:2] if len(cleaned) >= 2 else cleaned
            group_key = f"{matched_group}_{industry_key}"
            if group_key not in special_industry_groups:
                special_industry_groups[group_key] = []
            special_industry_groups[group_key].append({
                'code': code, 'original_name': original_name, 'cleaned_name': cleaned,
                'money': money, 'group_type': matched_group, 'display_group': matched_group
            })
        except Exception:
            continue
    
    final_pool_info = []
    for industry_key, items in normal_industry_groups.items():
        sorted_items = sorted(items, key=lambda x: x['money'], reverse=True)
        final_pool_info.append(sorted_items[0])
    for group_key, items in special_industry_groups.items():
        sorted_items = sorted(items, key=lambda x: x['money'], reverse=True)
        final_pool_info.append(sorted_items[0])
    
    final_pool_info_sorted = sorted(final_pool_info, key=lambda x: x['money'], reverse=True)
    _top_n = getattr(g, 'dynamic_pool_top_n', 100)
    top_100 = final_pool_info_sorted[:_top_n]
    g.dynamic_etf_pool = [item['code'] for item in top_100]
    log.info(f"【动态池更新完成】动态池共{len(g.dynamic_etf_pool)}只ETF")
    if len(g.dynamic_etf_pool) <= 10:
        for item in top_100[:10]:
            log.info(f"  {item['code']} {item['original_name']} 日均成交额: {item['money']/1e8:.2f}亿")


def filter_fixed_pool_by_volume(context):
    log.info("【固定池过滤】开始执行")
    if getattr(g, 'avg_etf_money_threshold', None) is None:
        log.info("【固定池过滤】阈值未初始化，立即计算")
        calculate_global_etf_threshold(context)
    if not g.fixed_etf_pool:
        log.info("【固定池过滤】固定池为空，跳过过滤")
        return
    dynamic_threshold = g.avg_etf_money_threshold
    log.info(f"【固定池过滤】使用流动性门槛=日均{dynamic_threshold/1e4:.0f}万元")
    end_date = context.previous_date
    TRADE_DAYS_COUNT = 3
    try:
        price_data = get_price(g.fixed_etf_pool, end_date=end_date, count=TRADE_DAYS_COUNT, frequency='daily', fields=['money'], panel=False)
        if price_data is None or price_data.empty:
            log.warning("【固定池过滤】无法获取成交额数据，跳过过滤")
            g.filtered_fixed_pool = g.fixed_etf_pool[:]
            return
        total_money = price_data.groupby('code')['money'].sum()
        avg_daily_money = total_money / TRADE_DAYS_COUNT
        qualified = avg_daily_money[avg_daily_money > dynamic_threshold]
        new_fixed_pool = qualified.index.tolist()
        removed = set(g.fixed_etf_pool) - set(new_fixed_pool)
        if removed:
            removed_info = []
            for code in removed:
                try:
                    name = getattr(g, 'etf_names_dict', {}).get(code, str(code))
                    money = avg_daily_money.get(code, 0)
                    removed_info.append(f"{name}({code}) {money/1e8:.2f}亿")
                except:
                    removed_info.append(code)
            log.info(f"【固定池过滤】剔除低流动性ETF({len(removed)}只)")
        g.filtered_fixed_pool = new_fixed_pool
        sorted_qualified = qualified.sort_values(ascending=False)
        log.info(f"【固定池过滤】保留高流动性ETF({len(new_fixed_pool)}只)")
    except Exception as e:
        log.warning(f"【固定池过滤】异常: {e}")
        g.filtered_fixed_pool = g.fixed_etf_pool[:]


def daily_merge_etf_pools(context):
    if not hasattr(g, 'filtered_fixed_pool'):
        g.filtered_fixed_pool = g.fixed_etf_pool[:]
    merged = list(set(g.filtered_fixed_pool + g.dynamic_etf_pool))
    merged.sort()
    log.info("【合并ETF池】开始执行")
    log.info(f"【合并池统计】固定池: {len(g.filtered_fixed_pool)}只, 动态池: {len(g.dynamic_etf_pool)}只, 合并后: {len(merged)}只")
    g.merged_etf_pool = merged


def calculate_and_log_ranked_etfs(context):
    if not hasattr(g, 'merged_etf_pool') or not g.merged_etf_pool:
        log.warning("【动量计算】合并池为空，无法计算")
        g.ranked_etfs_result = []
        return
    final_list = get_final_ranked_etfs(context)
    g.ranked_etfs_result = final_list


def calculate_momentum_score(price_series, lookback_days):
    if len(price_series) < lookback_days + 1:
        return None, None, None
    recent_price_series = price_series[-(lookback_days + 1):]
    y = np.log(recent_price_series)
    x = np.arange(len(y))
    weights = np.linspace(1, 2, len(y))
    W = weights ** 2
    W_sum = np.sum(W)
    x_bar = np.sum(W * x) / W_sum
    y_bar = np.sum(W * y) / W_sum
    dx = x - x_bar
    dy = y - y_bar
    variance_x = np.sum(W * dx**2)
    if variance_x == 0:
        return 0, 0, 0
    slope = np.sum(W * dx * dy) / variance_x
    intercept = y_bar - slope * x_bar
    annualized_returns = math.exp(slope * 250) - 1
    y_pred = slope * x + intercept
    ss_res = np.sum(weights * (y - y_pred) ** 2)
    ss_tot = np.sum(weights * (y - np.mean(y)) ** 2) 
    r_squared = 1 - ss_res / ss_tot if ss_tot else 0
    momentum_score = annualized_returns * r_squared
    return momentum_score, annualized_returns, r_squared


def get_series_ending_at(hist_closes, current_price, offset):
    """offset=0 为含当日实时价；offset=1 为昨天；offset=2 为前天。"""
    hist = np.asarray(hist_closes, dtype=float)
    if offset == 0:
        return np.append(hist, float(current_price))
    cut = offset - 1
    if cut == 0:
        return hist
    if len(hist) <= cut:
        return None
    return hist[:-cut]


def get_historical_volume_ratio(hist_volumes, offset, lookback_days):
    """offset=1 为昨天成交量 / 此前 lookback_days 日均量。"""
    try:
        vols = np.asarray(hist_volumes, dtype=float)
        idx = len(vols) - offset
        if idx <= 0 or idx >= len(vols):
            return None
        start = idx - lookback_days
        if start < 0:
            return None
        base = vols[start:idx]
        if len(base) < lookback_days or np.any(base <= 0) or np.any(np.isnan(base)):
            return None
        avg = np.mean(base)
        return vols[idx] / avg if avg > 0 else None
    except Exception:
        return None


def evaluate_super_mainline(hist_closes, hist_volumes, current_price, current_volume_ratio):
    """B型阶梯主线判断。

    识别特征：
    - 当前 score 仍在 (5, 20] 的早期区间；
    - 近 N 日 score 阶梯式抬升且增长倍数足够大；
    - R² 当前与均值都保持高位；
    - 近 N 日量比均值保持高位；
    - 拉普拉斯斜率持续为正。
    """
    if not getattr(g, 'enable_super_mainline', False):
        return False, {'reason': 'disabled'}
    days = int(getattr(g, 'mainline_days', 5))
    if hist_closes is None or hist_volumes is None:
        return False, {'reason': 'no_hist'}

    scores = []
    r2_values = []
    volume_ratios = []
    laplace_slopes = []

    # 按时间从旧到新排列，最后一个是当日。
    for offset in range(days - 1, -1, -1):
        series = get_series_ending_at(hist_closes, current_price, offset)
        if series is None or len(series) < int(g.lookback_days * 0.8):
            return False, {'reason': f'series_short@offset{offset}'}
        score, _, r2 = calculate_momentum_score(series, g.lookback_days)
        if score is None or r2 is None or pd.isna(score) or pd.isna(r2):
            return False, {'reason': f'score_nan@offset{offset}'}
        scores.append(score)
        r2_values.append(r2)

        try:
            lap_values = laplace_filter(series, s=g.laplace_s_param)
            lap_slope = lap_values[-1] - lap_values[-2] if len(lap_values) >= 2 else 0
        except Exception:
            lap_slope = 0
        laplace_slopes.append(lap_slope)

        if offset == 0:
            volume_ratios.append(current_volume_ratio)
        else:
            volume_ratios.append(get_historical_volume_ratio(hist_volumes, offset, g.volume_lookback))

    # 量比缺失自动 fallback: 仅当≥3 个有效值时, 用其均值填补 None/NaN
    vr_dump = []
    valid_vrs = []
    for v in volume_ratios:
        if v is None:
            vr_dump.append('None')
        elif pd.isna(v):
            vr_dump.append('NaN')
        else:
            vr_dump.append(f'{float(v):.2f}')
            valid_vrs.append(float(v))
    hist_vol_len = len(hist_volumes) if hist_volumes is not None else 0

    has_missing = len(valid_vrs) < len(volume_ratios)
    if has_missing:
        if len(valid_vrs) < 3:
            # 有效值太少, 仍判 False, 但带上完整诊断
            current_score = scores[-1] if scores else 0
            current_r2 = r2_values[-1] if r2_values else 0
            return False, {
                'reason': 'volume_none',
                'vr_dump': vr_dump,
                'hist_vol_len': hist_vol_len,
                'scores': scores, 'r2_values': r2_values,
                'volume_ratios': [None if v is None or pd.isna(v) else float(v) for v in volume_ratios],
                'laplace_slopes': laplace_slopes,
                'current_score': current_score, 'current_r2': current_r2,
                'r2_avg': float(np.mean(r2_values)) if r2_values else 0,
                'volume_avg': float(np.mean(valid_vrs)) if valid_vrs else 0,
                'score_up_days': sum(1 for i in range(1, len(scores)) if scores[i] >= scores[i - 1]),
                'positive_laplace_days': sum(1 for v in laplace_slopes if v > 0),
            }
        # ≥3 个有效, 用均值填补缺失
        fallback_v = float(np.mean(valid_vrs))
        volume_ratios = [fallback_v if (v is None or pd.isna(v)) else float(v) for v in volume_ratios]

    current_score = scores[-1]
    current_r2 = r2_values[-1]
    r2_avg = float(np.mean(r2_values))
    volume_avg = float(np.mean(volume_ratios))
    score_up_days = sum(1 for i in range(1, len(scores)) if scores[i] >= scores[i - 1])
    positive_laplace_days = sum(1 for v in laplace_slopes if v > 0)
    start_score = scores[0]
    if start_score > 0:
        score_growth = current_score / start_score
    else:
        score_growth = float('inf') if current_score > 0 else 0

    fails = []
    if not (g.mainline_score_min < current_score <= g.mainline_score_max):
        fails.append('score_range')
    if current_r2 < g.mainline_min_r2:
        fails.append('r2_cur')
    if r2_avg < g.mainline_min_r2_avg:
        fails.append('r2_avg')
    if volume_avg < g.mainline_min_volume_avg:
        fails.append('vol_avg')
    if score_up_days < g.mainline_min_score_up_days:
        fails.append('score_up')
    if positive_laplace_days < g.mainline_min_positive_laplace_days:
        fails.append('lap_pos')
    if score_growth < g.mainline_min_score_growth:
        fails.append('score_growth')
    passed = not fails

    reason_str = 'pass' if passed else '+'.join(fails)
    if has_missing and passed:
        reason_str = f'pass(vr_filled@{vr_dump.count("None") + vr_dump.count("NaN")})'

    return passed, {
        'scores': scores,
        'r2_values': r2_values,
        'volume_ratios': volume_ratios,
        'laplace_slopes': laplace_slopes,
        'current_score': current_score,
        'current_r2': current_r2,
        'r2_avg': r2_avg,
        'volume_avg': volume_avg,
        'score_up_days': score_up_days,
        'positive_laplace_days': positive_laplace_days,
        'score_growth': score_growth,
        'vr_dump': vr_dump,
        'hist_vol_len': hist_vol_len,
        'reason': reason_str,
    }


def calculate_all_metrics_for_etf(etf, etf_name, hist_closes, hist_volumes, current_price, today_vol, context):
    try:
        price_series = np.append(hist_closes, current_price)
        mom_lb = g.lookback_days
        if g.is_a_share_weak and getattr(g, "enable_dynamic_weak_lookback", False):
            mom_lb = g.weak_momentum_lookback
        if len(price_series) < mom_lb * 0.8:
            return None
        momentum_score, annualized_returns, r_squared = calculate_momentum_score(price_series, mom_lb)
        if momentum_score is None:
            return None
        passed_momentum = (g.min_score_threshold <= momentum_score <= g.max_score_threshold)
        volume_ratio = get_volume_ratio(hist_volumes, today_vol, context, g.volume_lookback)
        
        passed_loss_filter = True
        day_ratios = []
        if len(price_series) >= 4:
            day1 = price_series[-1] / price_series[-2]
            day2 = price_series[-2] / price_series[-3]
            day3 = price_series[-3] / price_series[-4]
            day_ratios = [day1, day2, day3]
            if min(day_ratios) < g.loss:
                passed_loss_filter = False
        
        passed_r2 = r_squared > g.r2_threshold
        
        passed_ma = True
        ma_value = None
        if len(price_series) >= g.ma_lookback:
            ma_value = np.mean(price_series[-g.ma_lookback:])
            passed_ma = current_price > ma_value * g.ma_threshold
        else:
            passed_ma = False
        
        premium_rate, passed_premium = calculate_premium_rate(etf, context)
        
        laplace_value = 0
        laplace_slope = 0
        passed_laplace = False
        if len(price_series) >= 10:
            try:
                laplace_values = laplace_filter(price_series, s=g.laplace_s_param)
                if len(laplace_values) >= 2:
                    laplace_value = laplace_values[-1]
                    laplace_slope = laplace_values[-1] - laplace_values[-2]
                    passed_laplace = (current_price > laplace_values[-1] and laplace_slope > g.laplace_min_slope)
            except Exception as e:
                pass

        passed_mainline, mainline_info = evaluate_super_mainline(hist_closes, hist_volumes, current_price, volume_ratio)
        
        # 优化2：震荡市量价背离检测
        passed_volume_divergence, vd_info = check_volume_price_divergence(hist_closes, hist_volumes, context)
        
        return {
            'etf': etf,
            'etf_name': etf_name,
            'momentum_score': momentum_score,
            'annualized_returns': annualized_returns,
            'r_squared': r_squared,
            'current_price': current_price,
            'volume_ratio': volume_ratio,
            'day_ratios': day_ratios,
            'premium_rate': premium_rate,
            'passed_momentum': passed_momentum,
            'passed_r2': passed_r2,
            'passed_ma': passed_ma,
            'passed_volume': volume_ratio is not None and volume_ratio < g.volume_threshold,
            'passed_loss': passed_loss_filter,
            'passed_premium': passed_premium,
            'ma_value': ma_value,
            'laplace_value': laplace_value,
            'laplace_slope': laplace_slope,
            'passed_laplace': passed_laplace,
            'passed_mainline': passed_mainline,
            'mainline_info': mainline_info,
            'passed_volume_divergence': passed_volume_divergence,
            'vd_info': vd_info,
        }
    except Exception as e:
        log.debug(f"【指标计算】{etf} {etf_name} 计算失败: {e}")
        return None


def get_volume_ratio(hist_volumes, today_vol, context, lookback_days=None):
    if lookback_days is None:
        lookback_days = g.volume_lookback
    try:
        if hist_volumes is None or len(hist_volumes) < lookback_days:
            return None
        past_n_days_vol = hist_volumes[-lookback_days:]
        if np.any(np.isnan(past_n_days_vol)) or np.any(past_n_days_vol == 0):
            return None
        avg_volume = np.mean(past_n_days_vol)
        if avg_volume == 0:
            return None
        now = context.current_dt
        elapsed_minutes = (now.hour - 9) * 60 + now.minute - 30
        if now.hour >= 13:
            elapsed_minutes -= 90
        elapsed_minutes = max(1, min(elapsed_minutes, 240))
        projected_today_vol = today_vol * (240.0 / elapsed_minutes)
        return projected_today_vol / avg_volume if avg_volume > 0 else 0
    except Exception:
        return None


def calculate_premium_rate(etf, context):
    try:
        etf_price = getattr(g, 'etf_yesterday_close_batch', {}).get(etf)
        if etf_price is None or pd.isna(etf_price):
            etf_price_df = get_price(etf, start_date=context.previous_date, end_date=context.previous_date, fields=['close'])
            if etf_price_df is None or len(etf_price_df) == 0:
                return None, False
            etf_price = etf_price_df['close'].iloc[-1]
        nav = getattr(g, 'etf_yesterday_nav_batch', {}).get(etf)
        if nav is None or pd.isna(nav):
            nav_df = get_extras('unit_net_value', etf, start_date=context.previous_date, end_date=context.previous_date)
            if nav_df is None or len(nav_df) == 0:
                return None, False
            nav = nav_df.iloc[-1].values[0]
        if nav <= 0 or pd.isna(nav):
            return None, False
        premium_rate = (etf_price - nav) / nav * 100
        passed_premium = premium_rate <= g.max_premium_rate
        return premium_rate, passed_premium
    except Exception as e:
        return None, True


def laplace_filter(price, s=0.05):
    alpha = 1 - np.exp(-s)
    L = np.zeros(len(price))
    L[0] = price[0]
    for t in range(1, len(price)):
        L[t] = alpha * price[t] + (1 - alpha) * L[t - 1]
    return L




def _compute_hs300_breadth(context):
    """沪深300成分股站上 MA20 比例（MA 用 T-1 及以前，现价用 11:30 intraday）。"""
    try:
        stocks = get_index_stocks('000300.XSHG', date=context.previous_date)
        if not stocks:
            return None
        stocks = list(stocks)
        w = int(getattr(g, 'regime_breadth_ma', 20))
        df = get_price(
            stocks,
            end_date=context.previous_date,
            count=w,
            frequency='daily',
            fields=['close'],
            panel=False,
            skip_paused=True,
        )
        if df is None or len(df) == 0:
            return None
        cur = get_current_data()
        above = 0
        total = 0
        for code in stocks:
            sub = df[df['code'] == code] if 'code' in df.columns else df[df.index == code]
            if sub is None or len(sub) < w:
                continue
            closes = sub['close'].values if 'close' in sub.columns else sub.values
            if len(closes) < w:
                continue
            ma = float(np.mean(closes[-w:]))
            px = cur[code].last_price if code in cur else float(closes[-1])
            if px is None or pd.isna(px) or ma <= 0:
                continue
            total += 1
            if px > ma:
                above += 1
        if total < 50:
            return None
        return float(above) / float(total)
    except Exception as e:
        log.debug(f"[RegimeP0] breadth error: {e}")
        return None


def _compute_market_liquidity_yi(context):
    """全市场流动性代理：上证+深证成指 20 日日均成交额（亿元）。"""
    try:
        lb = int(getattr(g, 'regime_liquidity_lookback', 20))
        idx = ['000001.XSHG', '399001.XSHE']
        df = get_price(
            idx,
            end_date=context.previous_date,
            count=lb,
            frequency='daily',
            fields=['money'],
            panel=False,
            skip_paused=True,
        )
        if df is None or len(df) == 0:
            return None
        if 'time' in df.columns:
            daily = df.groupby('time')['money'].sum()
        else:
            daily = df['money']
        if len(daily) == 0:
            return None
        return float(daily.mean()) / 1e8
    except Exception as e:
        log.debug(f"[RegimeP0] liquidity error: {e}")
        return None


def _compute_trend_votes(context):
    """与走弱期相同的四指数 MA10 投票（只读，不修改 g.is_a_share_weak）。"""
    indexes = {
        '大盘': '000300.XSHG',
        '小盘': '399101.XSHE',
        '创业板': '399006.XSHE',
        '中证A500': '000510.XSHG',
    }
    above_count = 0
    below_count = 0
    for name, code in indexes.items():
        df = attribute_history(code, g.weak_period_ma_lookback + 1, '1d', ['close'], skip_paused=False)
        if df is None or len(df) < g.weak_period_ma_lookback:
            continue
        current_price = df['close'][-1]
        ma_val = df['close'][-g.weak_period_ma_lookback:].mean()
        if current_price > ma_val:
            above_count += 1
        elif current_price < ma_val:
            below_count += 1
    return above_count, below_count


def _classify_regime_p0(above_count, below_count, breadth, liquidity_yi):
    """P0 三态：NORMAL / STRUCTURAL / DEFENSIVE（仅标签，不改池）。"""
    liq_min = float(getattr(g, 'regime_liquidity_min_yi', 20000.0))
    b_high = float(getattr(g, 'regime_breadth_high', 0.55))
    b_struct = float(getattr(g, 'regime_breadth_structural', 0.50))
    b_low = float(getattr(g, 'regime_breadth_low', 0.35))

    liquidity_ok = liquidity_yi is not None and liquidity_yi >= liq_min
    trend_ok = above_count >= 2
    trend_weak = below_count >= 3

    if breadth is not None and breadth < b_low:
        return 'DEFENSIVE', 2
    if not liquidity_ok:
        return 'DEFENSIVE', 2
    if trend_ok or (breadth is not None and breadth >= b_high):
        return 'NORMAL', 0
    if trend_weak and breadth is not None and breadth >= b_struct:
        return 'STRUCTURAL', 1
    # ABLATION: DEFENSIVE=width<low AND trend_weak（取消单独 trend_weak 触发）
    if trend_weak and breadth is not None and breadth < b_low:
        return 'DEFENSIVE', 2
    # trend_weak 但 width>=low → fall through to NORMAL
    return 'NORMAL', 0


def compute_regime_p0_daily(context):
    """11:30 环境评估：record + 结构化日志；P0 不改变交易。"""
    if not getattr(g, 'enable_regime_p0', False):
        return
    above_count, below_count = _compute_trend_votes(context)
    breadth = _compute_hs300_breadth(context)
    liquidity_yi = _compute_market_liquidity_yi(context)
    regime_name, regime_code = _classify_regime_p0(above_count, below_count, breadth, liquidity_yi)
    legacy_weak = bool(getattr(g, 'is_a_share_weak', False))
    mismatch = legacy_weak and regime_name in ('NORMAL', 'STRUCTURAL')

    entry = {
        'date': context.current_dt.strftime('%Y-%m-%d'),
        'regime': regime_name,
        'regime_code': regime_code,
        'breadth': None if breadth is None else round(breadth, 4),
        'liquidity_yi': None if liquidity_yi is None else round(liquidity_yi, 1),
        'trend_above': above_count,
        'trend_below': below_count,
        'legacy_weak': int(legacy_weak),
        'legacy_mismatch': int(mismatch),
    }
    g.regime_p0_log.append(entry)

    log.info(
        f"[REGIME_P0] {json.dumps(entry, ensure_ascii=False)}"
    )
    log.info(
        f"📊 【RegimeP0】{regime_name} | 宽度={entry['breadth']} 流动性={entry['liquidity_yi']}亿 "
        f"| 趋势 上/下={above_count}/{below_count} | 原走弱期={legacy_weak} "
        f"| 错配={'是' if mismatch else '否'}"
    )

    record(
        regime_p0=regime_code,
        breadth_p0=0.0 if breadth is None else float(breadth),
        liquidity_p0=0.0 if liquidity_yi is None else float(liquidity_yi),
        trend_below_p0=float(below_count),
        legacy_weak_p0=1.0 if legacy_weak else 0.0,
        regime_mismatch_p0=1.0 if mismatch else 0.0,
    )


def check_a_share_weak_period(context):
    today = context.current_dt.date()
    indexes = {
        '大盘': '000300.XSHG',
        '小盘': '399101.XSHE',
        '创业板': '399006.XSHE',
        '中证A500': '000510.XSHG'
    }
    
    above_count = 0
    below_count = 0
    for name, code in indexes.items():
        df = attribute_history(code, g.weak_period_ma_lookback + 1, '1d', ['close'], skip_paused=False)
        if df is None or len(df) < g.weak_period_ma_lookback:
            log.warning(f"📊 【走弱期判断】{name}({code})数据不足，跳过该指数")
            continue
        current_price = df['close'][-1]
        ma_val = df['close'][-g.weak_period_ma_lookback:].mean()
        is_above = current_price > ma_val
        is_below = current_price < ma_val
        if is_above:
            above_count += 1
        if is_below:
            below_count += 1
        status_emoji = "⬆️站上" if is_above else ("⬇️低于" if is_below else "➡️持平")
        log.info(f"📊 【走弱期判断】{name}({code}): 收盘{current_price:.2f} / MA{g.weak_period_ma_lookback} {ma_val:.2f} → {status_emoji}")
    
    weak_condition_met = (below_count >= 3)
    exit_condition_met = (above_count >= 3)
    log.info(f"📊 【走弱期判断】低于MA{g.weak_period_ma_lookback}: {below_count}/4, 站上MA{g.weak_period_ma_lookback}: {above_count}/4")
    
    if g.is_a_share_weak and g.weak_start_date is not None:
        g.weak_days_count = len(get_trade_days(start_date=g.weak_start_date, end_date=today))
    else:
        g.weak_days_count = 0
    max_days_exceeded = (g.weak_days_count >= g.max_weak_days)
    
    if g.is_a_share_weak:
        if max_days_exceeded:
            log.info(f"🔔 【走弱期退出】已达到最大持续天数{g.max_weak_days}个交易日，强制退出")
            g.is_a_share_weak = False
            g.weak_start_date = None
            g.weak_days_count = 0
        elif exit_condition_met:
            log.info(f"🟢 【走弱期退出】满足退出条件，退出走弱期")
            g.is_a_share_weak = False
            g.weak_start_date = None
            g.weak_days_count = 0
        elif weak_condition_met:
            old_start = g.weak_start_date
            g.weak_start_date = today
            g.weak_days_count = 0
            log.info(f"🟡 【走弱期延续】再次触发进入条件，重置计数器")
        else:
            log.info(f"🔴 【走弱期中】已持续{g.weak_days_count}/{g.max_weak_days}个交易日")
    else:
        if weak_condition_met:
            log.info(f"🔴 【走弱期进入】触发进入条件，进入大A走弱期")
            g.is_a_share_weak = True
            g.weak_start_date = today
            g.weak_days_count = 0
        else:
            log.info(f"🟢 【正常期中】未满足进入条件")
    
    status_emoji = "🔴" if g.is_a_share_weak else "🟢"
    status_str = f"{status_emoji} 最终状态: 走弱期={g.is_a_share_weak}"
    if g.is_a_share_weak:
        status_str += f" (已持续{g.weak_days_count}/{g.max_weak_days}个交易日)"
        record(走弱期状态=1)
    else:
        record(走弱期状态=0)
    log.info(f"📊 【走弱期判断】{status_str}")
    if getattr(g, "enable_dynamic_weak_lookback", False):
        adjust_weak_momentum_lookback(context)
    return g.is_a_share_weak
    
    
def apply_filters(metrics_list):
    # C06: 移植 V6.6 的强弱市过滤切换。
    # 正常期严格确认趋势，走弱期只留下动量和 R²，避免候选池被多重过滤筛空。
    if g.is_a_share_weak:
        steps = [
            ('动量得分', lambda m: m['passed_momentum'], True),
            ('R²', lambda m: m['passed_r2'], g.enable_r2_filter),
        ]
    else:
        steps = [
            ('动量得分', lambda m: m['passed_momentum'], True),
            ('R²', lambda m: m['passed_r2'], g.enable_r2_filter),
            ('均线', lambda m: m['passed_ma'], g.enable_ma_filter),
            ('成交量', lambda m: m['passed_volume'], g.enable_volume_check),
            ('短期风控', lambda m: m['passed_loss'], g.enable_loss_filter),
            ('溢价率', lambda m: m['passed_premium'], g.enable_premium_filter),
            ('拉普拉斯滤波', lambda m: m['passed_laplace'], g.enable_laplace_filter),
            ('量价背离', lambda m: m.get('passed_volume_divergence', True),
             g.enable_volume_divergence_filter and g.is_choppy),
        ]
    filtered = metrics_list[:]
    for name, condition, is_enabled in steps:
        if is_enabled:
            filtered = [m for m in filtered if condition(m)]
    return filtered


def get_final_ranked_etfs(context):
    all_metrics = []
    etf_set = list(g.merged_etf_pool)
    end_date = context.previous_date
    log.info(f"【动量得分计算】使用合并池，合计{len(etf_set)}只ETF")
    log.info(f"【当前状态】{'🔴 大A走弱期' if g.is_a_share_weak else '🟢 大A正常期'}")
    mom_lb = g.weak_momentum_lookback if (
        g.is_a_share_weak and getattr(g, "enable_dynamic_weak_lookback", False)
    ) else g.lookback_days
    lookback = max(mom_lb, g.volume_lookback, g.ma_lookback) + 20
    today = context.current_dt.date()
    current_data = get_current_data()
    safe_lookback = lookback + 20
    hist_df = get_price(etf_set, count=safe_lookback, end_date=end_date, frequency='1d', fields=['close', 'volume'], panel=False)
    today_vol_df = get_price(etf_set, start_date=today, end_date=context.current_dt, frequency='1m', fields=['volume'], panel=False, fill_paused=False)
    if hist_df is None or hist_df.empty:
        log.warning("【动量计算】无法获取历史价格数据")
        return []
    g.etf_yesterday_close_batch = {}
    g.etf_yesterday_nav_batch = {}
    try:
        y_price_df = get_price(etf_set, start_date=end_date, end_date=end_date, fields=['close'], panel=False)
        if y_price_df is not None and not y_price_df.empty:
            g.etf_yesterday_close_batch = y_price_df.groupby('code')['close'].last().to_dict()
        nav_df = get_extras('unit_net_value', etf_set, start_date=end_date, end_date=end_date)
        if nav_df is not None and not nav_df.empty:
            g.etf_yesterday_nav_batch = nav_df.iloc[-1].to_dict()
    except Exception as e:
        log.warning(f"【动量计算】批量获取溢价率数据异常: {e}")
    today_vols = today_vol_df.groupby('code')['volume'].sum() if (today_vol_df is not None and not today_vol_df.empty) else pd.Series(dtype=float)
    close_pivot = hist_df.pivot(index='time', columns='code', values='close')
    volume_pivot = hist_df.pivot(index='time', columns='code', values='volume')
    for etf in etf_set:
        if current_data[etf].paused:
            continue
        if etf not in close_pivot.columns:
            continue
        raw_closes = close_pivot[etf].values
        raw_volumes = volume_pivot[etf].values
        valid_mask = (~np.isnan(raw_volumes)) & (raw_volumes > 0)
        hist_closes = raw_closes[valid_mask]
        hist_volumes = raw_volumes[valid_mask]
        hist_closes = hist_closes[-lookback:]
        hist_volumes = hist_volumes[-lookback:]
        if len(hist_closes) < g.lookback_days:
            continue
        etf_name = get_security_name(etf)
        current_price = current_data[etf].last_price
        today_vol = today_vols.get(etf, 0)
        metrics = calculate_all_metrics_for_etf(etf, etf_name, hist_closes, hist_volumes, current_price, today_vol, context)
        if metrics:
            if metrics['etf'] in {m['etf'] for m in all_metrics}:
                continue
            all_metrics.append(metrics)
    for item in all_metrics:
        score = item.get('momentum_score')
        if pd.isna(score) or (isinstance(score, float) and np.isnan(score)):
            item['momentum_score'] = float('-inf')
    all_metrics.sort(key=lambda x: x.get('momentum_score', float('-inf')), reverse=True)
    log_buffer = []
    log_buffer.append("")
    log_buffer.append(">>> 第一步：所有ETF按动量得分从大到小排序 <<<")
    for m in all_metrics[:100]:
        def fmt_status(value_str, passed):
            return f"{value_str} {'✅' if passed else '❌'}"
        score_str = f"{m['momentum_score']:.4f}" if m['momentum_score'] != float('-inf') else "nan"
        r2_str = f"{m['r_squared']:.3f}" if not pd.isna(m['r_squared']) else "nan"
        vol_val = f"{m['volume_ratio']:.2f}" if m['volume_ratio'] is not None else "N/A"
        min_ratio = min(m['day_ratios']) if m['day_ratios'] else 'N/A'
        loss_val = f"{min_ratio:.4f}" if isinstance(min_ratio, float) and not pd.isna(min_ratio) else str(min_ratio)
        premium_str = f"{m['premium_rate']:.2f}%" if m['premium_rate'] is not None else "N/A"
        ma_str = f"MA{g.ma_lookback}: {m['ma_value']:.2f}" if m['ma_value'] is not None else "MA:N/A"
        line = (
            f"{m['etf']} {m['etf_name']}: "
            f"动量得分: {fmt_status(score_str, m['passed_momentum'])}，"
            f"R²: {fmt_status(r2_str, m['passed_r2'])}，"
            f"均线: {fmt_status(ma_str, m['passed_ma'])}，"
            f"成交量比值: {fmt_status(vol_val, m['passed_volume'])}，"
            f"短期风控: {fmt_status(loss_val, m['passed_loss'])}，"
            f"溢价率: {fmt_status(premium_str, m['passed_premium'])}，"
            f"拉普拉斯斜率: {m['laplace_slope']:.4f} {fmt_status('', m['passed_laplace'])}，"
            f"B型主线: {'✅' if m.get('passed_mainline') else '❌'}，"
            f"量价背离: {'✅' if m.get('passed_volume_divergence', True) else '❌'}"
        )
        log_buffer.append(line)
        if getattr(g, 'enable_super_mainline', False) and m.get('momentum_score', 0) > g.mainline_score_min:
            info = m.get('mainline_info', {}) or {}
            if info:
                line_d = (
                    f"    [主线诊断 {m['etf']}] reason={info.get('reason', 'n/a')} | "
                    f"score_cur={info.get('current_score', 0):.2f} "
                    f"r2_cur={info.get('current_r2', 0):.3f} "
                    f"r2_avg={info.get('r2_avg', 0):.3f} "
                    f"vol_avg={info.get('volume_avg', 0):.2f} "
                    f"up={info.get('score_up_days', 0)}/{g.mainline_days-1} "
                    f"lap+={info.get('positive_laplace_days', 0)}/{g.mainline_days} "
                    f"score_growth={info.get('score_growth', 0):.2f}"
                )
                vr_dump = info.get('vr_dump')
                if vr_dump:
                    line_d += f" | vr_list=[{', '.join(vr_dump)}] hist_vol_len={info.get('hist_vol_len', '?')}"
                log_buffer.append(line_d)
            else:
                log_buffer.append(f"    [主线诊断 {m['etf']}] info 为空 (评估提前返回)")
    filtered_list = apply_filters(all_metrics)
    if getattr(g, 'enable_super_mainline', False):
        normal_codes = {m['etf'] for m in filtered_list}
        mainline_list = [
            m for m in all_metrics
            if m.get('passed_mainline')
            and m['etf'] not in normal_codes
            and (not g.enable_loss_filter or m['passed_loss'])
            and (not g.enable_premium_filter or m['passed_premium'])
            and (not (g.enable_ma_filter and g.is_a_share_weak) or m['passed_ma'])
        ]
        filtered_list = filtered_list + mainline_list
        log_buffer.append("")
        log_buffer.append(
            f">>> B型阶梯主线：score在({g.mainline_score_min},{g.mainline_score_max}]且满足阶梯主线条件的ETF {len(mainline_list)}只 <<<"
        )
        for m in mainline_list[:15]:
            info = m.get('mainline_info', {})
            log_buffer.append(
                f"  {m['etf']} {m['etf_name']}: score={m['momentum_score']:.4f}, "
                f"R²当前={info.get('current_r2', 0):.3f}, R²均值={info.get('r2_avg', 0):.3f}, "
                f"量比均值={info.get('volume_avg', 0):.2f}, "
                f"score抬升={info.get('score_up_days', 0)}/{g.mainline_days-1}, "
                f"拉普拉斯正={info.get('positive_laplace_days', 0)}/{g.mainline_days}, "
                f"score增长={info.get('score_growth', 0):.2f}倍"
            )

        # ==================== B型主线持仓延续 ====================
        # 已在持仓中的 ETF, 即使 score 突破 mainline_score_max (主升浪爆发),
        # 只要趋势品质 (R²、拉普拉斯) + 风控 (loss / premium / 弱市MA) 都未破,
        # 仍保留在候选池里, 避免主升浪 ETF 因为 score 太高反而被踢出.
        retain_list = []
        if getattr(g, 'enable_mainline_retain', True):
            held_codes_set = {sec for sec, pos in context.portfolio.positions.items() if pos.total_amount > 0}
            already_codes = {m['etf'] for m in filtered_list}
            for m in all_metrics:
                if m['etf'] not in held_codes_set:
                    continue
                if m['etf'] in already_codes:
                    continue
                score_val = m.get('momentum_score', 0)
                if score_val is None or pd.isna(score_val):
                    continue
                if score_val <= g.mainline_score_max:
                    continue  # 未超天花板时不走这里, 走原版/普通主线即可
                r2_val = m.get('r_squared')
                lap_slope = m.get('laplace_slope', 0)
                if r2_val is None or pd.isna(r2_val) or r2_val < g.mainline_retain_min_r2:
                    continue
                if lap_slope is None or pd.isna(lap_slope) or lap_slope <= g.mainline_retain_min_lap_slope:
                    continue
                if g.enable_loss_filter and not m['passed_loss']:
                    continue
                if g.enable_premium_filter and not m['passed_premium']:
                    continue
                if g.enable_ma_filter and g.is_a_share_weak and not m['passed_ma']:
                    continue
                retain_list.append(m)
            if retain_list:
                for m in retain_list:
                    m['mainline_retained'] = True
                filtered_list = filtered_list + retain_list
                log_buffer.append("")
                log_buffer.append(
                    f">>> B型主线持仓延续：当前持仓中 score 已突破{g.mainline_score_max}但趋势品质仍达标的ETF {len(retain_list)}只 <<<"
                )
                for m in retain_list:
                    log_buffer.append(
                        f"  {m['etf']} {m['etf_name']}: score={m['momentum_score']:.4f}, "
                        f"R²={m['r_squared']:.3f}, 拉普拉斯斜率={m['laplace_slope']:.4f} "
                        f"→ 持仓延续保留"
                    )
    filtered_list.sort(key=lambda x: x.get('momentum_score', float('-inf')), reverse=True)
    top_10 = filtered_list[:10]
    log_buffer.append("")
    log_buffer.append(">>> 第二步：符合全部过滤条件的ETF按动量得分从大到小排序(前10名) <<<")
    if top_10:
        for m in top_10:
            def fmt_status(value_str, passed):
                return f"{value_str} {'✅' if passed else '❌'}"
            score_str = f"{m['momentum_score']:.4f}" if m['momentum_score'] != float('-inf') else "nan"
            r2_str = f"{m['r_squared']:.3f}" if not pd.isna(m['r_squared']) else "nan"
            vol_val = f"{m['volume_ratio']:.2f}" if m['volume_ratio'] is not None else "N/A"
            min_ratio = min(m['day_ratios']) if m['day_ratios'] else 'N/A'
            loss_val = f"{min_ratio:.4f}" if isinstance(min_ratio, float) and not pd.isna(min_ratio) else str(min_ratio)
            premium_str = f"{m['premium_rate']:.2f}%" if m['premium_rate'] is not None else "N/A"
            ma_str = f"MA{g.ma_lookback}: {m['ma_value']:.2f}" if m['ma_value'] is not None else "MA:N/A"
            line = (
                f"{m['etf']} {m['etf_name']}: "
                f"动量得分: {fmt_status(score_str, m['passed_momentum'])}，"
                f"R²: {fmt_status(r2_str, m['passed_r2'])}，"
                f"均线: {fmt_status(ma_str, m['passed_ma'])}，"
                f"成交量比值: {fmt_status(vol_val, m['passed_volume'])}，"
                f"短期风控: {fmt_status(loss_val, m['passed_loss'])}，"
                f"溢价率: {fmt_status(premium_str, m['passed_premium'])}，"
                f"拉普拉斯斜率: {m['laplace_slope']:.4f} {fmt_status('', m['passed_laplace'])}，"
                f"B型主线: {'✅' if m.get('passed_mainline') else '❌'}，"
                f"量价背离: {'✅' if m.get('passed_volume_divergence', True) else '❌'}"
            )
            log_buffer.append(line)
    else:
        log_buffer.append("（无符合条件的ETF）")
        full_log = "\n".join(log_buffer)
        log.info(full_log)
        return []
    score_key = 'momentum_score'
    if len(top_10) >= g.holdings_num:
        reference_score = top_10[g.holdings_num - 1].get(score_key, float('-inf'))
        ratio = g.score_threshold_ratio if not g.is_a_share_weak else 1.0
        score_threshold = reference_score * ratio
        log_buffer.append("")
        log_buffer.append(f">>> 第三步：选取动量得分≥第{g.holdings_num}名({top_10[g.holdings_num - 1]['etf_name']})得分{reference_score:.4f}×{g.score_threshold_ratio}={score_threshold:.4f}的ETF <<<")
        candidate_pool = [item for item in top_10 if item.get(score_key, float('-inf')) >= score_threshold]
    else:
        log_buffer.append("")
        log_buffer.append(f">>> 第三步：前10名不足{g.holdings_num}只，全部作为候选池 <<<")
        candidate_pool = top_10[:]
    log_buffer.append(f"【候选池】共{len(candidate_pool)}只ETF（按动量得分排序）：")
    for i, item in enumerate(candidate_pool):
        if item.get('mainline_retained'):
            tag = " [主线延续]"
        elif item.get('passed_mainline'):
            tag = " [B型主线]"
        else:
            tag = ""
        log_buffer.append(f"  {i+1}. {item['etf_name']}({item['etf']}) {score_key}: {item.get(score_key, 0):.4f}{tag}")
    log_buffer.append("")
    log_buffer.append(">>> 第四步：结合当前持仓进行调整 <<<")
    current_holdings = [sec for sec, pos in context.portfolio.positions.items() if pos.total_amount > 0]
    log_buffer.append(f"当前持仓ETF：{current_holdings}")
    candidate_dict = {item['etf']: item for item in candidate_pool}
    retained = [candidate_dict[etf] for etf in current_holdings if etf in candidate_dict]
    log_buffer.append(f"其中存在于候选池中的持仓ETF：{[item['etf'] for item in retained]}")
    if len(retained) >= g.holdings_num:
        retained_sorted = sorted(retained, key=lambda x: x.get(score_key, float('-inf')), reverse=True)
        final_result = retained_sorted[:g.holdings_num]
        log_buffer.append(f"保留的持仓ETF数量({len(retained)})超过目标持仓数({g.holdings_num})，将从保留的ETF中按动量得分取前{g.holdings_num}只作为最终目标。")
    else:
        need = g.holdings_num - len(retained)
        remaining_pool = [item for item in candidate_pool if item['etf'] not in {r['etf'] for r in retained}]
        additional = remaining_pool[:need]
        final_result = retained + additional
        log_buffer.append(f"保留持仓ETF {len(retained)}只，还需补充{need}只。")
        if retained:
            log_buffer.append("保留的ETF（按原有顺序）：")
            for item in retained:
                log_buffer.append(f"  {item['etf_name']}({item['etf']})")
        if additional:
            log_buffer.append("补充的ETF（按动量得分排序）：")
            for i, item in enumerate(additional):
                if item.get('mainline_retained'):
                    tag = " [主线延续]"
                elif item.get('passed_mainline'):
                    tag = " [B型主线]"
                else:
                    tag = ""
                log_buffer.append(f"  {i+1}. {item['etf_name']}({item['etf']}) {score_key}: {item.get(score_key, 0):.4f}{tag}")
    log_buffer.append(f"【最终目标】共{len(final_result)}只ETF：")
    for i, item in enumerate(final_result):
        if item.get('mainline_retained'):
            tag = " [主线延续]"
        elif item.get('passed_mainline'):
            tag = " [B型主线]"
        else:
            tag = ""
        log_buffer.append(f"  {i+1}. {item['etf_name']}({item['etf']}){tag}")
    log_buffer.append("==================================================")
    full_log = "\n".join(log_buffer)
    log.info(full_log)
    return final_result


def execute_sell_trades(context):
    log.info("========== 卖出操作开始 ==========")
    ranked_etfs = getattr(g, 'ranked_etfs_result', [])
    target_etfs = []
    
    if ranked_etfs:
        for metrics in ranked_etfs[:g.holdings_num]:
            target_etfs.append(metrics['etf'])
            log.info(f"确定最终目标: {metrics['etf']} {metrics['etf_name']}")
    else:
        if check_defensive_etf_available(context):
            target_etfs = [g.defensive_etf]
            etf_name = get_security_name(g.defensive_etf)
            log.info(f"🛡️ 确定最终目标(防御模式): {g.defensive_etf} {etf_name}")
        else:
            log.info("💤 无最终目标(空仓模式)")
            target_etfs = []
    
    g.target_etfs_list = target_etfs
    current_positions = list(context.portfolio.positions.keys())
    target_set = set(target_etfs)
    sell_count = 0
    
    for security in current_positions:
        position = context.portfolio.positions[security]
        if position.total_amount > 0 and security not in target_set:
            security_name = get_security_name(security)
            success = smart_order_target_value(security, 0, context)
            if success:
                sell_count += 1
                log.info(f"✅ 已成功卖出: {security} {security_name}")
    
    log.info(f"本次共计划卖出{sell_count}只ETF。")
    log.info("========== 卖出操作完成 ==========")


def execute_buy_trades(context):
    log.info("========== 买入操作开始（择时趋势判断）==========")
    g.pending_buy_etfs = []
    target_etfs = g.target_etfs_list
    
    if not target_etfs:
        log.info("根据计算的结果，今日无目标ETF，保持空仓")
        log.info("========== 买入操作完成 ==========")
        return
    
    current_positions = set(context.portfolio.positions.keys())
    etfs_to_buy = [etf for etf in target_etfs if etf not in current_positions]
    actual_holding_count = len(current_positions)
    max_buy_count = max(0, g.holdings_num - actual_holding_count)
    num_etfs_to_buy = min(len(etfs_to_buy), max_buy_count)
    
    if num_etfs_to_buy <= 0:
        log.info(f"当前实际持仓数量({actual_holding_count})已达到或超过目标({g.holdings_num})，无需买入")
        log.info("========== 买入操作完成 ==========")
        return
    
    etfs_to_buy = etfs_to_buy[:num_etfs_to_buy]
    log.info(f"当前实际持仓: {actual_holding_count}只, 目标持仓: {g.holdings_num}只, 本次计划买入: {num_etfs_to_buy}只")

    g.pending_buy_etfs = list(etfs_to_buy)
    log.info(f"计划买入ETF: {g.pending_buy_etfs}，先进行13:10趋势判断；若不满足，将在13:40/14:10/14:40复检，14:55强制买入")
    execute_buy_with_trend(context, force=False)

    if g.pending_buy_etfs:
        log.info(f"⏳ 等待趋势确认的ETF: {g.pending_buy_etfs}")

    log.info("========== 买入操作完成（择时趋势判断）==========")


def check_intraday_trend(security, context):
    """
    判断ETF盘中短期趋势。
    来源：五福5.2日内趋势准确版。用于择时执行层，不改变日线选股逻辑。
    注意：斜率必须使用原版“每分钟涨跌百分比”口径，才能匹配
    g.trend_slope_threshold = 0.001 这个阈值。
    """
    try:
        minute_data = get_price(
            security,
            end_date=context.current_dt,
            count=g.trend_lookback_minutes,
            frequency='1m',
            fields=['close'],
            skip_paused=False,
            fq='pre'
        )

        if minute_data is None or minute_data.empty:
            log.info(f"【趋势判断】{security} 无分钟数据，默认上涨趋势")
            return True

        closes = minute_data['close'].values
        closes = closes[closes > 0]
        if len(closes) < 5:
            log.info(f"【趋势判断】{security} 有效分钟数据不足({len(closes)}根)，默认没有上涨趋势")
            return False

        n = len(closes)
        x = np.arange(n)

        weights = np.linspace(0.5, 2.0, n)
        w = weights / weights.sum()
        x_bar = np.sum(w * x)
        y_bar = np.sum(w * closes)
        dx = x - x_bar
        dy = closes - y_bar
        variance_x = np.sum(w * dx**2)
        if variance_x == 0:
            slope = 0
        else:
            slope = np.sum(w * dx * dy) / variance_x

        mean_price = y_bar if y_bar > 0 else closes.mean()
        slope_pct = slope / mean_price * 100 if mean_price > 0 else 0

        y_pred = slope * x + (y_bar - slope * x_bar)
        ss_res = np.sum(w * (closes - y_pred)**2)
        ss_tot = np.sum(w * (closes - y_bar)**2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        passed_slope = slope_pct > g.trend_slope_threshold
        passed_r2 = r2 > g.trend_r2_threshold
        is_uptrend = passed_slope and passed_r2

        trend_desc = "上涨趋势确认" if is_uptrend else (
            "斜率不足" if not passed_slope else "趋势质量差(R²过低，假突破)" if not passed_r2 else "未知"
        )
        log.info(
            f"【趋势判断】{security} 最近{n}分钟 | "
            f"斜率={slope_pct:.6f}%/min(阈值{g.trend_slope_threshold}){'✓' if passed_slope else '✗'} | "
            f"R²={r2:.3f}(阈值{g.trend_r2_threshold}){'✓' if passed_r2 else '✗'} | "
            f"判定: {trend_desc}"
        )
        return is_uptrend

    except Exception as e:
        log.info(f"【趋势判断】{security} 异常: {e}，默认上涨趋势")
        return True


def execute_buy_with_trend(context, force=False):
    """
    带趋势判断的买入执行函数。
    force=False: 仅买入上涨趋势ETF，其余保留在待买列表。
    force=True: 14:55强制买入所有待买ETF。
    """
    if not g.pending_buy_etfs:
        return

    current_positions = set(context.portfolio.positions.keys())
    g.pending_buy_etfs = [etf for etf in g.pending_buy_etfs if etf not in current_positions]

    if not g.pending_buy_etfs:
        return

    current_time = context.current_dt.strftime('%H:%M')
    mode_desc = "强制买入" if force else "趋势判断"
    log.info(f"========== 买入操作开始（{mode_desc} {current_time}）==========")

    etfs_to_buy_now = []
    still_pending = []

    for etf in g.pending_buy_etfs:
        etf_name = get_security_name(etf)
        if force:
            etfs_to_buy_now.append(etf)
            log.info(f"⏰ {current_time} 强制买入 {etf} {etf_name}")
        else:
            if check_intraday_trend(etf, context):
                etfs_to_buy_now.append(etf)
                log.info(f"📈 {current_time} {etf} {etf_name} 趋势上涨，立即买入")
            else:
                still_pending.append(etf)
                log.info(f"📉 {current_time} {etf} {etf_name} 趋势未确认，等待下次判断")

    total_count = len(etfs_to_buy_now) + len(still_pending)
    for i, etf in enumerate(etfs_to_buy_now):
        remaining_cash = context.portfolio.available_cash
        if remaining_cash < g.min_money:
            log.info(f"可用现金 {remaining_cash:.2f} 不足最小交易额 {g.min_money:.2f}，停止买入")
            break
        
        remaining_to_buy = total_count - i
        target_value_for_this_etf = remaining_cash // remaining_to_buy
        
        # 最后一笔可使用剩余全部现金，但确保不小于最小交易额
        if target_value_for_this_etf < g.min_money and remaining_cash >= g.min_money:
            target_value_for_this_etf = remaining_cash
        
        etf_name = get_security_name(etf)
        log.info(f"为 {etf} {etf_name} 分配目标金额: {target_value_for_this_etf:.2f} 元 (剩余现金 {remaining_cash:.2f}, 总待买 {remaining_to_buy})")
        
        success = smart_order_target_value(etf, target_value_for_this_etf, context)
        if success:
            log.info(f"✅ ETF {etf} 下单成功")
        else:
            log.info(f"❌ ETF {etf} 下单失败")

    g.pending_buy_etfs = still_pending

    if still_pending:
        log.info(f"⏳ 仍待趋势确认的ETF: {still_pending}")
    else:
        log.info("✅ 所有待买ETF已处理完毕")

    log.info(f"========== 买入操作完成（{mode_desc}）==========")


def check_pending_buys_trend(context):
    """13:40/14:10/14:40 趋势复检：对待买ETF重新判断趋势。"""
    if not g.pending_buy_etfs:
        return
    log.info("★" * 80)
    log.info("▶️ 【趋势复检】检查待买ETF趋势...")
    execute_buy_with_trend(context, force=False)
    if g.pending_buy_etfs:
        log.info(f"⏳ 仍在等待的ETF: {g.pending_buy_etfs}")
    log.info("⏸️ 【趋势复检】执行完毕！")


def force_buy_pending(context):
    """14:55 强制买入所有剩余待买ETF，避免因择时过严导致整段行情空仓。"""
    if not g.pending_buy_etfs:
        return
    log.info("★" * 80)
    log.info("▶️ 【14:55强制买入】强制买入所有待买ETF...")
    execute_buy_with_trend(context, force=True)
    log.info("⏸️ 【14:55强制买入】执行完毕！")

def smart_order_target_value(security, target_value, context):
    current_data = get_current_data()
    security_name = get_security_name(security)

    # ========== 1. 买入初步资金检查（仅对买入操作） ==========
    if target_value > 0:
        available_cash = context.portfolio.available_cash
        if target_value > available_cash:
            target_value = available_cash
        if target_value < g.min_money:
            log.info(f"{security} {security_name}: 目标金额{target_value:.2f}小于最小交易额{g.min_money}，跳过")
            return False

    # ========== 2. 通用交易限制 ==========
    if current_data[security].paused:
        log.info(f"{security} {security_name}: 今日停牌，跳过交易")
        return False
    if current_data[security].last_price >= current_data[security].high_limit:
        log.info(f"{security} {security_name}: 当前涨停，跳过交易")
        return False
    if current_data[security].last_price <= current_data[security].low_limit:
        log.info(f"{security} {security_name}: 当前跌停，跳过交易")
        return False

    current_price = current_data[security].last_price
    if current_price == 0:
        log.info(f"{security} {security_name}: 当前价格为0，跳过交易")
        return False

    # ========== 3. 买入时使用预估成交价（包含佣金+滑点）计算股数 ==========
    # 佣金和滑点费率（买入方向）
    buy_commission_rate = 0.0001   # 买入佣金
    slippage_rate = 0.0001         # 滑点（价格相关滑点）
    estimated_price = current_price * (1 + buy_commission_rate + slippage_rate)
    
    if target_value > 0:
        # 用预估价格计算可买股数，确保实际花费不超可用现金
        target_amount = int(target_value / estimated_price)
        target_amount = (target_amount // 100) * 100
        if target_amount <= 0 and target_value > 0:
            target_amount = 100
        # 二次校验：用实时可用现金和当前价格严格限制（兜底）
        max_shares = int(context.portfolio.available_cash / current_price)
        max_shares = (max_shares // 100) * 100
        if max_shares < target_amount:
            log.info(f"{security} {security_name}: 现金可买{max_shares}股，原计划{target_amount}股，已调低")
            target_amount = max_shares
        if target_amount <= 0:
            log.info(f"{security} {security_name}: 现金不足买100股，跳过")
            return False
    else:
        # 卖出时不需要考虑资金，直接按目标数量0计算
        target_amount = 0

    # ========== 4. 获取当前持仓 ==========
    current_position = context.portfolio.positions.get(security, None)
    current_amount = current_position.total_amount if current_position else 0
    amount_diff = target_amount - current_amount
    trade_value = abs(amount_diff) * current_price

    # 小额交易过滤
    if 0 < trade_value < g.min_money:
        log.info(f"{security} {security_name}: 交易金额{trade_value:.2f}小于最小交易额{g.min_money}，跳过")
        return False

    # 卖出时检查可卖股数
    if amount_diff < 0:
        closeable_amount = current_position.closeable_amount if current_position else 0
        if closeable_amount == 0:
            log.info(f"{security} {security_name}: 当天买入不可卖出(T+1)")
            return False
        amount_diff = -min(abs(amount_diff), closeable_amount)

    # ========== 5. 执行下单 ==========
    if amount_diff != 0:
        order_result = order(security, amount_diff)
        if order_result:
            if amount_diff > 0:
                log.info(f"📦 买入{security} {security_name}，数量: {amount_diff}，价格: {current_price:.3f} (预估含成本价: {estimated_price:.3f})")
            else:
                log.info(f"📤 卖出{security} {security_name}，数量: {abs(amount_diff)}，价格: {current_price:.3f}")
            return True
        else:
            log.warning(f"下单失败: {security} {security_name}，数量: {amount_diff}")
            return False
    return False

def minute_level_stop_loss(context):
    if not g.use_fixed_stop_loss:
        return
    
    current_time = context.current_dt.strftime('%H:%M')
    if not (('09:25' < current_time < '11:30') or ('13:00' < current_time < '14:57')):
        return
    
    current_data = get_current_data()
    for security in list(context.portfolio.positions.keys()):
        position = context.portfolio.positions[security]
        if position.total_amount <= 0 or position.closeable_amount <= 0:
            continue
        
        current_price = current_data[security].last_price
        if current_price <= 0:
            continue
        
        cost_price = position.avg_cost
        if cost_price <= 0:
            continue
        
        if current_price <= cost_price * g.fixedStopLossThreshold:
            security_name = get_security_name(security)
            loss_percent = (current_price / cost_price - 1) * 100
            log.info(f"🚨 【分钟级固定止损】{security} {security_name} 触发止损，亏损: {loss_percent:.2f}%")
            smart_order_target_value(security, 0, context)


def minute_level_pct_stop_loss(context):
    if not g.use_pct_stop_loss:
        return
    
    current_time = context.current_dt.strftime('%H:%M')
    if not (('09:25' < current_time < '11:30') or ('13:00' < current_time < '14:57')):
        return
    
    current_data = get_current_data()
    current_date = context.current_dt.date()
    
    if not hasattr(g, 'cache_date') or g.cache_date != current_date:
        g.yesterday_close_cache = {}
        g.cache_date = current_date
    
    for security in list(context.portfolio.positions.keys()):
        position = context.portfolio.positions[security]
        if position.total_amount <= 0 or position.closeable_amount <= 0:
            continue
        
        yesterday_close = getattr(g, 'yesterday_close_cache', {}).get(security)
        if yesterday_close is None:
            try:
                close_series = attribute_history(security, 1, '1d', ['close'], skip_paused=False)
                if len(close_series['close']) == 0:
                    continue
                yesterday_close = close_series['close'][-1]
                if yesterday_close <= 0:
                    continue
                g.yesterday_close_cache[security] = yesterday_close
            except Exception:
                continue
        
        current_price = current_data[security].last_price
        if current_price <= 0:
            continue
        
        stop_price = yesterday_close * g.pct_stop_loss_threshold
        if current_price <= stop_price:
            security_name = get_security_name(security)
            daily_loss = (current_price / yesterday_close - 1) * 100
            log.info(f"🚨 【分钟级跌幅止损】{security} {security_name} 触发止损，当日跌幅: {daily_loss:.2f}%")
            smart_order_target_value(security, 0, context)


def get_security_name(security):
    try:
        if hasattr(g, 'etf_names_dict') and security in g.etf_names_dict:
            return g.etf_names_dict[security]
        return get_security_info(security).display_name
    except Exception:
        return "未知名称"


def check_defensive_etf_available(context):
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


def trade(context):
    pass
