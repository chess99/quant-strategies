# 克隆自聚宽文章：https://www.joinquant.com/post/45324
# 标题：低开买入小市值策略（剥头皮策略）3.0 总结
# 作者：langcheng999


from jqdata import *


def initialize(context):
    log.set_level('order', 'warning')
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    #set_option("t0_mode", True) 
    set_slippage(FixedSlippage(0.02))
    # set_commission(PerTrade(buy_cost=0.0003, sell_cost=0.0013, min_cost=5))
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5), type='stock')
    set_benchmark('399303.XSHE')
    
    g.choice = 500
    g.stock_num = 5
    g.stock_pool=[]
    # 模拟实盘中使用
    # run_daily(sell, time='9:26', reference_security='399303.XSHE')
    # run_daily(buy, time='9:27', reference_security='399303.XSHE')
    
    # 回测使用
    run_daily(my_trade, time='9:30', reference_security='399303.XSHE')

def filter_specials(context, stock_list):
    # type: (Context, int) -> list
    """
    过滤掉：1）三停：涨停、跌停、停牌；2）三特：st, *st, 退；3）科创、创业; 4）次新；
    适用于开盘前选股，如果是盘中，用curr_data[security].last_price替代curr_data[stock].day_open
    
    """
    curr_data = get_current_data()
    stock_list = [stock for stock in stock_list if not (
            # (curr_data[stock].day_open == curr_data[stock].high_limit) or   # 涨停开盘
            # (curr_data[stock].day_open == curr_data[stock].low_limit) or    # 跌停开盘
            curr_data[stock].paused or  # 停牌
            curr_data[stock].is_st or   # ST
            ('ST' in curr_data[stock].name) or
            ('*' in curr_data[stock].name) or
            ('退' in curr_data[stock].name) or
            # (stock.startswith('30')) or    # 创业
            (stock.startswith('688'))   # 科创
    )]
    #
    return stock_list

def before_trading_start(context):  # 该函数启动时间为'09:00'
    fundamentals_data = get_fundamentals(query(valuation.code, valuation.market_cap).order_by(valuation.market_cap.asc()).limit(g.choice))
    g.stock_pool = list(fundamentals_data['code'])
    g.stock_pool = filter_specials(context, g.stock_pool)

def my_trade(context):
    sell(context)
    buy(context)

def sell(context):
    for position in list(context.portfolio.positions.values()):
        if position.closeable_amount>0:
            close_position(position)

def buy(context):
    data_today = get_current_data()
    position_count = len(context.portfolio.positions)
    
    #选股  昨日收盘价大于五日收盘均价 且 昨日最低大于今天开盘价，卖出是第二天无条件卖出。
    buy_stocks = []
    for s in g.stock_pool:
        if position_count + len(buy_stocks) >= g.stock_num:
            break
        
        df = attribute_history(s, 5, '1d', ('close', 'low', 'high', 'paused'), False)
        # if (df['paused'].max() == 0): #过去5天没有停盘
        #     # today_open = data_today[s].day_open
    
        #     jihe_price = get_call_auction(s, str(context.current_dt.date()), str(context.current_dt.date()))
        #     if jihe_price.size > 0:
        #         today_open = jihe_price['current'][0]
        #         # today_open = get_call_auction(s, str(context.current_dt), str(context.current_dt), ['current', 'a1_p'])['current'][0]
        #         # print(str(context.current_dt.date()) +  '开盘价：' +  str(today_open))
        #         prev_close = df['close'][-1]
        #         prev_low = df['low'][-1]
        #         chg = (today_open-prev_close)/prev_close*100  #计算开盘时跌幅
        #         if today_open < prev_low and chg > -8 and chg < -1:
        #             low=min(df['low'].values[-4:])
        #             high=max(df['high'].values[-4:])
        #             precent = (high - low)/low*100 #计算4天振幅
        #             if(precent<=20):
        #                 df['ema']=df['close'].ewm(span=5).mean()
        #                 ema=df['ema'].values[-1]
        #                 if(prev_close > ema):
        #                     buy_stocks.append(s)
        #     # else:
        #     #     print('获取不到集合竞价，jihe_price')
            
        if (df['paused'].max() == 0): #过去5天没有停盘
            today_open = data_today[s].day_open
            prev_close = df['close'][-1]
            prev_low = df['low'][-1]
            chg = (today_open-prev_close)/prev_close*100  #计算开盘时跌幅
            if today_open < prev_low and chg > -8 and chg < -1:
                low=min(df['low'].values[-4:])
                high=max(df['high'].values[-4:])
                precent = (high - low)/low*100 #计算4天振幅
                if(precent<=20):
                    df['ema']=df['close'].ewm(span=5).mean()
                    ema=df['ema'].values[-1]
                    if(prev_close > ema):
                        buy_stocks.append(s)
    
    #按选股数分配资金买入
    target_num = len(buy_stocks)
    if target_num > 0:
        value =  context.portfolio.available_cash / g.stock_num

        for stock in buy_stocks:
            if stock not in context.portfolio.positions:
                open_position(stock, value)

                    
# 3-1 交易模块-自定义下单
def order_target_value_(security, value):
    if value == 0:
        log.debug("Selling out %s" % security)
    else:
        log.debug("Order %s to value %f" % (security, value))
    return order_target_value(security, value)


# 3-2 交易模块-开仓
def open_position(security, value):
    print("buy:"+security+" "+str(value))
    _order = order_target_value_(security, value)
    if _order is not None and _order.filled > 0:
        return True
    return False


# 3-3 交易模块-平仓
def close_position(position):
    security = position.security
    _order = order_target_value_(security, 0)  # 可能会因停牌失败
    if _order is not None:
        if _order.status == OrderStatus.held and _order.filled == _order.amount:
            return True
    return False

