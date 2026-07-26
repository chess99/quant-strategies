# 克隆自聚宽文章：https://www.joinquant.com/post/28789
# 标题：昨日炸板股策略
# 作者：WiseFurther

# 导入函数库
from jqdata import *
import talib

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')
    # 股票池
    g.stock_pool = []
    # 当天股票池行情数据缓存
    g.stock_cache = None
    # 当日盘前时间
    g.run_time = None
    # 持仓票信息
    g.hold_info = None
    # 最大持仓数量
    g.max_hold = 3
    # 当天交易信号
    g.trade_signal = True
    # 存放昨日触及到涨停板的行情
    g.df_high_limit = None
    # 用来止损使用的大盘指数，以确定当天是否交易
    g.stop_loss_index = ['000001.XSHG','399001.XSHE','399005.XSHE']
    # 存放昨日指数收盘价
    g.pre_close_index = dict()
    

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')

## 开盘前筛选昨日涨停票
def before_market_open(context):
    log.info('开盘筛选股票池：'+str(context.current_dt))
    securities = get_index_stocks('000001.XSHG')+get_index_stocks('399001.XSHE')
    # securities = ['600636.XSHG']
    end_date = context.previous_date
    securities = filter_st(securities, end_date)
    df = get_price(securities, fields=['open','high','low','close','high_limit','paused'], end_date=end_date, count=1, panel=False).set_index('code', drop=True)
    # 选出昨日炸板股
    g.df_high_limit = df[(df.high >= df.high_limit) & (df.close < df.high_limit) & (df.paused == 0)]
    # 过滤掉昨日一字开板被炸的票
    # g.df_high_limit = g.df_high_limit[g.df_high_limit.open < g.df_high_limit.high_limit]
    # 过滤掉昨日被炸且收阴的票
    g.df_high_limit = g.df_high_limit[g.df_high_limit.open < g.df_high_limit.close]
    g.stock_pool = list(g.df_high_limit.index)
    # 缓存股票池当天的分钟数据，仅在回测中使用，目的是提高回测速度，但有未来函数之嫌
    g.stock_cache = None
    if g.stock_pool:
        print(g.stock_pool)
        date = context.current_dt+datetime.timedelta(days=1)
        df_tmp = get_price(g.stock_pool, end_date=date, frequency='1m', count=240, fields=['close','high_limit'], panel=False)
        g.stock_cache = df_tmp.set_index(['time', 'code'], drop=True)
    g.run_time = context.current_dt
    g.hold_info = pd.DataFrame()
    for stock in context.portfolio.positions:
        g.hold_info = g.hold_info.append(df.loc[stock])
    print('hold_info: %s' % g.hold_info)
    # 使用上证指数、深证成指、中小板指是否站在MA5之上作为判断是否交易的信号
    df_idx = get_price(g.stop_loss_index, fields='close', end_date=end_date, count=5, panel=False)
    df_gp = df_idx.groupby(['code'])['close'].mean()
    on_ma5_num = 0
    for idx in g.stop_loss_index:
        pre_close = df_idx[df_idx.code == idx].iloc[-1].close
        if pre_close >= df_idx.groupby(['code'])['close'].mean()[idx]:
            on_ma5_num += 1
        g.pre_close_index[idx] = pre_close
    # 至少2个指数站上MA5才交易
    if on_ma5_num >= 2:
        g.trade_signal = True
    else:
        g.trade_signal = False
    # 计算上证综指MACD 判断是否交易
    if g.trade_signal:
        df_idx = get_price('000001.XSHG', end_date=end_date, count=35, fields='close')
        array = np.array(df_idx['close'])
        df_idx['macd'], df_idx['macdsignal'], df_idx['macdhist'] = talib.MACD(array, fastperiod=12, slowperiod=26, signalperiod=9)
        if df_idx['macdhist'][-1] < df_idx['macdhist'][-2]:
            g.trade_signal = False
    

## 开盘时运行函数
def handle_data(context, data):
    cur_data = get_current_data()
    if context.current_dt.hour == 9 and context.current_dt.minute == 30:
        if g.trade_signal == True:
            # 根据指数开盘情况确定当日是否交易
            open_down = 0
            for idx in g.stop_loss_index:
                if cur_data[idx].day_open < g.pre_close_index[idx]*0.99:
                    open_down += 1
            print('open_down:%s' % open_down)
            if open_down >= 2:
                g.trade_signal = False
        return
    sell_list = []
    for stock in context.portfolio.positions:
        if g.hold_info.empty or stock not in g.hold_info.index:
            continue
        tod_price = cur_data[stock]
        pre_close = g.hold_info.loc[stock].close
        # 昨日未涨停
        if stock not in g.stock_pool:
            # 低开翻红即卖
            if tod_price.day_open < pre_close and tod_price.last_price >= pre_close:
                sell_list.append(stock)
                continue
        # 尾盘
        if context.current_dt.hour == 14 and context.current_dt.minute == 50:
            # 未涨停即卖
            if tod_price.last_price < pre_close*1.099:
                sell_list.append(stock)
                continue

        if tod_price.last_price <= pre_close*0.93:
            sell_list.append(stock)
        elif tod_price.last_price <= tod_price.day_open*0.95:
            sell_list.append(stock)
        else: 
            # 已确认，此处无未来函数
            df = get_price(stock, start_date=g.run_time, end_date=context.current_dt, frequency='1m', fields=['close','high', 'high_limit'], panel=False)
            if tod_price.last_price <= df.high.max()*0.93:
                sell_list.append(stock)

    for stock in sell_list:
        # 记录这次卖出
        log.info("卖出 %s" % (stock))
        order_target_value(stock, 0)
        # 当天卖出的不再买入
        if stock in g.stock_pool:
            g.stock_pool.remove(stock)

    if not g.trade_signal:
        return
    
    # 10点后不买票
    if context.current_dt.hour >= 10:
        return
    
    remain_position = g.max_hold - len(context.portfolio.positions)
    if not g.stock_pool or remain_position <= 0 :
        return
    
    buy_list = []
    # 模拟时应使用此段代码
    '''
    for stock in g.stock_pool:
        # 此处无未来函数
        df = get_price(stock, start_date=g.run_time, end_date=context.current_dt, frequency='1m', fields=['close','high', 'high_limit'], panel=False)
        if cur_data[stock].last_price >= df.high_limit.max()*0.991:
            buy_list.append(stock)
    '''
    # 回测时取巧，从缓存中取数据
    for stock in list(g.stock_pool):
        # 过滤掉开盘价即高于昨日阳线实体高位的票
        open = g.df_high_limit.loc[stock].open
        close = g.df_high_limit.loc[stock].close
        h = open if open >= close else close
        # 过滤掉开盘价即高于昨日最高价的票
        if cur_data[stock].day_open >= g.df_high_limit.loc[stock].high:
        # if cur_data[stock].day_open >= h:
            g.stock_pool.remove(stock)
            continue
        # 过滤掉昨日长上影的票
        if (g.df_high_limit.loc[stock].high - h)/(g.df_high_limit.loc[stock].high - g.df_high_limit.loc[stock].low) >= 0.3:
            g.stock_pool.remove(stock)
            continue
        
        try:
            s = g.stock_cache.loc[str(context.current_dt), stock]
            if s.close >= g.df_high_limit.loc[stock].high:
                buy_list.append(stock)
        except:
            pass
            
    if not buy_list:
        return
    
    buy_list = buy_list if len(buy_list)<=remain_position else buy_list[:remain_position]
    # 单只股票买入金额
    cash = context.portfolio.available_cash/remain_position

    for stock in buy_list:
        if stock in context.portfolio.positions or cur_data[stock].last_price == cur_data[stock].high_limit:
            continue
        # 记录这次买入
        log.info("买入 %s" % (stock))
        order_target_value(stock, cash)

## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    log.info('一天结束')
    log.info('##############################################################')
    
#自定义函数去除st股票-学习自蒋老师
def filter_st(stocks,rq):
   datas = get_extras('is_st',stocks,end_date = rq ,count=1).T
   return  datas[~datas.iloc[:,0]].index.tolist()


