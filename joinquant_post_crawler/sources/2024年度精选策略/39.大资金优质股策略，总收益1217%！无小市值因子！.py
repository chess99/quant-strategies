# 克隆自聚宽文章：https://www.joinquant.com/post/42029
# 标题：大资金优质股策略，总收益1217%！无小市值因子！
# 作者：hello friends

from jqfactor import neutralize
from jqfactor import winsorize
from jqfactor import standardlize
import pandas as pd
import statsmodels.api as sm
from jqdata import *
from jqfactor import get_factor_values
import datetime

# 初始化函数
def initialize(context):
    # 设定基准
    set_benchmark('000905.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')

    # 初始化全局变量
    g.stock_num = 8#持股数
    g.limit_days = 20#用来检查最近20天内列表中有涨停的股票
    g.hold_list = []
    # 设置交易时间，每天运行
    run_daily(prepare_stock_list, time='9:05', reference_security='000300.XSHG')
    # run_weekly(weekly_adjustment, weekday=1, time='9:30', reference_security='000300.XSHG')
    run_monthly(monthly_adjustment, monthday=1, time='9:30', reference_security='000300.XSHG')
    #每周获取股票列表，去除最近20天内曾经涨停过的和曾经买过的股，去掉下跌趋势明显的
    run_daily(check_limit_up, time='14:00', reference_security='000300.XSHG')
    #把昨日涨停今天没涨停的股票卖出


# 1-2 选股模块：根据因子找出股票
def get_stock_list(context):
    yesterday=context.previous_date
    # 去掉次新股
    by_date = context.previous_date - datetime.timedelta(days=375)
    initial_list = get_all_securities(date=by_date).index.tolist()
    # 去科创，ST
    initial_list = filter_kcb_stock(initial_list)
    sample = filter_st_stock(initial_list)
    #FCF/市值和roe双因子得出
    q=query(valuation.code,
        (cash_flow.net_operate_cash_flow-cash_flow.subtotal_invest_cash_outflow)/100000000,
        (cash_flow.net_operate_cash_flow-cash_flow.subtotal_invest_cash_outflow)/(valuation.market_cap*100000000),
        indicator.roe,
        indicator.net_profit_margin,
        indicator.inc_net_profit_year_on_year,
        valuation.circulating_market_cap
       ).filter(valuation.code.in_(sample),#选股条件
               (cash_flow.net_operate_cash_flow-cash_flow.subtotal_invest_cash_outflow)/(valuation.market_cap*100000000)>0.02,
               indicator.adjusted_profit>0,#季度扣非利润
               indicator.roe>3,#季度ROE大于5%
               indicator.net_profit_margin>10,#净利率大于10%
               indicator.inc_net_profit_to_shareholders_year_on_year>5#归母净利同比增长＞5%，数据不对？？？
       ).order_by(
        (cash_flow.net_operate_cash_flow-cash_flow.subtotal_invest_cash_outflow)/(valuation.market_cap*100000000).desc()
       )
    #用DF来承接查询的数据
    df=get_fundamentals(q,date=None)
    #进行列名更改
    df.columns=['code', '自由现金流（亿元）','FCF/市值(排序列)','roe','净利率','归母净利润YOY','流通市值']
    df.index=df.code.values
    del df['code']
    df
    #去极值、中性化、标准化
    factors_list=['FCF/市值(排序列)','roe']
    df['score']=0
    for factor in factors_list:
        df[factor]=winsorize(df[factor], qrange=[0.05,0.93], inclusive=True, inf2nan=True, axis=0)#默认axis=1对行做处理
        df[factor]=neutralize(df[factor], how=['jq_l1', 'market_cap'], date=None, axis=0)#默认axis=1对行做处理，默认date=None                                                                                      #是否有未来函数？    
        df[factor]=standardlize(df[factor], inf2nan=True, axis=0)#默认axis=1对行做处理
        df['score']=df['score']+df[factor]
    #等权加分排序,取分数最高的前10个
    df3=df.sort_values("score",ascending=False).iloc[:10]
    WNS1_list=df3.index.tolist()    
    print('选股结果：',len(WNS1_list))
    return WNS1_list

# 1-3 准备股票池
def prepare_stock_list(context):
    # 获取已持有列表
    g.hold_list = list(context.portfolio.positions)

    
    # 获取持仓的昨日涨停列表
    g.high_limit_list = []
    if g.hold_list:
        df = get_price(g.hold_list, end_date=context.previous_date, frequency='daily',
                       fields=['close', 'high_limit', 'paused'],
                       count=1, panel=False)
        g.high_limit_list = df.query('close==high_limit and paused==0')['code'].tolist()#paused为0表示不停牌


# 1-4 整体调整持仓  
def monthly_adjustment(context):
    # type: (Context) -> None
    # 获取应买入列表
    target_list = get_stock_list(context)#获取股票列表
    #
    target_list = filter_paused_stock(target_list)
    target_list = filter_limit_stock(context, target_list)

    # 调仓：不在列表，昨日未涨停的持仓票卖出。
    for stock in g.hold_list:
        if (stock not in target_list) and (stock not in g.high_limit_list):
            log.info("卖出[%s]" % stock)
            position = context.portfolio.positions[stock]
            close_position(position)
        else:
            log.info("已持有[%s]" % stock)

    position_count = len(context.portfolio.positions)
    target_num = g.stock_num
    if target_num > position_count:
        value =  context.portfolio.available_cash / (target_num - position_count)
        for stock in target_list:
            if stock not in context.portfolio.positions:
                if open_position(stock, value):
                    if len(context.portfolio.positions) >= g.stock_num:
                        break


# 1-5 调整昨日涨停股票
def check_limit_up(context):
    current_data = get_current_data()
    if g.high_limit_list:#if list: list非0非空，则为true
        for stock in g.high_limit_list:
            if current_data[stock].last_price < current_data[stock].high_limit:
                log.info("[%s]涨停打开，卖出" % stock)
                position = context.portfolio.positions[stock]
                close_position(position)
            else:
                log.info("[%s]涨停，继续持有" % stock)


# 2-1 过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]


# 2-2 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not (
            current_data[stock].is_st or
            'ST' in current_data[stock].name or
            '*' in current_data[stock].name or
            '退' in current_data[stock].name)]



# 2-4 过滤涨停的股票
def filter_limit_stock(context, stock_list):
    # type: (Context, list) -> list
    current_data = get_current_data()
    holdings = list(context.portfolio.positions)
    return [stock for stock in stock_list if (stock in holdings) or
            current_data[stock].low_limit < current_data[stock].last_price < current_data[stock].high_limit]


# 2-6 过滤科创板
def filter_kcb_stock(stock_list):
    return [stock for stock in stock_list if not stock.startswith('68')]


# 3-1 交易模块-自定义下单
def order_target_value_(security, value):
    if value == 0:
        log.debug("Selling out %s" % security)
    else:
        log.debug("Order %s to value %f" % (security, value))
    return order_target_value(security, value)


# 3-2 交易模块-开仓
def open_position(security, value):
    _order = order_target_value_(security, value)
    if _order is not None and _order.filled > 0:
        return True
    return False


# 3-3 交易模块-平仓
def close_position(position):
    security = position.security
    _order = order_target_value_(security, 0)  # 可能会因停牌失败
    if _order is not None:
        if _order.status == OrderStatus.held and _order.filled == _order.amount:
            return True
    return False
