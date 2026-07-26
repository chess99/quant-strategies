# 克隆自聚宽文章：https://www.joinquant.com/post/27255
# 标题：欧奈尔 RPS选股战法回测
# 作者：子不语19

# 导入函数库
from jqdata import *
from kuanke.wizard import *
import numpy as np
import pandas as pd
import talib
import datetime

# 初始化函数，设定基准等等
def initialize(context):
    # parameter list
    g.rps_period = 120
    g.max_stock_num = 5
    g.filter_over_increase_percent=0.5 #过滤 超过限定涨幅的 rps 股票
    g.min_rps = 85 # 只选择 min 以上的 股票 买入
    
    
    # avoid future data
    set_option("avoid_future_data", True)
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
   
    
    
    g.security_universe_index = ["000300.XSHG"] # 选股"000300.XSHG" 沪深300 "399101.XSHE" 中小版  "399102.XSHE" 创业板
    g.watch_list = get_security_universe(context, g.security_universe_index, [])
    
    g.check_out_list = []
    g.cur_stock_num = 0


    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='before_open')
    run_daily(market_open, time='14:25', reference_security='000300.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')


#----------------------------------------------------------------------------

## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    g.check_out_list = []
    g.check_out_list = rps_select(context,g.watch_list) # 根据rps指标选股
    
def rps_select(context, stock_list):
    stock_dict = {}
    over_increase_list = []
    
    for stock in stock_list:
        rps_data = get_bars(stock, count=g.rps_period, unit='1d', fields=['close'], include_now=False)
        increase = rps_data['close'][-1]/rps_data['close'][0] - 1
        if increase > g.filter_over_increase_percent:
            over_increase_list.append(stock)
        stock_dict[stock]=increase
        
    a = sorted(stock_dict.items(), key=lambda x: x[1],reverse=True)
    rank = 1
    
    g.rps_dict = stock_dict
    
    rps_list = []
    for x in a:
        rps = (1 - rank/len(g.watch_list))*100
        rps_list.append((x[0],rps))
        rank += 1
    
    select_num = 10
    final_list = []
    for x in rps_list:
        if x[1] < g.min_rps:
            break
        if x[0] not in over_increase_list:
            select_num -= 1
            final_list.append(x[0])
    return final_list # 最多选10只 符合rps 条件的股票

## 开盘时运行函数
def market_open(context):
    #run every 15 mins
    #if context.current_dt.minute % 30 != 0:
    #    return
    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    buy_list = g.check_out_list
        
    for stock in context.portfolio.positions.keys():
        sell(context,stock)
        
    for stock in buy_list:
        buy(context, stock)
    

def buy(context,security):    
    g.cur_stock_num = len(context.portfolio.positions)
    if g.cur_stock_num >= g.max_stock_num: 
        return
    # 取得当前的现金
    cash = context.portfolio.available_cash
    
    if cash < 100: # 余额不足 
        return
    # 如果上一时间点价格高出五天平均价1%, 则全仓买入
    if (cash > 0):
        # 记录这次买入
        log.info("符合条件 , 买入 %s" % (security))
        # 等分的 cash 买入股票
        remaining_stock_num = g.max_stock_num - g.cur_stock_num
        
        cash_for_stock = 1/remaining_stock_num * cash
        # 避免重复买入同一只股票
        if security not in context.portfolio.positions.keys():
            order_value(security, cash_for_stock)
            
def sell(context,security):
    # 卖出条件 90天涨幅小于0.3 而且 价格低于100日均线
    if  n_day_chg_xiaoyu(security, 90, 0.3) and situation_filter_xiaoyu_ma(security, 'close', 100) and context.portfolio.positions[security].closeable_amount > 0:
        # 记录这次卖出
        log.info("价格低于卖出条件， 卖出 %s" % (security))
        # 卖出所有股票,使这只股票的最终持有量为0
        order_target(security, 0)
        
       

# 获取股票股票池
def get_security_universe(context, security_universe_index, security_universe_user_securities):
    temp_index = []
    for s in security_universe_index:
        if s == 'all_a_securities':
            temp_index += list(get_all_securities(['stock'], context.current_dt.date()).index)
        else:
            temp_index += get_index_stocks(s)
    for x in security_universe_user_securities:
        temp_index += x
    return  sorted(list(set(temp_index)))

## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
        
    log.info('一天结束')
    log.info('##############################################################')
