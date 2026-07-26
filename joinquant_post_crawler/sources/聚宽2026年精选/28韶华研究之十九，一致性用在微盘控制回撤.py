# 克隆自聚宽文章：https://www.joinquant.com/post/47349
# 标题：韶华研究之十九，一致性用在微盘控制回撤
# 作者：韶华不负

#导入函数库
from jqdata import *
from jqfactor import get_factor_values
import numpy as np
import pandas as pd

##24/2/6,加入蒋的一致性做风控,回测显示在23年开始有效，其余时间效果不明显，不管是静态还是BOLL带，主要是单边上涨趋势中过多干预则使得必反;
##24/2/10，一致性从10年开始是逐渐从70多向80多上涨，可以作为参考值存在；拥挤度择时S型波动，15年前高，24年初升高
##24/2/15，一致性的120天BOLL带上轨有风控效果，配上指数的牛关熊开后，Y18至今S2.2D23，结合Y10至今看相当，但回撤控制的更好，拟发布
#初始化函数 
def after_code_changed(context):
    unschedule_all()
    # 设定基准
    set_benchmark('000001.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 设置交易成本万分之三，不同滑点影响可在归因分析中查看
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),type='stock')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    #初始化全局变量
    g.stock_proportion = 0 #按照中小综总股票数的一定比例持仓,原版值为0.015
    g.stock_num = 5  #采用蒋版经典小市值持仓数
    g.limit_up_list = [] #记录持仓中涨停的股票
    g.hold_list = [] #当前持仓的全部股票
    g.history_hold_list = [] #过去一段时间内持仓过的股票
    g.not_buy_again_list = [] #最近买过且涨停过的股票一段时间内不再买入
    
    g.limit_days = 5 #不再买入的时间段天数
    
    g.HV_control = True #新增，Ture是日频判断是否放量，False则不然
    g.HV_duration = 60 #HV_control用，周期可以是240-120-60，默认比例是0.9
    g.HV_ratio = 0.9    #HV_control用
    
    g.target_list = [] #开盘前预操作股票池
    g.new_stock_control = False #判断是否过滤新股，默认不过滤收益更高
    
    #一致性(Min10%一致下跌超过86%落在-2%即清仓，下一次80%上涨超过2%即买入)作为风控
    g.consistency_control =1    #0-默认不启用，1-启用;
    g.consistency_signal = False    #False-起始满仓，一旦清信即为True，再次涨信即为False
    g.mini_livelevel = 1    #记录min指数的实时累计涨幅
    g.mini_prehigh = 1    #记录min指数的前高
    g.mini_prelow = 1    #记录min指数的前低
    g.mini_cosi_list =[]  #记录mini的一致性数据
    g.mini_crowd_list =[]   #记录mini的拥挤度数据

    #设置关仓变量，1/4月不交易
    g.no_trading_today_signal = False
    
    # 设置交易时间，每天运行
    run_daily(prepare_stock_list, time='6:00')
    run_weekly(weekly_adjustment, weekday=1, time='9:30')
    #run_daily(check_signal, time='9:30')
    run_daily(check_limit_up, time='14:00')
    if g.HV_control == True:
        run_daily(check_high_volume, time='14:45')
    #run_daily(print_position_info, time='15:10')

#1-1 选股模块
def get_factor_filter_list(context,stock_list,jqfactor,sort,p1,p2):
    yesterday = context.previous_date
    score_list = get_factor_values(stock_list, jqfactor, end_date=yesterday, count=1)[jqfactor].iloc[0].tolist()
    df = pd.DataFrame(columns=['code','score'])
    df['code'] = stock_list
    df['score'] = score_list
    df = df.dropna()
    df.sort_values(by='score', ascending=sort, inplace=True)
    filter_list = list(df.code)[int(p1*len(stock_list)):int(p2*len(stock_list))]
    return filter_list

#1-2 选股模块
def get_stock_list(context):
    initial_list = get_index_stocks('399101.XSHE') #获取指数成分股，确定买入数量##print('指数包含{}只股票，选取{}只'.format(len(initial_list),stock_num))#stock_num = 10不过滤新股，收益大幅提高#if g.new_stock_control == True:#    initial_list = filter_new_stock(context, initial_list, 250)
    initial_list = filter_st_stock(initial_list)
    log.info('中小板票池共%d只' % len(initial_list))
    list_len = len(initial_list)
    #stock_num = int(list_len * g.stock_proportion)
    stock_num = g.stock_num

    q = query(valuation.code,indicator.eps).filter(valuation.code.in_(initial_list)).order_by(valuation.circulating_market_cap.asc())
    df = get_fundamentals(q)
    #df = df[df['eps']>0]   #24/2/15新增测试，回测显示收益下降回撤变大，不推荐
    stock_list = list(df.code)
    log.info('今日前10:%s' % stock_list[:2*stock_num])
    stock_list = stock_list[:stock_num]

    return stock_list

#1-3 准备股票池
def prepare_stock_list(context):
    #判断当前日期是否1(01-01~01-31)-4(04-01~04-30)-6(06-01~06-30)，避开财报雷
    g.no_trading_today_signal = today_is_between(context,2 ,'01-01', '01-30') #原版为4.5-4.30，清明节为4.4/4.5
    
    if g.consistency_control ==1:
        g.consistency_signal = min_consistency_check(context,g.consistency_signal)
    
    #获取已持有列表
    g.hold_list= []
    for position in list(context.portfolio.positions.values()):
        stock = position.security
        g.hold_list.append(stock)
    #获取最近一段时间持有过的股票列表
    g.history_hold_list.append(g.hold_list)
    if len(g.history_hold_list) >= g.limit_days:
        g.history_hold_list = g.history_hold_list[-g.limit_days:]
    temp_set = set()
    for hold_list in g.history_hold_list:
        for stock in hold_list:
            temp_set.add(stock)
    g.not_buy_again_list = list(temp_set)
    #获取昨日涨停列表
    if g.hold_list != []:
        df = get_price(g.hold_list, end_date=context.previous_date, frequency='daily', fields=['close','high_limit'], count=1, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        g.high_limit_list = list(df.code)
    else:
        g.high_limit_list = []
        
    #top_list = get_stock_list(context)
    #log.info('今日前排:%s' % top_list)

#1-4 整体调整持仓
def weekly_adjustment(context):
    
    if g.no_trading_today_signal == True or g.consistency_signal == True:
        close_account(context)
        log.info('关仓期')
        return
    #获取应买入列表
    g.target_list = get_stock_list(context) #stock_num已确定，不需要再截取
    g.target_list = filter_paused_stock(g.target_list)
    g.target_list = filter_limitup_stock(context, g.target_list)
    g.target_list = filter_limitdown_stock(context, g.target_list)
        
    #调仓卖出
    for stock in g.hold_list:
        if (stock not in g.target_list) and (stock not in g.high_limit_list):
            log.info("卖出[%s]" % (stock))
            position = context.portfolio.positions[stock]
            close_position(position)
        else:
            log.info("已持有[%s]" % (stock))
    #调仓买入
    position_count = len(context.portfolio.positions)
    target_num = len(g.target_list)
    if target_num > position_count:
        value = context.portfolio.cash / (target_num - position_count)
        for stock in g.target_list:
            if context.portfolio.positions[stock].total_amount == 0:
                if open_position(stock, value):
                    if len(context.portfolio.positions) == target_num:
                        break

#1-5 调整昨日涨停股票
def check_limit_up(context):
    now_time = context.current_dt
    if g.high_limit_list != []:
        #对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
        for stock in g.high_limit_list:
            current_data = get_price(stock, end_date=now_time, frequency='1m', fields=['close','high_limit'], skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True)
            if current_data.iloc[0,0] < current_data.iloc[0,1]:
                log.info("[%s]涨停打开，卖出" % (stock))
                position = context.portfolio.positions[stock]
                close_position(position)
            else:
                log.info("[%s]涨停，继续持有" % (stock))

#1-6 根据风控信号操作
def check_signal(context):
    if g.consistency_signal == True:
        close_account(context)
        log.info('关仓期')
        return
    else:
        if len(context.portfolio.positions) ==0:
            weekly_adjustment(context)

# 3-6 调整放量股票
def check_high_volume(context):
    current_data = get_current_data()

    for stock in context.portfolio.positions:
        if current_data[stock].paused == True:
            continue
        if current_data[stock].last_price == current_data[stock].high_limit:
            continue
        if context.portfolio.positions[stock].closeable_amount ==0:
            continue
        df_volume = get_bars(stock,count=g.HV_duration,unit='1d',fields=['volume'],include_now=True, df=True)
        if df_volume['volume'].values[-1] > g.HV_ratio*df_volume['volume'].values.max():
            log.info("[%s]天量，卖出" % stock)
            position = context.portfolio.positions[stock]
            close_position(position)
    
#3-7 对min10%进行一致性检查
def min_consistency_check(context,signal):
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    all_data = get_current_data()
    
    #1,取昨天的30天以上Min500(10%)，去除ST
    stocklist = list(get_all_securities(['stock']).index)   #取all
    
    num1 = len(stocklist)    
    stocklist = [stockcode for stockcode in stocklist if not all_data[stockcode].paused]
    stocklist = [stockcode for stockcode in stocklist if not all_data[stockcode].is_st]
    stocklist = [stockcode for stockcode in stocklist if'退' not in all_data[stockcode].name]
    stocklist = [stockcode for stockcode in stocklist if stockcode[0:3] != '688']
    stocklist = [stockcode for stockcode in stocklist if (today_date-get_security_info(stockcode).start_date).days>20]
    num2 = len(stocklist)
    
    df_all = get_price(stocklist, end_date=lastd_date, frequency='1d', fields='money',count=1, panel=False)
    
    q = query(valuation.code, valuation.market_cap).filter(valuation.code.in_(stocklist)).order_by(valuation.market_cap.asc())
    df = get_fundamentals(q)
    num3 = round(0.05*num1)
    stocklist = list(df['code'])[:num3]

    #2，计算昨天的涨幅均值和方差，以及落在Mean+2方差内的
    df_chg = get_money_flow(stocklist, end_date=lastd_date, fields='change_pct', count=1)
    #log.info(df_chg)
    chg_med = np.median(df_chg.change_pct)
    chg_std = np.std(df_chg.change_pct)
    #log.info(chg_mean,chg_std)
    
    df_temp = df_chg[(df_chg.change_pct < (chg_med+chg_std)) & (df_chg.change_pct > (chg_med-chg_std))]
    num4 = len(df_temp)
    
    cosistency_last = num4/num3
    g.mini_cosi_list.append(cosistency_last)
    
    #0,增加基准指数的牛(关)熊(开)判断，1-年线上下
    df_index = get_price('000001.XSHG', end_date=lastd_date, frequency='1d', fields='close',count=240, panel=False)
    if df_index['close'].values[-1] >df_index['close'].values.mean():
        log.info('牛市,关闭一致性检查')
        return False
    else:
        log.info('熊市,打开一致性检查')
        
    if len(g.mini_cosi_list) >=120:
        cosistency_mean = np.mean(g.mini_cosi_list[-120:])
        cosistency_std = np.std(g.mini_cosi_list[-120:])
    else:
        cosistency_mean = 0.8
        cosistency_std =0.05
    
    cosistency_upper = cosistency_mean+cosistency_std
    log.info('%s的mini变动中值:%.4f,标准差:%.4f,昨一致性:%.4f,一致性均值:%.4f,一致性上轨:%.4f' % (lastd_date,chg_med,chg_std,cosistency_last,cosistency_mean,cosistency_upper))
    
    
    #使用BOLL带判断
    if (chg_med <-2 and cosistency_last>=cosistency_upper):# or (chg_med <-4 and num4/num3>0.84) or (chg_med <-6 and num4/num3>0.82) :
        log.info('清仓')
        return True
    elif (chg_med >2 and cosistency_last>=cosistency_mean):
        log.info('满上')
        return False
    else:
        log.info('照常')
        return signal
    """
    #使用绝对值判断
    if (chg_med <-2.2 and chg_med >-7 and num4/num3>=0.85):
        log.info('清仓')
        return True
    elif (chg_med >2.1 and num4/num3>=0.82) or (chg_med >4 and num4/num3>=0.75):
        log.info('满上')
        return False
    else:
        log.info('照常')
        return signal
    """
    return False
#3-8 判断今天是否为账户资金再平衡的日期
#date_flag,1-单个月，2-两个月1和4，3-三个月1和4和6
def today_is_between(context, date_flag, start_date, end_date):
    today = context.current_dt.strftime('%m-%d')
    #1(01-01~01-31)-4(04-01~04-30)-6(06-01~06-30)
    if date_flag ==1:
        if (start_date <= today) and (today <= end_date):
            return True
        else:
            return False
    elif date_flag ==2:
        if ('01-01' <= today) and (today <= '01-31'):
            return True
        elif ('04-01' <= today) and (today <= '04-30'):
            return True
        else:
            return False
    elif date_flag ==2:
        if ('01-01' <= today) and (today <= '01-31'):
            return True
        elif ('04-01' <= today) and (today <= '04-30'):
            return True
        elif ('06-01' <= today) and (today <= '06-30'):
            return True
        else:
            return False

#4-2 清仓后次日资金可转
def close_account(context):
    if len(context.portfolio.positions) ==0:
        return

    for stock in context.portfolio.positions:
        position = context.portfolio.positions[stock]
        close_position(position)
        log.info("关仓，卖出[%s]" % (stock))

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

#2-3 获取最近N个交易日内有涨停的股票
def get_recent_limit_up_stock(context, stock_list, recent_days):
    stat_date = context.previous_date
    new_list = []
    for stock in stock_list:
        df = get_price(stock, end_date=stat_date, frequency='daily', fields=['close','high_limit'], count=recent_days, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        if len(df) > 0:
            new_list.append(stock)
    return new_list

#2-4 过滤涨停的股票
def filter_limitup_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] < current_data[stock].high_limit]

#2-5 过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] > current_data[stock].low_limit]

#2-6 过滤科创板
def filter_kcb_stock(context, stock_list):
    return [stock for stock in stock_list  if stock[0:3] != '688']

#2-7 过滤次新股
def filter_new_stock(context,stock_list,d):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=d)]

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

#3-4 交易模块-调仓
def adjust_position(context, buy_stocks, stock_num):
	for stock in context.portfolio.positions:
		if stock not in buy_stocks:
			log.info("[%s]不在应买入列表中" % (stock))
			position = context.portfolio.positions[stock]
			close_position(position)
		else:
			log.info("[%s]已经持有无需重复买入" % (stock))

	position_count = len(context.portfolio.positions)
	if stock_num > position_count:
		value = context.portfolio.cash / (stock_num - position_count)
		for stock in buy_stocks:
			if context.portfolio.positions[stock].total_amount == 0:
				if open_position(stock, value):
					if len(context.portfolio.positions) == stock_num:
						break

#4-1 打印每日持仓信息
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
		
