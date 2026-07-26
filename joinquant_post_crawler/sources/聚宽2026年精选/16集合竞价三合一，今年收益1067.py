# 克隆自聚宽文章：https://www.joinquant.com/post/49474
# 标题：集合竞价三合一，今年收益1067%，年化198%
# 作者：jevon y

# 克隆自聚宽文章：https://www.joinquant.com/post/44901
# 标题：首板低开策略
# 作者：wywy1995

# 克隆自聚宽文章：https://www.joinquant.com/post/48523
# 标题：一进二集合竞价策略
# 作者：十足的小市值迷

# 克隆自聚宽文章：https://www.joinquant.com/post/49364
# 标题：一种弱转强的选股策略，年化100%以上
# 作者：紫露薇霜

# 2024/08/01  止损卖出修改为跌破5日均线

from jqdata import *
from jqfactor import *
from jqlib.technical_analysis import *
import datetime as dt
import pandas as pd
from datetime import datetime
from datetime import timedelta


def initialize(context):
    set_option('use_real_price', True)
    log.set_level('system', 'error')
    set_option('avoid_future_data', True)
    # 一进二
    run_daily(get_stock_list, '9:01')
    run_daily(buy, '09:26')
    run_daily(sell, time='11:25', reference_security='000300.XSHG')
    run_daily(sell, time='14:50', reference_security='000300.XSHG')


    # 首版低开
    # run_daily(buy2, '09:27') #9:25分知道开盘价后可以提前下单


# 选股
def get_stock_list(context): 
    # 文本日期
    date = context.previous_date
    date = transform_date(date, 'str')
    date_1=get_shifted_date(date, -1, 'T')
    date_2=get_shifted_date(date, -2, 'T')

    # 初始列表
    initial_list = prepare_stock_list(date)
    # 昨日涨停
    hl_list = get_hl_stock(initial_list, date)
    # 前日曾涨停
    hl1_list = get_ever_hl_stock(initial_list, date_1)
    # 前前日曾涨停
    hl2_list = get_ever_hl_stock(initial_list, date_2)
    # 合并 hl1_list 和 hl2_list 为一个集合，用于快速查找需要剔除的元素  
    elements_to_remove = set(hl1_list + hl2_list)  
    # 使用列表推导式来剔除 hl_list 中存在于 elements_to_remove 集合中的元素  
    hl_list = [stock for stock in hl_list if stock not in elements_to_remove] 
    
    g.target_list = hl_list
    
    # 昨日曾涨停
    h1_list = get_ever_hl_stock2(initial_list, date)
    # 上上个交易日涨停过滤
    elements_to_remove = get_hl_stock(initial_list, date_1)
    
    # 过滤上上个交易日涨停、曾涨停
    all_list = [stock for stock in h1_list if stock not in elements_to_remove]
    
    g.target_list2 = all_list
    




# 交易
def buy(context):
    qualified_stocks = [] 
    gk_stocks=[]
    dk_stocks=[]
    rzq_stocks=[]
    current_data = get_current_data()
    date_now = context.current_dt.strftime("%Y-%m-%d")
    mid_time1 = ' 09:15:00'
    end_times1 =  ' 09:26:00'
    start = date_now + mid_time1
    end = date_now + end_times1
    # 高开
    for s in g.target_list:
        # 条件一：均价，金额，市值，换手率
        prev_day_data = attribute_history(s, 1, '1d', fields=['close', 'volume', 'money'], skip_paused=True)
        avg_price_increase_value = prev_day_data['money'][0] / prev_day_data['volume'][0] / prev_day_data['close'][0] * 1.1 - 1
        if avg_price_increase_value < 0.07 or prev_day_data['money'][0] < 5.5e8 or prev_day_data['money'][0] > 20e8 :
            continue
        # market_cap 总市值(亿元) > 70亿 流通市值(亿元) < 520亿
        turnover_ratio_data=get_valuation(s, start_date=context.previous_date, end_date=context.previous_date, fields=['turnover_ratio', 'market_cap','circulating_market_cap'])
        if turnover_ratio_data.empty or turnover_ratio_data['market_cap'][0] < 70  or turnover_ratio_data['circulating_market_cap'][0] > 520 :
            continue
        # if turnover_ratio_data.empty or turnover_ratio_data['turnover_ratio'][0] < 5:
        #     continue
        
        # 条件二：左压
        zyts = calculate_zyts(s, context)
        volume_data = attribute_history(s, zyts, '1d', fields=['volume'], skip_paused=True)
        if len(volume_data) < 2 or volume_data['volume'][-1] <= max(volume_data['volume'][:-1]) * 0.9:
            continue
        
        # 条件三：高开,开比
        # log.info(s)
        auction_data = get_call_auction(s, start_date=start, end_date=end, fields=['time','volume', 'current'])
        # log.info(auction_data)
        if auction_data.empty or auction_data['volume'][0] / volume_data['volume'][-1] < 0.03:
            continue
        current_ratio = auction_data['current'][0] / (current_data[s].high_limit/1.1)
        if current_ratio<=1 or current_ratio>=1.06:
            continue

        # 如果股票满足所有条件，则添加到列表中  
        gk_stocks.append(s)
        qualified_stocks.append(s)

    
    # 低开    
    # 基础信息
    date = transform_date(context.previous_date, 'str')
    current_data = get_current_data()
    
    # 昨日涨停列表
    initial_list = prepare_stock_list2(date)
    hl_list = get_hl_stock(initial_list, date)
    
    if len(hl_list) != 0:    
        # 获取非连板涨停的股票
        ccd = get_continue_count_df(hl_list, date, 10)
        lb_list = list(ccd.index)
        stock_list = [s for s in hl_list if s not in lb_list]
        
        # 计算相对位置
        rpd = get_relative_position_df(stock_list, date, 60)
        rpd = rpd[rpd['rp'] <= 0.5]
        stock_list = list(rpd.index)
        
        # 低开
        df =  get_price(stock_list, end_date=date, frequency='daily', fields=['close'], count=1, panel=False, fill_paused=False, skip_paused=True).set_index('code') if len(stock_list) != 0 else pd.DataFrame()
        df['open_pct'] = [current_data[s].day_open/df.loc[s, 'close'] for s in stock_list]
        df = df[(0.955 <= df['open_pct']) & (df['open_pct'] <= 0.97)] #低开越多风险越大，选择3个多点即可
        stock_list = list(df.index)
        # send_message(','.join(stock_list))
        # print(df)

        for s in stock_list:
            prev_day_data = attribute_history(s, 1, '1d', fields=['close', 'volume', 'money'], skip_paused=True)
            if prev_day_data['money'][0] >= 1e8  :
                dk_stocks.append(s)
                qualified_stocks.append(s)
        
    # 弱转强
    for s in g.target_list2:
        # 过滤前面三天涨幅超过28%的票
        price_data = attribute_history(s, 4, '1d', fields=['close'], skip_paused=True)
        if len(price_data) < 4:
            continue
        increase_ratio = (price_data['close'][-1] - price_data['close'][0]) / price_data['close'][0]
        if increase_ratio > 0.28:
            continue
        
        # 过滤前一日收盘价小于开盘价5%以上的票
        prev_day_data = attribute_history(s, 1, '1d', fields=['open', 'close'], skip_paused=True)
        if len(prev_day_data) < 1:
            continue
        open_close_ratio = (prev_day_data['close'][0] - prev_day_data['open'][0]) / prev_day_data['open'][0]
        if open_close_ratio < -0.05:
            continue
        
        prev_day_data = attribute_history(s, 1, '1d', fields=['close', 'volume','money'], skip_paused=True)
        avg_price_increase_value = prev_day_data['money'][0] / prev_day_data['volume'][0] / prev_day_data['close'][0]  - 1
        if avg_price_increase_value < -0.04 or prev_day_data['money'][0] < 3e8 or prev_day_data['money'][0] > 19e8:
            continue
        turnover_ratio_data = get_valuation(s, start_date=context.previous_date, end_date=context.previous_date, fields=['turnover_ratio','market_cap','circulating_market_cap'])
        if turnover_ratio_data.empty or turnover_ratio_data['market_cap'][0] < 70  or turnover_ratio_data['circulating_market_cap'][0] > 520 :
            continue
        
        zyts = calculate_zyts(s, context)
        volume_data = attribute_history(s, zyts, '1d', fields=['volume'], skip_paused=True)
        if len(volume_data) < 2 or volume_data['volume'][-1] <= max(volume_data['volume'][:-1]) * 0.9:
            continue
        
        auction_data = get_call_auction(s, start_date=start, end_date=end, fields=['time','volume', 'current'])
        
        if auction_data.empty or auction_data['volume'][0] / volume_data['volume'][-1] < 0.03:
            continue
        current_ratio = auction_data['current'][0] / (current_data[s].high_limit/1.1)
        if current_ratio <= 0.98 or current_ratio >= 1.09:
            continue
        rzq_stocks.append(s)
        qualified_stocks.append(s)
    
    
    if len(qualified_stocks)>0:
        print('———————————————————————————————————')
        send_message('今日选股：'+','.join(qualified_stocks))
        print('一进二：'+','.join(gk_stocks))
        print('首板低开：'+','.join(dk_stocks))
        print('弱转强：'+','.join(rzq_stocks))
        print('今日选股：'+','.join(qualified_stocks))
        print('———————————————————————————————————')
    else:
        send_message('今日无目标个股')
        print('今日无目标个股')  
    
        
    if len(qualified_stocks)!=0  and context.portfolio.available_cash/context.portfolio.total_value>0.3:
        value = context.portfolio.available_cash / len(qualified_stocks)
        for s in qualified_stocks:
            # 下单
            #由于关闭了错误日志，不加这一句，不足一手买入失败也会打印买入，造成日志不准确
            if context.portfolio.available_cash/current_data[s].last_price>100: 
                order_value(s, value, MarketOrderStyle(current_data[s].day_open))
                print('买入' + s)
                print('———————————————————————————————————')

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
    return [stock for stock in initial_list 
    if stock[0] != '4' 
    and stock[0] != '8' 
    # and stock[0] != '3' 
    and stock[:2] != '68']

def filter_paused_stock(initial_list, date):
    df = get_price(initial_list, end_date=date, frequency='daily', fields=['paused'], count=1, panel=False, fill_paused=True)
    df = df[df['paused'] == 0]
    paused_list = list(df.code)
    return paused_list

# 一字
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


# 计算左压天数
def calculate_zyts(s, context):
    high_prices = attribute_history(s, 101, '1d', fields=['high'], skip_paused=True)['high']
    prev_high = high_prices.iloc[-1]
    zyts_0 = next((i-1 for i, high in enumerate(high_prices[-3::-1], 2) if high >= prev_high), 100)
    zyts = zyts_0 + 5
    return zyts


# 筛选出某一日涨停的股票
def get_hl_stock(initial_list, date):
    df = get_price(initial_list, end_date=date, frequency='daily', fields=['close','high_limit'], count=1, panel=False, fill_paused=False, skip_paused=False)
    df = df.dropna() #去除停牌
    df = df[df['close'] == df['high_limit']]
    hl_list = list(df.code)
    return hl_list
    
# 筛选曾涨停
def get_ever_hl_stock(initial_list, date):
    df = get_price(initial_list, end_date=date, frequency='daily', fields=['high','high_limit'], count=1, panel=False, fill_paused=False, skip_paused=False)
    df = df.dropna() #去除停牌
    df = df[df['high'] == df['high_limit']]
    hl_list = list(df.code)
    return hl_list

# 筛选曾涨停
def get_ever_hl_stock2(initial_list, date):
    df = get_price(initial_list, end_date=date, frequency='daily', fields=['close','high','high_limit'], count=1, panel=False, fill_paused=False, skip_paused=False)
    df = df.dropna() #去除停牌
    cd1 = df['high'] == df['high_limit'] 
    cd2 = df['close']!= df['high_limit']
    df = df[cd1 & cd2]
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

# 计算昨涨幅
def get_index_increase_ratio(index_code, context):
    # 获取指数昨天和前天的收盘价
    close_prices = attribute_history(index_code, 2, '1d', fields=['close'], skip_paused=True)
    if len(close_prices) < 2:
        return 0  # 如果数据不足，返回0
    day_before_yesterday_close = close_prices['close'][0]
    yesterday_close = close_prices['close'][1]
    
    # 计算涨幅
    increase_ratio = (yesterday_close - day_before_yesterday_close) / day_before_yesterday_close
    return increase_ratio

#上午有利润就跑
def sell(context):
    # 基础信息
    date = transform_date(context.previous_date, 'str')
    current_data = get_current_data()
    
    
    # 根据时间执行不同的卖出策略
    if str(context.current_dt)[-8:] == '11:25:00' :
        for s in list(context.portfolio.positions):
            if ((context.portfolio.positions[s].closeable_amount != 0) and (current_data[s].last_price < current_data[s].high_limit) and (current_data[s].last_price > 1*context.portfolio.positions[s].avg_cost)):#avg_cost当前持仓成本
                order_target_value(s, 0)
                print( '止盈卖出', [s,get_security_info(s, date).display_name])
                print('———————————————————————————————————')
    
    if str(context.current_dt)[-8:] == '14:50:00':
        for s in list(context.portfolio.positions):
            # close_data = attribute_history(s, 5, '1d', ['close'])
            #     # 取得过去五天的平均价格
            # MA5 = close_data['close'].mean()
            # print(MA5)
            close_data2 = attribute_history(s, 4, '1d', ['close'])
            M4=close_data2['close'].mean()
            MA5=(M4*4+current_data[s].last_price)/5
            # print(current_data[s].last_price)
            # if ((context.portfolio.positions[s].closeable_amount != 0) and (current_data[s].last_price < current_data[s].high_limit)): 
            if ((context.portfolio.positions[s].closeable_amount != 0) and (current_data[s].last_price < current_data[s].high_limit) and (current_data[s].last_price > 1*context.portfolio.positions[s].avg_cost)):#avg_cost当前持仓成本
                order_target_value(s, 0)
                print( '止盈卖出', [s,get_security_info(s, date).display_name])
                print('———————————————————————————————————')
            elif ((context.portfolio.positions[s].closeable_amount != 0) and (current_data[s].last_price < MA5)):
                #closeable_amount可卖出的仓位
                order_target_value(s, 0)
                print( '止损卖出', [s,get_security_info(s, date).display_name])
                print('———————————————————————————————————')  
                
                
# 首版低开策略代码                
def filter_new_stock2(initial_list, date, days=250):
    d_date = transform_date(date, 'd')
    return [stock for stock in initial_list if d_date - get_security_info(stock).start_date > dt.timedelta(days=days)]
    
    
# 每日初始股票池
def prepare_stock_list2(date): 
    initial_list = get_all_securities('stock', date).index.tolist()
    initial_list = filter_kcbj_stock(initial_list)
    initial_list = filter_new_stock2(initial_list, date)
    initial_list = filter_st_stock(initial_list, date)
    initial_list = filter_paused_stock(initial_list, date)
    return initial_list    
    
# 计算股票处于一段时间内相对位置
def get_relative_position_df(stock_list, date, watch_days):
    if len(stock_list) != 0:
        df = get_price(stock_list, end_date=date, fields=['high', 'low', 'close'], count=watch_days, fill_paused=False, skip_paused=False, panel=False).dropna()
        close = df.groupby('code').apply(lambda df: df.iloc[-1,-1])
        high = df.groupby('code').apply(lambda df: df['high'].max())
        low = df.groupby('code').apply(lambda df: df['low'].min())
        result = pd.DataFrame()
        result['rp'] = (close-low) / (high-low)
        return result
    else:
        return pd.DataFrame(columns=['rp'])    
    




