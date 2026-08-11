# 克隆自聚宽文章：https://www.joinquant.com/post/30350
# 标题：基于动量和反转效应的沪深300成分股策略
# 作者：糯米糍本糍

# 导入函数库
from jqdata import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')

    ### 股票相关设定 ###
    g.days_fzxy = 0
    g.weeks_fzxy = 0
    g.flag_fzxy = True
    g.flag_dlxy = True
    g.flag_dlxy_ex = False
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
    # 开盘前运行
    run_daily(cal_date_fzxy, time='before_open', reference_security='000300.XSHG')
    run_daily(handle, time='open', reference_security='000300.XSHG')
   

## 开盘前运行函数
def cal_date_fzxy(context):
    if g.days_fzxy < 5:
        g.days_fzxy = g.days_fzxy + 1
    elif g.days_fzxy == 5:
        g.days_fzxy = 0
        g.weeks_fzxy = g.weeks_fzxy + 1
    if g.weeks_fzxy == 30:
        g.weeks_fzxy = 0
        g.flag_fzxy = True
    


def handle(context):
    handle_fzxy(context)
    # handle_dlxy(context)


## 开盘时运行函数
def handle_fzxy(context):
    # 1.反转效应
    if g.flag_fzxy == True:
        g.flag_fzxy = False
        universe = get_index_stocks('000300.XSHG')
        stock_data = history(count=30, unit='5d', field='close', security_list=universe, df=True)
        stock_data = stock_data.T
        stock_data['ret'] = NaN
        for stock in universe:
            ret = stock_data.loc[stock][-2] / stock_data.loc[stock][1] - 1
            stock_data['ret'][stock] = ret
            
        # 反转选股列表
        dl_list = list(stock_data.sort_values('ret')[:25].index)
        # 分配资金为25份
        cash = context.portfolio.total_value / 25
        
        log.info('开始调仓')
        # 卖出持仓股
        list_position=context.portfolio.positions.keys()
        if len(list_position) > 0:
            for stock_to_sell in list_position:
                order_target(stock_to_sell, 0)
        for stock_to_buy in dl_list:
            order_value(stock_to_buy, cash)
            
def handle_dlxy(context):            
    # 2.动量效应
    if g.flag_dlxy == True:
        g.flag_dlxy = False
        g.flag_dlxy_ex = True
        universe = get_index_stocks('000300.XSHG')
        stock_data = history(count=14, unit='5d', field='close', security_list=universe, df=True)
        stock_data = stock_data.T
        stock_data['ret'] = NaN
        for stock in universe:
            ret = stock_data.loc[stock][-2] / stock_data.loc[stock][1] - 1
            stock_data['ret'][stock] = ret
        # 动量效应选股
        g.dl_list = list(stock_data.sort_values('ret')[-30:].index)
        # 卖出持仓股
        list_position=context.portfolio.positions.keys()
        if len(list_position) > 0:
                for stock_to_sell in list_position:
                    order_target(stock_to_sell, 0)
                    log.info('进入新一轮调仓周期')
        # 分配资金为30份，同时进行资金管理，再分为14份，每周投一份
        g.cash_ex = context.portfolio.total_value / 30 / 14
        g.days_dlxy = 0
        g.weeks_dlxy = 0
        
    # 每周进行买入
    if g.flag_dlxy_ex == True:
        if g.days_dlxy < 5:
            g.days_dlxy = g.days_dlxy + 1
        elif g.days_dlxy == 5:
            g.days_dlxy = 0
            g.weeks_dlxy = g.weeks_dlxy + 1
            for stock_to_buy in g.dl_list:
                order_value(stock_to_buy, g.cash_ex)
                log.info('投入 1/14 的资金')
        if g.weeks_dlxy == 14:
            g.weeks_dlxy = 0
            g.flag_dlxy = True
            

        

## 收盘后运行函数
def after_market_close(context):
    # log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    # #得到当天所有成交记录
    # trades = get_trades()
    # for _trade in trades.values():
    #     log.info('成交记录：'+str(_trade))
    # log.info('一天结束')
    # log.info('##############################################################')
    pass
