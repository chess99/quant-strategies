# 克隆自聚宽文章：https://www.joinquant.com/post/38552
# 标题：ffscore选股加rsrs择时
# 作者：美吉姆优秀毕业代表

# 克隆自聚宽文章：https://www.joinquant.com/post/35511
# 标题：FSCORE选股与RSRS择时
# 作者：量化菜鸟鸟

# 克隆自聚宽文章：https://www.joinquant.com/post/31359
# 标题：F_Score 选股，年化80%+
# 作者：回测时间长一点

# 导入函数库
from jqdata import *

from jqfactor import get_factor_values
import numpy as np
import pandas as pd

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    # set_benchmark('161005.XSHE')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    log.set_level('order', 'error')
    log.set_level('system', 'error')
    # log.set_level('history', 'error')
    # log.set_level('strategy', 'error')
    g.stock_index = '000300.XSHG'
    g.stock_list = []
    g.hold_num = 8
    g.score = 6 #几分以上，不含
    g.singl = []
    g.sellrank = g.hold_num * 2 # 排名多少位之后(不含)卖出
    g.buyrank = g.sellrank -1 # 排名多少位之前(含)可以买入
    g.roa_cgh = 0.002
    
    g.mincent = 0.6 #仓位偏差多少重置偏差
    g.maxcent = 1.4
    g.stocknum = []
    #########add for rsrs ##################
    g.ref_stock = '000300.XSHG' #用ref_stock做择时计算的基础数据
    g.N = 18 # 计算最新斜率slope，拟合度r2参考最近N天
    g.M = 600 # 计算最新标准分zscore，rsrs_score参考最近M天
    g.score_threshold = 0.7 # rsrs标准分指标阈值
    g.threshold = 0.03  #避免指标过于灵敏反复打脸

    g.mean_day = 30 #计算结束ma收盘价，参考最近mean_day
    g.mean_diff_day = 2 #计算初始ma收盘价，参考(mean_day + mean_diff_day)天前，窗口为mean_diff_day的一段时间
    g.slope_series = initial_slope_series()[:-1] # 除去回测第一天的slope，避免运行时重复加入
    ########## add end  #####################

      # 开盘前运行
    run_monthly(before_market_open, 1,time='before_open')
    # run_daily(before_market_open, time='before_open')
      # 开盘时运行
    run_daily(market_open, time='open')
      # 收盘后运行
    # run_daily(after_market_close, time='after_close')

#2-1 选股模块
def get_factor_filter_list(context,stock_list,jqfactor,sort,p1,p2):
    yesterday = context.previous_date
    score_list = get_factor_values(stock_list, jqfactor, end_date=yesterday, count=1)[jqfactor].iloc[0].tolist()
    df = pd.DataFrame(columns=['code','score'])
    df['code'] = stock_list
    df['score'] = score_list
    df.dropna(inplace=True)
    df.sort_values(by='score', ascending=sort, inplace=True)
    filter_list = list(df.code)[int(p1*len(stock_list)):int(p2*len(stock_list))]
    return filter_list

## 开盘前运行函数
def before_market_open(context):
    # g.stock_list = get_PEG(context,get_index_stocks('000300.XSHG'))
    # g.stock_list = g.stock_list[:g.buyrank]
    g.stock_list = get_index_stocks(g.stock_index)
    g.stock_list = kickout(context,g.stock_list)    #去除不要的行业，申万一级
    g.stock_list = get_factor_filter_list(context, g.stock_list, 'residual_volatility', False, 0, 0.8)  #残差波动因子
    g.stock_list = check_stock(context,g.stock_list)
    g.stock_list = roa_chg(context,g.stock_list)

    # print('g.stock_list',g.stock_list)
    # record(total = len(g.stock_list),hold_num = len(context.portfolio.positions.keys()))
    # g.stock_list = g.stock_list[:g.hold_num]
    # g.stock_list = g.stock_list[:min(g.sellrank,len(g.stock_list))]  #15和结果，选小的
    g.stock_list = g.stock_list[:max(g.sellrank,int(len(g.stock_list)* 0.5))]  #15和结果，选小的
    g.stock_list = g.stock_list #+ list('161005.XSHE')
    # print('初始g.stock_list',len(g.stock_list))
    
## 开盘时运行函数
def market_open(context):
    hold_stock = context.portfolio.positions.keys()
    pool = g.stock_list
    hold_stocks = g.stock_list
    g.stocknum = g.hold_num
    current_data = get_current_data()   #获取日期
    
    total_value = context.portfolio.total_value  #总共市值
    maxpercent = g.maxcent / g.stocknum #允许最大占比
    buycash = total_value / g.stocknum   #买入金额：总市值除以持股数

    # for s in hold_stock:
    #         if s not in pool:
    #             order_target(s,0)
    ###############根据择时信号看看是否需要买入############
    g.timing_signal = get_timing_signal(context,g.ref_stock)
    # print('g.timing_signal',g.timing_signal)
    if g.timing_signal == 'SELL':
        #择时信号为空卖出所有股票
        if context.portfolio.positions:
            for stock in context.portfolio.positions:
                position = context.portfolio.positions[stock]
                close_position(position)
    elif g.timing_signal == 'BUY' or g.timing_signal == 'KEEP':
            # 持有的股票如果不在选股池，没有涨停就卖出；如果仓位比重大于最大占比限制，就降到正常仓位比重
        # if context.portfolio.available_cash > 10000:
        for stock in context.portfolio.positions.keys():
            current_data = get_current_data()   #获取日期
            price1d = get_close_price(stock, 1) #获取昨天收盘价
            nosell_1 = context.portfolio.positions[stock].price >= current_data[stock].high_limit   #如果涨停了
            sell_2 = stock not in hold_stocks   #不在传入的列表里
            if sell_2 and not nosell_1:     #如果不传入的列表里and没有涨停
                _close_position(stock)
                # g.selllist.append(stock)
                log.info('交易：清仓股票 %s '%current_data[stock].name)
            else:
                current_percent = context.portfolio.positions[stock].value / context.portfolio.total_value  #个股市值除以账户总市值
                if current_percent > maxpercent:# or context.portfolio.available_cash > 10000 :
                    if order_target_value(stock, buycash):  #如果超过允许的最大比值，就重置
                        log.info('交易：平衡降低 %s 到 %s'%(current_data[stock].name, buycash))

        if len(pool) > 0 and len(context.portfolio.positions.keys()) < g.hold_num:
            # log.info("待买股票列表：%s" %(hold_stocks))
            total_value = context.portfolio.total_value
            minpercent = g.mincent / g.stocknum #0.6/4 = 0.15
            buycash = total_value / g.stocknum  #1/4 = 0.25
        
            for i in range(min(g.buyrank, len(hold_stocks))):
                free_cash = context.portfolio.available_cash
                # if hold_stocks[i] not in get_blacklist() and free_cash > context.portfolio.total_value / (g.stocknum * 10): # 黑名单里的股票不买，并且闲钱有这么多
                if hold_stocks[i] not in get_blacklist()  and free_cash > current_data[hold_stocks[i]].last_price  * 110: # 黑名单里的股票不买，并且闲钱够买1手以上
                    if hold_stocks[i] in context.portfolio.positions.keys():    #已经持仓的
                        log.info("交易：已有股票 [%s]" %(current_data[hold_stocks[i]].name))
                        current_percent = context.portfolio.positions[hold_stocks[i]].value / context.portfolio.total_value #持仓占比
                        if  current_percent >= minpercent:continue  #如果大于最低分界，就继续
                        tobuy = min(free_cash, buycash - context.portfolio.positions[hold_stocks[i]].value) #取小的：可用闲钱，或者total_value / g.stocknum 减去 持有的vaule就是要补充的
                        g.tobuyhold = tobuy  #用于调整持仓，等会rebuy用
                    else:   #如果不在持仓的
                        tobuy = min(buycash, free_cash) #取小的：total_value / g.stocknum，或者 可用闲钱
                        # g.tobuynew = tobuy #用于新买股票，等会rebuy用
                    if len(context.portfolio.positions.keys()) < g.hold_num:
                        if order_value(hold_stocks[i], tobuy) != None:
                        #     # g.buylist.append(hold_stocks[i])    #新买的票都写进list
                            log.info("交易：新买股票 [%s] %s " %((current_data[hold_stocks[i]].name),tobuy))
                    else:
                        log.info('持股数已满，停止买入')
            # cash = context.portfolio.total_value/g.hold_num
            # pool = pool[:min(g.buyrank, len(pool))]
            # # print('pool 二次',len(pool))
            # for s in pool:
            #     if len(context.portfolio.positions.keys()) < g.hold_num:
            #         if s not in context.portfolio.positions.keys():
            #             order_target_value(s,cash) 
    else: pass
def roa_chg(context,stocklist):
    security_list = stocklist
    my_watch_date = context.current_dt
    one_year_ago = my_watch_date - datetime.timedelta(days=365)
    h = get_history_fundamentals(security_list,
                             [indicator.adjusted_profit,
                            #   balance.total_current_assets,
                              balance.total_assets,
                            #   balance.total_current_liability,
                            #   balance.total_non_current_liability,
                            #   cash_flow.net_operate_cash_flow,
                            #   income.operating_revenue,
                            #   income.operating_cost,
                              ],
                             watch_date=my_watch_date, count=5).dropna()  # 连续的5个季度
                             
    def ttm_sum(x):
        return x.iloc[1:].sum()
    def ttm_avg(x):
        return x.iloc[1:].mean()
        
    def pre_ttm_sum(x):
        return x.iloc[:-1].sum()
    def pre_ttm_avg(x):
        return x.iloc[:-1].mean()
        
    def val_1(x):
        return x.iloc[-1]
    def val_2(x):
        if len(x.index) > 1:
            return x.iloc[-2]
        else:
            return nan


    # 扣非利润
    adjusted_profit_ttm = h.groupby('code')['adjusted_profit'].apply(ttm_sum)
    adjusted_profit_ttm_pre = h.groupby('code')['adjusted_profit'].apply(pre_ttm_sum)
    
    # 总资产平均
    total_assets_avg = h.groupby('code')['total_assets'].apply(ttm_avg)
    total_assets_avg_pre = h.groupby('code')['total_assets'].apply(pre_ttm_avg)
    
    # # 经营活动产生的现金流量净额
    # net_operate_cash_flow_ttm = h.groupby('code')['net_operate_cash_flow'].apply(ttm_sum)
    
    # # 长期负债率: 长期负债/总资产
    # long_term_debt_ratio = h.groupby('code')['total_non_current_liability'].apply(val_1) / h.groupby('code')['total_assets'].apply(val_1)
    # long_term_debt_ratio_pre = h.groupby('code')['total_non_current_liability'].apply(val_2) / h.groupby('code')['total_assets'].apply(val_2)
    
    # # 流动比率：流动资产/流动负债
    # current_ratio = h.groupby('code')['total_current_assets'].apply(val_1) / h.groupby('code')['total_current_liability'].apply(val_1)
    # current_ratio_pre = h.groupby('code')['total_current_assets'].apply(val_2) / h.groupby('code')['total_current_liability'].apply(val_2)
    
    # # 营业收入
    # operating_revenue_ttm = h.groupby('code')['operating_revenue'].apply(ttm_sum)
    # operating_revenue_ttm_pre = h.groupby('code')['operating_revenue'].apply(pre_ttm_sum)
    
    # # 营业成本
    # operating_cost_ttm = h.groupby('code')['operating_cost'].apply(ttm_sum)
    # operating_cost_ttm_pre = h.groupby('code')['operating_cost'].apply(pre_ttm_sum)
    
    # 1. ROA 资产收益率
    roa = adjusted_profit_ttm / total_assets_avg
    roa_pre = adjusted_profit_ttm_pre / total_assets_avg_pre
    
    # # 2. OCFOA 经营活动产生的现金流量净额/总资产
    # ocfoa = net_operate_cash_flow_ttm / total_assets_avg
    
    # 3. ROA_CHG 资产收益率变化
    roa_chg = roa - roa_pre
    
    # # 4. OCFOA_ROA 应计收益率: 经营活动产生的现金流量净额/总资产 -资产收益率
    # ocfoa_roa = ocfoa - roa
    
    # # 5. LTDR_CHG 长期负债率变化 (长期负债率=长期负债/总资产)
    # ltdr_chg = long_term_debt_ratio - long_term_debt_ratio_pre
    
    # # 6. CR_CHG 流动比率变化 (流动比率=流动资产/流动负债)
    # cr_chg = current_ratio - current_ratio_pre
    
    # # 8. GPM_CHG 毛利率变化 (毛利率=1-营业成本/营业收入)
    # gpm_chg = operating_cost_ttm_pre/operating_revenue_ttm_pre - operating_cost_ttm/operating_revenue_ttm
    
    # # 9. TAT_CHG 资产周转率变化(资产周转率=营业收入/总资产)
    # tat_chg = operating_revenue_ttm/total_assets_avg - operating_revenue_ttm_pre/total_assets_avg_pre

    spo_list = list(set(finance.run_query(
        query(
            finance.STK_CAPITAL_CHANGE.code
        ).filter(
            finance.STK_CAPITAL_CHANGE.code.in_(security_list),
            finance.STK_CAPITAL_CHANGE.pub_date.between(one_year_ago, my_watch_date),
            finance.STK_CAPITAL_CHANGE.change_reason_id == 306004)
    )['code']))
    
    spo_score = pd.Series(True, index = security_list)
    if spo_list:
        spo_score[spo_list] = False
        
    df_scores = pd.DataFrame(index=security_list)
    df_scores['roa_chg'] = roa_chg
    res  = df_scores.loc[lambda df_scores: df_scores['roa_chg'] > g.roa_cgh].sort_values(by = 'roa_chg',ascending=False).index
    return res
#ffscore选股
def check_stock(context,security_list):
    my_watch_date = context.current_dt
    one_year_ago = my_watch_date - datetime.timedelta(days=365)
    h = get_history_fundamentals(security_list,
                             [indicator.adjusted_profit,
                              balance.total_current_assets,
                              balance.total_assets,
                              balance.total_current_liability,
                              balance.total_non_current_liability,
                              cash_flow.net_operate_cash_flow,
                              income.operating_revenue,
                              income.operating_cost,
                              ],
                             watch_date=my_watch_date, count=5).dropna()  # 连续的5个季度
                             
    def ttm_sum(x):
        return x.iloc[1:].sum()

    def ttm_avg(x):
        return x.iloc[1:].mean()
    def pre_ttm_sum(x):
        return x.iloc[:-1].sum()
    
    def pre_ttm_avg(x):
        return x.iloc[:-1].mean()
    
    def val_1(x):
        return x.iloc[-1]
    
    def val_2(x):
        if len(x.index) > 1:
            return x.iloc[-2]
        else:
            return nan


    # 扣非利润
    adjusted_profit_ttm = h.groupby('code')['adjusted_profit'].apply(ttm_sum)
    adjusted_profit_ttm_pre = h.groupby('code')['adjusted_profit'].apply(pre_ttm_sum)
    
    # 总资产平均
    total_assets_avg = h.groupby('code')['total_assets'].apply(ttm_avg)
    total_assets_avg_pre = h.groupby('code')['total_assets'].apply(pre_ttm_avg)
    
    # 经营活动产生的现金流量净额
    net_operate_cash_flow_ttm = h.groupby('code')['net_operate_cash_flow'].apply(ttm_sum)
    
    # 长期负债率: 长期负债/总资产
    long_term_debt_ratio = h.groupby('code')['total_non_current_liability'].apply(val_1) / h.groupby('code')['total_assets'].apply(val_1)
    long_term_debt_ratio_pre = h.groupby('code')['total_non_current_liability'].apply(val_2) / h.groupby('code')['total_assets'].apply(val_2)
    
    # 流动比率：流动资产/流动负债
    current_ratio = h.groupby('code')['total_current_assets'].apply(val_1) / h.groupby('code')['total_current_liability'].apply(val_1)
    current_ratio_pre = h.groupby('code')['total_current_assets'].apply(val_2) / h.groupby('code')['total_current_liability'].apply(val_2)
    
    # 营业收入
    operating_revenue_ttm = h.groupby('code')['operating_revenue'].apply(ttm_sum)
    operating_revenue_ttm_pre = h.groupby('code')['operating_revenue'].apply(pre_ttm_sum)
    
    # 营业成本
    operating_cost_ttm = h.groupby('code')['operating_cost'].apply(ttm_sum)
    operating_cost_ttm_pre = h.groupby('code')['operating_cost'].apply(pre_ttm_sum)
    
    # 1. ROA 资产收益率
    roa = adjusted_profit_ttm / total_assets_avg
    roa_pre = adjusted_profit_ttm_pre / total_assets_avg_pre
    
    # 2. OCFOA 经营活动产生的现金流量净额/总资产
    ocfoa = net_operate_cash_flow_ttm / total_assets_avg
    
    # 3. ROA_CHG 资产收益率变化
    roa_chg = roa - roa_pre
    
    # 4. OCFOA_ROA 应计收益率: 经营活动产生的现金流量净额/总资产 -资产收益率
    ocfoa_roa = ocfoa - roa
    
    # 5. LTDR_CHG 长期负债率变化 (长期负债率=长期负债/总资产)
    ltdr_chg = long_term_debt_ratio - long_term_debt_ratio_pre
    
    # 6. CR_CHG 流动比率变化 (流动比率=流动资产/流动负债)
    cr_chg = current_ratio - current_ratio_pre
    
    # 8. GPM_CHG 毛利率变化 (毛利率=1-营业成本/营业收入)
    gpm_chg = operating_cost_ttm_pre/operating_revenue_ttm_pre - operating_cost_ttm/operating_revenue_ttm
    
    # 9. TAT_CHG 资产周转率变化(资产周转率=营业收入/总资产)
    tat_chg = operating_revenue_ttm/total_assets_avg - operating_revenue_ttm_pre/total_assets_avg_pre

    spo_list = list(set(finance.run_query(
        query(
            finance.STK_CAPITAL_CHANGE.code
        ).filter(
            finance.STK_CAPITAL_CHANGE.code.in_(security_list),
            finance.STK_CAPITAL_CHANGE.pub_date.between(one_year_ago, my_watch_date),
            finance.STK_CAPITAL_CHANGE.change_reason_id == 306004)
    )['code']))
    
    spo_score = pd.Series(True, index = security_list)
    if spo_list:
        spo_score[spo_list] = False
        
    df_scores = pd.DataFrame(index=security_list)
    # 1
    df_scores['roa'] = roa>0
    # df_scores['roa'] = roa>0.024    #不是拟合不是玄学，是国债收益率
    # 2
    df_scores['ocfoa'] = ocfoa>0
    # 3
    df_scores['roa_chg'] = roa_chg>0
    # df_scores['roa_chg'] = roa_chg>0.024    #不是拟合不是玄学，是国债收益率
    # 4
    df_scores['ocfoa_roa'] = ocfoa_roa>0
    # 5
    df_scores['ltdr_chg'] = ltdr_chg<=0
    # 6
    df_scores['cr_chg'] = cr_chg>0
    # 7
    df_scores['spo'] = spo_score  > 0
    # 8
    df_scores['gpm_chg'] = gpm_chg>0
    # 9
    df_scores['tat_chg'] = tat_chg>0
    
    # 合计
    df_scores = df_scores.dropna()
    df_scores['total'] = df_scores['roa'] + df_scores['ocfoa'] + df_scores['roa_chg'] + \
        df_scores['ocfoa_roa'] + df_scores['ltdr_chg'] + df_scores['cr_chg'] + \
        df_scores['spo'] + df_scores['gpm_chg'] + df_scores['tat_chg']
    res  = df_scores.loc[lambda df_scores: df_scores['total'] > g.score].sort_values(by = 'total',ascending=False).index
    
    
    
    # 升序	asc()
    # 降序	desc()
    
    # 市值排序：
    # q = get_fundamentals(query(
    #     valuation.code, valuation.market_cap, valuation.circulating_market_cap,valuation.pb_ratio,valuation.pe_ratio
    #     ).filter(valuation.code.in_(res)
    #     ).order_by(valuation.market_cap.asc()).limit(len(res)))

    # roe 排序：
    q = get_fundamentals(query(
             indicator.code,indicator.roe
          ).filter(
             indicator.code.in_(res)
          ).order_by(indicator.roe.desc()).limit(len(res)))

    res = list(q['code'])
    # record(total = len(res),hold_num = len(context.portfolio.positions.keys()))
    return res

def kickout(context,stocklist):
     #钢铁 	有色金属I 房地产  
     #金融服务 国防军工I 传媒I 
    z_list = []
    # stock_sw1 = get_industry_stocks('801040') + get_industry_stocks('801050') + get_industry_stocks('801180') + \
    #             get_industry_stocks('801190') + get_industry_stocks('801740') + get_industry_stocks('801760') +	\
    #             get_industry_stocks('801950') + get_industry_stocks('801960') + get_industry_stocks('801790')	
    stock_sw1 = get_industry_stocks('801180')
    for s in stocklist:
        if s not in stock_sw1:
            z_list.append(s)
        else:
            pass
    return z_list
############################# rsrs函数 #############################
# 这里求R2的式子有点问题，但是这个效果更好，原因未找到！
def get_ols(x, y):
    slope, intercept = np.polyfit(x, y, 1)
    r2 = 1 - (sum((y - (slope * x + intercept))**2) / ((len(y) - 1) * np.var(y, ddof=1)))
    return (intercept, slope, r2)

def initial_slope_series():
    data = attribute_history(g.ref_stock, g.N + g.M, '1d', ['high', 'low'])
    return [get_ols(data.low[i:i+g.N], data.high[i:i+g.N])[1] for i in range(g.M)]

# 因子标准化
def get_zscore(slope_series):
    mean = np.mean(slope_series)
    std = np.std(slope_series)
    return (slope_series[-1] - mean) / std

# 只看RSRS因子值作为买入、持有和清仓依据，前版本还加入了移动均线的上行作为条件
def get_timing_signal(context,stock):
    g.mean_diff_day = 5
    # 30+5 天,避免指标过于灵敏反复打脸
    close_data = attribute_history(g.ref_stock, g.mean_day + g.mean_diff_day, '1d', ['close'])
    high_low_data = attribute_history(g.ref_stock, g.N, '1d', ['high', 'low'])

    # 这两句同上面的功能相同，愿意测试的可以试试，与avoid_future_data相互矛盾，只能取二者中的一个
    # close_data = get_price(g.ref_stock, end_date=context.current_dt-datetime.timedelta(1),count=g.mean_day + g.mean_diff_day,fields=['close'])
    # high_low_data = get_price(g.ref_stock, end_date=context.current_dt-datetime.timedelta(1),count=g.N, fields=['high', 'low'])

    intercept, slope, r2 = get_ols(high_low_data.low, high_low_data.high)
    g.slope_series.append(slope)
    rsrs_score = get_zscore(g.slope_series[-g.M:]) * r2
    # g.score_threshold = g.score_threshold * (1 + g.threshold)
    # record(rsrs分数 = rsrs_score,low = -g.score_threshold * (1 - g.threshold),high = g.score_threshold * (1 - g.threshold))

    # if rsrs_score > g.score_threshold * (1 + g.threshold): return "BUY" #0.7乘以1.03    0.721
    # if rsrs_score > g.score_threshold: return "BUY" #0.7乘以1.03    0.721
    # elif rsrs_score < -g.score_threshold: return "SELL"
    print('rsrs_score %s'%rsrs_score)
    
    if g.singl == [] or g.singl == "KEEP":
        if rsrs_score > g.score_threshold: g.singl =  "BUY" #0.7乘以1.03    0.721
        elif rsrs_score < -g.score_threshold: g.singl =  "SELL"
        else: g.singl = "KEEP"
        
    elif g.singl ==  "SELL":
        if rsrs_score <= -g.score_threshold * (1 - g.threshold):    # 0.7 * 1-0.001
            g.singl =  "SELL"
            print('selling %s'%rsrs_score)
        else:
            g.singl =  "KEEP"
            
    elif g.singl ==  "BUY":
        if rsrs_score >= g.score_threshold * (1 - g.threshold):    #0.7 + 1.03 = 0.721 #0.679
            g.singl =  "BUY"
        else:
            g.singl =  "KEEP"
    return g.singl
    # elif rsrs_score < -g.score_threshold * (1 - g.threshold): return "SELL" ##0.7乘以0.97   -0.679

############################# rsrs函数 #############################

## 收盘后运行函数
def after_market_close(context):
    # record(hold_num = len(context.portfolio.positions.keys()))
    record(total = len(g.stock_list),hold_num = len(context.portfolio.positions.keys()))

# 交易函数
def order_target_value_(security, value):
	if value == 0:
# 		log.debug("Selling out %s" % (security))
		print('')
# 		print('rsrs清仓')
	else:
		log.debug("Order %s to value %f" % (security, value))
	# 如果股票停牌，创建报单会失败，order_target_value 返回None
	# 如果股票涨跌停，创建报单会成功，order_target_value 返回Order，但是报单会取消
	# 部成部撤的报单，聚宽状态是已撤，此时成交量>0，可通过成交量判断是否有成交
	return order_target_value(security, value)
	
def close_position(position):
	security = position.security
	order = order_target_value_(security, 0)  # 可能会因停牌失败
	if order != None:
		if order.status == OrderStatus.held and order.filled == order.amount:
			return True
	return False
# 获取前n个单位时间当时的收盘价
def get_close_price(code, n, unit='1d'):
    return attribute_history(code, n, unit, 'close', df=False)['close'][0]

def get_blacklist():
    blacklist = ['600519.XSHG']
    return blacklist


# 平仓，卖出指定持仓
def _close_position(code):
    order = order_target_value(code, 0) # 可能会因停牌或跌停失败
    # if order != None and order.status == OrderStatus.held:
        # g.sold_stock[code] = 0
