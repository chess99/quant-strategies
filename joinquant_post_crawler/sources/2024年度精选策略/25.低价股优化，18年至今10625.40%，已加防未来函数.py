# 克隆自聚宽文章：https://www.joinquant.com/post/40992
# 标题：低价股优化，18年至今10625.40%，已加防未来函数
# 作者：南国草

# 克隆自聚宽文章：https://www.joinquant.com/post/40980
# 标题：狂飙！低价股难道是圣杯？
# 作者：咔咔系

# 克隆自聚宽文章：https://www.joinquant.com/post/25650
# 标题：ST股日内做套每周调仓
# 作者：人生如梦

#导入函数库
from jqdata import *
import numpy as np 
import pandas as pd
from pandas import Series
from datetime import datetime, time
# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')
    g.sel_stock = None
    
    # 策略开始买卖时间
    g.strategy_starttime=time(10, 20)
    # 策略尾盘撮合买入时间
    g.strategy_endtime=time(14, 55)
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.00025, close_commission=0.00025, min_commission=5), type='stock')
    run_weekly(weekly, weekday=1, time='09:31', reference_security='000300.XSHG')

    # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
      # 开盘时运行
    run_daily(market_open, time='every_bar', reference_security='000300.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')

        
    #调整持仓
def weekly(context):  
    g.sel_stock = None
    current_data = get_current_data()
    # 取得所有股票
    stock_list=get_all_securities().index.tolist()
    # 取得5天的close
    last_5_prices=history(count=5, field='close', security_list=stock_list)
    # 取5天close 平均数
    last_5_prices=pd.DataFrame({'mean_val':last_5_prices.mean()})
    # 均值排序
    last_5_prices_sort=last_5_prices.sort_values(axis=0,ascending=True,by=['mean_val'])

    # 取得均值>=1.5的股票
    q='mean_val>=1.5'
    last_5_prices_query=last_5_prices_sort.query(q)

    last_5_prices_stock=list(last_5_prices_query.index)   

    today_str=context.current_dt.strftime("%Y-%m-%d")
    #log.info(last_5_prices_stock)
    # 去除停牌，*ST,退 , 选择出ST, 这个地方*ST，收益会更大，风险也大
    for security in last_5_prices_stock:
        if  (current_data[security].paused==False) \
            and not current_data[security].is_st \
            and '*' not in current_data[security].name \
            and '退' not in current_data[security].name:
            g.sel_stock= security
            break
    if g.sel_stock is not None:
        log.info(g.sel_stock)
        log.info(get_security_info(g.sel_stock).display_name)
        # 调仓
        sell_list = set(context.portfolio.positions.keys()) - set([g.sel_stock])
        print('sell:',sell_list)
        for stock in sell_list:
            order_target_value(stock, 0)
    else:
        for stock in context.portfolio.positions.keys():
            order_target_value(stock, 0)

    
def before_market_open(context):
    log.info('函数运行时间(before_market_open)：'+context.current_dt.strftime("%Y-%m-%d %H:%M:%S"))
    g.not_buy_flg=1
    g.not_sell_flg=1
    
    g.last_buy_orderid=None
    g.last_sell_orderid=None
    g.last_buy_price = 0
    g.last_sell_price = 0
    g.price_50m={'open':0.000,'close':0.000,'high':0.000,'low':0.000}
    g.price_before_close=0.000      

# 根据当前时间取得购买价格
def get_buy_price(context):
    sel_stock_price=attribute_history(g.sel_stock,1, unit='50m',fields=('open','close','high','low'),skip_paused=True, df=True, fq='pre')
    if context.current_dt.time()>=g.strategy_starttime and context.current_dt.time()< g.strategy_endtime:
        return sel_stock_price['low'][0]
    else:
        return sel_stock_price['close'][0]
        
# 根据当前时间取得卖出价格
def get_sell_price(context):
    sel_stock_price=attribute_history(g.sel_stock,1, unit='50m',fields=('open','close','high','low'),skip_paused=True, df=True, fq='pre')
    if context.current_dt.time()>=g.strategy_starttime and context.current_dt.time()< g.strategy_endtime:
        return sel_stock_price['high'][0]
    else:
        return sel_stock_price['close'][0]
    
def market_open(context):

    current_data = get_current_data()
    if g.sel_stock is None:
        return
    
    # 测试限价单bug ,时间 2022-05-05 10:38可以成交 ，10：37，10：36等都不行 
    # if context.current_dt.time() ==time(10, 37):
    #     _order = order('600568.XSHG',60900,LimitOrderStyle(1.63))
    #     print(_order)
    # return
    
    # 判断到了交易时间开始交易
    if context.current_dt.time()>=g.strategy_starttime:
        if g.not_buy_flg==1:
            now_buy_price = get_buy_price(context)
            # 取消
            orders=get_open_orders()
            for _order in orders.values():
                if _order.order_id==g.last_buy_orderid:
                    cancel_order(_order)         
            # 价格和之前的下单价格不一致 且 之前下过单
            # if now_buy_price!=g.last_buy_price and g.last_buy_orderid is not None:
            #     orders=get_open_orders()
            #     g.not_buy_flg=0
            #     for _order in orders.values():
            #         if _order.order_id==g.last_buy_orderid:
            #             cancel_order(_order)
            #             g.not_buy_flg=1
            
            g.last_buy_price=now_buy_price
            buy_count=int(context.portfolio.available_cash/now_buy_price/100)*100
            if buy_count>=100:
                new_order=order(g.sel_stock,buy_count,LimitOrderStyle(now_buy_price))
                if new_order is not None:
                    if str(new_order.status) == 'held':
                        g.not_sell_flg = 0
                    else:
                        g.last_buy_orderid = new_order.order_id

        # 卖盘逻辑
        if context.current_dt.time()<g.strategy_endtime and g.not_sell_flg==1:
            now_sell_price = get_sell_price(context)
            
            orders=get_open_orders()
            for _order in orders.values():
                if _order.order_id==g.last_sell_orderid:
                    cancel_order(_order)            
            # if now_sell_price!=g.last_sell_price and g.last_sell_orderid is not None:
            #     orders=get_open_orders()
            #     g.not_sell_flg=0
            #     for _order in orders.values():
            #         if _order.order_id==g.last_sell_orderid:
            #             cancel_order(_order)
            #             g.not_sell_flg=1
                        
            if g.sel_stock in context.portfolio.positions \
            and context.portfolio.positions[g.sel_stock].closeable_amount>0:
                g.last_sell_price=now_sell_price                
                new_order=order(g.sel_stock,-context.portfolio.positions[g.sel_stock].closeable_amount,LimitOrderStyle(now_sell_price))
                if new_order is not None:
                    if str(new_order.status) == 'held':
                        g.not_sell_flg = 0
                    else:                
                        g.last_sell_orderid = new_order.order_id
            else:
                g.not_sell_flg==0


##收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    log.info('一天结束')
    log.info('##############################################################')
