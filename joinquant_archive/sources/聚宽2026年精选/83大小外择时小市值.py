# 克隆自聚宽文章：https://www.joinquant.com/post/50470
# 标题：大小外择时小市值
# 作者：aqa

from jqdata import *
from jqfactor import *
import numpy as np
import pandas as pd
import pickle
import talib
import warnings
from jqlib.technical_analysis import *
warnings.filterwarnings("ignore")
# 初始化函数
def initialize(context):
    # 设定基准
    set_benchmark('000300.XSHG')
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
    g.no_trading_today_signal = False

    g.stock_num = 3
    g.highest = 50 
    g.hold_list = []  # 当前持仓的全部股票
    g.yesterday_HL_list = []  # 记录持仓中昨日涨停的股票
    g.bought_stocks = {} #记录补跌的股票和金额
    g.foreign_ETF = [
        '518880.XSHG',
        '513030.XSHG',
        '513100.XSHG',
        '164824.XSHE',
        '159866.XSHE',
        ]
    # 设置交易运行时间
    run_daily(prepare_stock_list, '9:05')
    run_monthly(singal, 1, '9:00')
    run_weekly(clear, 1, '9:30')
    run_weekly(monthly_adjustment, 1, '9:30')
    run_daily(stop_loss, '14:00')

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
        
def clear(context):#卖出补跌的仓位
    print(g.bought_stocks)
    if g.bought_stocks!={}:
        for stock, amount in g.bought_stocks.items():
            if stock in context.portfolio.positions:
                order_value(stock, -amount)  # 卖出股票至目标价值为0
                log.info("卖出补跌股票: %s, 卖出金额: %s" % (stock, amount))
            # 清空记录
        g.bought_stocks.clear()
    
def stop_loss(context):
    if not hasattr(g, 'bought_stocks'):
        g.bought_stocks ={}
    num = 0
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
                num = num+1
            else:
                log.info("[%s]涨停，继续持有" % (stock))
    SS=[]
    S=[]
    for stock in g.hold_list:
        if stock in list(context.portfolio.positions.keys()):
            if context.portfolio.positions[stock].price < context.portfolio.positions[stock].avg_cost * 0.85:
                order_target_value(stock, 0)
                log.debug("止损 Selling out %s" % (stock))
                num = num+1
            
            else:
                S.append(stock)
                NOW = (context.portfolio.positions[stock].price - context.portfolio.positions[stock].avg_cost)/context.portfolio.positions[stock].avg_cost
                SS.append(np.array(NOW))
   

    if num >=1:
        if len(SS) > 0:
            # 清空记录
            num=3
            min_values = sorted(SS)[:num]
            min_indices = [SS.index(value) for value in min_values]
            min_strings = [S[index] for index in min_indices]
            cash = context.portfolio.cash/num
            for ss in min_strings:
                order_value(ss, cash)
                log.debug("补跌最多的N支 Order %s" % (ss))
                if ss not in g.bought_stocks:
                    g.bought_stocks[ss] = cash
    
def filter_roic(context,stock_list):
    yesterday = context.previous_date
    list=[]
    for stock in stock_list:
        roic=get_factor_values(stock, 'roic_ttm', end_date=yesterday,count=1)['roic_ttm'].iloc[0,0]
        if roic>0.08:
            list.append(stock)
    return list
def filter_highprice_stock(context,stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] < 10]
def filter_highprice_stock2(context,stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] < 300]
def get_recent_limit_up_stock(context, stock_list, recent_days):
    stat_date = context.previous_date
    new_list = []
    for stock in stock_list:
        df = get_price(stock, end_date=stat_date, frequency='daily', fields=['close','high_limit'], count=recent_days, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        if len(df) > 0:
            new_list.append(stock)
    return new_list
def get_recent_down_up_stock(context, stock_list, recent_days):
    stat_date = context.previous_date
    new_list = []
    for stock in stock_list:
        df = get_price(stock, end_date=stat_date, frequency='daily', fields=['close','low_limit'], count=recent_days, panel=False, fill_paused=False)
        df = df[df['close'] == df['low_limit']]
        if len(df) > 0:
            new_list.append(stock)
    return new_list

#1-2 选股模块
def get_stock_list(context):
    final_list = []
    MKT_index = '399101.XSHE'
    initial_list = get_index_stocks(MKT_index)
    initial_list = filter_new_stock(context, initial_list)
    initial_list = filter_kcbj_stock(initial_list)
    initial_list = filter_st_stock(initial_list)
    
    q = query(valuation.code,valuation.market_cap).filter(valuation.code.in_(initial_list),valuation.market_cap.between(5,30)).order_by(valuation.market_cap.asc())
    df_fun = get_fundamentals(q)
    df_fun = df_fun[:100]
    
    initial_list = list(df_fun.code)
    initial_list = filter_paused_stock(initial_list)
    initial_list = filter_limitup_stock(context, initial_list)
    initial_list = filter_limitdown_stock(context, initial_list)
    #print('initial_list中含有{}个元素'.format(len(initial_list)))
    q = query(valuation.code,valuation.market_cap).filter(valuation.code.in_(initial_list)).order_by(valuation.market_cap.asc())
    df_fun = get_fundamentals(q)
    df_fun = df_fun[:50]
    final_list  = list(df_fun.code)
    return final_list


#1-2 选股模块
def get_stock_list_2(context):
    final_list = []
    MKT_index = '399101.XSHE'
    initial_list = get_index_stocks(MKT_index)
    initial_list = filter_new_stock(context, initial_list)
    initial_list = filter_kcbj_stock(initial_list)
    initial_list = filter_st_stock(initial_list)
    # 国九更新：过滤近一年净利润为负且营业收入小于1亿的
    # 国九更新：过滤近一年期末净资产为负的 (经查询没有为负数的，所以直接pass这条)
    # 国九更新：过滤近一年审计建议无法出具或者为负面建议的 (经过净利润等筛选，审计意见几乎不会存在异常)
    q = query(
        valuation.code,
        valuation.market_cap,  # 总市值 circulating_market_cap/market_cap
        income.np_parent_company_owners,  # 归属于母公司所有者的净利润
        income.net_profit,  # 净利润
        income.operating_revenue  # 营业收入
        #security_indicator.net_assets
    ).filter(
        valuation.code.in_(initial_list),
        valuation.market_cap.between(5,30),
        income.np_parent_company_owners > 0,
        income.net_profit > 0,
        income.operating_revenue > 1e8
    ).order_by(valuation.market_cap.asc()).limit(50)
    
    df = get_fundamentals(q)
    
    final_list = list(df.code)
    last_prices = history(1, unit='1d', field='close', security_list=final_list)
    

    return [stock for stock in final_list if stock in g.hold_list or last_prices[stock][-1] <= g.highest]

    
def SMALL(context, choice):
    
    target_list_1 = get_stock_list(context)
    target_list_2 = get_stock_list_2(context)
    target_list= list(dict.fromkeys(target_list_1 + target_list_2))
    target_list=target_list[:g.stock_num*3]
    #target_list = get_stock_list_2(context)[:g.stock_num*3]
    final_list = get_fundamentals(query(
        valuation.code,
        indicator.roe,
        indicator.roa,
    ).filter(
        valuation.code.in_(target_list),
        #valuation.pb_ratio<1
    ).order_by(
        valuation.market_cap.asc()
    )).set_index('code').index.tolist()
    return final_list
    
def BIG(context,choice):
    
    BIG_stock_list = get_fundamentals(query(
        valuation.code,
    ).filter(
        valuation.code.in_(choice),
        valuation.pe_ratio_lyr.between(0,30),#市盈率
        valuation.ps_ratio.between(0,8),#市销率TTM
        valuation.pcf_ratio<10,#市现率TTM
        indicator.eps>0.3,#每股收益
        indicator.roe>0.1,#净资产收益率
        indicator.net_profit_margin>0.1,#销售净利率
        indicator.gross_profit_margin>0.3,#销售毛利率
        indicator.inc_revenue_year_on_year>0.25,#营业收入同比增长率
    ).order_by(
    valuation.market_cap.desc()).limit(g.stock_num)).set_index('code').index.tolist()

    return BIG_stock_list
    
def ROIC_BIG(context,choice):
    final_list = get_fundamentals(query(
        valuation.code, valuation.market_cap, valuation.pe_ratio, income.total_operating_revenue
        ).filter(
        valuation.pb_ratio < 1,
        valuation.market_cap>50,
        #valuation.pb_ratio > 0.5,
        cash_flow.subtotal_operate_cash_inflow > 1e6,
        indicator.adjusted_profit > 1e6,
        indicator.roa > 0.15,
        #balance.development_expenditure>5000000,
        indicator.inc_net_profit_year_on_year > 0,
    	valuation.code.in_(choice)
    	).order_by(
    	indicator.roa.desc()
        ).limit(g.stock_num)).set_index('code').index.tolist()
    return final_list
    
def BM(context,choice):
    BM_list = get_fundamentals(query(
            valuation.code,
        ).filter(
            valuation.code.in_(choice),
            valuation.market_cap.between(100,900),#总市值（亿元）
            valuation.pb_ratio.between(0,10),#市净率
            valuation.pcf_ratio<4,#市现率TTM
            indicator.eps>0.3,#每股收益
            indicator.roe>0.2,#净资产收益率
            indicator.net_profit_margin>0.1,#销售净利率
            indicator.inc_revenue_year_on_year>0.2,#营业收入同比增长率
            indicator.inc_operation_profit_year_on_year>0.1,#营业利润同比增长率
        ).order_by(
        valuation.market_cap.asc()).limit(g.stock_num)).set_index('code').index.tolist()
    return BM_list
    
def singal(context):
    today = context.current_dt
    dt_last = context.previous_date
    N=10
    B_stocks = get_index_stocks('000300.XSHG', dt_last)
    B_stocks = filter_kcbj_stock(B_stocks)
    B_stocks = filter_st_stock(B_stocks)
    B_stocks = filter_new_stock(context, B_stocks)
    
    S_stocks = get_index_stocks('399101.XSHE', dt_last)
    S_stocks = filter_kcbj_stock(S_stocks)
    S_stocks = filter_st_stock(S_stocks)
    S_stocks = filter_new_stock(context, S_stocks)
    
    q = query(
        valuation.code, valuation.circulating_market_cap
    ).filter(
        valuation.code.in_(B_stocks)
    ).order_by(
        valuation.circulating_market_cap.desc()
    )
    df = get_fundamentals(q, date=dt_last)
    Blst = list(df.code)[:20]
    
    q = query(
        valuation.code, valuation.circulating_market_cap
    ).filter(
        valuation.code.in_(S_stocks)
    ).order_by(
        valuation.circulating_market_cap.asc()
    )
    df = get_fundamentals(q, date=dt_last)
    Slst = list(df.code)[:20]
    #
    B_ratio = get_price(Blst, end_date=dt_last, frequency='1d', fields=['close'], count=N, panel=False
                        ).pivot(index='time', columns='code', values='close')
    change_BIG = (B_ratio.iloc[-1] / B_ratio.iloc[0] - 1) * 100
    A1 = np.array(change_BIG)
    A1 = np.nan_to_num(A1)  
    B_mean = np.mean(A1)
    
    S_ratio = get_price(Slst, end_date=dt_last, frequency='1d', fields=['close'], count=N, panel=False
                        ).pivot(index='time', columns='code', values='close')
    change_SMALL = (S_ratio.iloc[-1] / S_ratio.iloc[0] - 1) * 100
    A1 = np.array(change_SMALL)
    A1 = np.nan_to_num(A1)
    S_mean = np.mean(A1)
    if B_mean>S_mean and B_mean>0:
        if B_mean>5:
           g.singal='small'
           print('大市值到头了，开小') 
        else:
            g.singal='big'
            print('开大')
    elif B_mean < S_mean and S_mean > 0:
        g.singal='small'
        print('开小')
    else:
        print('开外盘')
        g.singal='etf'
        
# 1-3 整体调整持仓
def monthly_adjustment(context):
    today = context.current_dt
    dt_last = context.previous_date
    target_list=[]
    print(g.singal)
    if g.singal=='big':
        B_stocks = get_index_stocks('000300.XSHG', dt_last)
        B_stocks = filter_kcbj_stock(B_stocks)
        B_stocks = filter_st_stock(B_stocks)
        B_stocks = boll_filter(B_stocks,dt_last)
        B_stocks = filter_new_stock(context, B_stocks)
        choice = B_stocks
        target_list1 = ROIC_BIG(context,choice)
        target_list2 = BIG(context,choice)
        target_list3 = BM(context,choice)
        target_list = target_list3+target_list1+target_list2
        target_list = list(set(target_list))
        
    elif g.singal=='small':
        S_stocks = get_index_stocks('399101.XSHE', dt_last)
        S_stocks = filter_kcbj_stock(S_stocks)
        S_stocks = filter_st_stock(S_stocks)
        S_stocks = filter_new_stock(context, S_stocks)       
        choice = S_stocks
        target_list = SMALL(context,choice)

        
    elif g.singal=='etf':
        target_list = g.foreign_ETF
    else:
        print("g.signal 的值不是预期中的一个")    
    
    print(target_list)
    target_list = filter_limitup_stock(context,target_list)
    target_list = filter_limitdown_stock(context,target_list)
    target_list = filter_paused_stock(target_list)
    for stock in g.hold_list:
        if (stock not in target_list) and (stock not in g.yesterday_HL_list):
            position = context.portfolio.positions[stock]
            close_position(position)
    position_count = len(context.portfolio.positions)
    target_num = len(target_list)
    if target_num > position_count:
        value = context.portfolio.cash / (target_num - position_count)
        for stock in target_list:
            if stock not in list(context.portfolio.positions.keys()):
                if open_position(stock, value):
                    if len(context.portfolio.positions) == target_num:
                        break
            
def boll_filter(stocks,date):
    x=get_bars(stocks, 1, unit='1d', fields=['high','low','close'],end_dt=date,df=True)
    x.index=stocks
    upperband, middleband, lowerband=Bollinger_Bands(stocks, date, timeperiod=20, 
                        nbdevup=2, nbdevdn=2, unit = '1d', include_now = True, fq_ref_date = None)
    x['up']= pd.DataFrame(upperband, index=[0]).T.values
    x['mid']=pd.DataFrame(middleband, index=[0]).T.values
    x['lowe']=pd.DataFrame(lowerband, index=[0]).T.values
    x=x[(x['close']<x['up'])&(x['lowe']<x['low'])]
    return(list(x.index))

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


