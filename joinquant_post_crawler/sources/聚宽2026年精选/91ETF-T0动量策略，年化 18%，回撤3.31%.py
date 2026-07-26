# 克隆自聚宽文章：https://www.joinquant.com/post/47374
# 标题：ETF-T0动量策略，年化 18%，回撤3.31%
# 作者：127.0.0.1

# 导入函数库
from jqdata import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('513030.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之一，卖出时佣金万分之一
    set_order_cost(OrderCost(close_tax=0, open_commission=0.00005, close_commission=0.00005, min_commission=0.1), type='fund')
    set_slippage(FixedSlippage(0.001))
    #时间区间(2021.08.01,2023.10.31)
    #2020.06.30 德国SAX30
    g.security1 = '513030.XSHG'
    #昨日收盘价
    g.yclose = 1
    #今日开盘价
    g.open = 1
    #最低高开
    g.thresholdMin = 0.003
    #最高高开
    g.thresholdMax = 0.5
    
    # 开盘前运行
    run_daily(before_market_open, time='before_open') 
    # 开盘时运行，判断是否买卖
    run_daily(market_open, time='9:30')
    # 收盘前一分钟运行
    run_daily(after_market_close, time='14:59')
    
    # 收盘后运行
    run_daily(after_market_close2, time='15:05')
## 开盘前运行函数     
def before_market_open(context):
    #计算昨日收盘价、最高价、最低价
    #log.info(str('开盘前 '+str(context.current_dt.time())))
    pass
## 开盘时运行函数
def market_open(context):
    
    #log.info("当前时间 : %s" % (context.current_dt.time()))
    #根据开盘价判断是否买入
    #获取当日开盘价
    current_data = get_current_data()
    g.open = current_data[g.security1].day_open
    #获取昨日收盘价
    yesterday = attribute_history(g.security1, 1, unit='1d',fields=['open', 'close', 'high', 'low'],df=False)
    g.yclose = yesterday['close'][-1]

    if((g.open - g.yclose >= g.thresholdMin) and (g.open - g.yclose <= g.thresholdMax)):
        order_value( g.security1, context.portfolio.available_cash)
    pass
## 收盘前一分钟运行
def after_market_close(context):
    #获取持仓
    positions = context.portfolio.positions
    #持仓不为空
    if len(positions) > 0:
        order_target(g.security1, 0)
    pass
## 收盘后运行
def after_market_close2(context):
    #log.info(str('收盘后 :'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    if(len(trades) > 0):
        log.info("昨日收盘价 : " +str(g.yclose) + "，今日开盘价：" + str(g.open) )
        for _trade in trades.values():
            log.info('成交记录：'+str(_trade))
        log.info("一天结束，余额：" + str(round(context.portfolio.available_cash,0)) +
        "，总值：" + str(round(context.portfolio.total_value,0)) +
        "，收益：" + str(round(context.portfolio.total_value - context.portfolio.starting_cash,0)))
        log.info('##############################################################')
    else:
        log.info("今日无交易！！！！！！！！")
    pass
