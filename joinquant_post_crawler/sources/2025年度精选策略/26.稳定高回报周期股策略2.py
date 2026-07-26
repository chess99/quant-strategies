# 克隆自聚宽文章：https://www.joinquant.com/post/23858
# 标题：稳定高回报周期股策略2
# 作者：jqz1226

from jqdata import *
import pandas as pd
import numpy as np
import datetime


# 初始化函数，设定基准等等
def initialize(context):
    set_param()
    run_monthly(main, 1, time='9:30')


def main(context):
    # 1、基本控制,返回Series，index:code, column:statDate
    s_stat_date = controlBasic(context)
    # 2、质量控制,
    df_fin = controlReport(s_stat_date, 6)
    # 3、进一步过滤或排序
    stocks_rank(df_fin)
    # 4、下单
    orderStock(context)


def controlBasic(context):
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

    df_pe['s'] = df_pe['pes'] * 1.0 + df_pe['hbs'] * 0.5 + df_pe['tbs'] * 0.3
    df_pe = df_pe.sort_values(by='s', ascending=False).reset_index(drop=True)
    #
    print(df_pe[['code', 'hb', 'tb', 'pe', 's']])
    #
    g.bten = list(df_pe.code[:g.stock_num * 2])
    g.bfive = list(df_pe.code[:g.stock_num])


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


def set_param():
    g.bten = []
    g.bfive = []
    g.stock_num = 5
    g.fin = pd.DataFrame()
    # 显示所有列
    pd.set_option('display.max_columns', None)
    # 显示所有行
    pd.set_option('display.max_rows', None)
    # 设置value的显示长度为100，默认为50
    pd.set_option('max_colwidth', 100)

    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)

    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5),
                   type='stock')


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
