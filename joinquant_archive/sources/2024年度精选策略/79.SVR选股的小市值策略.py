# 克隆自聚宽文章：https://www.joinquant.com/post/41611
# 标题：SVR选股的小市值策略
# 作者：南澳

# 克隆自聚宽文章：https://www.joinquant.com/post/41457
# 标题：SVM选股的小市值策略
# 作者：南澳

from jqdata import *
from sklearn.svm import SVR
from jqlib.technical_analysis import *
import datetime
from jqfactor import *
import numpy as np
import pandas as pd

#初始化函数 
def initialize(context):
    # 设定基准
    set_benchmark('399303.XSHE')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0.02))
    # 设置交易成本万分之三，不同滑点影响可在归因分析中查看
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),type='stock')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    #初始化全局变量
    g.no_trading_today_signal = False
    g.stock_num =5
    g.hold_list = [] #当前持仓的全部股票    
    g.yesterday_HL_list = [] #记录持仓中昨日涨停的股票
    # 设置交易运行时间
    # 每月第一个交易日运行
    run_monthly(monthly_filter, 1,time='before_open')
    # 每周最后一个交易日运行
    run_weekly(weekly_filter, -1,time='close')
    
    run_daily(prepare_stock_list, '9:05')
    run_weekly(weekly_adjustment, 1, '9:30')
    run_daily(check_limit_up, '14:00') #检查持仓中的涨停股是否需要卖出
    run_daily(close_account, '14:30')
    run_daily(print_position_info, '15:10')
    
    g.pools = set()

def monthly_filter(context):
    
    today = context.current_dt
    yestoday = today -  datetime.timedelta(days=1)
    start_day = today -  datetime.timedelta(days=375)

    # 选出小市值的股票
    q = query(
            valuation.code,
            valuation.circulating_market_cap
        ).filter(
            valuation.circulating_market_cap.between(0,30)
        ).order_by(
            valuation.circulating_market_cap.asc()).limit(100)
    codes = get_fundamentals(q).code.tolist()
    
    # 过滤掉双创股票
    codes = [code for code in codes if code[:2] in ('60','00')]
    log.info("Top 10 小市值:" + str(codes[:10]))
    # 过滤ST股票
    df = get_extras('is_st', codes, end_date=yestoday,count=1)
    df = df.T
    df.columns = ['is_st']
    df=df[df['is_st']==0]
    codes = df.index.tolist()
    # 过滤次新股
    q = query(finance.STK_LIST.code).filter(
        finance.STK_LIST.start_date <=start_day,
        finance.STK_LIST.code.in_(codes)
        )
    codes = list(finance.run_query(q).code)
    g.pools = set(codes)

def weekly_filter(context):
    today = context.current_dt
    yestoday = today -  datetime.timedelta(days=1)
    codes = list(g.pools)
    # 过滤ST股票
    df = get_extras('is_st', codes, end_date=yestoday,count=1)
    df = df.T
    df.columns = ['is_st']
    df=df[df['is_st']==0]
    codes = df.index.tolist()
    g.pools = set(codes)
    
#1-1 准备股票池
def prepare_stock_list(context):
    #获取已持有列表
    g.hold_list= list(context.portfolio.positions.keys())
    #获取昨日涨停列表
    if g.hold_list != []:
        df = get_price(g.hold_list, end_date=context.previous_date, frequency='daily', fields=['close','high_limit'], count=1, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        g.yesterday_HL_list = list(df.code)
    else:
        g.yesterday_HL_list = []
    #判断今天是否为账户资金再平衡的日期
    g.no_trading_today_signal = today_is_between(context, '04-05', '04-30')
    
#1-2 选股模块
def get_stock_list(context):
    final_list = set()
    initial_list = list(g.pools)
    today = context.current_dt
    # 通过timedelta算出前一天的日期
    delta = datetime.timedelta(days=1)
    yesterday = today - delta
    q = query(valuation.code, 
        valuation.market_cap, 
        valuation.turnover_ratio,
        valuation.pe_ratio, 
        valuation.pb_ratio, 
        valuation.ps_ratio,
        indicator.roa,
         income.total_operating_revenue).filter(valuation.code.in_(initial_list))
    # 将获得的因子值存入一个数据表
    dataset = get_fundamentals(q, date = None)
    dataset.columns = ['code', 'market_cap',
            '换手率','PE','PB','PS','总资产收益率','营业总收入']
    dataset['平均差']=list(DMA(dataset.code,  yesterday)[0].values())        
    dataset['平均差']=list(DMA(dataset.code,  yesterday)[0].values())
    dataset['换手率']=list(HSL(dataset.code,  yesterday)[0].values())
    dataset['移动平均']=list(MA(dataset.code,  yesterday).values())
    dataset['乖离率']=list(BIAS(dataset.code,  yesterday)[0].values())
    dataset['动量线']=list(MTM(dataset.code,  yesterday).values())
    dataset.fillna(0, inplace=True)
    dataset.index = dataset.code
    dataset.drop('code', axis=1, inplace=True)
    X = dataset.drop('market_cap', axis=1)
    y = dataset['market_cap']
    #这里我们使用SVM来训练模型
    svr = SVR()
    svr.fit(X, y)
    # 找到模型市值比预测值低最多的股票
    factor = y - pd.DataFrame(svr.predict(X), index=y.index, columns=['market_cap'])
    final_list = list(factor.sort_index(by='market_cap', ascending=True))[:g.stock_num ]
    return final_list

#1-3 整体调整持仓
def weekly_adjustment(context):
    if g.no_trading_today_signal:
        return

    #获取应买入列表 
    target_list = get_stock_list(context)
    #调仓卖出
    for stock in g.hold_list:
        if (stock not in target_list) and (stock not in g.yesterday_HL_list):
            log.info("卖出[%s]" % (stock))
            order_target(stock, 0)
        else:
            log.info("已持有[%s]" % (stock))
    #调仓买入
    position_count = len(context.portfolio.positions)
    target_num = len(target_list)
    if target_num > position_count:
        value = context.portfolio.cash / (target_num - position_count)
        for stock in target_list:
            if context.portfolio.positions[stock].total_amount == 0:
                if open_position(stock, value):
                    if len(context.portfolio.positions) == target_num:
                        break


#1-4 调整昨日涨停股票
def check_limit_up(context):
    now_time = context.current_dt
    if len(g.yesterday_HL_list) == 0:
        return

    #对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
    for stock in g.yesterday_HL_list:
        current_data = get_price(stock, end_date=now_time, frequency='1m', fields=['close','high_limit'], skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True)
        if current_data.iloc[0,0] <    current_data.iloc[0,1]:
            log.info("[%s]涨停打开，卖出" % (stock))
            order_target(stock, 0)
        else:
            log.info("[%s]涨停，继续持有" % (stock))

#2-1 过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]

#2-4 过滤涨停的股票
def filter_limitup_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] <    current_data[stock].high_limit]

#2-5 过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] > current_data[stock].low_limit]

#3-1 交易模块-自定义下单
def order_target_value_(security, value):
    if value == 0:
        log.debug("Selling out %s" % (security))
    else:
        log.debug("Order %s to value %f" % (security, value))
    return order_target_value(security, value)

#3-2 交易模块-开仓
def open_position(security, value):
    order = order_target_value_(security, value)
    if order != None and order.filled > 0:
        return True
    return False


#4-1 判断今天是否为账户资金再平衡的日期
def today_is_between(context, start_date, end_date):
    today = context.current_dt.strftime('%m-%d')
    return start_date <= today <= end_date

#4-2 清仓后次日资金可转
def close_account(context):
    if g.no_trading_today_signal == True:
        if len(g.hold_list) != 0:
            for stock in g.hold_list:
                order_target(stock, 0)
                log.info("卖出[%s]" % (stock))

#4-3 打印每日持仓信息
def print_position_info(context):
    #打印当天成交记录
    trades = get_trades()
    for _trade in trades.values():
        print('成交记录：'+str(_trade))
    #打印账户信息
    for position in list(context.portfolio.positions.values()):
        securities=position.security
        cost=position.avg_cost
        price=position.price
        ret=100*(price/cost-1)
        value=position.value
        amount=position.total_amount    
        print('代码:{}'.format(securities))
        print('成本价:{}'.format(format(cost,'.2f')))
        print('现价:{}'.format(price))
        print('收益率:{}%'.format(format(ret,'.2f')))
        print('持仓(股):{}'.format(amount))
        print('市值:{}'.format(format(value,'.2f')))
        print('———————————————————————————————————')
    print('———————————————————————————————————————分割线————————————————————————————————————————')
