# 克隆自聚宽文章：https://www.joinquant.com/post/24417
# 标题：策略coding吐槽帖——以“网红”ETF轮动为例
# 作者：jqz1226

# 克隆自聚宽文章：https://www.joinquant.com/post/24321
# 标题：无杠杆，稳定盈利的etf轮动，06年开始3000%收益
# 作者：热爱大自然

# 克隆自聚宽文章：https://www.joinquant.com/view/community/detail/6d4d808cf982be5db2d0225264cfe8d4?type=1
# 标题：etf轮动的优化，680%收益
# 作者：热爱大自然

# 克隆自聚宽文章：https://www.joinquant.com/post/22857
# 标题：无杠杆，回撤更小的etf轮动
# 作者：智习

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
    set_option("avoid_future_data", True)
    set_option('use_real_price', True)  # 用真实价格交易
    set_benchmark('000300.XSHG')
    log.set_level('order', 'error')
    #
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 手续费: 采用系统默认设置

    # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    # 11:30 计算大盘信号
    run_daily(get_signal, time='11:30')
    # 14:40 进行交易
    run_daily(ETFtrade, time='14:40')


# 1 设置参数
def set_params():
    g.use_dynamic_target_market = True  # 是否动态改变大盘热度参考指标
    # g.target_market = '000300.XSHG'
    g.target_market = '399001.XSHE'
    g.empty_keep_stock = '511880.XSHG'  # 闲时买入的标的
    # g.empty_keep_stock = '601318.XSHG'#闲时买入的标的
    g.signal = 'BUY'  # 交易信号初始化
    g.emotion_rate = 0  # 市场热度
    g.lag = 6  # 大盘成交量连续跌破均线的天数，发出空仓信号
    g.lag0 = 7  # 大盘成交量监控周期
    g.lag1 = 13  # 比价均线周期
    g.lag2 = 13  # 价格涨幅计算周期
    #
    g.buy = []  # 购买股票列表
    # 指数、基金对, 所有想交易的etf都可以，会自动过滤掉交易时没有上市的
    g.ETF_targets =  {
        '399001.XSHE':'150019.XSHE',#银华锐进
        #'399905.XSHE':'159902.XSHE',#中小板指
        #'399975.XSHE':'150201.XSHE',#券商B
        #'399632.XSHE':'159901.XSHE',#深100etf
        #'162605.XSHE':'162605.XSHE',#景顺鼎益
        '000016.XSHG':'510050.XSHG',#上证50
        '000010.XSHG':'510180.XSHG',#上证180
        '000015.XSHG':'510880.XSHG',#红利ETF
        '399324.XSHE':'159905.XSHE',#深红利
        '399006.XSHE':'159915.XSHE',#创业板
        #'399006.XSHE':'150153.XSHE',#创业板B
        #'000300.XSHG':'510300.XSHG',#沪深300
        '000905.XSHG':'510500.XSHG',#中证500
        '399673.XSHE':'159949.XSHE'#创业板50
    }
    #
    stocks_info = "\n股票池:\n"
    for security in g.ETF_targets.values():
        s_info = get_security_info(security)
        stocks_info += "【%s】%s 上市日期:%s\n" % (s_info.code, s_info.display_name, s_info.start_date)
    log.info(stocks_info)

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
    yesterday = context.previous_date
    list_date = get_before_after_trade_days(yesterday, g.lag1)  # 今天的前g.lag1个交易日的日期
    g.ETFList = {}
    all_funds = get_all_securities(types='fund', date=yesterday)  # 上个交易日之前上市的所有基金
    all_idxes = get_all_securities(types='index', date=yesterday)  # 上个交易日之前就已经存在的指数
    for idx in g.ETF_targets:
        if idx in all_idxes.index:
            if all_idxes.loc[idx].start_date <= list_date:  # 指数已经在要求的日期前上市
                symbol = g.ETF_targets[idx]
                if symbol in all_funds.index:
                    if all_funds.loc[symbol].start_date <= list_date:  # 对应的基金也已经在要求的日期前上市
                        g.ETFList[idx] = symbol  # 则列入可交易对象中
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


# 获取信号
def get_signal(context):
    # 创建保持计算结果的DataFrame
    df_etf = pd.DataFrame(columns=['基金代码', '对应指数', '周期涨幅', '均线差值'])
    current_data = get_current_data()
    for mkt_idx in g.ETFList:
        security = g.ETFList[mkt_idx]  # 指数对应的基金
        # 获取股票的收盘价
        close_data = attribute_history(security, g.lag1, '1d', ['close'], df=False)
        # 获取股票现价
        current_price = current_data[security].last_price
        # 获取股票的阶段收盘价涨幅
        cp_increase = (current_price / close_data['close'][g.lag2 - g.lag1] - 1) * 100
        # 取得平均价格
        ma_n1 = close_data['close'].mean()
        # 计算前一收盘价与均值差值
        pre_price = (current_price / ma_n1 - 1) * 100
        df_etf = df_etf.append({'基金代码': security, '对应指数': mkt_idx, '周期涨幅': cp_increase, '均线差值': pre_price},
                               ignore_index=True)

    # 按照涨幅降序排列
    if len(df_etf) == 0:
        log.info("大盘信号：没有可以交易的品种，清仓")
        g.signal = 'CLEAR'
        return

    df_etf.sort_values(by='周期涨幅', ascending=False, inplace=True)
    if g.use_dynamic_target_market:
        g.target_market = df_etf['对应指数'].iloc[-1]  # 用涨幅最小的指数来处理

    if EmotionMonitor() == -1:  # 大盘情绪不好发出空仓信号
        log.info("交易信号:大盘成交量持续低均线，空仓")
        g.signal = 'CLEAR'
        return

    log.info("\n行情统计,%s 热度%f%%:\n%s" % (g.target_market, g.emotion_rate, df_etf))
    # -----------------------------------------------------------------
    if df_etf['周期涨幅'].iloc[0] < 0.1 or df_etf['均线差值'].iloc[0] < 0:
        log.info('交易信号:所有品种均不符合要求，空仓')
        g.signal = 'CLEAR'
        return

    # 大盘符合要求， 有基金品种也符合要求，买
    g.buy = [df_etf['基金代码'].iloc[0],]
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
