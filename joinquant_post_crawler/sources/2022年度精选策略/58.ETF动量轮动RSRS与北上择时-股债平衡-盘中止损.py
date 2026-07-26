# 克隆自聚宽文章：https://www.joinquant.com/post/36162
# 标题：ETF动量轮动RSRS与北上择时-股债平衡-盘中止损
# 作者：Jim000

# 克隆自聚宽文章：https://www.joinquant.com/post/36113
# 标题：动量ETF轮动RSRS择时-升级
# 作者：莫急莫急
#1 12:53 增加北上资金择时
#2 增加股债波动率平衡

from jqdata import *
import numpy as np
from pykalman import KalmanFilter

#初始化函数 
def initialize(context):
    set_benchmark('399006.XSHE')
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)  # 避免引入未来信息
    set_slippage(FixedSlippage(0.001))
    set_order_cost(OrderCost(open_tax=0, close_tax=0, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),
                   type='fund')
    log.set_level('order', 'error')
    g.stock_pool = [
        '510050.XSHG', # 上证50ETF
        '510500.XSHG', # 中证500ETF
        '510300.XSHG', # 沪深300ETF
        '512100.XSHG',#1000ETF
        '159949.XSHE',#创业板50
        '163417.XSHE',#兴全合宜
        '161005.XSHE',# 富国天惠
    ]
    # 备选池：用流动性和市值更大的50ETF分别代替宽指ETF，500与300ETF保留一个
    
    g.stock_num = 1 #买入评分最高的前stock_num只股票
    g.momentum_day = 20 #最新动量参考最近momentum_day的
    g.ref_stock = '000300.XSHG' #用ref_stock做择时计算的基础数据
    g.N = 18 # 计算最新斜率slope，拟合度r2参考最近N天
    g.M = 600 # 计算最新标准分zscore，rsrs_score参考最近M天
    g.score_threshold = 0.7 # rsrs标准分指标阈值
    g.slope_series = initial_slope_series() # 除去回测第一天的slope，避免运行时重复加入
    g.checktime = '13:00'
    g.checktime2 = '13:50'
    g.hold = ''
    
    run_daily(my_trade, time='9:30', reference_security='000300.XSHG')
    run_daily(check_lose, time='open', reference_security='000300.XSHG')
    # run_daily(print_trade_info, time='15:30', reference_security='000300.XSHG')
    run_daily(hold_check,time=g.checktime)

## 持仓检查，盘中动态止损：早盘结束后，若60分钟周期跌破MA20均线则卖出 
def hold_check(context):
    N = 20
    hour = context.current_dt.hour
    minute = context.current_dt.minute
    if context.portfolio.positions:
        if hour == int(g.checktime.split(':')[0]) and minute == int(g.checktime.split(':')[-1]):
            for stk in context.portfolio.positions:
                dt = attribute_history(stk,N+2,'60m',['close'])
                dt['man'] = dt.close/dt.close.rolling(N).mean()
                if (dt.man[-1] < 1.0):
                    order_target_value(stk,0)
                    log.info('盘中止损',stk)
                    g.hold = stk
    else: return

# def check_buy_back(context):
#     N = 20
#     hour = context.current_dt.hour
#     minute = context.current_dt.minute
#     if not context.portfolio.positions:
#         if hour == int(g.checktime2.split(':')[0]) and minute == int(g.checktime2.split(':')[-1]):
#             dt = attribute_history(g.hold,N+2,'60m',['close'])
#             dt['man'] = dt.close/dt.close.rolling(N).mean()
#             if (dt.man[-1] >= 1.0):
#                 order_target_value(g.hold,context.portfolio.available_cash)
#                 log.info('盘中买回',g.hold)
#     else: return

## 动量因子：由收益率动量改为相对MA90均线的乖离动量
def get_rank(context,stock_pool):
    rank,biasN = [], 90
    for stock in g.stock_pool:
        data = attribute_history(stock, biasN + g.momentum_day, '1d', ['close'])
        bias = (data.close/data.close.rolling(biasN).mean())[-g.momentum_day:] # 乖离因子
        score = np.polyfit(np.arange(g.momentum_day),bias/bias[0],1)[0].real # 乖离动量拟合

        # data = attribute_history(stock, g.momentum_day, '1d', ['close'])
        # score = np.polyfit(np.arange(g.momentum_day),data.close/data.close[0],1)[0].real # 乖离动量拟合
        rank.append([stock, score])
    rank.sort(key=lambda x: x[-1],reverse=True)
    return rank[0]

## 线性回归：复现statsmodels的get_OLS函数
def get_ols(x, y):
    slope, intercept = np.polyfit(x, y, 1)
    r2 = 1 - (sum((y - (slope * x + intercept))**2) / ((len(y) - 1) * np.var(y, ddof=1)))
    return (intercept, slope, r2)

## 因子标准化
def get_zscore(slope_series):
    mean = np.mean(slope_series)
    std = np.std(slope_series)
    return (slope_series[-1] - mean) / std


#### 择时过程  ----->--------------------------------------------
def initial_slope_series():
    data = attribute_history(g.ref_stock, g.N + g.M, '1d', ['high', 'low'])
    return [get_ols(data.low[i:i+g.N], data.high[i:i+g.N])[1] for i in range(g.M)]

# 只看RSRS因子值作为买入、持有和清仓依据，前版本还加入了移动均线的上行作为条件
def get_timing_signal(context,stock):
    get_north_money(context)
    data = attribute_history(g.ref_stock, 18, '1d', ['high', 'low','volume'])
    intercept, slope, r2 = get_ols(data.low, data.high)
    g.slope_series.append(slope)
    rsrs_score = get_zscore(g.slope_series[-g.M:]) * r2
    # log.info('rsrs_score {:.3f}'.format(rsrs_score))
    if g.north_money>=0:
        if (rsrs_score > g.score_threshold) : return "BUY"
        elif (rsrs_score < -g.score_threshold): return "SELL"
        else: return "KEEP"
    else:
        return 'SELL'
        



#4-1 交易模块-自定义下单
#报单成功返回报单(不代表一定会成交),否则返回None,应用于
def order_target_value_(security, value):
# 	if value == 0:
# # 		log.debug("Selling out %s" % (security))
# 	else:
# 		log.debug("Order %s to value %f" % (security, value))
	# 如果股票停牌，创建报单会失败，order_target_value 返回None
	# 如果股票涨跌停，创建报单会成功，order_target_value 返回Order，但是报单会取消
	# 部成部撤的报单，聚宽状态是已撤，此时成交量>0，可通过成交量判断是否有成交
	return order_target_value(security, value)

#4-2 交易模块-开仓
#买入指定价值的证券,报单成功并成交(包括全部成交或部分成交,此时成交量大于0)返回True,报单失败或者报单成功但被取消(此时成交量等于0),返回False
def open_position(security, value):
	order = order_target_value_(security, value)
	if order != None and order.filled > 0:
		return True
	return False

#4-3 交易模块-平仓
#卖出指定持仓,报单成功并全部成交返回True，报单失败或者报单成功但被取消(此时成交量等于0),或者报单非全部成交,返回False
def close_position(position):
	security = position.security
	order = order_target_value_(security, 0)  # 可能会因停牌失败
	if order != None:
		if order.status == OrderStatus.held and order.filled == order.amount:
			return True
	return False

def adjust_position(context, buy_stocks):
	for stock in context.portfolio.positions:
		if stock not in buy_stocks:
# 			log.info("[%s]已不在应买入列表中" % (stock))
			position = context.portfolio.positions[stock]
			close_position(position)
		else:
		    pass
# 			log.info("[%s]已经持有无需重复买入" % (stock))
	position_count = len(context.portfolio.positions)
	if g.stock_num > position_count:
		value = context.portfolio.cash / (g.stock_num - position_count)
		for stock in buy_stocks:
			if context.portfolio.positions[stock].total_amount == 0:
				if open_position(stock, value):
					if len(context.portfolio.positions) == g.stock_num:
						break

# 交易主函数，先确定ETF最强的是谁，然后再根据择时信号判断是否需要切换或者清仓
def my_trade(context):
    
    ######
    stock_list(context)
  

    
    
    
    ######
    hour = context.current_dt.hour
    minute = context.current_dt.minute
    if hour == 9 and minute == 30:   # :30开盘时买入（标的根据昨天之前的数据算出来）
        check_out_list = get_rank(context,g.stock_pool)
        timing_signal = get_timing_signal(context,g.ref_stock)
        # print('今日自选及择时信号:{} {}'.format(check_out_list,timing_signal))
        print('context.portfolio.positions:',context.portfolio.positions)
        if timing_signal == 'SELL'  and len(context.portfolio.positions)>1:
            for stock in context.portfolio.positions :
                if stock not in ['511010.XSHG','511260.XSHG','513100.XSHG']:
                    position = context.portfolio.positions[stock]
                    close_position(position)
        elif timing_signal == 'BUY' or timing_signal == 'KEEP':
            ###
            df = history(40, unit='1d', field='close', security_list=g.stocks, df=True, skip_paused=True, fq='post')
            pre_price=df.iloc[-1]
            price_ratio=(pre_price/g.base_price).to_dict()
        
            waves=calc_volatility(df)
        
            g.position = pd.DataFrame(data={"weight": g.weights, "wave": waves})
            g.position["position"] = (g.position.weight)/ (g.position.wave ** 2)
           
            g.position["position"] = g.position["position"] / g.position["position"].sum()
            g.position["position"].loc[ g.position["position"]<0.05]=0.0
            g.position["position"] = g.position["position"] / g.position["position"].sum()
                    
            ###
            #adjust_position(context, check_out_list)
            if context.portfolio.available_cash > context.portfolio.total_value*0.02 or need_balance(context):
                rebalance(context)
        else: pass

# 这个函数几乎没用
def check_lose(context):
    for position in list(context.portfolio.positions.values()):
        securities=position.security
        cost=position.avg_cost
        price=position.price
        ret=100*(price/cost-1)
        value=position.value
        amount=position.total_amount
        if ret <=-90:
            order_target_value(position.security, 0)
            print("！！！！！！触发止损信号: 标的={},标的价值={},浮动盈亏={}% ！！！！！！"
                .format(securities,format(value,'.2f'),format(ret,'.2f')))

def print_trade_info(context):
    #打印当天成交记录
    trades = get_trades()
    for _trade in trades.values(): print('成交记录：'+str(_trade))
    #打印账户信息
    print('———————————————————————————————————————分割线————————————————————————————————————————')
    
    
def get_north_money(context):

    yesterday = context.previous_date
    # print(today.date(),'@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@')
    n_sh = finance.run_query(query(finance.STK_ML_QUOTA).filter(finance.STK_ML_QUOTA.day>='2013-01-10',finance.STK_ML_QUOTA.day <= yesterday,
                                                                finance.STK_ML_QUOTA.link_id == 310001).order_by(
        finance.STK_ML_QUOTA.day.desc()).limit(10))
    n_sz = finance.run_query(query(finance.STK_ML_QUOTA).filter(finance.STK_ML_QUOTA.day>='2017-01-10',finance.STK_ML_QUOTA.day <= yesterday,
                                                                finance.STK_ML_QUOTA.link_id == 310002).order_by(
        finance.STK_ML_QUOTA.day.desc()).limit(10))
    total_net_in = 0
    for i in range(0, 2):
        print("yesterday=",yesterday)
        if str(yesterday) > '2017-01-10':
            sh_in = n_sh['buy_amount'][i] - n_sh['sell_amount'][i]
            sz_in = n_sz['buy_amount'][i] - n_sz['sell_amount'][i]
            amount = sh_in + sz_in
            total_net_in += amount
          #  print("n+s")
        else:
            sh_in = n_sh['buy_amount'][i] - n_sh['sell_amount'][i]
           
            amount = sh_in
            total_net_in += amount
  
    g.north_money = total_net_in
    
    
def stock_list(context):
    g.stocks=[]
    check_out_list=[]
    check_out_list.append(get_rank(context,g.stock_pool)[0])
    check_out_list.append('513100.XSHG')
    check_out_list.append('511260.XSHG')
    
    print('check_out_list:',check_out_list)
    g.stocks=check_out_list
    stocksdata=[20,20,0.5]
    g.weights= pd.Series(stocksdata,index=g.stocks)
    df = history(1, unit='1d', field='close', security_list=g.stocks, df=True, skip_paused=True, fq='post')
    g.base_price=df.iloc[0]
    

def calc_volatility(df):
    df_return=np.log(df/df.shift(1)).dropna()
    s_std=df_return.std()
    s_mean=df_return.mean()
    for code in df_return.columns:
        df_return[code].loc[df_return[code] > s_mean[code] + 3 * s_std[code]] = s_mean[code] + 3 * s_std[code]
        #平均回报+3倍标准差
        df_return[code].loc[df_return[code] < s_mean[code] - 3 * s_std[code]] = s_mean[code] - 3 * s_std[code]
        ##平均回报-3倍标准差
    return df_return.std() * math.sqrt(250.0) * 100
    
def need_balance(context):
    position = g.position
    x = 0.0
    for s in position.index.values:
        p = position.position[s]
        #根据初始化权重和wave计算仓位
        r = p
        if s in context.portfolio.positions.keys():
            #持仓股票
            r = context.portfolio.positions[s].value / context.portfolio.total_value
            #计算每个股票的仓位占比
        x += abs(r - p)

    return x > 0.05
    #判断计算的仓位和实际仓位权重相差5%，是否要调仓


def rebalance(context):
    p = g.position
    sells = []
    cur =get_current_data()
    #先减仓，释放现金，再加仓
    for code in p.index.values:
        position = p.position.loc[code]
        target_value=context.portfolio.total_value*position
        if code in context.portfolio.positions:
            old_position = context.portfolio.positions[code].value / context.portfolio.total_value
            if old_position > position:
                if cur[code].last_price*100<abs(context.portfolio.positions[code].value-context.portfolio.total_value * position):
                    order_target_value(code, context.portfolio.total_value * position)
                    sells.append(code)

    for code in p.index.values:
        position = p.position.loc[code]
        target_value=context.portfolio.total_value*position
        add_value = target_value-context.portfolio.positions[code].value if code in context.portfolio.positions else target_value
        can_add_value = add_value if context.portfolio.available_cash> add_value else context.portfolio.available_cash
        can_buy= (code not in context.portfolio.positions and cur[code].last_price*100<context.portfolio.total_value * position)  or (code  in context.portfolio.positions and cur[code].last_price*100<abs(context.portfolio.positions[code].value-context.portfolio.total_value * position))
        if code not in sells and can_buy and can_add_value>cur[code].last_price*100:
            order_value(code, can_add_value)
    
