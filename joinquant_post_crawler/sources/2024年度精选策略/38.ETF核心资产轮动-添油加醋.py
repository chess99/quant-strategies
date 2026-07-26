# 克隆自聚宽文章：https://www.joinquant.com/post/44046
# 标题：ETF核心资产轮动-添油加醋
# 作者：hayy

# 克隆自聚宽文章：https://www.joinquant.com/post/42673
# 标题：【回顾3】ETF策略之核心资产轮动
# 作者：wywy1995

import numpy as np
import pandas as pd


#初始化函数 
def initialize(context):
    # 设定基准
    set_benchmark('513100.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 设置滑点 https://www.joinquant.com/view/community/detail/a31a822d1cfa7e83b1dda228d4562a70
    set_slippage(FixedSlippage(0.002))
    # 设置交易成本
    set_order_cost(OrderCost(open_tax=0, close_tax=0, open_commission=0.0002, close_commission=0.0002, close_today_commission=0, min_commission=5), type='fund')
    # 过滤一定级别的日志
    log.set_level('system', 'error')
    # 参数
    g.etf_pool = [
        '518880.XSHG', #黄金ETF（大宗商品）
        '513100.XSHG', #纳指100（海外资产）
        '159915.XSHE', #创业板100（成长股，科技股，中小盘）
        '510180.XSHG', #上证180（价值股，蓝筹股，中大盘）
    ]
    g.m_days = 25 #动量参考天数
    run_daily(trade, '9:30') #每天运行确保即时捕捉动量变化


# 基于年化收益和判定系数打分的动量因子轮动 https://www.joinquant.com/post/26142
def get_rank(etf_pool):
    score_list = []
    for etf in etf_pool:
        #每只股票计算分数流程
        df = attribute_history(etf, g.m_days, '1d', ['close'])
        y = df['log'] = np.log(df.close)
        x = df['num'] = np.arange(df.log.size)
        slope, intercept = np.polyfit(x, y, 1)
        annualized_returns = math.pow(math.exp(slope), 250) - 1
        r_squared = 1 - (sum((y - (slope * x + intercept))**2) / ((len(y) - 1) * np.var(y, ddof=1)))
        score = annualized_returns * r_squared   # 运用线性回归算出来的年度收益率×R方
        
        #加入反转
        df2 = attribute_history(etf, g.m_days*8, '1d', ['close'])
        y2= df2['log'] = np.log(df2.close)
        x2 = df2['num'] = np.arange(df2.log.size)
        slope2, intercept2 = np.polyfit(x2, y2, 1)
        annualized_returns2 = math.pow(math.exp(slope2), 250) - 1
        r_squared2 = 1 - (sum((y2 - (slope2 * x2 + intercept2))**2) / ((len(y2) - 1) * np.var(y2, ddof=1)))
        
        score= score - annualized_returns2 * r_squared2 / 6
        
        score_list.append(score)
        
    df = pd.DataFrame(index=etf_pool, data={'score':score_list})
    df = df.sort_values(by='score', ascending=False) # 从大到小
    return df
    


# 交易
def trade(context):
    # 获取动量最高的一只ETF
    target_num = 1    
    rank_df = get_rank(g.etf_pool)
    c = max(list(rank_df.score)) - min(list(rank_df.score))
    if c < 15 and c>0.1 :
        target_list = list(rank_df.index)[0:target_num]
    else:
        target_list = []
    
    # rsrs择时
    real_target_list = []
    for etf in target_list:
        hl = attribute_history(etf, 18, '1d', ['high','low'])
        if np.polyfit(hl.low,hl.high,1)[0] > getBeta(context, etf) :
            real_target_list.append(etf)
    target_list = real_target_list
    
    # 卖出    
    hold_list = list(context.portfolio.positions)
    for etf in hold_list:
        if etf not in target_list:
            order_target_value(etf, 0)
            # print('卖出' + str(etf))
        # else:
            # print('继续持有' + str(etf))
    # 买入
    if len(target_list) != 0:
        hold_list = list(context.portfolio.positions)
        if len(hold_list) < target_num:
            value = context.portfolio.available_cash / (target_num - len(hold_list))
            for etf in target_list:
                if context.portfolio.positions[etf].total_amount == 0:
                    order_target_value(etf, value)
                    # print('买入' + str(etf))

def getBeta(context, etf) :
    beta = 0
    if etf == '518880.XSHG': beta = countBeta(context, '518880.XSHG')   # 黄金ETF（大宗商品）
    if etf == '513100.XSHG': beta = countBeta(context, '513100.XSHG')   #纳指100（海外资产）
    if etf == '159915.XSHE': beta = countBeta(context, '159915.XSHE')   #创业板100（成长股，科技股，中小盘）
    if etf == '510180.XSHG': beta = countBeta(context, '510180.XSHG')   #上证180（价值股，蓝筹股，中大盘）
    return beta
    
def countBeta(context, etf):
    etf_data = attribute_history(etf, 250, '1d', fields=['high','low'])
    betaList = []
    for i in range(0,len(etf_data)-21):
        df = etf_data.iloc[i:i+20,:]
        betaList.append(np.polyfit(df.low,df.high,1)[0])
    return (mean(betaList)-2*std(betaList))
    
