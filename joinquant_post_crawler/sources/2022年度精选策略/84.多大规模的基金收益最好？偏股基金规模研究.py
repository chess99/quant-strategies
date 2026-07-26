# 克隆自聚宽文章：https://www.joinquant.com/post/37521
# 标题：多大规模的基金收益最好？偏股基金规模研究
# 作者：逆熵者

'''
条件：
1. 股票类资产规模大于1.5亿
2. 每年交易轮动持有最小规模基金
3. 持有10只基金
'''
# 导入函数库
import numpy as np
import pandas as pd
import datetime as dt
from jqdata import *

# 初始化函数，设定基准等等
def initialize(context):
    # 参数设置
    g.benchmark = '000300.XSHG' #设定比较基准
    g.funds_num = 10 #最大持仓基金数量限制
    g.min_asset = 150000000 #最小规模1.5亿
    g.retry_num = 0 #重复尝试交易计数
    g.first_time = True #首次运行
    g.finish_trade = False #完成交易，持仓标的与目标一致，不考虑仓位
    g.last_month = 0 #上次计算业绩的月份
    
    set_benchmark(g.benchmark) #设定基准
    set_option("use_real_price", True) #开启动态复权模式(真实价格)
    set_option("avoid_future_data", True) #避免未来数据模式
    log.set_level('order', 'error') #日志过滤级别
    # 设置账户类型: 场外基金账户
    set_subportfolios([SubPortfolioConfig(context.portfolio.cash, 'open_fund')])
    # 设置基金的到帐日为 T+3
    set_redeem_latency(day=3, type='open_fund')
    # 首次筛选和建仓
    check_out(context)
    buy(context, g.fund_targetpositions)
    # 定时任务
    run_monthly(check_out, -1, time='open', reference_security=g.benchmark)
    run_monthly(adding_to_position, -2, time='open', reference_security=g.benchmark)
    run_monthly(trade, -1, time='open', reference_security=g.benchmark)
    run_monthly(trade, 4, time='open', reference_security=g.benchmark)
    run_monthly(trade, 6, time='open', reference_security=g.benchmark)
    run_monthly(trade, 8, time='open', reference_security=g.benchmark)

# 每交易日进行交易
def trade(context):
    # check_out(context)
    if g.retry_num <= 8: #最多尝试8次
        if g.finish_trade == False:
            if sorted(context.portfolio.positions.keys()) != sorted(g.fund_targetpositions.keys()):
                sell(context, g.fund_targetpositions)
                buy(context, g.fund_targetpositions)
            else:
                g.finish_trade = True
    record(持仓比例=round(context.portfolio.positions_value / context.portfolio.total_value, 3))

# 基金拆分或分红后加仓，实盘应每天运行
def adding_to_position(context):
    now_positions_rate = context.portfolio.positions_value / context.portfolio.total_value #当前总仓位比例
    target_positions_rate = sum(list(g.fund_targetpositions.values())) #目标总仓位比例
    if target_positions_rate - now_positions_rate > 0.01: #误差超总仓位1%时触发加仓
        print("当前仓位比%s, 目标%s, 触发加仓" % (round(now_positions_rate,3), target_positions_rate))
        buy(context, g.fund_targetpositions)

# 选基程序
def check_out(context):
    # 只在首次运行或出基金每出季报的次月运行1次，确保取到最新季报数据
    if g.last_month != 0:
        if context.current_dt.strftime("%Y-%m") == g.last_month:
            return
        elif context.current_dt.month != 4:
            return
    g.finish_trade = False
    g.retry_num = 0
    g.last_month = context.current_dt.strftime("%Y-%m")
    current_date = context.current_dt.date()
    print(current_date)
    
    # 主区间
    last_report_date = get_report_date(current_date)
    fund_codes = get_fund_code(last_report_date, stock_rate_min=70)
    fund_asset = get_stock_asset(last_report_date, fund_codes, min_asset=g.min_asset)
    
    check_out_df = fund_asset.sort_values("stock_value")
    check_out_lists = [code +'.OF' for code in list(check_out_df.index)]
    
    # 去除会报错的数据
    err_lists = []
    for fund in check_out_lists:
        try:
            fund_info = get_fund_info(fund)
        except:
            err_lists.append(fund)
    
    check_out_lists = [fund for fund in check_out_lists if fund not in err_lists]
    check_out_lists = check_out_lists[:g.funds_num]

    # 分配目标仓位
    g.fund_targetpositions = {fund : 1 / len(check_out_lists) for fund in check_out_lists}

    trade(context)
    
    # 获取基金信息
    log.info("*" * 50)
    log.info("【目标基金列表】")
    for fund in g.fund_targetpositions.keys():
        rate_str = str(round(g.fund_targetpositions[fund] * 100, 1)) + "%"
        fund_info = get_fund_info(fund)
        log.info(rate_str + " " + fund + " " + fund_info['fund_name'])
    log.info("*" * 50)



'''
工具函数库
'''
# 赎回调仓交易函数, 需输入基金目标仓位dict
def sell(context, fund_targetpositions):
    # 空仓时不操作
    if len(context.portfolio.positions) == 0:
        return
    # 获取基金信息
    # fund_info = get_extras('unit_net_value', fund_targetpositions.keys(), start_date=context.previous_date, end_date=context.previous_date)
    # 赎回不在目标列表中的基金
    sell_list = [fund for fund in context.portfolio.positions if fund not in fund_targetpositions.keys()]
    for fund in sell_list:
        amount = context.portfolio.positions[fund].closeable_amount
        redeem(fund, amount)
        log.info("【清仓赎回】%s %s %i/%i 份", fund, get_fund_info(fund)['fund_name'], amount, amount)
    # 调仓
    for fund in list(fund_targetpositions.keys()):
        fund_name = get_fund_info(fund)['fund_name']
        weight = fund_targetpositions[fund]
        # 计算目标头寸大小
        position = int(weight * context.portfolio.total_value)
        # 标的偏离目标10%调仓
        if fund in context.portfolio.positions:
            amount = context.portfolio.positions[fund].closeable_amount
            value = context.portfolio.positions[fund].value
            rate = value / position
            if rate >= 1.1:
                # 按份额赎回
                redeem_amount = int(((rate - 1) / rate) * amount)
                redeem(fund, redeem_amount)
                log.info("【调仓赎回】%s %s %i/%i 份", fund, fund_name, redeem_amount, amount)

# 赎回调仓交易函数, 需输入基金目标仓位dict
def buy(context, fund_targetpositions):
    # 可用资金不足100元时不操作
    if context.portfolio.available_cash < 100:
        return
    # 获取基金信息
    # fund_info = get_extras('unit_net_value', fund_targetpositions.keys(), start_date=context.previous_date, end_date=context.previous_date)
    # 调仓和申购
    for fund in fund_targetpositions.keys():
        fund_name = get_fund_info(fund)['fund_name']
        weight = fund_targetpositions[fund]
        # 计算目标头寸大小
        position = int(weight * context.portfolio.total_value)
        # 标的偏离目标10%调仓
        if fund in context.portfolio.positions:
            amount = context.portfolio.positions[fund].closeable_amount
            value = context.portfolio.positions[fund].value
            rate = value / position
            if rate <= 0.9:
                # 按金额申购
                purchase_cash = position - value
                purchase(fund, purchase_cash)
                log.info("【调仓申购】%s %s %i 元", fund, fund_name, purchase_cash)
        else:
            purchase(fund, position)
            log.info("【建仓申购】%s %s %i 元", fund, fund_name, position)

# 求N年前的日期
def nyears_ago(end_date, nyears=10.0):
    d = dt.timedelta(days=-365.242199074 * nyears)
    return end_date + d

# 获取指定日期成立满1年且未退市的偏股混合基金
def get_fund_code(tradeDate, stock_rate_min=0, stock_rate_max=100):
    start_date=datetime.datetime.strptime(tradeDate,'%Y-%m-%d')-timedelta(days=365)
    start_date=start_date.strftime('%Y-%m-%d')
    report_date=get_report_date(tradeDate)
    codes=list(finance.run_query(query(finance.FUND_MAIN_INFO.main_code).filter(
            finance.FUND_MAIN_INFO.operate_mode_id.in_(["401001","401006"]), #开放式&LOF
            finance.FUND_MAIN_INFO.underlying_asset_type_id.in_(["402001","402004"]), #股基&混基
            finance.FUND_MAIN_INFO.invest_style_id.in_(["005001","005005"]), #股基+偏股混合基
            finance.FUND_MAIN_INFO.start_date < start_date).filter(
            (finance.FUND_MAIN_INFO.end_date > tradeDate) |
            (finance.FUND_MAIN_INFO.end_date == None)))['main_code'].values)
    # 限制股票占比高于70%
    codes=list(finance.run_query(query(finance.FUND_PORTFOLIO.code).filter(
        finance.FUND_PORTFOLIO.code.in_(codes), 
        finance.FUND_PORTFOLIO.stock_rate >= stock_rate_min,
        finance.FUND_PORTFOLIO.stock_rate <= stock_rate_max,
        finance.FUND_PORTFOLIO.period_end==report_date))['code'].values)
    return codes

#获取股票资产规模
def get_stock_asset(reportDate,code,min_asset=0):
    data = finance.run_query(query(
        finance.FUND_PORTFOLIO.code,
        finance.FUND_PORTFOLIO.stock_value
    ).filter(
        finance.FUND_PORTFOLIO.code.in_(code), 
        finance.FUND_PORTFOLIO.period_end==reportDate,
        finance.FUND_PORTFOLIO.stock_value > min_asset))
    data.set_index('code',inplace=True)
    data=data[~np.isinf(data)]
    data.dropna(inplace=True)
    print("%s：获取到%s只基金规模" % (reportDate, len(data)))
    return data

# 计算当前日期的上一个报表日
def get_report_date(tradeDate):
    if isinstance(tradeDate, str):
        tradeDate=datetime.datetime.strptime(tradeDate,"%Y-%m-%d")
    year=tradeDate.year
    month=tradeDate.month
    report_month=(month-1) //3*3
    if report_month==0:
        report_month=12
        year=year-1
    day=30
    if report_month in [3,12]:
        day=31
    report_date=str(year)+'-'+str(report_month).rjust(2,'0')+'-'+str(day)
    return report_date
