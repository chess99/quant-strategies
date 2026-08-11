# 克隆自聚宽文章：https://www.joinquant.com/post/38141
# 标题：胜率78%，6年36倍，今年行情依然50%年化
# 作者：何小爷

# 导入函数库
from jqdata import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定基准
    set_benchmark('000300.XSHG')
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
    #g.p = 0.005 #改进为选择一定比例的股票
    #g.stock_num = 5 #原版为固定5只小盘股，近3年来收益显著跑输大盘

    # 每周运行
    run_weekly(my_trade, weekday=1, time='09:30', reference_security='000300.XSHG')



## 开盘时运行函数
def my_trade(context):
    #计算动态持股数量
    mkt_list = get_all_securities().index.tolist()
    mkt_list = filter_st_stock(mkt_list)
    mkt_list = filter_paused_stock(mkt_list)
    #stock_num = int(g.p*len(mkt_list))
    stock_num = 5
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
