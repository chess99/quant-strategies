# 克隆自聚宽文章：https://www.joinquant.com/post/47966
# 标题：带上止损的核心资产轮动才更安心，低回撤，高收益率
# 作者：养家大哥

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
    # 参数
    g.etf_pool = [
        '518880.XSHG', #黄金ETF（大宗商品）
        '513100.XSHG', #纳指100（海外资产）
        '159915.XSHE', #创业板100（成长股，科技股，中小盘）
        '510180.XSHG', #上证180（价值股，蓝筹股，中大盘）
    ]
    g.m_days = 25 #动量参考天数
    g.etf_info = initial_etf_info(g.etf_pool, 100)
    g.etf_pre = None
    run_daily(update_etf_table, '7:00') #每天运行确保即时捕捉动量变化
    run_daily(trade, '9:30') #每天运行确保即时捕捉动量变化

# 初始化股票信息
def initial_etf_info(etf_pool, ndays=100):
    etf_info = {}
    for etf in etf_pool:
        etf_df = attribute_history(etf, ndays,'1d',['close'],skip_paused=True, df=True, fq='pre')
        etf_info[etf] = list(etf_df.close)
    return(etf_info)

def update_etf_table(context):
    for etf in g.etf_pool:
        etf_df = attribute_history(etf, 1,'1d',['close'],skip_paused=True, df=True, fq='pre')
        g.etf_info[etf].append(etf_df.close[-1])
        g.etf_info[etf].pop(0)
        
def evaluate_etf_worth(m_etf, is_hold=1):
    is_worth = 0
    if(m_etf==None):return(is_worth)
    #判断是否可以持有
    cur_p = g.etf_info[m_etf][-1]
    max10_p = max(g.etf_info[m_etf][-10:])
    max_p = max(g.etf_info[m_etf])
    cur2max = cur_p/max_p
    cur2max10 = cur_p/max10_p
    cur2yes = cur_p/g.etf_info[m_etf][-2]
    mean4   = np.mean(g.etf_info[m_etf][-4:])
    print("%s, cur2yes=%0f, cur2max=%0f, cur2max10=%0f, cur_p=%0f, mean4=%0f"%(m_etf, cur2yes, cur2max, cur2max10, cur_p, mean4))
    if(is_hold == 1):
        if(cur2yes <= 0.96):
            is_worth = 0
        else:
            is_worth = 1
    else:
        if(cur_p>=mean4):
            is_worth = 1
        else:
            is_worth = 0
    return(is_worth)

# 基于年化收益和判定系数打分的动量因子轮动 https://www.joinquant.com/post/26142
def get_rank(etf_pool):
    score_list = []
    for etf in etf_pool:
        df = attribute_history(etf, g.m_days, '1d', ['close'])
        y = df['log'] = np.log(df.close)
        x = df['num'] = np.arange(df.log.size)
        slope, intercept = np.polyfit(x, y, 1)
        annualized_returns = math.pow(math.exp(slope), 250) - 1
        r_squared = 1 - (sum((y - (slope * x + intercept))**2) / ((len(y) - 1) * np.var(y, ddof=1)))
        score = annualized_returns * r_squared
        score_list.append(score)
    df = pd.DataFrame(index=etf_pool, data={'score':score_list})
    df = df.sort_values(by='score', ascending=False)
    rank_list = list(df.index)    
    print(df)     
    record(黄金 = round(df.loc['518880.XSHG'], 2))
    record(纳指 = round(df.loc['513100.XSHG'], 2))
    record(成长 = round(df.loc['159915.XSHE'], 2))
    record(价值 = round(df.loc['510180.XSHG'], 2))
    return rank_list

# 交易
def trade(context):
    # 获取动量最高的一只ETF
    sel_etf = get_rank(g.etf_pool)[0]
    hold_etf = None
    # 卖出    
    hold_list = list(context.portfolio.positions)
    if(len(hold_list)>0): hold_etf = hold_list[0]
    sel_worth = evaluate_etf_worth(sel_etf, 0)
    hold_worth = evaluate_etf_worth(hold_etf, 1)
    print(f"持有{hold_etf}={hold_worth}, 选择{sel_etf}={sel_worth}")
    if(hold_etf != None):
        g.etf_pre = hold_etf
        if sel_etf not in hold_list:
            order_target_value(hold_etf, 0)
            print('调仓卖出' + str(hold_etf))
        elif hold_worth==0:
            order_target_value(hold_etf, 0)
            print('止损卖出' + str(hold_etf))
        else:
            print('继续持有' + str(hold_etf))
    # 买入
    if (sel_etf != g.etf_pre):
        order_target_value(sel_etf, context.portfolio.available_cash)
        print('调仓买入' + str(sel_etf))
    elif (len(hold_list)==0)and(sel_etf == g.etf_pre)and(sel_worth==1):
        order_target_value(sel_etf, context.portfolio.available_cash)
        print('恢复买入' + str(sel_etf))

