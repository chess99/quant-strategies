# 克隆自聚宽文章：https://www.joinquant.com/post/37573
# 标题：【复现】因子择时？？？
# 作者：Hugo2046

'''
回测会读取研究文档生成的四个本地文件:
Ret_mat.csv,datas.csv,df_m_shifted_.csv,weight_in.csv
如果无上述文件程序将会报错

** 此回测仅用于机器学习模型的评价
----------------------------
宏观数据每月公布可能会存在滞后性 在实际中不一定获取的及时
部分因子和因子收益都是月末的 所以还是存在引用未来数据的风险
'''

from jqdata import *
from jqfactor import get_factor_values

import pandas as pd
import numpy as np

# 日常处理
import datetime
import calendar
from dateutil.relativedelta import relativedelta

# 线性模型库
import statsmodels.api as sm

# 计算
import scipy.stats as ss
from scipy.stats import zscore,spearmanr

# 机器学习
from sklearn import linear_model,svm   
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier


from six import BytesIO # 读取研究环境文件用

enable_profile()  # 开启性能分析

def initialize(context):
   
    set_params()
    set_variables()
    set_backtest()
    
    run_monthly(Trade,-1 ,time='open', reference_security='000300.XSHG')


def set_params():

    g.index_symbol = '000300.XSHG'  # 目标指数
    g.N = 50
    
    '''
    method参数可选：
    SVM
    Logistic
    RandomForest
    not_timing <========仅因子选股无择时
    '''
    g.method = 'not_timing' # 'SVM','Logistic','RandomForest','not_timing'
    g.stocks_df = pd.DataFrame()


def set_variables():
    

    g.Ret_mat = pd.read_csv(BytesIO(read_file('Data/Ret_mat.csv')),index_col=[0],parse_dates=True)
    g.datas = pd.read_csv(BytesIO(read_file('Data/datas.csv')),index_col=[0,1],parse_dates=True)
    g.df_m_shifted_ = pd.read_csv(BytesIO(read_file('Data/df_m_shifted_.csv')),index_col=[0],parse_dates=True)
    g.weight_in = pd.read_csv(BytesIO(read_file('Data/weight_in.csv')),index_col=[0],parse_dates=True)


def set_backtest():

    set_option("avoid_future_data", True)  # 避免数据
    set_option("use_real_price", True)  # 真实价格交易
    set_benchmark('000300.XSHG')  # 设置基准
    #log.set_level("order", "debuge")
    log.set_level('order', 'error')


# 每日盘前运行
def before_trading_start(context):
    
    # 初始运行时
    if g.stocks_df.empty:
        Preprocessing()
        
    # 手续费设置
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))

    # 根据不同的时间段设置手续费
    dt = context.current_dt

    if dt > datetime.datetime(2013, 1, 1):
        set_commission(PerTrade(buy_cost=0.0003, sell_cost=0.0013, min_cost=5))

    elif dt > datetime.datetime(2011, 1, 1):
        set_commission(PerTrade(buy_cost=0.001, sell_cost=0.002, min_cost=5))

    elif dt > datetime.datetime(2009, 1, 1):
        set_commission(PerTrade(buy_cost=0.002, sell_cost=0.003, min_cost=5))

    else:
        set_commission(PerTrade(buy_cost=0.003, sell_cost=0.004, min_cost=5))
        
        
'''
=====================================================================================
                        Tools
=====================================================================================
'''
def Preprocessing():
    
    if g.method == 'SVM':
        th=0.05
        z=0.1  #设置阈值和权重调整系数
        print('%s模型,th:%s,z:%s'%(g.method,th,z))
        GetTargetDf(th,z)
        
    elif g.method == 'Logistic':
        th=0.1
        z=0.2
        print('%s模型,th:%s,z:%s'%(g.method,th,z))
        GetTargetDf(th,z)
        
    elif g.method == 'RandomForest':
        
        th=0
        z=0.1
        print('%s模型,th:%s,z:%s'%(g.method,th,z))
        GetTargetDf(th,z)
    
    elif g.method == 'not_timing':
        
        print(g.method)
        
        r2 = rolling_R2(g.df_m_shifted_.fillna(0),g.Ret_mat.fillna(0),window=24)  #计算拟合优度
        weight_new = pd.DataFrame(1/len(g.weight_in.columns),index=r2.index.tolist(),columns=g.weight_in.columns)
        g.stocks_df = get_portfolio(weight_new,g.datas,number=g.N) #选股
        
    
def GetTargetDf(th,z):
    
    r2 = rolling_R2(g.df_m_shifted_.fillna(0),g.Ret_mat.fillna(0),window=24)  #计算拟合优度
    predict_mat = run_predict_models(g.Ret_mat,g.df_m_shifted_,method=g.method,window=24) #预测因子收益的方向
    weight_new= weight_timing_threshold(g.Ret_mat,predict_mat,g.weight_in,r2,th,z)  #动态权重设置
    g.stocks_df = get_portfolio(weight_new,g.datas,number=g.N) #选股

    
    

# 输入参数：df_m_shifted_i（某段时间的择时变量），Ret_mat（对应时段的因子收益）
def R_squared(df_m_shifted_i:pd.DataFrame, Ret_mat:pd.DataFrame)->pd.DataFrame:

    # 提取输入的择时变量对应的索引值（即时间维度）
    datelist = df_m_shifted_i.index.unique()

    # 提取与择时变量相同维度的因子收益
    Ret_mat = Ret_mat.loc[datelist]

    # 计算因子个数
    num_factor = len(Ret_mat.columns)

    # 设置用于择时的变量
    macro_factor_selected = [
        'TS', 'CS', 'cpi_yoy', 'ppi', 'STD_Spread', 'RET_Spread', 'm1_yoy',
        'Bond_yield_3M'
    ]

    # 构建初始的拟合优度数据框
    R2_mat = pd.DataFrame(index=Ret_mat.columns, columns=['R_square'])

    for label,factor in Ret_mat.items():

        # 提取回归因变量（因子收益）
        factor_ret = factor.reset_index(drop=True)

        # 提取回归自变量（择时因子）
        macro_df = df_m_shifted_i.loc[datelist, macro_factor_selected].reset_index(drop=True)
        
        # 进行回归并提取拟合优度值
        r2 = sm.regression.linear_model.OLS(
            factor_ret.astype(float), macro_df.astype(float)).fit().rsquared

        R2_mat.loc[label, :] = r2

    return R2_mat  #得到的R2是一个以因子名为索引，以'R_square'为列名的数据框
    
# 构建滚动计算拟合优度及拟合优度均值
# 输入参数：df_m_shifted_（为全部测试区间段择时因子数据集）,Ret_mat（为全部时间段的因子收益）,window=24（滚动周期）
def rolling_R2(
        df_m_shifted_:pd.DataFrame, Ret_mat:pd.DataFrame, window:int=24
)->pd.DataFrame:  
    # 提取日期数
    datelist = df_m_shifted_.index.unique() 
    
    # 初始化拟合优度数据框中，以因子名为索引值
    R2_mat_all = pd.DataFrame(
        index=Ret_mat.columns.tolist())  

    for i in range(window - 1, len(df_m_shifted_)):

        df_m_shifted_i = df_m_shifted_.iloc[(i - window + 1):i, :]

        # 计算每期的拟合优度
        R2_mat_i = R_squared(df_m_shifted_i, Ret_mat) 

        # 将计算的第i期数据合并入初始化拟合优度数据框中
        R2_mat_all[datelist[i]] = R2_mat_i  

    return R2_mat_all.T
    
def run_predict_models(Ret_mat: pd.DataFrame,
                       df_m_shifted_: pd.DataFrame,
                       method: str,
                       window: int = 24) -> pd.DataFrame:
    '''
    输入因子收益Ret_mat，择时变量df_m_shifted_，
    滚动窗口window为24（每次以24期的数据进行预测，
    其中前23期作为训练集，最后一期作为测试集）
    method:SVM,Logistic,DecisionTree,RandomForest
    '''
    ##初始化数据
    # 获取需要预测的日期序列
    datelist = df_m_shifted_.index.tolist()[window - 1:]

    # 由于因子收益的时间跨度比择时变量的时间跨度大，为保持预测时间上的一致性，
    # 截取与择时变量相同时间跨度的因子收益
    Ret_mat_ = Ret_mat.loc[df_m_shifted_.index.tolist()]

    # 因子收益大于0的赋值为1，小于0的赋值为-1
    Ret_mat_sign = np.sign(Ret_mat_)

    # 获取待预测的因子个数
    num_factor = len(Ret_mat.columns)

    # 提取用于预测的择时因子
    macro_df = df_m_shifted_[[
        'TS', 'CS', 'cpi_yoy', 'ppi', 'STD_Spread', 'RET_Spread', 'm1_yoy',
        'Bond_yield_3M'
    ]]

    ## 用支持向量机进行预测
    # 初始化因子预测数据框,其中起始预测时间为start_date
    predicted_mat = pd.DataFrame(index=datelist, columns=Ret_mat_.columns)

    for j in range(num_factor):

        # 提取分类模型的预测变量，即第j个因子收益
        factor_sign_i = Ret_mat_sign.iloc[:, j]

        # 初始化单个因子的测试值
        predict = pd.Series(0, index=predicted_mat.index.tolist())

        for i in range(len(predict)):

            # 不进行变量缩减,提取预测日期前推window的择时变量数据
            x_design = macro_df.iloc[i:i + window, :]

            # 对数据进行标准化处理
            x_std = x_design.apply(lambda x: (x - x.mean()) / x.std())

            # 以前23期为训练集
            x_train = x_std.iloc[:-1, :]

            # 以最后一期为测试集
            x_test = x_std.iloc[-1:, :]

            # 提取y集
            y_design_logit = factor_sign_i.iloc[i:i + window - 1]

            # 判断选用哪个预测模型
            if method == 'SVM':
                regr = svm.SVC(kernel='rbf')  # 支持向量机核函数选择rbf

            elif method == 'Logistic':
                regr = linear_model.LogisticRegression()  # 导入逻辑回归模型

            elif method == 'DecisionTree':
                regr = DecisionTreeClassifier(max_depth=3)  # 导入决策树模型

            elif method == 'RandomForest':
                regr = RandomForestClassifier(
                    n_estimators=20, max_depth=3,
                    random_state=0)  # 随机森林最大深度为3，n_estimators=20

            regr.fit(x_train.fillna(0), y_design_logit.astype(float))
            predict.iloc[i] = regr.predict(x_test.fillna(0))

        print('%s,success'%Ret_mat.columns[j])  # 打印测试成功的因子

        predicted_mat.iloc[:, j] = predict  # 将各个因子滚动预测的因子收益存入初始化因子预测数据框中

    return predicted_mat

def weight_timing_threshold(Ret_mat: pd.DataFrame,
                            predict_mat: pd.DataFrame,
                            weight_in: pd.DataFrame,
                            r2: pd.DataFrame,
                            th: float,
                            z: float = 0.1) -> pd.DataFrame:
    '''
    输入参数：Ret_mat（因子收益数据集），
    predict_mat（预测的因子收益方向），
    weight_in（初始权重），
    r2(拟合优度R2)，
    th(阈值),
    z(权重调整系数)
    '''
    predict_mat.dropna(inplace=True)  # 删除预期收益的缺失值

    # 计算过去36个月的因子收益均值
    factor_sign = np.sign(Ret_mat.rolling(min_periods=1, window=36).mean())

    # 初始化新的因子权重
    weight_new = pd.DataFrame(
        0, index=predict_mat.index, columns=weight_in.columns)

    # 提取预期因子收益时间对应的原始因子权重集
    weight_in_chunk = weight_in.loc[predict_mat.index, :]

    for j in range(len(weight_new.index)):
        # 判断预测的因子收益方向是否发生变化，若发生变化则需要调整权重
        iftrue = pd.Series(predict_mat.loc[weight_new.index[j], :] ==
                           factor_sign.loc[weight_new.index[j], :])

        time_weight = iftrue.apply(lambda x: 1 if x == True else z)
        # 调整因子权重
        weight_new.iloc[j, :] = weight_in_chunk.iloc[j, :] * time_weight

        # 根据拟合优度判断是否有变换权重的资格
        aa = r2.loc[weight_new.index[j], :]  # 提取对应日期的过去n期的r2
        for name in weight_new.columns:
            if aa[name] < th:
                weight_new.loc[:, name] = weight_in_chunk.loc[:, name].astype(
                    float)  # 当拟合优度小于阈值时，权重保持不变

    return weight_new
    
#构建投资组合的函数（根据因子权重计算综合因子，再取预期收益排名前50名的股票作为最终的投资组合）
def get_portfolio(weight_new:pd.DataFrame, datas:pd.DataFrame, number:int):
    dates = weight_new.index
    stocks_dic = {}
    for date in dates:
        data = datas.loc[date]
        weight = weight_new.loc[date]
        data['score'] = (data * weight).sum(axis=1)
        stocks = data.sort_values(
            by='score',
            ascending=False).index.tolist()[:number]  #提取综合因子排名前50的股票代码
        stocks_dic[date] = stocks
    stocks_df = pd.DataFrame(stocks_dic).T
    return stocks_df

# 输入因子收益和半衰期
def Ret_mat_emw(Ret_mat:pd.DataFrame,period:int)->pd.DataFrame: 
    
    # 指数加权移动平均
    return Ret_mat.ewm(halflife=period,min_periods=2).mean()
    

# 获取上月末日期
def month_day_pair(context):
    
    """获取字符串格式的本月初与本月底时间对(或上月初与上月底时间对)"""
    today = context.current_dt.date()
    year, month = today.year, today.month

    end = datetime.date(today.year, today.month, 1) - datetime.timedelta(1)
        
    trade = get_trade_days(end_date=end,count=1)[0]
    
    return trade
    
    
'''
=====================================================================================
                        trade
=====================================================================================
'''

def Trade(context):
    
    bar_time = context.current_dt.date()
    end_date = month_day_pair(context)
    
    
        
    if bar_time in g.stocks_df.index:
        
        print('执行交易%s'%bar_time)
        
        target_stocks = g.stocks_df.loc[bar_time].values.tolist()
        
        SellStock(context,target_stocks)
        BuyStock(context,target_stocks)
    
def BuyStock(context,target):
    
    everyStock = context.portfolio.total_value / len(target)
    
    for buy_stock in target:
        
        order_target_value(buy_stock,everyStock)
        
def SellStock(context,target):
    
    for hold_stock in context.portfolio.long_positions:
        if hold_stock not in target:
            order_target(hold_stock,0)
    
