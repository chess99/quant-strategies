# 克隆自聚宽文章：https://www.joinquant.com/post/50559
# 标题：固收+
# 作者：开心果

from jqdata import *
import numpy as np
import pandas as pd
from scipy.linalg import inv
import warnings
warnings.filterwarnings("ignore")

#初始化函数 
def initialize(context):
    set_benchmark("511010.XSHG")
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    set_slippage(FixedSlippage(0.002))
    set_order_cost(OrderCost(open_tax=0, close_tax=0, open_commission=0.0002, close_commission=0.0002, close_today_commission=0, min_commission=5), type='fund')
    log.set_level('order', 'error')
    g.weights = {'510880.XSHG':0.08,'513100.XSHG':0.08, '518880.XSHG':0.14, "511010.XSHG":0.7}
    run_daily(trade, '9:35') 

# 交易
def trade(context):
    total_value = context.portfolio.total_value
    cdata = get_current_data()
    weights = g.weights
    balance = {}
    for stock in weights.keys():
        value = total_value * weights[stock] 
        if stock in context.portfolio.positions:
            diff = (value - context.portfolio.positions[stock].value)
        else:
            diff = value
        balance[stock] = diff
        
    rebalance = dict(sorted(balance.items(),key= lambda x: x[1],reverse=False))
    for stock in rebalance.keys():
        value = total_value * weights[stock]
        if abs(balance[stock]) >0.15*value and abs(balance[stock]/cdata[stock].last_price) >100:
            if balance[stock] < 0:
                order_target_value(stock, value)
            elif context.portfolio.cash / cdata[stock].last_price >100:
                order_target_value(stock, value)
            
