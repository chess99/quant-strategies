# 克隆自聚宽文章：https://www.joinquant.com/post/24432
# 标题：基本不耍六毛的ETF轮动策略
# 作者：jqz1226

from jqdata import *
import pandas as pd
import talib

'''
原理：每月动态筛选基金, 选择范围包括ETF和LOF，选择条件是：1）已经上市交易15天以上，2）有一定的成交量。
     每月动态选择1只收益率最高的场内货币基金。 
持仓原则：
    1、对泸深指数的成交量进行统计，如果连续6（lag）天成交量小于7（lag0)天成交量，空仓
    2、13个交易日内（lag1）涨幅大于1的，并且“均线差值”大于0的才进行考虑。
    3、对符合考虑条件的ETF的涨幅进行排序，按涨幅依次买入，买入的每只ETF不超过其全天成交量的千分之2。
    4、闲钱时买入货币基金
'''


def initialize(context):
    set_params()
    #
    # set_option("avoid_future_data", True)
    set_option('order_volume_ratio', 0.002)  # 成交量不得超过标的日成交量的千分之2
    set_option('use_real_price', True)  # 用真实价格交易
    set_benchmark('000300.XSHG')
    log.set_level('order', 'info')
    # 滑点设置：按系统默认
    # 设置手续费: 按系统默认
    choice_etfs(context)
    choice_mmf(context)

    #  ------------- 每月 ----------------
    # run_weekly(choice_etfs, weekday=1, time='before_open', reference_security='000300.XSHG')
    # run_weekly(choice_mmf, weekday=1, time='before_open', reference_security='000300.XSHG')
    run_monthly(choice_etfs, monthday=1, time='before_open', reference_security='000300.XSHG')
    run_monthly(choice_mmf, monthday=1, time='before_open', reference_security='000300.XSHG')

    #  ------------- 每天 ----------------
    # 11:30 计算大盘信号
    run_daily(get_signal, time='11:30')
    # 14:40 进行交易
    run_daily(ETFtrade, time='14:40')


# 1 设置参数
def set_params():
    g.target_market = '399001.XSHE'
    g.empty_keep_stock = ''  # 闲时买入的标的
    g.ETFList = []  # 目标ETFs
    #
    g.emotion_rate = 0  # 市场热度
    g.signal = 'BUY'  # 交易信号初始化
    g.buy = []  # 购买股票列表
    #
    g.lag = 6  # 大盘成交量连续跌破均线的天数，发出空仓信号
    g.lag0 = 7  # 大盘成交量监控周期
    g.lag1 = 13  # 比价均线周期
    g.lag2 = 13  # 价格涨幅计算周期


# 每日交易时
def ETFtrade(context):
    # type: (Context) -> NoReturn
    # 先卖掉货币基金
    if g.empty_keep_stock != '':
        if g.empty_keep_stock in context.portfolio.positions:
            order_target(g.empty_keep_stock, 0)
    #
    if g.signal == 'CLEAR':
        for stock in context.portfolio.positions:
            log.info("清仓: %s" % stock)
            order_target(stock, 0)
    elif g.signal == 'BUY':
        holdings = set(context.portfolio.positions.keys())  # 现在持仓的
        targets = set(g.buy)  # 想买的目标
        #
        # 1. 卖出不在targets中的
        sells = holdings - targets
        for code in sells:
            log.info("卖出: %s" % code)
            order_target(code, 0)
        # 2. 按顺序买入g.buy中的， 受交易量的限制, 超出部分不会下单
        for code in g.buy:
            val = context.portfolio.available_cash
            if val > 500:
                log.info('买入：%s' % code)
                order_value(code, val)
            else:
                break
        #
        current_returns = 100 * context.portfolio.returns
        log.info("当前权益：%.2f，收益：%.2f%%，当前持仓: %s", context.portfolio.total_value, current_returns,
                 list(context.portfolio.positions.keys()))
        #
    if g.empty_keep_stock != '':
        if context.portfolio.available_cash > 500:
            order_target_value(g.empty_keep_stock, context.portfolio.available_cash)


# 获取信号
def get_signal(context):
    # type: (Context) -> NoReturn
    if EmotionMonitor() == -1:  # 大盘情绪不好发出空仓信号
        log.info("交易信号:大盘成交量持续低均线，空仓")
        g.signal = 'CLEAR'
        return
    #
    log.info("\n行情统计：%s 热度%f%%" % (g.target_market, g.emotion_rate))

    # 创建保持计算结果的DataFrame
    df_etf = pd.DataFrame(columns=['基金代码', '周期涨幅', '均线差值'])
    current_data = get_current_data()
    for security in g.ETFList:
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
        df_etf = df_etf.append({'基金代码': security, '周期涨幅': cp_increase, '均线差值': pre_price},
                               ignore_index=True)

    if len(df_etf) == 0:
        log.info("交易信号：没有可以交易的品种，清仓")
        g.signal = 'CLEAR'
        return

    # 按照涨幅降序排列
    df_etf.sort_values(by='周期涨幅', ascending=False, inplace=True)
    df_etf.reset_index(drop=True, inplace=True)  # 重新设置索引
    log.info("ETF热度:\n%s" % df_etf)
    #
    if df_etf['周期涨幅'].iloc[0] < 0.1 or df_etf['均线差值'].iloc[0] < 0:
        log.info('交易信号:最热的品种都不符合均线差值的要求，空仓')
        g.signal = 'CLEAR'
        return

    # 过滤出符合要求的
    df_etf = df_etf[(df_etf['周期涨幅'] >= 0.1) & (df_etf['均线差值'] >= 0)]
    g.buy = list(df_etf['基金代码'])  # 所有符合要求的ETF
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


def choice_etfs(context):
    # type: (Context) -> NoReturn
    """
    功能：选择日均成交量居前的ETF和LOF
    """
    ret_val = []
    fund_list = list(get_all_securities(types=['etf', 'lof'], date=context.previous_date).index)  #
    if len(fund_list) > 0:
        h = history(15, unit='1d', field='volume', security_list=fund_list)  # 'money'
        h.dropna(axis=1, inplace=True)  # 15个交易日内任何一天为nan的，都drop掉
        if len(h.columns) > 0:
            s_h = h.mean(axis=0)  # 15个交易日的均值
            # ret_val = list(s_h[s_h > 10000000].index)  # 日均成交量在1千万以上
            ret_val = list(s_h.sort_values(ascending=False)[:6].index)  # 前6
    #
    g.ETFList = ret_val
    #
    _info = "\nETF池:\n"
    for security in g.ETFList:
        s_info = get_security_info(security)
        _info += "【%s】%s %s 上市日期:%s\n" % (s_info.code, s_info.display_name, s_info.type, s_info.start_date)
    log.info(_info)


def choice_mmf(context):
    # type: (Context) -> NoReturn
    """
    功能：选择收益率最高的一只mmf
    """
    ret_val = ''
    funds = get_all_securities(types='fund', date=context.previous_date)
    if len(funds) > 0:
        mmf_list = list(funds[funds.type == 'mmf'].index)  # 基金中的货币基金
        if len(mmf_list) > 0:
            h = history(15, unit='1d', field='money', security_list=mmf_list)
            h.dropna(axis=1, inplace=True)  # 15个交易日内任何一天money为nan的，都drop掉
            if len(h.columns) > 0:
                s_money = h.mean(axis=0)  # 15个交易日的成交额均值
                mmf_list = list(s_money[s_money > 10000000].index)  # 日成交额在1千万以上的
                if len(mmf_list) > 0:
                    h = history(15, unit='1d', field='close', security_list=mmf_list)
                    mmf_rate = 100 * (h.iloc[-1] / h.iloc[0] - 1)  # 首尾涨幅
                    ret_val = mmf_rate.sort_values(ascending=False).index[0]  # 涨幅最大的
    #
    g.empty_keep_stock = ret_val
    #
    _info = "\n货币基金:\n"
    if len(g.empty_keep_stock) > 0:
        s_info = get_security_info(g.empty_keep_stock)
        _info += "【%s】%s %s 上市日期:%s\n" % (s_info.code, s_info.display_name, s_info.type, s_info.start_date)
    #
    log.info(_info)
