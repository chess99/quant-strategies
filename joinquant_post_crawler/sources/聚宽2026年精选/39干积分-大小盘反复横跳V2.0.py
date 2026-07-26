# 克隆自聚宽文章：https://www.joinquant.com/post/47337
# 标题：干积分-大小盘反复横跳V2.0
# 作者：MarioC

from jqdata import *
from jqfactor import *
import numpy as np
import pandas as pd
import pickle
import talib
import warnings
warnings.filterwarnings("ignore")
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
    g.no_trading_today_signal = False
    g.stock_num = 5
    g.hold_list = []  # 当前持仓的全部股票
    g.yesterday_HL_list = []  # 记录持仓中昨日涨停的股票
    # 设置交易运行时间
    run_daily(prepare_stock_list, '9:05')
    # run_weekly(weekly_adjustment, 1, '9:30')
    run_monthly(weekly_adjustment, 1, '9:30')
    # run_monthly(weekly_adjustment, 10, '9:30')
    # run_daily(sell_stocks, '9:30')
    run_daily(check_limit_up, '14:00')  # 检查持仓中的涨停股是否需要卖出
    run_daily(close_account, '14:30')

def sell_stocks(context):
    for stock in context.portfolio.positions.keys():
        # 股票盈利大于等于10%则卖出
        if context.portfolio.positions[stock].price >= context.portfolio.positions[stock].avg_cost * 1.40:
            order_target_value(stock, 0)
            log.debug("Selling out %s" % (stock))
        # 股票亏损大于等于-5%则卖出
        elif context.portfolio.positions[stock].price < context.portfolio.positions[stock].avg_cost * 0.95:
            order_target_value(stock, 0)
            log.debug("Selling out %s" % (stock))

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


    
#2-4 过滤股价高于10元的股票	
def filter_highprice_stock(context,stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] < 10]

# 基本面筛选，并根据小市值排序
def get_peg(context,stocks):
    # 获取基本面数据
    q = query(valuation.code,
                indicator.roe,
                indicator.roa,
                ).filter(
                    indicator.roe > 0.15,
                    indicator.roa > 0.10,
                    valuation.code.in_(stocks))
    df_fundamentals = get_fundamentals(q, date = None)       
    stocks = list(df_fundamentals.code)
    # fuandamental data
    df = get_fundamentals(query(valuation.code).filter(valuation.code.in_(stocks)).order_by(valuation.market_cap.asc()))
    choice = list(df.code)
    return choice

def get_recent_limit_up_stock(context, stock_list, recent_days):
    stat_date = context.previous_date
    new_list = []
    for stock in stock_list:
        df = get_price(stock, end_date=stat_date, frequency='daily', fields=['close','high_limit'], count=recent_days, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        if len(df) > 0:
            new_list.append(stock)
    return new_list
    
def SMALL(context):
    dt_last = context.previous_date
    stocks = get_all_securities('stock', dt_last).index.tolist()
    stocks = filter_kcbj_stock(stocks)
    choice = filter_st_stock(stocks)
    choice = filter_paused_stock(choice)
    choice = filter_new_stock(context, choice)
    choice = filter_limitup_stock(context,choice)
    choice = filter_limitdown_stock(context,choice)
    choice = filter_highprice_stock(context,choice)
    
    choice = get_peg(context,choice)
    recent_limit_up_list = get_recent_limit_up_stock(context, choice, 40)
    black_list = list(set(g.hold_list).intersection(set(recent_limit_up_list)))
    target_list = [stock for stock in choice if stock not in black_list]
    check_out_lists = target_list[:g.stock_num]
    return check_out_lists
    
def BIG(context):
    dt_last = context.previous_date
    stocks = get_all_securities('stock', dt_last).index.tolist()
    stocks = filter_kcbj_stock(stocks)
    choice = filter_st_stock(stocks)
    choice = filter_paused_stock(choice)
    choice = filter_new_stock(context, choice)
    choice = filter_limitup_stock(context,choice)
    choice = filter_limitdown_stock(context,choice)

    BIG_stock_list = get_fundamentals(query(
        valuation.code,
    ).filter(
        valuation.code.in_(stocks),
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


# 1-3 整体调整持仓
def weekly_adjustment(context):
    yesterday = context.previous_date
    now_time = context.current_dt
    stockList_2000=get_index_stocks('399303.XSHE',now_time)
    stockList_500=get_index_stocks('399905.XSHE',now_time)
    h_ratio = get_price(stockList_2000, end_date = yesterday , frequency='1d', fields=['close'], count=20)['close']
    first_row = h_ratio.iloc[0]
    last_row = h_ratio.iloc[-1]
    change_BIG = (last_row - first_row) / first_row * 100
    mean_BIG = np.mean(change_BIG)
    h_ratio = get_price(stockList_500, end_date = yesterday , frequency='1d', fields=['close'], count=20)['close']
    first_row = h_ratio.iloc[0]
    last_row = h_ratio.iloc[-1]
    change_SMALL = (last_row - first_row) / first_row * 100
    mean_SMALL = np.mean(change_SMALL)
    if (mean_BIG/mean_SMALL)>1.2:
        print('本月赌场开大')
        target_list = BIG(context)
        for stock in g.hold_list:
            if (stock not in target_list) and (stock not in g.yesterday_HL_list):
                position = context.portfolio.positions[stock]
                close_position(position)

        position_count = len(context.portfolio.positions)
        target_num = len(target_list)
        if target_num > position_count:
            value = context.portfolio.cash / (target_num - position_count)
            for stock in target_list:
                if context.portfolio.positions[stock].total_amount == 0:
                    if open_position(stock, value):
                        if len(context.portfolio.positions) == target_num:
                            break


    else:
        print('本月赌场开小')
        target_list = SMALL(context)
        for stock in g.hold_list:
            if (stock not in target_list) and (stock not in g.yesterday_HL_list):
                position = context.portfolio.positions[stock]
                close_position(position)
        # 调仓买入
        position_count = len(context.portfolio.positions)
        target_num = len(target_list)
        if target_num > position_count:
            value = context.portfolio.cash / (target_num - position_count)
            for stock in target_list:
                if context.portfolio.positions[stock].total_amount == 0:
                    if open_position(stock, value):
                        if len(context.portfolio.positions) == target_num:
                            break


# 1-4 调整昨日涨停股票
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


# 4-1 判断今天是否为账户资金再平衡的日期
def today_is_between(context, start_date, end_date):
    today = context.current_dt.strftime('%m-%d')
    if (start_date <= today) and (today <= end_date):
        return True
    else:
        return False


# 4-2 清仓后次日资金可转
def close_account(context):
    if g.no_trading_today_signal == True:
        if len(g.hold_list) != 0:
            for stock in g.hold_list:
                position = context.portfolio.positions[stock]
                close_position(position)
                log.info("卖出[%s]" % (stock))

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


