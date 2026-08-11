# 克隆自聚宽文章：https://www.joinquant.com/post/31155
# 标题：抄底神器2.0，低回撤，高成功率，无未来函数
# 作者：枫中忆荣

#抄底神奇2.0版

#增加了以下几点：1.放宽市盈率筛选下限，调低到20倍下限；2.回撤止盈；
#3.剔除重复购买的股票；4.修改部分条件语句，以及让整体看上去美观整洁；
#5.增加了避免未来函数语句；6.设置了过滤涨跌停，和停牌的语句。
#7.不买银行股
#                                                   by 枫中忆荣


from jqdata import *
import pandas as pa
import numpy as np


# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 是否有未来函数
    set_option("avoid_future_data", True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')
    # 股票池
    g.tobuy_stock_BT=[]
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
    # 定时运行
    run_monthly(stocks_choice,1,time='9:30', reference_security='000300.XSHG')
    #股票池筛选
    run_weekly(tobuy_list_Bottom,2,time='9:30', reference_security='000300.XSHG')
    #买入模块
    run_daily(security_stopprofit_1,time='9:30', reference_security='000300.XSHG')
    #调仓模块
    # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')

def stocks_choice(context):
    q1=query(valuation.code, valuation.market_cap,income.total_operating_revenue,valuation.pe_ratio
    ).filter(
        valuation.market_cap < 3000,
        valuation.market_cap >30,
        valuation.pe_ratio>30,
        valuation.pe_ratio<100,
    ).order_by(
    # 按市值降序排列
        valuation.market_cap.asc()
    )
    g.check_out_lists=list(get_fundamentals(q1).code)
    g.check_out_lists=filter_st_stock(g.check_out_lists)
    g.check_out_lists=filter_paused_stock(g.check_out_lists)
    g.readytobuy_list=filter_limitup_stock(context,g.check_out_lists)
    
def tobuy_list_Bottom(context):
    for stock in g.readytobuy_list:
        df=attribute_history(stock, 60,unit='1d',
                 fields=['close','volume'], skip_paused=True, df=True, fq='pre')
        HH_10=df['close'][-12:-2].max()#近10个周期内的高点
        LL_60=df['close'][-60:-1].min()#60个周期内的低点
        current_price=df['close'][-1]#最新价
        vol5=df['volume'][-5:-1].mean()#5日内的成交量平均
        vol60=df['volume'][-60:-30].mean()#60日内的成交量平均
        vol30=df['volume'][-30:-1].mean()
        MA20=df['close'][-20:-1].mean()
        if  abs(1-current_price/LL_60)<0.5 and\
               (1-current_price/HH_10)<0.5 and\
                                vol5>vol30 and\
                               vol30<vol60 and\
                                HH_10>MA20 and\
                          current_price>10 :
            g.tobuy_stock_BT.append(stock)
        if len(g.tobuy_stock_BT)>3:
            g.tobuy_stock_BT=g.tobuy_stock_BT[-3:]
            
    money_tobuy=context.portfolio.available_cash#可用资金
    stock_count=3-len(list(context.portfolio.positions.keys()))#准备买入数量     
    every_stock_money=money_tobuy/stock_count#每只股的买入资金   

    if len(g.tobuy_stock_BT)==0:
            log.info("暂时没有可以买入的标的——75")
    if len(g.tobuy_stock_BT)>0 and len(list(context.portfolio.positions.keys()))==0:
        for stock in g.tobuy_stock_BT:
            order_target_value(stock, every_stock_money)
            log.info("第一次建仓，买入满足条件的股票[%s]"%(stock))
            if len(g.readytobuy_list)>3:
                g.readytobuy_list.remove(stock)
    if len(g.tobuy_stock_BT)>0:
        if  len(list(context.portfolio.positions.keys()))>0 and len(list(context.portfolio.positions.keys()))<4:
            order_target_value(stock, every_stock_money)
            log.info("不够3只，继续买入满足条件的股票[%s]"%(stock))
        if  len(list(context.portfolio.positions.keys()))==3:
            log.info("满仓，当前持有3只股票")
     
def security_stopprofit_1(context, profit1=0.5):
    if len(context.portfolio.positions) > 0:
        for stock in context.portfolio.positions.keys():
            df = attribute_history(stock,20, unit='1d', fields=['close'], skip_paused=True)
            df_max_high = df['close'].max()
            avg_cost = context.portfolio.positions[stock].avg_cost
            current_price = context.portfolio.positions[stock].price
            Buy_time=context.portfolio.positions[stock].init_time
            Now_time=context.current_dt.date()   
            hold_day=get_trade_days(start_date=Buy_time, end_date=Now_time)
            if 1-avg_cost/df_max_high>0.1:
                if 1-current_price/df_max_high >=profit1:
                    log.info(str(stock) + '  回撤达个股止盈线，平仓止盈！')
                    order_target_value(stock, 0)                
            if 1-avg_cost/current_price<-0.10:
                    log.info(str(stock) + '  回撤达到个股止损线，平仓止损！')
                    order_target_value(stock, 0) 
            if len(hold_day)>30 and 1-df['close'][-1]/avg_cost<0.1:
                    order_target(stock, 0)
                    log.info("持有时间超过30日，涨幅不足0.1，卖出[%s]" % (stock))
                    
## 收盘后运行函数
def after_market_close(context):
    log.info('##############################################################')
    log.info(str('函数运行时间(after_market_close):' + str(context.current_dt.time())))
    # 得到当天所有成交记录
    log.info('一天结束啦！')
    for stock in context.portfolio.positions.keys():
        log.info("当前持有[%s]"%(stock))
    log.info('##############################################################')



# 过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]


# 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list
            if not current_data[stock].is_st
            and 'ST' not in current_data[stock].name
            and '*' not in current_data[stock].name
            and '银行' not in current_data[stock].name
            and '退' not in current_data[stock].name]


def filter_limitup_stock(context, stock_list):
    last_prices = history(1,
                          unit='1m',
                          field='close',
                          security_list=stock_list)
    current_data = get_current_data()

    # 已存在于持仓的股票即使涨停也不过滤，避免此股票再次可买，但因被过滤而导致选择别的股票
    return [
        stock for stock in stock_list
        if stock in list(context.portfolio.positions.keys())
        or last_prices[stock][-1] <= current_data[stock].high_limit
        or last_prices[stock][-1] >= current_data[stock].low_limit
    ]

    return [
        stock for stock in stock_list
        if stock in list(context.portfolio.positions.keys())
        or last_prices[stock][-1] > current_data[stock].low_limit
    ]

