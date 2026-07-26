# 克隆自聚宽文章：https://www.joinquant.com/post/30461
# 标题：北向Boll带_ETF组合宝付费策略
# 作者：Funine

# 克隆自聚宽文章：https://www.joinquant.com/post/27351
# 标题：6年14倍的etf分级基金的轮动策略
# 作者：大吃一鲸

from jqdata import *
import pandas as pd
import talib

'''
原理：在8个种类的ETF中，持仓三个，ETF池相应的指数分别是
        '159915.XSHE' #创业板、
        '159949.XSHE' #创业板50
        '510300.XSHG' #沪深300
        '510500.XSHG' #中证500
        '510880.XSHG' #红利ETF
        '159905.XSHE' #深红利
        '510180.XSHG' #上证180
        '510050.XSHG' #上证50
持仓原则：
    1、对泸深指数的成交量进行统计，如果连续6（lag）天成交量小于7（lag0)天成交量的，空仓处理（购买货币基金511880 银华日利或国债 511010 ）
    2、13个交易日内（lag1）涨幅大于1的，并且“均线差值”大于0的才进行考虑。
    3、对符合考虑条件的ETF的涨幅进行排序，买涨幅最高的三个。
'''


def initialize(context):
    set_params()
    #
    set_option("avoid_future_data",True)
    set_option('use_real_price', True)  # 用真实价格交易
    set_benchmark('000300.XSHG')
    log.set_level('order', 'error')
    #
    # 将滑点设置为0
    set_slippage(FixedSlippage(0.001))
    # 手续费: 采用系统默认设置 
    set_order_cost(OrderCost(close_tax=0.00, open_commission=0.0001, close_commission=0.0001, min_commission=5),
                   type='stock')
    # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    # 11:30 计算大盘信号
    run_daily(get_signal, time='14:10')
    # 获取北向资金
    run_daily(trade,time='11:30')
    # 14:40 进行交易
    run_daily(ETFtrade, time='14:11')


# 1 设置参数
def set_params():
    g.use_dynamic_target_market = True  # 是否动态改变大盘热度参考指标
    # g.target_market = '000300.XSHG'
    g.target_market = '000300.XSHG'
    g.empty_keep_stock = '511880.XSHG'  # 闲时买入的标的
    # g.empty_keep_stock = '601318.XSHG'#闲时买入的标的
    g.signal = 'BUY'  # 交易信号初始化
    g.emotion_rate = 0  # 市场热度q
    g.lag = 6  # 大盘成交量连续跌破均线的天数，发出空仓信号
    g.lag0 = 7  # 大盘成交量监控周期
    g.lag1 = 15  # 比价均线周期
    g.lag2 = 15 # 价格涨幅计算周期
    g.north_money = 0
    #
    g.buy = []  # 购买股票列表
    g.ETFList = []
    
    g.boll252 = []
    g.boll150 = []
    g.boll80 = []
    g.boll20 = []

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
    ETF_targets = [ #'399001.XSHE' :'150019.XSHE',#银华锐进
        #'159902.XSHE',#中小板指
        #'512880.XSHG',#券商B
        '159901.XSHE',#深100etf
        '162605.XSHE',#景顺鼎益
        '510050.XSHG',#上证50
        #'510180.XSHG',#上证180
        '510880.XSHG',#红利ETF
        '159905.XSHE',#深红利
        '159915.XSHE',#创业板
        '510300.XSHG',#沪深300
        '510500.XSHG',#中证500
        '159949.XSHE',#创业板50
        # '515700.XSHG',# 新能车etf
        # '512660.XSHG',# 军工etf 
        # '512010.XSHG',# 医药etf 
        # '512290.XSHG',# 生物医药etf 
        #'518800.XSHG',# 黄金基金 
        # '512690.XSHG',#白酒
        # '159928.XSHE',#消费
        '161903.XSHE',#万家
        '161005.XSHE',#富国
        # '163417.XSHE',#兴全合一
        # '163402.XSHE',#兴全
        #'163415.XSHE',#兴全模式
        #'512760.XSHG',#半导体50
        #'159996.XSHE',#家用电器
        #'159995.XSHE',#芯片
        #'161226.XSHE',#白银
        #'515000.XSHG',#科技
        #'512800.XSHG',#银行
        #'512720.XSHG',#计算机
        #'512400.XSHG',#有色
        #'515050.XSHG',#通信
        #'588000.XSHG',#科创50
        #'501054.XSHG',#东征睿泽
        #'510900.XSHG',#H股ETF
        #'162703.XSHE',#广发小盘
        #'159920.XSHE',#恒生
        #'513500.XSHG',#标普500
        #'515220.XSHG',#煤炭
        #'159966.XSHE',#创蓝筹
        #'159941.XSHE',#纳指
        # '512200.XSHG',#房地产
        # '512170.XSHG',#医疗
        #'515900.XSHG',#央创
        #'512960.XSHG',#央调
        #'512980.XSHG',#传媒
        #'159967.XSHE',#创成长
        #'159997.XSHE',#电子
        #'159959.XSHE',#央企
        #'159819.XSHE',#人工智能
        # '515210.XSHG',#钢铁
        # '159807.XSHE',#科技
        ]
    yesterday = context.previous_date
    list_date = get_before_after_trade_days(yesterday, g.lag1)  # 今天的前g.lag1个交易日的日期
    g.ETFList = []
    all_funds = get_all_securities(types='fund', date=yesterday)  # 上个交易日之前上市的所有基金
    for symbol in ETF_targets:
        if symbol in all_funds.index:
            if all_funds.loc[symbol].start_date <= list_date:  # 对应的基金也已经在要求的日期前上市
                g.ETFList.append(symbol)  # 则列入可交易对象中
    # 创建保持计算结果的DataFrame
    df_etf = pd.DataFrame(columns=['基金代码', '对应名称', '周期涨幅', '均线差值'])
    current_data = get_current_data()
    for mkt_idx in g.ETFList:
        security = mkt_idx  # 指数对应的基金
        # 获取股票的收盘价
        close_data = attribute_history(security, g.lag1, '1d', ['close'], df=False)
        # 获取股票现价
        current_price = current_data[security].last_price
        #current_price = attribute_history(security, 1 , '1m', ['close'], df=False)[security].last_price
        # 获取股票的阶段收盘价涨幅
        cp_increase = (current_price / close_data['close'][g.lag2 - g.lag1] - 1) * 100
        # 取得平均价格
        ma_n1 = close_data['close'].mean()
        #log.info("当前价格:%s,%s" % (security,current_price))
        # 计算前一收盘价与均值差值
        info = get_security_info(security)
        pre_price = (current_price / ma_n1 - 1) * 100
        df_etf = df_etf.append({'基金代码': security, '对应名称': info.display_name, '周期涨幅': cp_increase, '均线差值': pre_price},
                               ignore_index=True)
    
    df_etf.sort_values(by='周期涨幅', ascending=False, inplace=True)
    log.info("盘前信号：%s" % (df_etf))
    send_message("盘前信号："+str(df_etf), channel='weixin')
    #
    return


# 每日交易时
def ETFtrade(context):
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
        if ratio >0:
            cash = context.portfolio.total_value / ratio
            # 2. 交集部分调仓
            adjusts = holdings & targets
            for code in adjusts:
                # 手续费最低5元，只有交易5000元以上时，交易成本才会低于千分之一，才去调仓
                if abs(cash - context.portfolio.positions[code].value) > 5000:  
                    log.info('调仓: %s' % code)
                    order_target_value(code, cash)
            # 3. 新的，买入
            purchases = targets - holdings
            for code in purchases:
                log.info('买入: %s' % code)
                order_target_value(code, cash)
            #
        current_returns = 100 * context.portfolio.returns
        log.info("当前收益：%.2f%%，当前持仓: %s", current_returns, list(context.portfolio.positions.keys()))

    if len(context.portfolio.positions) == 0:
        order_target_value(g.empty_keep_stock, context.portfolio.available_cash)

def trade(context):

    today = context.current_dt
    # print(today.date(),'@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@')
    n_sh = finance.run_query(query(finance.STK_ML_QUOTA).filter(finance.STK_ML_QUOTA.day <= today.date(),
                                                                finance.STK_ML_QUOTA.link_id == 310001).order_by(
        finance.STK_ML_QUOTA.day.desc()).limit(252))
    n_sz = finance.run_query(query(finance.STK_ML_QUOTA).filter(finance.STK_ML_QUOTA.day <= today.date(),
                                                                finance.STK_ML_QUOTA.link_id == 310002).order_by(
        finance.STK_ML_QUOTA.day.desc()).limit(252))
    
    money_north = []
    g.boll252 = []
    g.boll150 = []
    g.boll80 = []
    g.boll20 = []
    for i in range(0, 252):
        sh_in = n_sh['buy_amount'][i] - n_sh['sell_amount'][i]
        sz_in = n_sz['buy_amount'][i] - n_sz['sell_amount'][i]
        amount = sh_in + sz_in
        money_north.append(amount)
        
    g.north_money = money_north[0]
    mid252 = np.mean(money_north)
    sted252 = np.std(money_north)
    up252 = mid252+1.5*sted252
    low252 = mid252-1.5*sted252
    g.boll252.append(up252)
    g.boll252.append(low252)
    
    mid150 = np.mean(money_north[0:150])
    sted150 = np.std(money_north[0:150])
    up150 = mid150+1.5*sted150
    low150 = mid150-1.5*sted150
    g.boll150.append(up150)
    g.boll150.append(low150)
    
    mid80 = np.mean(money_north[0:80])
    sted80 = np.std(money_north[0:80])
    up80 = mid80+2*sted80
    low80 = mid80-2*sted80
    g.boll80.append(up80)
    g.boll80.append(low80)
    
    mid20 = np.mean(money_north[0:20])
    sted20 = np.std(money_north[0:20])
    up20 = mid20+2*sted20
    low20 = mid20-2*sted20
    g.boll20.append(up20)
    g.boll20.append(low20)
    
    log.info(str(up252)+","+str(low252))
    
# 获取信号
def get_signal(context):
    # 创建保持计算结果的DataFrame
    df_etf = pd.DataFrame(columns=['基金代码', '对应名称', '周期涨幅', '均线差值'])
    current_data = get_current_data()
    for mkt_idx in g.ETFList:
        security = mkt_idx  # 指数对应的基金
        # 获取股票的收盘价
        close_data = attribute_history(security, g.lag1, '1d', ['close'], df=False)
        # 获取股票现价
        current_price = current_data[security].last_price
        # 获取股票的阶段收盘价涨幅
        cp_increase = (current_price / close_data['close'][g.lag2 - g.lag1] - 1) * 100
        # 取得平均价格
        ma_n1 = close_data['close'].mean()
        info = get_security_info(security)
        # 计算前一收盘价与均值差值
        pre_price = (current_price / ma_n1 - 1) * 100
        df_etf = df_etf.append({'基金代码': security, '对应名称': info.display_name, '周期涨幅': cp_increase, '均线差值': pre_price},
                               ignore_index=True)
    
    df_etf.sort_values(by='周期涨幅', ascending=False, inplace=True)
    send_message("交易信号:"+str(df_etf), channel='weixin')
    
    # 按照涨幅降序排列
    if len(df_etf) == 0:
        log.info("大盘信号：没有可以交易的品种，清仓")
        g.signal = 'CLEAR'
        return
    
    # if g.use_dynamic_target_market:
    #     g.target_market = df_etf['对应指数'].iloc[-1]  # 用涨幅最小的指数来处理
    
    # log.info("\n行情统计,%s 热度%f%%:\n%s" % (g.target_market, g.emotion_rate, df_etf))
    # if EmotionMonitor() == -1 and g.north_money<5000:  # 大盘情绪不好发出空仓信号
    #     log.info("交易信号:大盘成交量持续低均线，空2")
    #     g.signal = 'CLEAR'
    #     return
    
    
    buyNum = 0
    sellNum = 0    
    if g.north_money - g.boll252[0]>0:
        buyNum+=1
        
    if g.north_money - g.boll150[0]>0:
        buyNum+=1   
    
    if g.north_money - g.boll80[0]>0:
        buyNum+=1 
    
    if g.north_money -g.boll20[0]>0:
        buyNum+=1
    
    if g.north_money -g.boll252[1]<0:
        sellNum+=1
        
    if g.north_money -g.boll150[1]<0:
        sellNum+=1   
    
    if g.north_money -g.boll80[1]<0:
        sellNum+=1 
    
    if g.north_money -g.boll20[1]<0:
        sellNum+=1
    
    if sellNum>=2:
        log.info("依据北向资金流入%s\n"%(round(g.north_money,1)))
        g.signal = 'CLEAR'
        return
    elif buyNum>=3:
        index = 2
        g.buy = df_etf['基金代码'].iloc[0:index]
        log.info("交易信号:持有 %s" % g.buy)
        g.signal = 'BUY'
        return
# 大盘行情监控函数
def EmotionMonitor():
    _cnt = g.lag0 + max(g.lag, 3)
    volume = attribute_history(security=g.target_market, count=_cnt, unit='1d', fields='volume')['volume']
    v_ma_lag0 = talib.MA(volume, g.lag0)  # 前 g.lag0 - 1 个会变成nan
    #
    g.emotion_rate = round((volume[-1] / v_ma_lag0[-1] - 1) * 100, 2)  # 最后一天的成交量比成交量均值高%
    #
    vol_diff = (volume - v_ma_lag0)
    if vol_diff[-1] >= 0:
        ret_val = 1 if (vol_diff[-3:] >= 0).all() else 0  # 大盘成交量，最近3天都站在均线之上
    else:
        ret_val = -1 if (vol_diff[-g.lag:] < 0).all() else 0  # 大盘成交量，最近g.lag天都在均线之下
    #
    return ret_val
