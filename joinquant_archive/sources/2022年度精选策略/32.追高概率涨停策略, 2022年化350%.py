# 克隆自聚宽文章：https://www.joinquant.com/post/39553
# 标题：追高概率涨停策略, 2022年化350%
# 作者：养家大哥

# 导入函数库
from jqdata import *
import numpy as np

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 避免引入未来信息
    set_option("avoid_future_data", True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')
    log.set_level('history', 'error')
    log.set_level('system', 'error')
    enable_profile()
    # 股票相关的变量
    g.prepare_lists = []
    g.check_out_lists = []
    g.buy_stock_count = 3

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.00013, close_commission=0.00013, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
    # 周选择股票清单
    run_weekly(prepare_stock_list, weekday=1, time='7:00', reference_security='000300.XSHG')
     # 开盘前运行
    run_daily(before_market_open, time='09:26', reference_security='000300.XSHG')
      # 开盘时运行
    run_daily(market_open, time='09:30', reference_security='000300.XSHG')
    
    run_daily(check_raise_up, time='14:00', reference_security='000300.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')

#  准备股票池
def prepare_stock_list(context):
    # type: (Context) -> list
    # 去掉次新股
    by_date = context.previous_date - datetime.timedelta(days=375)
    check_out_lists = get_all_securities(date=by_date).index.tolist()
    #选市值在200亿元以下
    check_out_lists = market_cap_filter(context, check_out_lists)
    # 去科创，ST
    check_out_lists = filter_kcb_stock(check_out_lists)
    check_out_lists = filter_cyb_stock(check_out_lists)
    check_out_lists = filter_st_stock(check_out_lists)
    check_out_lists = filter_paused_stock(check_out_lists)
    g.prepare_lists = get_recent_limit_up_stock(context, check_out_lists, 120)
    
## 开盘前运行函数
def before_market_open(context):
    check_out_lists = get_recent_limit_up_stock(context, g.prepare_lists, 5)
    check_out_lists = filter_limitdown_stock(context, check_out_lists)
    check_out_lists = get_available_price_stock(context, check_out_lists, 50, 1.2, 1.4, -0.05)
    check_out_lists = get_available_volume_stock(context, check_out_lists, 5, 1.8)
    check_out_lists = get_available_auction_stock(context, check_out_lists, 1.05)
    check_out_lists = add_hold_stock(context, check_out_lists, 0.96)
    if len(check_out_lists)>g.buy_stock_count:
        g.check_out_lists = check_out_lists[:g.buy_stock_count]
    else:
        g.check_out_lists = check_out_lists


## 开盘时运行函数
def market_open(context):
    log.info("运行 market_open 函数")
    adjust_position(context, g.check_out_lists)
    

## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    log.info('一天结束')
    log.info('##############################################################')

# 自定义下单
# 根据Joinquant文档，当前报单函数都是阻塞执行，报单函数（如order_target_value）返回即表示报单完成
# 报单成功返回报单（不代表一定会成交），否则返回None
def order_target_value_(security, value):
    if value == 0:
        log.debug("Selling out %s" % (security))
    else:
        log.debug("Order %s to value %f" % (security, value))
    
    # 如果股票停牌，创建报单会失败，order_target_value 返回None
    # 如果股票涨跌停，创建报单会成功，order_target_value 返回Order，但是报单会取消
    # 部成部撤的报单，聚宽状态是已撤，此时成交量>0，可通过成交量判断是否有成交
    return order_target_value(security, value)


# 开仓，买入指定价值的证券
# 报单成功并成交（包括全部成交或部分成交，此时成交量大于0），返回True
# 报单失败或者报单成功但被取消（此时成交量等于0），返回False
def open_position(security, value):
    order = order_target_value_(security, value)
    if order != None and order.filled > 0:
        return True
    return False


# 平仓，卖出指定持仓
# 平仓成功并全部成交，返回True
# 报单失败或者报单成功但被取消（此时成交量等于0），或者报单非全部成交，返回False
def close_position(position):
    security = position.security
    order = order_target_value_(security, 0)  # 可能会因停牌失败
    if order != None:
        if order.status == OrderStatus.held and order.filled == order.amount:
            return True
    
    return False
    
# 交易
def adjust_position(context, buy_stocks):
    for stock in context.portfolio.positions:
        if stock not in buy_stocks:
            log.info("stock [%s] in position is not buyable" % (stock))
            position = context.portfolio.positions[stock]
            close_position(position)
        #else:
        #    log.info("stock [%s] is already in position" % (stock))
    
    # 根据股票数量分仓
    # 此处只根据可用金额平均分配购买，不能保证每个仓位平均分配
    buy_stocks = buy_stocks[:g.buy_stock_count]
    position_count = len(context.portfolio.positions)
    if g.buy_stock_count > position_count:
        value = context.portfolio.cash / (g.buy_stock_count - position_count)
        
        for stock in buy_stocks:
            if context.portfolio.positions[stock].total_amount == 0:
                if open_position(stock, value):
                    if len(context.portfolio.positions) == g.buy_stock_count:
                        break
    
# 2-1 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not (
            current_data[stock].is_st or
            'ST' in current_data[stock].name or
            '*' in current_data[stock].name or
            '退' in current_data[stock].name)]

# 2-2 过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]
            
# 2-3 过滤科创板
def filter_kcb_stock(stock_list):
    return [stock for stock in stock_list if not (stock.startswith('68'))]

# 2-4 过滤创业板
def filter_cyb_stock(stock_list):
    return [stock for stock in stock_list if not (stock.startswith('30'))]

# 2-5 过滤器，流通市值在200亿以上
def market_cap_filter(context,stock_list):
    q = query(valuation.code,valuation.market_cap).filter(
        valuation.code.in_(stock_list),
        valuation.market_cap < 200
    ).order_by(
        valuation.circulating_market_cap.asc()
    )
    return(list(get_fundamentals(q).code))

# 2-6 过滤涨停的股票
def filter_limitup_stock(context, stock_list):
    close      = history(1, unit='1m', field='close', security_list=stock_list)
    high_limit = history(1, unit='1m', field='high_limit', security_list=stock_list)
    # 已存在于持仓的股票即使涨停也不过滤，避免此股票再次可买，但因被过滤而导致选择别的股票
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or close[stock][-1] < high_limit[stock][-1]]

# 2-7 过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
    close     = history(1, unit='1m', field='close', security_list=stock_list)
    low_limit = history(1, unit='1m', field='low_limit', security_list=stock_list)
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or close[stock][-1] > low_limit[stock][-1]]

#获取股票LIST
# 3-1 获取最近N个交易日内有涨停的股票
def get_recent_limit_up_stock(context, stock_list, recent_days=1, limit_num=0):
    yesterday = context.previous_date
    h = get_price(stock_list, end_date=yesterday, frequency='daily', fields=['close', 'high_limit', 'paused'],
                  count=recent_days, panel=False)
    s_limit = h.query('close==high_limit and paused==0').groupby('code')['high_limit'].count()
    if(limit_num>0):
        fix_limit = s_limit[(s_limit.values==limit_num)]
        return(fix_limit.index.tolist())
    else:
        return s_limit.index.tolist()
    
# 3-2 获取最近N个交易日内出现跌停的股票,包括跌停后打开的
def get_recent_limit_low_stock(context, stock_list, recent_days=1, limit_num=0):
    yesterday = context.previous_date
    h = get_price(stock_list, end_date=yesterday, frequency='daily', fields=['low', 'low_limit', 'paused'],
                  count=recent_days, panel=False)
    s_limit = h.query('low==low_limit and paused==0').groupby('code')['low_limit'].count()
    if(limit_num>0):
        fix_limit = s_limit[(s_limit.values==limit_num)]
        return(fix_limit.index.tolist())
    else:
        return s_limit.index.tolist()
    
# 3-3 获取昨日收盘价不超过最近N天最低价上涨x空间之内，最低和最高在y之内，昨天收盘价涨幅大于t
def get_available_price_stock(context, stock_list, recent_days, up_low_r=1.2, bottom_up_r=1.4, yes_price_r=-0.05):
    return_stocks = []
    for stock in stock_list:
        data = attribute_history(stock, recent_days, '1d', ['close', 'pre_close'])
        min_close = data.close.min()
        max_close = data.close.max()
        if(data.close[-1] <= min_close*up_low_r)and\
          (max_close <= min_close*bottom_up_r)and\
          (data.close[-1]>=data.pre_close[-1]*(1+yes_price_r)):
            return_stocks.append(stock)
    return(return_stocks)
    

# 3-4 最近N天的成交量要在合理范围，最高成交量不超过平均成交量的x
def get_available_volume_stock(context, stock_list, recent_days, up_volume_r=2):
    return_stocks = []
    for stock in stock_list:
        data = attribute_history(stock, recent_days, '1d', ['volume'])
        mean_volume = data.volume.mean()
        max_volume  = data.volume.max()
        if(max_volume <= mean_volume*up_volume_r):
            return_stocks.append(stock)
    return(return_stocks)
    
# 3-5 集合竞价成交量，按照成交量的比例排序，不能跌停或涨停的开盘价
def get_available_auction_stock(context, stock_list, raise_r=1.05):
    rank = []
    current_data = get_current_data()
    cur_date  = context.current_dt.strftime("%Y-%m-%d")
    cur_start = cur_date+' 09:25:00'
    cur_end   = cur_date+' 09:26:00'
    for stock in stock_list:
        tick_data = get_ticks(stock, cur_end, cur_start,None,['volume','current'], skip=False,df=True)
        yes_data  = attribute_history(stock, 1, '1d', ['volume','money','close'])
        if(len(tick_data.current) and len(tick_data.volume)):
            log.info("%s, %f"%(stock, (tick_data.volume[0]*100/yes_data.volume[0])))
            if(tick_data.current[0] > current_data[stock].low_limit)and\
              (tick_data.current[0] < current_data[stock].high_limit)and\
              (tick_data.current[0] < yes_data.close[0]*raise_r):
                  rank.append([stock, (tick_data.volume[0]*100/yes_data.volume[0])])
    rank.sort(key=lambda x: x[1],reverse=True)
    return_stocks = [item[0] for item in rank]
    return(return_stocks)



# 4-1 昨日购买股票未跌破x，或者涨幅未超过y的股票保留，已经涨停股票保留
def add_hold_stock(context, stock_list, fall_r=0.96):
    return_stocks = stock_list
    has_stocks = context.portfolio.positions.keys()
    for stock in has_stocks:
        stk_data = attribute_history(stock, 1, '1d', ['close','high_limit','pre_close'])
        if(stk_data.close[0]>=stk_data.pre_close[0]*fall_r)and\
          (stock not in return_stocks):
            return_stocks.insert(0, stock)
    return(return_stocks)
    
# 4-2 调整涨幅过大的股票
def check_raise_up(context):
    raise_r = 1.09
    fall_r  = 0.94
    current_data = get_current_data()
    holding_list = list(context.portfolio.positions)
    if holding_list:
        for stock in holding_list:
            if (current_data[stock].last_price < current_data[stock].high_limit):
                if(current_data[stock].last_price >= context.portfolio.positions[stock].avg_cost*raise_r)or\
                  (current_data[stock].last_price <= context.portfolio.positions[stock].avg_cost*fall_r):
                    log.info("[%s]涨幅或跌幅过大，卖出" % stock)
                    position = context.portfolio.positions[stock]
                    close_position(position)

