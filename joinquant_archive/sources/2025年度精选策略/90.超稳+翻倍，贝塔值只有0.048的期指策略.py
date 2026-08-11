# 克隆自聚宽文章：https://www.joinquant.com/post/30449
# 标题：超稳+翻倍，贝塔值只有0.048的期指策略
# 作者：老虎渔

# 克隆自聚宽文章：https://www.joinquant.com/post/30247
# 标题：【股指策略】PCR复合折溢价
# 作者：魔术先生

# 导入函数库
from jqdata import *
import talib as tl
import datetime as dt,numpy as np,pandas as pd

## 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000016.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    log.info('初始函数开始运行且全局只运行一次')
    g.leverage = 5 # 杠杆倍数
    g.max_net = context.portfolio.total_value
    g.pcr_list = []
    g.pcr_list_ = []
    g.multiplier = 300
    g.max_hold_days = 3 # 最大持仓天数限制
    g.margin = 0.1  # 保证金比率
    g.pcr_flag = 0
    g.hold_days = 0 # 记录持仓天数
    g.volume_thresh = False # 放量标志
    g.corr = np.nan
    g.corr_ = np.nan
    g.ind = np.nan
    g.ind_= np.nan
    g.hold_ins = '' # 持仓合约代码
    g.code = '510050.XSHG'
    g.d = 20
    g.corr = False
    g.corr_ = False
    g.trade_days = list(get_all_trade_days())
    g.thresh = 2
    ### 期货相关设定 ###
    # 设定账户为金融账户
    set_subportfolios([SubPortfolioConfig(cash=context.portfolio.starting_cash, type='index_futures')])
    # 期货类每笔交易时的手续费是：买入时万分之0.23,卖出时万分之0.23,平今仓为万分之23
    set_order_cost(OrderCost(open_commission=0.000023, close_commission=0.000023,close_today_commission=0.0023), type='index_futures')
    # 设定保证金比例
    set_option('futures_margin_rate', g.margin)
    # 设置期货交易的滑点
    set_slippage(StepRelatedSlippage(4))
    # 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'IF8888.CCFX'或'IH1602.CCFX'是一样的）
    # 注意：before_open/open/close/after_close等相对时间不可用于有夜盘的交易品种，有夜盘的交易品种请指定绝对时间（如9：30）
      # 开盘前运行
    run_daily( before_market_open, time='09:00', reference_security='IH8888.CCFX')
      # 开盘时运行
    run_daily( discount_close, time='09:40',reference_security='IH8888.CCFX')
    run_daily( market_open, time='14:30', reference_security='IH8888.CCFX')
    run_daily( discount, time='14:56', reference_security='IH8888.CCFX')
    
      # 收盘后运行
    run_daily( after_market_close, time='15:30', reference_security='IH8888.CCFX')


## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    # log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    g.ih = get_future_contracts('IH')[0]
    g.main = get_dominant_future('IF')
    g.hands = min(calc_hands(context),20)
    today = context.current_dt.date()
    nextday = g.trade_days[g.trade_days.index(today)+1]

    g.skip = True if (nextday-today).days>5 else False
    g.lc = False
    if g.pcr_flag != 0:
        g.hold_days+=1
## 开盘时运行函数
def market_open(context):
    # if str(context.current_dt.time()) == '10:00:00' and g.pcr_flag==0 and context.portfolio.positions:
    #     print('xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')
    #     print('                          仓位异常，平仓                         ')
    #     print('xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')
    #     closePosition(context)
    # if str(context.current_dt.time()) != '14:30:00':
    #     return
    # cancelOrder()
    lostControl(context)


    if g.hold_ins:
        end = get_security_info(g.hold_ins).end_date
        today = context.current_dt.date()
        if (pd.to_datetime(end)-pd.to_datetime(today)).days<2:
            print('到期平仓')
            g.pcr_flag = 0
            g.hold_ins = ''
            g.hold_days = 0
            closePosition(context)

    if g.lc or g.ind == -1:
        return
    
    if g.volume_thresh and g.pcr_flag != -1 and (g.ind>17 or g.ind_>17) and (g.corr or g.corr_):
        print('合成多头+++++')
        if g.pcr_flag == 0:
            g.pcr_flag = 1
        g.hold_days += 1
        order(g.ih,g.hands,None,'long')
        g.hold_ins = g.ih
    elif g.volume_thresh and g.pcr_flag != 1 and (g.ind<2 or g.ind_<2) and (g.corr or g.corr_):
        print('合成空头-----')
        if g.pcr_flag == 0:
            g.pcr_flag = -1
        g.hold_days += 1
        order(g.ih,g.hands,None,'short')
        g.hold_ins = g.ih

def discount(context):
    if g.pcr_flag != 0 or g.skip:
        return
    cash = context.portfolio.available_cash
    leverage = 2
    df = attribute_history(g.main,60,'1m',['close','volume'])
    df.volume /= df.volume.sum()
    settle = (df.close*df.volume).sum()
    close = df.close[-1]
    qty = min(int(cash/close/g.multiplier*leverage),20)
    
    date = str(context.current_dt.date())
    start = date+ ' 14:00:00'
    end = date+ ' 14:56:00'
    t = get_ticks(g.main,start_dt=start,end_dt=end,fields=['a1_v','b1_v'])
    buy = t['b1_v'].sum()
    sell = t['a1_v'].sum()
    imba = 2*(buy-sell)/(buy+sell)
    mul = 1
    if close > settle*(1+g.thresh/1000):
        mul+= 1/leverage
    if abs(imba)>0.5:
        mul+=1/leverage
    if -0.5<imba<-0.2:
        return
    # print(context.current_dt.time())
    # print(context.current_dt.date())
    # print(context.current_dt)
    # print(datetime.datetime.now())
    # print(g.code)
    # macd_dirc = get_macd_direct(g.code, context.current_dt, '60m') datetime.datetime.now()
    macd_dirc = get_macd_direct(g.code, context.current_dt, '1d')
    print('当前MACD运行方向为：%d' %macd_dirc )
    if macd_dirc>0:
        order(g.main,int(qty*mul))

def discount_close(context):
    if g.pcr_flag == 0:
        code = context.portfolio.positions.keys()
        for c in code:
            order_target(c,0)

## 收盘后运行函数
def after_market_close(context):
    g.max_net = max(g.max_net,context.portfolio.total_value)
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
        g.corr = a.corr(b)<-0.65
        g.corr_ = a.corr(b_)<-0.65

        g.spread = pd.Series(etf_return)*100 - pd.Series(g.pcr_list)
        g.spread_= pd.Series(etf_return)*100 - pd.Series(g.pcr_list_)
        try:
            g.ind = sorted(g.spread).index(g.spread.values[-1])
            g.ind_= sorted(g.spread_).index(g.spread_.values[-1])
        except:
            g.ind = np.nan
            g.ind_= np.nan
    
    szcz = get_price('399001.XSHE',end_date=today,fields='money',count=10,panel=False)/1e8
    szzz = get_price('000001.XSHG',end_date=today,fields='money',count=10,panel=False)/1e8
    vol = (szcz+szzz).money.astype(int).values.tolist()
    g.volume_thresh = True if sorted(vol,reverse=True).index(vol[-1])<2 else False
    
        
def calc_hands(context):
    money = context.portfolio.total_value
    price = attribute_history(g.ih,1,'1d','close').close.values[0]
    hands = int(money/price/g.multiplier*g.leverage)
    return hands
    
def lostControl(context):
    profit = np.nan
    net = context.portfolio.total_value
    
    if g.pcr_flag == 1:
        posi = context.portfolio.long_positions
        for p in posi.values():
            cost = p.avg_cost
            now = p.price
            profit = (now - cost)*g.multiplier*g.hands
        # now = get_current_tick(g.ih).current
    elif g.pcr_flag == -1:
        posi = context.portfolio.short_positions
        for p in posi.values():
            cost = p.avg_cost
            now = p.price
            profit = (cost - now)*g.multiplier*g.hands
    if net<0.9*g.max_net:
        print('止损---------------')
        g.hold_days = 0
        g.max_net = context.portfolio.total_value
        g.pcr_flag = 0
        g.hold_ins = '' 
        g.lc = True
        closePosition(context)
    elif profit/net > 0.2:
        g.hold_days = 0
        print('止盈---------------')
        g.pcr_flag = 0
        g.hold_ins = ''
        g.lc = True
        closePosition(context)
    elif g.hold_days>=g.max_hold_days:
        g.hold_days = 0
        print('持仓天数达到最大限制，平仓---------------')
        g.pcr_flag = 0
        g.hold_ins = ''
        g.lc = True
        closePosition(context)

def closePosition(context):
    print('------------------------------执行平仓函数-------------------------------------')
    if g.pcr_flag == 1:
        long_posi = context.portfolio.long_positions
        for p in long_posi.values():
            s = p.security
            order_target(s,0,None,'long')
    elif g.pcr_flag == -1:
        short_posi = context.portfolio.short_positions
        for p in short_posi.values():
            s = p.security
            order_target(s,0,None,'short')
    elif g.pcr_flag == 0:
        long_posi = context.portfolio.long_positions
        for p in long_posi.values():
            s = p.security
            order_target(s,0,None,'long')
        short_posi = context.portfolio.short_positions
        for p in short_posi.values():
            s = p.security
            order_target(s,0,None,'short')
            
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
    
################# 获取macd指示的运行方向#######################################
# MACD 公用函数
def MACD(close, fastperiod, slowperiod, signalperiod):
    macd_diff, macd_dea, macd = tl.MACDEXT(close, fastperiod=fastperiod, fastmatype=1, slowperiod=slowperiod,
                                           slowmatype=1, signalperiod=signalperiod, signalmatype=1)
    macd = macd * 2
    # 去掉空值行　也可以不去，
    # macd_diff = macd_diff.dropna().reset_index(drop=True)
    # macd_dea = macd_dea.dropna().reset_index(drop=True)
    # macd = macd.dropna().reset_index(drop=True) * 2　　# 主意是否要乘2
    # macd = macd.dropna().reset_index(drop=True)       # 主意是否要乘2

    return macd_diff, macd_dea, macd  # 返回series类型
#     return macd_diff.values, macd_dea.values, macd.values  # 返回ndarray类型


# 查寻一个时间段内某标的的macd信息
def get_macd(stock, count, end_date, unit):
    data = get_bars(security=stock, count=count, unit=unit,
                       include_now=True,
                       end_dt=end_date, fq_ref_date=None)
    close = data['close']
    # open = data['open']
    # high = data['high']
    # low = data['low']
    return MACD(close, 12, 26, 9)
    
# 获取macd指示的运行方向    
def get_macd_direct(stock, end_date, unit):
    macd_diff, macd_dea, macd_list = get_macd(stock, 100, end_date, unit)  # 默认取100个数据用于计算  unit周期支持 '1d','60m','5m'

    if macd_list[-1] >= macd_list[-2]:
        if macd_list[-1] > 0:
            return 2
        else:
            return 1
    else:
        if macd_list[-1] > 0:
            return -1
        else:
            return -2


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
