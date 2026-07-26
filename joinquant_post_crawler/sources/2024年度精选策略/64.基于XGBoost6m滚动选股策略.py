# 克隆自聚宽文章：https://www.joinquant.com/post/42706
# 标题：基于XGBoost_6m滚动选股策略
# 作者：雨汪

# 导入函数库
from jqdata import *
import numpy as np
import datetime
import pandas as pd
from jqfactor import get_factor_values
from jqfactor import winsorize_med
from jqfactor import standardlize
from jqfactor import neutralize
from scipy import stats
import statsmodels.api as sm
from statsmodels import regression
from jqlib.technical_analysis import *
from sklearn import svm
from xgboost import XGBClassifier
from sklearn.model_selection import GridSearchCV
from sklearn import metrics
import pickle


# 初始化函数，设定基准等等
def initialize(context):
    # 设定基准
    # g.benchmark = '000300.XSHG' #沪深300
    # g.benchmark = '000852.XSHG' #中证1000
    g.benchmark = '399905.XSHE' #中证500
    # g.benchmark = '399006.XSHE' #创业板指

    set_benchmark(g.benchmark)
    # 开启防未来函数
    set_option('avoid_future_data', True)
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    set_slippage(PriceRelatedSlippage(0)) 
    
    g.all_A = True #是否全A选股
    g.signal = True #开仓信号
    g.alllist = [] #股票池
    g.hold_list = [] # 今日持有的股票
    g.high_limit_list = [] # 前日涨停的股票
    g.stock_num = 10 #最大持仓个数
    
    g.windows = 6 #滚动训练窗口大小
    g.factor_cache = {} #因子缓存器
    
    g.regressor = XGBClassifier # 选用模型
    g.params = {'max_depth': 3, 'learning_rate': 0.05, 'subsample': 0.8} #经验参数
    # g.parameters = {'subsample':(0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1),
    #              'max_depth':(3, 4, 5, 6, 7, 8)} #交叉验证参数
    
    # g.regressor = svm.SVC # 选用模型
    # g.params = {'C': 3, 'gamma': 0.03} #经验参数
    # g.parameters = {'C':(0.01, 0.03, 0.1, 0.3, 1, 3, 10),
    #             'gamma':[1e-4, 3e-4, 1e-3, 3e-3, 0.01, 0.03, 0.1, 0.3, 1]} #交叉验证参数

    g.is_cv = False #是否交叉验证    

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
    # 开盘前运行
    run_daily(before_market_open, time='9:05', reference_security='000300.XSHG')
    # 开盘时运行
    run_daily(market_open, time='9:30', reference_security='000300.XSHG')
    # 开板止盈
    run_daily(check_limit_up, time='14:30', reference_security='000300.XSHG')

    

## 开盘前运行函数
def before_market_open(context):
    # 获取持仓的昨日涨停列表
    # 获取持仓
    g.hold_list = list(context.portfolio.positions)
    #获取昨日涨停列表
    if g.hold_list != []:
        yesterday = datetime.datetime.strftime(context.previous_date, '%Y-%m-%d')
        df = get_price(g.hold_list, end_date=yesterday, frequency='daily', fields=['close','high_limit'], count=1, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        g.high_limit_list = list(df.code)
    else:
        g.high_limit_list = []
    
    
    today = datetime.datetime.strftime(context.current_dt, '%Y-%m-%d')
    pre_m = datetime.datetime.strftime(context.previous_date, '%m')
    cur_m = datetime.datetime.strftime(context.current_dt, '%m')
    
    if cur_m != pre_m:
        start = datetime.datetime.now()
        # print('previous_date:%s current_dt:%s' % (context.previous_date, context.current_dt))
        g.signal = True
        stock_list = select_stocks(context)
        if g.all_A:
            # 沪深两市
            curr_stock_list = get_index_stocks('000002.XSHG', today) + get_index_stocks('399107.XSHE', today)
            # #沪深300、中证1000、中证500
            # curr_stock_list = get_index_stocks('000300.XSHG', today) + get_index_stocks('000852.XSHG', today) + get_index_stocks('399905.XSHE', today)
            curr_stock_list = list(set(curr_stock_list))
        else:
            curr_stock_list = get_index_stocks(g.benchmark, today)
            
        g.alllist = [stk for stk in stock_list if stk in curr_stock_list]
        end = datetime.datetime.now()
        print('选股总耗时:', (end-start))
    else:
        g.signal = False
        g.alllist = []

def select_stocks(context):
    # 1.获取截面T-m到T的所有交易日，其中T-m到T-1为训练数据，T为测试数据
    tody = datetime.datetime.strftime(context.current_dt, '%Y-%m-%d')
    yesterday = datetime.datetime.strftime(context.previous_date, '%Y-%m-%d')
    start_date = datetime.datetime.strftime(context.previous_date - datetime.timedelta(days=200), '%Y-%m-%d')
    date_list = get_period_date('M', start_date, yesterday)
    assert len(date_list) > g.windows
    if len(g.factor_cache) != 0:
        date_list = date_list[-g.windows-1:]
    else:
        t_m = int(g.windows/2) if g.windows > 1 else 1
        date_list = date_list[-t_m-1:]
    # 2.获取截面日期的因子值
    for date in g.factor_cache.copy().keys():
        if date not in date_list:
            del g.factor_cache[date]
    
    for date in date_list:
        if date in g.factor_cache:
            continue
        if g.all_A:
            #沪深两市
            stock_list = get_index_stocks('000002.XSHG', date) + get_index_stocks('399107.XSHE', date)
            # #沪深300、中证1000、中证500
            # stock_list = get_index_stocks('000300.XSHG', date) + get_index_stocks('000852.XSHG', date) + get_index_stocks('399905.XSHE', date)
            stock_list = list(set(stock_list))
        else:
            stock_list = get_index_stocks(g.benchmark, date)
            
        print('候选个数',len(stock_list), end=' ')
        # 排除st、科创板、北交所、次新股
        stock_list = filter_skbc_stock(context, stock_list)
        # 获取因子值
        print ('%s get_factor_data...' % date, end=' ')
        factor_origl_data = get_factor_data(stock_list, date)
        # print(factor_origl_data[:10])
        # 数据预处理
        print ('%s data_preprocessing...' % date, end=' ')
        industry_code = list(get_industries('sw_l1', date).index)
        factor_solve_data = data_preprocessing(factor_origl_data, stock_list, industry_code, date)
        # has_nan = factor_solve_data.isna().any()
        # cols_with_nan = has_nan[has_nan].index.tolist()
        # if len(cols_with_nan) != 0:
        #     print(cols_with_nan)
        # assert len(cols_with_nan) == 0
        factor_solve_data = factor_solve_data.dropna()
        assert factor_solve_data.shape[0] > 0
        
        # 添加下月收益
        if date_list.index(date) < len(date_list) - 1:
            stockList = list(factor_solve_data.index)
            data_close = pd.DataFrame()
            # print('%s %s'%(date, date_list[date_list.index(date)+1]))
            for stock in stockList:
                data_close[stock] = get_price(stock, date, date_list[date_list.index(date)+1], '1d', 'close')['close']
            factor_solve_data['pchg'] = data_close.iloc[-1] / data_close.iloc[0] - 1
            # has_nan = factor_solve_data.isna().any()
            # cols_with_nan = has_nan[has_nan].index.tolist()
            # if len(cols_with_nan) != 0:
            #     print('factor_cache,pchg',cols_with_nan)
            # assert len(cols_with_nan) == 0
            factor_solve_data = factor_solve_data.dropna()
            assert factor_solve_data.shape[0] > 0
        
        g.factor_cache[date] = factor_solve_data
    
    # 3.构造训练集
    train_data = pd.DataFrame()
    for date in date_list[:-1]:
        print(date, end=' ')
        traindf = g.factor_cache[date]
        if 'pchg' not in traindf:
            #取收益率数据
            stockList = list(traindf.index)
            data_close = pd.DataFrame()
            # print('%s %s'%(date, date_list[-1]))
            for stock in stockList:
                data_close[stock] = get_price(stock, date, date_list[-1], '1d', 'close')['close']
            # print(data_close[:1])
            # print(data_close[-1:])
            # a = data_close.iloc[-1] / data_close.iloc[0]
            # print(a[:10])
            traindf['pchg'] = data_close.iloc[-1] / data_close.iloc[0] - 1
            # has_nan = traindf.isna().any()
            # cols_with_nan = has_nan[has_nan].index.tolist()
            # print('train_data,pchg',cols_with_nan)
            # has_nan = traindf.isna().any(axis=1)
            # row_with_nan = has_nan[has_nan].index.tolist()
            # print('train_data,pchg',row_with_nan)
            # assert len(cols_with_nan) == 0
            traindf = traindf.dropna()
            assert traindf.shape[0] > 0
        #选取前后各30%的股票，剔除中间的噪声
        traindf = traindf.sort_values(by='pchg')
        traindf = traindf.iloc[:len(traindf['pchg'])//10*3,:].append(traindf.iloc[len(traindf['pchg'])//10*7:,:])
        traindf['label'] = list(traindf['pchg'].apply(lambda x:1 if x>np.mean(list(traindf['pchg'])) else -1))
        if train_data.empty:
            train_data = traindf
        else:
            train_data = train_data.append(traindf)
    train_target = train_data['label']
    train_feature= train_data.copy()
    del train_feature['pchg']
    del train_feature['label']
    
    # 4.创建网格搜索，进行时序交叉验证
    if g.is_cv:
        start = datetime.datetime.now()
        print ('\n开始交叉验证')
        clf = GridSearchCV(g.regressor, g.parameters, scoring='roc_auc',
                            cv=3, verbose=1)
        clf.fit(train_feature.values, train_target.values)
        print (clf.best_params_)
        print('交叉验证时长：', datetime.datetime.now()-start)
        g.params = clf.best_params_
    
    # 5.模型训练
    '''***************需要调整的地方****************'''
    clf = g.regressor(max_depth=g.params['max_depth'],
                       learning_rate=g.params['learning_rate'],
                       subsample=g.params['subsample'])
    # clf = g.regressor(C=g.params['C'],
    #              gamma=g.params['gamma'],
    #              probability=True)
    '''*******************************'''
    
    starttime = datetime.datetime.now()
    print ('开始训练模型...')
    clf.fit(train_feature.values, train_target.values)
    endtime = datetime.datetime.now()
    print ('模型训练时长：%.4f 分钟'%float((endtime - starttime).seconds/60))
    
    # 6.测试集选股
    date = date_list[-1]
    print(date, end=' ')
    test_feature = g.factor_cache[date]
    prob = clf.predict_proba(test_feature.values)[:, 1]
    # 按得分从高往低排
    df = pd.DataFrame(index=test_feature.index)
    df['score'] = list(prob)
    df = df.sort_values(by='score', ascending=False)
    # df = df[df['score'] > 0.6]
    # print(df[:10])
    # return list(df.index)
    
    
    df = df[:int(0.1*df.shape[0])]
    # df = df[df['score'] > 0.6]
    # print(df.shape)
    print(df[:10])
    stocks = list(df.index)
    q = query(valuation.code, indicator.eps).filter(valuation.code.in_(stocks)).order_by(valuation.circulating_market_cap.asc())
    df = get_fundamentals(q, yesterday).dropna()
    df = df[df['eps']>0]
    # print(df[:10])
    return list(df['code'])


## 开盘时运行函数
def market_open(context):
    # # 加入止盈
    # for stock in context.portfolio.positions:
    #     info = context.portfolio.positions[stock]
    #     cost = info.avg_cost
    #     price = info.price
    #     ret = price / cost - 1
    #     if ret >= 0.2 and stock not in g.high_limit_list:
    #         print('股票：%s 价格: %s 成本: %s 收益: %s' % (stock, price, cost, ret))
    #         order = order_target_value(stock, 0)
    #         if order != None:
    #             print('止盈卖出：%s 下单数量：%s 成交数量：%s'%(stock, order.amount, order.filled))
    #         else:
    #             print('止盈卖出[%s]失败。。。' % stock)
    
    # # # 加入超跌
    # down_buy_in = []
    # today = int(datetime.datetime.strftime(context.current_dt, '%d'))
    # for stock in context.portfolio.positions:
    #     info = context.portfolio.positions[stock]
    #     cost = info.avg_cost
    #     price = info.price
    #     ret = price / cost - 1
    #     if ret <= -0.2 and stock not in g.high_limit_list and not g.signal:
    #         # print("超跌..")
    #         print('股票：%s 价格: %s 成本: %s 收益: %s' % (stock, price, cost, ret))
    #         down_buy_in.append(stock)
    
    # target_num = len(down_buy_in)
    # if target_num > 0:
    #     value = context.portfolio.cash / target_num
    #     for stock in down_buy_in:
    #         order = order_value(stock, value)
    #         if order != None:
    #             print('超跌买入：%s 下单数量：%s 成交数量：%s'%(stock, order.amount, order.filled))
    #         else:
    #             print('超跌买入[%s]失败。。。' % stock)
    
    
    if not g.signal:
        return
    
    buylist = filter_limit_stock(context, g.alllist)[:g.stock_num]
    
    print('待买入股票池：%s'%str(buylist))
    print('待买入股票个数：%s'%len(buylist))
    # 调仓卖出
    for stock in context.portfolio.positions:
        if stock not in buylist and stock not in g.high_limit_list:
            order = order_target_value(stock, 0)
            if order != None:
                print('卖出股票：%s 下单数量：%s 成交数量：%s'%(stock, order.amount, order.filled))
            else:
                print('卖出股票[%s]失败。。。' % stock)
                
    # 调仓买入
    target_num = len(buylist)
    if target_num <= 0:
        return
    value = context.portfolio.total_value / target_num
    for stock in buylist:
        order = order_target_value(stock, value)
        if order != None:
            print('调仓：%s 调整至金额：%s 下单数量：%s 成交数量：%s'%(stock, value, order.amount, order.filled))
        else:
            print('调仓[%s]失败。。。' % stock)


## 排除st、科创板、北交所、次新股
def filter_skbc_stock(context, stock_list):
    e_stocks = []
    current_data = get_current_data()
    for stk in stock_list:
        # 排除st股票
        if current_data[stk].is_st or 'ST' in current_data[stk].name or\
        '*' in current_data[stk].name or '退' in current_data[stk].name:
            continue
        
        # 排除科创板
        if stk.startswith('688'):
            continue
        
        # 排除北交所
        if stk.startswith('43') or stk.startswith('8'):
            continue
        
        # 排除次新股(上市不足3个月)
        if (context.previous_date - datetime.timedelta(days=90)) < get_security_info(stk).start_date:
            continue
        
        e_stocks.append(stk)
        
    return e_stocks

def get_period_date(peroid, start_date, end_date):
    df = get_price('000001.XSHE', start_date, end_date, fields=['close'])
    df_sample = df.resample(peroid).last()
    date = df_sample.index
    pydate_array = date.to_pydatetime()
    date_array = np.vectorize(lambda x:x.strftime('%Y-%m-%d'))(pydate_array)
    date_list = list(date_array)
    start_date = datetime.datetime.strptime(start_date, '%Y-%m-%d') - datetime.timedelta(days=1)
    start_date = start_date.strftime('%Y-%m-%d')
    date_list = [start_date] + date_list
    return date_list

# 辅助线性回归的函数
def linreg(X, Y, columns=3):
    X = sm.add_constant(array(X))
    Y = array(Y)
    if len(Y) > 1:
        results = regression.linear_model.OLS(Y, X).fit()
        return results.params
    else:
        return [float("nan")] * (columns+1)
    
#取股票对应行业
def get_industry_name(i_Constituent_Stocks, value):
    return [k for k, v in i_Constituent_Stocks.items() if value in v]

#缺失值处理
def replace_nan_indu(factor_data, stockList, industry_code, date):
    #把nan用行业平均值代替，依然会有nan，此时用所有股票平均值代替
    i_Constituent_Stocks = {}
    data_temp = pd.DataFrame(index=industry_code, columns=factor_data.columns)
    for i in industry_code:
        temp = get_industry_stocks(i, date)
        i_Constituent_Stocks[i] = list(set(temp).intersection(set(stockList)))
        data_temp.loc[i] = mean(factor_data.loc[i_Constituent_Stocks[i], :])
    for factor in data_temp.columns:
        #行业缺失值用所有行业平均值代替
        null_industry = list(data_temp.loc[pd.isnull(data_temp[factor]), factor].keys())
        for i in null_industry:
            data_temp.loc[i,factor] = mean(data_temp[factor])
        null_stock = list(factor_data.loc[pd.isnull(factor_data[factor]), factor].keys())
        for i in null_stock:
            industry = get_industry_name(i_Constituent_Stocks, i)
            if industry:
                factor_data.loc[i, factor] = data_temp.loc[industry[0], factor] 
            else:
                factor_data.loc[i, factor] = mean(factor_data[factor])
    return factor_data

#数据预处理
def data_preprocessing(factor_data, stockList, industry_code, date):
    #去极值
    factor_data = winsorize_med(factor_data, scale=5, inf2nan=False,axis=0)
    #缺失值处理
    factor_data = replace_nan_indu(factor_data, stockList, industry_code, date)
    #中性化处理
    factor_data = neutralize(factor_data, how=['sw_l1', 'market_cap'], date=date, axis=0)
    #标准化处理
    factor_data = standardlize(factor_data, axis=0)
    return factor_data

#获取时间为date的全部因子数据
def get_factor_data(stock, date):
    data = pd.DataFrame(index=stock)
    q = query(valuation.market_cap, valuation.code, valuation.pb_ratio, valuation.ps_ratio, valuation.pcf_ratio, valuation.pe_ratio,
                balance.total_assets, balance.total_liability, balance.total_non_current_liability, balance.total_owner_equities,
                cash_flow.net_operate_cash_flow,
                income.operating_revenue, income.net_profit,
                indicator.roe, indicator.roa, indicator.gross_profit_margin, indicator.adjusted_profit
                ).filter(valuation.code.in_(stock))
    df = get_fundamentals(q, date)
    df['market_cap'] = df['market_cap']*100000000
    factor_data = get_factor_values(stock, ['roe_ttm', 'roa_ttm', 'total_asset_turnover_rate',
                                     'net_operate_cash_flow_ttm','net_profit_ttm', 
                                     'cash_to_current_liability','current_ratio',
                                     'gross_income_ratio','non_recurring_gain_loss',
                                    'operating_revenue_ttm','net_profit_growth_rate'],
                                    end_date=date,count=1)
    factor = pd.DataFrame(index=stock)
    for i in factor_data:
        factor[i] = factor_data[i].iloc[0]
    df.index = df['code']
    del df['code']
    #合并得大表
    df = pd.concat([df, factor], axis=1, sort=False)
    
    #净利润(TTM)/总市值
    data['EP'] = df['net_profit_ttm']/df['market_cap']
    #净资产/总市值
    data['BP'] = 1/df['pb_ratio']
    #营业收入(TTM)/总市值
    data['SP'] = 1/df['ps_ratio']
    #净现金流(TTM)/总市值
    data['NCFP'] = 1/df['pcf_ratio']
    #经营性现金流(TTM)/总市值
    data['OCFP'] = df['net_operate_cash_flow_ttm']/df['market_cap']
    #净利润(TTM)同比增长率/PE_TTM
    data['G/PE'] = df['net_profit_growth_rate']/df['pe_ratio']
    #ROE_ttm
    data['roe_ttm'] = df['roe_ttm']
    #ROE_YTD
    data['roe_q'] = df['roe']
    #ROA_ttm
    data['roa_ttm'] = df['roa_ttm']
    #ROA_YTD
    data['roa_q'] = df['roa']
    #毛利率TTM
    data['grossprofitmargin_ttm'] = df['gross_income_ratio']
    #毛利率YTD
    data['grossprofitmargin_q'] = df['gross_profit_margin']
    #扣除非经常性损益后净利润率YTD
    data['profitmargin_q'] = df['adjusted_profit']/df['operating_revenue']
    #资产周转率TTM
    data['assetturnover_ttm'] = df['total_asset_turnover_rate']
    #资产周转率YTD 营业收入/总资产
    data['assetturnover_q'] = df['operating_revenue']/df['total_assets']
    #经营性现金流/净利润TTM
    data['operationcashflowratio_ttm'] = df['net_operate_cash_flow_ttm']/df['net_profit_ttm']
    #经营性现金流/净利润YTD
    data['operationcashflowratio_q'] = df['net_operate_cash_flow']/df['net_profit']
    #净资产
    df['net_assets'] = df['total_assets'] - df['total_liability']
    #总资产/净资产
    data['financial_leverage'] = df['total_assets']/df['net_assets']
    #非流动负债/净资产
    data['debtequityratio'] = df['total_non_current_liability']/df['net_assets']
    #现金比率=(货币资金+有价证券)÷流动负债
    data['cashratio'] = df['cash_to_current_liability']
    #流动比率=流动资产/流动负债*100%
    data['currentratio'] = df['current_ratio']
    #总市值取对数
    data['ln_capital'] = np.log(df['market_cap'])
    
    #TTM所需时间
    his_date = [pd.to_datetime(date) - datetime.timedelta(90*i) for i in range(0, 4)]
    tmp = pd.DataFrame()
    tmp['code'] = stock
    for i in his_date:
        tmp_adjusted_dividend = get_fundamentals(query(indicator.code, indicator.adjusted_profit, \
                                                     cash_flow.dividend_interest_payment).
                                               filter(indicator.code.in_(stock)), date = i)
        tmp = pd.merge(tmp, tmp_adjusted_dividend, how='outer', on='code')

        tmp = tmp.rename(columns={'adjusted_profit':'adjusted_profit'+str(i.month), \
                                'dividend_interest_payment':'dividend_interest_payment'+str(i.month)})
    tmp = tmp.set_index('code')
    tmp_columns = tmp.columns.values.tolist()
    tmp_adjusted = sum(tmp[[i for i in tmp_columns if 'adjusted_profit' in i ]], 1)
    tmp_dividend = sum(tmp[[i for i in tmp_columns if 'dividend_interest_payment' in i ]], 1)
    #扣除非经常性损益后净利润(TTM)/总市值
    data['EPcut'] = tmp_adjusted/df['market_cap']
    #近12个月现金红利(按除息日计)/总市值
    data['DP'] = tmp_dividend/df['market_cap']
    #扣除非经常性损益后净利润率TTM
    data['profitmargin_ttm'] = tmp_adjusted/df['operating_revenue_ttm']
    #营业收入(YTD)同比增长率
    #_x现在 _y前一年
    his_date = pd.to_datetime(date) - datetime.timedelta(365)
    name = ['operating_revenue','net_profit','net_operate_cash_flow','roe']
    temp_data = df[name]
    his_temp_data = get_fundamentals(query(valuation.code, income.operating_revenue, income.net_profit,\
                                            cash_flow.net_operate_cash_flow,indicator.roe).
                                      filter(valuation.code.in_(stock)), date = his_date)
    his_temp_data = his_temp_data.set_index('code')
    #重命名 his_temp_data last_year
    for i in name:
        his_temp_data = his_temp_data.rename(columns={i:i+'last_year'})

    temp_data = pd.concat([temp_data, his_temp_data], axis=1, sort=False)
    #营业收入(YTD)同比增长率
    data['sales_g_q'] = temp_data['operating_revenue']/temp_data['operating_revenuelast_year']-1
    #净利润(YTD)同比增长率
    data['profit_g_q'] = temp_data['net_profit']/temp_data['net_profitlast_year']-1
    #经营性现金流(YTD)同比增长率
    data['ocf_g_q'] = temp_data['net_operate_cash_flow']/temp_data['net_operate_cash_flowlast_year']-1
    #ROE(YTD)同比增长率
    data['roe_g_q'] = temp_data['roe']/temp_data['roelast_year']-1
    
    #个股60个月收益与上证综指回归的截距项与BETA
    SZ_close = get_price('000001.XSHG', count = 60*20+1, end_date=date, frequency='daily', fields=['close'])['close']
    SZ_pchg = SZ_close.pct_change().iloc[1:]
    
    stock_close = pd.DataFrame()
    for i in stock:
        stock_close[i] = get_price(i, count=60*20+1, end_date=date, 
                                frequency='daily', fields=['close'])['close']
    stock_pchg = stock_close.pct_change().iloc[1:]
    
    beta = []
    stockalpha = []
    for i in stock:
        temp_beta, temp_stockalpha = stats.linregress(SZ_pchg, stock_pchg[i])[:2]
        beta.append(temp_beta)
        stockalpha.append(temp_stockalpha)
    #此处alpha beta为list
    data['alpha'] = stockalpha
    data['beta'] = beta
    
    #动量
    data['return_1m'] = stock_close.iloc[-1] / stock_close.iloc[-20]-1
    data['return_3m'] = stock_close.iloc[-1] / stock_close.iloc[-60]-1
    data['return_6m'] = stock_close.iloc[-1] / stock_close.iloc[-120]-1
    data['return_12m'] = stock_close.iloc[-1] / stock_close.iloc[-240]-1
    
    #取换手率数据
    data_turnover_ratio = pd.DataFrame()
    data_turnover_ratio['code'] = stock
    trade_days = list(get_trade_days(end_date=date, count=240*2))
    for i in trade_days:
        q = query(valuation.code,valuation.turnover_ratio).filter(valuation.code.in_(stock))
        temp = get_fundamentals(q, i)
        data_turnover_ratio = pd.merge(data_turnover_ratio, temp, how='left', on='code')
        data_turnover_ratio = data_turnover_ratio.rename(columns={'turnover_ratio':i})
    data_turnover_ratio = data_turnover_ratio.set_index('code').T
    
    #个股个股最近N个月内用每日换手率乘以每日收益率求算术平均值
    data['wgt_return_1m'] = mean(stock_pchg.iloc[-20:] * data_turnover_ratio.iloc[-20:])
    data['wgt_return_3m'] = mean(stock_pchg.iloc[-60:] * data_turnover_ratio.iloc[-60:])
    data['wgt_return_6m'] = mean(stock_pchg.iloc[-120:] * data_turnover_ratio.iloc[-120:])
    data['wgt_return_12m'] = mean(stock_pchg.iloc[-240:] * data_turnover_ratio.iloc[-240:])
    #个股个股最近N个月内用每日换手率乘以函数exp(-x_i/N/4)再乘以每日收益率求算术平均值
    temp_data = pd.DataFrame(index=data_turnover_ratio[-240:].index, columns=stock)
    temp=[]
    for i in range(240):
        if i/20 < 1:
            temp.append(exp(-i/1/4))
        elif i/20 < 3:
            temp.append(exp(-i/3/4))
        elif i/20 < 6:
            temp.append(exp(-i/6/4))
        elif i/20 < 12:
            temp.append(exp(-i/12/4))  
    temp.reverse()
    for i in stock:
        temp_data[i] = temp
    data['exp_wgt_return_1m'] = mean(stock_pchg.iloc[-20:] * temp_data.iloc[-20:] * data_turnover_ratio.iloc[-20:])
    data['exp_wgt_return_3m'] = mean(stock_pchg.iloc[-60:] * temp_data.iloc[-60:] * data_turnover_ratio.iloc[-60:])
    data['exp_wgt_return_6m'] = mean(stock_pchg.iloc[-120:] * temp_data.iloc[-120:] * data_turnover_ratio.iloc[-120:])
    data['exp_wgt_return_12m'] = mean(stock_pchg.iloc[-240:] * temp_data.iloc[-240:] * data_turnover_ratio.iloc[-240:])

    
    #特异波动率
    #获取FF三因子残差数据
    LoS = len(stock)
    S = df.sort_values(by='market_cap')[:LoS//3].index
    B = df.sort_values(by='market_cap')[LoS-LoS//3:].index
    
    df['BTM'] = df['total_owner_equities'] / df['market_cap']
    L = df.sort_values(by='BTM')[:LoS//3].index
    H = df.sort_values(by='BTM')[LoS-LoS//3:].index
    df_temp = stock_pchg.iloc[-240:]
    #求因子的值
    SMB = sum(df_temp[S].T)/len(S) - sum(df_temp[B].T)/len(B)
    HMI = sum(df_temp[H].T)/len(H) - sum(df_temp[L].T)/len(L)
    #用沪深300作为大盘基准
    dp = get_price('000300.XSHG', count=12*20+1, end_date=date, frequency='daily', fields=['close'])['close']
    RM = dp.pct_change().iloc[1:] - 0.04/252
    #将因子们计算好并且放好
    X = pd.DataFrame({"RM":RM, "SMB":SMB, "HMI":HMI})
    resd = pd.DataFrame()
    for i in stock:
        temp = df_temp[i] - 0.04/252
        t_r = linreg(X, temp)
        resd[i] = list(temp-(t_r[0]+X.iloc[:,0]*t_r[1]+X.iloc[:,1]*t_r[2]+X.iloc[:,2]*t_r[3]))
    data['std_FF3factor_1m'] = resd[-1*20:].std()
    data['std_FF3factor_3m'] = resd[-3*20:].std()
    data['std_FF3factor_6m'] = resd[-6*20:].std()
    data['std_FF3factor_12m'] = resd[-12*20:].std()
    
    #波动率
    data['std_1m'] = stock_pchg.iloc[-20:].std()
    data['std_3m'] = stock_pchg.iloc[-60:].std()
    data['std_6m'] = stock_pchg.iloc[-120:].std()
    data['std_12m'] = stock_pchg.iloc[-240:].std()

    #股价
    data['ln_price'] = np.log(stock_close.iloc[-1])
    
    
    #换手率
    data['turn_1m'] = mean(data_turnover_ratio.iloc[-20:])
    data['turn_3m'] = mean(data_turnover_ratio.iloc[-60:])
    data['turn_6m'] = mean(data_turnover_ratio.iloc[-120:])
    data['turn_12m'] = mean(data_turnover_ratio.iloc[-240:])
    
    data['bias_turn_1m'] = mean(data_turnover_ratio.iloc[-20:]) / mean(data_turnover_ratio) - 1
    data['bias_turn_3m'] = mean(data_turnover_ratio.iloc[-60:]) / mean(data_turnover_ratio) - 1
    data['bias_turn_6m'] = mean(data_turnover_ratio.iloc[-120:]) / mean(data_turnover_ratio) - 1
    data['bias_turn_12m'] = mean(data_turnover_ratio.iloc[-240:]) / mean(data_turnover_ratio) - 1
    
    #技术指标
    data['PSY'] = pd.Series(PSY(stock, date, timeperiod=20))
    data['RSI'] = pd.Series(RSI(stock, date, N1=20))
    data['BIAS'] = pd.Series(BIAS(stock,date, N1=20)[0])
    dif, dea, macd = MACD(stock, date, SHORT = 10, LONG = 30, MID = 15)
    data['DIF'] = pd.Series(dif)
    data['DEA'] = pd.Series(dea)
    data['MACD'] = pd.Series(macd)
    
    return data

# 排除涨/跌停、停牌股票
def filter_limit_stock(context, stock_list):
    stk_list = []
    current_data = get_current_data()
    for stk in stock_list:
        # 排除涨跌停
        if current_data[stk].last_price >= current_data[stk].high_limit or\
            current_data[stk].last_price <= current_data[stk].low_limit:
            continue
        # 排除停牌股票
        if current_data[stk].paused:
            continue
        stk_list.append(stk)
    return stk_list



def check_limit_up(context):
    now_time = context.current_dt
    if g.high_limit_list != []:
        #对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
        for stock in g.high_limit_list:
            current_data = get_price(stock, end_date=now_time, frequency='1m', fields=['close','high_limit'], skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True)
            if current_data.iloc[0]['close'] < current_data.iloc[0]['high_limit']:
                log.info("[%s]涨停打开，卖出" % (stock))
                order = order_target_value(stock, 0)
                if order != None:
                    print('涨停打开-卖出股票：%s 下单数量：%s 成交数量：%s'%(stock, order.amount, order.filled))
                else:
                    print('涨停打开-卖出股票[%s]失败。。。' % stock)
            else:
                log.info("[%s]涨停，继续持有" % (stock))
    g.high_limit_list = []

## 收盘后运行函数
def after_market_close(context):
    return
