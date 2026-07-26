# 克隆自聚宽文章：https://www.joinquant.com/post/40118
# 标题：开盘幅度决定日内方向
# 作者：ZWK123

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
    # log.set_level('order', 'error')
    
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    # 设置滑点
    set_slippage(FixedSlippage(0.00))
    # set_slippage(PriceRelatedSlippage(0.00246),type='stock')
    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
      # 开盘时运行
    run_daily(market_open, time='09:30:00', reference_security='000300.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')

## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))

    # 给微信发送消息（添加模拟交易，并绑定微信生效）
    # send_message('美好的一天~')

    # 要操作的股票：平安银行（g.为全局变量）
    g.security = '510180.XSHG'

## 开盘时运行函数
def market_open(context):
    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    data_close_300 = attribute_history('399300.XSHE', 1, unit='1d',fields=['close'],df=True)['close'][0]
    data_close_303 = attribute_history('399303.XSHE', 1, unit='1d',fields=['close'],df=True)['close'][0]
    current_data = get_current_data()
    data_open_300 = current_data['399300.XSHE'].day_open
    data_open_303 = current_data['399303.XSHE'].day_open
    fudu_300 = data_open_300/data_close_300
    fudu_303 = data_open_303/data_close_303
    ava_cash = context.portfolio.available_cash
    position = context.portfolio.long_positions
    if (fudu_300 > fudu_303 or fudu_300 > 1) and not position:
        order_value(g.security, value=ava_cash,side='long')
        print(current_data['510180.XSHG'].day_open)
        print('开多')
    elif fudu_300 < fudu_303 and fudu_300 < 1 and position:
        print(current_data['510180.XSHG'].day_open)
        order_target_value(g.security, 0)
        print('平多')

## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    log.info('一天结束')
    log.info('##############################################################')
