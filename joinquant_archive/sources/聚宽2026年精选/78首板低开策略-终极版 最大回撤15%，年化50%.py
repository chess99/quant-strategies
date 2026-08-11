# 克隆自聚宽文章：https://www.joinquant.com/post/49434
# 标题：首板低开策略-终极版  最大回撤15%，年化50%
# 作者：蓝猫量化

# 导入函数库
from jqlib.technical_analysis import *
from jqfactor import *
from jqdata import *
import datetime as dt
import pandas as pd


# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    
    run_daily(sell_if_limit_down_yesterday, '09:30')
    run_daily(buy, '09:30')
    run_daily(sell, '11:25')
    run_daily(sell, '14:30')


def buy(context):
    # 基础信息
    date = get_previous_trade_day(context, 0)
    stock_list_with_ST = prepare_stock_list(context)
    stock_list_not_ST = prepare_stock_list2(context)

    stock_list = stock_list_with_ST+stock_list_not_ST

    if len(stock_list) > 0:
        print(f"今日待选池为：{stock_list}")
        # 获取当前账户的现金余额
        cash = context.portfolio.cash
        # 买入
        if cash > 0:
            for s in stock_list:
                order_target_value(s, cash / len(stock_list))
                print('买入', [get_security_info(s, date).display_name, s])
                print('———————————————————————————————————')
        else:
            print("当前账户没有现金,无法买入")


def sell(context):
    # 基础信息
    date = get_previous_trade_day(context, 0)
    current_data = get_current_data()

    # 根据时间执行不同的卖出策略
    if str(context.current_dt)[-8:] == '11:25:00':
        for s in list(context.portfolio.positions):
            if ((context.portfolio.positions[s].closeable_amount != 0) and
                    (current_data[s].last_price < current_data[s].high_limit) and
                    (current_data[s].last_price > context.portfolio.positions[s].avg_cost)):
                order_target_value(s, 0)
                print('止盈卖出', [get_security_info(s, date).display_name, s])
                print('———————————————————————————————————')

    if str(context.current_dt)[-8:] == '14:30:00':
        for s in list(context.portfolio.positions):
            if ((context.portfolio.positions[s].closeable_amount != 0) and
                    (current_data[s].last_price < current_data[s].high_limit)):
                order_target_value(s, 0)
                if current_data[s].last_price > context.portfolio.positions[s].avg_cost:
                    print('止盈卖出', [get_security_info(s, date).display_name, s])
                    print('———————————————————————————————————')
                else:
                    print('止损卖出', [get_security_info(s, date).display_name, s])
                    print('———————————————————————————————————')

def sell_if_limit_down_yesterday(context):
    # 获取持仓股票列表
    positions = context.portfolio.positions
    
    # 获取昨天的日期
    yesterday = get_previous_trade_day(context, 1)
    
    # 遍历持仓股票
    for stock in positions:
        # 获取持仓股票的成本价和当前可卖出数量
        avg_cost = positions[stock].avg_cost
        closeable_amount = positions[stock].closeable_amount
        
        # 获取昨天的价格数据
        stock_data = get_price(stock, end_date=yesterday, count=1, fields=['close', 'low', 'low_limit'])
        
        if not stock_data.empty:
            close_price = stock_data['close'].iloc[0]
            low_price = stock_data['low'].iloc[0]
            low_limit = stock_data['low_limit'].iloc[0]
            
            # 判断是否跌停
            if close_price == low_limit and low_price == low_limit:
                order_target_value(stock, 0)
                log.info(f'股票 {stock} 昨日跌停，触发风控止损卖出')
                continue
            
            # 判断亏损是否超过 4%
            loss_ratio = (close_price - avg_cost) / avg_cost * 100
            if loss_ratio <= -4:
                order_target_value(stock, 0)
                log.info(f'股票 {stock} 亏损超过阈值，触发风控止损卖出')
        else:
            log.warning(f'无法获取 {stock} 的价格数据')
            
# 每日初始股票池
def prepare_stock_list(context):
    # 获取交易日
    date = get_previous_trade_day(context, 0)
    last_date = get_previous_trade_day(context, 1)
    last_last_date = get_previous_trade_day(context, 2)

    # 获取所有股票
    stock_list = get_all_securities('stock', last_date).index.tolist()
    # 筛选涨停股票
    stock_list = get_limit_up_stock(stock_list, last_date)
    # 过滤次新股
    stock_list = filter_new_stock(stock_list, last_date)
    # 过滤非ST股
    stock_list = filter_st_stock(stock_list, last_date)
    # 今日低开
    stock_list = filter_stocks_by_opening_range(date, stock_list)
    # 计算N日无涨停
    stock_list = get_no_limit_up_stocks(last_last_date, 1, stock_list)
    # 计算相对位置
    stock_list = get_relative_position_stocks(last_date, 15, stock_list)

    return stock_list

def prepare_stock_list2(context):
    # 获取交易日
    date = get_previous_trade_day(context, 0)
    last_date = get_previous_trade_day(context, 1)
    last_last_date = get_previous_trade_day(context, 2)

    # 获取所有股票
    stock_list = get_all_securities('stock', last_date).index.tolist()
    # 筛选涨停股票
    stock_list = get_limit_up_stock2(stock_list, last_date)
    # 过滤次新股
    stock_list = filter_new_stock2(stock_list, last_date)
    # 过滤ST股
    stock_list = filter_st_stock2(stock_list, last_date)
    # 今日低开
    stock_list = filter_stocks_by_opening_range2(date, stock_list)
    # 计算N日无涨停
    stock_list = get_no_limit_up_stocks2(last_last_date, 1, stock_list)
    # 计算相对位置
    stock_list = get_relative_position_stocks2(last_date, 30, stock_list)

    return stock_list


# 筛选出某一日涨停的股票
def get_limit_up_stock(initial_list, date):
    df = get_price(initial_list, end_date=date, frequency='daily', fields=['close', 'high', 'high_limit'], count=1,
                   panel=False, fill_paused=False, skip_paused=False).dropna()
    df = df[df['close'] == df['high_limit']]
    hl_list = list(df.code)
    return hl_list


# 过滤新股
def filter_new_stock(initial_list, date, days=60):
    return [stock for stock in initial_list if date - get_security_info(stock).start_date > dt.timedelta(days=days)]


# 过滤非ST
def filter_st_stock(stock_list, date):
    filtered_stocks = []

    for stock in stock_list:
        try:
            price_data = get_price(stock, end_date=date, count=2, frequency='daily', fields=['open', 'close'])

            if len(price_data) == 2:
                close_today = price_data['close'][-1]
                close_yesterday = price_data['close'][-2]
                return_percent_yesterday = (close_today - close_yesterday) / close_yesterday * 100

                open_today = price_data['open'][-1]
                return_percent_today = (close_today - open_today) / open_today * 100

                if 4 < return_percent_yesterday < 6 and close_today > 2.5:
                    filtered_stocks.append(stock) 

        except Exception as e:
            print(f"根据涨幅过滤ST出错 {stock}: {e}")

    # filtered_stocks.sort()
    return filtered_stocks


# 计算低开
def filter_stocks_by_opening_range(date, code_list):
    filtered_codes = []

    for code in code_list:
        stock_data = get_price(code, start_date=date, end_date=date, frequency='daily', fields=['open', 'pre_close'])

        if stock_data.empty:
            continue

        open_price = stock_data['open'].iloc[0]
        pre_close_price = stock_data['pre_close'].iloc[0]

        open_change_ratio = (open_price - pre_close_price) / pre_close_price * 100

        if (code.startswith('301') or code.startswith('300') or code.startswith('688') or code.startswith('689')):
            if 0 <= open_change_ratio <= 1:
                filtered_codes.append(code)
        else:
            if 0 <= open_change_ratio <= 1:
                filtered_codes.append(code)

    return filtered_codes


# 筛选近N日无涨停
def get_no_limit_up_stocks(date, no_limit_date, code_list):
    start_date = (pd.to_datetime(date) - pd.Timedelta(days=no_limit_date - 1)).strftime('%Y-%m-%d')
    end_date = date

    trading_days = get_trade_days(start_date=start_date, end_date=end_date)

    no_limit_up_stocks = code_list.copy()

    for day in trading_days:
        if not no_limit_up_stocks:
            break

        stock_data = get_price(no_limit_up_stocks, end_date=day, frequency='daily',
                               fields=['close', 'high', 'high_limit'], count=1, panel=False, fill_paused=False,
                               skip_paused=False)
        stock_data = stock_data.dropna()

        limit_up_stocks = stock_data[stock_data['close'] == stock_data['high_limit']]['code'].tolist()

        no_limit_up_stocks = [code for code in no_limit_up_stocks if code not in limit_up_stocks]

    return no_limit_up_stocks


# 计算相对位置
def get_relative_position_stocks(date, watch_days, code_list):
    filtered_codes = []

    for code in code_list:
        data = get_price(code, end_date=date, count=watch_days, fields=['high', 'low'])
        max_high = data['high'].max()
        min_low = data['low'].min()

        close_price = get_price(code, end_date=date, count=1, fields=['close'])['close'].iloc[0]

        relative_position = (close_price - min_low) / (max_high - min_low)

        if 0.0 <= relative_position <= 0.3:
            filtered_codes.append(code)

    return filtered_codes

# 筛选出某一日涨停的股票
def get_limit_up_stock2(initial_list, date):
    df = get_price(initial_list, end_date=date, frequency='daily', fields=['close', 'high', 'high_limit'], count=1,
                   panel=False, fill_paused=False, skip_paused=False).dropna()
    df = df[df['close'] == df['high_limit']]
    hl_list = list(df.code)
    return hl_list


# 过滤新股
def filter_new_stock2(initial_list, date, days=60):
    return [stock for stock in initial_list if date - get_security_info(stock).start_date > dt.timedelta(days=days)]


# 过滤非ST
def filter_st_stock2(stock_list, date):
    filtered_stocks = []

    for stock in stock_list:
        try:
            price_data = get_price(stock, end_date=date, count=2, frequency='daily', fields=['open', 'close'])

            if len(price_data) == 2:
                close_today = price_data['close'][-1]
                close_yesterday = price_data['close'][-2]
                return_percent_yesterday = (close_today - close_yesterday) / close_yesterday * 100

                open_today = price_data['open'][-1]
                return_percent_today = (close_today - open_today) / open_today * 100

                if 9 < return_percent_yesterday < 22 and return_percent_today > 5:
                    filtered_stocks.append(stock)

        except Exception as e:
            print(f"根据涨幅过滤ST出错 {stock}: {e}")

    # filtered_stocks.sort()
    return filtered_stocks


# 计算低开
def filter_stocks_by_opening_range2(date, code_list):
    filtered_codes = []

    for code in code_list:
        stock_data = get_price(code, start_date=date, end_date=date, frequency='daily', fields=['open', 'pre_close'])

        if stock_data.empty:
            continue

        open_price = stock_data['open'].iloc[0]
        pre_close_price = stock_data['pre_close'].iloc[0]

        open_change_ratio = (open_price - pre_close_price) / pre_close_price * 100

        if -4 <= open_change_ratio <= -3:
            filtered_codes.append(code)

    return filtered_codes


# 筛选近N日无涨停
def get_no_limit_up_stocks2(date, no_limit_date, code_list):
    start_date = (pd.to_datetime(date) - pd.Timedelta(days=no_limit_date - 1)).strftime('%Y-%m-%d')
    end_date = date

    trading_days = get_trade_days(start_date=start_date, end_date=end_date)

    no_limit_up_stocks = code_list.copy()

    for day in trading_days:
        if not no_limit_up_stocks:
            break

        stock_data = get_price(no_limit_up_stocks, end_date=day, frequency='daily',
                               fields=['close', 'high', 'high_limit'], count=1, panel=False, fill_paused=False,
                               skip_paused=False)
        stock_data = stock_data.dropna()

        limit_up_stocks = stock_data[stock_data['close'] == stock_data['high_limit']]['code'].tolist()

        no_limit_up_stocks = [code for code in no_limit_up_stocks if code not in limit_up_stocks]

    return no_limit_up_stocks


# 计算相对位置
def get_relative_position_stocks2(date, watch_days, code_list):
    filtered_codes = []

    for code in code_list:
        data = get_price(code, end_date=date, count=watch_days, fields=['high', 'low'])
        max_high = data['high'].max()
        min_low = data['low'].min()

        close_price = get_price(code, end_date=date, count=1, fields=['close'])['close'].iloc[0]

        relative_position = (close_price - min_low) / (max_high - min_low)

        if 0.0 <= relative_position <= 0.5:
            filtered_codes.append(code)

    return filtered_codes




def get_previous_trade_day(context, n):
    current_date = context.current_dt.date()

    trade_days = get_trade_days(end_date=current_date, count=100)

    if n > len(trade_days):
        return None

    previous_trade_day = trade_days[-(n + 1)]

    return previous_trade_day


# 过滤停牌
def filter_paused_stock(initial_list, date):
    df = get_price(initial_list, end_date=date, frequency='daily', fields=['paused'], count=1, panel=False,
                   fill_paused=True)
    df = df[df['paused'] == 0]
    paused_list = list(df.code)
    return paused_list


