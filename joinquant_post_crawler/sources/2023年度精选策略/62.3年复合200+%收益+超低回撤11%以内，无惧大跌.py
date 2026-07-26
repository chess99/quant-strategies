# 克隆自聚宽文章：https://www.joinquant.com/post/32630
# 标题：3年复合200+%收益+超低回撤11%以内，无惧大跌
# 作者：Sunj3001

# 标题：python 2/3无杠杆，稳定盈利的回撤更小的非行业etf轮动2021版 对2020年收益进行了优化
# 作者：sunny 参考：jqz1226 热爱大自然 智习 last modify by sunny by 2020.10.12-16 对风控回撤和收益均大量优化
#非行业14.1.1-20.10.15=724+%收益   2016年回撤最大时20%回撤，15年15%左右   
#非行业17.1.1-20.10.15=376+%收益   4年回撤最大10%左右   
#非行业2019.1.1-2020.10.15=226% 回撤8.9%
#非行业双保险版 2019-1-1-2020-10-15=126% 回撤7.67% 收益比单个要低，回撤接近 近3年回撤优化降至10%以内

#last fixed by 2020.11.5 for python2/3判断通用
#2020/11/6 加上单支ETF止盈 以提高收益, 止损优化
#2020/11/9 ETF印花税为0
#2020/11/11 对于上涨过快进行空仓回撤保护,下跌过快也进行空仓回撤保护
#加入了12月中下旬后保护当年不再交易,加入zz500大盘风控对行情不好时效果有一定改善
#2020/11/13 对选股时也进行上涨和下跌风控改进，对回撤和收益均有显著提升，回撤降至10%以下，收益2020升到320%以上
#特别是对2020年/2018年的提升最为明显，但对2019、2015上半年上涨过快时的效果不如以前了
#last modify by 2020/1/1

from jqdata import *
import pandas as pd
import talib
import numpy
import sys

'''
原理：在多个(行业)种类的ETF中(持续更新中)，持仓1个，ETF池相应的指数分别是
        '159915.XSHE' #创业板、
        '159949.XSHE' #创业板50
        '510300.XSHG' #沪深300
        '510500.XSHG' #中证500
        '510880.XSHG' #上证红利ETF
        '159905.XSHE' #深红利
        '510180.XSHG' #上证180
        '510050.XSHG' #上证50
        '000852.XSHG' #中证1000
        #纳指ETF
        #行业ETF
持仓原则：
    1、对泸深指数的成交量进行统计，如果连续6（lag）天成交量小于7（lag0)天成交量的，空仓处理（购买货币基金511880 银华日利或国债 511010 ）
    2、13个交易日内（lag1）涨幅大于1的，并且“均线差值”大于0的才进行考虑。
    3、对符合考虑条件的ETF的涨幅进行排序，买涨幅最高的1个。
'''


def initialize(context):
    set_params()
    #
    #set_option("avoid_future_data", True) #for python3
    set_option('use_real_price', True)  # 用真实价格交易
    set_benchmark('000300.XSHG')
    log.set_level('order', 'error')
    #
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 手续费: 采用系统默认设置
    # 股票类每笔交易时的手续费是：买入时佣金万分之2.5，卖出时佣金万分之2.5加千分之一印花税（ETF印花税为0）, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.000, open_commission=0.00025, close_commission=0.00025, min_commission=5), type='stock')

    # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    # 11:30 计算大盘信号
    run_daily(get_signal_back, time='09:58') #优化高收益的回测 止盈
    run_daily(get_signal, time='14:37')
    # 14:40 进行交易
    run_daily(ETFtradeSell, time='14:38')
    run_daily(ETFtradeBuy, time='14:39')

    # 14:53 收盘前检查订单
    run_daily(before_market_close, time='14:53')

# 1 设置参数
def set_params():
    g.ispython3 = (sys.version_info>=(3,0))  #2020/11/05
    print("version:",g.ispython3,sys.version)

    g.use_dynamic_target_market = True  # 是否动态改变大盘热度参考指标
    g.target_market = '000300.XSHG'
    #g.target_market = '399001.XSHE'
    g.empty_keep_stock = '511880.XSHG'  # 闲时买入的标的 ''表示空

    g.signal = 'WAIT'  # 交易信号初始化
    g.emotion_rate = 0  # 市场热度
    g.lag = 6  # 大盘成交量连续跌破均线的天数，发出空仓信号
    g.lag0 = 7  # 大盘成交量监控周期
    g.lag1 = 13  # 比价均线周期
    g.lag2 = 13  # 价格涨幅计算周期
    g.emptyforthreeday = 10.6 #三天最大收益百分比后调仓
    g.emptyforallday = 31 #周期最大收益百分比后调仓
    g.emptymaxday = 3  #最大空仓天数
    g.emptyholdday = 0 #当前空仓天数计数,大于1时有效，为0时不需要空仓处理
    #
    g.buy = []  # 购买股票列表
    # 指数、基金对, 所有想交易的etf都可以，会自动过滤掉交易时没有上市的
    g.ETF_targets =  {
        '399001.XSHE':'150019.XSHE',#深证指数 深证100ETF增强 2010.5 21亿 银华锐进 
        #'399905.XSHE':'159902.XSHE',#中小板指  2006 12亿 华夏
        #'159901.XSHE':'159901.XSHE',#深100etf 2006 78亿 易方达
        '162605.XSHE':'162605.XSHE',#景顺长城鼎益LOF  2005 7亿
        '000016.XSHG':'510050.XSHG',#上证50 2004 484亿 华夏
        '000010.XSHG':'510180.XSHG',#上证180 2006 227亿 华安
        '000015.XSHG':'510880.XSHG',#红利ETF 2006 54亿 华泰柏瑞 #上证红利50指数
        '399324.XSHE':'159905.XSHE',#深红利 工银瑞信 2010.11  36亿 #深证红利40指数
        #'000922.XSHG':'515080.XSHG', #中证红利100深沪 2019.11 3亿 招商 成交量300-2000万
        #'399006.XSHE':'159915.XSHE',#创业板 2011.9 171亿 易方达
        #'150153.XSHE':'150153.XSHE',#创业板B 2013.9 12亿 富国
        #'150152.XSHE':'150152.XSHE',#创业板A 2013.9 9亿 富国
        '399673.XSHE':'159949.XSHE',#创业板50 华安 116亿 2016.6
        
        '000300.XSHG':'510300.XSHG',#沪深300 华泰柏瑞 399亿 2012.5
        #'510330.XSHG':'510330.XSHG',#沪深300 华夏 278亿 2012.12
        #'159919.XSHE':'159919.XSHE',#沪深300 嘉实 242亿 2012.5
        
        '000905.XSHG':'510500.XSHG',#中证500 南方 379亿 2013.2
        #'512500.XSHG':'512500.XSHG',#中证500 华夏 49亿 2015.5
        #'510510.XSHG':'510510.XSHG', #中证500 广发 29亿 2013.4
        '399906.XSHE':'515800.XSHG', #中证800 2019.10 23亿 汇添富
        #'399903.XSHE':'512910.XSHG', #中证100 2019.5 5亿 广发  日成交量800万左右
        #'000852.XSHG':'512100.XSHG', #中证1000  2016.9 2亿 南方 日成交量1000万-1亿左右

        #'515090.XSHG':'515090.XSHG', #可持续 2020.1 3亿 博时 成交量小
        '159966.XSHE':'159966.XSHE', #创蓝筹 2019.6 20亿 华夏
        '159967.XSHE':'159967.XSHE', #创成长ETF 2019.6 9亿 华夏创业动量成长
        #2020.10.19---

        #2020.10.27  科创50 000688.XSHG 待加入
        #'501083.XSHG':'501083.XSHG', #科创银华 15亿 2019.7  成交量300-2000万 科创主题3年封闭3年灵活混合 
        #2020/11/16有效
        #'588000.XSHG':'588000.XSHG', #科创板50指数 华夏上证科创板50 51亿
        #'588080.XSHG':'588080.XSHG', #科创板50指数 易方达上证科创板50 51亿
        
        #'511010.XSHG':'511010.XSHG', #5年期国债ETF 2013.3 11亿 国泰
        '511380.XSHG':'511380.XSHG', #转债ETF 2020.3 11亿 博时
        #'399376.XSHE':'159906.XSHE', #深成长40 2010.12 2亿 大成 日交易100-500万左右
        #'160916.XSHE':'160916.XSHE', #大成优选混合LOF 2012.7 5亿 日交易100-800万左右 成交量低的实盘成交不及时
        #'515200.XSHG':'515200.XSHG', #中证研发创新100指数 2019.10 2亿 早万菱信

        '513500.XSHG':'513500.XSHG',  #标普500 2013.12 22亿 博时  QDII中国人民币ETF基金
        '513100.XSHG':'513100.XSHG',  #纳指ETF 2013.4 11亿 国泰 QDII中国人民币ETF基金
        #'513600.XSHG':'513600.XSHG',  #恒指ETF 2014.12 2.7亿 南方 QDII中国人民币ETF基金
        #'159920.XSHE':'159920.XSHE', #恒生ETF 2012.8 89亿 华夏
        '510900.XSHG':'510900.XSHG', #H股ETF 2012.8 102亿 易方达
        #'513030.XSHG':'513030.XSHG', #德国30ETF 2014.8 10亿 华安DAX龙头 QDII
        #'513000.XSHG':'513000.XSHG', #日经ETF 2019.6 0.7亿 易方达 QDII 规模小交易量低
        #'513050.XSHG':'513050.XSHG', #中概互联 2017.1 45亿 易方达 规模好 QDII 
        #'518880.XSHG':'518880.XSHG', #黄金ETF 2013.7 117亿 #不符合股市大盘规律 降收益了
        
        #'515770.XSHG':'515770.XSHG', #上投摩根MSCI中国 2020.5 5亿
        #'512990.XSHG':'512990.XSHG', #MSCI A股 2015.2 6亿 华夏
        '512160.XSHG':'512160.XSHG' #MSCI中国 2018.4 13.5亿 南方
        
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
    if g.emptyholdday > 0: #开盘时计算已经空仓的天数
        g.emptyholdday = g.emptyholdday - 1
    # 确保交易标的已经上市g.lag1个交易日以上
    yesterday = context.previous_date
    list_date = get_before_after_trade_days(yesterday, g.lag1)  # 今天的前g.lag1个交易日的日期
    g.ETFList = {}
    all_funds = get_all_securities(types='fund', date=yesterday)  # 上个交易日之前上市的所有基金
    '''all_idxes = get_all_securities(types='index', date=yesterday)  # 上个交易日之前就已经存在的指数
    for idx in g.ETF_targets:
        if idx in all_idxes.index:
            if all_idxes.loc[idx].start_date <= list_date:  # 指数已经在要求的日期前上市
                symbol = g.ETF_targets[idx]
                if symbol in all_funds.index:
                    if all_funds.loc[symbol].start_date <= list_date:  # 对应的基金也已经在要求的日期前上市
                        g.ETFList[idx] = symbol  # 则列入可交易对象中
    '''
    # fix by sunny 不在要求必须对应的指数，可以用自己基金作为数据
    for idx in g.ETF_targets:
        symbol = g.ETF_targets[idx]
        if symbol in all_funds.index:
            if all_funds.loc[symbol].start_date <= list_date:  # 对应的基金也已经在要求的日期前上市
                g.ETFList[idx] = symbol  # 则列入可交易对象中
    
    #
    return


# 每日交易时for卖出信号，卖和买分开，防止没有立即卖出买不了影响交易
def ETFtradeSell(context):
    if g.signal == 'CLEAR':
        for stock in context.portfolio.positions:
            if stock == g.empty_keep_stock:
                continue
            log.info("清仓: %s" % stock)
            order_target(stock, 0)
        #if (context.current_dt>=datetime.datetime.strptime('2020-10-20', '%Y-%m-%d')): #实盘后发邮件
        #    send_qq_email(str(context.current_dt.date())+"信号:CLEAR","交易日期："+str(context.current_dt.date())+"\n清仓:CLEAR")
    elif g.signal == 'BUY':  #1支时没有用
        if g.empty_keep_stock != '' and g.empty_keep_stock in context.portfolio.positions:
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
        #if (context.current_dt>=datetime.datetime.strptime('2020-10-20', '%Y-%m-%d')): #实盘后发邮件
        #    send_qq_email(str(context.current_dt.date())+"信号,调","交易日期："+str(context.current_dt.date())+"\n卖出:"+str(sells))


# 每日交易时for优化回撤的卖出信号
def ETFtradeSell_back(context):
    if g.signal == 'CLEAR':
        for stock in context.portfolio.positions:
            if stock == g.empty_keep_stock:
                continue
            log.info("清仓: %s" % stock)
            order_target(stock, 0)
        #if (context.current_dt>=datetime.datetime.strptime('2020-10-20', '%Y-%m-%d')): #实盘后发邮件
        #    send_qq_email(str(context.current_dt.date())+"信号:CLEAR","交易日期："+str(context.current_dt.date())+"\n清仓:CLEAR")


# 每日交易时for买入信号，卖和买分开，防止没有立即卖出买不了影响交易
def ETFtradeBuy(context):
    if g.emptyholdday > 0 and g.emptyholdday <= g.emptymaxday: #处于空仓天数期不买
        log.info('空仓期: 倒数第%d天' % g.emptyholdday)
        return        
    #每年的12.15日后不进行买卖，保护本年果实
    #if context.current_dt >= datetime.datetime.strptime(str(context.current_dt.year)+'-12-12', '%Y-%m-%d'): #处于空仓天数期不买
    #    log.info('每年的12.12日后不进行买卖，保护本年果实 %s' % str(context.current_dt.date()))
    #    #只买货币基金

    #el
    if g.signal == 'BUY':
        if g.empty_keep_stock != '' and g.empty_keep_stock in context.portfolio.positions:
            order_target(g.empty_keep_stock, 0)
        #
        holdings = set(context.portfolio.positions.keys())  # 现在持仓的
        targets = set(g.buy)  # 想买的目标
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
        #if (context.current_dt>=datetime.datetime.strptime('2020-10-20', '%Y-%m-%d')): #实盘后发邮件
        #    send_qq_email(str(context.current_dt.date())+"信号,买","交易日期："+str(context.current_dt.date())+"\n买:"+str(purchases))

    #买货币基金
    if len(context.portfolio.positions) == 0 and g.empty_keep_stock and g.empty_keep_stock != '':
        order_target_value(g.empty_keep_stock, context.portfolio.available_cash)


# 获取信号
def get_signal(context):
    buyold = g.buy  #在取之前把上次的g.buy进行保存，用于优化选中的继续上涨但上涨不够快的继续持有优化回撤
    if (len(g.ETFList)==0): #若开盘前运行的未成功时运行当天的交易受影响此处补上不影响当天的判断
        before_market_open(context)
    # 创建保持计算结果的DataFrame
    df_etf = pd.DataFrame(columns=['基金代码', '对应指数', '周期涨幅', '均线差值', '最新涨幅', '今日涨幅'])
    current_data = get_current_data()
    for mkt_idx in g.ETFList:
        security = g.ETFList[mkt_idx]  # 指数对应的基金
        # 获取股票的收盘价
        close_data = attribute_history(security, g.lag1, '1d', ['close'], df=False)
        # 获取股票现价
        current_price = current_data[security].last_price
        # 获取股票的阶段收盘价涨幅
        cp_increase = (current_price / close_data['close'][g.lag2 - g.lag1] - 1) * 100
        # 获取股票的2日内涨幅含今日的
        cp_increase_2 = (current_price / close_data['close'][-2] - 1) * 100
        #当日涨幅
        curr_increase = (current_price / close_data['close'][-1] - 1) * 100
        # 取得平均价格
        ma_n1 = close_data['close'].mean()
        # 计算前一收盘价与均值差值
        pre_price = (current_price / ma_n1 - 1) * 100
        df_etf = df_etf.append({'基金代码': security, '对应指数': mkt_idx, '周期涨幅': cp_increase, '均线差值': pre_price, '最新涨幅': cp_increase_2, '今日涨幅': curr_increase},
                               ignore_index=True)

    # 按照涨幅降序排列
    if len(df_etf) == 0:
        log.info("大盘信号：没有可以交易的品种，清仓")
        g.signal = 'CLEAR'
        return
    if g.ispython3:
        df_etf.sort_values(by='周期涨幅', ascending=False, inplace=True)
    else:
        df_etf.sort('周期涨幅', ascending=False, inplace=True) #for python2

    useidx = -1  # 用涨幅最大的指数来处理
    #useidx2 = -1 #用第2支ETF来平衡回撤
    for i in range(0, len(df_etf['对应指数'])):
        if df_etf['周期涨幅'].iloc[i] >= 1 and df_etf['均线差值'].iloc[i] >= 0.1 \
        and df_etf['最新涨幅'].iloc[i] < g.emptyforthreeday and df_etf['最新涨幅'].iloc[i] >-g.emptyforthreeday*0.5 \
        and df_etf['今日涨幅'].iloc[i] >-g.emptyforthreeday*0.2 and df_etf['今日涨幅'].iloc[i] < g.emptyforthreeday*0.6 \
        and df_etf['周期涨幅'].iloc[i] < g.emptyforallday \
        and df_etf['周期涨幅'].iloc[i] >= g.emptyforallday*0.1:
            useidx = i  # 找涨幅最大且符合要求的指数来处理
            break
    #for i in range(useidx+1, len(df_etf['对应指数'])):
    #    if df_etf['周期涨幅'].iloc[i] >= 1 and df_etf['均线差值'].iloc[i] >= 0.1 \
    #    and df_etf['最新涨幅'].iloc[i] < g.emptyforthreeday and df_etf['最新涨幅'].iloc[i] >-g.emptyforthreeday*0.5 \
    #    and df_etf['今日涨幅'].iloc[i] >-g.emptyforthreeday*0.2 and df_etf['今日涨幅'].iloc[i] < g.emptyforthreeday*0.6 \
    #    and df_etf['周期涨幅'].iloc[i] < g.emptyforallday \
    #    and df_etf['周期涨幅'].iloc[i] >= g.emptyforallday*0.1:
    #        useidx2 = i  # 找涨幅第二大且符合要求的指数来处理
    #        break

    if useidx < 0: # or useidx2 < 0:
        log.info('交易信号:周期所有品种均不符合要求，空仓')
        g.signal = 'CLEAR'
        return

    if g.use_dynamic_target_market:
        g.target_market = df_etf['对应指数'].iloc[useidx]  # 用涨幅最大的指数来处理

    #加入多个etf涨幅来判断大盘的好坏  
    red_etf_count = 0
    green_etf_count = 0
    for idx in df_etf['最新涨幅'].index:
        if (df_etf['最新涨幅'].iloc[idx] > 0):
            red_etf_count = red_etf_count + 1
        else:
            green_etf_count = green_etf_count + 1

    if EmotionMonitor() == -1 or EmotionMonitorNewZZ500() == -1:  # 大盘成交量情绪不好发出空仓信号
        log.info("交易信号:大盘成交量持续低均线，空仓")
        g.signal = 'CLEAR'
        return

    #改为所有可选的股票ETF列表综合来判断，风险更精确
    #if sum(df_etf['周期涨幅'])<0.1 and sum(df_etf['最新涨幅'])<0.1 and green_etf_count>red_etf_count*1.34:  # 大盘情绪不好发出空仓信号
    if sum(df_etf['周期涨幅'])<0.1 and green_etf_count>red_etf_count*1.34:  # 大盘情绪不好发出空仓信号
        log.info("周期信号:大盘大多数ETF股票均下跌，空仓,涨幅合计:"+str(sum(df_etf['周期涨幅']))+',上涨数：'+str(red_etf_count)+',下跌数：'+str(green_etf_count))
        g.signal = 'CLEAR'
        g.emptyholdday = 1 #空仓天数+1
        return

    log.info("\n行情统计,%s 热度%f%%:\n%s" % (g.target_market, g.emotion_rate, df_etf))
    # -----------------------------------------------------------------

    if df_etf['周期涨幅'].iloc[useidx] < 0.1 or df_etf['均线差值'].iloc[useidx] < 0:
        log.info('交易信号:所有品种均不符合要求，空仓')
        g.signal = 'CLEAR'
        return
    #if df_etf['周期涨幅'].iloc[useidx2] < 0.1 or df_etf['均线差值'].iloc[useidx2] < 0:
    #    log.info('交易信号:所有品种均不符合要求，空仓')
    #    g.signal = 'CLEAR'
    #    return
    #双保险版-2支ETF轮动
    #g.buy = [df_etf['基金代码'].iloc[useidx],df_etf['基金代码'].iloc[useidx2]]
    #主版本-只选1支ETF
    g.buy = [df_etf['基金代码'].iloc[useidx],]

    for j in range(0,len(buyold)): #add by 2021/1/1 对之前选中又在小涨的继续持有，优化回撤
        for i in range(0, len(df_etf['对应指数'])):
            if (df_etf['基金代码'].iloc[i] == buyold[j] and i<5 and
                useidx!=i and
                df_etf['今日涨幅'].iloc[i] > g.emptyforthreeday*0.01 and 
                df_etf['最新涨幅'].iloc[i] > g.emptyforthreeday*0.1
            ):
                g.buy = g.buy+[buyold[j]]  
                break

    log.info("交易信号:持有 %s" % g.buy)
    g.signal = 'BUY'
    return

# 获取回撤优化信号-止盈&止损
def get_signal_back(context):
    #加入止盈
    current_data = get_current_data() #当前价数据
    for stock in context.portfolio.positions.keys():
        currs = context.portfolio.positions[stock]
        currper = (currs.price-currs.avg_cost)/currs.avg_cost * 100  #这支股票当前盈利亏损比
        if currs.closeable_amount > 0: #可卖出仓位大于0显示
            log.info("持仓:%s, 价格：%.2f, 成本：%.2f, 总数量：%d, 可卖数量：%d, 价值：%.0f, 收益:%.2f％", stock, currs.price,currs.avg_cost,currs.total_amount,currs.closeable_amount,currs.value, currper)

            # 获取股票的收盘价
            close_data = attribute_history(stock, 3, '1d', ['close'], df=False)
            # 获取股票现价
            current_price = current_data[stock].last_price
            # 获取股票的今日比昨日收盘价涨幅
            curr_increase = (current_price / close_data['close'][-1] - 1) * 100
            two_increase = (current_price / close_data['close'][-2] - 1) * 100
            
            zz500ret = EmotionMonitorNewZZ500()
            if (zz500ret == -1): # or zz500ret == -2): 
                log.info("大盘信号不好，正在卖出 %s" % stock)
                order_target_value(stock, 0)
                #g.emptyholdday = g.emptymaxday #空仓天数计数
            elif (currper > g.emptyforthreeday or two_increase > g.emptyforthreeday*0.6 or curr_increase > g.emptyforthreeday*0.4): #加入单只ETF止盈 test   >6后加入ETF止盈止损后今年年化收益从141%=>317%
                log.info("正在止盈卖出 %s" % stock)
                order_target_value(stock, 0)
                g.emptyholdday = g.emptymaxday #空仓天数计数
            elif (currper < -g.emptyforthreeday*0.6 or two_increase < -g.emptyforthreeday*0.4 or curr_increase < -g.emptyforthreeday*0.2): #加入单只ETF止损 test  
                log.info("正在止损卖出 %s" % stock)
                order_target_value(stock, 0)
                #g.emptyholdday = 1 #空仓天数计数 只空1
        else:
            log.info("新持仓:%s, 价格：%.2f, 成本：%.2f, 数量：%d, 价值：%.0f, 收益:%.2f％", stock, currs.price,currs.avg_cost,currs.total_amount,currs.value, currper)
        
    return

    
# 大盘行情监控函数
def EmotionMonitor():
    _cnt = g.lag0 + max(g.lag, 3)
    volume = attribute_history(security=g.target_market, count=_cnt, unit='1d', fields='volume')['volume']
    #v_ma_lag0 = talib.MA(volume, g.lag0)  # 前 g.lag0 - 1 个会变成nan
    v_ma_lag0 = talib.MA(np.array(volume), g.lag0)  # 前 g.lag0 - 1 个会变成nan  #for python2 by 2020/10/12 by sj
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

def EmotionMonitorHS300():
    _cnt = g.lag0 + max(g.lag, 3)
    volume = attribute_history(security='000300.XSHG', count=_cnt, unit='1d', fields='volume')['volume']
    #v_ma_lag0 = talib.MA(volume, g.lag0)  # 前 g.lag0 - 1 个会变成nan
    v_ma_lag0 = talib.MA(np.array(volume), g.lag0)  # 前 g.lag0 - 1 个会变成nan  #for python2 by 2020/10/12 by sj
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

    
#收盘前对订单进行处理
def before_market_close(context):
  # 得到当前未完成订单
    orders = get_open_orders()
    # 循环，撤销订单
    for _order in orders.values():
        cancel_order(_order)
    #得到当天所有成交记录
    #orders = get_orders(status = [OrderStatus.held, OrderStatus.filled])
    orders = get_orders(status = OrderStatus.held)
    for _order in orders.values():
        log.info("order_id:%s, 股票: %s, 价格: %.2f, 成本: %.2f,  收益: %.2f％",_order.order_id, _order.security, _order.price, _order.avg_cost, (_order.price-_order.avg_cost)/_order.avg_cost)
    
    #对当前仓的所有股票显示当日收益                
    for stock in context.portfolio.positions.keys():
        currs = context.portfolio.positions[stock]
        currper = (currs.price-currs.avg_cost)/currs.avg_cost  #这支股票当前盈利亏损比
        if currs.closeable_amount > 0: #可卖出仓位大于0显示
            log.info("持仓:%s, 价格：%.2f, 成本：%.2f, 总数量：%d, 可卖数量：%d, 价值：%.0f, 收益:%.2f％", stock, currs.price,currs.avg_cost,currs.total_amount,currs.closeable_amount,currs.value, currper)
        else:
            log.info("新持仓:%s, 价格：%.2f, 成本：%.2f, 数量：%d, 价值：%.0f, 收益:%.2f％", stock, currs.price,currs.avg_cost,currs.total_amount,currs.value, currper)
        
    return

#新大盘行情监控函数 中证500
def EmotionMonitorNewZZ500():
    dpsecurity='000905.XSHG' #中证500 或沪深300
    lag = 8
    lag0 = 9
    ret_val = 0
    _cnt = lag0 + max(lag, 1)
    close = attribute_history(security=dpsecurity, count=_cnt, unit='1d', fields='close')['close']
    v_ma_lag0 = talib.MA(np.array(close), lag0) 
    #
    g.emotion_rate = round((close[-1] / v_ma_lag0[-1] - 1) * 100, 2)  # 最后一天的成交量比成交量均值高%
    #
    vol_diff = (close - v_ma_lag0)
    if vol_diff[-1] >= 0:
        ret_val = 1 if (vol_diff[-3:] >= 0).all() else 0  # 大盘成交价，最近3天都站在均线之上
    else:
        ret_val = -1 if (vol_diff[-lag:] < 0).all() else 0  # 大盘成交价，最近lag天都在均线之下
    
    #ret_val = 1 #test for disable emotion monitor
    #下面同时计算当日最新跌幅
    current_data = get_current_data()
    # 获取股票现价
    current_price = current_data[dpsecurity].last_price
    curr_increase = (current_price / close[-1] - 1) * 100
    if curr_increase < -1.1: #中证500指数大跌超过1%
        log.info('中证500指数大跌！！！%.2f' % curr_increase)
        ret_val = -2
    return ret_val
    
def after_code_changed(context):
    # 取消所有定时运行
    unschedule_all()
    set_params()  #add by 2020.11.3 防止替换代码后 ETF LIST没有重新初始化
    # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    # 11:30 计算大盘信号
    run_daily(get_signal_back, time='09:58') #优化高收益的回测 止盈
    #run_daily(get_signal_back, time='09:35') #优化高收益的回测 止盈

    run_daily(get_signal, time='14:37')
    # 14:40 进行交易
    run_daily(ETFtradeSell, time='14:38')
    run_daily(ETFtradeBuy, time='14:39')

    # 14:53 收盘前检查订单
    run_daily(before_market_close, time='14:53')
    
    before_market_open(context)
    return
