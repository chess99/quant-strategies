# 克隆自聚宽文章：https://www.joinquant.com/post/35253
# 标题：【回撤二波2.0】透过一次过拟合的机器学习摸底策略的收益上限
# 作者：_查尔斯葱_

# 标题：回撤二波
# 作者：查尔斯葱

# 导入函数库
from jqdata import *
from jqlib.technical_analysis import *
import lightgbm as lgb
import pickle

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
    # g 内置全局变量
    g.my_security = '000300.XSHG'
    set_universe([g.my_security])
    g.stock_list = []
    # 买入股票数
    g.buy_stock_num = 5
    
    # g.model_path = './gbm_model_v1_all.pkl'
    # g.model_path = './gbm_model_v1_unbalanced.pkl'
    g.model_zb_path = './gbm_fit_model_v1_zb.pkl'
    g.model_cyb_path = './gbm_fit_model_v1_cyb.pkl'
    g.model_zb = pickle.loads(read_file(g.model_zb_path)) # 加载模型
    g.model_cyb = pickle.loads(read_file(g.model_cyb_path)) # 加载模型
    
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
    # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    # 开盘时运行
    run_daily(market_open_buy, time='09:30', reference_security='000300.XSHG')
    # run_daily(market_open_sell, time='14:00', reference_security='000300.XSHG')
    run_daily(market_open_sell, time='every_bar', reference_security='000300.XSHG')# every_bar 每分钟

    # 收盘后运行before_open
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')


# 买入函数
def market_open_buy(context):
    if len(context.portfolio.positions) < g.buy_stock_num:
        new_buy_stock_num = g.buy_stock_num - len(context.portfolio.positions)
        buy_cash = context.portfolio.available_cash / new_buy_stock_num
        for s in g.stock_list[:new_buy_stock_num]:
            if s not in context.portfolio.positions and\
                context.portfolio.available_cash >= buy_cash >= 100 * get_current_data()[s].last_price:
                order_target_value(s, buy_cash)
                print(f'买入股票：{s}')
                send_message(f'买入股票：{s}')
    
    
## 开盘时运行函数
def market_open_sell(context):
    sells = list(context.portfolio.positions)
    for s in sells:
        keep_days = context.current_dt - context.portfolio.positions[s].init_time
        keep_days = keep_days.days
        loss = context.portfolio.positions[s].price / context.portfolio.positions[s].avg_cost
        s_sell, sell_msg = check_sell_point(context, s)
        if s_sell or loss < 0.95:
            if keep_days >= 0 and context.portfolio.positions[s].closeable_amount>0:
                order_target_value(s, 0)
                print(f'卖出股票：{s}, sell_msg={sell_msg}')
                send_message(f'卖出股票：{s}, sell_msg={sell_msg}')

def check_sell_point(context, stock):
    s_sell = False
    
    #持仓股票的当前价
    current_price = get_current_data()[stock].last_price
    # == context.portfolio.positions[stock].price 
    # 按天交易，【尾盘】跌破MA5或日内高点回撤5个点即撤
    bars = get_bars(stock, 60, '1d', ['close'], include_now=True)
    _close = bars['close']
    _close[-1] = current_price
    # ma3 & ma5
    ma3 = _close[-3:].mean()
    ma5 = _close[-5:].mean()
    ma55 = _close[-55:].mean()
    ma55_ = _close[-56:-1].mean()
    
    # # 按分钟交易，跌破MA5或日内高点回撤3个点即撤
    now = context.current_dt
    zeroToday = now - datetime.timedelta(hours=now.hour, minutes=now.minute, seconds=now.second,microseconds=now.microsecond)
    lastToday = zeroToday + datetime.timedelta(hours=9, minutes=31, seconds=00)
    df_panel_allday = get_price(stock, start_date=lastToday, end_date=context.current_dt, frequency='minute', fields=['high'])
    high_allday = df_panel_allday.loc[:, "high"].max()
    loss = current_price / context.portfolio.positions[stock].avg_cost
    
    # 跌破MA5 / 下跌3% / 高点回撤3% / 成本损失5%
    signal1 = current_price / _close[-2] < 0.98 and current_price < ma5
    signal2 = current_price / _close[-2] < 0.97
    signal3 = current_price / high_allday < 0.97
    signal4 = loss < 0.97
    signal5 = current_price < ma55 and _close[-2] > ma55_
    if signal1 or signal2 or signal3 or signal4 or signal5:
        s_sell = True
    msg = []
    if signal1:
        msg.append('跌破MA5')
    if signal2:
        msg.append('下跌3%')
    if signal3:
        msg.append('高点回撤3%')
    if signal4:
        msg.append('总亏损5%')
    if signal5:
        msg.append('跌破MA55')
    
    return s_sell, msg

## 选出符合条件的股票
def before_market_open(context):
    date_now =  (context.current_dt + timedelta(days = -1)).strftime("%Y-%m-%d")
    ten_days_ago = (context.current_dt + timedelta(days = -10)).strftime("%Y-%m-%d")
    # print('date_now=', date_now)
    # print('two_month_ago=', two_month_ago)
    trade_date = get_trade_days(start_date=ten_days_ago, end_date=date_now, count=None)
    end_date = trade_date[-1] # 开始回测的前一天
    stocks = list(get_all_securities(['stock'], date=end_date).index)
    
    # 去掉停牌和ST
    stocks = filter_st(stocks)
    stocks = filter_paused_stock(stocks)
    
    all_price = get_price(stocks, count=1, end_date=end_date, frequency='daily',
                          fields=['close', 'pre_close'], panel=False)
    up_num = len(all_price.query('close > pre_close')['code'])
    all_stock_num = len(stocks)
    up_num_ratio = up_num / all_stock_num
    
    # stocks = filter_kcb_cyb_stock(context, stocks)
    #选出符合条件的股票
    stocks = lightGBM_filter_stock(stocks, end_date, up_num_ratio)
    
    stocks = filter_stock_by_days(context, stocks, 150)
    g.stock_list = stocks
    print(f'选出的股票：{g.stock_list}')
    send_message(f'选出的股票：{g.stock_list}')


##选出2个月内涨停过2次，总涨幅大于30%且目前回撤超过20%的股票，当前处于最高点回撤下来的低点
def lightGBM_filter_stock(stocks, end_date, up_num_ratio):
    filtered_stocks = []
    filtered_stocks_with_criteria = {}
    rise_prob = 0
    
    for stock in stocks[:]:
        
        features_now = get_features(stock, end_date, up_num_ratio)
        
        if len(features_now) == 12:
            [up_num_ratio, get_high_limit_num_40_days, _close_max_index,
            get_rise_num_40_days, macd_1_day, macd_2_day, macd_3_day,
            compare_early_low, rise_before, withdraw_before, low_3_days_std,
            volume_reduce] = features_now
            
            if 10 < _close_max_index < 35:
                # GBDT
                # rise_prob = g.model.predict_proba([features_now])[:,1][0]
                
                # lightGBM fit
                # predict result is like: [[0.9794205324559725 0.02057946754402755]]
                rise_prob = 0
                if stock[:2] != '30':
                    rise_prob = g.model_zb.predict([features_now], raw_score=True)[0][1]
                else:
                    rise_prob = g.model_cyb.predict([features_now], raw_score=True)[0][1]
                # lightGBM train
                # rise_prob = g.model.predict([features_now])[0]
                # print(f'rise_prob={rise_prob}')
                # print(f'features_now={features_now}')
        
                if rise_prob > 0.75:
                    filtered_stocks_with_criteria[stock] = rise_prob
            
    filtered_stocks_ordered = sorted(filtered_stocks_with_criteria.items(), key = lambda x:x[1], reverse=True)
    send_message(f'筛选后的股票及概率值：{filtered_stocks_ordered}')
    for i in range(len(filtered_stocks_ordered)):
        filtered_stocks.append(filtered_stocks_ordered[i][0])

    return filtered_stocks
    
def get_features(stock, end_date, up_num_ratio):
    features = []
    target_value = 0
    
    # print(f'end_date={end_date}')
    # 这样get_bars才会包含end_Date当天
    end_date = end_date.strftime("%Y-%m-%d") + ' 15:30:00'
    end_date = datetime.datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S")
    
    bars = get_price(stock, count=40, end_date=end_date, frequency='daily',\
        fields=['open', 'close', 'high_limit'], panel=False, fill_paused=False)
    _close = bars['close'].values
    
    get_high_limit_num_40_days = (bars.loc[:, 'close'] == bars.loc[:, 'high_limit']).sum()
    get_rise_num_40_days = (bars.loc[:, 'close'] > bars.loc[:, 'open']).sum()
    
    bars_pre = get_bars(stock, 40, '1d', ['close', 'low', 'volume', 'money'], end_dt=end_date, include_now=True)

    if mean(_close) > 0 and len(bars_pre) == 40:
        closes = bars_pre['close']
        lows = bars_pre['low']
        volumes = bars_pre['volume']
        
        # calc MACD
        one_day_before_pre = (end_date + timedelta(days = -1)).strftime("%Y-%m-%d")
        two_day_before_pre = (end_date + timedelta(days = -2)).strftime("%Y-%m-%d")
        _, _, macd_1_day = MACD(stock, end_date, SHORT=12, LONG=26, MID=9)
        _, _, macd_2_day = MACD(stock, one_day_before_pre, SHORT=12, LONG=26, MID=9)
        _, _, macd_3_day = MACD(stock, two_day_before_pre, SHORT=12, LONG=26, MID=9)
        macd_1_day = macd_1_day[stock]
        macd_2_day = macd_2_day[stock]
        macd_3_day = macd_3_day[stock]
        
        _close_bak = list(closes[:])
        _close_max_index = _close_bak.index(max(_close_bak))
        close_max = closes[_close_max_index]
        
        if _close_max_index > 10:
            compare_early_low = min(lows[-3:]) / min(lows[:_close_max_index])
            rise_before = close_max / min(closes[:_close_max_index])
            withdraw_before = closes[-1] / close_max

            # 横盘缩量（近3天的量<前8-5天的量）
            low_3_days_std = std(lows[-3:]) / min(lows[-3:]) # 0.015
            volume_reduce = mean(volumes[-3:]) / mean(volumes[-8:-3]) # 1.0
            
            features = [up_num_ratio, get_high_limit_num_40_days, _close_max_index,
                        get_rise_num_40_days, macd_1_day, macd_2_day, macd_3_day,
                        compare_early_low, rise_before, withdraw_before, low_3_days_std,
                        volume_reduce]
    return features
    
## 去除st的股票
def filter_st(codelist):
    current_data = get_current_data()
    codelist = [code for code in codelist if not current_data[code].is_st]
    return codelist

# 过滤停牌的股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]

##过滤上市时间不满days天的股票
def filter_stock_by_days(context, stock_list, days):
    tmpList = []
    for stock in stock_list :
        days_public=(context.current_dt.date() - get_security_info(stock).start_date).days
        if days_public > days:
            tmpList.append(stock)
    return tmpList

# 过滤科创板/创业板
def filter_kcb_cyb_stock(context, stock_list):
    return [stock for stock in stock_list  if stock[0:3] != '688' and stock[0:2] != '30']

## 收盘后运行函数
def after_market_close(context):
    # log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    g.stock_list = []
    log.info('一天结束')
    log.info('##############################################################')
