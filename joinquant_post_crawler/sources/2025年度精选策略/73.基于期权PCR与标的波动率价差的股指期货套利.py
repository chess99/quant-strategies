# 克隆自聚宽文章：https://www.joinquant.com/post/27664
# 标题：基于期权PCR与标的波动率价差的股指期货套利
# 作者：魔术先生

# 导入函数库
from jqdata import *
import datetime as dt,numpy as np,pandas as pd

## 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000016.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    log.info('初始函数开始运行且全局只运行一次')
    g.pcr_list = []
    g.pcr_list_ = []
    g.multiplier = 300
    g.margin = 0.15
    g.pcr_flag = 0
    g.corr = np.nan
    g.corr_ = np.nan
    g.ind = np.nan
    g.ind_= np.nan
    g.count = 0    # 记录开平手数
    g.hold_ins = ''
    g.code = '510050.XSHG'
    g.d = 20
    g.corr = False
    g.corr_ = False

    ### 期货相关设定 ###
    # 设定账户为金融账户
    set_subportfolios([SubPortfolioConfig(cash=context.portfolio.starting_cash, type='index_futures')])
    # 期货类每笔交易时的手续费是：买入时万分之0.23,卖出时万分之0.23,平今仓为万分之23
    set_order_cost(OrderCost(open_commission=0.000023, close_commission=0.000023,close_today_commission=0.0023), type='index_futures')
    # 设定保证金比例
    set_option('futures_margin_rate', g.margin)

    # 设置期货交易的滑点
    set_slippage(StepRelatedSlippage(2))
    # 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'IF8888.CCFX'或'IH1602.CCFX'是一样的）
    # 注意：before_open/open/close/after_close等相对时间不可用于有夜盘的交易品种，有夜盘的交易品种请指定绝对时间（如9：30）
      # 开盘前运行
    run_daily( before_market_open, time='09:00', reference_security='IH8888.CCFX')
      # 开盘时运行
    run_daily( market_open, time='every_bar', reference_security='IH8888.CCFX')
      # 收盘后运行
    run_daily( after_market_close, time='15:30', reference_security='IH8888.CCFX')


## 开盘前运行函数
def before_market_open(context):

    # 输出运行时间
    # log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
      # 获取当月沪深300指数期货合约
    g.ih = get_future_contracts('IH')[0]
    g.hands = min(calc_hands(context),50)
    g.lc = False
## 开盘时运行函数
def market_open(context):
    if str(context.current_dt.time()) == '10:00:00' and g.pcr_flag==0 and context.portfolio.positions:
        print('xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')
        print('                          仓位异常，平仓                         ')
        print('xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')
        closePosition(context)
    if str(context.current_dt.time()) < '14:30:00':
        return
    cancelOrder()
    lostControl(context)
    if g.lc or g.ind == -1:
        return

    if g.hold_ins:
        end = get_security_info(g.hold_ins).end_date
        today = context.current_dt.date()
        if (pd.to_datetime(end)-pd.to_datetime(today)).days<2:
            print('到期平仓')
            if g.count == 1:
                g.pcr_flag = 0
                g.hold_ins = ''
            g.count -= 1
            closePosition(context)
            
    # print(info.end_date)
    # return
    # log.info('函数运行时间(market_open):'+str(context.current_dt.time()))

    if g.pcr_flag == 1 and (g.ind<4 or g.ind_<4) and g.count>0:
        print('平仓多头')
        if g.count == 1:
            g.pcr_flag = 0
        g.count -= 1
        closePosition(context)
        g.hold_ins = ''
    elif g.pcr_flag == -1 and (g.ind > 15 or g.ind_>15) and g.count>0:
        print('平仓空头')
        if g.count == 1:
            g.pcr_flag = 0
        g.count -= 1
        closePosition(context)
        g.hold_ins = ''
    
    if g.pcr_flag != -1 and (g.ind>18 or g.ind_>18) and (g.corr or g.corr_) and g.count<g.hands:
        print('合成多头+++++')
        if g.pcr_flag == 0:
            g.pcr_flag = 1
        g.count += 2
        order(g.ih,2,None,'long')
        g.hold_ins = g.ih
    elif g.pcr_flag != 1 and (g.ind<1 or g.ind_<1) and (g.corr or g.corr_) and g.count<g.hands:
        print('合成空头-----')
        if g.pcr_flag == 0:
            g.pcr_flag = -1
        g.count += 2
        order(g.ih,2,None,'short')
        g.hold_ins = g.ih

## 收盘后运行函数
def after_market_close(context):
    # posi = context.portfolio.long_positions
    # print(posi)
    # return
    # log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    today = context.current_dt.date()
    df = opt.run_query(query(opt.OPT_CONTRACT_INFO).filter(
    opt.OPT_CONTRACT_INFO.underlying_symbol==g.code,
    opt.OPT_CONTRACT_INFO.list_date<today,
    opt.OPT_CONTRACT_INFO.expire_date>today))
    call = df[df['contract_type']=='CO'].code.tolist()
    put  = df[df['contract_type']=='PO'].code.tolist()

    call_money = get_price(call,end_date=today ,fields='money',count=1,panel=False)
    call_volume = get_price(call,end_date=today ,fields='volume',count=1,panel=False)
    put_money = get_price(put,end_date=today,fields='money',count=1,panel=False)
    put_volume = get_price(put,end_date=today,fields='volume',count=1,panel=False)
    pcr = round(put_money.money.sum()/call_money.money.sum(),4)
    pcr_= round(put_volume.volume.sum()/call_volume.volume.sum(),4)
    g.pcr_list.append(pcr)
    g.pcr_list_.append(pcr_)
    etf_return = get_price(g.code,end_date=today,fields='close',count=21,panel=False).close.pct_change().dropna().tolist()
    if len(g.pcr_list)>20:
        g.pcr_list = g.pcr_list[-20:]
        g.pcr_list_= g.pcr_list_[-20:]
        a = pd.Series(etf_return[-10:])
        b = pd.Series(g.pcr_list[-10:])
        b_= pd.Series(g.pcr_list_[-10:])
        g.corr = a.corr(b)<-0.75
        g.corr_ = a.corr(b_)<-0.75

        g.spread = pd.Series(etf_return)*100 - pd.Series(g.pcr_list)
        g.spread_= pd.Series(etf_return)*100 - pd.Series(g.pcr_list_)
        try:
            g.ind = sorted(g.spread).index(g.spread.values[-1])
            g.ind_= sorted(g.spread_).index(g.spread_.values[-1])
        except:
            g.ind = np.nan
            g.ind_= np.nan
    
        # print(g.ind)
        # print(g.ind_)
        # print(a.corr(b))
        # print(a.corr(b_))

    
    # 得到当天所有成交记录
    # trades = get_trades()
    # for _trade in trades.values():
    #     log.info('成交记录：'+str(_trade))
    # log.info('一天结束')
    # log.info('##############################################################')

        
def calc_hands(context):
    money = context.portfolio.total_value
    price = attribute_history(g.code,1,'1d','close').close.values[0]
    hands = int(money/g.margin*0.8/price/g.multiplier)
    return hands
    
def lostControl(context):
    profit = np.nan
    if g.pcr_flag == 1:
        posi = context.portfolio.long_positions
        for p in posi.values():
            cost = p.avg_cost
            now = p.price
            profit = (now - cost)*300
        # now = get_current_tick(g.ih).current
    elif g.pcr_flag == -1:
        posi = context.portfolio.short_positions
        for p in posi.values():
            cost = p.avg_cost
            now = p.price
            profit = (cost - now)*300
    # print(profit)
    if profit < -20000:
        print('止损---------------')
        if g.count == 2:
            g.pcr_flag = 0
            g.hold_ins = '' 
        g.count -= 2
        g.lc = True
        closePosition(context)
    elif profit > 100000:
        print('止盈---------------')
        if g.count == 2:
            g.pcr_flag = 0
            g.hold_ins = ''
        g.count -= 2
        g.lc = True
        closePosition(context)


def closePosition(context):
    print('------------------------------执行平仓函数-------------------------------------')
    if g.pcr_flag == 1:
        long_posi = context.portfolio.long_positions
        for p in long_posi.values():
            s = p.security
            v = p.closeable_amount
            order(s,-2,None,'long')
    elif g.pcr_flag == -1:
        short_posi = context.portfolio.short_positions
        for p in short_posi.values():
            s = p.security
            v = p.closeable_amount
            order(s,-2,None,'short')
    elif g.pcr_flag == 0:
        long_posi = context.portfolio.long_positions
        for p in long_posi.values():
            s = p.security
            v = p.closeable_amount
            order(s,-v,None,'long')
        short_posi = context.portfolio.short_positions
        for p in short_posi.values():
            s = p.security
            v = p.closeable_amount
            order(s,-v,None,'short')
            
def cancelOrder():
    orders = get_open_orders()
    for o in orders:
        print(o)
        if o.action == 'close':
            g.count += 1
        else:
            g.count -= 1
        cancel_order(o)
        
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
