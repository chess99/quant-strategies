# 克隆自聚宽文章：https://www.joinquant.com/post/30310
# 标题：【股指策略】【研报复现】周内与日内结合CTA
# 作者：魔术先生

# 克隆自聚宽文章：https://www.joinquant.com/post/30310
# 标题：【股指策略】【研报复现】周内与日内结合CTA
# 作者：魔术先生

# 导入函数库
from jqdata import *

## 初始化函数，设定基准等等
def initialize(context):
    mkt = 2
    g.leverage = 3
    g.multiplier = 300
    if mkt == 50 or mkt==1:
        g.benchmark = '000016.XSHG'
        g.ins = 'IH'
    elif mkt == 300 or mkt==2:
        g.benchmark = '000300.XSHG'
        g.ins = 'IF'
    elif mkt == 500 or mkt==3:
        g.benchmark = '000905.XSHG'
        g.ins = 'IC'
        g.multiplier = 200
    set_benchmark(g.benchmark)
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    set_option('avoid_future_data',True)
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    g.trade_days = list(get_all_trade_days())
    g.flag = ''
    g.week_signal = '' # 周信号
    ### 期货相关设定 ###
    # 设定账户为金融账户
    set_subportfolios([SubPortfolioConfig(cash=context.portfolio.starting_cash, type='index_futures')])
    # 期货类每笔交易时的手续费是：买入时万分之0.23,卖出时万分之0.23,平今仓为万分之23
    set_order_cost(OrderCost(open_commission=0.000023, close_commission=0.000023,close_today_commission=0.000023), type='index_futures')
    # 设定保证金比例
    set_option('futures_margin_rate', 0.15)

    # 设置期货交易的滑点
    set_slippage(StepRelatedSlippage(4))
    # 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'IF8888.CCFX'或'IH1602.CCFX'是一样的）
    # 注意：before_open/open/close/after_close等相对时间不可用于有夜盘的交易品种，有夜盘的交易品种请指定绝对时间（如9：30）
      # 开盘前运行
    run_daily( before_market_open, time='09:00', reference_security='IF8888.CCFX')
      # 开盘时运行
    run_daily( on_close, time='10:00', reference_security='IF8888.CCFX')
    run_daily( on_open, time='14:59',reference_security='IF8888.CCFX')
      # 收盘后运行
    # run_daily( after_market_close, time='15:30', reference_security='IF8888.CCFX')


## 开盘前运行函数
def before_market_open(context):
    g.main = get_dominant_future(g.ins)
    today = context.current_dt.date()
    g.nextday = g.trade_days[g.trade_days.index(today)+1]

    g.skip = True if (g.nextday-today).days>3 else False   # 长假前空仓
    
def close_position(context):
    code = context.portfolio.positions.keys()
    g.flag = ''
    for c in code:
        order_target(c,0)
    code = context.portfolio.short_positions.keys()    
    for c in code:
        order_target(c,0,None,'short')
        
def reverse_position(context):
    posi = context.portfolio.positions
    for p in posi.values():
        code = p.security
        qty = p.total_amount
        order_target(code,0)
        # order(code,qty,None,'short')
        
def on_close(context):
    if g.flag == 'long' and g.week_signal == 'short':
        reverse_position(context)
        # g.flag == 'short'
        g.flag = ''
        
def on_open(context):
    if g.flag=='short':
        close_position(context)
    
    cash = context.portfolio.available_cash
    df = attribute_history(g.main,60,'1m',['close','volume'])
    future = df.close.values
    close_pre2 = attribute_history(g.benchmark,2,'1d','close').close.values[0]
    index = attribute_history(g.benchmark,15,'1m','close').close.values
    signal = 'long' if index[-1]>close_pre2 else 'short'
    weekday = g.nextday.weekday()
    if signal=='long' and weekday==0:  # 上涨市且下一交易日为周一做多
        g.week_signal = 'long'
    elif signal == 'short':   
        if weekday in [0,3]:    # 下跌市且下一交易日为周一或周四做空
            g.week_signal = 'short'
        elif weekday == 1:      # 周二做多
            g.week_signal = 'long'   

    df.volume /= df.volume.sum()
    settle = (df.close*df.volume).sum()
    close = df.close[-1]
    if g.skip:
        close_position(context)
        return
    
    qty = min(int(cash/close/g.multiplier*g.leverage),20)  # 上限20手
    
    date = str(context.current_dt.date())
    start = date+ ' 14:00:00'
    start2 = date+' 14:30:00'
    end = date+ ' 14:59:00'
    t = get_ticks(g.main,start_dt=start2,end_dt=end,fields=['a1_v','b1_v'])
    buy = t['b1_v'].sum()
    sell = t['a1_v'].sum()
    imba = 2*(buy-sell)/(buy+sell)
    
    f1 = 1 if settle>close else 0
    f2 = 1 if imba>0 else 0 
    f3 = 1 if (index[0]-index[-1])-(future[-15]-future[-1])<0 else 0
    
    if g.flag!='long' and ((f1+f2+f3)>1 or g.week_signal=='long'):
        g.flag = 'long'
        order(g.main,qty)
    elif g.flag=='long' and ~((f1+f2+f3)>1 or g.week_signal=='long'):
        close_position(context)
        

## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    # 得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    log.info('一天结束')
    log.info('##############################################################')

########################## 获取期货合约信息，请保留 #################################
# 获取金融期货合约到期日
def get_CCFX_end_date(future_code):
    # 获取金融期货合约到期日
    return get_security_info(future_code).end_date

