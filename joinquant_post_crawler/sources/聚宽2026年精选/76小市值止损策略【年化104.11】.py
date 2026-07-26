# 克隆自聚宽文章：https://www.joinquant.com/post/47721
# 标题：小市值止损策略【年化104.11% 最大回撤30.65%】
# 作者：天山灵兔

# 克隆自聚宽文章：https://www.joinquant.com/post/47523
# 标题：十年回测  年化103.32%  最大回撤23.89%
# 作者：jason_99

# 克隆自聚宽文章：https://www.joinquant.com/post/47346
# 标题：14-24【年化86%|胜率66%|回撤33%】无未来函数
# 作者：zycash

#导入函数库
from jqdata import *
from jqfactor import *
import numpy as np
import pandas as pd
import random
from datetime import time
#import datetime
#初始化函数 
def initialize(context):
    # 开启防未来函数，设定基线，真实价格，滑点及交易成本
    set_option('avoid_future_data', True)
    set_benchmark('000001.XSHG')
    set_option('use_real_price', True)
    set_slippage(FixedSlippage(3/10000))
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=2.5/10000, 
        close_commission=2.5/10000, close_today_commission=0, min_commission=5),type='stock')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    log.set_level('system', 'error')
    log.set_level('strategy', 'debug')
    #初始化全局变量 bool
    g.trading_signal = True  # 是否为可交易日
    g.pass_months = True  # 是否一四月空仓
    g.run_stoploss = True  # 是否进行止损
    #全局变量list
    g.hold_list = [] #当前持仓的全部股票    
    g.yesterday_HL_list = [] #记录持仓中昨日涨停的股票
    g.target_list = []  #准备买入的标的
    g.not_buy_again = []    #不再买入的标的
    g.history_hold_list = [] #持仓历史记录

    #全局变量float/str
    g.stock_num = 5
    g.up_price = 80  # 设置股票单价
    g.reason_to_sell = ''
    g.stoploss_limit = 0.07  # 止损线 0.07
    g.stoploss_market = 0.05  # 市场趋势止损参数
    g.limit_days = 5 #不再买入限制天数
    g.etf='511880.XSHG' #空仓买入银华日利ETF
    
    # 设置交易运行时间
    run_daily(prepare_stock_list, '9:00')       # 每天开盘前更新全局参数，持仓和昨日涨停
    run_weekly(weekly_adjustment,2,'10:00')     # 每周二上午10点检查并调仓，不会更新卖出原因
    run_daily(sell_stocks, time='10:30')        # 每天检查止损函数，止损会更新卖出原因
    run_daily(sell_stocks, time='14:00')        # 每天检查止损函数，止损会更新卖出原因
    # 涨停可能提前止盈并更新卖出原因，查看剩余金额，结合卖出原因决定是否需要买入，并重置卖出原因
    run_daily(trade_afternoon, time='14:30') 
    run_daily(close_account, '14:30')   # 特殊月份提前清仓
    # run_weekly(print_position_info, 5, time='15:30', reference_security='000300.XSHG')  # 每周5结束后统计持仓盈亏

#1-1 更新全局参数，每天开盘前运行
def prepare_stock_list(context):
    # 更新已持有列表
    g.hold_list= list(context.portfolio.positions)
    
    #更新最近一段时间持有过的股票列表
    g.not_buy_again = []
    if len(g.history_hold_list) >= g.limit_days:
        g.history_hold_list = g.history_hold_list[-g.limit_days:]
        
    # 更新持有股票中昨日涨停的股票
    if g.hold_list:
        df = get_price(g.hold_list, end_date=context.previous_date, frequency='daily', 
            fields=['close','high_limit','low_limit'], count=1, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        g.yesterday_HL_list = list(df.code)
    else:
        g.yesterday_HL_list = []
    #判断是否为特殊日期
    g.trading_signal = today_is_pass(context)

#1-2 选股模块，每周运行一遍
def get_stock_list(context):
    final_list = []
    by_date = context.previous_date - datetime.timedelta(days=375)  # 过滤次新股，上市不满1年的
    initial_list = get_index_stocks('399101.XSHE', by_date)          # 从中小综指中选股
    initial_list = filter_kcbj_stock(initial_list)          # 过滤科创北交所股票，改为保留沪深主板股票
    initial_list = filter_st_stock(initial_list)            # 过滤ST股票
    initial_list = filter_paused_stock(initial_list)        # 过滤停牌股票
    initial_list = filter_limitup_stock(context, initial_list)      # 过滤昨日涨停股票，持仓股不在此列
    initial_list = filter_limitdown_stock(context, initial_list)    # 过滤昨日跌停股票，持仓股不在此列
    initial_list = filter_highprice_stock(context, initial_list)    # 过滤股价过高的票，持仓股不在此列

    q = query(valuation.code,valuation.market_cap).filter(valuation.code.in_(initial_list),
        valuation.market_cap.between(5,50)).order_by(valuation.market_cap.asc())    # 5到50亿市值，从小到大排列
    df_fun = get_fundamentals(q)[:50]
    final_list  = list(df_fun.code)
    return final_list   # 返回前50只

#1-3 每周调整持仓
def weekly_adjustment(context):
    if g.trading_signal == True:
        #获取应买入列表 
        g.target_list = get_stock_list(context) # 选取50只符合条件的股票
        target_list = g.target_list[:g.stock_num]
        log.info("目标股："+str(target_list))
        #调仓卖出，没有更新卖出原因
        for stock in g.hold_list:
            if (stock not in target_list) and (stock not in g.yesterday_HL_list):   # 卖出非目标且非昨日涨停的股票
                position = context.portfolio.positions[stock]
                if not close_position(position):    # 卖出股票操作
                    log.info("！！！卖出失败[%s]" % (stock))
        #调仓买入
        buy_security(context,target_list)
 
#1-7 每天定点检查止损
def sell_stocks(context):
    if g.run_stoploss:
        #计算平均涨跌幅
        past_prices = history(2, '1d', 'close', get_index_stocks('399101.XSHE'))
        down_ratio = (past_prices.iloc[-1] / past_prices.iloc[0]).mean()
        #print(down_ratio)
        if down_ratio <= 1-g.stoploss_market:
            #g.reason_to_sell = 'stoploss'
            log.debug("基准指数暴跌,平均降幅{:.2%},全部清仓".format(1-down_ratio))
            for stock in context.portfolio.positions:
                order_target_value_(stock, 0)
        else:
            for stock in context.portfolio.positions:
                if context.portfolio.positions[stock].price < context.portfolio.positions[stock].avg_cost * (1-g.stoploss_limit):
                    log.debug("达到止损,卖出{}".format(stock))
                    order_target_value_(stock, 0)
                    g.reason_to_sell = 'stoploss'
                    g.not_buy_again.append(stock)  #记录止损股
            
#1-4 昨日涨停股票确定是否止盈，卖出时会记录卖出原因
def check_limit_up(context):
    if g.yesterday_HL_list:
        #对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
        current_data = get_current_data()
        for stock in g.yesterday_HL_list:
            if current_data[stock].last_price < current_data[stock].high_limit:
                position = context.portfolio.positions[stock]
                log.info("[%s]涨停打开，卖出" % (stock))
                if close_position(position):
                    g.reason_to_sell = 'limitup'
                    g.not_buy_again.append(stock)  #记录涨停开板股
            else:
                log.info("[%s]涨停，继续持有" % (stock))
                
    g.history_hold_list.append(g.not_buy_again)

#1-5 如果账户还有金额则执行此操作，会重置卖出原因
def check_remain_amount(context):
    if g.reason_to_sell in ['limitup', 'stoploss']: #判断售出原因，如果是涨停售出则可以再次交易，如果是止损后再交易收益更高
        g.hold_list= list(context.portfolio.positions)
        if len(g.hold_list) < g.stock_num:
            target_list = g.target_list     # 每周更新的股票池
            target_list = filter_not_buy_again(target_list)     # 排除涨停开板、止损股
            target_list = target_list[:min(g.stock_num, len(target_list))]
            log.info('有余额可用'+str(round((context.portfolio.cash),2))+'元。'+ str(target_list))
            buy_security(context,target_list)
        g.reason_to_sell = ''
   
    
#1-6 下午检查交易
def trade_afternoon(context):
    if g.trading_signal == True:
        check_limit_up(context)
        check_remain_amount(context)
    else:
        #空仓买日银华日利
        value = context.portfolio.available_cash
        if value>0 and g.etf not in context.portfolio.positions:
            order_value(g.etf, value)

#2-1 过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]

#2-2 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list
            if not current_data[stock].is_st
            and 'ST' not in current_data[stock].name
            and '*' not in current_data[stock].name
            and '退' not in current_data[stock].name]

#2-3 过滤科创北交股票，改为仅保留沪深主板股票
def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:3] == '688' or stock[:3] == '300':
            stock_list.remove(stock)
    return stock_list

#2-4 过滤除持仓外涨停的股票
def filter_limitup_stock(context, stock_list):
    df = get_price(stock_list, end_date=context.previous_date, frequency='daily', 
        fields=['close','high_limit','low_limit'], count=1, panel=False, fill_paused=False)
    df = df[df['close'] == df['high_limit']]
    return [stock for stock in stock_list if stock in g.hold_list or stock not in list(df.code)]

#2-5 过滤除了持仓外跌停的股票
def filter_limitdown_stock(context, stock_list):
    df = get_price(stock_list, end_date=context.previous_date, frequency='daily', 
        fields=['close','high_limit','low_limit'], count=1, panel=False, fill_paused=False)
    df = df[df['close'] == df['low_limit']]
    return [stock for stock in stock_list if stock in g.hold_list or stock not in list(df.code)]

#2-6 过滤次新股
def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date <  datetime.timedelta(days=375)]

#2-6.5 过滤除持仓外股价过高的
def filter_highprice_stock(context,stock_list):
	last_prices = history(1, unit='1d', field='close', security_list=stock_list)
	return [stock for stock in stock_list if stock in g.hold_list or
		last_prices[stock][-1] <= g.up_price]

#2-7 删除本周一买入的股票
def filter_not_buy_again(stock_list):
    # 获取不再买股票列表
    temp_set = set()
    for hold_list in g.history_hold_list:
        temp_set = temp_set.union(set(hold_list))
    not_buy_again_list = list(temp_set)
    
    return [stock for stock in stock_list if stock not in not_buy_again_list]
 
#3-1 交易模块-自定义下单
def order_target_value_(security, value):
    if value == 0:
        log.info("卖出[%s]" % (security))
    else:
        log.info("买入[%s]（%s元）" % (security,value))
    return order_target_value(security, value)

#3-2 交易模块-开仓
def open_position(security, value):
    order = order_target_value_(security, value)
    if order != None and order.filled > 0:
        return True
    return False

#3-3 交易模块-平仓，调仓，止盈，特殊月份卖出用这个函数，止损不是这个
def close_position(position):
    security = position.security
    order = order_target_value_(security, 0)  # 可能会因停牌失败
    if order != None:
        if order.status == OrderStatus.held and order.filled == order.amount:
            return True
    return False

#3-4 买入模块
def buy_security(context,target_list):
    #调仓买入
    position_count = len(context.portfolio.positions)   # 持仓股数量
    target_num = len(target_list)                       # 目标股数量
    if target_num > position_count:
        value = context.portfolio.available_cash / (target_num - position_count)
        for stock in target_list:
            if stock not in context.portfolio.positions:
                if open_position(stock, value):
                    if len(context.portfolio.positions) == target_num:
                        break


#4-1 判断今天是否为特殊时间段
def today_is_pass(context):
    if g.pass_months:
        today = context.current_dt.strftime('%m-%d')
        if (('04-05' <= today) and (today <= '04-30')) or (('01-01' <= today) and (today <= '01-31')):
            return False
        else:
            return True
    else:
        return True

#4-2 特殊月份清仓
def close_account(context):
    if g.trading_signal == False:
        for stock in g.hold_list:
            if stock != g.etf:
                position = context.portfolio.positions[stock]
                if not close_position(position):
                    log.info("！！！卖出失败[%s]" % (stock))

