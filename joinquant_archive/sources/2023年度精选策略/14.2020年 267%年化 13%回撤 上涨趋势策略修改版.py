# 克隆自聚宽文章：https://www.joinquant.com/post/31232
# 标题：2020年 267%年化 13%回撤 上涨趋势策略修改版
# 作者：苦咖啡

# 克隆自聚宽文章：https://www.joinquant.com/post/30863
# 标题：上涨股策略2020年收益123%
# 作者：scottchenrui

from kuanke.wizard import *
from jqdata import *
import numpy as np
import pandas as pd
import talib
import datetime
import numpy as np 
import pylab as pl
import matplotlib.pyplot as plt
import scipy.signal as signal
import heapq
from sklearn.linear_model import LinearRegression

## 初始化函数，设定要操作的股票、基准等等
def initialize(context):
    # 设定基准
    set_benchmark('000300.XSHG')
    # 设定滑点
    set_slippage(FixedSlippage(0.02))
    # True为开启动态复权模式，使用真实价格交易
    set_option('use_real_price', True)
    # 设定成交量比例
    set_option('order_volume_ratio', 1)
    # 股票类交易手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    # 个股最大持仓比重
    g.security_max_proportion = 1

    g.check_stocks_refresh_rate = 120
    # 回测天数

    # 买入频率
    g.buy_refresh_rate = 10
    # 卖出频率
    g.sell_refresh_rate = 10
    # 最大建仓数量
    g.max_hold_stocknum = 2
    # 平均建仓数量
    g.avg_hold = 0
    # 天数计数
    g.day_check = 0


    # 买卖交易频率计数器
    g.buy_trade_days=0
    g.sell_trade_days=0
    # 获取未卖出的股票
    g.open_sell_securities = []
    # 卖出股票的dict
    g.selled_security_list={}

    # 股票筛选初始化函数
    check_stocks_initialize()
    # 股票筛选排序初始化函数
    check_stocks_sort_initialize()
    # 出场初始化函数
    sell_initialize()
    # 入场初始化函数
    buy_initialize()
    # 风控初始化函数
    risk_management_initialize()

    # 关闭提示
    log.set_level('order', 'error')

    # 运行函数
    # run_daily(sell_every_day,'open') #卖出未卖出成功的股票
   #  run_daily(risk_management, 'every_bar') #风险控制
    # run_daily(risk_control,'open') #风控
    run_weekly(check_stocks, 1,'open') #选股
    run_weekly(trade, 1,'open') #交易
    #  run_daily(selled_security_list_count, 'after_close') #卖出股票日期计数


## 股票筛选初始化函数
def check_stocks_initialize():
    # 是否过滤停盘
    g.filter_paused = True
    # 是否过滤退市
    g.filter_delisted = True
    # 是否只有ST
    g.only_st = False
    # 是否过滤ST
    g.filter_st = True
    # 股票池
    g.security_universe_index = ["all_a_securities"]
    g.security_universe_user_securities = []
    # 行业列表
    g.industry_list = ["801010","801020","801030","801040","801050","801080","801110","801120","801130","801140","801150","801160","801170","801180","801200","801210","801230","801710","801720","801730","801740","801750","801760","801770","801780","801790","801880","801890"]
    # 概念列表
    g.concept_list = []

## 股票筛选排序初始化函数
def check_stocks_sort_initialize():
    # 总排序准则： desc-降序、asc-升序
    g.check_out_lists_ascending = 'desc'

## 出场初始化函数
def sell_initialize():
    # 设定是否卖出buy_lists中的股票
    g.sell_will_buy = True

    # 固定出仓的数量或者百分比
    g.sell_by_amount = None
    g.sell_by_percent = None

## 入场初始化函数
def buy_initialize():
    # 是否可重复买入
    g.filter_holded = False

    # 委托类型
    #每次买入固定股数
    g.order_style_str = 'by_amount'
    g.order_style_value = 500
    #等权重买入
    #g.order_style_str = 'by_cap_mean'
    #g.order_style_value = 100
## 风控初始化函数
def risk_management_initialize():
    # 策略风控信号
    g.risk_management_signal = True

    # 策略当日触发风控清仓信号
    g.daily_risk_management = True

    # 单只最大买入股数或金额
    g.max_buy_value = None
    g.max_buy_amount = None

def risk_control(context):
    hold_stock = list(context.portfolio.positions.keys())
    stocks_close = history(60,'1d','close',hold_stock)
    for security in hold_stock:
        if max_high(security,60,0,59)/stocks_close[security][-1]>1.15:
            order_target_value(security,0)

## 股票筛选
def check_stocks(context):

    # 股票池赋值
    g.check_out_lists = get_up_security(context)#get_security_universe(context, g.security_universe_index, g.security_universe_user_securities) #
    # print(g.check_out_lists)
    # 行业过滤
    # g.check_out_lists = industry_filter(context, g.check_out_lists, g.industry_list)
    # 概念过滤
    # g.check_out_lists = concept_filter(context, g.check_out_lists, g.concept_list)
    # 过滤ST股票
    g.check_out_lists = st_filter(context, g.check_out_lists)
    # 过滤退市股票
    g.check_out_lists = delisted_filter(context, g.check_out_lists)

        # 过滤停牌股票
    g.check_out_lists = paused_filter(context, g.check_out_lists)

        # 过滤涨停股票
    g.check_out_lists = high_limit_filter(context, g.check_out_lists)
    # 财务筛选
    # g.check_out_lists = financial_statements_filter(context, g.check_out_lists)
    # 行情筛选
    # g.check_out_lists = situation_filter(context, g.check_out_lists)
    # 技术指标筛选
    # g.check_out_lists = technical_indicators_filter(context, g.check_out_lists)
    # 形态指标筛选函数
    # g.check_out_lists = pattern_recognition_filter(context, g.check_out_lists)
    # 其他筛选函数
    # g.check_out_lists = other_func_filter(context, g.check_out_lists)
    #print(g.check_out_lists)
    # 排序
    # input_dict = get_check_stocks_sort_input_dict()
    # g.check_out_lists = check_stocks_sort(context,g.check_out_lists,input_dict,g.check_out_lists_ascending)
    # sorted(g.check_out_lists,key=get_stock_score, reverse=False)[:g.max_hold_stocknum]
    g.check_out_lists.sort(key=get_stock_score, reverse=True)
    #print(g.check_out_lists)
    g.check_out_lists = g.check_out_lists[:g.max_hold_stocknum]
    g.avg_hold = g.avg_hold + len(g.check_out_lists)
    g.day_check = g.day_check + 1
    print(g.avg_hold/g.day_check)
    print(g.check_out_lists)
    # a=get_stock_score('601633.XSHG')


    return

## 交易函数
def trade(context):
   # 初始化买入列表
    buy_lists = []
        # 获取 buy_lists 列表
    buy_lists = g.check_out_lists

    # 卖出操作
    sell(context, buy_lists)
    # 买入操作
    buy(context, buy_lists)


## 卖出股票日期计数
def selled_security_list_count(context):
    g.daily_risk_management = True
    if len(g.selled_security_list)>0:
        for stock in g.selled_security_list.keys():
            g.selled_security_list[stock] += 1

##################################  选股函数群 ##################################

# 获取选股排序的 input_dict
def get_check_stocks_sort_input_dict():
    input_dict = {
        indicator.eps:('desc',1),
        }
    # 返回结果
    return input_dict

##################################  交易函数群 ##################################
# 交易函数 - 出场
def sell(context, buy_lists):
    # 获取 sell_lists 列表

    log.info('sell')
    hold_stock = list(context.portfolio.positions.keys())

    for s in hold_stock:        #卖出不在买入列表中的股票
        if s not in buy_lists:
            log.info(s  + get_security_info(s).display_name + ' sell')
            order_target_value(s,0)   
    return

# 交易函数 - 入场
def buy(context, buy_lists):
    # 风控信号判断
    if not g.risk_management_signal:
        return

    # 判断当日是否触发风控清仓止损
    if not g.daily_risk_management:
        return
  
    Num = len(buy_lists)
    # buy_lists = buy_lists[:Num]
    # 买入股票

    if len(buy_lists)>0:
        # 分配资金
        cash = context.portfolio.total_value
        #cash = context.portfolio.available_cash
        amount = cash/Num
        #result = order_style(context,buy_lists,len(buy_lists), g.order_style_str, g.order_style_value)
        hold_stock = list(context.portfolio.positions.keys())
        for stock in buy_lists:
            if stock  in hold_stock:
  
                log.info(stock + get_security_info(stock).display_name +' 购买资金：' +str(amount)  + ' 剩余资金：' + str(cash) +  ' 热度：' +  str(avg_volume(stock,7)/avg_volume(stock,180)))
                order_target_value(stock,amount)
                #order_value(stock,amount)
        for stock in buy_lists:
            if stock  not in hold_stock:
  
                log.info(stock + get_security_info(stock).display_name +' 购买资金：' +str(amount)  + ' 剩余资金：' + str(cash) +  ' 热度：' +  str(avg_volume(stock,7)/avg_volume(stock,180)))
                order_target_value(stock,amount)

    return

###################################  公用函数群 ##################################


## 过滤同一标的继上次卖出N天不再买入
def filter_n_tradeday_not_buy(security, n=0):
    try:
        if (security in g.selled_security_list.keys()) and (g.selled_security_list[security]<n):
            return False
        return True
    except:
        return True

## 是否可重复买入
def holded_filter(context,security_list):
    if not g.filter_holded:
        security_list = [stock for stock in security_list if stock not in context.portfolio.positions.keys()]
    # 返回结果
    return security_list

## 卖出股票加入dict
def selled_security_list_dict(context,security_list):
    selled_sl = [s for s in security_list if s not in context.portfolio.positions.keys()]
    if len(selled_sl)>0:
        for stock in selled_sl:
            g.selled_security_list[stock] = 0

## 过滤停牌股票
def paused_filter(context, security_list):
    if g.filter_paused:
        current_data = get_current_data()
        security_list = [stock for stock in security_list if not current_data[stock].paused]
    # 返回结果
    return security_list

## 过滤退市股票
def delisted_filter(context, security_list):
    if g.filter_delisted:
        current_data = get_current_data()
        security_list = [stock for stock in security_list if not (('退' in current_data[stock].name) or ('*' in current_data[stock].name))]
    # 返回结果
    return security_list


## 过滤ST股票
def st_filter(context, security_list):
    if g.only_st:
        current_data = get_current_data()
        security_list = [stock for stock in security_list if current_data[stock].is_st]
    else:
        if g.filter_st:
            current_data = get_current_data()
            security_list = [stock for stock in security_list if not current_data[stock].is_st]
    # 返回结果
    return security_list

# 过滤涨停股票
def high_limit_filter(context, security_list):
    current_data = get_current_data()
    security_list = [stock for stock in security_list if not (current_data[stock].day_open >= current_data[stock].high_limit)]
    # 返回结果
    return security_list



#获取上涨趋势的股票
def get_up_security(context):
    dfs=get_all_securities(types=['stock'], date=context.previous_date)
    dfs300=get_index_stocks("000300.XSHG", date=context.previous_date)
    #a = query(valuation.code).filter(valuation.market_cap > 1000,valuation.pe_ratio > 15,valuation.pe_ratio < 70)
    #dfs300  = list(get_fundamentals(a).code)
    #print(len(dfs300))
    #dfs=get_index_stocks("000300.XSHG", date='2020-12-20')
    temp_index = list()
    
    for s in dfs300:#dfs.index:
        df=attribute_history(s, g.check_stocks_refresh_rate, '1d', ('close'))
        if max_high(s,30,0,29)/df['close'][-1] > 1.1:
            continue
        if df['close'][-1] > 500:
            continue
        if avg_volume(s,7)/avg_volume(s,180) > 1.5:
            continue

        Y=np.array(df['close'].tolist())
    
        #  Y=x[signal.argrelextrema(x, np.less)]
        #  print(Y)
        #  print(len(Y))
        if len(Y)<=0 or np.isnan(Y).any():
            #print("------------"+s+"-------------------")
            continue
        X=range(len(Y))
        #转换成numpy的ndarray数据格式，n行1列,LinearRegression需要列格式数据，如下：
        X_train = np.array(X).reshape((len(X), 1))
        Y_train = np.array(Y).reshape((len(Y), 1))
        #新建一个线性回归模型，并把数据放进去对模型进行训练
        lineModel = LinearRegression()
        lineModel.fit(X_train, Y_train)
    
        #用训练后的模型，进行预测
        Y_predict = lineModel.predict(X_train)
    
        #coef_是系数，intercept_是截距
        a1 = lineModel.coef_[0][0]
        b = lineModel.intercept_[0]
        score=lineModel.score(X_train, Y_train)
        #print("y=%.4f*x+%.4f" % (a1,b))
        if a1/b>0.005 and score>0.8:
            temp_index.append(s)
            #print(Y)
            #print("%s y=%.4f*%.4f+%.4f stock:%s dayraise: %s score : %s" % (dfs.loc[s]['display_name'],a1,len(Y),b,s,a1/b,score))
            #print("%s %s"%(s,dfs.loc[s]['display_name']))

    #print('temp_index')
   # print(str(context.previous_date)+":".join(temp_index))
    return list(set(temp_index))

def get_stock_score(ele):
    df=attribute_history(ele, g.check_stocks_refresh_rate, '1d', ('close'))
    Y=np.array(df['close'].tolist())
    #print(Y)
    score=0
    if len(Y)>0:
        X=range(len(Y))
        #转换成numpy的ndarray数据格式，n行1列,LinearRegression需要列格式数据，如下：
        X_train = np.array(X).reshape((len(X), 1))
        Y_train = np.array(Y).reshape((len(Y), 1))
        #新建一个线性回归模型，并把数据放进去对模型进行训练
        lineModel = LinearRegression()
        lineModel.fit(X_train, Y_train)
        Y_predict = lineModel.predict(X_train)
        a1 = lineModel.coef_[0][0]
        b = lineModel.intercept_[0]
        score=lineModel.score(X_train, Y_train)
        marketcap = get_market_cap(ele)
    print(str(ele) + get_security_info(ele).display_name + ":" + str(a1/b*100) + ":" + str(score*10) + ":" + str(marketcap /5000))
    return score
#自定义函数

    
def get_market_cap(security):
    q = query(valuation.market_cap).filter(
                income.code == security,
            )
    return get_fundamentals(q).loc[0][0]
    
def avg_volume(security,timeperiod):
    security_data = attribute_history(security, timeperiod, '1d', ['volume'])
    avg_volume = security_data['volume'].mean()
    return avg_volume
    
def max_high(security,timeperiod,start,end):
    max_high = attribute_history(security, timeperiod, '1d', ['high'])['high'].max()
    
    return max_high
