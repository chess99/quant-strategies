# 克隆自聚宽文章：https://www.joinquant.com/post/30551
# 标题：敢于直接实盘的—八仙过海V2
# 作者：Funine

from jqdata import *
import pandas as pd
import talib

def initialize(context):
    set_params()
    #
    set_option("avoid_future_data",True)
    set_option('use_real_price', True)  # 用真实价格交易
    set_benchmark('000300.XSHG')
    log.set_level('order', 'error')
    #
    # 将滑点设置为0
    set_slippage(FixedSlippage(0.00))
    # 手续费: 采用系统默认设置 
    set_order_cost(OrderCost(close_tax=0.00, open_commission=0.0001, close_commission=0.0001, min_commission=5),
                   type='stock')
    # 开盘前运行L
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    #run_daily(get_signal, time='11:00')
    run_daily(get_signal, time='14:30')
    
    
# 1 设置参数
def set_params():
    g.use_dynamic_target_market = True  # 是否动态改变大盘热度参考指标
    # g.target_market = '000300.XSHG'
    g.target_market = '000300.XSHG'
    g.empty_keep_stock = '511880.XSHG'  # 闲时买入的标的
    # g.empty_keep_stock = '601318.XSHG'#闲时买入的标的
    g.signal = 'BUY'  # 交易信号初始化
    g.lag = 60  #获取前多少天的数据 
    #
    g.buy = []  # 购买股票列表
    g.ETFList = []
    g.cang = {}
    g.allCang = 0
    
def get_before_after_trade_days(date, count, is_before=True):
    """
    来自： https://www.joinquant.com/view/community/detail/c9827c6126003147912f1b47967052d9?type=1
    date :查询日期
    count : 前后追朔的数量
    is_before : True , 前count个交易日  ; False ,后count个交易日
    返回 : 基于date的日期, 向前或者向后count个交易日的日期 ,一个datetime.date 对象
    """
    all_date = pd.Series(get_all_trade_days())
    if isinstance(date, str):
        date = datetime.datetime.strptime(date, '%Y-%m-%d').date()
    if isinstance(date, datetime.datetime):
        date = date.date()

    if is_before:
        return all_date[all_date <= date].tail(count).values[0]
    else:
        return all_date[all_date >= date].head(count).values[-1]


def before_market_open(context):
    # 确保交易标的已经上市g.lag1个交易日以上
    ETF_targets = [
        #'159902.XSHE',#中小板指
        #'512880.XSHG',#券商B
        #'159901.XSHE',#深100etf
        #'510050.XSHG',#上证50
        # '510180.XSHG',#上证180
        #'510880.XSHG',#红利ETF
        #'159905.XSHE',#深红利
        # '159915.XSHE',#创业板
        # '510300.XSHG',#沪深300
        #'510500.XSHG',#中证500
        #'159949.XSHE',#创业板50
        # '515700.XSHG',# 新能车etf
        # '512660.XSHG',# 军工etf 
         #'512010.XSHG',# 医药etf 
        # '512290.XSHG',# 生物医药etf 
         #'518800.XSHG',# 黄金基金 
        # '512690.XSHG',#白酒
         #'159928.XSHE',#消费
        '162605.XSHE',#景顺鼎益
        '161903.XSHE',#万家
        '161005.XSHE',#富国
        '163417.XSHE',#兴全合一
        '163402.XSHE',#兴全
        '163415.XSHE',#兴全模式
        '501054.XSHG',#东征睿泽
        '162703.XSHE',#广发小盘
        # '512760.XSHG',#半导体50
        # '159996.XSHE',#家用电器
        # '159995.XSHE',#芯片
        # '161226.XSHE',#白银
        # '515000.XSHG',#科技
        # '512800.XSHG',#银行
        # '512720.XSHG',#计算机
        # '512400.XSHG',#有色
        # '515050.XSHG',#通信
        #'588000.XSHG',#科创50
        # '510900.XSHG',#H股ETF
        # '159920.XSHE',#恒生
        # '513500.XSHG',#标普500
        #'515220.XSHG',#煤炭
        # '159966.XSHE',#创蓝筹
        #'513100.XSHG',#纳指
        # '512200.XSHG',#房地产
        # '512170.XSHG',#医疗
        # '515900.XSHG',#央创
        # '512960.XSHG',#央调
        # '512980.XSHG',#传媒
        #'159967.XSHE',#创成长
        # '159997.XSHE',#电子
        # '159959.XSHE',#央企
        # '159819.XSHE',#人工智能
        # '515210.XSHG',#钢铁
        # '159807.XSHE',#科技
        ]
    yesterday = context.previous_date
    list_date = get_before_after_trade_days(yesterday, g.lag)  # 今天的前g.lag1个交易日的日期
    g.ETFList = []
    all_funds = get_all_securities(types='fund', date=yesterday)  # 上个交易日之前上市的所有基金
    for symbol in ETF_targets:
        if symbol in all_funds.index:
            if all_funds.loc[symbol].start_date <= list_date:  # 对应的基金也已经在要求的日期前上市
                g.ETFList.append(symbol)  # 则列入可交易对象中
    return


# 每日交易时
def ETFtrade(context):
    record(cangWei = g.allCang)
    if g.signal == 'CLEAR':
        for stock in context.portfolio.positions:
            if stock == g.empty_keep_stock:
                continue
            log.info("清仓: %s" % stock)
            order_target(stock, 0)
    elif g.signal == 'BUY':
        if g.empty_keep_stock in context.portfolio.positions:
            order_target(g.empty_keep_stock, 0)
        #
        holdings = set(context.portfolio.positions.keys())  # 现在持仓的
        targets = set(g.buy)  # 想买的目标
        #
        # 1. 卖出不在targets中的
        sells = holdings - targets
        for code in sells:
            log.info("卖出: %s" % code)
            order_target(code, 0)
        #
        ratio = len(targets)
        if ratio>0:
            cash = context.portfolio.total_value 
            # 2. 交集部分调仓
            adjusts = holdings & targets
            for code in adjusts:
                # 手续费最低5元，只有交易5000元以上时，交易成本才会低于千分之一，才去调仓
                log.info('调仓: %s' % code)
                order_target_value(code, cash*g.cang[code])
            # 3. 新的，买入
            purchases = targets - holdings
            for code in purchases:
                log.info('买入: %s' % code)
                order_target_value(code,cash*g.cang[code])
        #
        current_returns = 100 * context.portfolio.returns
        log.info("当前收益：%.2f%%，当前持仓: %s", current_returns, list(context.portfolio.positions.keys()))
    # if len(context.portfolio.positions) == 0:
    order_target_value(g.empty_keep_stock, context.portfolio.available_cash)

# 获取信号
def get_signal(context):
    # # 创建保持计算结果的DataFrame
    current_data = get_current_data()
    fen = 1.0/len(g.ETFList)
    g.cang = 0
    df_etf = pd.DataFrame(columns=['基金代码','周期涨幅'])
    mZhangfu = 0
    g.buy = [] 
    g.cang = {}
    g.allCang = 0
    for mkt_idx in g.ETFList:
        security = mkt_idx  # 指数对应的基金
        # 获取股票的收盘价
        close_data = attribute_history(security, g.lag, '1d', ['close'], df=False)
        # 获取股票现价
        zhangfu = 0
        current_price = current_data[security].last_price
        # 取得平均价格
        ma_n5 = close_data['close'][-5:].mean()
        ma_n10 = close_data['close'][-10:].mean()
        ma_n20 = close_data['close'][-20:].mean()
        ma_n30 = close_data['close'][-30:].mean()
        ma_n60 = close_data['close'][-60:].mean()
        #总的仓位计算
        index = 0
        if current_price>ma_n5:
            index+=0.3
        if current_price>ma_n10:
            index+=0.25
        if current_price>ma_n20:
            index+=0.2
        if current_price>ma_n30:
            index+=0.15
        if current_price>ma_n60:
            index+=0.1
        cang = 0
        if index==1:
            cang = fen
        elif index>0:
            cang = index*0.3*fen
            
        if index>0:    
            g.buy.append(security)
            g.cang[security] = cang
            g.allCang += cang
        
        df_etf = df_etf.append({'基金代码':security, '周期涨幅':zhangfu },ignore_index=True)
        mZhangfu+=zhangfu
    if len(g.buy)==0:
        g.signal = 'CLEAR'
        log.info("仓位"+str(g.allCang)+"\n清仓")
        ETFtrade(context)
        return
    log.info("仓位"+str(g.allCang)+"持仓数量"+str(g.cang)+"\n交易信号:持有 %s" % g.buy)
    g.signal = 'BUY'
    ETFtrade(context)
    return
    
      

def GetMACD(stock, period, isIncludNow = True):
# 获取各周期 MACD 数据 
# 参数说明
# stock: 股票代码
# period: 周期，支持如下周期：’1m’, ‘5m’, ‘15m’, ‘30m’, ‘60m’, ‘120m’, ‘1d’, ‘1w’, ‘1M’。’1w’ 表示一周，‘1M’ 表示一月。
# isIncludNow: 是否包含当前数据，比如：在收盘后运行，当isIncludNow=False时不包含当天数据，Ture 时包含
# 注：可能由于浮点数精度问题，个别数据和东方财富通有些许差别，但不影响计算结果的判断
    
    #取较长周期的数据，这里为100（MACD存在一个问题，即若选取时间较短，则可能出现不收敛的状况）
    bars = get_bars(stock, 100, period, ['close'], include_now = isIncludNow)
    close = array(bars['close'])
    macd_tmp = talib.MACD(close, fastperiod = 12, slowperiod = 26, signalperiod = 9)   #将参数传入MACD函数中
    # 返回的数据分别为短期慢线DIF、长期快线DEA、MACD
    DIF  = macd_tmp[0]
    DEA  = macd_tmp[1]
    MACD = macd_tmp[2]
    # 注：东方财富通MACD，即 MACD=2*(DIF-DEA)
    return DIF[-1], DEA[-1], MACD[-1] * 2

def GetKDJ(stock, period, isIncludNow = True):
    bars = get_bars(stock, 100, period, ['close'], include_now = isIncludNow)
    close = array(bars['close'])
    kdj = talib.KDJ()
    
    
