# 克隆自聚宽文章：https://www.joinquant.com/post/47033
# 标题：基于趋势、拥挤、景气的行业轮动，及行业强势个股的选择
# 作者：hayy

# 导入函数库
from jqdata import *
from jqfactor import *
from jqlib.technical_analysis import *
import datetime as dt
import pandas as pd
# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.0005, open_commission=0.0001, close_commission=0.0001, min_commission=1), type='stock')
    set_slippage(FixedSlippage(0.02))# 设置滑点  
    
    g.buyList = []
      # 开盘时运行
    # run_weekly(market_open, 1, time='open')
    run_monthly(market_open, 20, time='open')
    # run_daily(market_open, '9:30')

## 运行函数
def market_open(context):
    industry_codes = ["801010", "801030", "801040", "801050", "801080", "801110", "801120", "801130", "801140", 
                  "801150", "801160", "801170", "801180", "801200", "801210", "801230", "801710", 
                  "801720", "801730", "801740", "801750", "801760", "801770", "801780", "801790", 
                  "801880", "801890"]
    codes = get_factor(context, industry_codes)[0:2]
   # g.buyList = get_stocks_from_industry(context, codes)
    g.buyList = get_buyStock_from_industry(context, codes)
    rebalance_position(context, g.buyList)

# 该行业所有股票
def get_stocks_from_industry(context, codes):
    stock_list = []
    prepare_list = prepare_stock_list(context.previous_date)
    for code in codes:
        i_dt = (get_factor_values(prepare_list, code, context.previous_date, count=1))
        i_dt = i_dt[code].T.iloc[:,0]
        stock_list = stock_list+i_dt[i_dt == 1].index.tolist()
    return stock_list
    
# 为每个行业选择市值最大的20支股票代表整个行业情况（改成动态选择）
def get_star_stocks_from_industry(context, codes):
    stock_dict = dict()
    prepare_list = prepare_stock_list(context.previous_date)
    for code in codes:
        i_dt = (get_factor_values(prepare_list, code, context.previous_date, count=1))
        i_dt = i_dt[code].T.iloc[:,0]
        stock_dict[code] = sorted_by_circulating_market_cap(i_dt[i_dt == 1].index.tolist(), n_limit_top=int(round(len(prepare_list)/130)))
    return stock_dict

# 为每个行业选择强势个股
def get_buyStock_from_industry(context, industry_codes):
    stocks = []
    for code in industry_codes:
        stock_list = get_stocks_from_industry(context, [code])
                # 股票所属行业过去20日数据
        industry_data = finance.run_query(query(finance.SW1_DAILY_PRICE).filter(finance.SW1_DAILY_PRICE.code==code)
                          .filter(finance.SW1_DAILY_PRICE.date<=context.previous_date)
                          .order_by(finance.SW1_DAILY_PRICE.date.desc()).limit(20))
        industry_data.index = pd.to_datetime(industry_data.date)
        factor_values = pd.Series()
        for stock in stock_list:
            # 股票过去20日数据
            stock_data = attribute_history(stock, 20, unit='1d', fields=['close', 'pre_close', 'volume'], skip_paused=False, df=True, fq='pre')
            stock_data.insert(0, 'sy',stock_data.close/stock_data.pre_close-1)
            stock_data.insert(0, 'sy_volume',stock_data.sy*stock_data.volume)
            #股票收益×成交量最大的五天
            stock_sy_max5days = stock_data.sort_values(by = 'sy_volume', ascending = False).iloc[0:5,:]
            # 相对应的行业那5天
            industry_5days_from_stock = industry_data.loc[industry_data.index.isin(stock_sy_max5days.index)]
            factor_value = 0
            for i in range(0,5):
                change_pct = industry_5days_from_stock.loc[stock_sy_max5days.index[i]].change_pct
                weight = pow(2, -(i/(5-1)))
                factor_value = factor_value+weight*change_pct
            factor_values[stock] = factor_value
        stocks = stocks+factor_values.sort_values(ascending = False).index.tolist()[0:10]
    return stocks
    


# 获取因子
def get_factor(context, industry_codes):
    industry_dict = get_star_stocks_from_industry(context, industry_codes)
    
    # 动量因子 60天夏普比率
    factor_mom = pd.Series()
    for key in industry_dict.keys():
        stock_list = industry_dict[key]
        factor_mom_values = get_factor_values(stock_list, 'sharpe_ratio_60', end_date=context.previous_date, count=1)['sharpe_ratio_60'].iloc[0].dropna()
        factor_mom[key] =  -factor_mom_values.mean()
    
    factor_mom = (factor_mom-factor_mom.mean())/factor_mom.std()
    
    # 拥挤度因子
    factor_yj = pd.Series()
    for key in industry_dict.keys():
        stock_list = industry_dict[key]
        factor_yj_values = get_factor_values(stock_list, 'DAVOL20', end_date=context.previous_date, count=1)['DAVOL20'].iloc[0].dropna()
        factor_yj[key] =  factor_yj_values.mean()
    
    factor_yj = (factor_yj-factor_yj.mean())/factor_yj.std()
    
    
    # 分析师预期
    factor_cz = pd.Series()
    for key in industry_dict.keys():
        stock_list = industry_dict[key]
        factor_cz_values = get_factor_values(stock_list, 'long_term_predicted_earnings_growth', end_date=context.previous_date, count=1)['long_term_predicted_earnings_growth'].iloc[0].dropna()
        factor_cz[key] =  -factor_cz_values.mean()
    
    factor_cz = (factor_cz-factor_cz.mean())/factor_cz.std()
    
    
    # 外资看好
    factor_wz = pd.Series()
    for key in industry_dict.keys():
        stock_list = industry_dict[key]
        factor_wz_values = factor_beixiang(context, getAllData(context, stock_list), stock_list)
        factor_wz[key] =  -factor_wz_values.share_ratio_mean.mean()
    
    factor_wz = (factor_wz-factor_wz.mean())/factor_wz.std()
    
    
    factor_series = factor_mom+factor_yj+0.5*factor_cz+factor_wz
    factor_series = factor_series.sort_values(ascending=True)
    
    return factor_series.index
        


# 北向资金持股占流通股比例的20日均值
def factor_beixiang(context, allData, code_pool):
    factor2_dict = {}
    for code in code_pool:
        data = allData[allData.code == code]
        factor2_dict[code] = data.share_ratio.mean()
    data = pd.DataFrame(list(factor2_dict.items()),columns=['code', 'share_ratio_mean'])
    factor2 = data.sort_values('share_ratio_mean', ascending=False)
    return factor2        



def getAllData(context, code_pool):
    pre_date = context.previous_date
    pre_20_date = (pre_date+datetime.timedelta(days=-25)).strftime('%Y-%m-%d')  
    allData = finance.run_query(query(finance.STK_HK_HOLD_INFO).filter(finance.STK_HK_HOLD_INFO.day>=pre_20_date,
                                                                finance.STK_HK_HOLD_INFO.day<=pre_date,
                                                                finance.STK_HK_HOLD_INFO.link_id==310001,   
                                                                finance.STK_HK_HOLD_INFO.code.in_(code_pool)))
    allData2 = finance.run_query(query(finance.STK_HK_HOLD_INFO).filter(finance.STK_HK_HOLD_INFO.day>=pre_20_date,
                                                                finance.STK_HK_HOLD_INFO.day<=pre_date,
                                                                finance.STK_HK_HOLD_INFO.link_id==310002,   
                                                                finance.STK_HK_HOLD_INFO.code.in_(code_pool)))
    allData = allData.append(allData2)
    allData.day = allData.day.apply(lambda x:x.strftime('%Y-%m-%d'))
    return allData



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

# 剔除科创创业京
def filter_kcbj_stock(initial_list):
    return [stock for stock in initial_list if stock[0] != '4' and stock[0] != '8' and stock[:2] != '68' and stock[:2] != '30']

# 停牌
def filter_paused_stock(initial_list, date):
    df = get_price(initial_list, end_date=date, frequency='daily', fields=['paused'], count=1, panel=False, fill_paused=True)
    df = df[df['paused'] == 0]
    paused_list = list(df.code)
    return paused_list

# 筛选市值
def filter_market_cap(initial_list, date, left, right):
    df = get_valuation(initial_list, end_date=date, fields='circulating_market_cap', count=1)
    i = len(df)-1
    df = df.sort_values(by = 'circulating_market_cap')
    stocks = df.code.tolist()
    return stocks[int(i*left):int(i*right)]




# 将股票按照流通市值排序，只取前n_limit_top个
def sorted_by_circulating_market_cap(stock_list, n_limit_top=5):
    q = query(
        valuation.code,
    ).filter(
        valuation.code.in_(stock_list),
        indicator.eps > 0
    ).order_by(
        valuation.circulating_market_cap.desc()
    ).limit(
        n_limit_top
    )
    return get_fundamentals(q)['code'].tolist()


# 每日初始股票池
def prepare_stock_list(date): 
    initial_list = get_all_securities('stock', date).index.tolist()
    initial_list = filter_kcbj_stock(initial_list)
    initial_list = filter_new_stock(initial_list, date)
    initial_list = filter_st_stock(initial_list, date)
    initial_list = filter_paused_stock(initial_list, date)
    return initial_list


def rebalance_position(context, stock_list):
    current_holding = context.portfolio.positions.keys()
    stocks_to_sell = list(set(current_holding) - set(stock_list))
    # 卖出
    bulk_orders(stocks_to_sell, 0)
    total_value = context.portfolio.total_value

    if len(stock_list) >0 :
        # 买入
        bulk_orders(stock_list, total_value/len(stock_list))

# 批量买卖股票
def bulk_orders(stock_list,target_value):
    for i in stock_list:
        order_target_value(i, target_value)

# 日期转换函数
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

# 时间移动函数
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
    

