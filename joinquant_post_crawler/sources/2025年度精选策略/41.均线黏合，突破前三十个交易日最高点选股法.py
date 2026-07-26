# 克隆自聚宽文章：https://www.joinquant.com/post/25698
# 标题：均线黏合，突破前三十个交易日最高点选股法
# 作者：fireflytxy

# 克隆自聚宽文章：https://www.joinquant.com/post/21474
# 标题：基于分析师深度研报的T+1策略-年化51%，回撤3.7%
# 作者：wsd518

# 导入函数库

from jqdata import *
import jqdata
import numpy as np
import pandas as pd
import datetime



def get_stocks_tobuy(context):
    
    date1= str(context.current_dt)[0:10]
    #print(date1)
    stock_list1 = get_index_stocks('000001.XSHG')+get_index_stocks('399106.XSHE')
    
    #stock_list1 = delisted_filter(stock_list1)
    stock_list1 = delisted_filter(stock_list1)
    stock_list1 = st_filter(stock_list1)
    
    df = get_fundamentals(query(
        valuation.code, valuation.market_cap,income.total_operating_revenue
    ).filter(
        valuation.circulating_market_cap > 20,
        valuation.pe_ratio > 0,
        valuation.code.in_(stock_list1)
    ).order_by(
        # 按市值降序排列
        valuation.market_cap.desc()
    ) )
    
    stock_list1 = df.code.tolist()
    
    
    close = get_price(stock_list1, end_date= date1, 
    frequency='daily', fields='close', count=250)['close']
    
    
    close_12days = get_price(stock_list1, end_date= date1, 
    frequency='daily', fields='close', count=12)['close'].iloc[-30:1,:]
    
    Open =  get_price(stock_list1, end_date= date1, 
    frequency='daily', fields='open', count=1)['open'].T
    Open.columns=['open']
    
    close13 = close.rolling(13).mean().iloc[-1,:].T
    close34 = close.rolling(34).mean().iloc[-1,:].T
    close55 = close.rolling(55).mean().iloc[-1,:].T

    close13_1 = close.rolling(13).mean().iloc[-10,:].T
    close34_1 = close.rolling(34).mean().iloc[-10,:].T
    close55_1 = close.rolling(55).mean().iloc[-10,:].T
    
    close13_2 = close.rolling(13).mean().iloc[-19,:].T
    close34_2 = close.rolling(34).mean().iloc[-19,:].T
    close55_2 = close.rolling(55).mean().iloc[-19,:].T
    
    #close1 = close.iloc[-3,:].T
    #close2 = close.iloc[-4,:].T

    ###55日线开始向上拐头
    #close55pre = close.rolling(55).mean().iloc[-10,:].T
    close250 = close.rolling(250).mean().iloc[-1,:].T
    
    
    highest = close_12days.max()
    lowest = close_12days.min()

    
    All = pd.concat([close.iloc[-1,:],Open,highest,lowest,close13,close34,close55,close250
    ,close13_1,close34_1,close55_1,close13_2,close34_2,close55_2],axis = 1)
    
    All.columns = ['close','open','highest','lowest','close13','close34','close55','close250',
    'close13_1','close34_1','close55_1','close13_2','close34_2','close55_2'
    ]
    #print(All.head() )
    stock_list = stock_list = All[ ( (All['highest']- All['lowest'])/All['close'] < 0.2 ) 
    & (All['close'] > All['highest'])  & (All['close13'] > All['close34']) &
    (All['close34'] > All['close55']) & (All['close'] >= All['open'])  
    & ( abs( ( All['close34_1'] - All['close13_1'])/All['close13_1'] ) <= 0.03 )
    & ( abs( ( All['close55_1'] - All['close34_1'])/All['close34_1'] ) <= 0.03 )
    & ( abs( ( All['close55_1'] - All['close13_1'])/All['close13_1'] ) <= 0.03 )
   
    & ( abs( ( All['close34_2'] - All['close13_2'])/All['close13_2'] ) <= 0.03 )
    & ( abs( ( All['close55_2'] - All['close34_2'])/All['close34_2'] ) <= 0.03 )
    & ( abs( ( All['close55_2'] - All['close13_2'])/All['close13_2'] ) <= 0.03 )
    ]
    df = [x for x in stock_list.index.tolist() if x not in g.previous_buylist.keys()]
    #print(stock_list)
    return df        
            


# 过滤退市
def delisted_filter(stock_list):
    current_data = get_current_data()
    stock_list = [stock for stock in stock_list if not '退' in current_data[stock].name]
    return stock_list

# 过滤ST
def st_filter(stock_list):
    current_data = get_current_data()
    stock_list = [stock for stock in stock_list if not current_data[stock].is_st]
    return stock_list
        

## 收盘后运行函数
def after_trading_end(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    
    #控制突破30日高点后只有第一次买入
    for stock in list(g.previous_buylist.keys()):
        if g.previous_buylist[stock] >=30:

            del g.previous_buylist[stock]
            
        else:
            g.previous_buylist[stock]+=1
    
    
    stock_list = get_stocks_tobuy(context) 
    to_buy = stock_list
    g.my_stock_today = to_buy
    if len(to_buy)>0:
        print(to_buy)
    
    temp = []
    for stock in context.portfolio.positions.keys():
        temp.append(stock)
        
    #print('type of temp',type(temp))
    #print(temp)
    
    
    
    if len(temp)>0:
        date1= str(context.current_dt)[0:10]
        
        close = get_price(temp , end_date= date1, 
        frequency='daily', fields='close', count=16)['close']
    
        close13_1 = close.rolling(13).mean().iloc[-1,:].T
        close13_2 = close.rolling(13).mean().iloc[-2,:].T
        close13_3 = close.rolling(13).mean().iloc[-3,:].T
        close_1 = close.iloc[-1,:].T
        close_2 = close.iloc[-2,:].T
        close_3 = close.iloc[-3,:].T
        
        stock_hold = pd.concat([close_1,close_2,close_3,close13_1,close13_2,close13_3],axis = 1)
        stock_hold.columns = ['close1','close2','close3','close13_1','close13_2','close13_3']
        to_sell = stock_hold[  (stock_hold['close1'] <  stock_hold['close13_1']) 
        &  (stock_hold['close2'] <  stock_hold['close13_2']) &  (stock_hold['close3'] <  stock_hold['close13_3'])]
        
        if len(to_sell)>0:
            g.stock_tosell = to_sell.index.tolist()
        
        
        
    
    
# 初始化函数，设定基准等等
def initialize(context):
    #body=read_file("深度报告数据0.csv")
    
    
    #g.datapd=pd.read_csv(BytesIO(body))
    g.stock_tosell = []
    
    g.previous_buylist = {}
    g.my_stock_today = []
    #g.datapd['证券代码']=[str(1000000+int(code))[1::] for code in g.datapd['证券代码'].tolist()]
    #去除新三板股票
    #g.datapd=g.datapd[g.datapd['证券代码']<'7']
    #g.datapd=g.datapd[(g.datapd['证券代码']<'4')|(g.datapd['证券代码']>='6')]
    #g.datapd['证券代码']=[code+'.XSHG' if code[0]=='6' else code+'.XSHE' for code in g.datapd['证券代码'].tolist()]
    #留下14：59前分享的研报
    #g.datapd=g.datapd[g.datapd['time']<='14:59']
    #g.datapd=g.datapd[g.datapd['页数']>=20]
    # print(g.datapd.head(10))
    # raise 11
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0, open_commission=0, close_commission=0, min_commission=0), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
    #中午卖出股
    
    run_daily(buy_stock, time='09:31', reference_security='000300.XSHG')

    #  收盘前买入股票
    #run_daily(buy_stock, time='15:00', reference_security='000300.XSHG')


# 清空卖出所有持仓

def sell_stock(context):
    #print(g.previous_stocklist)
    
    for stock in g.stock_tosell:
        
        order_target_value(stock,0) 
        
    g.stock_tosell = []
    
            
    #for stock in context.portfolio.positions.keys():
    #    if stock not in g.previous_stocklist.keys():
    #        order_target_value(stock,0) 
            
        
    return

def buy_stock(context):
    #date1=str(context.current_dt)[0:10]
    #date2=str(context.previous_date)[0:10]
    #datapd2=g.datapd[g.datapd['分享日期']==date1]
    #buylist=list(set(datapd2['证券代码'].tolist()))
    sell_stock(context)

    
    buynum = len(context.portfolio.positions.keys()) + len(g.my_stock_today)#len(g.my_stock_today);
    if len(context.portfolio.positions.keys())<=6:  # >0:
        if len(g.my_stock_today)>0:
            print('今天要买的股票是%s'%(",".join(g.my_stock_today)) )
            
            buynum =6
       
            target_to_buy = context.portfolio.total_value/buynum

            
            for stock in g.my_stock_today:
                cash = context.portfolio.available_cash
                if cash/target_to_buy<0.1:
                    break;
                order_target_value(stock,target_to_buy)
                
                
                g.previous_buylist[stock] = 0
                #g.previous_stocklist[stock] = 0;
    
    
    g.my_stock_today = []
    
    
    

    return
