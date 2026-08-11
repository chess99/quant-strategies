# 克隆自聚宽文章：https://www.joinquant.com/post/35604
# 标题：生猪期货CTA策略
# 作者：PokerTrader

# 导入函数库
from jqdata import *
import talib
import numpy as np
import pandas as pd

## 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('LH8888.XDCE')
    # set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')

    ### 期货相关设定 ###
    # 设定账户为金融账户
    set_subportfolios([SubPortfolioConfig(cash=context.portfolio.starting_cash, type='futures')])
    # 期货类每笔交易时的手续费是：买入时万分之0.23,卖出时万分之0.23,平今仓为万分之23
    set_order_cost(OrderCost(open_commission=0.000023, close_commission=0.000023,close_today_commission=0.0023), type='futures')
    # 设定保证金比例
    set_option('futures_margin_rate', 0.14)

    # 设置期货交易的滑点
    set_slippage(StepRelatedSlippage(0))
    # 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'IF8888.CCFX'或'IH1602.CCFX'是一样的）
    # 注意：before_open/open/close/after_close等相对时间不可用于有夜盘的交易品种，有夜盘的交易品种请指定绝对时间（如9：30）

    g.loss_ratio = 0.03
    g.win_ratio = 0.03
    g.loss_limit =0 
    g.std=0
    g.security = 'LH9999.XDCE'
    g.relative_security = '002714.XSHE' #相关品种选取的是牧原股份
    g.main_symbol = get_dominant_future('LH')
    g.buy_ration = 0.7
    g.sell_ration = 0.7
    g.long_order = None
    g.short_order = None
    g.long_threshold = g.short_threshold = 0
    g.ma_up_count = 0
    g.ma_down_count = 0
    g.open_order_lock = False 
    g.is_settlement_date = False
    g.firstTimeCalculateThreshold = True
    g.today_canBuy = True
    g.iskd_deadCross = False
    g.relative_is_close_down = False
    g.relative_is_close_up = False
    dt = context.current_dt # 当前日期
    dt_yestoday = dt-datetime.timedelta(days=1)
    cacluate_ma(dt_yestoday)
    run_daily( before_market_open, time = '8:50', reference_security = g.security)
    
      # 开盘时运行,支持分钟级别
    #run_daily( market_open, time = 'every_bar', reference_security = g.security)
      # 收盘后运行
     
    run_daily( after_market_close, time = '15:30', reference_security = g.security)

def handle_tick(context, tick):
    # 获取最新的 tick 数据 2018-01-02 09:00:59.
    tick_data = get_current_tick(g.main_symbol)
    # 判断是不是敏感时间
    
    deal(context, tick_data.current, 'tick')
    # print(tick_data)
# 2018-01-02 09:00:59.500000 - INFO  - Tick(code: RB1805.XSGE, datetime: 2018-01-02 09:00:59.500000, open: 3801.0, current: 3800.0, high: 3809.0, low: 3798.0, volume: 79234, money: 3013083440.0, position: 2527764.0, a1_p: 3800.0, a1_v: 116, b1_p: 3799.0, b1_v: 141)
## 开盘前运行函数
def before_market_open(context):
    # log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    dt = context.current_dt # 当前日期
    g.main_symbol = get_dominant_future('LH')  #获取主力合约
    if g.long_order is not None : g.main_symbol = g.long_order['security']
    if g.short_order is not None : g.main_symbol = g.short_order['security']
    subscribe(g.main_symbol, 'tick')
    
    #计算截止到上一个交易日的MACD指标
    dt_yestoday = dt-datetime.timedelta(days=1)
    yestoday = dt_yestoday.strftime('%Y-%m-%d')
    cacluate_ma(dt_yestoday)
    set_ration()
    g.firstTimeCalculateThreshold = True
    g.today_canBuy = True
    '''
    kdlist = myself_kdj(g.main_symbol,yestoday)
    g.k = kdlist[0]
    g.d = kdlist[1]
    g.iskd_deadCross = is_kd_deadCross(kdlist)
    g.std = calculate_std(g.main_symbol,20,yestoday)
    '''
    g.macd,g.diff,g.dea= calculateMACD_oneday(g.main_symbol,yestoday)
    print(g.macd,g.diff,g.dea)
    #判断相关品种的趋势一致性
    g.relative_is_close_down=is_close_down(g.relative_security,yestoday,5)
    g.relative_is_close_up = not g.relative_is_close_down
    print(g.relative_is_close_down)



def market_open(context):
    deal(context, get_current_data()[g.main_symbol].last_price)

def deal(context, last_price, frequency = 'tick'):
    dt = context.current_dt# 当前日期
    dt_yestoday = dt-datetime.timedelta(days=1)
    if frequency == 'bar' and dt.hour ==9 and dt.minute ==0:return
    
    #log.info('函数运行时间(deal)：'+str(dt.time()))
    if g.long_order and can_close_long(g.long_order, last_price, context.current_dt):
        log.info('close long in ', frequency)
        close_orders(g.long_order,list(context.portfolio.long_positions.keys())[0])
        g.main_symbol = get_dominant_future('LH')
    if g.short_order and can_close_short(g.short_order, last_price, context.current_dt):
        log.info('close short in ', frequency)
        close_orders(g.short_order, list(context.portfolio.short_positions.keys())[0])
        g.main_symbol = get_dominant_future('LH')
    if dt.hour == 21 or dt.hour == 9 :
        calculate_threshold(dt_yestoday)

    if g.long_order or g.short_order or g.is_settlement_date or (dt.hour == 14 and dt.minute == 59) or dt.hour == 15: return

    # 开仓逻辑 当macd大于0，且最新价格突破开仓阈值，且相关品种趋势向上时开多仓
    if  g.macd>0 and last_price > g.long_threshold and g.long_threshold!=0  and g.today_canBuy and g.relative_is_close_up:
        log.info('open long in ', frequency, last_price, g.long_threshold)
        open_order(context.portfolio.total_value, last_price, 'long')
    
    if  last_price < g.short_threshold and g.short_threshold!=0 and g.macd<0 and g.today_canBuy and g.relative_is_close_down:
        log.info('open short in ', frequency, last_price, g.long_threshold)
        open_order(context.portfolio.total_value, last_price,'short')

    
## 收盘后运行函数
def after_market_close(context):
    g.long_threshold = g.short_threshold = 0
    unsubscribe_all()
    log.info('##############################################################')

def cacluate_ma(dt):
    g.ten_ma_up = is_ma_up(g.main_symbol, 10, 4, dt.date())
    g.ten_ma_down = is_ma_down(g.main_symbol, 10, 4, dt.date())
    g.long_ma_down = is_ma_down(g.main_symbol, 60, 4, dt.date())
    g.long_ma_up = is_ma_up(g.main_symbol, 60, 4, dt.date())
    g.five_ma_up = is_ma_up(g.main_symbol, 5, 4, dt.date())
    g.five_ma_down = is_ma_down(g.main_symbol, 5, 4, dt.date())
    if(g.ten_ma_up): 
        g.ma_up_count = g.ma_up_count + 1
        log.info("均线上升趋势打开第" + str(g.ma_up_count) + "次")
    if(g.ten_ma_down): 
        g.ma_down_count = g.ma_down_count + 1
        log.info("均线下降趋势打开" + str(g.ma_down_count) + "次")
#计算标准差 
def calculate_std(stock,timePeriod,end_date):
    df = get_price(stock, count = timePeriod, end_date=end_date, frequency='daily', fields=['close'])
    close = df['close'].values
    std=close.std(ddof = 1)
    return std    


def open_order(total_value, last_price, side):
    # log.info("try open order =>",g.open_order_lock)
    if g.open_order_lock: return
    g.open_order_lock = True
    setLimit(last_price)
    lots = set_lots(total_value, g.loss_limit)
    new_order = order(g.main_symbol, lots, side=side)
    if new_order is None:
        g.open_order_lock = False
        log.warn("开仓失败!!!!!")
    else:
        # 还没有执行到这里另一个tick就进来了.. 所以这里需要做些什么
        if (new_order.status == OrderStatus.held):
            if side == 'long':
                g.long_order = clone_order(new_order)
            else:
                g.short_order = clone_order(new_order)
            g.can_close_order_time = get_close_order_time(new_order.add_time)
            ratio = g.loss_limit/last_price
            g.loss_ratio = round(ratio,3)
            log.info("止损比 => {}",g.loss_ratio)
            
def close_orders(close_order, stock):
    #  没办法应用g.main_symbol
    new_close_order = order(stock, close_order['amount'] * -1, side=close_order['side'])
    if new_close_order is None:
        log.warn("平仓失败！！！！！！！！！！！！！！")
    else:
        if close_order['side'] == "long":
            g.long_order = None
        else:
            g.short_order = None
        g.open_order_lock = False
        # g.can_close_order_time = get_close_order_time(new_close_order.add_time)

            
########################## 获取期货合约信息，请保留 #################################

# status: 状态, 一个[OrderStatus]值
# add_time: 订单添加时间, [datetime.datetime]对象
# is_buy: bool值, 买还是卖，对于期货:
# 开多/平空 -> 买
# 开空/平多 -> 卖
# amount: 下单数量, 不管是买还是卖, 都是正数
# filled: 已经成交的股票数量, 正数
# security: 股票代码
# order_id: 订单ID
# price: 平均成交价格, 已经成交的股票的平均成交价格(一个订单可能分多次成交)
# avg_cost: 卖出时表示下卖单前的此股票的持仓成本, 用来计算此次卖出的收益. 买入时表示此次买入的均价(等同于price).
# side: 多/空，'long'/'short'
# action: 开/平， 'open'/'close'
# commission：交易费用（佣金、税费等）
# 是否可以平多仓, 按照开盘价格卖出吗? 每天看盘就可以决定是否卖出了
def clone_order(order):
    return {'status': order.status,
                  'add_time': order.add_time,
                  'is_buy': order.is_buy,
                  'amount': order.amount,
                  'security': order.security,
                  'price': order.price,
                  'side': order.side,
                  'action': order.action
                  }
                 
def can_close_long(order, last_price, current_date):
    #跌破止损点或满足反向开仓条件则止损离场
    if last_price < order['price'] - g.loss_limit or (last_price < g.short_threshold and g.short_threshold!=0 and g.macd<0):
        log.info("止损平多 last_price => {}, cut_price => {}", last_price, order['price'] - g.loss_limit)
        return True
    if last_price > order['price'] + g.win_limit:
        log.info("止赢平多 last_price => {}, win_price => {}", last_price, order['price'] + g.win_limit)
        g.today_canBuy = False
        return True
    # log.warn("current_date => close_order_date", current_date, g.can_close_order_time)
    if current_date < g.can_close_order_time: return False
    return last_price > order['price'] and current_date.hour == 14 and current_date.minute == 59


def can_close_short(order, last_price, current_date):
    if last_price > order['price'] + g.loss_limit or (g.macd>0 and last_price > g.long_threshold and g.long_threshold!=0):
        log.info("止损平空 last_price => {}, cut_price => {}", last_price, order['price'] + g.loss_limit)
        return True
    if last_price < order['price'] - g.win_limit:
        log.info("止赢平空 last_price => {}, win_price => {}", last_price, order['price'] - g.win_limit)
        g.today_canBuy = False
        return True
    # log.warn("current_date => close_order_date", current_date, g.can_close_order_time)
    if current_date < g.can_close_order_time: return False
    return last_price < order['price'] and current_date.hour == 14 and current_date.minute == 59

#设置止盈止损点
def setLimit(last_price):
    
    g.loss_limit = max(g.std,last_price*0.05)
    log.info("losslimit",g.loss_limit)
    g.win_limit = max(2*g.std,last_price*0.05)
    log.info("winlimit",g.win_limit)        
    
# 获取金融期货合约到期日
def get_CCFX_end_date(future_code):
    # 获取金融期货合约到期日
    return get_security_info(future_code).end_date
# 获取五天平均振幅   
def get_swing(stock,amount,strdate,unit = '1d'):
    hist = get_price(g.main_symbol, count = amount, end_date=strdate, frequency='daily', fields=['high', 'low'])
    x = hist['high'] - hist['low']
    print(hist)
    average = int(x.mean())
    #倘若其中某一天振幅过大则返回0
    #for i in range(amount):
        #if (hist['high'][i]-hist['low'][i])>average*1.6:return 0
        #i=i+1
    #倘若三天的总振幅大于百分之5则返回0
    if (hist['high'].max()-hist['low'].min())/hist['low'].min()>0.1:
        log.info("过去五天总振幅大于百分之10,今日不开仓")
        return 0
    return average
    
#  获取开盘价
def get_open_price(stock):
    current_data = get_current_data()
    return current_data[stock].day_open

# 获取前n个单位时间当时的收盘价
def get_before_close_price(security, n, unit = '1d'):
    return attribute_history(security, n, unit, 'close')['close'][0]

def get_close_order_time(open_dt):
    close_date = open_dt + datetime.timedelta(days=7)
    return datetime.datetime(close_date.year, close_date.month, close_date.day, 14, 59, 00)
    
    
# 判断均线趋势向上
def is_ma_up(stock, sma_length, duration_day, end_date):
    ma_day = get_ma(stock, sma_length, duration_day, end_date)
    log.info("ma up => {}", ma_day)
    n = 1
    for i in range(len(ma_day) - 1):
        if ma_day[i] <= ma_day[i + 1]: n = n+1
    return n == len(ma_day)


# 判断均线趋势向下
def is_ma_down(stock, sma_length, duration_day, end_date):
    ma_day = get_ma(stock, sma_length, duration_day, end_date)
    log.info("ma down => {}", ma_day)
    n = 1
    for i in range(len(ma_day) - 1):
        if ma_day[i] >= ma_day[i + 1]: n = n+1
    return n == len(ma_day)

def get_ma(stock, sma_length, duration_day, end_date):
    #log.info("ma end date {}".format(end_date))
    df = get_price(stock, count = sma_length + duration_day, end_date=end_date, frequency='daily', fields=['open', 'close'])
    #log.info("----df close {}---".format(df['close']))
    closed = df['close'].values
    ma=talib.SMA(closed,timeperiod = sma_length)
    return ma[sma_length:]

    
def myself_kdj(stock,end_date):
    df = get_price(stock, count = 30, end_date=end_date, frequency='daily', fields=['high','low','close'])
    low_list = df['low'].rolling(9, min_periods=9).min()
    low_list.fillna(value=df['low'].expanding().min(), inplace=True)
    high_list = df['high'].rolling(9, min_periods=9).max()
    high_list.fillna(value = df['high'].expanding().max(), inplace=True)
    rsv = (df['close'] - low_list) / (high_list - low_list) * 100
    df['k'] = pd.DataFrame(rsv).ewm(com=2).mean()
    df['d'] = df['k'].ewm(com=2).mean()
    df['j'] = 3 * df['k'] - 2 * df['d']
    kdList = [int(df['k'][-1]),int(df['d'][-1])]
    log.info('kdlist ', kdList)
    return kdList
    
def is_kd_deadCross(kdlist):
    return kdlist[0]<kdlist[1]

#设置交易手数
def set_lots(total_value, loss_limit):
    # return 5
    N = 0.01 * total_value/loss_limit
    return int(N)
    
#设置阈值系数    
def set_ration():
    if g.five_ma_up and g.long_ma_up :
        g.buy_ration = 0.5
    elif g.long_ma_up :
        g.buy_ration = 0.6
    else : g.buy_ration = 0.7
    
    if  g.long_ma_down:
        g.sell_ration = 0.6
    else : g.sell_ration = 0.7
    
    
def calculate_threshold(date):
    if g.firstTimeCalculateThreshold == True:
        open_price = get_open_price(g.main_symbol)
        end = date.strftime('%Y-%m-%d')
        print(type(end))
        print(end)
        swing = get_swing(g.main_symbol,5,end)
        if swing ==0:
            g.long_threshold = g.short_threshold = 0
        else :
            g.long_threshold = int(open_price + swing * g.buy_ration)
            g.short_threshold = int(open_price - swing * g.sell_ration)
        log.info("震荡值：%d" %(swing))
        log.info("多单开仓点: %d" %(g.long_threshold)) 
        log.info("空单开仓点: %d" %(g.short_threshold))
        g.firstTimeCalculateThreshold = False
#判断前一天的价格是否低于5日前的价格
def is_close_down(stock,date,period):
    df = get_price(stock, count = period, end_date=date, frequency='daily', fields=['close'])
    closed=df['close'].values
    if closed[0]>closed[-1]:
        log.info("相关品种价格:%s" %(closed))
        return True
    else:
        return False
        
def calculateEMA(period, closeArray, emaArray=[]):
    """计算指数移动平均"""
    length = len(closeArray)
    nanCounter = np.count_nonzero(np.isnan(closeArray))
    if not emaArray:
        emaArray.extend(np.tile([np.nan],(nanCounter + period - 1)))
        firstema = np.mean(closeArray[nanCounter:nanCounter + period - 1])    
        emaArray.append(firstema)    
        for i in range(nanCounter+period,length):
            ema=(2*closeArray[i]+(period-1)*emaArray[-1])/(period+1)
            emaArray.append(ema)        
    return np.array(emaArray)
    
def calculateMACD(closeArray,shortPeriod = 12 ,longPeriod = 26 ,signalPeriod =9):
    ema12 = calculateEMA(shortPeriod ,closeArray,[])
    #print (ema12)
    ema26 = calculateEMA(longPeriod ,closeArray,[])
    #print (ema26)
    diff = ema12-ema26
    dea= calculateEMA(signalPeriod,diff,[])
    macd = 2*(diff-dea)
    return macd,diff,dea 
    
def calculateMACD_oneday(stock,date):
    df = get_price(stock, count =300, end_date=date,frequency='daily', fields=['close'])
    close = df['close']
    #print(df['close'])
    macd,diff,dea= calculateMACD(close,shortPeriod = 12 ,longPeriod = 26 ,signalPeriod =9)
    return macd[-1],diff[-1],dea[-1]
    
def print_position(dict):
    if dict:
        for position in list(dict.values()):  
            print("标的:{0},总仓位:{1},标的价值:{2}, 建仓时间:{3}".format(position.security, position.total_amount, position.value, position.init_time))

########################## 自动移仓换月函数 #################################
def position_auto_switch(context,pindex=0,switch_func=None, callback=None):
    """
    期货自动移仓换月。默认使用市价单进行开平仓。
    :param context: 上下文对象
    :param pindex: 子仓对象
    :param switch_func: 用户自定义的移仓换月函数.
        函数原型必须满足：func(context, pindex, previous_dominant_future_position, current_dominant_future_symbol)
    :param callback: 移仓换月完成后的回调函数。
        函数原型必须满足：func(context, pindex, previous_dominant_future_position, current_dominant_future_symbol)
    :return: 发生移仓换月的标的。类型为列表。
    """
    import re
    subportfolio = context.subportfolios[pindex]
    symbols = set(subportfolio.long_positions.keys()) | set(subportfolio.short_positions.keys())
    switch_result = []
    for symbol in symbols:
        match = re.match(r"(?P<underlying_symbol>[A-Z]{1,})", symbol)
        if not match:
            raise ValueError("未知期货标的：{}".format(symbol))
        else:
            dominant = get_dominant_future(match.groupdict()["underlying_symbol"])
            cur = get_current_data()
            symbol_last_price = cur[symbol].last_price
            dominant_last_price = cur[dominant].last_price
            if dominant > symbol:
                for p in (subportfolio.long_positions.get(symbol, None), subportfolio.short_positions.get(symbol, None)):
                    if p is None:
                        continue
                    if switch_func is not None:
                        switch_func(context, pindex, p, dominant)
                    else:
                        amount = p.total_amount
                        # 跌停不能开空和平多，涨停不能开多和平空。
                        if p.side == "long":
                            symbol_low_limit = cur[symbol].low_limit
                            dominant_high_limit = cur[dominant].high_limit
                            if symbol_last_price <= symbol_low_limit:
                                log.warning("标的{}跌停，无法平仓。移仓换月取消。".format(symbol))
                                continue
                            elif dominant_last_price >= dominant_high_limit:
                                log.warning("标的{}涨停，无法开仓。移仓换月取消。".format(symbol))
                                continue
                            else:
                                log.info("进行移仓换月：({0},long) -> ({1},long)".format(symbol, dominant))
                                order_target(symbol,0,side='long')
                                order_target(dominant,amount,side='long')
                                switch_result.append({"before": symbol, "after":dominant, "side": "long"})
                            if callback:
                                callback(context, pindex, p, dominant)
                        if p.side == "short":
                            symbol_high_limit = cur[symbol].high_limit
                            dominant_low_limit = cur[dominant].low_limit
                            if symbol_last_price >= symbol_high_limit:
                                log.warning("标的{}涨停，无法平仓。移仓换月取消。".format(symbol))
                                continue
                            elif dominant_last_price <= dominant_low_limit:
                                log.warning("标的{}跌停，无法开仓。移仓换月取消。".format(symbol))
                                continue
                            else:
                                log.info("进行移仓换月：({0},short) -> ({1},short)".format(symbol, dominant))
                                order_target(symbol,0,side='short')
                                order_target(dominant,amount,side='short')
                                switch_result.append({"before": symbol, "after": dominant, "side": "short"})
                                if callback:
                                    callback(context, pindex, p, dominant)
    return switch_result
