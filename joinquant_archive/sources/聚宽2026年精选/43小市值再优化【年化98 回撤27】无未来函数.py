# 克隆自聚宽文章：https://www.joinquant.com/post/47562
# 标题：小市值再优化【年化98%|胜率69%|回撤27%】无未来函数
# 作者：zycash

#本策略为www.joinquant.com/post/47346的改进版本
#导入函数库
from jqdata import *
from jqfactor import *
import numpy as np
import pandas as pd
from datetime import time
#import datetime
#初始化函数 
def initialize(context):
    # 开启防未来函数
    set_option('avoid_future_data', True)
    # 设定基准
    set_benchmark('000001.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(3/10000))
    # 设置交易成本万分之三，不同滑点影响可在归因分析中查看
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=2.5/10000, close_commission=2.5/10000, close_today_commission=0, min_commission=5),type='stock')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    log.set_level('system', 'error')
    log.set_level('strategy', 'debug')
    #初始化全局变量 bool
    g.trading_signal = True  # 是否为可交易日
    g.run_stoploss = True  # 是否进行止损
    #全局变量list
    g.hold_list = [] #当前持仓的全部股票    
    g.yesterday_HL_list = [] #记录持仓中昨日涨停的股票
    g.target_list = []
    g.pass_months = [1,4]  # 空仓的月份
    g.limitup_stocks = []   # 记录涨停的股票避免再次买入
    #全局变量float/str
    g.stock_num = 9
    g.reason_to_sell = ''
    g.stoploss_strategy = 3  # 1为止损线止损，2为市场趋势止损, 3为联合1、2策略
    g.stoploss_limit = 0.1  # 止损线
    g.stoploss_market = 0.05  # 市场趋势止损参数
    g.etf = '511880.XSHG'  # 空仓月份持有银华日利ETF
    # 设置交易运行时间
    run_daily(prepare_stock_list, '9:05')
    run_daily(trade_afternoon, time='14:00', reference_security='399101.XSHE') #检查持仓中的涨停股是否需要卖出
    run_daily(sell_stocks, time='10:00') # 止损函数
    run_daily(close_account, '14:50')
    run_weekly(weekly_adjustment,2,'10:00')
    #run_weekly(print_position_info, 5, time='15:10', reference_security='000300.XSHG')

#1-1 准备股票池
def prepare_stock_list(context):
    #获取已持有列表
    g.hold_list= []
    g.limitup_stocks = []
    for position in list(context.portfolio.positions.values()):
        stock = position.security
        g.hold_list.append(stock)
    #获取昨日涨停列表
    if g.hold_list != []:
        df = get_price(g.hold_list, end_date=context.previous_date, frequency='daily', fields=['close','high_limit','low_limit'], count=1, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        g.yesterday_HL_list = list(df.code)
    else:
        g.yesterday_HL_list = []
    #判断今天是否为账户资金再平衡的日期
    g.trading_signal = today_is_between(context)

#1-2 选股模块
def get_stock_list(context):
    final_list = []
    MKT_index = '399101.XSHE'
    initial_list = filter_stocks(context, get_index_stocks(MKT_index))
    q = query(valuation.code,valuation.market_cap).filter(valuation.code.in_(initial_list),valuation.market_cap.between(5,300)).order_by(valuation.market_cap.asc())
    df_fun = get_fundamentals(q)
    df_fun = df_fun[:g.stock_num*3]
    final_list  = list(df_fun.code)
    return final_list

#1-3 整体调整持仓
def weekly_adjustment(context):
    if g.trading_signal == True:
        #获取应买入列表 
        g.target_list = get_stock_list(context)[:g.stock_num]
        log.info(str(g.target_list))
        #调仓卖出
        sell_list = []  # 售出持仓
        hold_list = []  # 不变持仓
        for stock in g.hold_list:
            if (stock not in g.target_list) and (stock not in g.yesterday_HL_list):
                sell_list.append(stock)
                position = context.portfolio.positions[stock]
                close_position(position)
            else:
                hold_list.append(stock)
        log.info("已持有[%s]" % (str(hold_list)))
        log.info("卖出[%s]" % (str(sell_list)))
        #调仓买入
        buy_security(context,g.target_list)
        #记录已买入股票
        for position in list(context.portfolio.positions.values()):
            stock = position.security
    else:
        buy_security(context,[g.etf])
        log.info('该月份为空仓月份，持有银华日利ETF')

#1-4 调整昨日涨停股票
def check_limit_up(context):
    now_time = context.current_dt
    if g.yesterday_HL_list != []:
        #对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
        for stock in g.yesterday_HL_list:
            current_data = get_price(stock, end_date=now_time, frequency='1m', fields=['close','high_limit'], skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True)
            if current_data.iloc[0,0] <    current_data.iloc[0,1]:
                log.info("[%s]涨停打开，卖出" % (stock))
                position = context.portfolio.positions[stock]
                close_position(position)
                g.reason_to_sell = 'limitup'
                g.limitup_stocks.append(stock)
            else:
                log.info("[%s]涨停，继续持有" % (stock))

#1-5 如果昨天有股票卖出或者买入失败，剩余的金额今天早上买入
def check_remain_amount(context):
    if g.reason_to_sell is 'limitup': #判断提前售出原因，如果是涨停售出则次日再次交易，如果是止损售出则不交易
        g.hold_list= []
        for position in list(context.portfolio.positions.values()):
            stock = position.security
            g.hold_list.append(stock)
        if len(g.hold_list) < g.stock_num:
            # 计算需要买入的股票数量
            num_stocks_to_buy = min(len(g.limitup_stocks), g.stock_num - len(context.portfolio.positions))
            target_list = [stock for stock in g.target_list if stock not in g.limitup_stocks][:num_stocks_to_buy]
            log.info('有余额可用'+str(round((context.portfolio.cash),2))+'元。买入'+ str(target_list))
            buy_security(context,target_list)
        g.reason_to_sell = ''
    elif g.reason_to_sell is 'stoploss':
        log.info('有余额可用'+str(round((context.portfolio.cash),2))+'元。买入'+ str(g.etf))
        buy_security(context,[g.etf])
        g.reason_to_sell = ''

#1-6 下午检查交易
def trade_afternoon(context):
    if g.trading_signal == True:
        check_limit_up(context)
        check_remain_amount(context)
        
#1-7 止盈止损
def sell_stocks(context):
    if g.run_stoploss:
        current_positions = context.portfolio.positions

        if g.stoploss_strategy == 1 or g.stoploss_strategy == 3:
            for stock in current_positions.keys():
                price = current_positions[stock].price
                avg_cost = current_positions[stock].avg_cost
                # 个股盈利止盈
                if price >= avg_cost * 2:
                    order_target_value(stock, 0)
                    log.debug("收益100%止盈,卖出{}".format(stock))
                # 个股止损
                elif price < avg_cost * (1 - g.stoploss_limit):
                    order_target_value(stock, 0)
                    log.debug("收益止损,卖出{}".format(stock))
                    g.reason_to_sell = 'stoploss'

        if g.stoploss_strategy == 2 or g.stoploss_strategy == 3:
            stock_df = get_price(security=get_index_stocks('399101.XSHE'), end_date=context.previous_date, frequency='daily', fields=['close', 'open'], count=1, panel=False)
            down_ratio = abs((stock_df['close'] / stock_df['open'] - 1).mean())
            # 市场大跌止损
            if down_ratio >= g.stoploss_market:
                g.reason_to_sell = 'stoploss'
                log.debug("大盘惨跌,平均降幅{:.2%}".format(down_ratio))
                for stock in current_positions.keys():
                    order_target_value(stock, 0)

#2 过滤各种股票
def filter_stocks(context, stock_list):
    current_data = get_current_data()
        # 涨跌停和最近价格的判断
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
        # 过滤标准
    filtered_stocks = []
    for stock in stock_list:
        if current_data[stock].paused:  # 停牌
            continue
        if current_data[stock].is_st:  # ST
            continue
        if '退' in current_data[stock].name:  # 退市
            continue
        if stock.startswith('30') or stock.startswith('68') or stock.startswith('8') or stock.startswith('4'):  # 市场类型
            continue
        if not (stock in context.portfolio.positions or last_prices[stock][-1] < current_data[stock].high_limit):  # 涨停
            continue
        if not (stock in context.portfolio.positions or last_prices[stock][-1] > current_data[stock].low_limit):  # 跌停
            continue
        # 次新股过滤
        start_date = get_security_info(stock).start_date
        if context.previous_date - start_date < timedelta(days=375):
            continue
        filtered_stocks.append(stock)
    return filtered_stocks

#3-1 交易模块-自定义下单
def order_target_value_(security, value):
    if value == 0:
        pass
        #log.debug("Selling out %s" % (security))
    else:
        log.debug("Order %s to value %f" % (security, value))
    return order_target_value(security, value)

#3-2 交易模块-开仓
def open_position(security, value):
    order = order_target_value_(security, value)
    if order != None and order.filled > 0:
        return True
    return False

#3-3 交易模块-平仓
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
    position_count = len(context.portfolio.positions)
    target_num = len(target_list)
    if target_num > position_count:
        value = context.portfolio.cash / (target_num - position_count)
        for stock in target_list:
            if context.portfolio.positions[stock].total_amount == 0:
            #if stock not in context.portfolio.positions:
                if open_position(stock, value):
                    log.info("买入[%s]（%s元）" % (stock,value))
                    if len(context.portfolio.positions) == target_num:
                        break


#4-1 判断今天是否跳过月份
def today_is_between(context):
    # 根据g.pass_month跳过指定月份
    today = context.current_dt
    month = today.month
    if month in g.pass_months:
        return False
    else:
        return True


#4-2 清仓后次日资金可转
def close_account(context):
    if g.trading_signal == False:
        if len(g.hold_list) != 0 and g.hold_list != [g.etf]:
            for stock in g.hold_list:
                position = context.portfolio.positions[stock]
                close_position(position)
                log.info("卖出[%s]" % (stock))


def print_position_info(context):
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
    print('———————————————————————————————————————分割线————————————————————————————————————————')
