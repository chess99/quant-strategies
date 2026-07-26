# 克隆自聚宽文章：https://www.joinquant.com/post/30028
# 标题：【股指期货】收盘折溢价策略
# 作者：魔术先生

# 导入函数库
from jqdata import *

## 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    set_option('avoid_future_data',True)
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    g.thresh = 0
    g.flag = ''
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
    run_daily( close_position, time='10:00', reference_security='IF8888.CCFX')
    run_daily( open_position, time='14:59',reference_security='IF8888.CCFX')
      # 收盘后运行
    run_daily( after_market_close, time='15:30', reference_security='IF8888.CCFX')


## 开盘前运行函数
def before_market_open(context):
    g.main = get_dominant_future('IF')

def close_position(context):
    code = context.portfolio.positions.keys()
    for c in code:
        order_target(c,0,None,g.flag)
        g.flag = ''
    
def open_position(context):
    cash = context.portfolio.available_cash
    qty = int(cash/400000) # 50w开一手
    df = attribute_history(g.main,59,'1m',['close','volume'])
    df.volume /= df.volume.sum()
    settle = (df.close*df.volume).sum()
    close = df.close[-1]
    
    if close < settle*(1-g.thresh/1000):
        order(g.main,qty)
        g.flag = 'long'

## 开盘时运行函数
def market_open(context):
    return
    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))

    ## 交易

    # 当月合约
    IF_current_month = g.IF_current_month
    # 下季合约
    IF_next_quarter = g.IF_next_quarter

    # 合约列表
    # 当月合约价格
    IF_current_month_close = get_bars(IF_current_month, count=1, unit='1d', fields=['close'])["close"]
    # 下季合约价格
    # IF_next_quarter_close = hist[IF_next_quarter][0]
    IF_next_quarter_close = get_bars(IF_next_quarter, count=1, unit='1d', fields=['close'])["close"]
    print(IF_current_month_close)
    print(IF_next_quarter_close)
    # 计算差值
    CZ = IF_current_month_close - IF_next_quarter_close

    # 获取当月合约交割日期
    end_data = get_CCFX_end_date(IF_current_month)

    # 判断差值大于80，且空仓，则做空当月合约、做多下季合约；当月合约交割日当天不开仓
    if (CZ > 80):
        if (context.current_dt.date() == end_data):
            # return
            pass
        else:
            if (len(context.portfolio.short_positions) == 0) and (len(context.portfolio.long_positions) == 0):
                log.info('开仓---差值：', CZ)
                # 做空1手当月合约
                order(IF_current_month, 1, side='short')
                # 做多1手下季合约
                order(IF_next_quarter, 1, side='long')
    # 如有持仓，并且基差缩小至70内，则平仓
    if (CZ < 70):
        if(len(context.portfolio.short_positions) > 0) and (len(context.portfolio.long_positions) > 0):
            log.info('平仓---差值：', CZ)
            # 平仓当月合约
            order_target(IF_current_month, 0, side='short')
            # 平仓下季合约
            order_target(IF_next_quarter, 0, side='long')

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
