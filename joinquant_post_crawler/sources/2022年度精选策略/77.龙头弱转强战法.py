# 克隆自聚宽文章：https://www.joinquant.com/post/37189
# 标题：龙头弱转强战法
# 作者：oupian

# 标题：龙头弱转强战法
# 作者：oupian

# 导入函数库
from jqdata import *
import math

# 初始化函数，设定基准等等
def initialize(context):
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
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
      # 开盘时运行
    run_daily(market_open, time='open', reference_security='000300.XSHG')
    
    #盘中卖
    #run_daily(sellstock, time='10:00', reference_security='000300.XSHG')
    run_daily(sellstock2, time='11:00', reference_security='000300.XSHG')
    run_daily(sellstock2, time='13:30', reference_security='000300.XSHG')
    run_daily(sellstock2, time='14:00', reference_security='000300.XSHG')
    run_daily(sellstock2, time='14:30', reference_security='000300.XSHG')
    
    #尾盘卖
    run_daily(sellstock, time='14:57', reference_security='000300.XSHG')
      # 收盘后运行
    #run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')
    
    g.STOCKCOUNT  = 3

## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    g.bought_stocks_o = list(context.portfolio.positions.keys())
    # 给微信发送消息（添加模拟交易，并绑定微信生效）
    # send_message('美好的一天~')

    # 要操作的股票：平安银行（g.为全局变量）
    g.security = '000001.XSHE'
    #g.stocktobuy=[] #存放StocktoBuy
    g.securitytobuy=[] #存放股票代码
    g.securitytobuy2=[] #存放股票代码
    stocktobuydict = dict()

    # 获取交易日
    today=context.current_dt.date()
    trd_days = get_trade_days(end_date=today, count = 90)
    # 获取n个交易日之前前上市股票【即过滤掉次新股】
    g.all_securities = get_all_securities('stock', trd_days[0])
    
    #获得所有股票代码
    g.stocks = list(g.all_securities.index)
    #过掉停牌股票
    current_data = get_current_data()
    g.stocks = [stock for stock in g.stocks if  ('退' not in current_data[stock].name) and (not current_data[stock].paused)]
    
    for tmpstock in g.bought_stocks_o:
        if (g.stocks.count(tmpstock) <= 0):
            g.stocks.append(tmpstock)
    
    stocknamelist = []
    for tmpstock in g.stocks:
        stockname = g.all_securities.loc[tmpstock, "display_name"]
        stocknamelist.append(stockname)
    
    g.stockdict = dict(zip(g.stocks,stocknamelist))
    
    g.stocks10 = [] #10cm
    g.stocks20 = [] #20cm
    g.stocksST = [] #ST
    
    for security in g.stocks:
        if security.startswith('688') or security.startswith('30'):
            g.stocks20.append(security)
        elif security.startswith('ST') or security.startswith('*ST'):
            g.stocksST.append(security)
        else:
            g.stocks10.append(security)
    
    for security in g.stocks10:
        #df = False, 返回dic
        hisprice = attribute_history(security, 20, '1d', ('open', 'close', 'high', 'low', 'volume'),df=False)
        if (len(hisprice['open'])<5): #K线数量小于5个，跳过
            continue
        
        if(hisprice['high'].max()/hisprice['close'][-1] > 1.1):
            continue
        
        zfnum = hisprice['close'].max()/hisprice['close'].min()
        
        if(zfnum<1.3): #涨幅小于30%
            continue
        stocktobuydict[security] = zfnum
        #海选结束
        
    #按照涨停次数排序
    stocktobuyorder=sorted(stocktobuydict.items(),key=lambda x:x[1],reverse=True)
    length = len(stocktobuyorder)
    length = min(length,3) #只关注市场涨幅前涨幅前3
    securitytobuytmp = []
    for i in range(length):
        securitytobuytmp.append(stocktobuyorder[i][0])
    for security in securitytobuytmp:
        hisprice = attribute_history(security, 10, '1d', ('open', 'close', 'high', 'low', 'volume'),df=False)
        if (len(hisprice['open'])<5): #K线数量小于5个，跳过
            continue
        #if(hisprice['close'][-2]/hisprice['close'][-3] < 1.099): #前天涨停
            #continue
        if(hisprice['close'][-1] / hisprice['close'][-2] < 0.911 ): #昨天未跌停
            continue
        if((hisprice['close'][-1] / hisprice['close'][-2])>1.099 ): #昨天未涨停
            continue
        if((hisprice['high'][-1] / hisprice['low'][-1])>1.2 ): #振幅太大
            continue
        #if(hisprice['volume'][-1] < hisprice['volume'].mean()): #昨天放量
        #    continue
        g.securitytobuy.append(security)

    #log.info(g.securitytobuy)
## 开盘时运行函数
def market_open(context):
    #log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    #history(count, unit='1d', field='avg', security_list=None, df=True, skip_paused=False, fq='pre')
    if(len(g.securitytobuy)<1):
        log.info('None to buy1')
        return
    
    hisprice = history(1, unit='1d', field='close', security_list=g.securitytobuy, df=False, skip_paused=True, fq='pre')
    current_data=get_current_data()
    for security in g.securitytobuy:
        if ((current_data[security].day_open>hisprice[security][0]) & (current_data[security].day_open/hisprice[security][0]<1.045)): #高开 less than 5%
            g.securitytobuy2.append(security)

    if(len(g.securitytobuy2)<1):
        log.info('None to buy2')
        return
    
    bought_num = len(context.portfolio.positions)
    numcanbuy = g.STOCKCOUNT - bought_num
    numtobuy = min(numcanbuy,2) #每天最多买两支票
    if (numtobuy<1):
        log.info('number to buy is 0')
        return
    buy_cash = context.portfolio.available_cash / numcanbuy
    for security in g.securitytobuy2:
        if(numtobuy<=0):
            break
        cprice = current_data[security].last_price
        hlprice = current_data[security].high_limit
        if(cprice == hlprice): #涨停了 跳过
            continue
        buynum = math.floor(buy_cash/(100*cprice))
        if buynum < 1:
            log.info("%s 价格太贵，跳过, 可用现金: %s" % (g.stockdict[security], buy_cash))
            continue
        ordert = order_target(security, buynum*100)
        if (None == ordert):
            log.info("Buy %s failed" % (g.stockdict[security]))
        else: 
            #g.bought_stocks.append(security)
            log.info("Buy %s success,amount:%s" % (g.stockdict[security], buynum*100*cprice))
            numtobuy -= 1
            break


#获取卖票的列表
def get_sell_list(context, securitylist):
    listgot = []
    if len(securitylist) <= 0:
        return listgot
    today = context.current_dt.strftime('%Y-%m-%d')

    #获取2天的数据，包括今天; 昨天的在前，今天的在后
    todayclose=get_bars(securitylist, 2,  unit='1d',fields=['high','close'], include_now=True)
    #hisclose=get_bars(securitylist, 1,  unit='1d',fields=['close'], include_now=False)
    #VOLT,MAVOL5,MAVOL10 = VOL(securitylist, check_date=today, M1=5, M2=10, include_now = False)

    for security in securitylist:
        if ((todayclose[security][1][1]/todayclose[security][0][1]) < 1.098): #未涨停就卖 
            listgot.append(security)
    return listgot

#获取卖票的列表
def get_sell_list2(context, securitylist):
    listgot = []
    if len(securitylist) <= 0:
        return listgot
    today = context.current_dt.strftime('%Y-%m-%d')

    #获取2天的数据，包括今天; 昨天的在前，今天的在后
    todayclose=get_bars(securitylist, 2,  unit='1d',fields=['high','close'], include_now=True)
    #hisclose=get_bars(securitylist, 1,  unit='1d',fields=['close'], include_now=False)
    #VOLT,MAVOL5,MAVOL10 = VOL(securitylist, check_date=today, M1=5, M2=10, include_now = False)

    for security in securitylist:
        if ((todayclose[security][1][1] < todayclose[security][0][1])): #跌破昨日收盘价 
            log.info("Less than lastday close %s" % (g.stockdict[security]))
            listgot.append(security)
    return listgot

##卖股票函数
def sellstock(context):
    sell_list = get_sell_list(context, g.bought_stocks_o)
    if len(sell_list)>0:
        for security in sell_list:
            boughtcost = context.portfolio.positions[security].acc_avg_cost
            profit = (context.portfolio.positions[security].price - boughtcost)/boughtcost *100
            log.info("Sell %s " % (g.stockdict[security]), "profit: %.1f%%" % profit, "init time %s" % context.portfolio.positions[security].init_time)
            ordert = order_target_value(security,0)
            if (None == ordert):
                log.info("Sell failed %s" % (g.stockdict[security]))
            else:
                g.bought_stocks_o.remove(security)
    else:
        log.info("no one to sell")
    return

##盘中，跌破昨日收盘价卖
def sellstock2(context):
    sell_list = get_sell_list2(context, g.bought_stocks_o)
    if len(sell_list)>0:
        for security in sell_list:
            boughtcost = context.portfolio.positions[security].acc_avg_cost
            profit = (context.portfolio.positions[security].price - boughtcost)/boughtcost *100
            log.info("Sell %s " % (g.stockdict[security]), "profit: %.1f%%" % profit, "init time %s" % context.portfolio.positions[security].init_time)
            ordert = order_target_value(security,0)
            if (None == ordert):
                log.info("Sell failed %s" % (g.stockdict[security]))
            else:
                g.bought_stocks_o.remove(security)
    return    
