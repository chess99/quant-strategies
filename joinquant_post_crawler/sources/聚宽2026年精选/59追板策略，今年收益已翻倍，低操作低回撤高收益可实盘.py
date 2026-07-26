# 克隆自聚宽文章：https://www.joinquant.com/post/49749
# 标题：追板策略，今年收益已翻倍，低操作低回撤高收益可实盘
# 作者：古月量化研究

# 克隆自聚宽文章：https://www.joinquant.com/post/48680
# 标题：追首板涨停 过去两年年化304%
# 作者：子匀

# 克隆自聚宽文章：https://www.joinquant.com/post/48523
# 标题：一进二集合竞价策略
# 作者：Fragance

import psutil  # 查看内存
from jqdata import *
from jqfactor import *
from jqlib.technical_analysis import *
import datetime as dt
import pandas as pd
import sys
import gc
from datetime import datetime
from datetime import timedelta


def initialize(context):
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    log.set_level('system', 'error')
    # 股票类每笔交易时的手续费是：买入时佣金万1，卖出时佣金万1加万5印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(open_tax=0, close_tax=0.0005, open_commission=0.0001, close_commission=0.0001,
                             close_today_commission=0, min_commission=5), type='stock')
    # 设置滑点为正负0.3%，更加保守真实些
    set_slippage(PriceRelatedSlippage(0.006))
    # 创建一个空的 DataFrame，用于观测放弃的股票涨幅情况
    g.columns = ['日期', '代码', '名称', '类型', '原因', '总市值', '流通市值', '总成交额', '总成交量', '平均成交价',
                 '换手率', '左压比', '封顶量比', '开盘量比', '开盘委比', '开盘涨幅', '买入价格']
    g.logdf = pd.DataFrame(columns=g.columns)
    # 回测打开时，不做每日预判减少耗时。
    g.is_huice = True
    if g.is_huice:
        g.excel_name = 'myFile/追首日涨停/' + str(context.current_dt)[:10] + ' by ' + str(datetime.now())[:-7] + '.csv'
    else:
        g.excel_name = 'myFile/追首日涨停/实盘日志 by ' + str(datetime.now())[:-7] + '.csv'
    set_option('avoid_future_data', True)  # 避免未来函数
    write_file(g.excel_name, g.logdf.to_csv(index=False))

    g.selltime1 = '11:25:00'
    g.selltime2 = '14:50:00'
    g.target_list = []

    run_daily(get_stock_list, '00:00:10')
    # 直接掉 write_excel 只写今日文件，不做明日预测计算
    if g.is_huice:
        run_daily(write_excel, '16:00:10')
    else:
        run_daily(get_stock_list, '16:00:10')
    run_daily(buy, '09:26:00')
    run_daily(sell, time=g.selltime1)
    run_daily(sell, time=g.selltime2)


# 写分析日志
def write_excel(context):
    if len(g.logdf) == 0:
        return
    write_file(g.excel_name, g.logdf.to_csv(header=False, index=False), append=True)
    g.logdf = pd.DataFrame(columns=g.columns)

# 选股逻辑
def get_stock_list(context):
    # 文本日期
    date = get_the_day(context)
    date = transform_date(date, 'str')
    date_1 = get_shifted_date(date, -1, 'T')
    date_2 = get_shifted_date(date, -2, 'T')

    # 初始列表
    initial_list = prepare_stock_list(date)
    # 当日涨停的票
    hl_list = get_hl_stock(initial_list, date)
    # 昨日涨停过的票
    hl1_list = get_ever_hl_stock(initial_list, date_1)
    # 前日涨停过的票
    hl2_list = get_ever_hl_stock(initial_list, date_2)
    # 合并 hl1_list 和 hl2_list 为一个集合，用于快速查找需要剔除的元素
    elements_to_remove = set(hl1_list + hl2_list)
    # 使用列表推导式来剔除 hl_list 中存在于 elements_to_remove 集合中的元素
    hl_list = [stock for stock in hl_list if stock not in elements_to_remove]

    buy_str = ''
    g.target_list = []
    for stock in hl_list:
        if (nobuy(stock, context, date)):
            continue
        name = get_security_info(stock, date).display_name
        g.target_list.append(stock)
        buy_str += f"{stock}, {name};"
    # 如果是收盘后运行，则发预备消息，写今天的日志
    if (context.current_dt.time() > dt.time(15)):
        log.info('可能股票：%s ' % (buy_str))
        send_message('可能股票：%s ' % (buy_str))
        write_excel(context)

# 交易
def buy(context):
    qualified_stocks = []
    current_data = get_current_data()
    date_now = context.current_dt.strftime("%Y-%m-%d")
    mid_time1 = ' 09:15:00'
    end_times1 = ' 09:25:01'
    start = date_now + mid_time1
    end = date_now + end_times1
    for s in g.target_list:
        bumailiyou = ''
        name = get_security_info(s, date_now).display_name
        volume_data = attribute_history(s, 1, '1d', fields=['close', 'volume'], skip_paused=True)
        # 开盘时看竞价条件
        auction_data = get_call_auction(s, start_date=start, end_date=end, fields=['time', 'volume', 'current'])
        if auction_data.empty:
            volume_rate = 0
            current_ratio = 0
            bumailiyou += "停牌，"
        else:
            volume_rate = auction_data['volume'][0] / volume_data['volume'][0] * 100
            current_ratio = (auction_data['current'][0] / volume_data['close'][0] - 1) * 100
        # 如果竞价成交量不足昨日的3%则抛弃，排除极端情况失去热度
        if volume_rate < 3:
            bumailiyou += "开盘量比，"
        # 排除低开，和高开6个点以上
        if current_ratio <= 0 or current_ratio >= 6:
            bumailiyou += "开盘涨幅，"

        # 如果股票满足所有条件，则添加到列表中
        if bumailiyou == '':
            qualified_stocks.append(s)
        else:
            log_data = {
                '日期': str(context.current_dt)[:10],
                '代码': s,
                '名称': name,
                '类型': '放弃',
                '原因': bumailiyou,
                '开盘量比': round(volume_rate, 2),
                '开盘涨幅': round(current_ratio, 2),
                '买入价格': 0 if auction_data.empty else auction_data['current'][0]
            }
            add_to_logdf(context, log_data)
            print(f"放弃购买：\n{log_data}")
            send_message(f"放弃购买：\n{log_data}")

    if len(qualified_stocks) != 0:
        value = context.portfolio.available_cash / len(qualified_stocks)
        for s in qualified_stocks:
            # 下单
            # 由于关闭了错误日志，不加这一句，不足一手买入失败也会打印买入，造成日志不准确
            log_data = {
                '日期': str(context.current_dt)[:10],
                '代码': s,
                '名称': get_security_info(s, date_now).display_name,
                '买入价格': 0 if current_data[s].paused else current_data[s].day_open,
                '类型': "放弃"
            }
            if current_data[s].paused:
                log_data["原因"] = "停牌,"
                continue
            if value / current_data[s].day_open < 100:
                send_message('资金不足-----错过' + s + get_security_info(s).display_name)
                log_data["原因"] = "资金不足，"
            else:
                order_value(s, value)
                log_data["类型"] = "买入"
                print('买入-----' + s + get_security_info(s).display_name)
            print('———————————————————————————————————')
            add_to_logdf(context, log_data)


# 上午有利润就跑
def sell(context):
    # 基础信息
    date = transform_date(context.previous_date, 'str')
    current_data = get_current_data()

    for s in list(context.portfolio.positions):
        # 如果涨停、跌停，则不卖出
        if ((context.portfolio.positions[s].closeable_amount == 0) or
                (current_data[s].last_price == current_data[s].high_limit) or
                (current_data[s].last_price == current_data[s].low_limit)):
            continue
        # 中午如果赚钱且没封板，直接走人
        if (str(context.current_dt)[-8:] == g.selltime1 and
                (current_data[s].last_price > 1 * context.portfolio.positions[s].avg_cost)):  # avg_cost当前持仓成本
            order_target_value(s, 0)
            print('止盈卖出-----', [s, get_security_info(s, date).display_name])
            print('———————————————————————————————————')
        # 下午如果没封板，直接走人，不管盈亏
        elif (str(context.current_dt)[-8:] == g.selltime2):
            order_target_value(s, 0)
            print('止损卖出-----', [s, get_security_info(s, date).display_name])
            print('———————————————————————————————————')

        # 这部分股票不买


def nobuy(stock, context, theDay):
    bumailiyou = ''
    name = get_security_info(stock, theDay).display_name

    the_day_data = get_price(stock, count=1, end_date=theDay, frequency='1d', fields=['close', 'volume', 'money'],
                             skip_paused=True)

    # 平均成交价如果较低，说明市场热情不高，属于纠结涨停，剔除。
    # 成交额太小受游资影响会过大不好赚钱，剔除。
    # 成交额太大想要吃后面的肉也比较难，剔除。
    avg_price_increase_value = the_day_data['money'][0] / the_day_data['volume'][0] / the_day_data['close'][0] * 100
    if avg_price_increase_value < 96:
        bumailiyou = '平均成交价，'
    if the_day_data['money'][0] > 19e8 or the_day_data['money'][0] < 7e8:
        bumailiyou += '总成交额，'
    # 总市值<70亿，流通市值>520亿，剔除，
    turnover_ratio_data = get_valuation(stock, start_date=theDay, end_date=theDay,
                                        fields=['turnover_ratio', 'market_cap', 'circulating_market_cap'])
    if turnover_ratio_data.empty:
        bumailiyou += '总市值，'
    else:
        if turnover_ratio_data['market_cap'][0] < 70:
            bumailiyou += '总市值，'
        if turnover_ratio_data['circulating_market_cap'][0] > 520:
            bumailiyou += '流通市值，'
        # if turnover_ratio_data['turnover_ratio'][0] > 28:
        #     bumailiyou+='换手率，'

    zy_rate = calculate_zy(stock, theDay)
    # 左压比小于0.9，则排除掉，说明热度还不够之前猛，容易掉下来
    if zy_rate <= 0.9:
        bumailiyou += '左压比，'

    log_data = {
        '日期': get_shifted_date(theDay, 1, 'T')[:10],
        '代码': stock,
        '名称': name,
        '类型': '放弃',
        '原因': bumailiyou,
        '平均成交价': round(avg_price_increase_value, 2),
        '总成交额': round(the_day_data['money'][0] / 1e8, 2),
        '左压比': round(zy_rate, 2)
    }
    if not turnover_ratio_data.empty:
        log_data['换手率'] = round(turnover_ratio_data['turnover_ratio'][0], 2)
        log_data['总市值'] = round(turnover_ratio_data['market_cap'][0], 2)
        log_data['流通市值'] = round(turnover_ratio_data['circulating_market_cap'][0], 2)

    if bumailiyou != '':
        add_to_logdf(context, log_data)
    else:
        log_data['类型'] = "预备"
        log.info(f"{log_data['类型']}-{log_data}")
    del log_data

    return bumailiyou != ''

# 字典加到excel日志中
def add_to_logdf(context, log_data):
    if not g.is_huice:
        log.info(f"{log_data['类型']}-{log_data}")
    # 如果是收盘前运行，则保存到日志中
    if (context.current_dt.time() < dt.time(15)):
        # log_data["index"]=log_data["日期"]+"-"+log_data["代码"]
        log_data_df = pd.DataFrame(log_data, index=[0])
        log_data_df = log_data_df.reindex(columns=g.columns, fill_value='')
        g.logdf.loc[len(g.logdf)] = log_data_df.iloc[0]
        # g.logdf=pd.concat([g.logdf, log_data_df], sort=False) #效率太低


# 转换时间，如果收盘前运行则为昨天，否则为今天
def get_the_day(context):
    theDay = context.previous_date
    # 如果是收盘后运行，则取当天数据
    if (context.current_dt.time() > dt.time(15)):
        theDay = transform_date(context.current_dt, 'str')[:10]
    return theDay


# 计算五档委比
def get_entrust_rate(auction_data):
    buy_cols = auction_data.iloc[:, 0:5].sum().sum()
    sell_cols = auction_data.iloc[:, 5:10].sum().sum()
    entrust_rate = round((buy_cols - sell_cols) / (buy_cols + sell_cols) * 100, 2)
    return entrust_rate


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
    dct = {'str': str_date, 'dt': dt_date, 'd': d_date}
    return dct[date_type]


def get_shifted_date(date, days, days_type='T'):
    # 获取上一个自然日
    d_date = transform_date(date, 'd')
    yesterday = d_date + dt.timedelta(-1)
    # 移动days个自然日
    if days_type == 'N':
        shifted_date = yesterday + dt.timedelta(days + 1)
    # 移动days个交易日
    if days_type == 'T':
        all_trade_days = [i.strftime('%Y-%m-%d') for i in list(get_all_trade_days())]
        # 如果上一个自然日是交易日，根据其在交易日列表中的index计算平移后的交易日
        if str(yesterday) in all_trade_days:
            shifted_date = all_trade_days[all_trade_days.index(str(yesterday)) + days + 1]
        # 否则，从上一个自然日向前数，先找到最近一个交易日，再开始平移
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


# 过滤科创板、创业板、其他类型股票
def filter_kcbj_stock(initial_list):
    return [stock for stock in initial_list if
            stock[0] != '4' and stock[0] != '8' and stock[0] != '3' and stock[:2] != '68']


def filter_paused_stock(initial_list, date):
    df = get_price(initial_list, end_date=date, frequency='daily', fields=['paused'], count=1, panel=False,
                   fill_paused=True)
    df = df[df['paused'] == 0]
    paused_list = list(df.code)
    return paused_list


# 每日初始股票池
def prepare_stock_list(date):
    initial_list = get_all_securities('stock', date).index.tolist()
    initial_list = filter_kcbj_stock(initial_list)
    initial_list = filter_new_stock(initial_list, date)
    initial_list = filter_st_stock(initial_list, date)
    initial_list = filter_paused_stock(initial_list, date)
    return initial_list


# 计算左压比
# 左压比=上一次超过今日最高价的这些天里，涨停的成交量/这段时间的最大成交量
def calculate_zy(s, theDay):
    high_prices = get_price(s, count=100, end_date=theDay, fields=['high'], skip_paused=True)['high']
    prev_high = high_prices.iloc[-1]
    zyts_0 = next((i - 1 for i, high in enumerate(high_prices[-3::-1], 2) if high >= prev_high), 100)
    zyts = zyts_0 + 5
    volume_data = get_price(s, end_date=theDay, count=zyts, frequency='1d', fields=['volume'], skip_paused=True)
    if len(volume_data) < 2:
        return 0
    return volume_data['volume'][-1] / max(volume_data['volume'][:-1].dropna())


# 筛选出某一日涨停的股票
def get_hl_stock(initial_list, date):
    df = get_price(initial_list, end_date=date, frequency='daily', fields=['close', 'high_limit'], count=1, panel=False,
                   fill_paused=False, skip_paused=False)
    df = df.dropna()  # 去除停牌
    df = df[df['close'] == df['high_limit']]
    hl_list = list(df.code)
    return hl_list


# 筛选曾涨停
def get_ever_hl_stock(initial_list, date):
    df = get_price(initial_list, end_date=date, frequency='daily', fields=['high', 'high_limit'], count=1, panel=False,
                   fill_paused=False, skip_paused=False)
    df = df.dropna()  # 去除停牌
    df = df[df['high'] == df['high_limit']]
    hl_list = list(df.code)
    return hl_list


# 计算涨停数
def get_hl_count_df(hl_list, date, watch_days):
    # 获取watch_days的数据
    df = get_price(hl_list, end_date=date, frequency='daily', fields=['close', 'high_limit', 'low'], count=watch_days,
                   panel=False, fill_paused=False, skip_paused=False)
    df.index = df.code
    # 计算涨停与一字涨停数，一字涨停定义为最低价等于涨停价
    hl_count_list = []
    extreme_hl_count_list = []
    for stock in hl_list:
        df_sub = df.loc[stock]
        hl_days = df_sub[df_sub.close == df_sub.high_limit].high_limit.count()
        extreme_hl_days = df_sub[df_sub.low == df_sub.high_limit].high_limit.count()
        hl_count_list.append(hl_days)
        extreme_hl_count_list.append(extreme_hl_days)
    # 创建df记录
    df = pd.DataFrame(index=hl_list, data={'count': hl_count_list, 'extreme_count': extreme_hl_count_list})
    return df


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

