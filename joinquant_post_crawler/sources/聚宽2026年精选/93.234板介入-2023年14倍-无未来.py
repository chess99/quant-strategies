# 克隆自聚宽文章：https://www.joinquant.com/post/47559
# 标题：234板介入-2023年14倍-无未来
# 作者：Clarence.罗

from jqlib.technical_analysis import *
from jqfactor import *
from jqdata import *
import datetime as dt
import pandas as pd
#from jq_sendMsg import *
#from wxpusher import *
import MySQLdb

def initialize(context):
    # 系统设置
    set_option('use_real_price', True)
    # set_option('avoid_future_data', True)
    log.set_level('system', 'error')
    pd.set_option('display.max_columns', None)

    #假定：
    #1 游资手上2亿
    #2 选股看的是流通市值: 50亿以下
    #2 持有了一定的筹码：
    #3 拉升到二板上没多少人卖了，绝对值小于NN？LB小于1.5？
    g.max_free_market_cap = 50 #亿，没用到
    g.max_actual_turnover_ratio = 30 #没用到，仅作提示

    g.max_turnover_ratio = 30
    g.max_LB_1d = 1.875 #比前一天的量比，不是比5日均量

#实盘变更代码后重设全部参数                
def after_code_changed(context):
    unschedule_all()
    # 分仓数量
    g.ps = 1
    # 盘前选股
    g.target_list =[]
    g.strategy = "首板低开200"

    g.sort = True
    g.jqfactor = 'VOL5'
    # 每日运行
    run_daily(get_stock_list, '09:25')


    run_daily(sell_234_if_open_lower_than_96pct, '09:30') #低开太多先跑
    run_daily(sell_if_open_lower_than_92pct, '09:30') #垃圾股先跑
    run_daily(buy_all_cluo, '09:30') #确保卖出了再买

    run_daily(sell_lt, '11:29:00')
    run_daily(sell_lt, '14:52:00')

    #run_daily(sell_if_profit_and_not_HL, '13:59:30') #止盈
    #run_daily(sell_if_not_HL, '14:49:30') #止损
    #run_daily(log_stocks_bought, '15:02')


def sell_lt(context):

  
    #基本信息
    date = transform_date(context.previous_date, 'str')
    hold_list = context.portfolio.positions.keys()
    current_data = get_current_data()
    stock_list = []
    for s in hold_list:
        
        # 条件1：不涨停
        if not (current_data[s].last_price == current_data[s].high_limit):
            if context.portfolio.positions[s].closeable_amount != 0:
                
                # 条件2.1：持有一定时间
                start_date = transform_date(context.portfolio.positions[s].init_time, 'str')
                target_date = get_shifted_date(start_date, 2, 'T')
                current_date = transform_date(context.current_dt, 'str')
                
                # 条件2.2：已经盈利
                cost = context.portfolio.positions[s].avg_cost
                price = context.portfolio.positions[s].price
                ret = 100 * (price/cost-1)
                
                # 在满足条件1的前提下，条件2中只要满足一个即卖出
                if current_date >= target_date or ret > 0:
                    order_target_value(s, 0)
                    print('龙头卖出', [s, get_security_info(s, date).display_name])
                    print('———————————————————————————————————')


# 选股
def get_stock_list(context):
    
    # 基础信息: 昨天开始算
    date = transform_date(context.previous_date, 'str')
    current_data = get_current_data()
    
    # 初始列表（过滤函数兼容研究与回测）
    initial_list = prepare_stock_list(date)

    #昨日
    date_1d = transform_date(context.previous_date, 'str')
    #两天前
    date_2d = get_shifted_date(date_1d, -1, days_type='T')
    #三天前
    date_3d = get_shifted_date(date_2d, -1, days_type='T')
    #三天前
    date_4d = get_shifted_date(date_3d, -1, days_type='T')
    date_5d = get_shifted_date(date_4d, -1, days_type='T')

    hl_list_1d = filter_yzb(get_hl_stock(initial_list, date_1d),date_1d)
    hl_list_2d = get_hl_stock(initial_list, date_2d)
    #hl_list_2d = filter_yzb(get_hl_stock(initial_list, date_2d),date_1d)
    hl_list_3d = get_hl_stock(initial_list, date_3d)
    hl_list_4d = get_hl_stock(initial_list, date_4d)
    hl_list_5d = get_hl_stock(initial_list, date_5d)

    #昨日非一字板，已经放到hl_list_1d = filter_yzb(get_hl_stock(initial_list, date_1d),date_1d)里了
    # def filter_yzb(stock_list, date):
    #stock_list = filter_yzb(stock_list, date_1d)
    #print ("昨日非一字板",stock_list)    

    #stock_list = list( set(hl_list_1d).intersection(set(hl_list_2d)).intersection(set(hl_list_3d)) - set(hl_list_4d)) - set(hl_list_5d) )
    #print ("昨日三连板，且昨日非一字板", stock_list)
    #stock_list = list( set(hl_list_1d).intersection(set(hl_list_2d)) - set(hl_list_3d) - set(hl_list_4d) - set(hl_list_5d) )
    #print ("昨日二连板，且昨日非一字板", stock_list)

    #昨日二、三、四板，且不考虑断板，断板就不是启动的逻辑了
    stock_list = list( set(hl_list_1d).intersection(set(hl_list_2d)).intersection(set(hl_list_3d)).intersection(set(hl_list_4d)) - set(hl_list_5d) )
    #print ("昨日四连板，且昨日非一字板", stock_list)
    stock_list.extend( list( set(hl_list_1d).intersection(set(hl_list_2d)).intersection(set(hl_list_3d)) - set(hl_list_4d) - set(hl_list_5d) ) )
    #print ("昨日三四连板，且昨日非一字板",stock_list)
    stock_list.extend( list( set(hl_list_1d).intersection(set(hl_list_2d)) - set(hl_list_3d) - set(hl_list_4d) - set(hl_list_5d) ) )
    print ("昨日二三四板，且昨日非一字板",stock_list)

    #昨日三、四板，且不考虑断板，断板就不是启动的逻辑了
    #stock_list = list( set(hl_list_1d).intersection(set(hl_list_2d)).intersection(set(hl_list_3d)).intersection(set(hl_list_4d)) - set(hl_list_5d) )
    #print ("昨日四连板，且昨日非一字板", stock_list)
    #stock_list.extend( list( set(hl_list_1d).intersection(set(hl_list_2d)).intersection(set(hl_list_3d)) - set(hl_list_4d) - set(hl_list_5d) ) )
    #print ("昨日三四连板，且昨日非一字板",stock_list)

    #昨日二三板
    #stock_list = list( set(hl_list_1d).intersection(set(hl_list_2d)).intersection(set(hl_list_3d)) - set(hl_list_4d) - set(hl_list_5d) ) 
    #print ("昨日三连板，且昨日非一字板", stock_list)
    #stock_list.extend( list( set(hl_list_1d).intersection(set(hl_list_2d)) - set(hl_list_3d) - set(hl_list_4d) - set(hl_list_5d) ) )
    #print ("昨日二、三板，且昨日非一字板",stock_list)

    #stock_list = list( set(hl_list_1d).intersection(set(hl_list_2d)) - set(hl_list_3d) )
    #print ("昨日二连板，且昨日非一字板", stock_list)
    

    #昨日二三板，可能包含断板，断板就不是启动主升浪的逻辑了，不考虑
    #stock_list = list(set(hl_list_1d).intersection(set(hl_list_2d)))
    #stock_list = list(set(stock_list) - set(hl_list_3d) - set(hl_list_4d))
    #print ("昨日二、三板，且昨日非一字板",stock_list)
    
    # 90日内未出现3连板及以上情况
    if len(stock_list) > 0:
        df = get_continue_count_df1(stock_list, date_4d, 90) 
        #df1 = df[df['count'] >= 4]
        #print ("90日内3连扳过", list(df1.index))
        df = df[df['count'] < 4]
        df = df[df['count'] > 0]
        stock_list = list(df.index)
        print ("此前90日内涨停过有主力，且最高连扳不高于3板的股票", list(stock_list))


    #昨日换手率<g.max_turnover_ratio
    stock_list = [ s for s in stock_list[:] if HSL([s], date_1d)[0][s] < g.max_turnover_ratio ]
    print ("昨日换手率<g.max_turnover_ratio",stock_list)

    #昨天交易量比前天小
    #def get_money(stock_code, N_days_ago=1):
    stock_list = [ s for s in stock_list[:] if get_money(s,1) < get_money(s,2) * g.max_LB_1d ]
    print ("昨天交易量不大于前天g.max_LB_1d倍",stock_list)

    stock_list_with_low_actual_turnover_ratio = []
    for s in stock_list[:]:
        print('———————————————————————————————————')
        free_market_cap, actual_turnover_ratio = get_free_market_cap_and_actual_turnover_ratio(s, date_1d)
        print (s + "【"+ get_security_info(s).display_name + "】")
        print ("流通市值" + str(get_circulating_market_cap(context, s)) + "，换手率" + str( HSL([s], date_1d)[0][s]) )
        print ("自由流通市值" + str(free_market_cap) + "，实际换手率" + str(actual_turnover_ratio))
        if actual_turnover_ratio < g.max_actual_turnover_ratio :
            stock_list_with_low_actual_turnover_ratio.append(s)
        else:
            print ("====>实际换手率过大" + str(actual_turnover_ratio) + "，忽略不要？")
            pass
    #stock_list = stock_list_with_low_actual_turnover_ratio
    print('———————————————————————————————————')

    #昨日收盘价 高于 120 最高价
    #def get_historical_high(stock_code, N_days=120):
    #stock_list = [ s for s in stock_list if get_historical_high(s,1) >= get_historical_high(s,120) ]
    #print ("昨日收盘价 高于 前120 最高价",stock_list)
    
    #在昨天热点板块
    ## 热门股票池
    
    #try:
    #dct = get_concept(hl_list_1d, date_1d)
    #hot_concept = get_hot_concept(dct, date_1d)
    #hot_stocks = filter_concept_stock(dct, hot_concept)
    #except:
    #    hot_stocks=[]
    #    pass    
    #print ("hot_concept",hot_concept)
    #print ("hot_stocks",hot_stocks)
    #stock_list = list(set(stock_list).intersection(set(hot_stocks)))
    #print ("在昨天热点板块",stock_list)

    if len(stock_list) > 0:
        if len(stock_list) > 1:
            #自由流通市值最小
            stock_list = sort_stocks_by_free_market_cap(context,stock_list)
            print("二三四板自由流通市值由小到大", stock_list)
            g.target_list = stock_list

            #实际换手率最小
            #sort_stocks_by_actual_turnover_ratio
            #print("二三四板实际换手率由小到大", stock_list)
            #g.target_list = stock_list

            #stock_list = sort_stocks_by_market_cap(context,stock_list)
            #print("按流通市值由小到大", stock_list)
    
            #g.target_list = stock_list[:g.ps]
            #print("直接取最高板", g.target_list, current_data[g.target_list[0]].name)
        else:
            g.target_list = stock_list

    else:
        g.target_list = []
    
    
    print('———————————————————————————————————')

def get_circulating_market_cap(context, security_code):
    q = query(
        valuation
    ).filter(
        valuation.code == security_code
    )
    df = get_fundamentals(q, context.previous_date )
    return df['circulating_market_cap'][0]

def sort_stocks_by_market_cap(context,stock_list):
    #log.info("sort_stocks_by_market_cap，按换手率由大到小排列。", len(stock_list))
    if len(stock_list)<=0:
        log.info("!!! 输入sort_stocks_by_market_cap的股票池是空的  !!!")
        return []

    q = query(valuation.code,
            valuation.market_cap,
            valuation.circulating_market_cap,
        ).filter(
            valuation.code.in_(stock_list)
        ).order_by(
            valuation.circulating_market_cap.asc()
        )
    df = get_fundamentals(q)
    stock_list = list(df["code"])

    return stock_list

def sort_stocks_by_actual_turnover_ratio(context,stock_list):
    if len(stock_list)<1:
        log.error("数据非法, sort_stocks_by_actual_turnover_ratio 获取0只股票")
        return[]

    free_market_cap_list = []
    actual_turnover_ratio_list = []
    for stock in stock_list:
        free_market_cap, actual_turnover_ratio = get_free_market_cap_and_actual_turnover_ratio(stock, context.previous_date)
        # 自由流通市值
        free_market_cap_list.append(free_market_cap)
        actual_turnover_ratio_list.append(actual_turnover_ratio)

    combined_data = list(zip(stock_list, actual_turnover_ratio_list))
    print (combined_data)
    # Sort the list of tuples based on free_market_cap (second element in the tuple)
    sorted_data = sorted(combined_data, key=lambda x: x[1], reverse=False)
    
    # Extract the sorted stock_list
    stock_list_sorted_by_actual_turnover_ratio = [item[0] for item in sorted_data]
    
    print("按实际换手率排序后:", stock_list_sorted_by_actual_turnover_ratio)

    return stock_list_sorted_by_actual_turnover_ratio

def sort_stocks_by_free_market_cap(context,stock_list):
    if len(stock_list)<1:
        log.error("数据非法, sort_stocks_by_free_market_cap 获取0只股票")
        return[]


    free_market_cap_list = []
    actual_turnover_ratio_list = []
    for stock in stock_list:
        free_market_cap, actual_turnover_ratio = get_free_market_cap_and_actual_turnover_ratio(stock, context.previous_date)
        # 自由流通市值
        free_market_cap_list.append(free_market_cap)
        actual_turnover_ratio_list.append(actual_turnover_ratio)

    combined_data = list(zip(stock_list, free_market_cap_list))
    print (combined_data)
    # Sort the list of tuples based on free_market_cap (second element in the tuple)
    sorted_data = sorted(combined_data, key=lambda x: x[1], reverse=False)
    
    # Extract the sorted stock_list
    stock_list_sorted_by_free_market_cap = [item[0] for item in sorted_data]
    
    print("按自由流通市值排序后:", stock_list_sorted_by_free_market_cap)

    return stock_list_sorted_by_free_market_cap


#某只股票的自由流通市值，即总股数扣减掉5%以上的大股东
def get_free_market_cap_and_actual_turnover_ratio(stk, pub_date_str):


    #当日收盘价
    prices_df = get_price(stk, end_date=pub_date_str, count=1, frequency='daily', 
                          fields=['close','volume'], skip_paused=False, fq='pre') 

    #总市值
    q = query(
        valuation.code,
        valuation.market_cap,
        valuation.circulating_market_cap
    ).filter(
        valuation.code.in_([stk]),
    )
    market_cap_df = get_fundamentals(q, date=pub_date_str) #pub_date_str日的市值

    #先按流通市值算
    circulating_market_cap = market_cap_df['circulating_market_cap'].iloc[0]
    circulating_turnover_ratio = 100 * prices_df['volume'].iloc[0] / circulating_market_cap / 1e8

    #总股数 = 当日市值 / 当日收盘价
    capitalization = (1e8 * market_cap_df['market_cap'].iloc[0] / prices_df['close'].iloc[0])
    #print 'capitalization', capitalization

    #某只股票的自由流通市值，即总股数扣减掉5%以上的大股东
    #还要再判断持股5%以上的股东，将其股数从股本中减掉
    #季报应该有吧？
    #pub_date_str = get_shifted_date(test_date_str, -62, days_type='T')
    q=query(
        finance.STK_SHAREHOLDER_TOP10.code,
        finance.STK_SHAREHOLDER_TOP10.shareholder_name,
        finance.STK_SHAREHOLDER_TOP10.share_number,
        finance.STK_SHAREHOLDER_TOP10.share_ratio,
        finance.STK_SHAREHOLDER_TOP10.pub_date,
           ).filter(
        finance.STK_SHAREHOLDER_TOP10.code==stk,
        finance.STK_SHAREHOLDER_TOP10.pub_date<pub_date_str,
    ).order_by(
        finance.STK_SHAREHOLDER_TOP10.pub_date.desc()
    ).limit(
        20
        )
    shareholder_df = finance.run_query(q)
    #有些最近财报数据是空的，所以多取了一个季度,10大*2=20
    if len(shareholder_df) <1:
        print ('------------ 出错了！------------')
        print (pub_date_str, stk, '找不到十大股东数据')
        print (shareholder_df[['shareholder_name','share_ratio','pub_date']])
        print ('------------ 出错了！------------')
        return circulating_market_cap,circulating_turnover_ratio

    #print (stk+"【"+get_security_info(stk).display_name+"】,十大股东：")
    #print (shareholder_df[['shareholder_name','share_ratio','pub_date']])

    #因为取了两个季度的财报中的十大股东，必须去空！！！
    shareholder_df = shareholder_df.dropna()
    #因为取了两个季度的财报中的十大股东，必须去重！！！
    shareholder_df['pub_date'] = pd.to_datetime(shareholder_df['pub_date'])
    latest_annual_report_date = shareholder_df['pub_date'].max() 
    shareholder_df = shareholder_df[shareholder_df['pub_date'] >= latest_annual_report_date]
    shareholder_df = shareholder_df.sort_values(by='share_ratio', ascending=False)

    if len(shareholder_df) <1:
        print ('------------ 出错了！------------')
        print (pub_date_str, stk, '找不到十大股东数据')
        print ('------------ 出错了！------------')
        return circulating_market_cap,circulating_turnover_ratio
    else:
        #print (stk+"去除更早财报中的十大股东数据之后：" )
        #print (stk+"【"+get_security_info(stk).display_name+"】,十大股东：")
        #print (shareholder_df[['shareholder_name','share_ratio','pub_date']])
        pass

    sum_share_ratio_large_than_5_pct = shareholder_df.loc[shareholder_df['share_ratio'] > 5, 'share_number'].sum() 
    effective_capitalization = capitalization - sum_share_ratio_large_than_5_pct

    if effective_capitalization<0:
        print ('------------ 出错了！------------')
        print ('十大股东持股比例大于100')
        print (pub_date_str, stk, '十大股东')
        print (shareholder_df[['shareholder_name','share_ratio','pub_date']])
        print ('市值'+str(market_cap_df['market_cap'].iloc[0])+'，流通市值'+str(market_cap_df['circulating_market_cap'].iloc[0])) 
        print ('流通股数'+str(capitalization)+'，实际流通股数'+str(effective_capitalization)) 
        print ('昨日成交量'+str(prices_df['volume'])) 
        print ('------------ 出错了！------------')
        return circulating_market_cap,circulating_turnover_ratio
    
    free_market_cap = effective_capitalization * prices_df['close'].iloc[0] / 1e8
    actual_turnover_ratio = 100 * prices_df['volume'].iloc[0] / effective_capitalization 

    #print (pub_date_str+', ' +stk)
    #print ('市值'+str(market_cap_df['market_cap'].iloc[0])+'，流通市值'+str(market_cap_df['circulating_market_cap'].iloc[0])) 
    #print ('流通股数'+str(capitalization)+', 昨日成交量'+str(prices_df['volume'].iloc[0]) + ', 换手率' + str(circulating_turnover_ratio) ) 
    #print ('实际流通股数'+str(effective_capitalization)+', 昨日成交量'+str(prices_df['volume'].iloc[0]) + ', 实际换手率' + str(actual_turnover_ratio) ) 

    #可能还有其他限售股，取最小的
    min_floating_cap = min(circulating_market_cap,free_market_cap)
    max_turnover_ratio = max(circulating_turnover_ratio,actual_turnover_ratio)
    if free_market_cap>circulating_market_cap:
        print ('最终采用的 流通市值 和 换手率：')
        print (min_floating_cap,max_turnover_ratio)

    return min_floating_cap, max_turnover_ratio

#某只股票的自由流通市值，即总股数扣减掉5%以上的大股东
def get_free_market_cap(stk, pub_date_str):
    #流通股本
    q = query(valuation.code,
        valuation.market_cap
    ).filter(
        valuation.code.in_([stk]),
    )
    market_cap_df = get_fundamentals(q, date=pub_date_str) #pub_date_str日的市值


    #还要再判断持股5%以上的股东，将其股数从股本中减掉
    #季报应该有吧？
    #pub_date_str = get_shifted_date(test_date_str, -62, days_type='T')
    q=query(
        finance.STK_SHAREHOLDER_TOP10.code,
        finance.STK_SHAREHOLDER_TOP10.shareholder_name,
        finance.STK_SHAREHOLDER_TOP10.share_number,
        finance.STK_SHAREHOLDER_TOP10.share_ratio,
        finance.STK_SHAREHOLDER_TOP10.pub_date,
           ).filter(
        finance.STK_SHAREHOLDER_TOP10.code==stk,
        finance.STK_SHAREHOLDER_TOP10.pub_date<pub_date_str,
    ).order_by(
        finance.STK_SHAREHOLDER_TOP10.pub_date.desc()
    ).limit(
        40
        )
    shareholder_df = finance.run_query(q)

    #print (stk+"【"+get_security_info(stk).display_name+"】,十大股东：" )
    #print (shareholder_df)
    if len(shareholder_df) <1:
        #print ('------------ 出错了！------------')
        #print (pub_date_str, stk, '找不到十大股东数据')
        #print ('------------ 出错了！------------')
        return 10000,100

    #如果没有十大股东，会取到上一次的数据，必须去重！！！
    shareholder_df = shareholder_df.dropna()
    #print (stk+"删除空余的行之后" )
    #print (stk+"【"+get_security_info(stk).display_name+"】,十大股东：")
    #print (shareholder_df)
    if len(shareholder_df) <1:
        #print ('------------ 出错了！------------')
        #print (pub_date_str, stk, '找不到十大股东数据')
        #print ('------------ 出错了！------------')
        return 10000,100
    else:
        latest_annual_report_date = shareholder_df['pub_date'].max() 
        shareholder_df = shareholder_df[shareholder_df['pub_date'] >= latest_annual_report_date]

    #print (stk+"去除更早财报中的十大股东数据之后：" )
    #print (stk+"【"+get_security_info(stk).display_name+"】,十大股东：")
    #print (shareholder_df)
    
    
    #当日收盘价
    prices_df = get_price(stk, end_date=pub_date_str, count=1, frequency='daily', 
                          fields=['close'], skip_paused=False, fq='pre') 

    #总股数 = 当日市值 / 当日收盘价
    capitalization = (1e8 * market_cap_df['market_cap'].iloc[0] / prices_df['close'].iloc[0])
    #print 'capitalization', capitalization

    sum_share_number = shareholder_df.loc[shareholder_df['share_ratio'] > 5, 'share_number'].sum() 
    effective_capitalization = capitalization - sum_share_number
    #print stk, 'effective_capitalization', effective_capitalization
    if effective_capitalization<0:
        print ('------------ 出错了！------------')
        print (pub_date_str, stk, '十大股东')
        print (shareholder_df)
        print ('市值和流通市值' )
        print (market_cap_df)
        print ('流通股数', capitalization)
        print ('实际流通股数', effective_capitalization)
        print ('------------ 出错了！------------')
        return 0  #表示出错了

    free_market_cap = effective_capitalization * prices_df['close'].iloc[0] / 1e8
    #print '-----------------------------------------'
    #print pub_date_str, stk, '十大股东'
    #print shareholder_df
    #print '市值和流通市值' 
    #print market_cap_df
    #print '流通股数', capitalization
    #print '实际流通股数', effective_capitalization
    #rint '【自由流通市值】', free_market_cap

    return free_market_cap



# 计算热门概念
def get_hot_concept(dct, date):
    # 计算出现涨停最多的概念 
    concept_count = {}
    for key in dct:
        for i in dct[key]['jq_concept']:
            if i['concept_name'] in concept_count.keys():
                concept_count[i['concept_name']] += 1
            else:
                if i['concept_name'] not in ['转融券标的', '融资融券', '深股通', '沪股通']:
                    concept_count[i['concept_name']] = 1
    df = pd.DataFrame(list(concept_count.items()), columns=['concept_name','concept_count'])
    df = df.set_index('concept_name')
    df = df.sort_values(by='concept_count', ascending=False)
    max_num = df.iloc[0,0]
    df = df[df['concept_count'] == max_num]
    concept = list(df.index)[0]
    return concept

# 概念筛选
def filter_concept_stock(dct, concept):
    tmp_set = set()
    for k,v in dct.items():
        for d in dct[k]['jq_concept']:
            if d['concept_name'] == concept:
                tmp_set.add(k)
    return list(tmp_set)



def sort_stocks_by_market_cap(context,stock_list):
    #log.info("sort_stocks_by_market_cap，按换手率由大到小排列。", len(stock_list))
    if len(stock_list)<=0:
        log.info("!!! 输入sort_stocks_by_market_cap的股票池是空的  !!!")
        return []

    q = query(valuation.code,
            valuation.market_cap,
            valuation.circulating_market_cap,
        ).filter(
            valuation.code.in_(stock_list)
        ).order_by(
            valuation.market_cap.asc()
        )
    df = get_fundamentals(q)
    stock_list = list(df["code"])

    return stock_list
    
# 筛选按因子值排名的股票
def sort_stocks_by_factor_df(context, stock_list, jqfactor, sort):
    if len(stock_list) != 0:
        yesterday = context.previous_date
        score_list = get_factor_values(stock_list, jqfactor, end_date=yesterday, count=1)[jqfactor].iloc[0].tolist()
        df = pd.DataFrame(index=stock_list, data={'score':score_list}).dropna()
        df = df.sort_values(by='score', ascending=sort)
    else:
        df = pd.DataFrame(index=[], data={'score':[]})
    return df


# 每日初始股票池
def prepare_stock_list(date): 
    initial_list = get_all_securities('stock', date).index.tolist()
    initial_list = filter_cykcbj_stock(initial_list)
    #initial_list = remove_black_listed_stock(initial_list)
    initial_list = filter_new_stock(initial_list, date)
    initial_list = filter_st_stock(initial_list, date)
    initial_list = filter_paused_stock(initial_list, date)
    return initial_list
    
# 筛选出某一日涨停的股票
def get_hl_stock(initial_list, date):
    df = get_price(initial_list, end_date=date, frequency='daily', fields=['close','high','high_limit'], count=1, panel=False, fill_paused=False, skip_paused=False)
    df = df.dropna() #去除停牌
    df = df[df['close'] == df['high_limit']]
    hl_list = list(df.code)
    return hl_list


# 计算连板数(新)
def get_continue_count_df1(hl_list, date, watch_days):
    
    def get_continue_count_list(lst):
        
        # 输入[0,1,1,0,1,1,1]，输出[0,1,2,0,1,2,3]
        lst0 = [0] + lst
        lst1 = lst0.copy()
        for i in range(1, len(lst0)):
            if lst0[i] == 1 and lst0[i-1] != 0:
                lst1[i] = lst0[i] + lst1[i-1]
        
        # 输入[0,1,2,0,1,2,3]，输出[0,0,2,0,0,0,3]
        lst2 = lst1.copy()
        for i in range(len(lst1)-1):
            if lst1[i] < lst1[i+1]:
                lst2[i] = 0
        return lst2[1:]

    df = get_price(hl_list, end_date=date, frequency='daily', fields=['close','high_limit'], count=watch_days, panel=False, fill_paused=False, skip_paused=False).dropna()
    df = pd.DataFrame(columns=['count'], data=df.groupby('code').apply(lambda df: max([0] + [i for i in list(get_continue_count_list(list(np.where(df['close'] == df['high_limit'], 1, 0)))) if i > 1])))
    return df



# 计算某区间内股票收益
def get_stock_ret_df(stock_list, sd, fq1, field1, ed, fq2, field2):
    start_price = get_price(stock_list, end_date=sd, frequency=fq1, fields=[field1], count=1, panel=False, fill_paused=True)
    end_price = get_price(stock_list, end_date=ed, frequency=fq2, fields=[field2], count=1, panel=False, fill_paused=True).drop(columns=['code'])
    df = pd.concat([start_price, end_price], axis=1)
    df['ret'] = end_price[field2] / start_price[field1] - 1
    df = df.set_index('code')
    return df



# 计算股票处于一段时间内相对位置
def get_relative_position_df(stock_list, date, watch_days):
    if len(stock_list) != 0:
        df = get_price(stock_list, end_date=date, fields=['high', 'low', 'close'], count=watch_days, fill_paused=False, skip_paused=False, panel=False).dropna()
        close = df.groupby('code').apply(lambda df: df.iloc[-1,-1])
        high = df.groupby('code').apply(lambda df: df['high'].max())
        low = df.groupby('code').apply(lambda df: df['low'].min())
        result = pd.DataFrame()
        result['rp'] = (close-low) / (high-low)
        result = result.dropna()
        return result
    else:
        return pd.DataFrame(columns=['rp'])

# 交易
def buy_all_cluo(context):
    
    #基础信息
    date = transform_date(context.previous_date, 'str')
    current_data = get_current_data()

    #剩余仓位
    remaining_ps = g.ps - len(context.portfolio.positions)

    target_list = g.target_list
    if len(target_list)>0:
        if remaining_ps>0: 
            value = context.portfolio.available_cash / remaining_ps
            target_list = target_list[0:remaining_ps]
            print('准备买入',target_list)

            #开盘涨停用限价单模拟排板，否则用市价单买入
            for s in target_list:
                if ((len(context.portfolio.positions) < 2) and (context.portfolio.available_cash/current_data[s].last_price > 100)): #由于关闭了错误日志，不加这一句，不足一手买入失败也会打印买入，造成日志不准确
                    if current_data[s].last_price == current_data[s].high_limit:
                        order_value(s, value, LimitOrderStyle(current_data[s].day_open))
                        print('买入', [s, get_security_info(s, date).display_name])
                        print('———————————————————————————————————')
                    else:
                        order_value(s, value, MarketOrderStyle(current_data[s].day_open))
                        print('买入', [s, get_security_info(s, date).display_name])
                        print('———————————————————————————————————')
        else:
            print('无剩余仓位，不买入')
            print('———————————————————————————————————')
            

'''
def sell(context):
    # 基础信息
    date = transform_date(context.previous_date, 'str')
    current_data = get_current_data()
    if str(context.current_dt)[-8:] == '09:30:00':
        stock_list = list(context.portfolio.positions)
        df =  get_price(stock_list, end_date=date, frequency='daily', fields=['close'], count=1, panel=False, fill_paused=False, skip_paused=True).set_index('code') if len(stock_list) != 0 else pd.DataFrame()
        for s in list(context.portfolio.positions):
            if ((context.portfolio.positions[s].closeable_amount != 0) and (current_data[s].day_open/df.loc[s]['close']<0.92)):
                order_target_value(s, 0)
                print( '垃圾股先跑', [get_security_info(s, date).display_name, s])
                print('———————————————————————————————————')

    # 根据时间执行不同的卖出策略
    if str(context.current_dt)[-8:] == '14:00:00':
        for s in list(context.portfolio.positions):
            if ((context.portfolio.positions[s].closeable_amount != 0) and (current_data[s].last_price < current_data[s].high_limit) and (current_data[s].last_price > context.portfolio.positions[s].avg_cost)):
                order_target_value(s, 0)
                print( '止盈卖出', [get_security_info(s, date).display_name, s])
                print('———————————————————————————————————')
    
    if str(context.current_dt)[-8:] == '14:50:00':
        for s in list(context.portfolio.positions):
            if ((context.portfolio.positions[s].closeable_amount != 0) and (current_data[s].last_price < current_data[s].high_limit)):
                order_target_value(s, 0)
                print( '止损卖出', [get_security_info(s, date).display_name, s])
                print('———————————————————————————————————')
'''

############################################################################################################################################################################
def sell_if_open_lower_than_92pct(context):
    # 基础信息
    date = transform_date(context.previous_date, 'str')
    current_data = get_current_data()

    stock_list = list(context.portfolio.positions)
    df =  get_price(stock_list, end_date=date, frequency='daily', fields=['close'], count=1, panel=False, fill_paused=False, skip_paused=True).set_index('code') if len(stock_list) != 0 else pd.DataFrame()
    for s in list(context.portfolio.positions):
        if ((context.portfolio.positions[s].closeable_amount != 0) and (current_data[s].day_open/df.loc[s]['close']<0.92)):
            order_target_value(s, 0)
            print( '垃圾股先跑', [get_security_info(s, date).display_name, s])
            print('———————————————————————————————————')

def sell_234_if_open_lower_than_96pct(context):
    # 基础信息
    date = transform_date(context.previous_date, 'str')
    current_data = get_current_data()

    stock_list = list(context.portfolio.positions)
    df =  get_price(stock_list, end_date=date, frequency='daily', fields=['close'], count=1, panel=False, fill_paused=False, skip_paused=True).set_index('code') if len(stock_list) != 0 else pd.DataFrame()
    for s in list(context.portfolio.positions):
        if ((context.portfolio.positions[s].closeable_amount != 0) and (current_data[s].day_open/df.loc[s]['close']<0.96)):
            order_target_value(s, 0)
            print( '垃圾股先跑', [get_security_info(s, date).display_name, s])
            print('———————————————————————————————————')


def sell_if_profit_and_not_HL(context):
    
    # 基础信息
    date = transform_date(context.previous_date, 'str')
    current_data = get_current_data()
    
    for s in list(context.portfolio.positions):
        if ((context.portfolio.positions[s].closeable_amount != 0) and (current_data[s].last_price < current_data[s].high_limit) and (current_data[s].last_price > context.portfolio.positions[s].avg_cost)):
            order_target_value(s, 0)
            print( '止盈卖出', [get_security_info(s, date).display_name, s])
            print('———————————————————————————————————')
    
def sell_if_not_HL(context):
    # 基础信息
    date = transform_date(context.previous_date, 'str')
    current_data = get_current_data()
    
    for s in list(context.portfolio.positions):
        if ((context.portfolio.positions[s].closeable_amount != 0) and (current_data[s].last_price < current_data[s].high_limit)):
            order_target_value(s, 0)
            print( '止损卖出', [get_security_info(s, date).display_name, s])
            print('———————————————————————————————————')

############################################################################################################################################################################

# 处理日期相关函数
def transform_date(date, date_type):
    if type(date) == str:
        str_date = date
        dt_date = dt.datetime.strptime(date, '%Y-%m-%d')
        d_date = dt_date.date()
    elif type(date) == dt.datetime:
        str_date = date.strftime('%Y-%m-%d')
        dt_date = date
        d_date = dt_date.date()
    elif type(date) == dt.date:
        str_date = date.strftime('%Y-%m-%d')
        dt_date = dt.datetime.strptime(str_date, '%Y-%m-%d')
        d_date = date
    dct = {'str':str_date, 'dt':dt_date, 'd':d_date}
    return dct[date_type]

def get_shifted_date(date, days, days_type='T'):
    #获取上一个自然日
    d_date = transform_date(date, 'd')
    yesterday = d_date + dt.timedelta(-1)
    #移动days个自然日
    if days_type == 'N':
        shifted_date = yesterday + dt.timedelta(days+1)
    #移动days个交易日
    if days_type == 'T':
        all_trade_days = [i.strftime('%Y-%m-%d') for i in list(get_all_trade_days())]
        #如果上一个自然日是交易日，根据其在交易日列表中的index计算平移后的交易日        
        if str(yesterday) in all_trade_days:
            shifted_date = all_trade_days[all_trade_days.index(str(yesterday)) + days + 1]
        #否则，从上一个自然日向前数，先找到最近一个交易日，再开始平移
        else: #否则，从上一个自然日向前数，先找到最近一个交易日，再开始平移
            for i in range(100):
                last_trade_date = yesterday - dt.timedelta(i)
                if str(last_trade_date) in all_trade_days:
                    shifted_date = all_trade_days[all_trade_days.index(str(last_trade_date)) + days + 1]
                    break
    return str(shifted_date)



# 过滤函数
def filter_new_stock(initial_list, date, days=250):
    d_date = transform_date(date, 'd')
    return [stock for stock in initial_list if d_date - get_security_info(stock).start_date > dt.timedelta(days=days)]

def filter_st_stock(initial_list, date):
    str_date = transform_date(date, 'str')
    if get_shifted_date(str_date, 0, 'N') != get_shifted_date(str_date, 0, 'T'):
        str_date = get_shifted_date(str_date, -1, 'T')
    df = get_extras('is_st', initial_list, start_date=str_date, end_date=str_date, df=True)
    df = df.T
    df.columns = ['is_st']
    df = df[df['is_st'] == False]
    filter_list = list(df.index)
    return filter_list

def filter_kcbj_stock(initial_list):
    return [stock for stock in initial_list if stock[0] != '4' and stock[0] != '8' and stock[:2] != '68' ]

def filter_cykcbj_stock(initial_list):
    return [stock for stock in initial_list if stock[0] != '4' and stock[0] != '8' and stock[:2] != '68' and stock[0] != '3']

def filter_paused_stock(initial_list, date):
    df = get_price(initial_list, end_date=date, frequency='daily', fields=['paused'], count=1, panel=False, fill_paused=True)
    df = df[df['paused'] == 0]
    paused_list = list(df.code)
    return paused_list

def filter_yzb(stock_list, date):
    stock_list1 = []
    for stock in stock_list:
        df = get_price(stock, end_date=date, frequency='1d', fields=['close','high','low','high_limit','open'], skip_paused=True, count=1)
        # print("过滤一字板",df) 
        if df['low'][0]!=df['high'][0]: stock_list1.append(stock)
    return stock_list1


# 过滤black list票
def remove_black_listed_stock(stock_list):
    for stock in stock_list[:]:
        if stock[:6] == '002989' or stock[:6] == '000017' or stock[:6] == '000963': 
            stock_list.remove(stock)
    return stock_list


########################################################
#买和卖时上传指令的示例
#3-2 交易模块-开仓
def open_position(context, security, value):
    order = order_target_value_(security, value)
    if order != None and order.filled > 0:
        return True
    return False

#3-3 交易模块-平仓
def close_position(context, position):
    security = position.security
    order = order_target_value_(security, 0)  # 可能会因停牌失败
    if order != None:
        if order.status == OrderStatus.held and order.filled == order.amount:
            return True
    return False



#头一天的交易额：用于回顾小市值的容量
def get_historical_high(stock_code, N_days=120):
    return attribute_history(stock_code, N_days, '1d', 'high', df=False)['high'].max()

#头一天的交易额：用于回顾小市值的容量
def get_money(stock_code, N_days_ago=1):
    return attribute_history(stock_code, N_days_ago, '1d', 'money', df=False)['money'][-N_days_ago]


# 记录持仓的股票 
def log_stocks_bought(context):
    current_data = get_current_data()   #获取日期
    hold_stocks = context.portfolio.positions.keys()

    try:
        log.info('----------------------------------------------------------------------')
        for s in hold_stocks:
            q = query(
                valuation.code,
                valuation.market_cap,
                valuation.circulating_market_cap,
                valuation.pe_ratio, 
                indicator.inc_total_revenue_year_on_year, 
                indicator.inc_total_revenue_annual,
                indicator.inc_operation_profit_year_on_year,
                indicator.inc_operation_profit_annual,
                ).filter(
                    valuation.code == s)
            df = get_fundamentals(q)
            log.info(\
                s,',',current_data[s].name,\
                ', 市值,',df['market_cap'][0],'亿',\
                ', 流通市值,',df['circulating_market_cap'][0],'亿',\
                ', 自由流通市值,', get_free_market_cap(s, context.previous_date ) ,'亿',\
                ', 昨日交易额,', get_money(s, N_days_ago=1)/1e8 ,'亿',\
                ', 市盈率TTM,',df['pe_ratio'][0],\
                ', 季度营收同比,',df['inc_total_revenue_year_on_year'][0],\
                ', 环比,',df['inc_total_revenue_annual'][0],\
                ', 季度经营利润同比,',df['inc_operation_profit_year_on_year'][0],\
                ', 环比,',df['inc_operation_profit_annual'][0]\
                )
    
        log.info('----------------------------------------------------------------------')
        for s in hold_stocks:
            #q = query(valuation.code,valuation.market_cap,valuation.circulating_market_cap,valuation.pe_ratio, indicator.inc_net_profit_year_on_year).filter(valuation.code == s)
            #df = get_fundamentals(q)
            log.info(\
                s,',',current_data[s].name,\
                ', 持股数量,',context.portfolio.positions[s].total_amount,'股',\
                ', 冻结数量,',context.portfolio.positions[s].locked_amount,'股',\
                ', 成本,',context.portfolio.positions[s].avg_cost,'元',\
                ', 现价,',current_data[s].last_price,'元',\
                ', 浮动盈亏, %.4f%%'%(current_data[s].last_price/context.portfolio.positions[s].avg_cost-1),\
                ', 持仓天数,',(context.current_dt-context.portfolio.positions[s].init_time).days\
                )
    
        log.info('----------------------------------------------------------------------')
        log.info('总资产', context.portfolio.total_value, \
                '， 股票 ', context.portfolio.positions_value,  \
                '， 现金', context.portfolio.available_cash,  \
                '， 仓位', context.portfolio.positions_value / context.portfolio.total_value )
    except:
        print ("打印交易日志出错了")
    
    log.info('####################################################################一天结束####################################################################')
        
        

