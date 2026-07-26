# 克隆自聚宽文章：https://www.joinquant.com/post/30772
# 标题：北向资金股票轮动-优质策略可直接实盘
# 作者：Funine

from jqdata import *
import pandas as pd
import talib

def initialize(context):
    set_params()
    #
    set_option("avoid_future_data",True)
    set_option('use_real_price', True)  # 用真实价格交易
    set_benchmark('000300.XSHG')
    log.set_level('order', 'error')
    #
    # 将滑点设置为0
    #set_slippage(FixedSlippage(0.00))
    # 手续费: 采用系统默认设置 
    # set_order_cost(OrderCost(close_tax=0.00, open_commission=0.0001, close_commission=0.0001, min_commission=5),
    #               type='stock')

    # 11:30 计算大盘信号
    run_daily(get_signal, time='9:30')
    # 获取北向资金
    run_daily(trade,time='8:30')

# 1 设置参数
def set_params():
    g.use_dynamic_target_market = True  # 是否动态改变大盘热度参考指标
    # g.target_market = '000300.XSHG'
    g.target_market = '000300.XSHG'
    g.empty_keep_stock = '511880.XSHG'  # 闲时买入的标的
    # g.empty_keep_stock = '601318.XSHG'#闲时买入的标的
    g.signal = 'BUY'  # 交易信号初始化
    g.north_money = 0
    g.max_stock_count = 15
    #
    g.buy = []  # 购买股票列表
    
# 每日交易时
def ETFtrade(context):
    if g.signal == 'CLEAR':
        for stock in context.portfolio.positions:
            if stock == g.empty_keep_stock:
                continue
            log.info("清仓: %s" % stock)
            order_target(stock, 0)
    elif g.signal == 'BUY':
        if g.empty_keep_stock in context.portfolio.positions:
            order_target(g.empty_keep_stock, 0)
        #
        holdings = set(context.portfolio.positions.keys())  # 现在持仓的
        targets = set(g.buy)  # 想买的目标
        #
        # 1. 卖出不在targets中的
        sells = holdings - targets
        for code in sells:
            log.info("卖出: %s" % code)
            order_target(code, 0)
        #
        ratio = len(targets)
        if ratio>0:
            cash = context.portfolio.total_value / ratio
            # 2. 交集部分调仓
            adjusts = holdings & targets
            for code in adjusts:
                # 手续费最低5元，只有交易5000元以上时，交易成本才会低于千分之一，才去调仓
                if abs(cash - context.portfolio.positions[code].value) > 5000:  
                    log.info('调仓: %s' % code)
                    order_target_value(code, cash)
            # 3. 新的，买入
            purchases = targets - holdings
            for code in purchases:
                log.info('买入: %s' % code)
                order_target_value(code, cash)
            #
            current_returns = 100 * context.portfolio.returns
            log.info("当前收益：%.2f%%，当前持仓: %s", current_returns, list(context.portfolio.positions.keys()))

    if len(context.portfolio.positions) == 0:
        order_target_value(g.empty_keep_stock, context.portfolio.available_cash)
#计算北向资金
def trade(context):
    today = context.current_dt
    # print(today.date(),'@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@')
    n_sh = finance.run_query(query(finance.STK_ML_QUOTA).filter(finance.STK_ML_QUOTA.day < today.date(),
                                                                finance.STK_ML_QUOTA.link_id == 310001).order_by(
        finance.STK_ML_QUOTA.day.desc()).limit(10))
    n_sz = finance.run_query(query(finance.STK_ML_QUOTA).filter(finance.STK_ML_QUOTA.day < today.date(),
                                                                finance.STK_ML_QUOTA.link_id == 310002).order_by(
        finance.STK_ML_QUOTA.day.desc()).limit(10))
    total_net_in = 0
    for i in range(0, 3):
        sh_in = n_sh['buy_amount'][i] - n_sh['sell_amount'][i]
        sz_in = n_sz['buy_amount'][i] - n_sz['sell_amount'][i]
        amount = sh_in + sz_in
        total_net_in += amount
    g.north_money = total_net_in
    out = 0
    if g.north_money>-10:
        out = -10-g.north_money
        send_message("近2日北向资金流入"+str(round(g.north_money,1))+",明日北向资金流出"+str(round(out,1))+"时,卖出\n", channel='weixin')
    else:
        out = -10-g.north_money
        send_message("近2日北向资金流入"+str(round(g.north_money,1))+",明日北向资金流入"+str(round(out,1))+"时,买进\n", channel='weixin')
    log.info("近2日北向资金流入%s,明日北向资金流入或流出%s,买进或卖出\n"%(round(g.north_money,1),round(out,1)))

# 获取信号
def get_signal(context):
    record(north_money=round(g.north_money,1))
    
    result = calc_change(context)
    
    if g.north_money < -10:
        log.info("依据北向资金流入%s\n"%(round(g.north_money,1)))
        g.signal = 'CLEAR'
        ETFtrade(context)
        return

    # 大盘符合要求， 有基金品种也符合要求，买
    g.buy = result
    log.info("交易信号:持有 %s" % g.buy)
    g.signal = 'BUY'
    ETFtrade(context)
    return

def calc_change(context):
    table = finance.STK_HK_HOLD_INFO
    q = query(table.day, table.name, table.code, table.share_ratio)\
        .filter(table.link_id.in_(['310001', '310002']),
                table.day.in_([context.previous_date]))
    df = finance.run_query(q)
    df = df.sort_values(by='share_ratio',ascending=False)
    result = []   
    for se in df['code'].values:
        # if se.startswith('300'):
        #     continue
        if len(result)<g.max_stock_count:
            result.append(se)
        else:
            break
    return result
