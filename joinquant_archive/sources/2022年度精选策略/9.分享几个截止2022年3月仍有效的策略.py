# 导入函数库
from jqdata import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定基准
    set_benchmark('399101.XSHE')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 开启防未来函数
    set_option('avoid_future_data', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5),type='stock')

    # 股票池
    g.security_universe_index = "399101.XSHE" 
    g.p = 0.005 #改进为选择一定比例的股票
    #g.stock_num = 5 #原版为固定5只小盘股，近3年来收益显著跑输大盘

    # 每周运行
    run_weekly(my_trade, weekday=1, time='09:30', reference_security='000300.XSHG')



## 开盘时运行函数
def my_trade(context):
    #计算动态持股数量
    mkt_list = get_all_securities().index.tolist()
    mkt_list = filter_st_stock(mkt_list)
    mkt_list = filter_paused_stock(mkt_list)
    stock_num = int(g.p*len(mkt_list))
    print(stock_num)
    # 选取中小板中市值最小的若干只
    check_out_lists = get_index_stocks(g.security_universe_index)
    q = query(valuation.code).filter(valuation.code.in_(check_out_lists)).order_by(valuation.circulating_market_cap.asc()).limit(100)
    check_out_lists = list(get_fundamentals(q).code)
    check_out_lists = filter_st_stock(check_out_lists) #注释掉这一行不过滤st收益反倒更高！
    check_out_lists = filter_limitup_stock(context, check_out_lists)
    check_out_lists = filter_limitdown_stock(context, check_out_lists)
    check_out_lists = check_out_lists[:stock_num]
    adjust_position(context, check_out_lists, stock_num)



# 自定义下单
def order_target_value_(security, value):
    if value == 0:
        log.debug("Selling out %s" % (security))
    else:
        log.debug("Order %s to value %f" % (security, value))
    return order_target_value(security, value)
# 开仓
def open_position(security, value):
    order = order_target_value_(security, value)
    if order != None and order.filled > 0:
        return True
    return False
# 平仓
def close_position(position):
    security = position.security
    order = order_target_value_(security, 0)  # 可能会因停牌失败
    if order != None:
        if order.status == OrderStatus.held and order.filled == order.amount:
            return True
    return False
# 交易
def adjust_position(context, buy_stocks, stock_num):
    for stock in context.portfolio.positions:
        if stock not in buy_stocks:
            log.info("stock [%s] in position is not buyable" % (stock))
            position = context.portfolio.positions[stock]
            close_position(position)
        else:
            log.info("stock [%s] is already in position" % (stock))
    position_count = len(context.portfolio.positions)
    if stock_num > position_count:
        value = context.portfolio.cash / (stock_num - position_count)

        for stock in buy_stocks:
            if context.portfolio.positions[stock].total_amount == 0:
                if open_position(stock, value):
                    if len(context.portfolio.positions) == stock_num:
                        break



# 过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]
# 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list
            if not current_data[stock].is_st
            and 'ST' not in current_data[stock].name
            and '*' not in current_data[stock].name
            and '退' not in current_data[stock].name]
# 过滤涨停的股票
def filter_limitup_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] < current_data[stock].high_limit]
# 过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] > current_data[stock].low_limit]
# 过滤科创板
def filter_kcb_stock(context, stock_list):
    return [stock for stock in stock_list  if stock[0:3] != '688']
# 过滤次新股
def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=250)]




#导入函数库
from jqdata import *
from jqfactor import get_factor_values
import numpy as np
import pandas as pd

#初始化函数 
def initialize(context):
    set_benchmark('399101.XSHE')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 设置交易成本万分之三
    set_order_cost(OrderCost(open_tax=0, close_tax=0.000, open_commission=0.0000, close_commission=0.0000, close_today_commission=0, min_commission=5),type='fund')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    #选股参数
    g.stock_list = []
    g.candidate_list = []
    g.to_buy_concept = 0
    # 设置交易时间，每天运行
    run_weekly(get_stock_list, weekday=1, time='16:05', reference_security='000300.XSHG')
    run_weekly(print_stock_list_before_open, weekday=2, time='9:15', reference_security='000300.XSHG')
    run_weekly(my_trade, weekday=1, time='9:30', reference_security='000300.XSHG')

#1-1 获取股票列表
def get_stock_list(context):
    stat_date = context.current_dt.strftime('%Y-%m-%d')
    MKT_index = '399101.XSHE'
    MKT_list = get_index_stocks(MKT_index)
    stock_list = filter_st_stock(MKT_list)
    stock_list = filter_new_stock(context,stock_list)
    stock_list = filter_kcb_stock(context, stock_list)
    stock_list = filter_bjs_stock(context, stock_list)
    stock_list = filter_paused_stock(stock_list)

    stock_list = filter_high_limit_count_stock(MKT_index, stock_list, stat_date, 250, 0.2)
    stock_list = filter_relative_high_stock(MKT_index, stock_list, stat_date, 250, 1, ref='000300.XSHG')

    g.stock_list = stock_list

#1-2 开盘前打印自选股
def print_stock_list_before_open(context):
    num = len(g.stock_list)
    print('股票数:{}'.format(num))

#1-3 交易
def my_trade(context):
    #获取选股列表并过滤掉:st,st*,退市,涨停,跌停,停牌
    check_out_list = g.stock_list
    check_out_list = filter_limitup_stock(context, check_out_list)
    check_out_list = filter_limitdown_stock(context, check_out_list)
    adjust_position(context, check_out_list, len(g.stock_list))



#2-1 过滤模块-过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]

#2-2 过滤模块-过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list
            if not current_data[stock].is_st
            and 'ST' not in current_data[stock].name
            and '*' not in current_data[stock].name
            and '退' not in current_data[stock].name]

#2-3 过滤模块-过滤涨停的股票
def filter_limitup_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    # 已存在于持仓的股票即使涨停也不过滤，避免此股票再次可买，但因被过滤而导致选择别的股票
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] < current_data[stock].high_limit]

#2-4 过滤模块-过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] > current_data[stock].low_limit]

#2-5 过滤模块-过滤科创板
def filter_kcb_stock(context, stock_list):
    return [stock for stock in stock_list  if stock[0:3] != '688']

#2-5 过滤模块-过滤北交所
def filter_bjs_stock(context, stock_list):
    return [stock for stock in stock_list  if (stock[0] != '8') and (stock[0] != '4')]

#2-6 过滤次新股
def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=250)]

#2-7 过滤涨停次数过多的股票
def filter_high_limit_count_stock(MKT_index, stock_list, stat_date, watch_days, m):
    MKT_list = get_index_stocks(MKT_index)
    df = get_price(MKT_list, end_date=stat_date, frequency='daily', fields=['close','high_limit'], count=watch_days, panel=False, fill_paused=True)
    df.index = df.code
    count_list = []
    for stock in MKT_list:
        df_sub = df.loc[stock]
        high_limit_days = df_sub[df_sub.close==df_sub.high_limit].close.count()
        count_list.append(high_limit_days)   
    df = pd.DataFrame(index=MKT_list, columns=['count'])
    df['count'] = count_list
    mean = df['count'].mean(0)
    df = df.loc[stock_list]
    df = df[df['count']< m*mean]
    return list(df.index)

#2-8 过滤低位股票
def filter_relative_high_stock(MKT_index, stock_list, stat_date, watch_days, m, ref='000300.XSHG'):
    MKT_list = get_index_stocks(MKT_index)
    gap_list = []
    all_trade_days=[i.strftime('%Y-%m-%d') for i in list(get_all_trade_days())]
    tradingday = get_trade_days(start_date='2005-01-01', end_date=stat_date, count=None)
    trade_day_list = []
    past_date = str(datetime.datetime.strptime(all_trade_days[all_trade_days.index(stat_date)-watch_days],"%Y-%m-%d").date())
    for item in list(tradingday):
        trade_day_list.append(str(item))
    for stock in MKT_list:
        close_now = get_price(ref, end_date=stat_date, frequency='daily', fields=['close'], skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True).iloc[-1,0]
        close_past = get_price(ref, end_date=past_date, frequency='daily', fields=['close'], skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True).iloc[-1,0]
        MKT_ret = (close_now - close_past) / close_past

        close_now = get_price(stock, end_date=stat_date, frequency='daily', fields=['close'], skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True).iloc[-1,0]
        close_past = get_price(stock, end_date=past_date, frequency='daily', fields=['close'], skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True).iloc[-1,0]
        stock_ret = (close_now - close_past) / close_past

        gap = stock_ret - MKT_ret
        gap_list.append(gap)

    df = pd.DataFrame(index=MKT_list, columns=['gap'])
    df['gap'] = gap_list
    mean = df['gap'].mean(0)
    df = df.loc[stock_list]
    df = df[df['gap']>m*mean]
    return list(df.index)


def order_target_value_(security, value):
    if value == 0:
        log.debug("Selling out %s" % (security))
    else:
        log.debug("Order %s to value %f" % (security, value))
    return order_target_value(security, value)

def open_position(security, value):
    order = order_target_value_(security, value)
    if order != None and order.filled > 0:
        return True
    return False

def close_position(position):
    security = position.security
    order = order_target_value_(security, 0)  # 可能会因停牌失败
    if order != None:
        if order.status == OrderStatus.held and order.filled == order.amount:
            return True
    return False

def adjust_position(context, buy_stocks, stock_num):
    for stock in context.portfolio.positions:
        if stock not in buy_stocks:
            log.info("[%s]不在应买入列表中" % (stock))
            position = context.portfolio.positions[stock]
            close_position(position)
        else:
            log.info("[%s]已经持有无需重复买入" % (stock))
    position_count = len(context.portfolio.positions)
    if stock_num > position_count:
        value = context.portfolio.cash / (stock_num - position_count)
        for stock in buy_stocks:
            if context.portfolio.positions[stock].total_amount == 0:
                if open_position(stock, value):
                    if len(context.portfolio.positions) == stock_num:
                        break




#导入函数库
from jqdata import *
from jqfactor import get_factor_values
import numpy as np
import pandas as pd

#初始化函数 
def initialize(context):
    set_benchmark('000905.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 设置交易成本万分之三
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),type='fund')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    #选股参数
    g.stock_num = 5 #持仓数
    # 设置交易时间，每天运行
    run_weekly(my_trade, weekday=1, time='9:30', reference_security='000300.XSHG')
    run_daily(print_trade_info, time='15:30', reference_security='000300.XSHG')



#2-1 选股模块
def get_factor_filter_list(context,stock_list,jqfactor,sort,p):
    yesterday = context.previous_date
    score_list = get_factor_values(stock_list, jqfactor, end_date=yesterday, count=1)[jqfactor].iloc[0].tolist()
    df = pd.DataFrame(columns=['code','score'])
    df['code'] = stock_list
    df['score'] = score_list
    df = df.dropna()
    df = df[df['score']>0]
    df.sort_values(by='score', ascending=sort, inplace=True)
    filter_list = list(df.code)[0:int(p*len(stock_list))]
    return filter_list


#2-2 选股模块
def get_stock_list(context):
    initial_list = get_all_securities().index.tolist()
    initial_list = filter_new_stock(context,initial_list)
    initial_list = filter_kcb_stock(context, initial_list)
    initial_list = filter_st_stock(initial_list)
    peg_list = get_factor_filter_list(context, initial_list, 'PEG', True, 0.1)
    ebit_list = get_factor_filter_list(context, peg_list, 'EBIT', True, 0.25)
    test_list = get_factor_filter_list(context, ebit_list, 'turnover_volatility', True, 0.5)
    q = query(valuation.code,valuation.circulating_market_cap).filter(valuation.code.in_(test_list)).order_by(valuation.circulating_market_cap.asc())
    df = get_fundamentals(q)
    final_list = list(df.code)
    return final_list



#3-1 过滤模块-过滤停牌股票
#输入选股列表，返回剔除停牌股票后的列表
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]

#3-2 过滤模块-过滤ST及其他具有退市标签的股票
#输入选股列表，返回剔除ST及其他具有退市标签股票后的列表
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list
            if not current_data[stock].is_st
            and 'ST' not in current_data[stock].name
            and '*' not in current_data[stock].name
            and '退' not in current_data[stock].name]

#3-3 过滤模块-过滤涨停的股票
#输入选股列表，返回剔除未持有且已涨停股票后的列表
def filter_limitup_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    # 已存在于持仓的股票即使涨停也不过滤，避免此股票再次可买，但因被过滤而导致选择别的股票
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] < current_data[stock].high_limit]

#3-4 过滤模块-过滤跌停的股票
#输入股票列表，返回剔除已跌停股票后的列表
def filter_limitdown_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] > current_data[stock].low_limit]

#3-5 过滤模块-过滤科创板
#输入股票列表，返回剔除科创板后的列表
def filter_kcb_stock(context, stock_list):
    return [stock for stock in stock_list  if stock[0:3] != '688']

#3-6 过滤次新股
#输入股票列表，返回剔除上市日期不足250日股票后的列表
def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=250)]

#4-1 交易模块-自定义下单
#报单成功返回报单(不代表一定会成交),否则返回None,应用于
def order_target_value_(security, value):
    if value == 0:
        log.debug("Selling out %s" % (security))
    else:
        log.debug("Order %s to value %f" % (security, value))
    # 如果股票停牌，创建报单会失败，order_target_value 返回None
    # 如果股票涨跌停，创建报单会成功，order_target_value 返回Order，但是报单会取消
    # 部成部撤的报单，聚宽状态是已撤，此时成交量>0，可通过成交量判断是否有成交
    return order_target_value(security, value)

#4-2 交易模块-开仓
#买入指定价值的证券,报单成功并成交(包括全部成交或部分成交,此时成交量大于0)返回True,报单失败或者报单成功但被取消(此时成交量等于0),返回False
def open_position(security, value):
    order = order_target_value_(security, value)
    if order != None and order.filled > 0:
        return True
    return False

#4-3 交易模块-平仓
#卖出指定持仓,报单成功并全部成交返回True，报单失败或者报单成功但被取消(此时成交量等于0),或者报单非全部成交,返回False
def close_position(position):
    security = position.security
    order = order_target_value_(security, 0)  # 可能会因停牌失败
    if order != None:
        if order.status == OrderStatus.held and order.filled == order.amount:
            return True
    return False

#4-4 交易模块-调仓
#当择时信号为买入时开始调仓，输入过滤模块处理后的股票列表，执行交易模块中的开平仓操作
def adjust_position(context, buy_stocks):
    for stock in context.portfolio.positions:
        if stock not in buy_stocks:
            log.info("[%s]已不在应买入列表中" % (stock))
            position = context.portfolio.positions[stock]
            close_position(position)
        else:
            log.info("[%s]已经持有无需重复买入" % (stock))
    # 根据股票数量分仓
    # 此处只根据可用金额平均分配购买，不能保证每个仓位平均分配
    position_count = len(context.portfolio.positions)
    if g.stock_num > position_count:
        value = context.portfolio.cash / (g.stock_num - position_count)
        for stock in buy_stocks:
            if context.portfolio.positions[stock].total_amount == 0:
                if open_position(stock, value):
                    if len(context.portfolio.positions) == g.stock_num:
                        break

#4-5 交易模块-择时交易
#结合择时模块综合信号进行交易
def my_trade(context):
    #获取选股列表并过滤掉:st,st*,退市,涨停,跌停,停牌
    check_out_list = get_stock_list(context)
    check_out_list = filter_limitup_stock(context, check_out_list)
    check_out_list = filter_limitdown_stock(context, check_out_list)
    check_out_list = filter_paused_stock(check_out_list)
    check_out_list = check_out_list[:g.stock_num]
    print('今日自选股:{}'.format(check_out_list))
    adjust_position(context, check_out_list)



#5-1 复盘模块-打印
#打印每日持仓信息
def print_trade_info(context):
    #打印当天成交记录
    trades = get_trades()
    for _trade in trades.values():
        print('成交记录：'+str(_trade))
    #打印账户信息
    for position in list(context.portfolio.positions.values()):
        securities=position.security
        cost=position.avg_cost
        price=position.price
        ret=100*(price/cost-1)
        value=position.value
        amount=position.total_amount    
        print('代码:{}'.format(securities))
        print('成本价:{}'.format(format(cost,'.2f')))
        print('现价:{}'.format(price))
        print('收益率:{}%'.format(format(ret,'.2f')))
        print('持仓(股):{}'.format(amount))
        print('市值:{}'.format(format(value,'.2f')))
        print('———————————————————————————————————')
    print('———————————————————————————————————————分割线————————————————————————————————————————')





# 导入函数库
from jqdata import *
from jqfactor import *
import pandas as pd

#初始化函数 
def initialize(context):
    #设定股票池
    set_benchmark('000905.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 设置交易成本万分之三
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),type='fund')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    #选股参数
    g.stock_num = 5 #持仓数
    # 设置交易时间，每天运行
    #run_monthly(print_stock_list_before_open, monthday=1, time='9:15', reference_security='000300.XSHG')
    run_weekly(my_trade, weekday=1, time='9:30', reference_security='000300.XSHG')
    #run_daily(print_position_info, time='15:10', reference_security='000300.XSHG')



#1-1 选股模块
#先根据资产负债排除一些股票，再选出roe改善最多的列表，最后在这个列表中根据pb轮动
def get_stock_list(context):
    yesterday = str(context.previous_date)
    initial_list = get_all_securities().index.tolist()
    initial_list = filter_new_stock(context,initial_list)
    initial_list = filter_kcb_stock(context, initial_list)
    initial_list = filter_st_stock(initial_list)

    factor_values = get_factor_values(initial_list, ['operating_revenue_growth_rate', #营业收入增长率
    'total_profit_growth_rate', #利润总额增长率
    'net_profit_growth_rate', #净利润增长率
    'earnings_growth', #5年盈利增长率
    'sales_growth', #5年营业收入增长率
    ], end_date=yesterday, count=1)

    df = pd.DataFrame(index=initial_list, columns=factor_values.keys())
    df['operating_revenue_growth_rate'] = list(factor_values['operating_revenue_growth_rate'].T.iloc[:,0])
    df['total_profit_growth_rate'] = list(factor_values['total_profit_growth_rate'].T.iloc[:,0])
    df['net_profit_growth_rate'] = list(factor_values['net_profit_growth_rate'].T.iloc[:,0])
    df['earnings_growth'] = list(factor_values['earnings_growth'].T.iloc[:,0])
    df['sales_growth'] = list(factor_values['sales_growth'].T.iloc[:,0])
    df['total_score'] = 0.1*df['operating_revenue_growth_rate'] + 0.35*df['total_profit_growth_rate'] + 0.15*df['net_profit_growth_rate'] + 0.35*df['earnings_growth'] + 0.05*df['sales_growth']
    df = df.sort_values(by=['total_score'], ascending=False)
    complex_growth_list = list(df.index)[:int(0.1*len(list(df.index)))]

    q = query(valuation.code,valuation.circulating_market_cap,indicator.eps).filter(valuation.code.in_(complex_growth_list)).order_by(valuation.circulating_market_cap.asc())
    df = get_fundamentals(q)
    df = df[df['eps']>0]
    final_list = list(df.code)

    return final_list

#1-2 开盘前打印自选股
def print_stock_list_before_open(context):
    stock_list = get_stock_list(context)
    stock_list = filter_paused_stock(stock_list)
    stock_list = stock_list[:g.stock_num]
    print('今日自选股:{}'.format(stock_list))



#2-1 开盘时运行函数
def my_trade(context):
    check_out_list = get_stock_list(context)
    check_out_list = filter_limitup_stock(context, check_out_list)
    check_out_list = filter_limitdown_stock(context, check_out_list)
    check_out_list = filter_paused_stock(check_out_list)
    check_out_list = check_out_list[:g.stock_num]
    adjust_position(context, check_out_list)



#3-1 交易函数
def order_target_value_(security, value):
    if value == 0:
        log.debug("Selling out %s" % (security))
    else:
        log.debug("Order %s to value %f" % (security, value))
    return order_target_value(security, value)

def open_position(security, value):
    order = order_target_value_(security, value)
    if order != None and order.filled > 0:
        return True
    return False

def close_position(position):
    security = position.security
    order = order_target_value_(security, 0)  # 可能会因停牌失败
    if order != None:
        if order.status == OrderStatus.held and order.filled == order.amount:
            return True
    return False

def adjust_position(context, buy_stocks):
    for stock in context.portfolio.positions:
        if stock not in buy_stocks:
            log.info("[%s]不在应买入列表中" % (stock))
            position = context.portfolio.positions[stock]
            close_position(position)
        else:
            log.info("[%s]已经持有无需重复买入" % (stock))
    position_count = len(context.portfolio.positions)
    if g.stock_num > position_count:
        value = context.portfolio.cash / (g.stock_num - position_count)
        for stock in buy_stocks:
            if context.portfolio.positions[stock].total_amount == 0:
                if open_position(stock, value):
                    if len(context.portfolio.positions) == g.stock_num:
                        break



#4-1 过滤函数
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]

def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list
            if not current_data[stock].is_st
            and 'ST' not in current_data[stock].name
            and '*' not in current_data[stock].name
            and '退' not in current_data[stock].name]

def filter_limitup_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] < current_data[stock].high_limit]

def filter_limitdown_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] > current_data[stock].low_limit]

def filter_kcb_stock(context, stock_list):
    return [stock for stock in stock_list  if stock[0:3] != '688']

def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=250)]



#5-1 打印每日持仓信息
def print_position_info(context):
    #打印当天成交记录
    trades = get_trades()
    for _trade in trades.values():
        print('成交记录：'+str(_trade))
    #打印账户信息
    for position in list(context.portfolio.positions.values()):
        securities=position.security
        cost=position.avg_cost
        price=position.price
        ret=100*(price/cost-1)
        value=position.value
        amount=position.total_amount    
        print('代码:{}'.format(securities))
        print('成本价:{}'.format(format(cost,'.2f')))
        print('现价:{}'.format(price))
        print('收益率:{}%'.format(format(ret,'.2f')))
        print('持仓(股):{}'.format(amount))
        print('市值:{}'.format(format(value,'.2f')))
        print('———————————————————————————————————')
    print('———————————————————————————————————————分割线————————————————————————————————————————')
