# 克隆自聚宽文章：https://www.joinquant.com/post/49180
# 标题：行业宽度轮动研究
# 作者：MarioC

from jqdata import *
from jqfactor import *
import numpy as np
import pandas as pd
import pickle
from six import StringIO,BytesIO # py3的环境，使用BytesIO
import talib

# 初始化函数
def initialize(context):
    # 设定基准
    set_benchmark('000985.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 设置交易成本万分之三，不同滑点影响可在归因分析中查看
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    # 初始化全局变量
    g.stock_num = 5
    g.hold_list = []  # 当前持仓的全部股票
    g.yesterday_HL_list = []  # 记录持仓中昨日涨停的股票
    g.num=1
    # 设置交易运行时间
    run_daily(prepare_stock_list, '9:05')
    # run_daily(weekly_adjustment,  '9:30')
    run_weekly(weekly_adjustment, 1, '9:30')
    # run_monthly(weekly_adjustment, 1, '9:30')
    run_daily(check_limit_up, '14:00')  # 检查持仓中的涨停股是否需要卖出
    
industry_code = ['801740','801120','801950','801780','801770']
SW1 = {
    '801740': '国防军工I',
    '801120': '食品饮料I',
    '801950': '煤炭I',
    '801780': '银行I',
    '801770': '通信I',
}

# 1-1 准备股票池
def prepare_stock_list(context):
    # 获取已持有列表
    g.hold_list = []
    for position in list(context.portfolio.positions.values()):
        stock = position.security
        g.hold_list.append(stock)
    # 获取昨日涨停列表
    if g.hold_list != []:
        df = get_price(g.hold_list, end_date=context.previous_date, frequency='daily', fields=['close', 'high_limit'],
                       count=1, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        g.yesterday_HL_list = list(df.code)
    else:
        g.yesterday_HL_list = []


def industry(stockList,industry_code,date):
    i_Constituent_Stocks={}
    for i in industry_code:
        temp = get_industry_stocks(i, date)
        i_Constituent_Stocks[i] = list(set(temp).intersection(set(stockList)))
    count_dict = {}
    for name, content_list in i_Constituent_Stocks.items():
        count = len(content_list)
        count_dict[name] = count
    return count_dict
    
def getStockIndustry(p_stocks, p_industries_type, p_day):
    dict_stk_2_ind = {}
    stocks_industry_dict = get_industry(p_stocks, date=p_day)
    for stock in stocks_industry_dict:
        if p_industries_type in stocks_industry_dict[stock]:
            if stocks_industry_dict[stock]['sw_l1']['industry_code'] in industry_code:
                dict_stk_2_ind[stock] = stocks_industry_dict[stock][p_industries_type]['industry_code']
    return pd.Series(dict_stk_2_ind)
# 1-2 选股模块
def get_stock_list(context):
    # 指定日期防止未来数据
    yesterday = context.previous_date
    today = context.current_dt
    final_list =[]
    # 获取初始列表
    initial_list = get_index_stocks('000985.XSHG', today)
    p_count=1
    p_industries_type='sw_l1'
    h = get_price(initial_list, end_date=yesterday, frequency='1d', fields=['close'], count=p_count + 20, panel=False)
    h['date'] = pd.DatetimeIndex(h.time).date
    df_close = h.pivot(index='code', columns='date', values='close').dropna(axis=0)
    df_ma20 = df_close.rolling(window=20, axis=1).mean().iloc[:, -p_count:]
    df_bias = (df_close.iloc[:, -p_count:] > df_ma20) 
    s_stk_2_ind = getStockIndustry(p_stocks=initial_list, p_industries_type=p_industries_type, p_day=yesterday)
    df_bias['industry_code'] = s_stk_2_ind
    df_ratio = ((df_bias.groupby('industry_code').sum() * 100.0) / df_bias.groupby(
        'industry_code').count()).round()  
    column_names = df_ratio.columns.tolist()
    top_values = df_ratio[datetime.date(yesterday.year, yesterday.month, yesterday.day)].nlargest(g.num)
    I   =  top_values.index.tolist()
    sum_of_top_values = df_ratio.sum()
    name_list = [SW1[code] for code in I]
    S_stocks = get_industry_stocks(I[0], yesterday)
    stocks = filter_kcbj_stock(S_stocks)
    choice = filter_st_stock(stocks)
    choice = filter_new_stock(context, choice)
    # choice=get_fundamentals(query(
    #         valuation.code,
    #     ).filter(
    #         valuation.code.in_(choice),
    #         indicator.roe > 0,
    #         indicator.roa > 0,
    #         # indicator.eps>0,#每股收益
    #     )).set_index('code').index.tolist()

    df = get_price(choice, end_date=yesterday, frequency='1d', fields=['close'], count=10, panel=False
                    ).pivot(index='time', columns='code', values='close')
    change_BIG = (df.iloc[-1] / df.iloc[0] - 1) * 100
    # BIG_stock_list = change_BIG.nlargest(g.stock_num).index.tolist()
    BIG_stock_list = change_BIG.nsmallest(g.stock_num).index.tolist()

    # BIG_stock_list = get_fundamentals(query(
    #         valuation.code,
    #     ).filter(
    #         valuation.code.in_(choice),
    #         indicator.roe > 0.15,
    #         indicator.roa > 0.10,
    #     ).order_by(
    # valuation.market_cap.desc()).limit(g.stock_num)).set_index('code').index.tolist()
    
    # BIG_stock_list = get_fundamentals(query(
    #     valuation.code,
    # ).filter(
    #     valuation.code.in_(choice),
    #     # valuation.pe_ratio_lyr.between(0,30),#市盈率
    #     # valuation.ps_ratio.between(0,8),#市销率TTM
    #     # valuation.pcf_ratio<10,#市现率TTM
    #     # indicator.eps>0.3,#每股收益
    #     # indicator.roe>0.1,#净资产收益率
    #     # indicator.net_profit_margin>0.1,#销售净利率
    #     # indicator.gross_profit_margin>0.3,#销售毛利率
    #     indicator.inc_revenue_year_on_year>0.25,#营业收入同比增长率
    # ).order_by(
    # valuation.market_cap.desc()).limit(g.stock_num)).set_index('code').index.tolist()
    
    BIG_stock_list = filter_paused_stock(BIG_stock_list)
    BIG_stock_list = filter_limitup_stock(context,BIG_stock_list)
    L = filter_limitdown_stock(context,BIG_stock_list)
    return L

# 1-3 整体调整持仓
def weekly_adjustment(context):
    target_B = get_stock_list(context)
    # 调仓卖出
    for stock in g.hold_list:
        if (stock not in target_B) and (stock not in g.yesterday_HL_list):
            position = context.portfolio.positions[stock]
            close_position(position)
    position_count = len(context.portfolio.positions)
    target_num = len(target_B)
    if target_num > position_count:
        buy_num = min(len(target_B), g.stock_num*g.num - position_count)
        value = context.portfolio.cash / buy_num
        for stock in target_B:
            if stock not in list(context.portfolio.positions.keys()):
                if open_position(stock, value):
                    if len(context.portfolio.positions) == target_num:
                        break
 
def check_limit_up(context):
    now_time = context.current_dt
    if g.yesterday_HL_list != []:
        # 对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
        for stock in g.yesterday_HL_list:
            current_data = get_price(stock, end_date=now_time, frequency='1m', fields=['close', 'high_limit'],
                                     skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True)
            if current_data.iloc[0, 0] < current_data.iloc[0, 1]:
                log.info("[%s]涨停打开，卖出" % (stock))
                position = context.portfolio.positions[stock]
                close_position(position)
            else:
                log.info("[%s]涨停，继续持有" % (stock))

# 3-1 交易模块-自定义下单
def order_target_value_(security, value):
    if value == 0:
        log.debug("Selling out %s" % (security))
    else:
        log.debug("Order %s to value %f" % (security, value))
    return order_target_value(security, value)


# 3-2 交易模块-开仓
def open_position(security, value):
    order = order_target_value_(security, value)
    if order != None and order.filled > 0:
        return True
    return False


# 3-3 交易模块-平仓
def close_position(position):
    security = position.security
    order = order_target_value_(security, 0)  # 可能会因停牌失败
    if order != None:
        if order.status == OrderStatus.held and order.filled == order.amount:
            return True
    return False


# 2-1 过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]


# 2-2 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list
            if not current_data[stock].is_st
            and 'ST' not in current_data[stock].name
            and '*' not in current_data[stock].name
            and '退' not in current_data[stock].name]


# 2-3 过滤科创北交股票
def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68' or stock[0] == '3':
            stock_list.remove(stock)
    return stock_list


# 2-4 过滤涨停的股票
def filter_limitup_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] < current_data[stock].high_limit]


# 2-5 过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] > current_data[stock].low_limit]


# 2-6 过滤次新股
def filter_new_stock(context, stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if
            not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=375)]


