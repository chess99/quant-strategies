# 克隆自聚宽文章：https://www.joinquant.com/post/24680
# 标题：基于RSRS的趋势交易与网格交易相结合的尝试
# 作者：最爱苹果

# 导入函数库
import statsmodels.api as sm
import numpy as np
import talib

# 初始化函数，设定基准等等
def initialize(context):
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    set_parameter(context)
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.00015, close_commission=0.00015, min_commission=0.1), type='stock')
    g.slippage=0.02 #设置滑点
    #set_slippage(PriceRelatedSlippage(g.slippage),type='stock')
      # 开盘时运行
    run_daily(market_open, time='every_bar')

'''
==============================参数设置部分================================
'''
def set_parameter(context):
    #网格参数设定
    g.gear=2 #网格档位，原为2
    g.NATRstop = 2 # 以ATR倍数表示的网格上限,原为2
    g.ATR_period=20 # ATR计算周期
    g.position = 1/(g.gear+1) #每次投入仓位
    g.cash = context.portfolio.available_cash*g.position #初始投入金额
    g.Buy_tag=[0]*(g.gear+1) #每个网格只许买入一次，未买标记为0,已买标记为1
    g.last_buy_tag=0
    #风险参考基准
    g.security = '000300.XSHG'
    # 设定策略运行基准
    set_benchmark(g.security)
    # 设置RSRS指标中N, M的值
    #统计周期
    g.N = 18
    #统计样本长度
    g.M = 1100
    #首次运行判断
    g.init = True
    # 买入阈值
    g.buy = 0.7
    g.sell = -0.7
    #用于记录回归后的beta值，即斜率
    g.ans = []
    #用于计算被决定系数加权修正后的贝塔值
    g.ans_rightdev= []
    # 计算2005年1月5日至回测开始日期的RSRS斜率指标
    prices = get_price(g.security, '2005-01-05', context.previous_date, '1d', ['high', 'low'])
    prices[np.isnan(prices)] = 0
    prices[np.isinf(prices)] = 0
    highs = prices.high
    lows = prices.low
    g.ans = []
    for i in range(len(highs))[g.N:]:
        data_high = highs.iloc[i-g.N+1:i+1]
        data_low = lows.iloc[i-g.N+1:i+1]
        X = sm.add_constant(data_low)
        model = sm.OLS(data_high,X)
        results = model.fit()
        g.ans.append(results.params[1])
        #计算r2
        g.ans_rightdev.append(results.rsquared)

## 开盘时运行函数
def market_open(context):
    security = g.security
    cash = g.cash
    g.LastRealPrice = history(1, '1m', 'close', security, df=False,skip_paused=True).get(security)[0] #取最新即时价格
    # 填入各个日期的RSRS斜率值
    if context.current_dt.hour==9 and context.current_dt.minute==30:
        beta=0
        r2=0
        if g.init:
            g.init = False
        else:
            #RSRS斜率指标定义
            prices = attribute_history(security, g.N, '1d', ['high', 'low'])#获取过去g.n（18）天的最高价、最低价
            prices[np.isnan(prices)] = 0
            prices[np.isinf(prices)] = 0
            highs = prices.high#最高价
            lows = prices.low#最低价
            X = sm.add_constant(lows)#线性回归X
            model = sm.OLS(highs, X)#线性回归结果
            beta = model.fit().params[1]
            g.ans.append(beta)#回归后的beta值，即斜率
            #计算r2
            r2=model.fit().rsquared    
            g.ans_rightdev.append(r2)#用于计算被决定系数加权修正后的贝塔值
        # 计算标准化的RSRS指标
        section = g.ans[-g.M:]
        # 计算均值序列
        mu = np.mean(section)
        # 计算标准化RSRS指标序列
        sigma = np.std(section)
        zscore = (section[-1]-mu)/sigma  
        #计算右偏RSRS标准分
        zscore_rightdev= zscore*beta*r2

        # 如果上一时间点的RSRS斜率大于买入阈值, 则全仓买入
        if (security not in context.portfolio.positions.keys()) and zscore_rightdev > g.buy and context.portfolio.available_cash>=0:
            # 记录这次买入
            log.info("标准化RSRS斜率大于买入阈值, 买入 %s" % (security))
            # 用所有 cash 买入股票
            buy_amount=floor(cash/(g.LastRealPrice*(1+g.slippage/2))/100)*100
            orders=order(security, buy_amount)
            if order is None:
                log.info("创建订单失败...")
            else:
                g.Buy_tag[0]=1 #标记已买
                g.buy_price=orders.price #记录本次买入订单的成交均价
                g.ATR_buy=ATR(context,security) #以建仓时的ATR为标准计算网格
                g.Stop_price=g.buy_price+g.NATRstop*g.ATR_buy #网格价格上限
                g.Price_list=linspace(g.buy_price,g.Stop_price,g.gear+1) #计算网格各档位价格，ATR太小，等比数列没有结果，只能算等差数列
                g.Price_list=[round(x,2) for x in g.Price_list] #对各档位价格做四舍六入，注意不是四舍五入
        # 如果上一时间点的RSRS斜率小于卖出阈值, 则空仓卖出
        elif zscore_rightdev < g.sell and (security in context.portfolio.positions.keys()) and context.portfolio.positions[security].closeable_amount > 0:
            # 记录这次卖出
            log.info("标准化RSRS斜率小于卖出阈值, 卖出 %s" % (security))
            # 卖出所有股票,使这只股票的最终持有量为0
            order_target(security, 0)
            g.cash=context.portfolio.available_cash*g.position
            g.Buy_tag=[0]*(g.gear+1) #标记已卖
            g.last_buy_tag=0
    #执行网格交易
    if (security in context.portfolio.positions.keys()) and context.portfolio.positions[security].closeable_amount > 0:
        for n in range(1,g.gear+1,1):
            if ((n<g.gear and g.LastRealPrice>=g.Price_list[n] and g.LastRealPrice<g.Price_list[n+1]) or (n==g.gear and g.LastRealPrice>=g.Price_list[n])) and g.Buy_tag[n]==0:
                log.info("网格交易买入第%s档" %n)
                buy_amount=floor((n-g.last_buy_tag)*cash/(g.LastRealPrice*(1+g.slippage/2))/100)*100
                order(security, buy_amount)
                for a in range(g.last_buy_tag+1,n+1,1):
                    g.Buy_tag[a]=1 #标记已买
                g.last_buy_tag=n

def ATR(context,stock):
    PriceArray= get_price(stock, '2005-01-05', context.previous_date, '1d', ['close','high','low'])
    PriceArray[np.isnan(PriceArray)] = 0
    PriceArray[np.isinf(PriceArray)] = 0
    close = np.array(PriceArray['close'])
    high = np.array(PriceArray['high'])
    low = np.array(PriceArray['low'])
    ATR = talib.ATR(high,low,close, g.ATR_period)[-1]
    return ATR
