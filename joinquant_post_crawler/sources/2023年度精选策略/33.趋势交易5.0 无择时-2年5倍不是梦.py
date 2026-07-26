# 克隆自聚宽文章：https://www.joinquant.com/post/31286
# 标题：趋势交易5.0 无择时-2年5倍不是梦
# 作者：矢南

#趋势交易5.0
#by:矢南


# 导入函数库
from jqdata import *
from scipy.stats import linregress



# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    #过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
      # 开盘时运行
    run_daily(market_open, time='open', reference_security='000300.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')
    
    #选股
    g.buy_list = []


## 开盘前运行函数
def before_market_open(context):
    
    
    # 输出运行时间
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))



## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    log.info('一天结束')
    log.info('##############################################################')



# 交易函数
def orderStocks(context):
    current_data = get_current_data()
    # 获取 buy_lists 列表
    buy_lists = g.buy_list
    # 卖出操作
    for s in context.portfolio.positions:
        if s not in buy_lists:
            _order = order_target_value(s, 0)
            if _order is not None:
                log.info('卖出: %s (%s)' % (get_security_info(s).display_name, s))
                
    if buy_lists:
        amount = context.portfolio.total_value / len(buy_lists)
        for stock in buy_lists:
            if stock in context.portfolio.positions:
                _order = order_target_value(stock, amount)
                if _order is not None:
                    log.info('调仓: %s (%s)' % (get_security_info(stock).display_name, stock))

        for stock in buy_lists:
            if stock not in context.portfolio.positions:
                _order = order_target_value(stock, amount)
                if _order is not None:
                    log.info('买入: %s (%s)' % (get_security_info(stock).display_name, stock))

## 开盘时运行函数
def market_open(context):
    
    current_data = get_current_data()
    
    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    # 获取所有沪深300的股票, 设为股票池
    indexs = get_index_stocks('000300.XSHG')
    #去掉掉科创板的
    indexs = [ii for ii in indexs if not ii.startswith('688')]

    df0 = history(100,'1d',field='close',security_list=indexs,df=True,skip_paused=True,fq='pre')
    df = df0.T
    df.fillna(method='ffill',inplace=True)
    df['ma100'] = df.mean(axis=1)
    df['ma60'] = (df0.iloc[-60:]).T.mean(axis=1)
    df['ma30'] = (df0.iloc[-30:]).T.mean(axis=1)

    #筛选多头的
    df = df[(df[99]>df.ma100) & (df.ma30>df.ma60) & (df.ma60>df.ma100)]
    
    stocks = []
    g.buy_list = []
    #趋势排名
    if len(df)>0:
        x = np.arange(100)
        lis = [linregress(x,df.iloc[ii][:100])[0:3] for ii in range(len(df))]
        df['k'] = [ii[0] for ii in lis]
        df['i'] = [ii[1] for ii in lis]
        df['k_i'] = df.k/df.i
        df['R'] = [ii[2] for ii in lis]
        df = df[(df.R>0.5) & (df.k_i>0.005)]
        df.sort_values('k',ascending=False,inplace=True)
        
        if len(df)>0:
            stocks = df.index.tolist()
            
            # 近30个交易日的最高价 / 昨收盘价 <=1.1, 即HHV(HIGH,30)/C[-1] <= 1.1
            close_1 = history(1, '1d', 'close', stocks).iloc[-1]
            high_max_30 = history(30, '1d', 'high', stocks).max()
            s_fall = high_max_30 / close_1
            stocks = list(s_fall[s_fall <= 1.1].index)
    
            # 近7个交易日的交易量均值 与 近180给交易日的成交量均值 相比，放大不超过2倍  MA(VOL,7)/MA(VOL,180) <=1.5
            df_vol = history(180, '1d', 'volume', stocks)
            s_vol_ratio = df_vol.iloc[-7:].mean() / df_vol.mean()
            stocks = list(s_vol_ratio[s_vol_ratio <= 1.5].index)
    
            g.buy_list = stocks[:5]
    
    # 交易函数
    orderStocks(context)    

