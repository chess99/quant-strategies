# 克隆自聚宽文章：https://www.joinquant.com/post/33840
# 标题：机器学习策略分享
# 作者：leo713

from jqfactor import *
from jqdata import *
from jqlib.optimizer import *
from datetime import date, timedelta
import pandas as pd
import talib as ta
from functools import reduce
from sklearn.linear_model import Lasso, ElasticNet
from sklearn.svm import SVC
from sklearn.preprocessing import scale, StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.decomposition import PCA
from sklearn.feature_selection import SelectKBest, f_classif
import os.path



### 全局变量
# features = []


# 策略初始
def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    log.set_level('order', 'error')
    set_option("avoid_future_data", True)
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003,
                            min_commission=5), type='stock')
    run_daily(market_open, time='open', reference_security='000300.XSHG')
    g.timer = 0
    ## 数据源
    g.dataSource = DataSource()
'''
######################策略的交易逻辑######################
每周计算因子值， 并买入前 20 支股票
'''
def tag_label(data):
    top_line = data.ret.quantile(0.7)
    bottom_line = data.ret.quantile(0.3)
    data = data[(data.ret > top_line) | (data.ret < bottom_line)]
    data['label'] = data.ret.apply(lambda x: 1 if x > top_line else 0)
    return data
    
def backtest(backtest_dt, timer):
    dataSource = g.dataSource
    stocks = DataSource.get_stocks(backtest_dt)
    if (timer + 1) % 1 == 0:
        print('更新因子权重')
        dates = get_trade_days(end_date=backtest_dt, count=200)[::30]
        before_df = dataSource.get_range_features(dates)
        before_df = before_df.dropna()
        before_df = before_df.groupby('time').apply(tag_label)
        print('训练数据量:', len(before_df))
        features = before_df.columns.difference(['ret', 'time', 'label'])
        model = Pipeline([
            ('pca', PCA()),
            ('svc', SVC(C=0.1, probability=True))
        ]).fit(before_df[features], before_df.label)
        
    current_df = dataSource.get(stocks, backtest_dt)
    current_df = current_df.dropna()
    print('当期数据量', len(current_df))
    current_df['score'] = model.predict_proba(current_df[features])[:, 1]
    current_df['label'] = model.predict(current_df[features])
    stock_to_buy = current_df[current_df.label == 1].sort_values('score').tail(10)
    stock_to_buy.loc[:, 'time'] = backtest_dt
    return stock_to_buy

def market_open(context):
    g.timer += 1
    if g.timer % 30 == 0:
        stock_to_buy = backtest(context.previous_date, g.timer)
        print('买入', stock_to_buy)
        rebalance_position(context, list(stock_to_buy.index))

def rebalance_position(context, stock_list):
    current_holding = context.portfolio.positions.keys()
    if len(stock_list) == 0:
        stocks_to_sell = stock_list
    else:
        stocks_to_sell = list(set(current_holding) - set(stock_list))
    # 卖出
    bulk_orders(stocks_to_sell, 0)
    
    total_value = context.portfolio.total_value
    if len(stock_list) > 0:
        bulk_optimize_orders(context, stock_list)
        
# 批量买卖股票
def bulk_orders(stock_list,target_value):
    for i in stock_list:
        order_target_value(i, target_value)

def bulk_optimize_orders(context, buy_list):
    optimized_weight = portfolio_optimizer(date=context.previous_date,
                                    securities = buy_list,
                                    target = MinVariance(count=250),
                                    constraints = [WeightConstraint(low=0.9, high=1.0),
                                                   AnnualProfitConstraint(limit=0.20, count=250)],
                                    bounds=[],
                                    default_port_weight_range=[0., 1.0],
                                    ftol=1e-09,
                                    return_none_if_fail=True)
    total_value = context.portfolio.total_value # 获取总资产
    if optimized_weight is None:
        return
    for stock in optimized_weight.keys():
        value = total_value * optimized_weight[stock] # 确定每个标的的权重
        order_target_value(stock, value) # 调整标的至目标权重 

'''
### 因子值 ####
'''
from jqfactor import Factor

class GROSSPROFITABILITY(Factor):
    # 设置因子名称
    name = 'gross_profitability'
    # 设置获取数据的时间窗口长度
    max_window = 1
    # 设置依赖的数据
    # 在策略中需要使用 get_fundamentals 获取的 income.total_operating_revenue, 在这里可以直接写做total_operating_revenue。 其他数据同理。
    dependencies = ['total_operating_revenue','total_operating_cost','total_assets']

    # 计算因子的函数， 需要返回一个 pandas.Series, index 是股票代码，value 是因子值
    def calc(self, data):
        # 获取单季度的营业总收入数据 , index 是日期，column 是股票代码， value 是营业总收入
        total_operating_revenue = data['total_operating_revenue']
        # 获取单季度的营业总成本数据
        total_operating_cost = data['total_operating_cost']
        # 获取总资产
        total_assets = data['total_assets']
        # 计算 gross_profitability
        gross_profitability = (total_operating_revenue - total_operating_cost)/total_assets
        # 由于 gross_profitability 是一个一行 n 列的 dataframe，可以直接求 mean 转成 series
        return gross_profitability.mean()
    
class MOM_N(Factor):
    dependencies = ['close']
    def __init__(self, day):
        self.name = f'mom_{day}'
        self.max_window = day
    def calc(self, data):
        close = data['close']
        return close.iloc[-1,:] / close.iloc[1,:] - 1
    
    
class CLOSE(Factor):
    name = 'close'
    max_window = 1
    dependencies = ['close']
    def calc(self, data):
        return data['close'].mean()
    
    
class PCF(Factor):
    name = 'PCF'
    max_window = 1
    dependencies = ['pcf_ratio']
    def calc(self, data):
        return 1 / data['pcf_ratio'].mean()
    
class BP(Factor):
    name = 'BP'
    max_window = 1
    dependencies = ['pb_ratio']
    def calc(self, data):
        return (1 / data['pb_ratio']).mean()
    
class NET_PROFIT_INCREASE(Factor):
    name = 'NET_PROFIT_INCREASE'
    max_window = 1
    dependencies = ['net_profit_1', 'net_profit_2', 'net_profit_3', 'net_profit_4']
    def calc(self, data):
        df = data['net_profit_1'].transpose()
        df = df.merge(data['net_profit_2'].transpose(), how='inner', on='code')
        df = df.merge(data['net_profit_3'].transpose(), how='inner', on='code')
        df = df.merge(data['net_profit_4'].transpose(), how='inner', on='code')
        increase = df.pct_change(axis=1)
        factor = increase.mean(axis=1) / increase.std(axis=1) 
        return factor
    
class ROA_TTM(Factor):
    name = 'ROA_TTM'
    max_window = 1
    dependencies = ['roa_1', 'roa_2', 'roa_3', 'roa_4']
    def calc(self, data):
        df = data['roa_1'].transpose()
        df = df.merge(data['roa_2'].transpose(), how='inner', on='code')
        df = df.merge(data['roa_3'].transpose(), how='inner', on='code')
        df = df.merge(data['roa_4'].transpose(), how='inner', on='code')
        increase = df.pct_change(axis=1)
        factor = increase.mean(axis=1) / increase.std(axis=1)
        return factor

class MARKET_CAP(Factor):
    name = 'MARKET_CAP'
    max_window = 1
    dependencies = ['circulating_market_cap']
    def calc(self, data):
        return np.log(data['circulating_market_cap'].mean())
    
class VSTD_20(Factor):
    name = 'VSTD_20'
    max_window = 20
    dependencies = ['volume', 'close']
    def calc(self, data):
        return data['volume'].std()
    
    
class MOENY_MAIN_INCREASE(Factor):
    name = 'MOENY_MAIN_INCREASE'
    max_window = 20
    dependencies = ['net_pct_main']
    def calc(self, data):
        return data['net_pct_main'].mean() / data['net_pct_main'].std()
    
class operating_revenue_increase(Factor):
    name = 'operating_revenue_increase'
    max_window = 1
    dependencies = ['operating_revenue_1', 'operating_revenue_2', 'operating_revenue_3', 'operating_revenue_4']
    def calc(self, data):
        df = data['operating_revenue_1'].transpose()
        df = df.merge(data['operating_revenue_2'].transpose(), how='inner', on='code')
        df = df.merge(data['operating_revenue_3'].transpose(), how='inner', on='code')
        df = df.merge(data['operating_revenue_4'].transpose(), how='inner', on='code')
        increase = df.pct_change(axis=1)
        return increase.mean(axis=1)
    
class ROE(Factor):
    name = 'ROE'
    max_window = 1
    dependencies = ['roe']
    def calc(self, data):
        return data['roe'].mean()
    
class ROA(Factor):
    name = 'ROA'
    max_window = 1
    dependencies = ['roa']
    def calc(self, data):
        return data['roa'].mean()
    
class std_N(Factor):
    dependencies = ['close']
    def __init__(self, window = 10):
        self.max_window = window
        self.name = f'std_{window}'
    def calc(self, data):
        return data['close'].std()
    
class SHARE_HOLDERS_INCREASE(Factor):
    name = 'SHARE_HOLDERS_INCREASE'
    dependencies = ['a_share_holders']
    max_window = 2
    def calc(self, data):
        return data['a_share_holders'].pct_change()
    
class CASH_RATIO(Factor):
    name = 'CASH_RATIO'
    dependencies = ['cash_to_current_liability']
    max_window = 1
    def calc(self, data):
        return data['cash_to_current_liability'].mean()
    
class SP(Factor):
    name = 'SP'
    dependencies = ['ps_ratio']
    max_window = 1
    def calc(self, data):
        return (1 / data['ps_ratio']).mean()
        
'''
### DataSource
'''
factor_custom = [
    CASH_RATIO(),
    GROSSPROFITABILITY(), 
    MOM_N(120), 
    MOM_N(60), 
    MOM_N(10), 
    CLOSE(),
    PCF(), 
    BP(), 
    SP(),
    ROA(),
    ROA_TTM(),
    MARKET_CAP(),
    NET_PROFIT_INCREASE(),
    VSTD_20(),
    MOENY_MAIN_INCREASE(),
    operating_revenue_increase(),
    ROE(),
    std_N(20),
    std_N(40),
    std_N(120),
#     SHARE_HOLDERS_INCREASE()
]
factor_custom_name = [i.name for i in factor_custom]


    

class DataSource:
    cache_file = 'feature_cache.csv'
    def __init__(self):
        if os.path.isfile(self.cache_file):
            print('读取缓存文件')
            self.cache = pd.read_csv(self.cache_file, index_col=0)
        else:
            self.cache = pd.DataFrame(columns=['time'])

    def get(self, stocks, date):
        print('获取数据日期:', date)
        if len(self.cache) > 0 and len(self.cache[self.cache.time == str(date)]) > 0:
             print('命中缓存')
             feature = self.cache[self.cache.time == str(date)]  
        else:
            feature = DataSource.get_features(stocks, date)
            self.update_cache(date, feature)
        return feature
    
    def update_cache(self, date, feature):
        feature.loc[:, 'time'] = str(date)
        self.cache = pd.concat([self.cache, feature], sort=False)
        print('更新数据源缓存')
        
    @staticmethod
    def get_features(stocks, date):
        factor_custom_df = calc_factors(stocks,factor_custom, start_date=date, end_date=date)
        result_df = pd.DataFrame(index=stocks)
        for i in factor_custom_name:
            factor_series = factor_custom_df[i].tail(1).transpose()
            factor_series = DataSource.format_factor(factor_series, date)
            result_df.loc[:, i] = factor_series
        return result_df
    
    @staticmethod
    def format_factor(factor_series, date, axis = 0):
        factor_series = winsorize_med(factor_series, scale=5, inclusive=True, inf2nan=True, axis=axis)
        factor_series = neutralize(factor_series, how=['jq_l1', 'market_cap'], fillna='sw_l1', date=date, axis=axis)
        factor_series = standardlize(factor_series, inf2nan=True, axis=axis)
        return factor_series
    
    def get_ret_df(self, pre, end, arr):
        stocks = self.get_stocks(pre)
        df = get_price(stocks, start_date=pre, end_date=end, panel=False, fq='post')
        df = df.groupby('code').apply(self.get_stock_ret)
        date = pre
        result_df = self.get(stocks, date)
        df = df.join(result_df)
        df.loc[:,'time'] = date
    
        arr.append(df)
        return end
    
    def get_range_features(self, dates):
        arr = []
        reduce(lambda x,y: self.get_ret_df(x, y, arr), dates)
        return pd.concat(arr) 
    
    def store(self):
        self.cache.to_csv(self.cache_file)
        
    @staticmethod
    def get_stocks(date):
        return get_index_stocks('000905.XSHG', date)
    
    @staticmethod
    def get_stock_ret(data):
        ret = data.close.pct_change()
        return pd.Series({
            'ret': ret.sum()
        })
    
