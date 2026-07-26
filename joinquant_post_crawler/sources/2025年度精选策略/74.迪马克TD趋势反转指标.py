# 克隆自聚宽文章：https://www.joinquant.com/post/28543
# 标题：迪马克TD趋势反转指标
# 作者：魔术先生

# 导入函数库
from jqdata import *

## 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    g.code = '000300.XSHG'
    g.n1 = 8
    g.n2 = 13
    g.count = 0    # setup完成后开始count
    g.stop = 0
    g.setup_high = 0 #下跌setup中的最高价
    g.setup_low = 0 #上升setup中的最低价
    g.setup = 0 #1：上升；-1：下降；0：无
    g.flag = 0
    g.price = 0
    g.p = 0
    g.hold = ''
    g.lc = False
    g.trend = 0  # -1:反转 0：空仓 1：顺势
    
    ### 期货相关设定 ###
    # 设定账户为金融账户
    set_subportfolios([SubPortfolioConfig(cash=context.portfolio.starting_cash, type='index_futures')])
    # 期货类每笔交易时的手续费是：买入时万分之0.23,卖出时万分之0.23,平今仓为万分之23
    set_order_cost(OrderCost(open_commission=0.000023, close_commission=0.000023,close_today_commission=0.0023), type='index_futures')
    # 设定保证金比例
    set_option('futures_margin_rate', 0.15)

    # 设置期货交易的滑点
    set_slippage(StepRelatedSlippage(2))
    # 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'IF8888.CCFX'或'IH1602.CCFX'是一样的）
    # 注意：before_open/open/close/after_close等相对时间不可用于有夜盘的交易品种，有夜盘的交易品种请指定绝对时间（如9：30）
      # 开盘前运行
    run_daily( before_market_open, time='09:00', reference_security='IF8888.CCFX')
      # 开盘时运行
    run_daily( market_open, time='09:30', reference_security='IF8888.CCFX')
      # 收盘后运行
    run_daily( after_market_close, time='15:30', reference_security='IF8888.CCFX')


## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    # log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    g.today = context.current_dt.date()
    g.hands = calc_hands(context)
    g.c = get_future_contracts('IF')
    g.sub = g.c[1]
    g.main = g.c[0]
    if (get_security_info(g.main).end_date - context.current_dt.date()).days < 10:
        g.main = g.sub

## 开盘时运行函数
def market_open(context):
    # if g.lc and g.stop!=0:
    #     g.stop += 1
    #     return
    # elif g.lc and g.stop==0:
    #     g.stop = 0
    #     g.lc = False
    current_data = get_current_data()
    last = current_data[g.code].last_price
    if g.hold:
        end = get_security_info(g.hold).end_date
        if (end - context.current_dt.date()).days < 5:
            gap = current_data[g.sub].last_price - last
            g.price += gap
            g.p += gap
            if g.trend == 1:
                if g.setup==-1:
                    print('顺势移仓空头')
                    order_target(g.hold,0,None,'short')
                    order(g.sub,g.hands,None,'short')
                    g.hold = g.sub
                elif g.setup==1:
                    print('顺势移仓多头')
                    order_target(g.hold,0,None,'long')
                    order(g.sub,g.hands,None,'long')
                    g.hold = g.sub
            elif g.trend == -1:
                if g.setup==1:
                    print('反转移仓空头')
                    order_target(g.hold,0,None,'short')
                    order(g.sub,g.hands,None,'short')
                    g.hold = g.sub
                elif g.setup==-1:
                    print('反转移仓多头')
                    order_target(g.hold,0,None,'long')
                    order(g.sub,g.hands,None,'long')
                    g.hold = g.sub

    
    if g.setup==-1 and g.count==g.n2 and not g.flag:
        pre3close = attribute_history(g.code,3,'1d','close').close.values[0]
        pre1low = attribute_history(g.code,1,'1d','low').low.values[0]
        if pre1low > pre3close:
            print('做空信号----------------')
            g.price = last
            g.p = last
            g.hold = g.main
            g.flag = 1
            g.trend = 1
            order(g.main,g.hands,None,'short')
    elif g.setup==1 and g.count==g.n2 and not g.flag:
        pre3close = attribute_history(g.code,3,'1d','close').close.values[0]
        pre1high = attribute_history(g.code,1,'1d','high').high.values[0]
        if pre1high < pre3close:
            print('做多信号----------------')
            g.flag = 1
            g.price = last
            g.p = last
            g.hold = g.main
            g.trend = 1
            order(g.main,g.hands,None,'long')
    if g.setup==-1 and g.flag==1 and g.trend == 1:
        if g.price/last >1.05 or g.price/last <0.95:
            
            if g.price/last >1.05:
                print('顺势空头止盈')
            else:
                print('顺势空头止损')
            g.price = last
            g.p = last
            reverse_posi()
            
    elif g.setup==1 and g.flag==1 and g.trend == 1:
        if last/g.price >1.05 or last/g.price <0.95:
            order_target(g.hold,0,None,'long')
            if last/g.price >1.05:
                print('顺势多头止盈')
            else:
                print('顺势多头止损')
            g.price = last
            g.p = last
            reverse_posi()

    if g.setup==1 and g.flag==1 and g.trend == -1:
        if g.price>last:
            g.price = last
        elif g.price < 0.9*last or g.p > 1.2*last:
            
        # if g.price/last >1.15 or g.price/last <0.85:
            order_target(g.hold,0,None,'long')
            if g.p > 1.2*last:
                print('反转空头止盈')
            else:
                print('反转空头止损')
                g.lc = True
            g.trend = 0 
            g.price = 0
            g.p = 0
            g.setup = 0
            g.setup_high = 0
            g.hold = ''
            g.count = 0
            g.flag = 0
    elif g.setup==-1 and g.flag==1 and g.trend == -1:
        if g.price < last:
            g.price = last
        elif g.price > 1.2*last or g.p < 0.8*last:
            
        # if last/g.price >1.15 or last/g.price <0.85:
            order_target(g.hold,0,None,'short')
            if g.p < 0.9*last:
                print('反转多头止盈')
            else:
                print('反转多头止损')
                g.lc = True
            g.trend = 0
            g.price = 0
            g.p = 0
            g.setup = 0
            g.setup_low = 0
            g.hold = ''
            g.count = 0
            g.flag = 0            
## 收盘后运行函数
def after_market_close(context):
    calc_setup()
    # print(g.count)

def reverse_posi():
    if g.setup==-1:
        print('空头反手')
        order_target(g.hold,0,None,'short')
        order(g.hold,g.hands,None,'long')
        g.trend = -1
        
    elif g.setup==1:
        print('多头反手')
        order_target(g.hold,0,None,'long')
        order(g.hold,g.hands,None,'short')
        g.trend = -1

    
def calc_setup():
    close = get_price(g.code,end_date=g.today,count=g.n1+5,fields='close')
    diff4 = close.diff(4).dropna().values
    first = g.setup
    #setup
    if (diff4[:-1]<0).all() and diff4[-1]>0 and not g.setup: #下降setup
        g.setup = -1
        high = get_price(g.code,end_date=g.today,count=g.n1,fields='high').values.max()
        g.setup_high = high
    elif (diff4[:-1]>0).all() and diff4[-1]<0 and not g.setup: #上升setup
        g.setup = 1
        low = get_price(g.code,end_date=g.today,count=g.n1,fields='low').values.min()
        g.setup_low = low
        
    #count
    if g.setup == -1 and g.count!=g.n2:
        pre2low = get_price(g.code,end_date=g.today,count=3,fields='low').values[0]
        if close.values[-1]<pre2low:
            g.count+=1
            print('下跌setup完成，count加1，当前数量：【{}】'.format(g.count))
    elif g.setup == 1 and g.count!=g.n2:
        pre2high = get_price(g.code,end_date=g.today,count=3,fields='high').values[0]
        if close.values[-1]>pre2high:
            g.count+=1
            print('上升setup完成，count加1，当前数量：【{}】'.format(g.count))
    
    
    
    #cancel    
    if g.setup==-1 and g.count!=g.n2:
        info = '下跌setup完成，'
        if close.values[-1] > g.setup_high:
            info += '当日收盘价大于setup中的最高价，停止'
            g.setup = 0
            g.setup_high = 0
            g.count = 0
            print(info)
        elif (diff4>0).all():
            info += '出现反向setup，优先新setup'
            g.setup = 1
            g.count = 0
            g.setup_high = 0
            low = get_price(g.code,end_date=g.today,count=g.n1,fields='low').values.min()
            g.setup_low = low
            print(info)
        elif not first and (diff4<0).all():
            info += '出现同向setup，重新计数'
            g.count = 0
            print(info)
    elif g.setup==1 and g.count!=g.n2:
        info = '上升setup完成，'
        if close.values[-1] < g.setup_low:
            info += '当日收盘价小于setup中最低价，停止'
            g.setup = 0
            g.setup_low = 0
            g.count = 0
            print(info)
        elif (diff4<0).all():
            info += '出现反向setup，优先新setup'
            g.setup = -1
            g.count = 0
            g.setup_low = 0
            high = get_price(g.code,end_date=g.today,count=g.n1,fields='high').values.max()
            g.setup_high = high
            print(info)
        elif not first and (diff4>0).all():
            info += '出现同向setup，重新计数'
            g.count = 0
            print(info)
        
def calc_hands(context):
    money = context.portfolio.total_value
    price = attribute_history(g.code,1,'1d','close').close.values[0]
    hands = int(money/0.15*0.5/price/300)
    return hands














