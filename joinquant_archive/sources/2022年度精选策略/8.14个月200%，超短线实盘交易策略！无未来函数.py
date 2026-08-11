# 克隆自聚宽文章：https://www.joinquant.com/post/36786
# 标题：14个月200%，超短线实盘交易策略！无未来函数
# 作者：随波逐浪9

# 导入函数库
import datetime
from jqdata import *
from jqlib.technical_analysis import *
import numpy as np
# 初始化函数，设定基准等等
def initialize(context):
    enable_profile()
    # log.set_level('order', 'error')
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 关闭未来函数
    set_option("avoid_future_data", True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 设置交易成本万分之三
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),type='fund')
    # 股票购买限制
    g.buy_stock_limit = 1

## 开盘前运行函数
def before_trading_start(context):
    # 初始化参数
    initHandleParam()
    prev_trade_day = context.previous_date
    # 获取过滤股票
    stock_pool = get_all_securities(['stock'], date=prev_trade_day)
    stock_list = filter_stock(stock_pool)
    
    # 取昨天，前天的MA5,MA10,MA20,MA30数据
    p1_ma5 = get_stock_price(stock_list,prev_trade_day,5).groupby('code').mean()
    p1_ma10 = get_stock_price(stock_list,prev_trade_day,10).groupby('code').mean()
    p1_ma20 = get_stock_price(stock_list,prev_trade_day,20).groupby('code').mean()
    p1_ma30 = get_stock_price(stock_list,prev_trade_day,30).groupby('code').mean()
    p2_ma5 = get_stock_price(stock_list,getday3(prev_trade_day,-1),5).groupby('code').mean()
    p2_ma10 = get_stock_price(stock_list,getday3(prev_trade_day,-1),10).groupby('code').mean()
    p2_ma20 = get_stock_price(stock_list,getday3(prev_trade_day,-1),20).groupby('code').mean()
    p2_ma30 = get_stock_price(stock_list,getday3(prev_trade_day,-1),30).groupby('code').mean()
    dx1 = []
    for stock in stock_list:
        p1_ma5_close = p1_ma5['close'][stock]
        p1_ma10_close = p1_ma10['close'][stock]
        p1_ma20_close = p1_ma20['close'][stock]
        p1_ma30_close = p1_ma30['close'][stock]
        p2_ma5_close = p2_ma5['close'][stock]
        p2_ma10_close = p2_ma10['close'][stock]
        p2_ma20_close = p2_ma20['close'][stock]
        p2_ma30_close = p2_ma30['close'][stock]
        p1_ma5_volume = p1_ma5['volume'][stock]
        p1_ma10_volume = p1_ma10['volume'][stock]
        p2_ma5_volume = p2_ma5['volume'][stock]
        p2_ma10_volume = p2_ma10['volume'][stock]

        # MA5下穿MA10
        # MA5,MA10交易量纠错
        # MA20,MA30上升
        if p1_ma5_close < p1_ma10_close \
        and p2_ma5_close > p2_ma10_close \
        and p2_ma5_volume > p2_ma10_volume \
        and (p1_ma5_volume * 1.2) > p1_ma10_volume \
        and p1_ma20_close > p2_ma20_close \
        and p1_ma30_close > p2_ma30_close \
        :
            dx1.append(stock)
    print('dx1可选股票%s支.' %(len(dx1)))
    dx2 = []
    macd_dif, macd_dea, macd_macd = MACD(security_list = dx1, check_date = prev_trade_day, SHORT = 12, LONG = 26, MID = 9, unit = '1d')
    macd_dif2, macd_dea2, macd_macd2 = MACD(security_list = dx1, check_date = getday(prev_trade_day,-1), SHORT = 12, LONG = 26, MID = 9, unit = '1d')
    for stock in dx1:
        # MACD 0到-0.1之间
        if macd_dif[stock] > 0 and macd_dea[stock] > 0 \
        and 0 > macd_dea[stock] - macd_dif[stock] > -0.1 \
        :
            dx2.append(stock)
    print('dx2可选股票%s支' %(len(dx2)))
    dx3 = []
    current_data = get_current_data()
    for stock in dx2:
        p1_flow = get_money_flow(security_list = stock,end_date = prev_trade_day,count = 1,fields=['change_pct'])
        p2_flow = get_money_flow(security_list = stock,end_date = getday3(prev_trade_day,-1),count = 1,fields=['change_pct'])
        if len(p1_flow['change_pct']) == 0 or len(p2_flow['change_pct']) == 0:
            continue
        # 死叉前后两天收盘价必须一跌一涨
        if (p1_flow['change_pct'][0] > 0 and p2_flow['change_pct'][0] < 0) \
        or (p1_flow['change_pct'][0] < 0 and p2_flow['change_pct'][0] > 0) \
        :
            dx3.append(stock)
    print('dx3可选股票%s支' %(len(dx3)))
    dx4 = dx3
    dx5 = []
    for stock in dx4:
        p1_1 = get_price(security=stock, end_date=prev_trade_day, frequency='1d', fields=['close'],
                                          panel=False, count=1, skip_paused=True)
        if p1_1['close'][0] <= current_data[stock].day_open:
            continue
        dx5.append(stock)
    print('dx5可选股票%s支' %(len(dx5)))
    g.buy_list = dx5
    g.buy_list.sort()
    print('%s:共找到%d只股票可以购买.%s'%(context.current_dt,len(g.buy_list),g.buy_list))


## 开盘时运行函数
def handle_data(context,data):
    current_data = get_current_data()
    # 卖出
    for stock in context.portfolio.positions.keys():
        price = data[stock].close
        if context.portfolio.positions[stock].closeable_amount == 0  \
        or current_data[stock].low_limit == price \
        or current_data[stock].high_limit == price \
        :
            continue
        print('%s卖出(自动):自动卖出:成本价:%s,当前价:%s'%(stock,context.portfolio.positions[stock].avg_cost,price))
        sell_stock(stock,0)

    # 判断是否买满
    if g.buy_stock_limit <= len(context.portfolio.positions.keys()):
        return 
    # 买入
    for stock in g.buy_list:
        price = data[stock].close
        if context.portfolio.available_cash < (price * 100) \
        or current_data[stock].low_limit == price \
        or current_data[stock].high_limit == price \
        or stock in context.portfolio.positions.keys() \
        :
            continue
        print('%s买入(自动):自动买入:当前价:%s'%(stock,price))
        buy_stock(context,stock)
        break

####################################公共函数######################################
def initHandleParam():
    g.buy_list = []
    
def get_stock_price(stock_list,ed,days):
    stock_price = get_price(security=stock_list, end_date=ed, frequency='1d', fields=['close','volume'],
                                      panel=False, count=days, skip_paused=True)
    return stock_price
def getday(ed,count):
    dates = get_trade_days(end_date =ed,count = (-count+1))
    return dates[0]
def getday2(date,n):
    yesterday = datetime.datetime.strptime(date,'%Y-%m-%d') + datetime.timedelta(n)
    return yesterday
def getday3(d,step):
    day = d + datetime.timedelta(step)
    return day
# 购买股票
def buy_stock(context,stock):
    # 计算今天还需要买入的股票数量
    need_count = g.buy_stock_limit - len(context.portfolio.positions.keys())
    if need_count == 0:
        return
    # 把现金分成几份,
    buy_cash = context.portfolio.available_cash / need_count
    # 买入这么多现金的股票
    order_value(stock, buy_cash)
    # 记录这次买入
    # log.info("购买： %s" % (stock))
#出售股票
def sell_stock(stock,value):
    # 全部卖出
    order_target(stock, value)
    # 记录这次卖出
    # log.info("卖出： %s" % (stock))

def filter_stock(stock_pool):
    return list(stock for stock in stock_pool.index
                if not stock.startswith('30') and not stock.startswith('688')
                and not 'ST' in stock_pool['display_name']
                and not '*' in stock_pool['display_name']
                and not '退' in stock_pool['display_name']
                )
