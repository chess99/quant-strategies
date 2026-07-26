# 克隆自聚宽文章：https://www.joinquant.com/post/35994
# 标题：RSI学习贴
# 作者：蚂蚁量化

# 克隆自聚宽文章：https://www.joinquant.com/post/34794
# 标题：关于rsi策略有效性,年化依然有56%的收益
# 作者：潜水的白鱼

#策略经过改进，更加简洁，只是单纯的rsi指标也能获得丰厚的收益

# 克隆自聚宽文章：https://www.joinquant.com/post/34021
# 标题：RSRS+RSI择时策略，股票池从基金重仓股中选取。
# 作者：Yeah_CD

# 克隆自聚宽文章：https://www.joinquant.com/post/34021
# 标题：RSRS+RSI择时策略，股票池从基金重仓股中选取。
# 作者：Yeah_CD

from jqdata import *
import pandas as pd
import numpy as np
import datetime
import statsmodels.api as sm  # 线性回归
import talib

# 初始化函数，设定基准等等
def initialize(context):
    set_param()
    run_daily(stock_order,time='9:30')
#    run_daily(stock_order,time='14:30')

def stock_order(context):
    # 4、取得买卖信号
    get_RSRS_signal(context)
    # 5、下单
    orderStock(context)


#----计算股票池中每只股票的买卖信号，加入买卖股票列表中-------------------
def get_RSRS_signal(context):
    rsi_code=[]
    buys=[]
    sells=[]
    buy_flag=0

    pool = g.pool #股票池在默认参数里面
        
    #1、取得股票的历史价格
    for stockcode in pool:


        prices = attribute_history(stockcode, 61, '1d', ('close')) #获得一只股票的历史收盘价，历史数据是不包括当天数据的
        # 创建RSI买卖信号，包括参数timeperiod
        # 注意：RSI函数使用的price必须是narray
        try:
            rsi = talib.RSI(prices['close'].values, timeperiod=6)[-1] #6日周期
            rsi = int(rsi)
        except:
            ris = 100
        #3、形成买卖股票list
#        if signal_revise > g.B and rsi < 40:
        if 15 < rsi < 25:
            rsi_code.append((rsi,stockcode))
            buy_flag = 1
#            log.info('buy code:'+str(stockcode)+'  RSI = ' + str(rsi) + '  Signal = ' + str(signal_revise))
#        elif signal_revise < g.S or rsi > 85: 
        elif rsi > 85 or rsi < 10: 
            sells.append(stockcode)
#            log.info('sell code:'+str(stockcode)+'  RSI = ' + str(rsi) + '  Signal = ' + str(signal_revise))

    if buy_flag == 1:
#        rsi_code.sort(key=lambda x:x[0],reverse=True)
        rsi_code.sort(key=lambda x:x[0]) #按照rsi的大小进行排列
        buys = np.array(rsi_code)
        g.buy = list(buys[:,1])
    else:
        g.buy = []

    g.sell = sells
    log.info('buy list: ' +str(g.buy))

    
    
def orderStock(context):
    # type: (Context) -> None
    buys = g.buy
    sells = g.sell

    curr_data_b = get_current_data(buys)  #获得当前买入价
    curr_data_s = get_current_data(sells) #获得当前卖出价
    
    all_value = context.portfolio.total_value #获得所有资产价值
    
    ####卖出的部分，的代码
    for sell_code in context.portfolio.long_positions.keys(): #多单的仓位 首先他会循环很多遍
        if sell_code  in sells: #其次他要确认在里面
            if curr_data_s[sell_code].last_price >= curr_data_s[sell_code].high_limit:  #涨停不卖
                continue
            elif context.portfolio.positions[sell_code].closeable_amount > 0: #可卖出餐位大于0
                # 全部卖掉
                log.info('sell all: ', sell_code)
                order_target_value(sell_code, 0)
        if sell_code not in g.pool: #如果发现要卖的股票不在股票池，卖出
            # 卖掉
            log.info('sell all: ', sell_code)
            order_target_value(sell_code, 0)
            
    ####买入部分的代码
    for buy_code in buys:   # buy pool
        if buy_code not in context.portfolio.long_positions.keys():
            cash_value = context.portfolio.available_cash   #可用现金
            if (g.stock_num - len(context.portfolio.positions)) > 0:  #6最多买6支股票，只要还有名额就可以使用
                if curr_data_b[buy_code].last_price <= curr_data_b[buy_code].low_limit:  #跌停不买
                    continue
                else:
                    buy_value = cash_value / (g.stock_num - len(context.portfolio.positions))
                    log.info('buy:  ' + buy_code + '   ' + str(buy_value))
                    order_target_value(buy_code, buy_value)

def set_param():
    #定义RSRS计算周期和序列长度

    g.buy = []
    g.sell = []

    g.pool = ['603799.XSHG','300750.XSHE','601633.XSHG','603659.XSHG','002594.XSHE','603259.XSHG',
            '601012.XSHG','000661.XSHE','600763.XSHG','300359.XSHE','300347.XSHE','300014.XSHE',
            '300661.XSHE','300073.XSHE','002050.XSHE','002714.XSHE','601888.XSHG','002407.XSHE',
            '002456.XSHE','300782.XSHE','000333.XSHE','002088.XSHE','600660.XSHG','002597.XSHE',
            '002821.XSHE','600276.XSHG','600196.XSHG','002371.XSHE','300595.XSHE','300750.XSHE',
            '600309.XSHG','002352.XSHE','300357.XSHE','300009.XSHE','300702.XSHE','002595.XSHE',
            '300036.XSHE','300037.XSHE','601058.XSHG','601677.XSHG','601222.XSHG','002286.XSHE'
          ]

    g.stock_num = 9  #2020-09-07，6->10
    # 显示所有列
    pd.set_option('display.max_columns', None)
    # 显示所有行
    pd.set_option('display.max_rows', None)
    # 设置value的显示长度为100，默认为50
    pd.set_option('max_colwidth', 100)

    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)

    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5),
                   type='stock')


#----------------------------------------------------------

