# 克隆自聚宽文章：https://www.joinquant.com/post/39272
# 标题：场内基金定投价值平均增强策略，年化30%+
# 作者：子匀

# 克隆自聚宽文章：https://www.joinquant.com/post/39137
# 原策略使用场外基金，随着场内ETF越来越丰富，改写成场内基金
# 为方便改为场外基金，保留场外基金交易的代码
# 回测的结束日期，应设置此月的最后一天,run_monthly(compute_profit, -1, time = 'close')
# 每天检查止赢，1. 赢利超过50%，最大回撤超过10%，则清仓  2.赢利超过80%，止盈
# 上涨50%后，下跌10%止赢后，如何操作？小牛市，即上轮最高点与最低点之差大于50%，不到90%，去半仓；
# 大于90%，则大牛市，去全仓。   
# 半仓止盈后，为方便计算，采用了先全仓卖出，再买回的方法

import jqdata
from jqlib.technical_analysis import *
import datetime as dt
import numpy as np
# import warnings
# warnings.filterwarnings('ignore')

def initialize(context): #用来写最开始要初始化的参数
    log.set_level('order', 'error')
    log.set_level('system', 'error')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)

    g.init_status = False      # 已经建仓 True  否则 False
    g.totalmoney = context.portfolio.available_cash

    # 《价值平均策略》中要规划目标资金和目标日期，在实际应用中，更多是根据行情完成投资目标退出

    # g.money = g.totalmoney/months   # 月平均投资金额
    g.money = g.totalmoney * 0.2 / 8    # 建仓时买入80%，余下20%分为8期
    print( '每期投资金额：%.2f' % g.money)
    # 不用的指数和ETF，可注释掉
    g.index = '000300.XSHG'     # 参考指数 沪深300
    g.security = '510300.XSHG'  #  300ETF 场内代码
    # g.security = '050002.OF'    # 场外基金用此代码代替，博时沪深300指数A

    g.index = '399006.XSHE'  #  创业板指
    g.security = '159915.XSHE' #创业板ETF

    g.index = '399324.XSHE'   # 深证红利
    g.security = '159905.XSHE'  #  深证红利ETF

    g.r = 0 #基金单位净值收益率
    g.cost = 0 #用来计算持有成本
    g.count = 0   # 购买交数 
    g.high  = 0.01   #   基金的最高净值
    g.down  = 0.01   #   基金当前回撤
    g.take_profit_flag = 0 #判断当月是否止盈
    g.last_month_dwjz = 0    #  月初的单位净值
    g.last_month_value = 0   # 月初的标的价值
    g.bought_price = 0         # 上次交易价格 这两个价格，用于最基本的策略，低不卖，高不买
    g.sold_price = 0           #  上次卖出价格
    g.new_dwjz = 0           # 最新单位净值
    g.take_profit_value = 0      # 止盈市值
    g.take_profit_days  = 0      # 止盈天数，中期止赢后，资金到账后，重新买入
    g.buy_avg_cost = 0            # 真实买入成本
    g.month_growth_rate = 1.005  # 每月价值增长额
    g.investments = np.array([])      # 每次投入金额，用于IRR计算回报率
    set_benchmark('000300.XSHG') #沪深300指数
    #设置基金申购赎回费用均为万分之三
    # set_order_cost(OrderCost(open_commission=0.0003, close_commission = 0.0003, min_commission=0), type='stock_fund')
    set_order_cost(OrderCost(close_tax=0.0, open_commission=0.0003, close_commission=0.0003, min_commission=1), type='fund')
    
    # 初始化场外基金仓位
    # set_subportfolios([SubPortfolioConfig(context.portfolio.cash, 'open_fund')])
    run_daily(init_position,  time = 'open')
    # run_monthly(before_trading, 1, time='open-30m') #每月第一个交易日开盘前输出一些数据，用做检查，可以注释掉
    run_daily(take_profit,  time = 'open') #每月第一个交易日开盘时运行止盈函数
    run_monthly(target_mv, 1, time = 'open+30m') #每月第一个交易日开盘后半小时按照平均市值策略申购基金
    # run_monthly(compute_value, 3, time = 'open+30m') #按照申购基金t+2到账，第三个交易日计算本月净值数据，给下个月使用
    run_monthly(compute_value, 2, time = 'open') #按上一天的收盘价，计算本月净值数据，给下个月使用

    run_monthly(compute_profit, -1, time = 'close')   # 最后一个月按IRR计算年化收益率，
#def handle_data(context, data): #用来写每天循环要做什么

def before_trading(context):
    log.info('当前持仓总市值(1st)%.2f'%context.portfolio.positions[g.security].value) # # 获取账户的标的价值，计算方法是: price * total_amount 
    log.info('当前持仓仓位(1st)%.2f'%context.portfolio.positions[g.security].total_amount)  #total_amount: 总仓位, 但不包括挂单冻结仓位

#  该内置定时函数，会在每天结束交易后被调用一次
def after_trading_end(context):
    if g.init_status == False : return

    if context.portfolio.positions[g.security].total_amount > 0:     # 持仓数量>0
        dwjz = context.portfolio.positions[g.security].price
        g.high = max(g.high,dwjz)
        g.down = 1 - dwjz/g.high
        
        if g.buy_avg_cost == 0 :
            avg_cost = context.portfolio.positions[g.security].avg_cost
        else :
            avg_cost = g.buy_avg_cost
        # log.info('日期：%s ，单位净值：%s ,平均持仓成本：%s' %(context.current_dt.date(),dwjz,avg_cost))
        g.r = 100*(dwjz/avg_cost - 1)
    elif context.portfolio.positions[g.security].total_amount == 0 :
        g.r = 0
        g.high = 0
    if g.take_profit_days > 0 : g.take_profit_days +=1
    record(return_rate = g.r)   # 回测环境/模拟专用API 画图函数

# 止盈
def take_profit(context):
    date_now = context.previous_date
    if g.r > 40  and g.down > 0.09:
        #基金净值收益达到40%以上并且最大回撤9%时，进行止盈赎回操作
        g.r = 1
        g.down = 0.01
        
        rate0 = max_increase(date_now)[0]
        log.info('当前持仓总市值(0.40止盈后)，基金净值最大增长：%s ，基金持仓成本：%s' %(rate0,context.portfolio.positions[g.security].avg_cost))
        take_profit_rate = 1     # 止盈比例   为计算方便，全部卖出，再考虑是否买入
        g.high = 0 
        g.buy_avg_cost = 0
        g.last_month_value =0 
        if rate0 > 90 :

            # g.take_profit_flag = 1      # 止盈标志
            g.init_status = False       # 等待建仓

        else :
            g.take_profit_days = 1
        amount = take_profit_rate * context.portfolio.positions[g.security].total_amount
        g.take_profit_value = take_profit_rate * context.portfolio.positions[g.security].value
        # redeem(g.security, amount)
        g.sold_price = 10000 
        g.bought_price = 0
        g.take_profit_value = get_cur_money(g.take_profit_value)  #  整手买卖
        order_value(g.security,-g.take_profit_value)
        g.investments = np.append(g.investments,g.take_profit_value)
        g.take_profit_flag = 1      # 止盈标志
        log.info('当前持仓总市值(0.40止盈后立刻)%.2f'%context.portfolio.positions[g.security].value)
        # log.info('当前持仓仓位(0.40止盈后立刻)%.2f'%context.portfolio.positions[g.security].total_amount)
    elif g.r > 100 or max_increase1y(date_now)>75:
        g.r = 1
        g.down = 0.01
        take_profit_rate = 1     # 止盈比例
        amount = take_profit_rate * context.portfolio.positions[g.security].total_amount
        g.take_profit_value = take_profit_rate * context.portfolio.positions[g.security].value
        g.take_profit_value = get_cur_money(g.take_profit_value)  #  整手买卖
        order_value(g.security,-g.take_profit_value)
        
        # redeem(g.security, amount)
        g.investments = np.append(g.investments,g.take_profit_value)
        g.take_profit_flag = 1      # 止盈标志
        g.init_status = False       # 等待建仓
        g.high = 0
        g.sold_price = 10000 
        g.bought_price = 0
        log.info('当前持仓总市值(全仓止盈后立刻)%.2f'%context.portfolio.positions[g.security].value)
        # log.info('当前持仓仓位(全仓止盈后立刻)%.2f'%context.portfolio.positions[g.security].total_amount)
        
#  止损 def stot_lost  价值平均策略，不止损

#  根据A股100为一手，整手交易规则，计算洽当的真实成交金额
def get_cur_money(money):
    cur_data = get_current_data()
    price = cur_data[g.security].last_price
    g.bought_price = price
    money = money*0.01//price * 100 * price #  整手买卖
    return money
    
#  建仓条件
def init_position(context):
    #  半仓止盈后，第二天买回
    if g.take_profit_days > 0 :
        g.take_profit_days = 0
        g.totalmoney = context.portfolio.available_cash
        g.money = g.totalmoney * 0.5 / 16    # 建仓时买入50%，余下50%分为16期
        # print( '每期投资金额：%.2f' % g.money)
        money = get_cur_money(g.totalmoney * 0.5)
        log.info('每期投资金额：%.2f，止盈后买入：%.2f' % ( g.money,money))
 
        # purchase(g.security,money)
        order_value(g.security,money)
        refresh_trade_price(context.current_dt,'buy')
        g.init_status = True 
        g.last_month_value = money * g.month_growth_rate   # 
        g.investments = np.append(g.investments,-money)     # np.append(arr, values,axis=None) 为原始array添加一些values 
        g.count = 1
        
    if g.init_status : return 
    date_now = context.previous_date

    rate1 = max_increase(date_now)[1]
    if rate1 < 0.318 :
        # min_now = round(min1 + (max0-min1) * 0.318,2)
        # print("建仓点位：%s ,建仓日期：%s" %(min_now,l0))
        g.totalmoney = context.portfolio.available_cash
        g.money = g.totalmoney * 0.2 / 10    # 建仓时买入80%，余下20%分为10期
        money = get_cur_money(g.totalmoney * 0.7)
        # purchase(g.security,money)
        order_value(g.security,money)
        # print( '每期投资金额：%.2f' % g.money)
        refresh_trade_price(context.current_dt,'buy')
        log.info(' 每期投资金额：%.2f，建仓买入：%.2f' % (  g.money,money))
        g.init_status = True 
        g.last_month_value = money * g.month_growth_rate   # 
        g.investments = np.append(g.investments,-money)     # np.append(arr, values,axis=None) 为原始array添加一些values 
        g.count = 1
        
        
#  基金交易     
def target_mv(context):
    if g.init_status == False : return
    cash = context.portfolio.available_cash
    value = context.portfolio.positions[g.security].value
    total_amount =  context.portfolio.positions[g.security].total_amount
    if total_amount>0:   # 持仓份额> 0 
        g.new_dwjz = value/total_amount
    
    if g.count == 0:    # 首次买入
        # purchase(g.security,g.money)     # 申购基金
        # g.investments = np.append(g.investments,-g.money)     # np.append(arr, values,axis=None) 为原始array添加一些values 
        g.count = 1
    elif g.count!=0 and g.take_profit_flag == 0 :
        #当月未止盈的情况下正常使用价值平均策略申购基金
        thismonth = g.money - (value - g.last_month_value)
        
        if thismonth > 0 and cash > 1000 and context.portfolio.positions[g.security].price < g.sold_price :
            #净值增长不够平均市值增长
            # 避免个别月度买入值过大，实证取5倍月值时，投资业绩变化不大
            if thismonth / g.money > 5 : thismonth = 5 * g.money 
            # 超过可用现金，则全部买完
            if thismonth > cash : thismonth = cash
            
            thismonth= get_cur_money(thismonth)
            log.info('当月净值：%s涨幅不够平均市值增长%s，应买入%s ' %(value,g.last_month_value,thismonth))
            # purchase(g.security,thismonth)
            order_value(g.security,thismonth) 
            refresh_trade_price(context.current_dt,'buy')
            g.investments = np.append(g.investments,-thismonth)
        #  当前价格高于平均持仓成本，并且涨幅高于本月净值增加值时，方才减仓
        elif thismonth <= 0 and context.portfolio.positions[g.security].price > context.portfolio.positions[g.security].avg_cost and context.portfolio.positions[g.security].price > g.bought_price :
            if -thismonth / g.money > 5 : thismonth = -5 * g.money
            # amount = -thismonth / context.portfolio.positions[g.security].price
            # redeem(g.security, amount )     # 净值增长超过目标市值增长，则赎回
            thismonth= get_cur_money(-thismonth)
            order_value(g.security,-thismonth) 
            refresh_trade_price(context.current_dt,'sell')
            g.bought_price = 0
            log.info('当月净值：%s涨幅超过市值增长%s，应卖出%s ' %(value,g.last_month_value,thismonth))
 
            g.investments = np.append(g.investments,thismonth)
    elif g.count!=0 and g.take_profit_flag == 1:
        # 止盈次月不调整仓位，如需调整仓位，打开以下代码即可
        #当月发生止盈情况的申购策略:申购额按照当前持仓数量*(当前单位净值-上月申购后单位净值)计算，扔遵循固定增值额度
        # thismonth = g.money - (g.new_dwjz-g.last_month_dwjz)*context.portfolio.positions[g.security].total_amount
        # if thismonth > 0:
        #     #净值增长不够平均市值增长
        #     log.info('当月净值涨幅不够平均市值增长222')
        #     purchase(g.security,thismonth)
        #     g.investments = np.append(g.investments,g.take_profit_value-thismonth)
        # elif thismonth <= 0:  #  
        #     g.investments = np.append(g.investments,g.take_profit_value)
        g.take_profit_flag = 0

#  T + 3 日，获取标的价值，单位净值    
def compute_value(context):
    if g.init_status == False : return

    g.last_month_value = context.portfolio.positions[g.security].value  * g.month_growth_rate
    if context.portfolio.positions[g.security].total_amount>0 :
        g.take_profit = context.portfolio.positions[g.security].value/context.portfolio.positions[g.security].total_amount
        # log.info('当前持仓总市值(4th)%.2f'%g.last_month_value)
        # log.info('当前持仓仓位(4th)%.2f'%context.portfolio.positions[g.security].total_amount)

def compute_profit(context):
    if g.init_status == False : return
    if context.run_params.end_date.year == context.current_dt.year and context.current_dt.month == context.run_params.end_date.month:
        g.investments = np.append(g.investments,context.portfolio.positions[g.security].value)
        irr = np.irr(g.investments)
        log.info(g.investments)
        log.info(len(g.investments))
        log.info('月度irr 为：%.4f'%irr)
        yearlyreturn = np.power(1+irr,12)-1
        log.info('策略年化收益率为：%.4f'%yearlyreturn)

#  根据买卖方向，刷新上次交易价格
def refresh_trade_price(datetime1,buy_or_sell):
    price = get_price(g.security, end_date=datetime1, frequency='1m', fields='close',
                      count=1, panel=False)['close'][-1]
    if buy_or_sell == 'buy' :
        g.bought_price = price
    elif buy_or_sell == 'sell' :
        g.sold_price = price

#  计算指数当前最大涨幅，
def max_increase1y(date):
    days = 250 *1

    # 1.5年内的最高点
    h = get_price(g.index, end_date=date, frequency='1d', fields='close',
                      count=days, panel=False )
    h0 = h['close'].idxmax()
    max0 = h['close'].max()
    min0 = h['close'].loc[h0:].min()
    return (max0/min0-1)*100
# 计算当前向前2年的最高点，以及最高点向前2.5年的最低点之间的最大涨幅

def max_increase(date):
    date_now = date
    days = 250 *1.5

    # 1.5年内的最高点
    h = get_price(g.index, end_date=date, frequency='1d', fields='close',
                      count=250*1.5, panel=False )
    h0 = h['close'].idxmax()
    max0 = h['close'].max()
    min0 = h['close'].loc[h0:].min()

    
    #  高点前的起涨点
    h = get_price(g.index, end_date=h0, frequency='1d', fields='close',
                      count=250*2.5, panel=False )
    min1 = h['close'].min()
    # print(min1)
    l1 = h['close'].idxmin()

    growth0 = max0 - min1
    rate0 = max0/min1 * 100 - 100
    down0 = max0 - min0
    rate1 = 1- down0 / growth0
    return rate0,rate1 
'''    

'''
