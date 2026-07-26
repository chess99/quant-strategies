# 克隆自聚宽文章：https://www.joinquant.com/post/35902
# 标题：北上净买入策略
# 作者：daa

# 克隆自聚宽文章：https://www.joinquant.com/post/31797
# 标题：追随北上资金
# 作者：geekzhp

# 导入函数库
from jqdata import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    g.N=2
    
    run_daily(period2,time='every_bar')
    #run_weekly(period2,-1)
    #run_monthly(period, 1)
    run_monthly(period, 7)

def period2(context):
    if len(context.portfolio.positions)>0:
        for stock in context.portfolio.positions:
            cost=context.portfolio.positions[stock].avg_cost
            # 获得股票现价
            price=context.portfolio.positions[stock].price
            # 计算收益率
            if cost > 0 :
                ret=price/cost-1
                if ret < -0.16 :
                    order_target(stock,0)
                    log.info('止损卖出:{}'.format(get_security_info(stock).display_name))
                    log.info(cost)
                    log.info(price)
                    #log.info('自损卖出')
                    log.info(ret)
                    period(context)

def period(context):
    toBuy=selectStock(context, -1)
    #print(toBuy)
    # for stock in toBuy:
    #     print('{}:{}'.format(stock[:6],get_security_info(stock).display_name))
    adjustPostion(context,toBuy)
    
def adjustPostion(context,toBuy):
    #卖出:现持仓的股票，如果不在目标池中，且没有涨停，卖出
    if len(context.portfolio.positions)>0:
        lastPrice=history(1,'1m','close',context.portfolio.positions.keys()) 
        #print(lastPrice)
        for stock in context.portfolio.positions:
            if not stock in toBuy:
                if lastPrice[stock][-1]<get_current_data()[stock].high_limit:
                    order_target(stock,0)
                    log.info('卖出:{}'.format(get_security_info(stock).display_name))
            
    #买入:依次买入目标池中的股票
    #cash=context.portfolio.available_cash/g.N
    for stock in toBuy:
        positionsCount=len(context.portfolio.positions)
        if g.N>positionsCount:
            div = (g.N-positionsCount)
            cash=context.portfolio.available_cash 
            if div > 0 :
                cash=context.portfolio.available_cash/div
            if stock not in context.portfolio.positions:
                order_value(stock,cash)
                log.info('买入:{}'.format(get_security_info(stock).display_name))

def selectStock(context, mix):
    today=context.current_dt.date()
    yesterday=shiftTradingDay(today, mix)
    q=query(finance.STK_EL_TOP_ACTIVATE
        ).filter(finance.STK_EL_TOP_ACTIVATE.day==yesterday,
        finance.STK_EL_TOP_ACTIVATE.link_id.in_([310001]))
    df=finance.run_query(q)
    df['net']=df['buy']-df['sell']
    df.sort_values(by=['net'],ascending=False,inplace=True)
    stockList=df['code'].tolist()
    stockList=filterStock(context,stockList)
    #print(stockList)
    
    q2=query(finance.STK_EL_TOP_ACTIVATE
        ).filter(finance.STK_EL_TOP_ACTIVATE.day==yesterday,
        finance.STK_EL_TOP_ACTIVATE.link_id.in_([310002]))
    df2=finance.run_query(q2)
    df2['net']=df2['buy']-df2['sell']
    df2.sort_values(by=['net'],ascending=False,inplace=True)
    stockList2=df2['code'].tolist()
    stockList2=filterStock(context,stockList2)
    #print(stockList2)

    allList = []
    if len(stockList) > 0 :
        hStock = stockList[0]
        allList.append(hStock)
    if len(stockList2) > 0 :
        sStock = stockList2[0]
        allList.append(sStock)

    if len(allList) <= 0 :
        nexta = mix - 1
        allList = selectStock(context, nexta)
    
    print(allList)
    
    return allList
    

#获取N天前的交易日日期
def shiftTradingDay(date,shift):
    tradingDays=get_all_trade_days()
    return tradingDays[list(tradingDays).index(date)+shift]
    
    
#综合过滤
def filterStock(context,stockList):
    currData=get_current_data()
    return [stock for stock in stockList if not (
        currData[stock].paused or                   #停牌
        currData[stock].is_st or                    #ST
        'ST' in currData[stock].name or          #ST
        '*'  in currData[stock].name or          #ST
        '退' in currData[stock].name           #退市
        #or stock.startswith('300') or              #创业板
        #stock.startswith('688')               #科创板
        #or currData[stock].day_open>=currData[stock].high_limit  #开盘涨停
        # or currData[stock].day_open<=currData[stock].low_limit  #开盘跌停
        # or (context.current_dt.date()-get_security_info(stock).start_date).days<250    #上市不满一年
        )]
