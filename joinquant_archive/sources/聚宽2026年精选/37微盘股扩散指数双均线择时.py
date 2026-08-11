# 克隆自聚宽文章：https://www.joinquant.com/post/47407
# 标题：微盘股扩散指数双均线择时
# 作者：无逻辑的光

# 克隆自聚宽文章：https://www.joinquant.com/post/40981
# 标题：差不多得了
# 作者：wywy1995

# 克隆自聚宽文章：https://www.joinquant.com/post/40407
# 标题：wywy1995大侠的小市值AI因子选股 5组参数50股测试
# 作者：Bruce_Lee

#https://www.joinquant.com/view/community/detail/30684f8d65a74eef0d704239f0eec8be?type=1&page=2
#导入函数库
from jqdata import *
from jqfactor import *
import numpy as np
import pandas as pd
import talib
import datetime
import pickle
from six import BytesIO



#初始化函数  000852.XSHG (ZZ1000)
def initialize(context):
    # 设定基准
    set_benchmark('399303.XSHE')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0.002))
    # 设置交易成本万分之三，不同滑点影响可在归因分析中查看
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),type='stock')
    # 过滤order中低于error级别的日志
    #log.set_level('order', 'error')
    #初始化全局变量
    g.no_trading_today_signal = True
    g.stock_num = 5
    g.hold_list = [] #当前持仓的全部股票    
    g.yesterday_HL_list = [] #记录持仓中昨日涨停的股票
    g.watch_day = 20
    g.base = pd.read_csv(BytesIO(read_file('wp_ks_index.csv')),encoding='utf_8_sig')
    g.factor_list = [
        (#P1Y-TPtCR-VOL120 
            [
                'Price1Y', #动量类因子 当前股价除以过去一年股价均值再减1
                'total_profit_to_cost_ratio', #质量类因子 成本费用利润率
                'VOL120' #情绪类因子 120日平均换手率
            ],
            [
              -1.6481969388084845,
              -0.17062057099935446,
              -0.061842557079243125
            ]
        ) 
    ]
   
    # 设置交易运行时间
    run_daily(prepare_stock_list, '9:05')
    run_daily(daily_adjustment,'9:30')
    run_daily(check_limit_up, '14:00') #检查持仓中的涨停股是否需要卖出
    #run_daily(close_account, '14:30')
    run_daily(print_position_info, '15:10')



#1-1 准备股票池
def prepare_stock_list(context):
    #获取已持有列表
    g.hold_list= []
    for position in list(context.portfolio.positions.values()):
        stock = position.security
        g.hold_list.append(stock)
    #获取昨日涨停列表
    if g.hold_list != []:
        df = get_price(g.hold_list, end_date=context.previous_date, frequency='daily', fields=['close','high_limit'], count=1, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        g.yesterday_HL_list = list(df.code)
    else:
        g.yesterday_HL_list = []
    #判断今天是否为账户资金再平衡的日期
    #g.no_trading_today_signal = today_is_between(context, '04-01', '04-30') or today_is_between(context, '01-01', '02-28')

#获取扩散系数
def get_ks_index(context,watch_day):
    yesterday = context.previous_date
    ks_index = []
    dates = get_trade_days(end_date = yesterday, count=30)
    for date in dates:
        stocks = get_index_stocks('000852.XSHG',date=date)
        df0 = get_price(stocks, end_date=date, fields=['close'], count=watch_day, fill_paused=False, skip_paused=False, panel=False).dropna()
        end_price = df0.groupby('code').apply(lambda df0: df0.iloc[-1,-1])
        open_price=df0.groupby('code').apply(lambda df0: df0.iloc[0,-1])
        result = pd.DataFrame()
        result['ks']=end_price-open_price
        ks = len(result[result['ks']>0])/len(result['ks']>0)
        ks_index.append(ks)
    df = pd.DataFrame()
    df['date'] = dates
    df['ks_index'] = ks_index
    return df
        
'''
 #获取择时信号  
def get_timing_signal(context):
    yesterday = context.previous_date
    df = get_ks_index(context,g.watch_day)
    df['EMA6']=talib.EMA(df['ks_index'],6)
    df['EMA28']=talib.EMA(df['ks_index'],28)
    df['signal'] = np.where(df['EMA6']-df['EMA28']<0,1,0)
    today_sig=np.array(df['signal'])[-1]
    return today_sig
    
'''
#获取择时信号  
def get_timing_signal(context):
    yesterday = context.previous_date
    yesterday = yesterday.strftime("%Y-%m-%d")
    base = g.base
    base = base.loc[base['date']==yesterday]
    today_sig = base['signal'].tolist()[0]
    return today_sig


#获取微盘股列表
def _get_stocks(date):
    initial_list = get_all_securities().index.tolist()
    initial_list = filter_new_stock(context, initial_list)
    initial_list = filter_kcbj_stock(initial_list)
    initial_list = filter_st_stock(initial_list)
    q = query(valuation.code,valuation.circulating_market_cap).filter(valuation.code.in_(initial_list)).order_by(valuation.circulating_market_cap.asc())
    df = get_fundamentals(q,date=date)
    stock_list = df.code.tolist()[0:1000]
    return stock_list
    
#1-2 选股模块
def get_stock_list(context):
    yesterday = context.previous_date
    final_list = []
    for factor_list,coef_list in g.factor_list:
        initial_list = get_all_securities().index.tolist()
        initial_list = filter_new_stock(context, initial_list)
        initial_list = filter_kcbj_stock(initial_list)
        initial_list = filter_st_stock(initial_list)
        #MS
        factor_values = get_factor_values(initial_list,factor_list, end_date=yesterday, count=1)
        df = pd.DataFrame(index=initial_list, columns=factor_values.keys())
        for i in range(len(factor_list)):
            df[factor_list[i]] = list(factor_values[factor_list[i]].T.iloc[:,0])
        df = df.dropna()
        df['total_score'] = 0
        for i in range(len(factor_list)):
            df['total_score'] += coef_list[i]*df[factor_list[i]]
        df = df.sort_values(by=['total_score'], ascending=False) #分数越高即预测未来收益越高，排序默认降序
        complex_factor_list = list(df.index)[:int(0.1*len(list(df.index)))]
        q = query(valuation.code,valuation.circulating_market_cap,indicator.eps).filter(valuation.code.in_(complex_factor_list)).order_by(valuation.circulating_market_cap.asc())
        df = get_fundamentals(q)
        df = df[df['eps']>0]
        lst  = list(df.code)
        lst = filter_paused_stock(lst)
        lst = filter_limitup_stock(context, lst)
        lst = filter_limitdown_stock(context, lst)
        lst = lst[:min(g.stock_num, len(lst))]
        final_list.extend(lst)
    final_list = list(set(final_list))
    return final_list

#1-3 整体调整持仓
def daily_adjustment(context):
    #获取应买入列表 
    target_stock = get_stock_list(context)
    target_list = target_stock[:g.stock_num]
    if g.no_trading_today_signal:
        #获得今日开平仓信号
        today_sig= get_timing_signal(context)
        try:
            if today_sig > 0:
                for stock in g.hold_list:
                    position = context.portfolio.positions[stock]
                    close_position(position)
                    print(context.previous_date,f'大盘风控止损触发,全仓卖出{stock}')
                return
        except:
            print('开仓！') 
  
    #调仓卖出
    for stock in g.hold_list:
        if (stock not in target_stock) and (stock not in g.yesterday_HL_list):
            log.info("卖出[%s]" % (stock))
            position = context.portfolio.positions[stock]
            close_position(position)
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
    if g.yesterday_HL_list != []:
        #对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
        for stock in g.yesterday_HL_list:
            current_data = get_price(stock, end_date=now_time, frequency='1m', fields=['close','high_limit'], skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True)
            if current_data.iloc[0,0] <    current_data.iloc[0,1]:
                log.info("[%s]涨停打开，卖出" % (stock))
                position = context.portfolio.positions[stock]
                close_position(position)
            else:
                log.info("[%s]涨停，继续持有" % (stock))



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

#2-3 过滤科创北交股票
def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68':
            stock_list.remove(stock)
    return stock_list

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

#2-6 过滤次新股
def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date <    datetime.timedelta(days=250)]



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

#3-3 交易模块-平仓
def close_position(position):
    security = position.security
    order = order_target_value_(security, 0)  # 可能会因停牌失败
    if order != None:
        if order.status == OrderStatus.held and order.filled == order.amount:
            return True
    return False



#4-1 判断今天是否为账户资金再平衡的日期
def today_is_between(context, start_date, end_date):
    today = context.current_dt.strftime('%m-%d')
    if (start_date <= today) and (today <= end_date):
        return True
    else:
        return False

#4-2 清仓后次日资金可转
def close_account(context):
    if g.no_trading_today_signal == True:
        if len(g.hold_list) != 0:
            for stock in g.hold_list:
                position = context.portfolio.positions[stock]
                close_position(position)
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
        name=get_security_info(securities).display_name
        cost=position.avg_cost
        price=position.price
        ret=100*(price/cost-1)
        value=position.value
        amount=position.total_amount    
        print('代码:{}'.format(securities))
        print('名字:{}'.format(name))
        print('成本价:{}'.format(format(cost,'.2f')))
        print('现价:{}'.format(price))
        print('收益率:{}%'.format(format(ret,'.2f')))
        print('持仓(股):{}'.format(amount))
        print('市值:{}'.format(format(value,'.2f')))
        print('———————————————————————————————————')
    print('———————————————————————————————————————分割线————————————————————————————————————————')
