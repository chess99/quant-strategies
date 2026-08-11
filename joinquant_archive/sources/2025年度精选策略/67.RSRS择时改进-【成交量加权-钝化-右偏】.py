# 克隆自聚宽文章：https://www.joinquant.com/post/27399
# 标题：RSRS择时改进-【成交量加权-钝化-右偏】
# 作者：uuyue

# 成交量加权的4种RSRS #
# 成交量加权-右偏标准分        vol_rsrs_right      = zscore*beta*r2   
# 成交量加权-钝化-右偏标准分   vol_rsrs_right_dun  = zscore*beta*(r2**(2*stdpercent)) 
# 成交量加权-无偏标准分        vol_rsrs            = zscore*r2 
# 成交量加权-钝化-无偏标准分   vol_rsrs_dun        = zscore*(r2**(2*stdpercent))  

import statsmodels.api as sm
import scipy.stats as stats

def initialize(context):
    g.security = '000300.XSHG'

    # 成交量加权-右偏标准分
    g.N = 18
    g.M = 200
    g.buy = 0.85
    g.sell = -g.buy
    g.run_time = '14:00'  #14:00
    
    '''
    #成交量加权-钝化-右偏标准分
    g.N = 18
    g.M = 200
    g.buy = 0.75
    g.sell = -g.buy
    g.run_time = '14:00'
    
    #成交量加权-无偏标准分   
    g.N = 17
    g.M = 1300
    g.buy = 0.9
    g.sell = -g.buy
    g.run_time = '9:30'  
    
    #成交量加权-钝化-无偏标准分    
    g.N = 16
    g.M = 1100
    g.buy = 0.7
    g.sell = -g.buy
    g.run_time = '9:30' 
    '''
    # 中间变量
    g.beta_weight = []
    g.r2_weight = []
    g.volatility = []
    g.pos = False
    g.days = 0
    g.rsrs = 0
  
    set_option("avoid_future_data", True)
    set_option('order_volume_ratio', 0.002)  # 成交量不得超过标的日成交量的千分之2
    set_option('use_real_price', True)    # 开启动态复权模式(真实价格)
    set_benchmark('000300.XSHG')    # 设定上证指数作为基准
    log.set_level('order', 'error')    # 过滤掉order系列API产生的比error级别低的log
    
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='fund')
    set_slippage(PriceRelatedSlippage(0.00246),type='fund')
   
    run_daily(before_market_open, time = 'before_open', reference_security='000300.XSHG') 
    run_daily(market_open, time = g.run_time, reference_security='000300.XSHG')
    run_daily(after_market_close, time = 'after_close', reference_security='000300.XSHG')

    # 计算2005年1月5日至回测开始日期的RSRS斜率指标    #context.previous_date + timedelta(days = -1)
    prices = get_price(g.security, '2005-05-01', context.previous_date, '1d', ['high', 'low', 'volume'])
    highs = prices.high
    lows = prices.low
    volumes = prices.volume
    weight_list = []
    
    for i in range(0, len(highs)-g.N+1):  #range(a,b)=[a,b)
        data_high = highs.iloc[i :i+g.N]  #dataframe 不包括[a:b]中的b，相当于[a:b)
        data_low  = lows.iloc[i :i+g.N]
        data_volume = volumes.iloc[i :i+g.N]
        X = sm.add_constant(data_low)  #为模型增加常数项，即回归线在y轴上的截距(括号里面写上自变量)
        # 处理报错：exog contains inf or nans
        #X[np.isnan(X)] = 0  #把X中的空值令为0
        #X[np.isinf(X)] = 0  #把无穷大的数据令为0
        
        # 成交量加权的权重列表
        for j in range(0, len(data_volume)):  #len(data_volume)=g.N=18,  j=0到17
            weight = data_volume[j]/data_volume.sum()
            weight_list.append(weight)

        model = sm.WLS(data_high, X, weight_list)  # 加权最小二乘法
        g.beta_weight.append(model.fit().params.low)
        g.r2_weight.append(model.fit().rsquared)
        weight_list = []
    
    #log.info('prices的长度=%s, g.beta_weight的长度=%s, g.r2_weight的长度=%s' % (len(prices),len(g.beta_weight),len(g.r2_weight)))
        
    #计算2005-01-01至开盘前一天的指数日收益率的波动率
    close = get_price(g.security,'2005-05-01', context.previous_date, '1d', 'close')['close']
    daily_return =  (close-close.shift(1))/close.shift(1)
    daily_return=list(daily_return.dropna())
    for i in range(len(daily_return))[g.N:]:
        std = np.std(daily_return[i-g.N:i])
        g.volatility.append(std)
    

def before_market_open(context):
    beta = 0
    r2 = 0
    weights = []
    
    if g.days == 0:
        g.days = 1
    elif g.days == 1:
        
        # 计算各种RSRS
        prices = attribute_history(g.security, g.N, '1d', ['high','low','volume'])
        highs = prices['high']
        lows = prices['low']
        volumes = prices['volume']
        X = sm.add_constant(lows)      # sm计算OLS时，左侧要补一列常数
        
        # 成交量加权的权重列表
        for i in range(0,len(prices)):
            weight = volumes[i]/volumes.sum()
            weights.append(weight)
        
        # 加权最小二乘法  #sm.WLS(y, X, weights)
        model = sm.WLS(highs, X, weights)
        beta = model.fit().params.low
        g.beta_weight.append(beta)
        r2 = model.fit().rsquared
        g.r2_weight.append(r2)        
        
        # 标准化/归一化
        section = g.beta_weight[-g.M:]
        mu = np.mean(section)
        sigma = np.std(section)
        zscore = (section[-1]-mu)/sigma
        
        # 计算N日收益率的标准差、M日收益率标准差的分位数（钝化RSRS所需）     
        # 用过去g.N天的数据,计算波动率,并获取它在过去g.M所处的百分位
        close = attribute_history(g.security, g.N+1, '1d', ['close'])['close']
        daily_return =  (close-close.shift(1))/close.shift(1)
        daily_return = list(daily_return.dropna())
        std = np.std(daily_return)                                           #计算N日收益率的标准差
        g.volatility.append(std)
        stdpercent = stats.percentileofscore(g.volatility[-g.M:], std)/100   #计算M日收益率标准差的分位数
        
        vol_rsrs_right = zscore*beta*r2                        #成交量加权-右偏标准分
        vol_rsrs = zscore*r2                                   #成交量加权-无偏标准分
        vol_rsrs_right_dun = zscore*beta*(r2**(2*stdpercent))  #钝化-成交量加权-右偏标准分
        vol_rsrs_dun = zscore*(r2**(2*stdpercent))             #钝化-成交量加权-无偏标准分
        
        log.info('zscore= %s, beta= %s, r2= %s, std= %s, stdpercent= %s'% (round(zscore,3),round(beta,3),round(r2,3),round(std,3),round(stdpercent,3)))
        log.info('成交量加权-右偏rsrs     = %s，成交量加权-无偏rsrs     = %s' % (round(vol_rsrs_right,3), round(vol_rsrs,3)))
        log.info('钝化-成交量加权-右偏rsrs= %s，钝化-成交量加权-无偏rsrs= %s' % (round(vol_rsrs_right_dun,3), round(vol_rsrs_dun,3)))
       
        # 成交量加权-右偏标准分        vol_rsrs_right      = zscore*beta*r2   
        # 成交量加权-钝化-右偏标准分   vol_rsrs_right_dun  = zscore*beta*(r2**(2*stdpercent)) 
        # 成交量加权-无偏标准分        vol_rsrs            = zscore*r2 
        # 成交量加权-钝化-无偏标准分   vol_rsrs_dun        = zscore*(r2**(2*stdpercent))  
        g.rsrs = vol_rsrs_right
        log.info('g.rsrs=%s' % round(g.rsrs,3))


def market_open(context):
    if g.rsrs > g.buy and g.pos==False:
        log.info('buy')
        order_value(g.security, context.portfolio.available_cash)
        g.pos = True
    elif g.rsrs < g.sell and g.pos==True:
        log.info('sell')
        order_target(g.security, 0)
        g.pos = False
 
def after_market_close(context):
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    log.info('##############################################################')
