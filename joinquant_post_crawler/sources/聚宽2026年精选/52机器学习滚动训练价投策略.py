# 克隆自聚宽文章：https://www.joinquant.com/post/47347
# 标题：机器学习滚动训练价投策略
# 作者：MarioC

from jqdata import *
from jqfactor import *
import numpy as np
import pandas as pd
import pickle
from xgboost import XGBClassifier,XGBRegressor
import warnings
from sklearn.preprocessing import StandardScaler
warnings.filterwarnings("ignore")

# 初始化函数
def initialize(context):
    # 设定基准
    set_benchmark('000905.XSHG')
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
    g.stock_num = 20
    g.hold_list = []  # 当前持仓的全部股票 'operating_revenue_growth_rate' ,'circulating_market_cap','BIAS20',
    g.yesterday_HL_list = []  # 记录持仓中昨日涨停的股票 circulating_market_cap
    # 因子列表
    g.factor_list =  [
    'liquidity', 'VDIFF', 'VEMA26', 'WVAD', 'money_flow_20'
     ]


    # 设置交易运行时间
    run_daily(prepare_stock_list, '9:05')
    run_monthly(weekly_adjustment, 1, '9:30')
    run_daily(check_limit_up, '14:00') 


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
        
def get_factor_data(securities_list,date):
    factor_data = get_factor_values(securities=securities_list, \
                                    factors=g.factor_list , \
                                    count=1, \
                                    end_date=date)
    df_jq_factor=pd.DataFrame(index=securities_list)
    for i in factor_data.keys():
        df_jq_factor[i]=factor_data[i].iloc[0,:]
    return df_jq_factor

# 1-2 选股模块
def get_stock_list(context):
    # 指定日期防止未来数据
    yesterday = context.previous_date
    initial_list = get_all_securities('stock', yesterday).index.tolist()
    initial_list = filter_kcbj_stock(initial_list)
    N=30
    by_date = get_trade_days(end_date=context.previous_date, count=10*N)
    by_date = by_date[::-1]
    dateList=by_date[::N]
    dateList=dateList[::-1].tolist()
    train_data=pd.DataFrame()
    for date in dateList[:-1]:
        S = get_all_securities('stock', date).index.tolist()
        S = filter_kcbj_stock(S)
        factor_origl_data = get_factor_data(S,date)
        median_values = factor_origl_data.median()
        factor_origl_data.fillna(median_values, inplace=True)
        data_close=get_price(S,date,dateList[dateList.index(date)+1],'1d','close')['close']
        factor_origl_data['pchg']=data_close.iloc[-1]/data_close.iloc[0]-1
        factor_origl_data=factor_origl_data.sort_values(by=['pchg'],ascending=False)
        factor_origl_data=factor_origl_data.iloc[:int(len(factor_origl_data['pchg'])/10*1),:].append(factor_origl_data.iloc[int(len(factor_origl_data['pchg'])/10*9):,:])
        factor_origl_data['label']=list(factor_origl_data['pchg'].apply(lambda x:1 if x>np.mean(list(factor_origl_data['pchg'])) else 0))  
        train_data=train_data.append(factor_origl_data)
    X_train = train_data[g.factor_list]
    y_train = train_data['label']
    classification_model = XGBClassifier(
        learning_rate=0.01, max_depth=10, min_child_weight=17, n_estimators=100, nthread=1, subsample=0.2
        )
    classification_model.fit(X_train, y_train)
    df = get_factor_data(initial_list,yesterday)
    median_values = df.median()
    df.fillna(median_values, inplace=True)
    X_test = df[g.factor_list]
    y_pred_proba =classification_model.predict_proba(X_test)[:, 1]
    df['total_score'] = list(y_pred_proba)
    df = df.sort_values(by=['total_score'], ascending=False)
    lst = df.index.tolist()
    N = int(len(lst)//5)
    lst = lst[:N]
    lst = get_stock_pool2(lst,context.current_dt)
    q = query(
    valuation.code
    ).filter(
	valuation.code.in_(lst)
	).order_by(
       	indicator.roa.desc())
    lst = list(get_fundamentals(q).code)[:g.stock_num]
    return lst
    
    
# 1-3 整体调整持仓
def weekly_adjustment(context):
    target_list = get_stock_list(context)
    for stock in g.hold_list:
        if (stock not in target_list) and (stock not in g.yesterday_HL_list):
            position = context.portfolio.positions[stock]
            close_position(position)
    position_count = len(context.portfolio.positions)
    target_num = len(target_list)
    if target_num > position_count:
        value = context.portfolio.cash / (target_num - position_count)
        for stock in target_list:
            if stock not in list(context.portfolio.positions.keys()):
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

def get_stock_pool2(stock_list,date):
    by_date = get_trade_days(end_date=date, count=120)[0]  
    all_stocks = get_all_securities(date=by_date).index.tolist()
    stock_list = list(set(stock_list).intersection(set(all_stocks)))
    # 过滤涨跌停，停牌
    stock_list = get_price(
        security=stock_list, frequency='1m', end_date=date, count=1,
        fields=['close', 'high_limit', 'low_limit', 'paused'], panel=False
    ).query(
        'close>low_limit and close< high_limit and paused==0'
    )['code'].tolist()
    # 过滤st
    s_extras = get_extras(info='is_st', security_list=stock_list, 
                          end_date=date, count=1).iloc[0]
    stock_list = s_extras[~s_extras].index.tolist()
    # 过滤：创业板，科创板，北交所
    stock_list = [stock for stock in stock_list if not stock.startswith(('3', '68', '4', '8'))]
    return stock_list

def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68' or stock[0] == '3':
            stock_list.remove(stock)
    return stock_list
    
