# 克隆自聚宽文章：https://www.joinquant.com/post/46977
# 标题：发一个学习策略5年70倍，思路可以学习
# 作者：xxzlw

#有赚就好
import talib
import numpy as np
import pandas as pd

def initialize(context):
    log.set_level('order', 'warning')
    set_benchmark('000001.XSHG')
    g.choice = 500
    g.amount = 5
    g.muster = []
    g.bucket = []
    g.summit = {}
    set_benchmark('000905.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 设置滑点为理想情况，不同滑点影响可以在归因分析中查看
    set_slippage(PriceRelatedSlippage(0.000))
    run_daily(prepare, time='9:15')
    run_daily(buy, time='9:26')
    run_daily(sell, time='13:06')
    
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.00011, close_commission=0.00011, close_today_commission=0, min_commission=5), type='stock')
    # run_weekly(prepare,weekday=1,time='09:15', reference_security='000300.XSHG')
    # run_weekly(buy,weekday=1,time='09:26', reference_security='000300.XSHG')
    # run_weekly(sell,weekday=5,time='14:50', reference_security='000300.XSHG')
    
    
    run_daily(high_sell, time='every_bar')

def high_sell(context):
    
    nowtime = context.current_dt.strftime('%H:%M')
    if nowtime>'09:35':
        
        holdlist =list(context.portfolio.positions)
        current_data = get_current_data()    
        holdlist_stock=[]
        for stock in holdlist[:]:
            if get_security_info(stock).type == 'stock':
              holdlist_stock.append(stock)
        for i in holdlist_stock[:]:
            day_open = current_data[i].day_open
            nowprice = current_data[i].last_price
            high_limit = current_data[i].high_limit
            zhangfu_stock = (nowprice-day_open)/day_open
            if zhangfu_stock>0.065 and  nowprice < high_limit:
                order_target(i, 0,LimitOrderStyle(nowprice*0.983)) 
                log.info('______________stock盘中盘中涨幅较大卖出_______________')
                log.info("卖出[%s]" % (i))

    
#2-1 过滤停牌股票
def filter_paused_stock(stock_list):
	current_data = get_current_data()
	return [stock for stock in stock_list if not current_data[stock].paused]

#2-2 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
	current_data = get_current_data()
	return [stock for stock in stock_list
			if not current_data[stock].is_st
			and 'ST' not in current_data[stock].name
			and '*' not in current_data[stock].name
			and '退' not in current_data[stock].name]

# 2-3 过滤科创北交股票 30为创业板
def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68' :
            stock_list.remove(stock)
    return stock_list

#2-4 过滤涨停的股票
def filter_limitup_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	return [stock for stock in stock_list if last_prices[stock][-1] < current_data[stock].high_limit]

#2-5 过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	return [stock for stock in stock_list if last_prices[stock][-1] > current_data[stock].low_limit]

#2-6 过滤次新股
def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=144)]

#2-6 过滤持有股票 
def filter_hold_stock(context,stock_list):
	return [stock for stock in stock_list if stock not in context.portfolio.positions.keys()]


def prepare(context):
    log.info('------------------------------------------------------------')
    fundamentals_data = get_fundamentals(query(valuation.code, valuation.market_cap).order_by(valuation.market_cap.asc()).limit(g.choice))
    stocks = list(fundamentals_data['code'])
    current_data = get_current_data()
    g.muster = [s for s in stocks if not current_data[s].paused and not current_data[s].is_st and 'ST' not in current_data[s].name and '*' not in current_data[s].name and '退' not in current_data[s].name and current_data[s].low_limit < current_data[s].day_open < current_data[s].high_limit]
    g.muster = filter_paused_stock(g.muster)
    g.muster = filter_st_stock(g.muster)
    g.muster = filter_kcbj_stock(g.muster)
    g.muster = filter_limitup_stock(context, g.muster)
    g.muster = filter_limitdown_stock(context, g.muster)
    g.muster = filter_hold_stock(context, g.muster)

def sell(context):
    data_today = get_current_data()
    current_data = get_current_data()
    for s in context.portfolio.positions:
        #如果不涨停才能卖  
        if current_data[s].last_price < current_data[s].high_limit:
        
            name = get_security_info(s).display_name
            print('sell [{} {}]'.format(s,name))  
            #order_target(s, 0)
            
            # (为适应注册制挂单限制0.02,换成限价单,当前价格浮动百分之 之内,这里浮动0.017)
            current_data = get_current_data()
            last_price = current_data[s].last_price
            order_target(s, 0,LimitOrderStyle(last_price*0.983)) 
        
def buy(context):
    data_today = get_current_data()
    available_slots = g.amount - len(context.portfolio.positions)
    if available_slots <= 0: 
        print("无需新购买股票")
    else:
        allocation = context.portfolio.cash / available_slots
        for s in g.muster:
            if available_slots==0:
                break
            if history(5, '1d', 'paused', s).max().values[0] == 0:
                
                # 过滤A杀
                low = history(4, '1d', 'low', s).min().values[0]
                high = history(4, '1d', 'high', s).max().values[0]
                precent = (high - low)/low*100
                if(precent<=20):
                    day_open = data_today[s].day_open
                    day1_close = get_price(s, count=1, end_date=context.previous_date).iloc[-1]['close']
                    day1_low = get_price(s, count=1, end_date=context.previous_date).iloc[-1]['low']
                    
                    his = history(60, '1d', 'close', s)
                    ema1 = talib.EMA(his.values.flatten(), timeperiod=5)[-1]
                    
                    if day1_close > ema1 and day_open < day1_low:
                        #order(s, int(allocation/day_open))
                            
                        # (为适应注册制挂单限制0.02,换成限价单,当前价格浮动百分之  之内,这里浮动0.017)
                        name = get_security_info(s).display_name
                        print('buy [{} {}]'.format(s,name))
                        
                        current_data = get_current_data()
                        last_price = current_data[s].last_price
                        
                        nums = math.floor( int(allocation/last_price) )
                        int_nums = int(nums // 100 ) * 100 # 取整除 - 返回商的整数部分（向下取整） 再乘以 100 
                        
                        order(s, int_nums,LimitOrderStyle(last_price*1.017)) # 使用order 买入指定的仓位
                        available_slots -= 1
                        
# 打印每日持仓
def print_trade_info(context):
    trades = get_trades()
    for _trade in trades.values():
        print('成交记录：'+str(_trade.security) + '--' + str(_trade.price) + '--' + str(_trade.amount))

    for position in list(context.portfolio.positions.values()):
        securities=position.security
        name = get_security_info(securities).display_name
        cost=position.avg_cost
        price=position.price
        ret=100*(price/cost-1)
        value=position.value
        amount=position.total_amount
        
        print('----------------------')
        print('代码:{}'.format(securities))
        print('名称:{}'.format(name))
        print('成本价:{}'.format(format(cost,'.2f')))
        print('现价:{}'.format(price))
        print('收益率:{}%'.format(format(ret,'.2f')))
        print('持仓(股):{}'.format(amount))
        print('市值:{}'.format(format(value,'.2f')))
        
    print('=================================================')
    print('今日收盘账户可用资金: %d' % context.portfolio.available_cash)
    print('今日收盘账户总资产：%s' % round(context.portfolio.total_value,2))
    print('=================================================')                         
