# 克隆自聚宽文章：https://www.joinquant.com/post/33647
# 标题：MACD多周期共振，精准打击！
# 作者：海枫

# 导入 technical_analysis 库
from jqlib.technical_analysis import *
from jqdata import *
import talib as tl
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import datetime
import heapq 

def initialize(context):
    set_backtest() #股票相关设定
    # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')    
    # 每分钟运行
    run_daily(every_bar,time='every_bar', reference_security='000300.XSHG')
    # 开盘运行
    #run_daily(market_open, time='open', reference_security='000300.XSHG')
    # 每30m运行
    #run_daily(buy_every30m, time='9:30', reference_security='000300.XSHG')
    #run_daily(buy_every30m, time='10:00', reference_security='000300.XSHG')
    #run_daily(buy_every30m, time='10:30', reference_security='000300.XSHG')
    #run_daily(buy_every30m, time='11:00', reference_security='000300.XSHG')
    #run_daily(buy_every30m, time='11:30', reference_security='000300.XSHG')
    #run_daily(buy_every30m, time='13:00', reference_security='000300.XSHG')
    #run_daily(buy_every30m, time='13:30', reference_security='000300.XSHG')
    #run_daily(buy_every30m, time='14:00', reference_security='000300.XSHG')
    run_daily(buy_every30m, time='14:00', reference_security='000300.XSHG')
    # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')
### 股票相关设定 ###
def set_backtest():
    g.t=0 #运行天数
    g.s=[] #股票池
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_slippage(FixedSlippage(0))
    set_order_cost(OrderCost(close_tax=0.001,
        open_commission=0.0003, close_commission=0.0003,
        min_commission=5), type='stock')
## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))#获取当前日期
    g.Now_date = context.current_dt.strftime('%Y-%m-%d')
    print("今天是：%s" %(g.Now_date))
    # 股票筛选
    filterlist(context)
    #将所有股票列表转换成数组
    g.stocks = g.all_stocks_list
    get_D()#股票池
def get_D():
    if len(g.stocks)!=0:
        for i in g.stocks:
            macd_day = get_macd(i, 200, g.Now_date, '1w')
            value = is_second_low_gold_cross(macd_day)
            if value:
                g.s.append(i)
        for l in g.s:
            macd_day = get_macd(l, 200, g.Now_date, '1w')
            gs_dif=macd_day[0][-2:]
            gs_dea=macd_day[1][-2:]
            if gs_dif[-1]>gs_dea[-1] and gs_dif[-2]<gs_dea[-2]:
                g.s.remove(l)
    print("股票池：%s" %(g.s))
 #从股票池中选出当天三个要买   
def c_s(context):
    g.buys=[]
    g.buy_d=[]
    g.buy=[]
    if len(g.s)!=0:
        for i in g.s:
            macd_day = get_macd(i, 200, g.Now_date, '1w')
            day_dea=macd_day[1][-1:]
            day_macd=macd_day[2][-1:]
            macd_30m = get_macd(i, 200, g.Now_date, '60m')
            value = is_gold_cross(macd_30m)
            if day_macd[-1]>day_dea[-1] and value:
                g.buys.append(i)
                g.buy_d.append(day_dea[-1])
        lis=g.buy_d    
        max_number = heapq.nlargest(3, lis) 
        max_index = [] 
        for t in max_number: 
            index = lis.index(t) 
            max_index.append(index) 
            lis[index] = 0 
        #print(max_number) 
        #print(max_index)
        for b in max_index:
            g.buy.append(g.buys[b])
        #print("当天要买：%s" %(g.buy))
        buy_stock(context)
#def market_open(context):
#    market_sell(context)
def buy_every30m(context):
    c_s(context)
def every_bar(context):
    open_every_bar(context)

#卖出股票
def market_sell(context):
     #获取持仓列表
    init_sl = context.portfolio.positions.keys()
    if len(init_sl)!=0:
        for i in init_sl:
            h = attribute_history(i, 3, '1d', ('open','close', 'volume'))
            h1=h['close'][-1]
            h2=h['close'][-2]
            h3=h['close'][-3]
            hv1=h['volume'][-1]
            hv2=h['volume'][-2]
            ho1=h['open'][-1]
            ho2=h['open'][-2]
            ho3=h['open'][-3]
            if h1<h2 or h1<ho1 or hv1>1.5*hv2:
                order_target_value(i,0)
            print('卖出：%s' % (i))

# 买入股票
def buy_stock(context):
    if g.buy and len(g.buy)!=0:
        # 取得当前的现金
        cash = context.portfolio.available_cash
        N=len(g.buy) 
        for i in g.buy:
            order_value(i,cash/N)
            g.s.remove(i)
            print('买入：%s' % (i))
## 移动止盈   
def open_every_bar(context):
    #print("Day:%s" % (g.t))
    # 获取持仓列表
    init_sl = context.portfolio.positions.keys()
    if len(init_sl)!=0:
        for i in init_sl:
            # 获得股票持仓成本
            cost=context.portfolio.positions[i].avg_cost
            # 获得股票现价
            price=context.portfolio.positions[i].price
            # 计算收益率
            ret=price/cost-1
            if ret>=0.1:
                order_target(i,0)
                log.info('触发止盈:'+i +str(context.current_dt.time()))  

#股票筛选                
def filterlist(context):
    g.all_stocks_list=[]
    g.all_stocks_list=get_all_stocks()
    # 过滤停盘
    g.all_stocks_list=paused_filter(g.all_stocks_list)
    # 过滤退市
    g.all_stocks_list=delisted_filter(g.all_stocks_list)
    # 过滤ST
    g.all_stocks_list=st_filter(g.all_stocks_list)
    # 过滤科创板
    g.all_stocks_list=kc_filter(g.all_stocks_list)
    # 过滤上市不足60天的新股
    current_date = context.current_dt.date()
    g.all_stocks_list = [stock for stock in g.all_stocks_list if (current_date - get_security_info(stock).start_date).days > 60]

## 取所有A股
def get_all_stocks():
    df=get_fundamentals(query(valuation.code))
    return list(df['code'])

## 过滤停牌股票
def paused_filter(security_list):
    current_data = get_current_data()
    security_list = [stock for stock in security_list if not current_data[stock].paused]
    # 返回结果
    return security_list

## 过滤退市股票
def delisted_filter(security_list):
    current_data = get_current_data()
    security_list = [stock for stock in security_list if not '退' in current_data[stock].name]
    # 返回结果
    return security_list

## 过滤ST股票
def st_filter(security_list):
    current_data = get_current_data()
    security_list = [stock for stock in security_list if not current_data[stock].is_st]
    # 返回结果
    return security_list
# 剔除出科创板的股票
def kc_filter(security_list):
    current_data = get_current_data()
    security_list = [stock for stock in security_list if stock[0:3] != '688']
    # 返回结果
    return security_list    

## 收盘后运行    
def after_market_close(context):
    # 取得当前的现金
    cash = context.portfolio.available_cash
    # 获取持仓列表
    init_sl = context.portfolio.positions.keys()
    g.t+=1
    if g.t%10==0:
        g.D_Macd=[]
    print ("剩余资金：%s" % (cash))
    print ("当前持仓：%s" % (init_sl))
    print("运行天数：%s" % (g.t))
    
    

# MACD 公用函数###############################################
def MACD(close, fastperiod, slowperiod, signalperiod):
    macdDIFF, macdDEA, macd = tl.MACDEXT(close, fastperiod=fastperiod, fastmatype=1, slowperiod=slowperiod, slowmatype=1, signalperiod=signalperiod, signalmatype=1)
    macd = macd * 2
    return macdDIFF, macdDEA, macd 
# 查寻一个时间段内某标的的macd信息
def get_macd(stock, count, end_date, unit):
    data = get_bars(security=stock, count=count, unit=unit,
                        include_now=False, 
                        end_dt=end_date, fq_ref_date=True)
    close = data['close']
    open = data['open']
    high = data['high']
    low = data['low']

    return MACD(close, 12, 26, 9)

# 0上第一次死叉
def is_second_low_gold_cross(macd_list):
    macdDIFF, macdDEA, macd = macd_list
    
    cross_list = []
    # 判断当前是否发生金叉，并且位置在0轴之下
    if macdDIFF[-2] > macdDEA[-2] and macdDIFF[-1] < macdDEA[-1] and macd[-1]>macdDEA[-1]:
        for i in range(4, len(macd)):
            if macd[i-3]<macd[i-2]<macd[i-1]<macd[i] and macdDIFF[i-1] < macdDEA[i-1] and macdDIFF[i] > macdDEA[i]:
                gold_cross = {'id':i,
                              'name':'gold_cross',
                              'dif':macdDIFF[i],
                              'dea':macdDEA[i]}
                cross_list.append(gold_cross)
                
            elif macd[i-3]>macd[i-2]>macd[i-1]>macd[i] and macdDIFF[i-1] > macdDEA[i-1] and macdDIFF[i] < macdDEA[i]:
                death_cross = {'id':i,
                              'name':'death_cross',
                              'dif':macdDIFF[i],
                              'dea':macdDEA[i]}
                cross_list.append(death_cross)

        df = pd.DataFrame(cross_list, columns=['id', 'name', 'dif', 'dea']).sort_values(by="id",ascending=False)
        index_list = []
        if len(df.index) > 4:
            index_list = df.index[0:4] 
        else:
            return False
        #result1 = df.loc[index_list[0]]['name']=='gold_cross' and df.loc[index_list[0]]['dif'] < 0
        result1 = df.loc[index_list[0]]['name']=='death_cross' and df.loc[index_list[0]]['dif'] < 0
        result2= df.loc[index_list[1]]['name']=='gold_cross' and df.loc[index_list[1]]['dif'] < 0
        result3 = df.loc[index_list[2]]['name']=='death_cross'             
        result4 = df.loc[index_list[0]]['dea']>df.loc[index_list[1]]['dea']    
       
        if result1 and result2 and result3 and result4:
            return True
        else:
            return False
    else:
        return False    
        
# 判断是否是0下二金叉
def is_gold_cross(macd_list):
    macdDIFF, macdDEA, macd = macd_list
    
    cross_list = []
    # 判断当前是否发生金叉，并且位置在0轴之下
    if macdDIFF[-2] < macdDEA[-2] and macdDIFF[-1] > macdDEA[-1] and macdDIFF[-1] < 0:
        for i in range(4, len(macd)):
            if macd[i-3]<macd[i-2]<macd[i-1]<macd[i] and macdDIFF[i-1] < macdDEA[i-1] and macdDIFF[i] > macdDEA[i]:
                gold_cross = {'id':i,
                              'name':'gold_cross',
                              'dif':macdDIFF[i],
                              'dea':macdDEA[i]}
                cross_list.append(gold_cross)
                
            elif macd[i-3]>macd[i-2]>macd[i-1]>macd[i] and macdDIFF[i-1] > macdDEA[i-1] and macdDIFF[i] < macdDEA[i]:
                death_cross = {'id':i,
                              'name':'death_cross',
                              'dif':macdDIFF[i],
                              'dea':macdDEA[i]}
                cross_list.append(death_cross)

        df = pd.DataFrame(cross_list, columns=['id', 'name', 'dif', 'dea']).sort_values(by="id",ascending=False)
        index_list = []
        if len(df.index) > 4:
            index_list = df.index[0:4] 
        else:
            return False
            
        result1 = df.loc[index_list[0]]['name']=='gold_cross' and df.loc[index_list[0]]['dif'] < 0
        result2 = df.loc[index_list[1]]['name']=='death_cross' and df.loc[index_list[1]]['dif'] < 0
        result3= df.loc[index_list[2]]['name']=='gold_cross' and df.loc[index_list[2]]['dif'] < 0
        result4 = df.loc[index_list[3]]['name']=='death_cross' and df.loc[index_list[3]]['dif'] > 0                                            
        result5 = df.loc[index_list[0]]['dea']>df.loc[index_list[2]]['dea']
        if result1 and result2 and result3 and result4 and result5:
            return True
        else:
            return False
    else:
        return False    
