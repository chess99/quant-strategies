# 克隆自聚宽文章：https://www.joinquant.com/post/29165
# 标题：ETF宽基轮动修改版-1.0
# 作者：几米哥

# 克隆自聚宽文章：https://www.joinquant.com/post/22833
# 标题：ETF宽基轮动修改版v1
# 作者：Jimmy

from jqdata import *

g.lag1 = 20  #比价周期，原始值13
g.lag2 = 10  #均线周期，原始值13
g.ma_threshold = 0.9 #ma的90%容限阈值
g.mtm_threshold = 2 #2%的20天涨幅阈值，不到就买债券
g.ETFList = np.array([
    ['513100.XSHG','513100.XSHG'], #纳指ETF
    ['513500.XSHG','513500.XSHG'], #标普500ETF
    ['518880.XSHG','518880.XSHG'], #黄金ETF
    ['399006.XSHE','159915.XSHE'], #创业板
    ['000300.XSHG','510300.XSHG'], #沪深300
    ['000905.XSHG','510500.XSHG'], #中证500
    ['159920.XSHE','159920.XSHE']  #恒生ETF
])

'''
=================================================
总体回测前设置参数和回测
=================================================
'''
def initialize(context):
    set_params()    #设置参数
    set_backtest()  #设置回测条件
    run_daily(ETFtrade1, time='10:30') #信号确认
    run_daily(ETFtrade2, time='14:30') #下单交易
    
# 设置参数
def set_params():
    # 设置基准收益
    set_benchmark('000300.XSHG') #比沪深300差的最多

# 设置回测条件
def set_backtest():
    set_option('use_real_price', True) #用真实价格交易
    log.set_level('order', 'error')

#每天开盘前要做的事情
def before_trading_start(context):
    set_slip_fee(context) 

# 根据不同的时间段设置滑点与手续费
def set_slip_fee(context):
    # 将滑点设置为0
    set_slippage(FixedSlippage(0)) 
    # 根据不同的时间段设置手续费
    set_commission(PerTrade(buy_cost=0.0005, sell_cost=0.0005, min_cost=5)) 

'''
=================================================
每日信号确认及交易
=================================================
'''
def ETFtrade1(context): #信号确认函数
    buy_list, g.buy_list_weights = get_signal(context)#产生购买标的
    # print(buy_list.size)
    # print(type(buy_list))
    if buy_list.size == 1 and isinstance(buy_list, np.str_): # 如果只返回一个code，有可能是字符串类型
        g.buy_list = list(buy_list.split())
    else: # return a list
        g.buy_list = list(buy_list)
    print(g.buy_list)
    
def ETFtrade2(context): #交易函数
    sell_the_stocks(context, g.buy_list) #卖出持仓股票
    buy_the_stocks(context, g.buy_list, g.buy_list_weights) #买入股票

#获取交易信号
def get_signal(context):
    i=0 # 计数器初始化
    df = pd.DataFrame()
    for row in g.ETFList:
        security = row[0]
    # 获取指数的历史收盘价
        close_data = attribute_history(security, g.lag1, '1d', ['close'],df=False) #df为False返回的是dict类型
    # 获取指数当前收盘价
        current_data = get_current_data() #获取当前时间数据
        current_price = current_data[security].last_price
    # 获取指数票的阶段收盘价涨幅百分比
        cp_increase = 100*(current_price/close_data['close'][0]-1)
    # 获取指数的收盘价
        close_data = attribute_history(security, g.lag2, '1d', ['close'],df=False)
    # 取得过去 g.lag2 天的平均价格
        ma_n1 = (current_price+close_data['close'].sum()-close_data['close'][0])/g.lag2
    # 计算最新收盘价与均线差值    
        pre_price = current_price - ma_n1*g.ma_threshold #10%的阈值，防止假摔
        df.loc[i,'代码'] = row[1] # 把标的股票代码添加到DataFrame
        df.loc[i,'涨幅'] = cp_increase # 把计算结果添加到DataFrame
        df.loc[i,'均线差'] = pre_price # 把计算结果添加到DataFrame
        i=i+1
        
    # 对计算结果表格进行排序
    df.sort_values(by='涨幅',ascending=False,inplace=True) # 按照涨幅排序
    df.reset_index(drop=True, inplace=True) # 把序列号drop掉！
    log.info("行情表格:\n %s" % (df)) # 输出计算结果
    
    df_buy = df[(df['涨幅'] > g.mtm_threshold) & (df['均线差'] > 0)] #涨幅可调整，用来控制权重
    df_buy.set_index('代码', inplace=True)
    
    print(df_buy.iloc[0:4, 0]/df_buy.iloc[0:4, 0].sum()) #计算权重
    
    if len(df_buy) > 0: # 有强势的，买股票
        return df_buy.index[0:4], df_buy.iloc[0:4, 0]/df_buy.iloc[0:4, 0].sum()
    else: # 没强势的，买债券
        # return np.array(['511220.XSHG'], dtype=np.str_)[0] #城投ETF 2015年开始的回测
        return np.array(['511010.XSHG'], dtype=np.str_)[0], pd.Series([1],index=['511010.XSHG']) #国债ETF 2014年开始的回测, 100%
        
        
#获得卖出信号，并执行卖出操作
#输入：context, buy_list
#输出：none
def sell_the_stocks(context, buy_list):
    #如果现有持仓股票不在股票池，清空
    list_position=context.portfolio.positions.keys()
    for stock in list_position:
        if stock not in buy_list:
            order_target_value(stock, 0)
            log.info("正在卖出 %s" % stock)

#获得买入信号，并执行买入操作
#输入：context,buy_list
#输出：none
def buy_the_stocks(context, buy_list, buy_list_weights):
    # 对于不需要持仓的股票，按分配到的份额买入
    # list_position=context.portfolio.positions.keys()
    g.everyStock=context.portfolio.portfolio_value/len(buy_list)
    
    for stock in buy_list:
        # order_target_value(stock, g.everyStock)
        order_target_value(stock, buy_list_weights.loc[stock]*context.portfolio.portfolio_value)
        log.info("正在买入 %s, 百分比为：%s", stock, buy_list_weights.loc[stock])
