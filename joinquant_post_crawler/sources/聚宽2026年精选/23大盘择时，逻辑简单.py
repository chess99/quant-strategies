# 克隆自聚宽文章：https://www.joinquant.com/post/47516
# 标题：大盘择时，逻辑简单
# 作者：gjbdyrs

import pandas as pd
import talib as tb
import numpy as np
from jqdata import *
from jqfactor import get_factor_values


def initialize(context):
    set_benchmark('000300.XSHG') 
    log.set_level('order', 'error')
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)# 设置是否开启避免未来数据模式
    set_slippage(FixedSlippage(0.02))# 设置滑点
    # 股票类交易手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, \
                             open_commission=0.00015, close_commission=0.00015,\
                             close_today_commission=0, min_commission=0), type='stock')
    # 持仓数量
    g.stock_num =5
    # 空仓选用
    g.etf_A = '511880.XSHG'
    # 轮动选用
    g.etf_B = '510300.XSHG'
    #相对300指数波动
    g.beta=0.7
    # MACD择时
    g.no_trading_today_signal =True
    # 设置交易时间，每天运行
    run_daily(prepare_stock_list, time='9:05', reference_security='000300.XSHG')
    run_daily(get_macd,time='9:30', reference_security='000300.XSHG')
    run_monthly(my_Trader,1, time='9:35', reference_security='000300.XSHG')
    run_daily(check_limit_up, time='14:00', reference_security='000300.XSHG')
    run_daily(my_trade_stocknum, '15:00')

def my_trade_stocknum(context):
    record(stocknum=len(context.portfolio.positions)) 

#获取macd择时信号  
def get_macd(context):
    yesterday = context.previous_date
    re_value = get_macd_M(['000300.XSHG'],yesterday)
    dif, dea, macd = re_value['000300.XSHG']
    today_sig =macd
    stock_list=context.portfolio.positions.keys()
    stock_list=list(stock_list)
    if today_sig >0:
        g.no_trading_today_signal =False
    if today_sig <= 0:
        g.no_trading_today_signal =True
    
    # 定义一个包含所有需要从stock_list中移除的ETF的集合
    etfs_to_remove = {g.etf_A, g.etf_B}
    # 检查并移除stock_list中的ETF
    stock_list = [stock for stock in stock_list if stock not in etfs_to_remove]    
    if today_sig>0 and len(stock_list)>0:
        for s in stock_list:
            order_target(s, 0)
            print(context.previous_date,f'大盘风控止损触发,全仓卖出{s}')
        # 买入轮动基金
        order_value(g.etf_B, context.portfolio.available_cash) 
    else:
        if today_sig <= 0 and len(stock_list)==0:
            my_Trader(context)


def my_Trader(context):
    if g.no_trading_today_signal == False:
        return
    dt_last = context.previous_date
    stocks = get_all_securities('stock', dt_last).index.tolist()#读取所有股票
    stocks = filter_kcbj_stock(stocks)  #去科创和北交所
    stocks = filter_st_stock(stocks)#去ST
    stocks = filter_new_stock(context, stocks)#去除上市未满300天
    stocks = choice_roa(context,stocks)#基本面选股********************
    stocks = filter_paused_stock(stocks)#去停牌
    stocks = filter_limit_stock(context,stocks)[:20]#去除涨停的
    cdata = get_current_data()
    #slist(context,stocks)
    
    # Sell
    #先卖掉货币ETF
    if g.etf_A in context.portfolio.positions:
        log.info('Sell', g.etf_A, cdata[g.etf_A].name)
        order_target(g.etf_A, 0)
    for s in context.portfolio.positions:
        if (s  not in stocks) and (cdata[s].last_price <  cdata[s].high_limit):
            log.info('Sell', s, cdata[s].name)
            order_target(s, 0)
    # buy
    position_count = len(context.portfolio.positions)

    if g.stock_num > position_count:
        psize = context.portfolio.available_cash/(g.stock_num - position_count)
        for s in stocks:
            if s not in context.portfolio.positions:
                log.info('buy', s, cdata[s].name)
                order_value(s, psize)
                if len(context.portfolio.positions) == g.stock_num:
                    break
    # 买入货币基金
    order_value(g.etf_A, context.portfolio.cash)
#基本面	
def choice_roa(context,stocks):
    # 获取基本面数据
    df = get_fundamentals(query(
            valuation.code,
            valuation.market_cap
          ).filter(
            valuation.code.in_(stocks),
            valuation.pb_ratio < 1,
            valuation.pb_ratio > 0,
            valuation.market_cap >500,
            indicator.roa > 0.15
          ).order_by(
    	    indicator.roa.desc()
          ).limit(
    	    100
          ))
    stocks = list(df.code)
    #历史BETA<0.7
    yesterday = context.previous_date
    stocks=get_beta(yesterday,stocks)
    return stocks

#显示筛查出股票的：名称，代码，市值
def slist(context,stock_list):    
    current_data = get_current_data()
    for stock in stock_list:
        df = get_fundamentals(query(valuation).filter(valuation.code == stock))
        print('股票代码：{0},  名称：{1},  总市值:{2:.2f},  流通市值:{3:.2f},  PE:{4:.2f},股价：{5:.2f}'.format(stock,get_security_info(stock).display_name,df['market_cap'][0],df['circulating_market_cap'][0],df['pb_ratio'][0],current_data[stock].last_price))

#1-1 准备股票池
# 如果持有股票昨天处于涨停的，则放入涨停列表，只要今天打开涨停就卖出，这个每天执行
def prepare_stock_list(context):
    #获取昨日涨停列
    g.high_limit_list=[]
    for stock in context.portfolio.positions.keys():
        df = get_price(stock, end_date=context.previous_date, frequency='daily', fields=['close','high_limit'], count=1)
        if df['close'][0] >= df['high_limit'][0]*0.98:#如果昨天有股票涨停，则放入列表
            g.high_limit_list.append(stock)
    
#1-5 调整昨日涨停股票
def check_limit_up(context):
    if g.high_limit_list != []:
        current_data = get_current_data()
        #对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
        for stock in g.high_limit_list:
            if current_data[stock].last_price <   current_data[stock].high_limit:
                log.info("[%s]涨停打开，卖出" % (stock))
                order_target(stock, 0)
                order_value(g.etf_A, context.portfolio.cash)
            else:
                log.info("[%s]涨停，继续持有" % (stock))            
 
# 过滤科创北交股票
def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68':
            stock_list.remove(stock)
    return stock_list

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
			and '退' not in current_data[stock].name]


# 过滤涨停的股票
def filter_limit_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	# 已存在于持仓的股票即使涨停也不过滤，避免此股票再次可买，但因被过滤而导致选择别的股票
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or current_data[stock].low_limit < last_prices[stock][-1] < current_data[stock].high_limit]
# 过滤次新股
def filter_new_stock(context, stock_list):
    return [stock for stock in stock_list if (context.previous_date - datetime.timedelta(days=300)) > get_security_info(stock).start_date]

  
#macd
def get_macd_M(stock_list,check_date):
    macd_list = {}
    if isinstance(check_date,str):
        check_date = datetime.datetime.strptime(check_date, "%Y-%m-%d %H:%M:%S")
    if isinstance(stock_list,str):
        stock_list = [stock_list]
    for stock in stock_list:
        array = get_bars(security=stock, 
                         count=500, 
                         unit='1M',
                         fields=['close'],
                         include_now=False,
                         end_dt=check_date, 
                         fq_ref_date=check_date)
        close_list = array['close']
        dif, dea, macd = tb.MACD(close_list, 
                                 fastperiod=12, 
                                 slowperiod=26, 
                                 signalperiod=9)
        last_dif = dif[-1]
        last_dea = dea[-1]
        last_macd = macd[-1]
        macd_dic = (last_dif, last_dea, last_macd*2)
        macd_list[stock] = macd_dic
    return macd_list
    

#历史BETA
def get_beta(today, stock_list):
    time0 = today  # 请根据实际情况调整开始日期
    if time0.day==29:
        time1day=28
    else:
        time1day=time0.day
    time1 = datetime.datetime((time0.year)-1,time0.month,time1day)
    print(time1)
    score_list =[]
    # 计算沪深300指数的方差
    index_data = get_price('000300.XSHG', start_date=time1.strftime('%Y-%m-%d') , end_date=time0.strftime('%Y-%m-%d'), frequency='daily', fields=['close'],panel=False)
    index_returns = index_data['close'].pct_change()
    index_var = index_returns.var()
    for stock in stock_list:   
        stock_data = get_price(stock, start_date=time1.strftime('%Y-%m-%d') , end_date=time0.strftime('%Y-%m-%d'), frequency='daily', fields=['close'],panel=False)
        stock_returns = stock_data['close'].pct_change()
        cov_matrix = index_returns.cov(stock_returns)
        cov = cov_matrix 
    # 计算比率
        ratio = cov / index_var
        score_list.append(ratio)
    df = pd.DataFrame(columns=['code','score'])
    df['code'] = stock_list
    df['score'] = score_list
    df = df.dropna()
    df = df.query(f'score<{g.beta}')


    filter_list = list(df.code)
    
    return filter_list
