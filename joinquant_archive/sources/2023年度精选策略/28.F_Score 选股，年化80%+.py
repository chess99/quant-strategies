# 克隆自聚宽文章：https://www.joinquant.com/post/31359
# 标题：F_Score 选股，年化80%+
# 作者：回测时间长一点

# 导入函数库
from jqdata import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')
    g.stock_index = '000300.XSHG'
    


    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_weekly(before_market_open, time='before_open', reference_security='000300.XSHG',weekday=1)
      # 开盘时运行
    run_weekly(market_open, time='open', reference_security='000300.XSHG',weekday=1)
      # 收盘后运行
    run_weekly(after_market_close, time='after_close', reference_security='000300.XSHG',weekday=1)

## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))

    # 给微信发送消息（添加模拟交易，并绑定微信生效）
    # send_message('美好的一天~')

    # 要操作的股票：平安银行（g.为全局变量）
    # g.security = '000001.XSHE'

def check_risk(context):
    today = context.current_dt
    All = get_index_stocks(g.stock_index,today)
    flowData =  get_money_flow(All, end_date=today, fields=['sec_code','date','net_amount_xl','net_amount_l','net_amount_m','net_amount_s'], count=30)
   
    
    preData = flowData.groupby(["sec_code"]).sum()
    pre2Data = preData.loc[(preData['net_amount_xl'] > 0)  &  (preData['net_amount_l'] > 0)]
    pre3Data = preData.loc[(preData['net_amount_xl'] > 0)  &  (preData['net_amount_l'] > 0) &  (preData['net_amount_s'] > 0) ]
    # pre4Data = preData.loc[(preData['net_amount_xl'] > 0)  &  (preData['net_amount_l'] > 0)  ]
    pre5Data = preData.loc[(preData['net_amount_s'] > 0) &  (preData['net_amount_m'] > 0) ]
    # pre6Data = preData.loc[(preData['net_amount_l'] > 0)  &  (preData['net_amount_s'] > 0) &  (preData['net_amount_m'] > 0) ]

    
    # print('pre5Data is len:%s'%len(pre5Data))
    # print('pre6Data is len:%s'%len(pre6Data))
    g.is_danger = False
    if len(pre3Data) > 0:
    
        # # if (len(pre3Data) <= 0  or (((len(pre3Data) <=10) and (len(pre4Data) <=10)) and ((len(pre5Data) <=10) and (len(pre6Data) <=15)) ) ):
        # if ( len(pre5Data)/len(pre3Data) >250 ):
        #     return  True
        # else:
        return False
    else:
        return True

def check_stock(context):
    security_list = get_index_stocks(g.stock_index )
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
    # 2
    df_scores['ocfoa'] = ocfoa>0
    # 3
    df_scores['roa_chg'] = roa_chg>0
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
    res  = df_scores.loc[lambda df_scores: df_scores['total'] > 8].sort_values(by = 'total',ascending=False).index
    return res

## 开盘时运行函数
def market_open(context):
    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    hold_stock = context.portfolio.positions.keys()
    # security = g.security
  
    pool = check_stock(context)
        
    for s in hold_stock:
            if s not in pool:
                order_target(s,0)
    if len(pool) >0:
        cash = context.portfolio.total_value/len(pool)
        for s in pool:
            order_target_value(s,cash)
        #获取已经持仓列表
       
        #卖出不在持仓中的股票
    
        #买入股票
    

## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    log.info('一天结束')
    log.info('##############################################################')
