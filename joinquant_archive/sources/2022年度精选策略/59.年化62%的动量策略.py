# 克隆自聚宽文章：https://www.joinquant.com/post/39838
# 标题：年化62%的动量策略
# 作者：逸_

#导入函数库
from jqdata import *
from jqfactor import get_factor_values
import numpy as np
import pandas as pd
from heapq import nlargest

#初始化函数 
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 设置交易成本万分之三
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),type='fund')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    #选股参数
    g.stock_num = 10 #持仓数
    g.day_count = 91 #动量计算参数
    g.stock_price = 5 #股价筛选参数
    # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    # 开盘时运行
    run_daily(market_open, time='open', reference_security='000300.XSHG')
    run_daily(print_trade_info, time='15:30', reference_security='000300.XSHG')

## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))

    # 要操作的股票：（g.为全局变量）
    initial_list = get_all_securities().index.tolist()
    initial_list = filter_trade_stock(context, initial_list)
    initial_list = filter_new_stock(context,initial_list)
    initial_list = filter_paused_stock(initial_list)
    initial_list = filter_st_stock(initial_list)
    #接下来预持有的代码
    next_holding_codes = get_momentum(context, initial_list)
    #持有的代码
    holding_codes=list(context.portfolio.positions.keys())
    #在昨日持仓列表中而不在今日预持仓列表中
    g.security1 = [x for x in holding_codes if x not in next_holding_codes]  
    #在今日预持仓列表中而不在昨日持仓列表中
    g.security2 = [y for y in next_holding_codes if y not in holding_codes]  
        
    # 给微信发送消息（添加模拟交易，并绑定微信生效）
    # send_message('美好的一天~')

## 开盘时运行函数
def market_open(context):
    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    security1 = g.security1
    security2 = g.security2
    #平仓
    for stock in security1:
        order_target(stock, 0)
    #开仓
    cash = context.portfolio.available_cash / len(security2)
    for stock in security2:
        order_value(stock, cash)
    
    
#定义获取最大几个值所在键和最小几个值所在键
def max_dict(d, n):
    return nlargest(n, d, key=lambda k: d[k])
    
def min_dict(d, n):
    return nlargest(n, d, key=lambda k: -d[k])

#计算动量，选出动量最大的指定个数
def get_momentum(context, stock_list):
    stock_momentum = {}
    for stock in stock_list:
        #get_price获取的包含当天的数据，开盘前就执行的话，会造成未来函数，截止日期需要向前减一天
        df = get_price(stock, count=g.day_count, end_date=context.current_dt-datetime.timedelta(days=1), fields= ['close'], skip_paused=True, panel=False)
        if df['close'][-1] < g.stock_price:
            continue
        stock_momentum[stock] = (df['close'][-1] - df['close'][0]) / df['close'][0]
    next_hold = min_dict(stock_momentum, g.stock_num)
    return next_hold

#1 过滤模块-选取主板、中小板
#输入股票列表，返回选取主板、中小板后的列表
def filter_trade_stock(context, stock_list):
    return [stock for stock in stock_list  if stock[0:2] == '60' or stock[0:2] == '00']
    
#2 过滤次新股
#输入股票列表，返回剔除上市日期不足250日股票后的列表
def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=250)]

#3 过滤模块-过滤停牌股票
#输入选股列表，返回剔除停牌股票后的列表
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]

#4 过滤模块-过滤ST及其他具有退市标签的股票
#输入选股列表，返回剔除ST及其他具有退市标签股票后的列表
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list
            if not current_data[stock].is_st
            and 'ST' not in current_data[stock].name
            and '*' not in current_data[stock].name
            and '退' not in current_data[stock].name]



#复盘模块-打印
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
