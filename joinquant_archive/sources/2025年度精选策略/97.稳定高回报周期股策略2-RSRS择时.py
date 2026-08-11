# 克隆自聚宽文章：https://www.joinquant.com/post/29915
# 标题：稳定高回报周期股策略2-RSRS择时
# 作者：风轻云淡0769

# 克隆自聚宽文章：https://www.joinquant.com/post/23858
# 标题：稳定高回报周期股策略2
# 作者：jqz1226
'''
原本策略：
白马股策略
月度调仓，买入股票池升序排名1-5的股票，卖出持仓且排名低于5的股票。
选股标准：
1、营业收入/(应收账款+应收票据-预付款项) > 6;
2、资产负债率 < 90%；
3、上市天数 > 500；
4、市盈率为正且低于25；
5、扣非净利润和营业利润为正；
6、动态市盈率为正且低于20。
排序指标：rank(动态市盈率)+0.5rank(1/扣非净利润环比)+0.3rank(1/扣非净利润同比)

修改部分：
1、增加择时：RSRS择时
'''

from jqdata import *
import pandas as pd
import numpy as np
import datetime
import statsmodels.api as sm

# 初始化函数，设定基准等等
def initialize(context):
    set_param()
    #是否有未来函数
    #set_option("avoid_future_data", True)
    #选股
    run_monthly(main, 1, time='9:30')
    #run_weekly(main,1, time='open', reference_security='000300.XSHG')
    # 开盘时运行交易
    run_daily(market_open, time='open', reference_security='000300.XSHG')
    sl=g.sell
    # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')

def set_param():
    g.bten = []  # 排序靠前的10只股票
    g.bfive = []  # 排序靠前的5只股票
    g.stock_num = 5
    g.fin = pd.DataFrame()
    
    # 设置RSRS指标中N, M的值
    #统计周期
    g.N = 18
    #统计样本长度
    g.M = 800 ##600 1100
    # 买入阈值
    g.buy = 0.8     ##1.0  1.1  0.95  0.95  0.8      0.8
    g.sell = -0.8   ##-0.6 -0.6 -0.6  -0.55  -0.8    -0.6
                    ##19    15   19     16    15      16
    #用于记录回归后的beta值，即斜率
    g.ans = []
    #用于计算被决定系数加权修正后的贝塔值
    g.ans_rightdev= []
    
    # 显示所有列
    pd.set_option('display.max_columns', None)
    # 显示所有行
    pd.set_option('display.max_rows', None)
    # 设置value的显示长度为100，默认为50
    pd.set_option('max_colwidth', 100)
    
     #风险参考基准
    g.security = '000300.XSHG'
    # 设定沪深300作为基准
    set_benchmark(g.security)
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)

    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5),
                   type='stock')


def main(context):
    # 1、基本控制,返回Series，index:code, column:statDate
    s_stat_date = controlBasic(context)
    # 2、质量控制,
    df_fin = controlReport(s_stat_date, 6)
    # 3、进一步过滤或排序
    stocks_rank(df_fin)
    # 4、下单
    #orderStock(context)

## 开盘时运行函数
def market_open(context):
    security = g.security
    # 填入各个日期的RSRS斜率值
    beta=0
    r2=0
    
    #RSRS斜率指标定义
    prices = attribute_history(security, g.N, '1d', ['high', 'low'])
    highs = prices.high
    lows = prices.low
    X = sm.add_constant(lows)
    model = sm.OLS(highs, X)
    beta = model.fit().params[1]
    g.ans.append(beta)
    #计算r2
    r2=model.fit().rsquared
    g.ans_rightdev.append(r2)
    
    # 计算标准化的RSRS指标
    # 计算均值序列    
    section = g.ans[-g.M:]
    # 计算均值序列
    mu = np.mean(section)
    # 计算标准化RSRS指标序列
    sigma = np.std(section)
    zscore = (section[-1]-mu)/sigma  
    #计算右偏RSRS标准分
    zscore_rightdev= zscore*beta*r2
    
    # 如果上一时间点的RSRS斜率大于买入阈值, 则全仓买入
    record(zs=zscore_rightdev,by=g.buy,sl=g.sell)
    
    #log.info(zscore_rightdev)
    current_data = get_current_data()
    if zscore_rightdev > g.buy:
        # 记录这次买入
        log.info("市场风险在合理范围")
        #满足条件运行交易
        trade_func(context)
    # 如果上一时间点的RSRS斜率小于卖出阈值, 则空仓卖出
    elif (zscore_rightdev < g.sell) and (len(context.portfolio.positions.keys()) > 0):
        # 卖出所有股票,使这只股票的最终持有量为0
        for s in context.portfolio.positions.keys():
            order_target(s, 0)
            log.info('市场风险过大，空仓：',current_data[s].name,s)
            
#策略选股买卖部分    
def trade_func(context):
    pool = g.bfive
    #log.info('总共选出%s只股票'%len(pool))
    log.info('选出的股票 %s'%pool)
    #得到每只股票应该分配的资金
    cash = context.portfolio.total_value/len(pool)
    #获取已经持仓列表
    hold_stock = context.portfolio.positions.keys() 
    
    current_data = get_current_data()
    #卖出不在持仓中的股票
    for s in hold_stock:
        if s not in pool:
            order_target(s,0)
    #买入股票
    for s in pool:
        order_target_value(s,cash)
        log.info("买入：%s %s" %(current_data[s].name, s))
        
#打分工具
def f_sum(x):
    return sum(x)

def controlBasic(context):
# 1、基本条件：净利润>0, PE(0,25), 资产负债率 < 90%
# 2、筛选条件：符合基本条件的 1）非 J金融，K房地产；2）非次新股； 3)正常上市的(排除了st, *st, 退)
# 3、查询最后报告时间
    # type: (Context) -> pd.Series
    '''
    :return: DataFrame(index:'code', columns:['statDate'])
    '''
    # 基本条件：净利润>0, PE(0,25), 资产负债率 < 90%，确保数量少于3000家公司
    q = query(
        income.code
    ).filter(
        income.net_profit > 0,  # 净利润大于0
        valuation.pe_ratio > 0,  # PE [0,25]
        valuation.pe_ratio < 25,
        balance.total_liability / balance.total_assets < 0.9  # 资产负债率 < 90%
    )
    primary_stks = list(get_fundamentals(q)['code'])

    # J金融，K房地产 行业
    notcall = finance.run_query(
        query(finance.STK_COMPANY_INFO.code,
              ).filter(
            finance.STK_COMPANY_INFO.industry_id.in_(['J66', 'J67', 'J68', 'J69', 'K70']),  # J金融，K房地产
        ))
    notcall_stks = list(notcall['code'])

    # 筛选条件：符合基本条件的 1）非 J金融，K房地产；2）非次新股； 3)正常上市的(排除了st, *st, 退)。
    date_500days_ago = context.previous_date - datetime.timedelta(days=500)  # 500天之前的日期
    compinfo = finance.run_query(query(
        finance.STK_LIST.code,
    ).filter(
        finance.STK_LIST.code.in_(primary_stks),  # 符合基本条件
        ~finance.STK_LIST.code.in_(notcall_stks),  # 非 J金融，K房地产
        finance.STK_LIST.start_date < date_500days_ago,  # 非次新
        finance.STK_LIST.state_id == 301001  # 正常上市
    ))
    call_stks = list(compinfo['code'])

    # 查询最后报告时间
    q = query(
        income.statDate,
        income.code
    ).filter(
        income.code.in_(call_stks),
    )
    rets = get_fundamentals(q)
    rets = rets.set_index('code')
    return rets.statDate


def stocks_rank(df_fin):
    if len(df_fin) <= 0:
        return
    # 5、PE<20
    q_cap = query(valuation.code, valuation.market_cap).filter(valuation.code.in_(list(df_fin.index)))
    df_cap = get_fundamentals(q_cap).set_index('code')
    df_pe = pd.concat([df_fin, df_cap], axis=1)  # df_pe.merge(df_cap)
    df_pe['pe'] = df_pe['market_cap'] * 100000000 / df_pe['adjusted_profit']
    df_pe = df_pe[(df_pe['pe'] < 20) & (df_pe['pe'] > 0)]

    df_pe = df_pe.sort_values(by='pe', ascending=True).reset_index(drop=False)
    df_pe['pes'] = 100 - df_pe.index * 100 / len(df_pe)

    df_pe = df_pe.sort_values(by='hb', ascending=False).reset_index(drop=True)
    df_pe['hbs'] = 100 - df_pe.index * 100 / len(df_pe)

    df_pe = df_pe.sort_values(by='tb', ascending=False).reset_index(drop=True)
    df_pe['tbs'] = 100 - df_pe.index * 100 / len(df_pe)

    #df_pe['s'] = df_pe['pes'] * 1.0 + df_pe['hbs'] * 0.5 + df_pe['tbs'] * 0.3
    df_pe['s'] = df_pe['pes'] * 1.0 + df_pe['hbs'] * 0.3 + df_pe['tbs'] * 0.5
    df_pe = df_pe.sort_values(by='s', ascending=False).reset_index(drop=True)
    #
    #print(df_pe[['code', 'hb', 'tb', 'pe', 's']])
    #
    g.bten = list(df_pe.code[:g.stock_num * 2])
    g.bfive = list(df_pe.code[:g.stock_num])

'''
def orderStock(context):
    # type: (Context) -> None
    bfive = g.bfive
    bten = g.bten

    all_value = context.portfolio.total_value
    for sell_code in context.portfolio.long_positions.keys():
        if sell_code not in bfive:
            # 卖掉
            log.info('sell all:', sell_code)
            order_target_value(sell_code, 0)
        # else:
        #    log.info('sell part:',sell_code)
        #    order_target_value(sell_code,all_value/g.stock_num)

    for buy_code in bfive:   # bten
        if buy_code not in context.portfolio.long_positions.keys():
            cash_value = context.portfolio.available_cash
            buy_value = cash_value / (g.stock_num - len(context.portfolio.positions))
            log.info('buy:' + buy_code + '   ' + str(buy_value))
            order_target_value(buy_code, buy_value)
'''

def controlReport(s, period):
    # type: (pd.Series, int) -> pd.DataFrame
    stat_date_stocks = {sd: [stock for stock in s.index if s[stock] == sd] for sd in set(s.values)}  # {报告日期：股票列表}
    qt = query(
        income.statDate,
        income.code,
        income.operating_revenue,  # 营业收入
        indicator.adjusted_profit,  # 扣非净利润
        balance.bill_receivable,  # 应收票据
        balance.account_receivable,  # 应收账款
        balance.advance_peceipts,  # 预收账款
        # cash_flow.net_operate_cash_flow,  # 经营现金流
        # cash_flow.fix_intan_other_asset_acqui_cash,  # 购固取无
        # balance.total_assets,  # 资产总计
        # balance.total_liability,  # 负债合计
        # balance.shortterm_loan,  # “短期借款”
        # balance.longterm_loan,  # “长期借款”
        # balance.non_current_liability_in_one_year,  # “一年内到期的非流动性负债”
        # balance.bonds_payable  # “应付债券”、
    )
    # 分别取多期数据
    data_quarters = [[], [], []]
    for stat_date in stat_date_stocks.keys():  # 一个报告日 -> 6个季度 -> 2个季度一组，共3组
        lqt = qt.filter(balance.code.in_(stat_date_stocks[stat_date]))
        #
        arr_quarters = get_past_quarters(stat_date, period)
        for i in range(len(arr_quarters)):  # 3组
            #
            df_two_quarter = pd.DataFrame()
            for statq in arr_quarters[i]:  # 每组两个季度
                oneData = get_fundamentals(lqt, statDate=statq)
                if len(oneData) > 0:
                    df_two_quarter = df_two_quarter.append(oneData)
            #
            if len(df_two_quarter) > 0:
                df_two_quarter = df_two_quarter.fillna(0)
                data_quarters[i].append(df_two_quarter)

    # 2个季度一组，共3组, 对应3个df
    df_qr01 = pd.concat(data_quarters[0]) if len(data_quarters[0]) > 1 else data_quarters[0][0]
    df_qr23 = pd.concat(data_quarters[1]) if len(data_quarters[1]) > 1 else data_quarters[1][0]
    df_qr45 = pd.concat(data_quarters[2]) if len(data_quarters[2]) > 1 else data_quarters[2][0]

    # 合并01和23，计算一年的应收账款周转率
    df_year = df_qr01.append(df_qr23)
    # 按公司分组，求sum: 营业收入，扣非净利润，mean：应收票据，应收账款，预付账款, count: statDate
    group_by_code = df_year.groupby('code')
    df_year_count = group_by_code[['statDate']].count()
    df_year_sum = group_by_code[['operating_revenue', 'adjusted_profit']].sum()
    df_year_mean = group_by_code[['account_receivable', 'bill_receivable', 'advance_peceipts']].mean()
    df_year_code = pd.concat([df_year_count, df_year_sum, df_year_mean], axis=1)
    df_year_code['receivable'] = df_year_code['account_receivable'] + df_year_code['bill_receivable'] - df_year_code[
        'advance_peceipts']
    # df_year_code['receivable'] = df_year_code['account_receivable']
    df_year_code['ar_turnover_rate'] = df_year_code['operating_revenue'] / df_year_code['receivable'].replace(0, np.inf)
    ## 够四个季度的， 应收账款周转率 > 6 或者 <=0
    df_year_code = df_year_code[(df_year_code.statDate == 4) & (
            (df_year_code['ar_turnover_rate'] > 6.0) | (df_year_code['ar_turnover_rate'] <= 0))]

    ## 01, 23, 45 分别计算adjusted_profit之和
    df_qr01_code = df_qr01.groupby('code')[['adjusted_profit']].sum()
    df_qr01_code.columns = ['qr01']
    df_qr23_code = df_qr23.groupby('code')[['adjusted_profit']].sum()
    df_qr23_code.columns = ['qr23']
    df_qr45_code = df_qr45.groupby('code')[['adjusted_profit']].sum()
    df_qr45_code.columns = ['qr45']
    ## 合并，计算环比，同比
    df_comp = pd.concat([df_qr01_code, df_qr23_code, df_qr45_code], axis=1)
    df_comp['hb'] = df_comp['qr01'] / df_comp['qr23']
    df_comp['tb'] = df_comp['qr01'] / df_comp['qr45']

    # 合并： df_year_code, df_comp
    df_rets = pd.concat([df_year_code[['adjusted_profit']], df_comp[['hb', 'tb']]], axis=1, sort=False).dropna()
    # df_rets = df_rets[(df_rets.tb > 0)]  # (df_rets.hb>0) &
    return df_rets


def get_past_quarters(stat_date, num):
    # type: (str, int) -> np.ndarray
    '''
    参数：'2019-09-30', 6, 两个季度一组，共三组
    返回：array([['2019q3', '2019q2'], ['2019q1', '2018q4'], ['2018q3', '2018q2']])
    '''
    date_stat = datetime.datetime.strptime(stat_date, '%Y-%m-%d').date()
    year = date_stat.year
    month = date_stat.month
    #
    list_quarter = []
    for i in range(num):
        if month < 3:
            year -= 1
            month = 12
        quarter = (month - 1) // 3 + 1
        list_quarter.append('{}q{}'.format(year, quarter))
        #
        month -= 3
    #
    return np.array(list_quarter).reshape(3, 2)


## 收盘后运行函数
def after_market_close(context):
    # log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in list(trades.values()):
        log.info('成交记录：'+str(_trade))
        send_message(str(_trade), channel='weixin')
    log.info('一天结束')
    #log.info('————'*10)
