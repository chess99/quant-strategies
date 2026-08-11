# 克隆自聚宽文章：https://www.joinquant.com/post/45699
# 标题：山寨红利
# 作者：开心果

from jqdata import *
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

#初始化函数 
def initialize(context):
    # 设定基准
    set_benchmark('510880.XSHG')
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    log.set_level('system', 'error')
    g.stocknum = 30
    run_monthly(trade, 1, '10:00')
    
# 交易
def trade(context):
    end_date = context.previous_date 
    current_data = get_current_data()
    stocks = get_all_securities('stock', end_date).index.tolist()
    q = query(
        valuation.code
    ).filter(
        valuation.code.in_(stocks),
        valuation.pb_ratio > 0,
        indicator.inc_return>0
    )
    stocks = list(get_fundamentals(q).code)
    stocks = get_dividend_ratio_filter_list(context, stocks, False, 0, 0.1)[:100]
    
    stocks = [
        stock for stock in stocks if not (
                current_data[stock].paused or
                current_data[stock].is_st or
                ('ST' in current_data[stock].name) or
                ('*' in current_data[stock].name) or
                ('退' in current_data[stock].name) or
                (current_data[stock].last_price == current_data[stock].high_limit) or
                (current_data[stock].last_price == current_data[stock].low_limit)
        )]
    stocks = stocks[:g.stocknum]    
    
    for s in context.portfolio.positions:
        if s  not in stocks:
            order_target(s, 0)
            
    psize = context.portfolio.total_value/g.stocknum  
    for s in stocks:
        if len(context.portfolio.positions) >= g.stocknum:
                    break
        if s not in context.portfolio.positions:
            order_value(s, psize)
            
    record(stocknum=len(context.portfolio.positions))

#1-1 根据最近一年分红除以当前总市值计算股息率并筛选    
def get_dividend_ratio_filter_list(context, stock_list, sort, p1, p2):
    time1 = context.previous_date
    time0 = time1 - datetime.timedelta(days=365*3)
    #获取分红数据，由于finance.run_query最多返回4000行，以防未来数据超限，最好把stock_list拆分后查询再组合
    interval = 1000 #某只股票可能一年内多次分红，导致其所占行数大于1，所以interval不要取满4000
    list_len = len(stock_list)
    #截取不超过interval的列表并查询
    q = query(finance.STK_XR_XD.code, finance.STK_XR_XD.a_registration_date, finance.STK_XR_XD.bonus_amount_rmb
    ).filter(
        finance.STK_XR_XD.a_registration_date >= time0,
        finance.STK_XR_XD.a_registration_date <= time1,
        finance.STK_XR_XD.code.in_(stock_list[:min(list_len, interval)]))
    df = finance.run_query(q)
    #对interval的部分分别查询并拼接
    if list_len > interval:
        df_num = list_len // interval
        for i in range(df_num):
            q = query(finance.STK_XR_XD.code, finance.STK_XR_XD.a_registration_date, finance.STK_XR_XD.bonus_amount_rmb
            ).filter(
                finance.STK_XR_XD.a_registration_date >= time0,
                finance.STK_XR_XD.a_registration_date <= time1,
                finance.STK_XR_XD.code.in_(stock_list[interval*(i+1):min(list_len,interval*(i+2))]))
            temp_df = finance.run_query(q)
            df = df.append(temp_df)
    dividend = df.fillna(0)
    dividend = dividend.set_index('code')
    dividend = dividend.groupby('code').sum()
    temp_list = list(dividend.index) #query查询不到无分红信息的股票，所以temp_list长度会小于stock_list
    #获取市值相关数据
    q = query(valuation.code,valuation.market_cap).filter(valuation.code.in_(temp_list))
    cap = get_fundamentals(q, date=time1)
    cap = cap.set_index('code')
    #计算股息率
    DR = pd.concat([dividend, cap] ,axis=1, sort=False)
    DR['dividend_ratio'] = (DR['bonus_amount_rmb']/10000) / DR['market_cap']
    #排序并筛选
    DR = DR.sort_values(by=['dividend_ratio'], ascending=sort)
    final_list = list(DR.index)[int(p1*len(DR)):int(p2*len(DR))]
    return final_list
    

