# 克隆自聚宽文章：https://www.joinquant.com/post/46331
# 标题：WY大神的“龙头打板”策略小改
# 作者：苗老八

# 克隆自聚宽文章：https://www.joinquant.com/post/44926
# 标题：连板龙头策略
# 作者：wywy1995

from jqdata import *
from jqfactor import *
from jqlib.technical_analysis import *
import datetime as dt
import pandas as pd



def initialize(context):
    # 系统设置
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    log.set_level('system', 'error')
    # 分仓数量
    g.ps = 10 #同时最高板龙头一般不会超过10个
    # 聚宽因子
    g.jqfactor = 'VOL5' #5日平均换手率（只是做为示例）
    g.sort = True #选取因子值最小
    
    g.notBuylst = [] # 买入失败的列表 第二天选股时剔除
    
    # 每日运行
    run_daily(get_stock_list, '9:01')
    run_daily(buy, '09:30')
    run_daily(stoploss, '10:30')
    run_daily(stoploss, '13:00')
    run_daily(stoploss, '14:00')
    run_daily(sell, 'every_bar')
    run_daily(print_position_info, '15:02')



# 选股
def get_stock_list(context): 

    # 文本日期
    date = context.previous_date
    date = transform_date(date, 'str')
    
    # 初始列表
    initial_list = prepare_stock_list(date)
    
    # 当日涨停
    hl_list = get_hl_stock(initial_list, date)
    
    # 全部连板股票
    ccd = get_continue_count_df(hl_list, date, 20) if len(hl_list) != 0 else pd.DataFrame(index=[], data={'count':[],'extreme_count':[]})
    
    # 最高连板
    M = ccd['count'].max() if len(ccd) != 0 else 0
    
    # 龙头
    ccd0 = pd.DataFrame(index=[], data={'count':[],'extreme_count':[]})
    CCD = ccd[ccd['count'] == M] if M != 0 else ccd0
    lt = list(CCD.index)

    #可以利用多个因子对lt进行进一步筛选大幅提高收益并降低回撤，使用到的因子见代码末尾

    #打印全部合格股票
    df = get_factor_filter_df(context, lt, g.jqfactor, g.sort)
    stock_list = list(df.index)
    
    #################
    stock_list = remove_values(stock_list,g.notBuylst) 
    #################
    
    
    #根据仓位截取列表
    g.target_list = stock_list[:(g.ps - len(context.portfolio.positions))]
    



# 定义一个函数，用于从list1中移除list2中存在的值
def remove_values(list1, list2):
    return [value for value in list1 if value not in list2]

# 交易
def buy(context):
    current_data = get_current_data()
    value = context.portfolio.total_value / g.ps
    
    for s in g.target_list:
        #由于关闭了错误日志，不加这一句，不足一手买入失败也会打印买入，造成日志不准确
        if context.portfolio.available_cash/current_data[s].last_price>100: 
            # 如果开盘涨停，用限价单排板
            if current_data[s].last_price == current_data[s].high_limit:
                order_value(s, value, LimitOrderStyle(current_data[s].day_open))
                print('限价单买入' + s)
                print('———————————————————————————————————')
            # 如果开盘未涨停，用市价单即刻买入
            else:
                order_value(s, value, MarketOrderStyle(current_data[s].day_open))
                print('市价单买入' + s)
                print('———————————————————————————————————')
                

            # 每日收盘后  查看今日买入和今日选股的列表是否一致  
            # 若不一致则说明有买入失败  则在每日剔除该个股
                
                

def sell(context):
    hold_list = list(context.portfolio.positions)
    current_data = get_current_data()
    hour = context.current_dt.hour
    minute = context.current_dt.minute

    # ------------------处理卖出-------------------
    if minute > 50 and hour == 14:
        for s in hold_list:
            # 条件1：不涨停
            if not (current_data[s].last_price == current_data[s].high_limit):
                if context.portfolio.positions[s].closeable_amount != 0:
                    
                    # 条件2.1：持有一定时间  2天
                    start_date = transform_date(context.portfolio.positions[s].init_time, 'str')
                    target_date = get_shifted_date(start_date, 2, 'T')
                    current_date = transform_date(context.current_dt, 'str')
                    
                    # 条件2.2：已经盈利
                    cost = context.portfolio.positions[s].avg_cost
                    price = context.portfolio.positions[s].price
                    ret = 100 * (price/cost-1)
                    
                    # 在满足条件1的前提下，条件2中只要满足一个即卖出
                    if current_date >= target_date or ret < 0:
                        if current_data[s].last_price > current_data[s].low_limit:
                            order_target_value(s, 0)
                            print('卖出' + s)
                            print('———————————————————————————————————')

# 可以收盘后判断风险决定第二天是否提前卖出，可以降低回撤

# 止损
def stoploss(context):
    hold_list = list(context.portfolio.positions)
    current_data = get_current_data()
    hour = context.current_dt.hour
    minute = context.current_dt.minute

    for s in hold_list:
        issell = False
        if context.portfolio.positions[s].closeable_amount != 0:
            cost = context.portfolio.positions[s].avg_cost
            price = context.portfolio.positions[s].price
            ret = 100 * (price/cost-1)
            # 条件1：已经亏损则直接卖出
            if ret < 0:
                if current_data[s].last_price > current_data[s].low_limit:
                    order_target_value(s, 0)
                    print('止损卖出' + s)
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
        else:
            for i in range(100):
                last_trade_date = yesterday - dt.timedelta(i)
                if str(last_trade_date) in all_trade_days:
                    shifted_date = all_trade_days[all_trade_days.index(str(last_trade_date)) + days + 1]
                    break
    return str(shifted_date)



# 过滤函数
def filter_new_stock(initial_list, date, days=50):
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
    return [stock for stock in initial_list if stock[0] != '4' and stock[0] != '8' and stock[:2] != '68']

def filter_paused_stock(initial_list, date):
    df = get_price(initial_list, end_date=date, frequency='daily', fields=['paused'], count=1, panel=False, fill_paused=True)
    df = df[df['paused'] == 0]
    paused_list = list(df.code)
    return paused_list

def filter_extreme_limit_stock(context, stock_list, date):
    tmp = []
    for stock in stock_list:
        df = get_price(stock, end_date=date, frequency='daily', fields=['low','high_limit'], count=1, panel=False)
        if df.iloc[0,0] < df.iloc[0,1]:
            tmp.append(stock)
    return tmp



# 每日初始股票池
def prepare_stock_list(date): 
    initial_list = get_all_securities('stock', date).index.tolist()
    initial_list = filter_kcbj_stock(initial_list)
    initial_list = filter_new_stock(initial_list, date)
    initial_list = filter_st_stock(initial_list, date)
    initial_list = filter_paused_stock(initial_list, date)
    return initial_list

# 初始化情绪列表
def get_init_emo_count(context, date):
    d1 = get_shifted_date(date, -3)
    d2 = get_shifted_date(date, -2)
    date_list = [d1, d2]
    emo_count = []
    for date in date_list:
        initial_list = prepare_stock_list(date)
        hl_list = get_hl_stock(initial_list, date)
        CCD = get_continue_count_df(hl_list, date, 20) if len(hl_list) != 0 else pd.DataFrame(index=[], data={'count':[],'extreme_count':[]})
        M = CCD['count'].max() if len(CCD) != 0 else 0
        emo_count.append(M)
    return emo_count



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



# 筛选出某一日涨停的股票
def get_hl_stock(initial_list, date):
    df = get_price(initial_list, end_date=date, frequency='daily', fields=['close','high_limit'], count=1, panel=False, fill_paused=False, skip_paused=False)
    df = df.dropna() #去除停牌
    df = df[df['close'] == df['high_limit']]
    hl_list = list(df.code)
    return hl_list
    
    
# 筛选出某一日涨停 且 剔除一字板 的股票
def get_hl_notlow_stock(initial_list, date):
    df = get_price(initial_list, end_date=date, frequency='daily', fields=['close','high_limit','low'], count=1, panel=False, fill_paused=False, skip_paused=False)
    df = df.dropna() #去除停牌
    df = df[df['close'] == df['high_limit']] 
    df = df[df['low'] < df['high_limit']] 
    hl_list = list(df.code)
    return hl_list

    

# 计算涨停数
def get_hl_count_df(hl_list, date, watch_days):
    # 获取watch_days的数据
    df = get_price(hl_list, end_date=date, frequency='daily', fields=['close','high_limit','low'], count=watch_days, panel=False, fill_paused=False, skip_paused=False)
    df.index = df.code
    #计算涨停与一字涨停数，一字涨停定义为最低价等于涨停价
    hl_count_list = []
    extreme_hl_count_list = []
    for stock in hl_list:
        df_sub = df.loc[stock]
        hl_days = df_sub[df_sub.close==df_sub.high_limit].high_limit.count()
        extreme_hl_days = df_sub[df_sub.low==df_sub.high_limit].high_limit.count()
        hl_count_list.append(hl_days)
        extreme_hl_count_list.append(extreme_hl_days)
    #创建df记录
    df = pd.DataFrame(index=hl_list, data={'count':hl_count_list, 'extreme_count':extreme_hl_count_list})
    return df

# 计算连板数
def get_continue_count_df(hl_list, date, watch_days):
    df = pd.DataFrame()
    for d in range(2, watch_days+1):
        HLC = get_hl_count_df(hl_list, date, d)
        CHLC = HLC[HLC['count'] == d]
        df = df.append(CHLC)
    stock_list = list(set(df.index))
    ccd = pd.DataFrame()
    for s in stock_list:
        tmp = df.loc[[s]]
        if len(tmp) > 1:
            M = tmp['count'].max()
            tmp = tmp[tmp['count'] == M]
        ccd = ccd.append(tmp)
    if len(ccd) != 0:
        ccd = ccd.sort_values(by='count', ascending=False)    
    return ccd



# 筛选按因子值排名的股票
def get_factor_filter_df(context, stock_list, jqfactor, sort):
    if len(stock_list) != 0:
        yesterday = context.previous_date
        log.info("\n筛选前：%s\n"%(stock_list))
        score_list = get_factor_values(stock_list, jqfactor, end_date=yesterday, count=1)[jqfactor].iloc[0].tolist()
        log.info("\n筛选后：%s"%(stock_list))
        df = pd.DataFrame(index=stock_list, data={'score':score_list}).dropna()
        df = df.sort_values(by='score', ascending=sort)
    else:
        df = pd.DataFrame(index=[], data={'score':[]})
    return df



# 打印持仓信息
def print_position_info(context):
    position_percent = 100 * context.portfolio.positions_value /  context.portfolio.total_value
    record(仓位 = round(position_percent, 2))
    #打印账户信息
    today_buylist = []
    for position in list(context.portfolio.positions.values()):
        securities=position.security
        cost=position.avg_cost
        price=position.price
        ret=100*(price/cost-1)
        value=position.value
        amount=position.total_amount
        
        #################################
        today_amount=position.today_amount
        if today_amount > 0:
            # 今天有买入的个股名
            today_buylist.append(securities)
        
        #################################        
        
        print('代码:{}'.format(securities))
        print('成本价:{}'.format(format(cost,'.2f')))
        print('现价:{}'.format(price))
        print('收益率:{}%'.format(format(ret,'.2f')))
        print('持仓(股):{}'.format(amount))
        print('市值:{}'.format(format(value,'.2f')))
        print('———————————————————————————————————')
        
    # g.notBuylst = [] # 每次交易重置买入失败的列表    
    g.notBuylst = remove_values(g.target_list,today_buylist) 
    
    log.info("今日选股列表：%s"%(g.target_list))
    log.info("今日已买入的个股列表：%s"%(today_buylist))
    log.info("今日买入失败列表：%s"%(g.notBuylst))
    
    print('———————————————————————————————————————分割线————————————————————————————————————————')


############################################################################################################################################################################
'''
    ## 市场特征
    #1 龙头
    ccd0 = pd.DataFrame(index=[], data={'count':[],'extreme_count':[]})
    CCD = ccd[ccd['count'] == M] if M != 0 else ccd0
    m = CCD['extreme_count'].min()
    CCD1 = CCD[CCD['extreme_count'] == m] if str(m) != 'nan' else ccd0
    lt = list(CCD1.index)
    #2 数量
    l = len(CCD)
    #3 晋级
    r = 100 * len(CCD) / len(hl_list) if len(hl_list) != 0 else 0
    #4 情绪
    emo = M
    g.emo_count.append(emo) #初始化时计算g.emo_count
    #5 周期
    cyc = g.emo_count[-1] if g.emo_count[-1] == max(g.emo_count[-3:]) and g.emo_count[-1] != 0 else 0 #根据连板数判断情绪周期  
    cyc = 1 if cyc == emo else 0
    
    ## 热门股票池
    try:
        dct = get_concept(hl_list, date)
        hot_concept = get_hot_concept(dct, date)
        hot_stocks = filter_concept_stock(dct, hot_concept)
    except:
        pass
    
    ## 龙头特征
    condition_dct = {}
    for s in lt:
        try:
            #6 独食
            ds = ccd.loc[s]['extreme_count']
            #7 市值
            sz = get_fundamentals(query(valuation.code, valuation.circulating_market_cap).filter(valuation.code==s), date).iloc[0,1]
            #8 换手
            hs = HSL([s], date)[0][s]
            #9 龙头概念
            try:
                c = 1 if s in hot_stocks else 0
            except:
                c = 0
            
            ## 逻辑判断
            condition = ''
            if hs? ds? emo?:
                # 上升周期
                if cyc? sz?:
                    condition += '上升周期 '
                # 资金接力
                if ds? hs? hs?:
                    condition += '资金接力 '
                # 题材初期
                if c? emo?:
                    condition += '题材初期(' + str(hot_concept) + ') '
                # 热点集中
                if l? r?:
                    condition += '热点集中 '
                # 情绪突破
                if emo?:
                    condition += '情绪突破 '
            #获取符合逻辑的列表
            if len(condition) != 0:
                condition_dct[s] = get_security_info(s, date).display_name+' —— ' + condition
        except:
            pass
    stock_list = list(condition_dct.keys())
'''
