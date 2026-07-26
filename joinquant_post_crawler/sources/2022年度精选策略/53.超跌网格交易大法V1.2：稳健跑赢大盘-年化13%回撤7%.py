# 克隆自聚宽文章：https://www.joinquant.com/post/36039
# 标题：超跌网格交易大法V1.2：稳健跑赢大盘-年化13%回撤7%
# 作者：wwr

enable_profile()
from jqlib.technical_analysis import*
from jqdata import *
import time
import numpy as np
import copy
import datetime
import pandas as pd
from jqfactor import get_factor_values


#股票版本
origin_param_list_0 = [
         ('000063.XSHE',50000,5000,1080,0.95,1.1,1.3)
        ,('601088.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('601111.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('510050.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('600104.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('002415.XSHE',50000,5000,1080,0.95,1.1,1.3)
        ,('601166.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('600547.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('513100.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('601318.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('600900.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('601688.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('600737.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('002714.XSHE',50000,5000,1080,0.95,1.1,1.3)
        ,('600887.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('000651.XSHE',50000,5000,1080,0.95,1.1,1.3)
        ,('600276.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('512660.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('000002.XSHE',50000,5000,1080,0.95,1.1,1.3)
        ,('600150.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('601857.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('601600.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('600104.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('601800.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('600259.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('600030.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('000723.XSHE',50000,5000,1080,0.95,1.1,1.3)
        ,('000977.XSHE',50000,5000,1080,0.95,1.1,1.3)
        ,('002511.XSHE',50000,5000,1080,0.95,1.1,1.3)
        ,('002025.XSHE',50000,5000,1080,0.95,1.1,1.3)
        #,('002190.XSHE',50000,5000,1080,0.95,1.1,1.3)
        ,('600021.XSHG',50000,5000,1080,0.95,1.1,1.3)
        ,('159915.XSHE',50000,5000,1080,0.95,1.1,1.3)
        ,('000858.XSHE',50000,5000,1080,0.95,1.1,1.3)
        ,('603288.XSHG',50000,5000,1080,0.95,1.1,1.3)
    ]


g.buy_dict = {} #买的价格和[数量--时间,sell price],以及要卖的价格得是多少(取最近6个月最高价和当前价*5%的最高者)
#g.sell_dict = {} #卖的价格和[数量--时间]
g.last_buy_price = {}
g.last_sell_price = {}
g.last_opt_price = {}
g.traceDisaster = {}
g.origin_param_list = {}
g.origin_param_list_all = {}
MAX_HOLD = 10
MAX_HOLD_DAYS = 30
MAX_HOLD_DAYS_LAST = 360

def KDJ_condition(context,stock):
    g.KDJ_J=0
    cur_date=context.previous_date.strftime('%Y-%m-%d')
    K1,D1,J1 = KDJ(stock,check_date=cur_date,N =9, M1=3, M2=3)
    KDJ_J=J1[stock]
    return KDJ_J
    
def choose_stocks(context):
    #半年运行一次
    year = context.current_dt.year
    month = context.current_dt.month
    day = context.current_dt.day
    if month%3 != 1:
        return
        
    g.origin_param_list = {}
    
    tmp = []
    max_num_candidate = 100
    for et in origin_param_list_0:
        tmp.append(et[0])
        stock = et[0]
        days = MAX_HOLD_DAYS
        sell_grid = 1.0 #额外的动量因子
        g.origin_param_list[stock] = (et[0],et[1],et[2],days,et[4],et[5],et[6],sell_grid)
        g.origin_param_list_all[stock] = (et[0],et[1],et[2],days,et[4],et[5],et[6],sell_grid)
        
        max_num_candidate = max_num_candidate -1
        if max_num_candidate <= 0:
            break
    
    # #获取前一个交易日的日期
    # previous_day=context.previous_date
    # # 获取要操作行业的股票代码列表
    # g.security =get_all_securities(types=['stock'],date=previous_day).index.tolist()
    # #筛选上市日期为5年前的股票；
    # if previous_day.year>=2009:
    #     days=1800
    # else:
    #     days=365
    # stock_list=start_date_filter(watch_date=previous_day,security=g.security,days=days)
    # #剔除ST、停牌、退市的股票
    # stock_list0=get_ST_stock_out(security=stock_list,watch_date=previous_day).index.tolist()
    # #获取EBIT/EV最高的股票
    # data1=get_EBIT_EV(security=stock_list0,watch_date=previous_day)
    # stock_list1=data1.index.tolist()[0:200]
    # #获取股息5年最高的股票
    # data2=get_DP(security=stock_list1,watch_date=previous_day,days=1800)
    # stock_list2=data2.index.tolist()[0:100]
    # #获取最近一年股息率最高的股票
    # data3=get_DP(security=stock_list2,watch_date=previous_day,days=365)
    # stock_list3=data3.index.tolist()[0:50]
    # #获取F-score评分最高的股票
    # data4=get_F_socre_and_rank(security=stock_list3,watch_date=previous_day)
    # stock_list4=data4.index.tolist()[0:20]
    # for stock in stock_list4:
    #     g.origin_param_list[stock] = (stock,50000,5000,MAX_HOLD_DAYS,0.97,1.1,1.3,1.0)
    #     g.origin_param_list_all[stock] = (stock,50000,5000,MAX_HOLD_DAYS,0.97,1.1,1.3,1.0)
    
    # print('all candidates size:',len(g.origin_param_list_all))
  
def check_buy_point(context, stock):
    s_buy = False
    buy_level = 0 #0,不买；买入的力度
    if get_current_data()[stock].is_st:
        return 0
        
    close_data = attribute_history(stock, 90, '1d', ['close', 'high'])
    closes = close_data['close'].values
    high = max(closes)
    if high > 0:
        if KDJ_condition(context,stock) < 0:
            s_buy = True
            buy_level = 1.0
            
        
    # close_data = attribute_history(stock, 90, '1d', ['close', 'high'])
    # closes = close_data['close'].values
    # high = max(closes)
    # low = min(closes)
    # current_price = get_current_data()[stock].last_price
    # #print('check:'+stock,high,low,current_price)
    
    # #取300的涨跌情况，看是否超跌了
    # close_data = attribute_history('000300.XSHG', 90, '1d', ['close', 'high'])
    # closes = close_data['close'].values
    # high_300 = max(closes)
    # low_300 = min(closes)
    # current_price_300 = get_current_data()['000300.XSHG'].last_price
    
    # down_300_rate = (high_300-current_price_300)/high_300
    # down_stock_rate = (high-current_price)/high
    

    # #比hs300多跌了30%以上，并且根据300\stock的位置来判断买入的力度
    # if (down_stock_rate-down_300_rate) > 0.1: 
    #     s_buy = True
    #     buy_level = math.sqrt(down_stock_rate/0.3)
    #     if KDJ_condition(context,stock) < 0:
    #         buy_level = buy_level * 1.2
    #     if buy_level > 4:
    #         buy_level = 4
        
    
    #print('check:'+stock,high,low,current_price,down_300_rate,down_stock_rate)
    
    return buy_level
    
    
# def check_buy_point(context, stock):
#     s_buy = False
#     buy_level = 0
#     close_data = attribute_history(stock, 120, '1d', ['close', 'high'])
    
#     closes = close_data['close'].values
    
#     # 取得过去55天的平均价格
#     ma55_list = list(np.zeros(120))
#     for i in range(54, 120):
#         ma55_list[i] = closes[i-54:i+1].mean()
    
#     # 近40天内，共有<5天大于ma55，且近3天有大于ma55的
#     over_55_in_40_days = np.array(closes[-40:]) > np.array(ma55_list[-40:])
    
#     num_over_55_40_days = sum(over_55_in_40_days)
#     ever_upcross_ma55 = sum(over_55_in_40_days[:20])
#     nowadays_upcross_ma55 = sum(over_55_in_40_days[-3:])
#     yesterday_over_ma55 = over_55_in_40_days[-1]
    
#     current_price = get_current_data()[stock].last_price
#     current_ma55 = (np.sum(closes[-54:]) + current_price)/55
    
#     now_over_ma55 = current_price > current_ma55
    
#     ten_days_lowest = min(closes[-10:]) == min(closes[-60:])
    
    
#     if 1 <= ever_upcross_ma55 <= 3 and\
#         nowadays_upcross_ma55 >= 1 and\
#         now_over_ma55 and\
#         ten_days_lowest:
#         s_buy = True
#         buy_level = 2
    
#     return buy_level

def initialize(context):
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    
    log.set_level('order', 'warning')

    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    # 为股票设定滑点为百分比滑点
    set_slippage(PriceRelatedSlippage(0.002),type='stock')
    
    set_benchmark('000300.XSHG')#origin_param_list_0[0][0])
    
    run_monthly(choose_stocks, monthday=1, time='9:00')
    #reset_stocks(context)
    #run_daily(dolsd, time='9:05', reference_security='000300.XSHG')
    #run_daily(dolsd1, time='9:35', reference_security='000300.XSHG')
    #run_daily(dolsd2, time='10:00', reference_security='000300.XSHG')
    #run_daily(dolsd1, time='10:30', reference_security='000300.XSHG')
    #run_daily(dolsd1, time='11:00', reference_security='000300.XSHG')
    #run_daily(dolsd1, time='13:00', reference_security='000300.XSHG')
    #run_daily(dolsd1, time='14:00', reference_security='000300.XSHG')
    run_daily(dolsd2, time='14:50')

def dolsd(context):
    buy(context)
    cover(context)
    sell(context)
    
def dolsd1(context):
    reset(context)
    cover(context)
    sell(context)

def dolsd2(context):
    reset(context)
    buy(context)
    cover(context)
    sell(context)
    
# def handle_data(context, data):
#     dolsd2(context)


def reset(context):
    
    #如果已经走完一个轮回周期，则重置
    origin_param_list = g.origin_param_list_all.values()
    hold_stocks = context.portfolio.positions.keys()
    finish_stocks = []
    for origin_param in origin_param_list:
        stock = origin_param[0]
        
        #if (stock in g.last_opt_price) and context.portfolio.positions[stock].total_amount <= 0:
        if  (stock in g.last_opt_price) and (stock not in hold_stocks):
            log.warning("Great! finish one turn:%s", stock)
            g.last_opt_price.pop(stock)
            g.buy_dict.pop(stock)
            
            #重置相关参数
            finish_stocks.append(stock)
            
    #反向检验
    for stock in hold_stocks:
       if (stock not in  g.last_opt_price) or len(g.last_opt_price[stock]) <= 0 or (stock not in g.buy_dict) or len(g.buy_dict[stock]) <= 0:
            log.warning("Not Great! finish one turn:%s", stock)
            try:
                g.last_opt_price.pop(stock)
            except:
                print('exception1:'+stock)
            
            try:
                g.buy_dict.pop(stock)
            except:
                print('exception2:'+stock)
            
            order_target_value(stock, 0)
            #重置相关参数
            finish_stocks.append(stock)
            
    #重置相关参数
    for et in origin_param_list_0:
        if et[0] in finish_stocks:
            days = MAX_HOLD_DAYS
            sell_grid = 1.0 #额外的动量因子
            g.origin_param_list[stock] = (et[0],et[1],et[2],days,et[4],et[5],et[6],sell_grid)
            g.origin_param_list_all[stock] = (et[0],et[1],et[2],days,et[4],et[5],et[6],sell_grid)


def buy(context):
    year = context.current_dt.year
    month = context.current_dt.month
    day = context.current_dt.day
    str_t = '%s-%s-%s' %(year,month,day)
    
    #最多同时持股10只
    hold_stocks_num = len(context.portfolio.positions.keys())
    if hold_stocks_num >= MAX_HOLD:
        return
    
    hold_stocks = context.portfolio.positions.keys()
    
    current_data = get_current_data()
    # 获取总账户的持仓价值
    total_value = context.portfolio.positions_value + context.portfolio.available_cash
    
    buy_stocks_now = 0
    origin_param_list = g.origin_param_list.values()
    #print('buy:',origin_param_list)
    for origin_param in origin_param_list:
        if (buy_stocks_now + hold_stocks_num) > MAX_HOLD:
            #log.warning('reject because buy_stocks_now > 10')
            break
        
        #eg:'510050.XSHG',50000,15000,1080,0.97,1.1,1.3
        stock = origin_param[0]
        min_value = origin_param[2]
        current_price = current_data[stock].last_price
        high_limit = current_data[stock].high_limit
        low_limit = current_data[stock].low_limit
        #涨停 or 跌停 or paused都停止
        if current_data[stock].paused or  current_price <= low_limit*1.01:
             continue
        #BUY--------------------------------------------------
        if (stock not in hold_stocks) :
            # #if KDJ_condition(context,stock)>0:
            # if check_buy_point(context,stock) == False:
            #     #print('filter first in:'+stock)
            #     continue
            buy_level =  check_buy_point(context,stock) 
            if buy_level <= 0:
                #print('filter first in:'+stock)
                continue
            
            log.warning("first in:%s,%s", stock, buy_level)
            buy_value = total_value*buy_level/(min(len(g.origin_param_list_all),MAX_HOLD)*4)
            
            cash = context.portfolio.available_cash
            if buy_value > cash:
                buy_value = cash
                
            num = int(buy_value/current_price)
            real_buy_value = (num - num%100 + 1) * current_price

            order_value(stock, buy_value)
            stock_dict = {}
            if stock in g.buy_dict:
                stock_dict = g.buy_dict[stock]
                
            sell_price = current_price * origin_param[6]
            #取最近3个月的高价当做残留标的高价
            close_data = get_bars(stock, count=90, unit='1d', fields=['close'])
            good_need_price = close_data['close'].max()
            good_sell_price = good_need_price * 0.97
            
            if current_price in stock_dict:
                stock_dict[current_price][str_t]=(real_buy_value,good_sell_price)
            else:
                stock_dict[current_price]={str_t:(real_buy_value,good_sell_price)}
            g.last_buy_price[stock] = {current_price:(str_t,real_buy_value)}
            g.last_opt_price[stock] = {current_price:(str_t,real_buy_value)}
            g.buy_dict[stock] = stock_dict

            #print('000 last-opt:',g.last_opt_price)
            buy_stocks_now = buy_stocks_now + 1

            
def cover(context):
    year = context.current_dt.year
    month = context.current_dt.month
    day = context.current_dt.day
    str_t = '%s-%s-%s' %(year,month,day)
    current_data = get_current_data() 
    # 获取总账户的持仓价值
    total_value = context.portfolio.positions_value + context.portfolio.available_cash
    #print(str_t)
    hold_stocks = context.portfolio.positions.keys()

    for stock in hold_stocks:
        #eg:'510050.XSHG',50000,15000,1080,0.97,1.1,1.3
        origin_param = g.origin_param_list_all[stock]
        stock = origin_param[0]
        min_value = origin_param[2]
        current_price = current_data[stock].last_price
        if current_price <= 0:
            log.warning('Error: price=0'+stock)
            continue
        high_limit = current_data[stock].high_limit
        low_limit = current_data[stock].low_limit
        #涨停 or 跌停 or paused都停止
        if current_data[stock].paused:
             continue
         
        if stock not in g.last_opt_price:
            continue

        last_price = list(g.last_opt_price[stock].keys())[0]
        last_cash = list(g.last_opt_price[stock].values())[0][1]
        # 取得当前的现金， 指数提高买入资金
        cash = context.portfolio.available_cash
        buy_value = 100*current_price
        
        #单个股票占比不能超过30%
        space=context.portfolio.positions[stock].total_amount
        holdcost=context.portfolio.positions[stock].avg_cost
        if space*holdcost > total_value* (3/min(MAX_HOLD,len(g.origin_param_list_all))):
            log.warning('Ignore: over 25% '+stock)
            continue
            
        ##连续下跌行清下，调大买入网格，调低卖出网格，加大MAX天观察期
        cover_grid = origin_param[4]
        sell_grid = origin_param[7]
        max_days = origin_param[3]
        if last_cash < 0:#上次是卖出
            last_cash = -last_cash
            buy_value = last_cash * 1.0
            #上涨小网格
            cover_grid = cover_grid*1.01 if cover_grid<0.98 else 0.98
            #sell_grid = sell_grid*0.99 if sell_grid>1.0 else 1.0
        else: #连续下跌
            buy_value = last_cash * 1.2 #指数提高买入资金
            #下跌大网格
            cover_grid = cover_grid*0.99 if cover_grid>0.93 else 0.93
            #sell_grid = sell_grid*0.99 if sell_grid>1.0 else 1.0
            #max_days = max_days + 5

        predict_cover_price = last_price * cover_grid
        #eg: ('601111.XSHG',50000,50000,1080,0.97,1.1)
        if current_price < predict_cover_price:
            # 如果比最近一次操作的低才买入,还是比卖的低就可以买入
            last_buy_price = list(g.last_buy_price[stock].keys())[0]
            last_buy_cash = list(g.last_buy_price[stock].values())[0][1]
            last_sell_price = list(g.last_buy_price[stock].keys())[0]
            last_sell_cash = list(g.last_buy_price[stock].values())[0][1]
            
            if buy_value < min_value:
                buy_value = min_value
            max_value = min(total_value/(min(MAX_HOLD,len(g.origin_param_list_all))*4),min_value * 10)
            if buy_value > max_value:
                buy_value = max_value
            if buy_value < 100*current_price:
                buy_value = 101*current_price
            if buy_value > cash: #钱不够
               continue
            # 记录这次买入
            #log.info("价格更低了, 买入 %s,%f,%f" % (stock,last_price,current_price))
            num = int(buy_value/current_price)
            real_buy_value = (num - num%100) * current_price

            order_value(stock, buy_value)
            stock_dict = {}
            if stock in g.buy_dict:
                stock_dict = g.buy_dict[stock]
            sell_price = current_price * origin_param[5]
            if current_price in stock_dict:
                stock_dict[current_price][str_t] = (real_buy_value,sell_price)
            else:
                stock_dict[current_price] = {str_t:(real_buy_value,sell_price)}
            g.last_buy_price[stock] = {current_price:(str_t,real_buy_value)}
            g.last_opt_price[stock] = {current_price:(str_t,real_buy_value)}
            g.buy_dict[stock] = stock_dict
            
            #调整网格
            origin_param = (origin_param[0],origin_param[1],origin_param[2],max_days,cover_grid,origin_param[5],origin_param[6],sell_grid)
            g.origin_param_list_all[stock] = origin_param
            g.origin_param_list[stock] = origin_param
            
            continue

def sell(context):
    year = context.current_dt.year
    month = context.current_dt.month
    day = context.current_dt.day
    str_t = '%s-%s-%s' %(year,month,day)
    date_now_t = datetime.date(year,month,day)
    
    
    current_data = get_current_data() 
    hold_stocks = context.portfolio.positions.keys()
    for stock in hold_stocks:
        #eg:'510050.XSHG',50000,15000,1080,0.97,1.1,1.3
        origin_param = g.origin_param_list_all[stock]
        stock = origin_param[0]
        min_value = origin_param[2]
        current_price = current_data[stock].last_price
        if current_price <= 0:
            log.warning('Error: price=0'+stock)
            continue
        high_limit = current_data[stock].high_limit
        low_limit = current_data[stock].low_limit
        #涨停 or 跌停 or paused都停止
        if current_data[stock].paused or current_price <= low_limit*1.01:
             continue
        
        if stock not in g.last_opt_price:
            continue
    
        #重整网格大小，连续买入行情下：调大买入网格，调低卖出网格
        cover_grid = origin_param[4]
        sell_grid =  origin_param[7]
        max_hold_days = origin_param[3]
        last_cash = list(g.last_opt_price[stock].values())[0][1]
        last_price = list(g.last_opt_price[stock].values())[0][0]

        if last_cash < 0:#上次是卖出
            #连续上涨买入小网格、卖出大网格
            sell_grid = sell_grid*1.01 if sell_grid<1.2 else 1.2
            #max_hold_days = max_hold_days + 5
            #cover_grid = cover_grid*1.01 if cover_grid<0.98 else 0.98
        else:
             #sell_grid = sell_grid*0.99 if sell_grid>1.0 else 1.0 
             sell_grid = 1.0
        
        #SELL--------------------------------------------------------
        # 如果当前价格比买入的高就可以卖;遍历buy_dict，卖出所有可以卖的股票
        stock_dict = g.buy_dict[stock]
        tmp_dict = copy.deepcopy(stock_dict)
        change = 0
        delay_day = 0
        sum_sell_value = 0
        #取最近3个月的高价当做残留标的高价
        close_data = get_bars(stock, count=90, unit='1d', fields=['close'])
        good_need_price = close_data['close'].max()
        for price in stock_dict:
            t_num_dict = stock_dict[price]
            if len(t_num_dict) <= 0:
                tmp_dict.pop(price)
                continue
            if price <= 0:
                print('price=0:'+stock)
                print('wrong_buy_dict:',stock_dict)
                continue
            
            max_hold_days = origin_param[3]

            for pre_t in t_num_dict:
                last_buy_value = stock_dict[price][pre_t][0]
                need_price = stock_dict[price][pre_t][1]
                num = int(last_buy_value/price)
                cap = num*current_price
                num = num - num%100
                tmp = pre_t.split('-')
                date_pre_t = datetime.date(int(tmp[0]),int(tmp[1]),int(tmp[2]))
                days_ago_t = date_now_t - datetime.timedelta(days = max_hold_days)
                
                #控制风险，如果交易超过了3个月，就卖出
                if days_ago_t > date_pre_t:
                    if current_price > price*sell_grid or max_hold_days > MAX_HOLD_DAYS_LAST:
                        change = change + 1
                        sum_sell_value = sum_sell_value + cap
                        tmp_dict[price].pop(pre_t)
                    else:
                        delay_day = delay_day + 1
                    #log.warning('sell 3 month ago:%s,%s',stock,pre_t)
                    continue
                
                #超过卖的时间可以卖了
                if str_t>pre_t and current_price >= need_price*sell_grid:
                    #print('current_price:',current_price,'need_price:',need_price,'t',str_t,'pre_t',pre_t)
                    change = change + 1
                    sell_num = int(num*0.5+50)
                    sell_num = sell_num - sell_num%100
                    if (num-sell_num)*current_price < min_value:
                        sell_num = num
                    
                    sum_sell_value = sum_sell_value + sell_num * current_price
                            
                    if sell_num < num:
                        if need_price >= good_need_price*0.97:
                            need_price = need_price * 1.05
                        else:
                            need_price = good_need_price*0.97

                        tmp_dict[price][pre_t]=((num-sell_num)*current_price,need_price)
                    else:
                        tmp_dict[price].pop(pre_t)
                        #print('pop:',pre_t)
                        
                
                
            
        if change > 0:    
            #print('pre_buy_dict:',stock_dict)
            #print('now:',tmp_dict)
            order_value(stock,-1*sum_sell_value)
            
            g.last_sell_price[stock] = {current_price:(str_t,sum_sell_value)}
            g.last_opt_price[stock] = {current_price:(str_t,-sum_sell_value)}
            
            if delay_day >= 1:
                max_hold_days = max_hold_days + 7
            
            #重整网格
            origin_param = (origin_param[0],origin_param[1],origin_param[2],max_hold_days,cover_grid,origin_param[5],origin_param[6],sell_grid)
            g.origin_param_list_all[stock] = origin_param
            g.origin_param_list[stock] = origin_param
            
            g.buy_dict[stock] = tmp_dict
        


# 定义获取上市公司首发上市的日期
def start_date_filter(watch_date,security,days):

    #获取上市日期、证券简称；
    q0=query(finance.STK_LIST.code,finance.STK_LIST.name,finance.STK_LIST.start_date).filter(\
    finance.STK_LIST.code.in_(security))
    df_start_date=finance.run_query(q0)
    
    
    #筛选条件：days以前上市的；
    days_ago=watch_date-datetime.timedelta(days=days)
    df_start_date1=df_start_date[df_start_date['start_date']<days_ago]

    df_start_date2=df_start_date1.set_index('code')
    df_start_list=df_start_date2.index.tolist()
    
    return df_start_list


#定义一个函数，这个函数可以剔除ST类股票
def get_ST_stock_out(security,watch_date):
    data1=get_extras('is_st', security_list=security, start_date=watch_date, end_date=watch_date, df=True)
    data2=data1.T
    data2.columns=['ST']
    data3=data2[data2['ST']==False]
    return data3



def get_EBIT_EV(security,watch_date):

    #获取相关数据并形成EBIT相关数据
    
    if len(security)>=2000:
        EBIT_data1=get_history_fundamentals(security=security[int(len(security)*0):int(len(security)*0.33)], \
                                            fields=[indicator.adjusted_profit,\
                                                                      income.income_tax_expense,\
                                                           income.financial_expense], 
                                 watch_date=watch_date, count=4, interval='1q', stat_by_year=False)
        
        EBIT_data2=get_history_fundamentals(security=security[int(len(security)*0.33):int(len(security)*0.66)], \
                                            fields=[indicator.adjusted_profit,\
                                                                      income.income_tax_expense,\
                                                           income.financial_expense], 
                                 watch_date=watch_date, count=4, interval='1q', stat_by_year=False)
        
        EBIT_data3=get_history_fundamentals(security=security[int(len(security)*0.66):int(len(security)*1)], \
                                            fields=[indicator.adjusted_profit,\
                                                                      income.income_tax_expense,\
                                                           income.financial_expense], 
                                 watch_date=watch_date, count=4, interval='1q', stat_by_year=False)
        
        EBIT_data=pd.concat([EBIT_data1,EBIT_data2,EBIT_data3],axis=0,sort=True)
        
    
    else:
        EBIT_data=get_history_fundamentals(security=security, fields=[indicator.adjusted_profit,\
                                                                      income.income_tax_expense,\
                                                           income.financial_expense], 
                                 watch_date=watch_date, count=4, interval='1q', stat_by_year=False)
        
        
        
        
    # EBIT_data.fillna(0,inplace=True)
    EBIT_data=EBIT_data.groupby('code').sum()
    EBIT_data['EBIT']=EBIT_data['adjusted_profit']+EBIT_data['income_tax_expense']+EBIT_data['financial_expense']
    
    #获取市值以及负债相关数据
    factor_data = get_factor_values(securities=security, factors=['market_cap',\
                                                                  'financial_liability','financial_assets'], \
                                    end_date=watch_date,count=1)

    df_factor_data=pd.concat([factor_data['market_cap'].T,factor_data['financial_liability'].\
                              T,factor_data['financial_assets'].T],axis=1)

    col1=['market_cap','financial_liability','financial_assets']
    df_factor_data.columns=col1

    #计算EBIT/EV
    df_factor_data['EV']=df_factor_data['market_cap']+df_factor_data['financial_liability']\
                         -df_factor_data['financial_assets']
    EBIT_EV=EBIT_data['EBIT']/df_factor_data['EV']
    
     #以EBIT/EV进行排名
    EBIT_EV=EBIT_EV.sort_values(ascending=False)

    return EBIT_EV



def get_DP(security,watch_date,days):
    
    # 获取股息数据
    one_year_ago=watch_date-datetime.timedelta(days=days)
    
    q1=query(finance.STK_XR_XD.a_registration_date,finance.STK_XR_XD.bonus_amount_rmb,\
            finance.STK_XR_XD.code\
           ).filter(finance.STK_XR_XD.a_registration_date>= one_year_ago,\
                    finance.STK_XR_XD.a_registration_date<=watch_date,\
                    finance.STK_XR_XD.code.in_(security[0:int(len(security)*0.3)]))
    q2=query(finance.STK_XR_XD.a_registration_date,finance.STK_XR_XD.bonus_amount_rmb,\
            finance.STK_XR_XD.code\
           ).filter(finance.STK_XR_XD.a_registration_date>= one_year_ago,\
                    finance.STK_XR_XD.a_registration_date<=watch_date,\
                    finance.STK_XR_XD.code.in_(security[int(len(security)*0.3):int(len(security)*0.6)]))
    q3=query(finance.STK_XR_XD.a_registration_date,finance.STK_XR_XD.bonus_amount_rmb,\
            finance.STK_XR_XD.code\
           ).filter(finance.STK_XR_XD.a_registration_date>= one_year_ago,\
                    finance.STK_XR_XD.a_registration_date<=watch_date,\
                    finance.STK_XR_XD.code.in_(security[int(len(security)*0.6):]))
    
    
    df_data1=finance.run_query(q1)
    df_data2=finance.run_query(q2)
    df_data3=finance.run_query(q3)
    df_data=pd.concat([df_data1,df_data2,df_data3],axis=0,sort=False)
    df_data.fillna(0,inplace=True)
    
    df_data=df_data.set_index('code')
    df_data=df_data.groupby('code').sum()
    
    #获取市值相关数据
    q01=query(valuation.code,valuation.market_cap).filter(valuation.code.in_(security))
    BP_data=get_fundamentals(q01,date=watch_date)
    BP_data=BP_data.set_index('code')
    
    #合并数据
    data=pd.concat([df_data,BP_data],axis=1,sort=False)
    data.fillna(0,inplace=True)
    data['股息率']=(data['bonus_amount_rmb']/10000)/data['market_cap']
    data1=data.sort_values(by=['股息率'],ascending=False)
    
    return data1
    


def get_F_socre_and_rank(security,watch_date):
    
    one_year_ago = watch_date - datetime.timedelta(days=365)
    
    h = get_history_fundamentals(security,
                             [indicator.adjusted_profit,
                              balance.total_current_assets,
                              balance.total_assets,
                              balance.total_current_liability,
                              balance.total_non_current_liability,
                              cash_flow.net_operate_cash_flow,
                              income.operating_revenue,
                              income.operating_cost,
                              ],
                             watch_date=watch_date, count=5)  # 连续的5个季度
    
    #去除历史数据不足5的情况
    not_enough_data = h.groupby('code').size() <  5
    not_enough_data = not_enough_data[not_enough_data]
    h = h[~h['code'].isin(not_enough_data.index)]
    
    def ttm_sum(x):
        return x.iloc[1:].sum()

    def ttm_avg(x):
        return x.iloc[1:].mean()

    def pre_ttm_sum(x):
        return x.iloc[:-1].sum()

    def pre_ttm_avg(x):
        return x.iloc[:-1].mean()

    def val_1(x):
        return x.iloc[-1]

    def val_2(x):
        return x.iloc[-2]
    
    
    # 扣非利润
    adjusted_profit_ttm = h.groupby('code')['adjusted_profit'].apply(ttm_sum)
    adjusted_profit_ttm_pre = h.groupby('code')['adjusted_profit'].apply(pre_ttm_sum)

    # 总资产平均
    total_assets_avg = h.groupby('code')['total_assets'].apply(ttm_avg)
    total_assets_avg_pre = h.groupby('code')['total_assets'].apply(pre_ttm_avg)

    # 经营活动产生的现金流量净额
    net_operate_cash_flow_ttm = h.groupby('code')['net_operate_cash_flow'].apply(ttm_sum)

    # 长期负债率: 长期负债/总资产
    long_term_debt_ratio = h.groupby('code')['total_non_current_liability'].apply(val_1) / h.groupby('code')['total_assets'].apply(val_1)
    long_term_debt_ratio_pre = h.groupby('code')['total_non_current_liability'].apply(val_2) / h.groupby('code')['total_assets'].apply(val_2)

    # 流动比率：流动资产/流动负债
    current_ratio = h.groupby('code')['total_current_assets'].apply(val_1) / h.groupby('code')['total_current_liability'].apply(val_1)
    current_ratio_pre = h.groupby('code')['total_current_assets'].apply(val_2) / h.groupby('code')['total_current_liability'].apply(val_2)

    # 营业收入
    operating_revenue_ttm = h.groupby('code')['operating_revenue'].apply(ttm_sum)
    operating_revenue_ttm_pre = h.groupby('code')['operating_revenue'].apply(pre_ttm_sum)

    # 营业成本
    operating_cost_ttm = h.groupby('code')['operating_cost'].apply(ttm_sum)
    operating_cost_ttm_pre = h.groupby('code')['operating_cost'].apply(pre_ttm_sum)
    
    
    # 1. ROA 资产收益率
    roa = adjusted_profit_ttm / total_assets_avg
    roa_pre = adjusted_profit_ttm_pre / total_assets_avg_pre

    # 2. OCFOA 经营活动产生的现金流量净额/总资产
    ocfoa = net_operate_cash_flow_ttm / total_assets_avg

    # 3. ROA_CHG 资产收益率变化
    roa_chg = roa - roa_pre

    # 4. OCFOA_ROA 应计收益率: 经营活动产生的现金流量净额/总资产 -资产收益率
    ocfoa_roa = ocfoa - roa

    # 5. LTDR_CHG 长期负债率变化 (长期负债率=长期负债/总资产)
    ltdr_chg = long_term_debt_ratio - long_term_debt_ratio_pre

    # 6. CR_CHG 流动比率变化 (流动比率=流动资产/流动负债)
    cr_chg = current_ratio - current_ratio_pre

    # 8. GPM_CHG 毛利率变化 (毛利率=1-营业成本/营业收入)
    gpm_chg = operating_cost_ttm_pre/operating_revenue_ttm_pre - operating_cost_ttm/operating_revenue_ttm

    # 9. TAT_CHG 资产周转率变化(资产周转率=营业收入/总资产)
    tat_chg = operating_revenue_ttm/total_assets_avg - operating_revenue_ttm_pre/total_assets_avg_pre
    
    
    # 7. 股票是否增发
    spo_list = list(set(finance.run_query(
        query(
            finance.STK_CAPITAL_CHANGE.code
        ).filter(
            finance.STK_CAPITAL_CHANGE.code.in_(security),
            finance.STK_CAPITAL_CHANGE.pub_date.between(one_year_ago, watch_date),
            finance.STK_CAPITAL_CHANGE.change_reason_id == 306004)
    )['code']))

    spo_score = pd.Series(True, index = security)
    
    if spo_list:
        spo_score[spo_list] = False
        
        
        
    # 计算得分total
    df_scores = pd.DataFrame(index=security)
    # 1
    df_scores['roa'] = roa>0 
    # 2
    df_scores['ocfoa'] = ocfoa>0
    # 3
    df_scores['roa_chg'] = roa_chg>0
    # 4
    df_scores['ocfoa_roa'] = ocfoa_roa>0
    # 5
    df_scores['ltdr_chg'] = ltdr_chg<=0
    # 6
    df_scores['cr_chg'] = cr_chg>0
    # 7
    df_scores['spo'] = spo_score
    # 8
    df_scores['gpm_chg'] = gpm_chg>0
    # 9
    df_scores['tat_chg'] = tat_chg>0

    # 合计
    df_scores = df_scores.dropna()
    
    for u in df_scores.columns:
        if df_scores[u].dtype==bool:
            df_scores[u]=df_scores[u].astype('int')
        
    df_scores['total'] = df_scores['roa'] + df_scores['ocfoa'] + df_scores['roa_chg'] + \
        df_scores['ocfoa_roa'] + df_scores['ltdr_chg'] + df_scores['cr_chg'] + \
        df_scores['spo'] + df_scores['gpm_chg'] + df_scores['tat_chg']

    df_scores=df_scores.sort_values(by='total',ascending=False)   
        
    return df_scores



