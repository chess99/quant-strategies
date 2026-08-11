# 克隆自聚宽文章：https://www.joinquant.com/post/43083
# 标题：ETF轮动：年化收益82.68%，最大回撤13.54%
# 作者：小武子

# 克隆自聚宽文章：https://www.joinquant.com/post/42673
# 标题：【回顾3】ETF策略之核心资产轮动
# 作者：wywy1995

import numpy as np
import pandas as pd


#初始化函数 
def initialize(context):
    # 设定基准
    set_benchmark('000300.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 设置滑点 https://www.joinquant.com/view/community/detail/a31a822d1cfa7e83b1dda228d4562a70
    set_slippage(FixedSlippage(0.000))
    # 设置交易成本
    set_order_cost(OrderCost(open_tax=0, close_tax=0, open_commission=0.0002, close_commission=0.0002, close_today_commission=0, min_commission=5), type='fund')
    # 过滤一定级别的日志
    log.set_level('system', 'error')
    g.etf_pool = [
        '161725.XSHE', #白酒
        '159992.XSHE', #创新药
        '560080.XSHG', #中药
        '515700.XSHG', #新能源车 
        '515250.XSHG', #智能汽车
        '515790.XSHG', #光伏
        '515880.XSHG', #通信
        '159819.XSHE', #人工智能
        '512720.XSHG', #计算机（云计算，大数据）
        '159740.XSHE', #恒生科技
        '159985.XSHE', #豆粕
        '162411.XSHE', #华宝油气
        '518880.XSHG', #黄金ETF（大宗商品）
        '513100.XSHG', #纳指100（海外资产）
    ]
    g.m_days = 25 #动量参考天数
    run_daily(trade, '9:40') #每天运行确保即时捕捉动量变化


# 基于年化收益和判定系数打分的动量因子轮动 https://www.joinquant.com/post/26142
def get_rank(etf_pool):
    score_list = []
    for etf in etf_pool:
        df = attribute_history(etf, g.m_days, '1d', ['close'])
        y = df['log'] = np.log(df.close)   # `np.log()` 函数计算其对数。 这是因为对数收益率的变化更容易分析和理解。
        x = df['num'] = np.arange(df.log.size)  # 创建一个等差数列 `x`，其长度为 `df.log` 的长度，并将其存储在 `df.num` 列中。这是为了确保每个数据点都有一个对应的 x 值，以便进行线性回归分析。
        slope, intercept = np.polyfit(x, y, 1)  # 使用 `np.polyfit()` 函数对 `x` 和 `y` 进行线性回归分析，得到回归方程的斜率和截距。其中，`slope` 是斜率，`intercept` 是截距。
        annualized_returns = math.pow(math.exp(slope), 250) - 1  # 利用回归方程的斜率计算该股票的年化收益率。因为收盘价数据是每日的，所以需要将斜率指数化，然后将其减去1，再乘以250，得到年化收益率。
        r_squared = 1 - (sum((y - (slope * x + intercept))**2) / ((len(y) - 1) * np.var(y, ddof=1)))  # 计算回归方程的 R 平方值，用于衡量回归方程对数据的拟合程度。R 平方值越接近1，表示回归方程对数据的拟合越好
        score = annualized_returns * r_squared  
        score_list.append(score)
    df = pd.DataFrame(index=etf_pool, data={'score':score_list})
    df = df.sort_values(by='score', ascending=False)
    rank_list = list(df.index)    
    print(df)     
    record(白酒 = round(df.loc['161725.XSHE'], 2))
    record(创新药 = round(df.loc['159992.XSHE'], 2))
    record(中药 = round(df.loc['560080.XSHG'], 2))
    record(新能源车 = round(df.loc['515700.XSHG'], 2))
    record(智能汽车 = round(df.loc['515250.XSHG'], 2))
    record(光伏 = round(df.loc['515790.XSHG'], 2))
    record(通信 = round(df.loc['515880.XSHG'], 2))
    record(人工智能 = round(df.loc['159819.XSHE'], 2))
    record(计算机 = round(df.loc['512720.XSHG'], 2))
    record(恒生科技 = round(df.loc['159740.XSHE'], 2))
    record(豆粕 = round(df.loc['159985.XSHE'], 2))
    record(华宝油气 = round(df.loc['162411.XSHE'], 2))
    record(黄金 = round(df.loc['518880.XSHG'], 2))
    record(纳指 = round(df.loc['513100.XSHG'], 2))
    return rank_list

# 交易
def trade(context):
    # 获取动量最高的一只ETF
    target_num = 1    
    target_list = get_rank(g.etf_pool)[:target_num]
    # 卖出    
    hold_list = list(context.portfolio.positions)
    for etf in hold_list:
        if etf not in target_list:
            order_target_value(etf, 0)
            print('卖出' + str(etf))
        else:
            print('继续持有' + str(etf))
    # 买入
    hold_list = list(context.portfolio.positions)
    if len(hold_list) < target_num:
        value = context.portfolio.available_cash / (target_num - len(hold_list))
        for etf in target_list:
            if context.portfolio.positions[etf].total_amount == 0:
                order_target_value(etf, value)
                print('买入' + str(etf))

