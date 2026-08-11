# 克隆自聚宽文章：https://www.joinquant.com/post/47395
# 标题：回馈社区顺便搞积分《一个完整的机器学习pipeline》
# 作者：MarioC

from jqdata import *
from jqfactor import *
import numpy as np
import pandas as pd
import pickle



# 初始化函数
def initialize(context):
    # 设定基准
    set_benchmark('000985.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 设置交易成本万分之三，不同滑点影响可在归因分析中查看
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    # 初始化全局变量
    g.no_trading_today_signal = False
    g.stock_num = 5
    g.hold_list = []  # 当前持仓的全部股票
    g.yesterday_HL_list = []  # 记录持仓中昨日涨停的股票


    g.model = pickle.loads(read_file('model_baseline.pkl'))


    # 因子列表
    g.factor_list =  [
    "circulating_market_cap",
    "EBIT",
    "EBITDA",
    "financial_expense_ttm",
    "market_cap",
    "net_operate_cash_flow_ttm",
    "operating_profit_ttm",
    "sales_to_price_ratio",
    "sale_expense_ttm",
    "ATR14",
    "ATR6",
    "TVMA6",
    "VOL5",
    "VOL60",
    "VROC6",
    "VSTD20",
    "financing_cash_growth_rate",
    "net_asset_growth_rate",
    "operating_revenue_growth_rate",
    "total_asset_growth_rate",
    "arron_down_25",
    "arron_up_25",
    "fifty_two_week_close_rank",
    "ROC60",
    "single_day_VPT",
    "capital_reserve_fund_per_share",
    "cashflow_per_share_ttm",
    "net_operate_cash_flow_per_share",
    "operating_profit_per_share",
    "surplus_reserve_fund_per_share",
    "account_receivable_turnover_rate",
    "asset_turnover_ttm",
    "cfo_to_ev",
    "inventory_turnover_rate",
    "MLEV",
    "sale_expense_to_operating_revenue",
    "sharpe_ratio_20",
    "Variance20",
    "book_to_price_ratio",
    "earnings_to_price_ratio",
    "market_leverage",
    "boll_down",
    "boll_up",
    "MACDC",
    "MFI14",
    "price_no_fq"
]

    # 设置交易运行时间
    run_daily(prepare_stock_list, '9:05')
    run_monthly(weekly_adjustment, 1, '9:30')
    run_daily(check_limit_up, '14:00') 
    run_daily(close_account, '14:30')



# 1-1 准备股票池
def prepare_stock_list(context):
    # 获取已持有列表
    g.hold_list = []
    for position in list(context.portfolio.positions.values()):
        stock = position.security
        g.hold_list.append(stock)
    # 获取昨日涨停列表
    if g.hold_list != []:
        df = get_price(g.hold_list, end_date=context.previous_date, frequency='daily', fields=['close', 'high_limit'],
                       count=1, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        g.yesterday_HL_list = list(df.code)
    else:
        g.yesterday_HL_list = []

# 1-2 选股模块
def get_stock_list(context):
    # 指定日期防止未来数据
    yesterday = context.previous_date
    today = context.current_dt
    # 获取初始列表
    stocks = get_all_securities('stock', yesterday).index.tolist()
    initial_list = filter_kcbj_stock(stocks)
    initial_list = filter_st_stock(initial_list)
    initial_list = filter_paused_stock(initial_list)
    initial_list = filter_new_stock(context, initial_list)
    initial_list = filter_limitup_stock(context,initial_list)
    initial_list = filter_limitdown_stock(context,initial_list)
    
    final_list = []
    # MS
    factor_data = get_factor_values(initial_list, g.factor_list, end_date=yesterday, count=1)
    df_jq_factor_value = pd.DataFrame(index=initial_list, columns=g.factor_list)
    for factor in g.factor_list:
        df_jq_factor_value[factor] = list(factor_data[factor].T.iloc[:, 0])
    df_jq_factor_value = data_preprocessing(df_jq_factor_value, initial_list, industry_code, yesterday)
    tar = g.model.predict_proba(df_jq_factor_value)
    df = df_jq_factor_value
    df['total_score'] = list(tar[:, 1])
    df = df.sort_values(by=['total_score'], ascending=False)  # 分数越高即预测未来收益越高，排序默认降序
    lst = df.index.tolist()
    lst = lst[:min(g.stock_num, len(lst))]
    return lst


# 1-3 整体调整持仓
def weekly_adjustment(context):
    if g.no_trading_today_signal == False:
        # 获取应买入列表
        target_list = get_stock_list(context)
        # 调仓卖出
        for stock in g.hold_list:
            if (stock not in target_list) and (stock not in g.yesterday_HL_list):
                log.info("卖出[%s]" % (stock))
                position = context.portfolio.positions[stock]
                close_position(position)
            else:
                log.info("已持有[%s]" % (stock))
        # 调仓买入
        position_count = len(context.portfolio.positions)
        print(position_count)
        target_num = len(target_list)
        print(target_num)
        if target_num > position_count:
            print(context.portfolio.cash)
            value = context.portfolio.cash / (target_num - position_count)
            for stock in target_list:
                if context.portfolio.positions[stock].total_amount == 0:
                    if open_position(stock, value):
                        if len(context.portfolio.positions) == target_num:
                            break
 



# 1-4 调整昨日涨停股票
def check_limit_up(context):
    now_time = context.current_dt
    if g.yesterday_HL_list != []:
        # 对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
        for stock in g.yesterday_HL_list:
            current_data = get_price(stock, end_date=now_time, frequency='1m', fields=['close', 'high_limit'],
                                     skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True)
            if current_data.iloc[0, 0] < current_data.iloc[0, 1]:
                log.info("[%s]涨停打开，卖出" % (stock))
                position = context.portfolio.positions[stock]
                close_position(position)
            else:
                log.info("[%s]涨停，继续持有" % (stock))

# 3-1 交易模块-自定义下单
def order_target_value_(security, value):
    if value == 0:
        log.debug("Selling out %s" % (security))
    else:
        log.debug("Order %s to value %f" % (security, value))
    return order_target_value(security, value)


# 3-2 交易模块-开仓
def open_position(security, value):
    order = order_target_value_(security, value)
    if order != None and order.filled > 0:
        return True
    return False


# 3-3 交易模块-平仓
def close_position(position):
    security = position.security
    order = order_target_value_(security, 0)  # 可能会因停牌失败
    if order != None:
        if order.status == OrderStatus.held and order.filled == order.amount:
            return True
    return False


# 4-1 判断今天是否为账户资金再平衡的日期
def today_is_between(context, start_date, end_date):
    today = context.current_dt.strftime('%m-%d')
    if (start_date <= today) and (today <= end_date):
        return True
    else:
        return False


# 4-2 清仓后次日资金可转
def close_account(context):
    if g.no_trading_today_signal == True:
        if len(g.hold_list) != 0:
            for stock in g.hold_list:
                position = context.portfolio.positions[stock]
                close_position(position)
                log.info("卖出[%s]" % (stock))

# 2-1 过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]


# 2-2 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list
            if not current_data[stock].is_st
            and 'ST' not in current_data[stock].name
            and '*' not in current_data[stock].name
            and '退' not in current_data[stock].name]


# 2-3 过滤科创北交股票
def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68' or stock[0] == '3':
            stock_list.remove(stock)
    return stock_list


# 2-4 过滤涨停的股票
def filter_limitup_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] < current_data[stock].high_limit]


# 2-5 过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] > current_data[stock].low_limit]


# 2-6 过滤次新股
def filter_new_stock(context, stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if
            not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=375)]



def get_industry_name(i_Constituent_Stocks, value):
    return [k for k, v in i_Constituent_Stocks.items() if value in v]

#缺失值处理
def replace_nan_indu(factor_data,stockList,industry_code,date):
    #把nan用行业平均值代替，依然会有nan，此时用所有股票平均值代替
    i_Constituent_Stocks={}
    data_temp=pd.DataFrame(index=industry_code,columns=factor_data.columns)
    for i in industry_code:
        temp = get_industry_stocks(i, date)
        i_Constituent_Stocks[i] = list(set(temp).intersection(set(stockList)))
        data_temp.loc[i]=mean(factor_data.loc[i_Constituent_Stocks[i],:])
    for factor in data_temp.columns:
        #行业缺失值用所有行业平均值代替
        null_industry=list(data_temp.loc[pd.isnull(data_temp[factor]),factor].keys())
        for i in null_industry:
            data_temp.loc[i,factor]=mean(data_temp[factor])
        null_stock=list(factor_data.loc[pd.isnull(factor_data[factor]),factor].keys())
        for i in null_stock:
            industry=get_industry_name(i_Constituent_Stocks, i)
            if industry:
                factor_data.loc[i,factor]=data_temp.loc[industry[0],factor] 
            else:
                factor_data.loc[i,factor]=mean(factor_data[factor])
    return factor_data
industry_code = ['801010','801020','801030','801040','801050','801080','801110','801120','801130','801140','801150',\
                    '801160','801170','801180','801200','801210','801230','801710','801720','801730','801740','801750',\
                   '801760','801770','801780','801790','801880','801890']
def data_preprocessing(factor_data,stockList,industry_code,date):
    #去极值
    factor_data=winsorize_med(factor_data, scale=5, inf2nan=False,axis=0)
    #缺失值处理
    factor_data=replace_nan_indu(factor_data,stockList,industry_code,date)
    factor_data=standardlize(factor_data,axis=0)
    return factor_data
