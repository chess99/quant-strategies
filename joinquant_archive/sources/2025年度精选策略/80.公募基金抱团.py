# 克隆自聚宽文章：https://www.joinquant.com/post/29768
# 标题：公募基金抱团
# 作者：dejiangwang

# 导入函数库
from jqdata import *

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

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
#   开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
#   开盘时运行
    run_daily(market_open, time='open', reference_security='000300.XSHG')
#   收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')

## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    # log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    time = datetime.datetime.strftime(context.current_dt, "%Y%m%d")
    year = time[:4]
    trade_day_1 = get_trade_days(end_date=year + '0131', count=1)[0]
    trade_day_1 = datetime.datetime.strftime(trade_day_1, "%Y%m%d")
    trade_day_2 = get_trade_days(end_date=year + '0430', count=1)[0]
    trade_day_2 = datetime.datetime.strftime(trade_day_2, "%Y%m%d")
    trade_day_3 = get_trade_days(end_date=year + '0731', count=1)[0]
    trade_day_3 = datetime.datetime.strftime(trade_day_3, "%Y%m%d")
    trade_day_4 = get_trade_days(end_date=year + '1031', count=1)[0]
    trade_day_4 = datetime.datetime.strftime(trade_day_4, "%Y%m%d")
    g.trade_day_list = [trade_day_1, trade_day_2, trade_day_3, trade_day_4]
    g.judge_date = datetime.datetime.strftime(context.current_dt, "%Y%m%d")

    if g.judge_date not in g.trade_day_list:
        return
    today_date = context.current_dt
    # 给微信发送消息（添加模拟交易，并绑定微信生效）
    # send_message('美好的一天~')
    end = today_date
    start = today_date - datetime.timedelta(180)
    fund_frame = finance.run_query(query(finance.FUND_MAIN_INFO).filter(finance.FUND_MAIN_INFO.underlying_asset_type == '股票型' , 
    finance.FUND_MAIN_INFO.operate_mode == '开放式基金', finance.FUND_MAIN_INFO.start_date <start,
    finance.FUND_MAIN_INFO.end_date == None))
    fund_frame_codes = fund_frame['main_code'].values
    df_all_fund_value = None
    for codes in fund_frame_codes:
        try:
            temp_value = finance.run_query(query(finance.FUND_NET_VALUE).filter(finance.FUND_NET_VALUE.code==codes, 
            finance.FUND_NET_VALUE.day>start, finance.FUND_NET_VALUE.day<end))
            a = temp_value.iloc[-88]['sum_value']
            b = temp_value.iloc[-1]['sum_value']
            fund_value = (b-a) / b
            df_fund_value = pd.DataFrame([temp_value['code'][0]], columns=['codes'])
            df_fund_value['values'] = fund_value
            df_all_fund_value = df_fund_value if df_all_fund_value is None else pd.concat([df_all_fund_value, df_fund_value], axis=0)
        except:
            continue
    df = df_all_fund_value.replace(np.inf, -1)
    fund_value_sort = df.sort_values(by='values', ascending=False)
    last_fund_list = fund_value_sort['codes'][:50].values
    all_data = None
    report_type = finance.run_query(query(finance.FUND_PORTFOLIO_STOCK).filter(finance.FUND_PORTFOLIO_STOCK.code==last_fund_list[0])).iloc[-1, :]['report_type']
    period_end = finance.run_query(query(finance.FUND_PORTFOLIO_STOCK).filter(finance.FUND_PORTFOLIO_STOCK.code==last_fund_list[0])).iloc[-1, :]['period_end']
    # 获取基金持股信息
    for code in last_fund_list:
        data = finance.run_query(query(finance.FUND_PORTFOLIO_STOCK).filter(finance.FUND_PORTFOLIO_STOCK.code==code, finance.FUND_PORTFOLIO_STOCK.period_end == period_end, finance.FUND_PORTFOLIO_STOCK.report_type == report_type).limit(10))
        select_data = data[['symbol','market_cap','proportion']]
        all_data = select_data if all_data is None else pd.concat([all_data, select_data], axis=0)
    all_data['count']=1
    security_list = all_data.groupby(all_data['symbol']).sum().sort_values(by='proportion', ascending=False).iloc[0:50]
    security_list['buy'] = (security_list['proportion'] / sum(security_list['proportion']))*1000000
    security_list.reset_index(inplace=True)
    security_list.index.astype(str)[:50]
    buy_list = security_list[['symbol', 'buy']]
    g.buy_list = buy_list

## 开盘时运行函数
def market_open(context):
    # log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    if g.judge_date not in g.trade_day_list:
        return
    buy_list = g.buy_list
    for future in context.portfolio.long_positions.keys():
        order_target(future, 0)
    security_all = []    
    for i in range(50):
        security = buy_list['symbol'][i]
        if len(security) == 5:
            continue
        if security[:2] == '30':
            security = security + '.XSHE'
        elif security[:2] == '60':
            security = security + '.XSHG'
        elif security[:2] == '00':
            security = security + '.XSHE'
        elif security[:2] == '68':
            security = security + '.XSHG'
        security_all.append(security)
    
    for i in range(len(security_all)):
        security = security_all[i]
        cash = buy_list['buy'][i]
        if security in context.portfolio.long_positions.keys():
            continue
        else:
            order_value(security, cash)
    for stock in context.portfolio.long_positions.keys():
        if stock not in security_all:
            order_target_value(stock, 0)


## 收盘后运行函数
def after_market_close(context):
    # log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    if g.judge_date not in g.trade_day_list:
        return
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    log.info('一天结束')
    log.info('##############################################################')
