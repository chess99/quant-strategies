# 克隆自聚宽文章：https://www.joinquant.com/post/25313
# 标题：XGBoost模型多因子策略分享
# 作者：cgzol

#从这个版本开始，使用XGB多分类方式训练模型
#20200207运行的是12分类模型
import talib
import pandas as pd
import numpy as np
import math
import jqdata
import re
import time,datetime
from jqdata import *
from jqfactor import neutralize
from prettytable import PrettyTable
from jqdata import finance
from jqfactor import get_factor_values
import warnings
from jqdata import *
from jqlib.technical_analysis import *
from jqfactor import get_factor_values
from jqfactor import winsorize_med
from jqfactor import standardlize
from jqfactor import neutralize
import datetime
from scipy import stats
import statsmodels.api as sm
from statsmodels import regression
from six import StringIO
#导入pca
from sklearn.decomposition import PCA
from sklearn.model_selection import train_test_split
#from sklearn.grid_search import GridSearchCV #原来的代码
from sklearn.model_selection import GridSearchCV
from xgboost import XGBClassifier
from xgboost import Booster
from xgboost import DMatrix
from sklearn import metrics
import seaborn as sns
import warnings
import datetime
from six import BytesIO
import pickle


def initialize(context):
    disable_cache()
    warnings.filterwarnings("ignore")
    set_commission(PerTrade(buy_cost=0.00025, sell_cost=0.001, min_cost=5))
    set_slippage(FixedSlippage(0))
    set_option('use_real_price', True)
    g.index = '399906.XSHE'#中证800指数
    set_benchmark(g.index)
    log.set_level('order', 'info')
    log.set_level('history', 'error')
    g.buy_stock_count = 20
    g.day_count = 0
    g.period = 5
    g.trade_hour = 14
    g.trade_minute = 30
    g.count_days = 100
    g.pre_date =context.previous_date
    g.F_score_limit = 6

def handle_data(context, data):
    g.pre_date =context.previous_date
    hour = context.current_dt.hour
    minute = context.current_dt.minute
    buy_stocks = []
    if (hour == g.trade_hour) and (minute == g.trade_minute):
        if g.day_count % g.period == 0:
            buy_stocks = select_stocks(context,data)
            print('需持有的股票：\n')
            for stock in buy_stocks:
                print(show_stock(stock))
            if len(context.portfolio.positions)>0:
                print('卖出股票：')
                last_prices = history(1, '1m', 'close', security_list=context.portfolio.positions.keys())
                curr_data = get_current_data()
                for stock in context.portfolio.positions.keys():
                    if stock not in buy_stocks and last_prices[stock][-1] < curr_data[stock].high_limit:
                        order_target_value(stock, 0)
                        print('卖出股票：',stock)
            print('买入股票：')
            for stock in buy_stocks:
                position_count = len(context.portfolio.positions)
                if g.buy_stock_count > position_count:
                    value = context.portfolio.cash / (g.buy_stock_count - position_count)
                    if context.portfolio.positions[stock].total_amount == 0:
                        order_target_value(stock, value)
                        print('买入股票：',stock)
            #print get_portfolio_info_text(context,buy_stocks)
        g.day_count += 1
        print('计数日：',g.day_count)
        
def get_all_stocks():
    lst_000905 = get_index_stocks(g.index) # 指数成分股
    return lst_000905
        
def filter_paused_and_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused 
    and not current_data[stock].is_st and 'ST' not in current_data[stock].
    name and '*' not in current_data[stock].name and '退' not in current_data[stock].name]
    
def filter_gem_stock(context, stock_list):
    #过滤创业板股票
    return [stock for stock in stock_list  if stock[0:3] != '300']
    
def filter_inno_stock(security_list) :
    #过滤科创板股票
    return [stock for stock in security_list if stock[0:3] != '688' and stock[0:3] != '787']
    # 返回结果
    

def filter_old_stock(context, stock_list):
    tmpList = []
    for stock in stock_list :
        days_public=(context.current_dt.date() - get_security_info(stock).start_date).days
        # 上市未超过1年
        if days_public > 365 :
            tmpList.append(stock)
    return tmpList

def filter_limit_stock(context, data, stock_list):
    tmpList = []
    curr_data = get_current_data()
    for stock in stock_list:
        # 未涨停，也未跌停
        if curr_data[stock].low_limit < data[stock].close < curr_data[stock].high_limit:
            tmpList.append(stock)
    return tmpList

#去除上市距beginDate不足3个月的股票
def delect_stop(stocks,beginDate,n=30*3):
    stockList=[]
    beginDate = datetime.datetime.strptime(beginDate, "%Y-%m-%d")
    for stock in stocks:
        start_date=get_security_info(stock).start_date
        if start_date<(beginDate-datetime.timedelta(days=n)).date():
            stockList.append(stock)
    return stockList
#获取股票池
def get_stock(stockPool,begin_date):
    if stockPool=='HS300':
        stockList=get_index_stocks('000300.XSHG',begin_date)
    elif stockPool=='ZZ500':
        stockList=get_index_stocks('399905.XSHE',begin_date)
    elif stockPool=='ZZ800':
        stockList=get_index_stocks('399906.XSHE',begin_date)   
    elif stockPool=='CYBZ':
        stockList=get_index_stocks('399006.XSHE',begin_date)
    elif stockPool=='ZXBZ':
        stockList=get_index_stocks('399005.XSHE',begin_date)
    elif stockPool=='A':
        stockList=get_index_stocks('000002.XSHG',begin_date)+get_index_stocks('399107.XSHE',begin_date)
    #剔除ST股
    stockList = filter_paused_and_st_stock(stockList)
    #剔除停牌、新股及退市股票
    #stockList=delect_stop(stockList,begin_date)
    return stockList
    
# 辅助线性回归的函数
def linreg(X,Y,columns=3):
    X=sm.add_constant(array(X))
    Y=array(Y)
    if len(Y)>1:
        results = regression.linear_model.OLS(Y, X).fit()
        return results.params
    else:
        return [float("nan")]*(columns+1)
#取股票对应行业
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

#数据预处理
def data_preprocessing(factor_data,stockList,industry_code,date):
    #去极值
    factor_data=winsorize_med(factor_data, scale=5, inf2nan=False,axis=0)
    #缺失值处理
    factor_data=replace_nan_indu(factor_data,stockList,industry_code,date)
    #中性化处理
    factor_data=neutralize(factor_data, how=['sw_l1', 'market_cap'], date=date, axis=0)
    #标准化处理
    factor_data=standardlize(factor_data,axis=0)
    return factor_data

#获取时间为date的全部因子数据
def get_factor_data(stock,date):
    data=pd.DataFrame(index=stock)
    q = query(valuation,balance,cash_flow,income,indicator).filter(valuation.code.in_(stock))
    df = get_fundamentals(q, date)
    df['market_cap']=df['market_cap']*100000000
    factor_data=get_factor_values(stock,['roe_ttm',
                                         'roa_ttm',
                                         'total_asset_turnover_rate',
                                         'net_operate_cash_flow_ttm',
                                         'net_profit_ttm',
                                         'cash_to_current_liability',
                                         'current_ratio',
                                         'gross_income_ratio',
                                         'non_recurring_gain_loss',
                                         'operating_revenue_ttm',
                                         'net_profit_growth_rate'
                                        ],end_date=date,count=1)
    factor=pd.DataFrame(index=stock)
    for i in factor_data.keys():
        factor[i]=factor_data[i].iloc[0,:]
    df.index = df['code']
    del df['code'],df['id']
    #合并得大表
    df=pd.concat([df,factor],axis=1)
    #净利润(TTM)/总市值
    data['EP']=df['net_profit_ttm']/df['market_cap']
    #净资产/总市值
    data['BP']=1/df['pb_ratio']
    #营业收入(TTM)/总市值
    data['SP']=1/df['ps_ratio']
    #净现金流(TTM)/总市值
    data['NCFP']=1/df['pcf_ratio']
    #经营性现金流(TTM)/总市值
    data['OCFP']=df['net_operate_cash_flow_ttm']/df['market_cap']
    #净利润(TTM)同比增长率/PE_TTM
    data['G/PE']=df['net_profit_growth_rate']/df['pe_ratio']
    #ROE_ttm
    data['roe_ttm']=df['roe_ttm']
    #ROE_YTD
    data['roe_q']=df['roe']
    #ROA_ttm
    data['roa_ttm']=df['roa_ttm']
    #ROA_YTD
    data['roa_q']=df['roa']
    #毛利率TTM
    data['grossprofitmargin_ttm']=df['gross_income_ratio']
    #毛利率YTD
    data['grossprofitmargin_q']=df['gross_profit_margin']

    #扣除非经常性损益后净利润率YTD
    data['profitmargin_q']=df['adjusted_profit']/df['operating_revenue']
    #资产周转率TTM
    data['assetturnover_ttm']=df['total_asset_turnover_rate']
    #资产周转率YTD 营业收入/总资产
    data['assetturnover_q']=df['operating_revenue']/df['total_assets']
    #经营性现金流/净利润TTM
    data['operationcashflowratio_ttm']=df['net_operate_cash_flow_ttm']/df['net_profit_ttm']
    #经营性现金流/净利润YTD
    data['operationcashflowratio_q']=df['net_operate_cash_flow']/df['net_profit']
    #净资产
    df['net_assets']=df['total_assets']-df['total_liability']
    #总资产/净资产
    data['financial_leverage']=df['total_assets']/df['net_assets']
    #非流动负债/净资产
    data['debtequityratio']=df['total_non_current_liability']/df['net_assets']
    #现金比率=(货币资金+有价证券)÷流动负债
    data['cashratio']=df['cash_to_current_liability']
    #流动比率=流动资产/流动负债*100%
    data['currentratio']=df['current_ratio']
    #总市值取对数
    data['ln_capital']=np.log(df['market_cap'])
    #TTM所需时间
    his_date = [pd.to_datetime(date) - datetime.timedelta(90*i) for i in range(0, 4)]
    tmp = pd.DataFrame()
    tmp['code']=stock
    for i in his_date:
        tmp_adjusted_dividend = get_fundamentals(query(indicator.code, indicator.adjusted_profit, \
                                                     cash_flow.dividend_interest_payment).
                                               filter(indicator.code.in_(stock)), date = i)
        tmp=pd.merge(tmp,tmp_adjusted_dividend,how='outer',on='code')

        tmp=tmp.rename(columns={'adjusted_profit':'adjusted_profit'+str(i.month), \
                                'dividend_interest_payment':'dividend_interest_payment'+str(i.month)})
    tmp=tmp.set_index('code')
    tmp_columns=tmp.columns.values.tolist()
    tmp_adjusted=sum(tmp[[i for i in tmp_columns if 'adjusted_profit'in i ]],1)
    tmp_dividend=sum(tmp[[i for i in tmp_columns if 'dividend_interest_payment'in i ]],1)
    #扣除非经常性损益后净利润(TTM)/总市值
    data['EPcut']=tmp_adjusted/df['market_cap']
    #近12个月现金红利(按除息日计)/总市值
    data['DP']=tmp_dividend/df['market_cap']
    #扣除非经常性损益后净利润率TTM
    data['profitmargin_ttm']=tmp_adjusted/df['operating_revenue_ttm']
    #营业收入(YTD)同比增长率
    #_x现在 _y前一年
    his_date = pd.to_datetime(date) - datetime.timedelta(365)
    name=['operating_revenue','net_profit','net_operate_cash_flow','roe']
    temp_data=df[name]
    his_temp_data = get_fundamentals(query(valuation.code, income.operating_revenue,income.net_profit,\
                                            cash_flow.net_operate_cash_flow,indicator.roe).
                                      filter(valuation.code.in_(stock)), date = his_date)
    his_temp_data=his_temp_data.set_index('code')
    #重命名 his_temp_data last_year
    for i in name:
        his_temp_data=his_temp_data.rename(columns={i:i+'last_year'})

    temp_data =pd.concat([temp_data,his_temp_data],axis=1)
    #营业收入(YTD)同比增长率
    data['sales_g_q']=temp_data['operating_revenue']/temp_data['operating_revenuelast_year']-1
    #净利润(YTD)同比增长率
    data['profit_g_q']=temp_data['net_profit']/temp_data['net_profitlast_year']-1
    #经营性现金流(YTD)同比增长率
    data['ocf_g_q']=temp_data['net_operate_cash_flow']/temp_data['net_operate_cash_flowlast_year']-1
    #ROE(YTD)同比增长率
    data['roe_g_q']=temp_data['roe']/temp_data['roelast_year']-1
    #个股60个月收益与上证综指回归的截距项与BETA
    stock_close=get_price(stock, count = 60*20+1, end_date=date, frequency='daily', fields=['close'])['close']
    SZ_close=get_price('000001.XSHG', count = 60*20+1, end_date=date, frequency='daily', fields=['close'])['close']
    stock_pchg=stock_close.pct_change().iloc[1:]
    SZ_pchg=SZ_close.pct_change().iloc[1:]
    beta=[]
    stockalpha=[]
    for i in stock:
        temp_beta, temp_stockalpha = stats.linregress(SZ_pchg, stock_pchg[i])[:2]
        beta.append(temp_beta)
        stockalpha.append(temp_stockalpha)
    #此处alpha beta为list
    data['alpha']=stockalpha
    data['beta']=beta

    #动量
    data['return_1m']=stock_close.iloc[-1]/stock_close.iloc[-20]-1
    data['return_3m']=stock_close.iloc[-1]/stock_close.iloc[-60]-1
    data['return_6m']=stock_close.iloc[-1]/stock_close.iloc[-120]-1
    data['return_12m']=stock_close.iloc[-1]/stock_close.iloc[-240]-1

    #取换手率数据
    data_turnover_ratio=pd.DataFrame()
    data_turnover_ratio['code']=stock
    trade_days=list(get_trade_days(end_date=date, count=240*2))
    for i in trade_days:
        q = query(valuation.code,valuation.turnover_ratio).filter(valuation.code.in_(stock))
        temp = get_fundamentals(q, i)
        data_turnover_ratio=pd.merge(data_turnover_ratio, temp,how='left',on='code')
        data_turnover_ratio=data_turnover_ratio.rename(columns={'turnover_ratio':i})
    data_turnover_ratio=data_turnover_ratio.set_index('code').T   

    #个股个股最近N个月内用每日换手率乘以每日收益率求算术平均值
    data['wgt_return_1m']=mean(stock_pchg.iloc[-20:]*data_turnover_ratio.iloc[-20:])
    data['wgt_return_3m']=mean(stock_pchg.iloc[-60:]*data_turnover_ratio.iloc[-60:])
    data['wgt_return_6m']=mean(stock_pchg.iloc[-120:]*data_turnover_ratio.iloc[-120:])
    data['wgt_return_12m']=mean(stock_pchg.iloc[-240:]*data_turnover_ratio.iloc[-240:])
    #个股个股最近N个月内用每日换手率乘以函数exp(-x_i/N/4)再乘以每日收益率求算术平均值
    temp_data=pd.DataFrame(index=data_turnover_ratio[-240:].index,columns=stock)
    temp=[]
    for i in range(240):
        if i/20<1:
            temp.append(exp(-i/1/4))
        elif i/20<3:
            temp.append(exp(-i/3/4))
        elif i/20<6:
            temp.append(exp(-i/6/4))
        elif i/20<12:
            temp.append(exp(-i/12/4))  
    temp.reverse()
    for i in stock:
        temp_data[i]=temp
    data['exp_wgt_return_1m']=mean(stock_pchg.iloc[-20:]*temp_data.iloc[-20:]*data_turnover_ratio.iloc[-20:])
    data['exp_wgt_return_3m']=mean(stock_pchg.iloc[-60:]*temp_data.iloc[-60:]*data_turnover_ratio.iloc[-60:])
    data['exp_wgt_return_6m']=mean(stock_pchg.iloc[-120:]*temp_data.iloc[-120:]*data_turnover_ratio.iloc[-120:])
    data['exp_wgt_return_12m']=mean(stock_pchg.iloc[-240:]*temp_data.iloc[-240:]*data_turnover_ratio.iloc[-240:])

    #特异波动率
    #获取FF三因子残差数据
    LoS=len(stock)
    # S=df.sort('market_cap')[:LoS/3].index #原来代码
    # B=df.sort('market_cap')[LoS-LoS/3:].index #原来代码
    S=df.sort_values(by = 'market_cap')[:int(LoS/3)].index 
    B=df.sort_values(by = 'market_cap')[int(LoS-LoS/3):].index
    
    df['BTM']=df['total_owner_equities']/df['market_cap']
    L=df.sort_values(by = 'BTM')[:int(LoS/3)].index
    H=df.sort_values(by = 'BTM')[int(LoS-LoS/3):].index
    df_temp=stock_pchg.iloc[-240:]
    #求因子的值
    SMB=sum(df_temp[S].T)/len(S)-sum(df_temp[B].T)/len(B)
    HMI=sum(df_temp[H].T)/len(H)-sum(df_temp[L].T)/len(L)
    #用沪深300作为大盘基准
    dp=get_price('000300.XSHG',count=12*20+1,end_date=date,frequency='daily', fields=['close'])['close']
    RM=dp.pct_change().iloc[1:]-0.04/252
    #将因子们计算好并且放好
    X=pd.DataFrame({"RM":RM,"SMB":SMB,"HMI":HMI})
    resd=pd.DataFrame()
    for i in stock:
        temp=df_temp[i]-0.04/252
        t_r=linreg(X,temp)
        resd[i]=list(temp-(t_r[0]+X.iloc[:,0]*t_r[1]+X.iloc[:,1]*t_r[2]+X.iloc[:,2]*t_r[3]))
    data['std_FF3factor_1m']=resd[-1*20:].std()
    data['std_FF3factor_3m']=resd[-3*20:].std()
    data['std_FF3factor_6m']=resd[-6*20:].std()
    data['std_FF3factor_12m']=resd[-12*20:].std()

    #波动率
    data['std_1m']=stock_pchg.iloc[-20:].std()
    data['std_3m']=stock_pchg.iloc[-60:].std()
    data['std_6m']=stock_pchg.iloc[-120:].std()
    data['std_12m']=stock_pchg.iloc[-240:].std()

    #股价
    data['ln_price']=np.log(stock_close.iloc[-1])

    #换手率
    data['turn_1m']=mean(data_turnover_ratio.iloc[-20:])
    data['turn_3m']=mean(data_turnover_ratio.iloc[-60:])
    data['turn_6m']=mean(data_turnover_ratio.iloc[-120:])
    data['turn_12m']=mean(data_turnover_ratio.iloc[-240:])

    data['bias_turn_1m']=mean(data_turnover_ratio.iloc[-20:])/mean(data_turnover_ratio)-1
    data['bias_turn_3m']=mean(data_turnover_ratio.iloc[-60:])/mean(data_turnover_ratio)-1
    data['bias_turn_6m']=mean(data_turnover_ratio.iloc[-120:])/mean(data_turnover_ratio)-1
    data['bias_turn_12m']=mean(data_turnover_ratio.iloc[-240:])/mean(data_turnover_ratio)-1
    #技术指标
    data['PSY']=pd.Series(PSY(stock, date, timeperiod=20))
    data['RSI']=pd.Series(RSI(stock, date, N1=20))
    data['BIAS']=pd.Series(BIAS(stock,date, N1=20)[0])
    dif,dea,macd=MACD(stock, date, SHORT = 10, LONG = 30, MID = 15)
    data['DIF']=pd.Series(dif)
    data['DEA']=pd.Series(dea)
    data['MACD']=pd.Series(macd)
    return data


def select_stocks(context,data):
    #clf = pickle.load(BytesIO(read_file('xgb_factors_model_ZZ800_D.model')))
    #file = read_file('xgb_factors_model_ZZ800_D.model')
    #clf = Booster.load_model(fname = BytesIO(read_file('xgb_factors_model_ZZ800_D.model')))
    with open('temp','wb') as f:
        f.write(read_file('xgb_factors.model'))  #储存一个临时文件,进程结束后清理
    clf = Booster(model_file='temp')
    #clf = Booster.load_model(fname = 'temp')
    industry_old_code = ['801010','801020','801030','801040','801050','801080','801110','801120','801130','801140','801150',\
                    '801160','801170','801180','801200','801210','801230']
    industry_new_code = ['801010','801020','801030','801040','801050','801080','801110','801120','801130','801140','801150',\
                    '801160','801170','801180','801200','801210','801230','801710','801720','801730','801740','801750',\
                   '801760','801770','801780','801790','801880','801890']
    starttime = datetime.datetime.now()
    date  = context.previous_date
    #获取行业因子数据
    print ('获取数据的日期：',date)
    '''
    if datetime.datetime.strptime(date,"%Y-%m-%d").date()<datetime.date(2014,2,21):
        industry_code=industry_old_code
    else:
    '''
    industry_code=industry_new_code
    stockList=get_stock('ZZ800',date)
    factor_origl_data = get_factor_data(stockList,date)
    factor_solve_data = data_preprocessing(factor_origl_data,stockList,industry_code,date)
    endtime = datetime.datetime.now()
    print ('取数运行时长：',int((endtime - starttime).seconds/60),'分钟')
    test_feature_or=factor_solve_data.copy()
    test_feature=np.array(test_feature_or)
    # 模型预测
    test_predict=clf.predict(DMatrix(test_feature_or))
    test_sample_predict=pd.DataFrame(data = test_predict,index = test_feature_or.index,columns =  ['XGB_predict_0','XGB_predict_1','XGB_predict_2','XGB_predict_3','XGB_predict_4','XGB_predict_5','XGB_predict_6','XGB_predict_7','XGB_predict_8','XGB_predict_9','XGB_predict_10','XGB_predict_11'])
    #test_sample_predict['XGB_predict_0_and_1'] = test_sample_predict['XGB_predict_0'] + test_sample_predict['XGB_predict_1']
    test_sample_predict = test_sample_predict.sort_values(by='XGB_predict_0',ascending = False)
    stock_list = test_sample_predict.index.values.tolist()
    stock_list = stock_list[:g.buy_stock_count]  
    return stock_list



# 策略看10天涨幅
def get_growth_rate(security, n = 10):
    lc = get_close_price(security, n)
    #c = data[security].close
    c = get_close_price(security, 1, '1m')

    if not isnan(lc) and not isnan(c) and lc != 0:
        return (c - lc) / lc
    else:
        log.error("数据非法, security: %s, %d日收盘价: %f, 当前价: %f" %(security, n, lc, c))
        return 0
        
# 获取前n个单位时间当时的收盘价
def get_close_price(security, n, unit='1d'):
    return attribute_history(security, n, unit, ('close'), True)['close'][0]

def show_stock(stock):
    '''
    获取股票代码的显示信息    
    :param stock: 股票代码，例如: '603822.SH'
    :return: str，例如：'603822 嘉澳环保'
    '''
    return u"%s %s" % (stock[:6], get_security_info(stock).display_name)
