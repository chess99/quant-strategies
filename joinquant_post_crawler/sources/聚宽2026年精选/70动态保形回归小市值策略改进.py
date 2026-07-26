# 克隆自聚宽文章：https://www.joinquant.com/post/48996
# 标题：动态保形回归小市值策略改进
# 作者：yanzigao

# 克隆自聚宽文章：https://www.joinquant.com/post/43738
# 标题：分享适合研究多因子和随机森林的框架
# 作者：TheFun

#时间间隔方面5日与20日间隔有较好表现和回撤
#价格训练的判断标准return小于0表现更好
#导入函数库
from jqlib.technical_analysis import *
from jqdata import *
from jqfactor import *
import pandas as pd
import numpy as np
import math
from sklearn.svm import SVR  
from sklearn.model_selection import GridSearchCV  
from sklearn.model_selection import learning_curve
from sklearn.linear_model import LinearRegression
import jqdata
import datetime
from datetime import time
from sklearn.tree import DecisionTreeRegressor
from sklearn.tree import DecisionTreeClassifier
from sklearn.preprocessing import StandardScaler 
from sklearn.model_selection import train_test_split 
from sklearn.preprocessing import StandardScaler 
import sklearn.base
from sklearn.mixture import GaussianMixture  
import xgboost
from xgboost import Booster, XGBRegressor

def initialize(context):
    set_params()# #设置策略参数
    set_backtest()#设置回测条件
    set_variables()  
    set_option('avoid_future_data', True)#防止未来函数
    # run_daily(trade, 'every_bar')# 开盘时运行
    run_daily(close_account, '14:50')
    g.pass_april = True# 是否一、四月空仓
    g.no_trading_today_signal = False
    g.filter_bons = True #国九条：红利条件
    g.stock_pro =0.1   # 股票池内股票占删选后总股票比例
    g.stoploss_market = 0.1 # 止损线
    g.stopprofit_market = 0.35 #止盈线
    g.list_to_buy=[] #买入列表初始化
    
def set_params():
    # g.refresh_rate = 10
    g.tc=20 # 调仓频率，这里为5天一次
    g.tc_stoploss = 1 #止损检测，每天一次
    g.stocknum_1 = 5#突破行情持股数量
    g.stocknum_2 = 3#反转行情持股数量
    g.ret=-0.05
    
def set_backtest():
    set_benchmark('000300.XSHG')#设置对比基本，这里为沪深300
    set_option('use_real_price', True)#使用真实价格成交
    log.set_level('order', 'error')
    
def set_variables():
    g.days = 0 # 记录回测运行的天数
    g.if_trade = False 
    g.if_trade_stoploss = False

# 开盘之前需要做的事：
def before_trading_start(context):
    g.no_trading_today_signal = today_is_between(context)
    #print(g.no_trading_today_signal)
    
    
    
    final_list = []
   # MKT_index = '399101.XSHE'#沪深300:'000300.XSHG'
   # stock_list = get_index_stocks(MKT_index)

    yesterday = context.previous_date
    today = context.current_dt
    stock_list = get_all_securities('stock',yesterday).index.tolist()
    # 设置可行股票池
    stock_list = stock_list
    #国九条：财务造假退市指标：==> 【C罗：按审计无保留意见过滤】
    stock_list = filter_stocks_by_auditor_opinion_jqz(context, stock_list)
    #国九条：利润总额、净利润、扣非净利润三者孰低为负值，且营业收入低于 3 亿元 退市
    stock_list = filter_stocks_by_revenue_and_profit(context, stock_list)
    #国九条：最近三个会计年度累计现金分红总额低于年均净利润的30%，且累计分红金额低于5000万元的，将被实施ST
    stock_list = filter_st_stock(stock_list)
    stock_list = filter_kcb_stock(context, stock_list)
    stock_list = filter_new_stock(context, stock_list)
    stock_list = filter_paused_stock(stock_list)
    
    g.feasible_stocks = list(stock_list)
    
    set_slip_fee(context) 
    if g.days%g.tc==0:
        g.if_trade=True                          # 每g.tc天，调仓一次
    if g.days%g.tc_stoploss == 0:
        g.if_trade_stoploss = True
        
        set_slip_fee(context)                    # 设置手续费与手续费
    if g.no_trading_today_signal == True :         #在空仓月份重置天数计数
        g.days = -1
        
    g.days+=1
    #print(g.days)
#过滤函数
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]
    
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list
            if not current_data[stock].is_st
            and 'ST' not in current_data[stock].name
            and '*' not in current_data[stock].name
            and '退' not in current_data[stock].name]

def filter_limitup_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] < current_data[stock].high_limit]

def filter_limitdown_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] > current_data[stock].low_limit]

def filter_kcb_stock(context, stock_list):
    return [stock for stock in stock_list  if stock[0:3] != '688']

def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=250)]

# 2.1 筛选审计意见：蒋老师提供
def filter_stocks_by_auditor_opinion_jqz(context, stock_list):
    #print(f'按审计无保留意见筛选前：{len(stock_list)}')
    # type:(context,list)-> list
    #剔除近三年内有不合格(opinion_type_id >2 且不是 6)审计意见的股票
    start_date = datetime.date(context.current_dt.year - 3, 1,1).strftime('%Y-%m-%d')
    end_date = context.previous_date.strftime('%Y-%m-%d')
    q = query(finance.STK_AUDIT_OPINION).filter(finance.STK_AUDIT_OPINION.code.in_(stock_list), 
        finance.STK_AUDIT_OPINION.report_type == 0, #0:财务报表审计报告
        finance.STK_AUDIT_OPINION.opinion_type_id > 2,  #1:无保留,2:无保留带解释性说明
        finance.STK_AUDIT_OPINION.opinion_type_id != 6,   #6:未经审计，季报
        finance.STK_AUDIT_OPINION.end_date >= start_date,
        finance.STK_AUDIT_OPINION.pub_date <= end_date)
    df = finance.run_query(q)
    bad_companies = df['code'].unique().tolist()
    #print (f'剔除：审计有保留意见的公司：{bad_companies}')
    keep_list = [s for s in stock_list if s not in bad_companies ]
    #print(f'按审计无保留意意见筛选后：{len(keep_list)}')
    return keep_list

#国九条：财务造假退市指标：==> 【C罗：按审计无保留意见过滤】
def filter_stocks_by_revenue_and_profit(context, stock_list):

    #计算分红的三年起止时间
    time1 = context.previous_date
    time0 = time1 - datetime.timedelta(days=365*3) #三年
    #计算年报的去年
    if time1.month>=5:#5月后取去年
        last_year=str(time1.year-1)
    else:   #5月前取前年
        last_year=str(time1.year-2)

    #print(f'按收入和盈利筛选前：{len(stock_list)}')
    #2：主板亏损公司营业收入退市标准，组合指标修改为利润总额、净利润、扣非净利润三者孰低为负值，且营业收入低于 3 亿元。
    #get_history_fundamentals(security, fields, watch_date=None, stat_date=None, count=1, interval='1q', stat_by_year=False)
    list_len = len(stock_list)
    interval = 1000 
    multiple_n = list_len // interval + 1
    start_i = 0
    stk_df = pd.DataFrame()
    for mul in range(multiple_n):
        start_i = mul * interval
        end_i = start_i + interval
        #print(f'{start_i} - {end_i}')
        df = get_history_fundamentals( stock_list[start_i:end_i], fields=[income.operating_revenue, income.total_profit, income.net_profit ], 
            watch_date=context.current_dt, count=1, interval='1y', stat_by_year=True )
        #扣非净利润找不到
        if len(stk_df) == 0:
            stk_df = df
        else:
            stk_df = pd.concat([stk_df,df])
    df = stk_df[ (stk_df["operating_revenue"] < 3e8) & ((stk_df["total_profit"] < 0) | (stk_df["net_profit"] < 0))]
    bad_companies = list(df["code"]) 
    #print (f'剔除：营收太小 且 净利润为负的公司：{bad_companies}')
    
    selected_columns = ['code', 'operating_revenue', 'total_profit','net_profit']
    #print (df[selected_columns])

    # 同时满足才剔除
    keep_list = [s for s in stock_list if s not in bad_companies ]

    #print(f'按利润总额、净利润最低为负值，且 营业收入低于3亿元 筛选后：{len(keep_list)}')
    return keep_list
    
#红利筛选
def bons_filter(context, stock_list):
    time1 = context.previous_date
    time2= time1 - datetime.timedelta(days=365)
    time3 = time1 - datetime.timedelta(days=365*3)
    #去年未分配利润大于0
    q = query(
        finance.STK_BALANCE_SHEET.code, 
        finance.STK_BALANCE_SHEET.pub_date, 
        finance.STK_BALANCE_SHEET.retained_profit, 
    ).filter(
        finance.STK_BALANCE_SHEET.pub_date >= time2,
        finance.STK_BALANCE_SHEET.pub_date <= time1,
        finance.STK_BALANCE_SHEET.retained_profit>0,
        finance.STK_BALANCE_SHEET.code.in_(stock_list))
    df = finance.run_query(q)
    df = df.set_index('code')
    df = df.groupby('code').mean()
    check_list= list(df.index)

    #获取分红数据
    q = query(
        finance.STK_XR_XD.code, 
        finance.STK_XR_XD.a_registration_date, 
        finance.STK_XR_XD.bonus_amount_rmb
    ).filter(
        finance.STK_XR_XD.a_registration_date >= time3,
        finance.STK_XR_XD.a_registration_date <= time1,
        finance.STK_XR_XD.code.in_(check_list))
    bons_df = finance.run_query(q)
    bons_df = bons_df.fillna(0)
    bons_df = bons_df.set_index('code')
    bons_df = bons_df.groupby('code').sum()
    bons_list=list(bons_df.index)
    #获取过去三年平均净利润
    if time1.month>=5:#5月后取去年
        start_year=str(time1.year-1)
    else:   #5月前取前年
        start_year=str(time1.year-2)
    #获取3年净利润数据
    np=get_history_fundamentals(bons_list, fields=[income.net_profit], watch_date=context.current_dt, count=3, interval='1y', stat_by_year=True)
    np = np.set_index('code')
    np = np.groupby('code').mean()
    #获取市值相关数据
    q = query(valuation.code,valuation.market_cap).filter(valuation.code.in_(bons_list))
    cap = get_fundamentals(q, date=time1)
    cap = cap.set_index('code')
    #筛选过去三年累计分红大于平均净利润的30%或累计分红>5000万
    DR = pd.concat([bons_df,np,cap], axis=1, sort=False)
    DR = DR[((DR['bonus_amount_rmb']*10000)>(DR['net_profit']*0.3)) | (DR['bonus_amount_rmb']>5000)]
    final_list = list(DR.index)
    return final_list    
#4
#4-1 判断今天是否为四月
def today_is_between(context):
    today = context.current_dt.strftime('%m-%d')
    if g.pass_april is True:
        if (('04-07' <= today) and (today <= '05-09')
        or('01-07' <= today) and (today <= '02-09')):
            return True
        else:
           return False
    else:
        return False
# 设置可行股票池：过滤掉当日停牌的股票
# 输入：initial_stocks为list类型,表示初始股票池； context（见API）
# 输出：unsuspened_stocks为list类型，表示当日未停牌的股票池，即：可行股票池
def set_feasible_stocks(initial_stocks,context):
    # 判断初始股票池的股票是否停牌，返回list
    paused_info = []
    current_data = get_current_data()
    for i in initial_stocks:
        paused_info.append(current_data[i].paused)
    df_paused_info = pd.DataFrame({'paused_info':paused_info},index = initial_stocks)
    stock_list =list(df_paused_info.index[df_paused_info.paused_info == False])
    return stock_list
# 根据不同的时间段设置滑点与手续费
# 输入：context（见API）
# 输出：none
def set_slip_fee(context):
    # 将滑点设置为0
    set_slippage(FixedSlippage(0.02)) 
    # 根据不同的时间段设置手续费
    dt=context.current_dt
    if dt>datetime.datetime(2013,1, 1):
        set_commission(PerTrade(buy_cost=0.0003, sell_cost=0.0013, min_cost=5)) 
        
    elif dt>datetime.datetime(2011,1, 1):
        set_commission(PerTrade(buy_cost=0.001, sell_cost=0.002, min_cost=5))
            
    elif dt>datetime.datetime(2009,1, 1):
        set_commission(PerTrade(buy_cost=0.002, sell_cost=0.003, min_cost=5))
    else:
        set_commission(PerTrade(buy_cost=0.003, sell_cost=0.004, min_cost=5))

    
# 每天回测时做的事情
def handle_data(context,data):
        
        
    if g.if_trade == True:
        # 待买入的g.num_stocks支股票，list类型
        g.list_to_buy = stocks_to_buy(context)
        # 待卖出的股票，list类型
        list_to_sell = stocks_to_sell(context, g.list_to_buy)
        if g.no_trading_today_signal == False:
            # 卖出操作
            sell_operation(list_to_sell)
            # 买入操作
            buy_operation(context, g.list_to_buy)
            
    if (g.if_trade_stoploss == True) and (len(context.portfolio.positions) > 0):  
        # 待卖出的股票，list类型  
        list_to_sell = stocks_to_sell(context, g.list_to_buy)  
        if g.no_trading_today_signal == False:  
            # 卖出操作  
            sell_operation(list_to_sell)
            
            
            
    g.if_trade = False
    g.if_trade_stoploss == False


#准备股票池
def get_rff(context,stock_list):
    
    #过滤红利
    # 过滤红利股  
    if g.filter_bons:  
        before_bons_filter = len(stock_list)  
        stock_list = bons_filter(context, stock_list)
        removed_stocks_bons = before_bons_filter - len(stock_list)  
        log.info('去除掉了存在红利问题的股票{}只'.format(removed_stocks_bons))  
    else:  
        stock_list = stock_list['code'].tolist()  # 如果没有过滤红利股，则直接使用全部股票代码  
    
    #决定选股数量
    final_stock_count = len(stock_list)  
    g.stock_num = round(final_stock_count*g.stock_pro)
    print(f"最终选择的股票池持股的数量为: {g.stock_num}")
    
    
   #创建query对象，指定获取股票的代码、市值、净运营资本
    #净债务、产权比率、股东权益比率、营收增长率、换手率、
    #市盈率（PE）、市净率（PB）、市销率（PS）、总资产收益率因子
    q = query(valuation.code, #code
        valuation.circulating_market_cap,#流通市值
        valuation.market_cap,   #市值
        indicator.inc_net_profit_year_on_year,#销售毛利率
        balance.total_current_assets- balance.total_current_liability,  #净营运资本
        balance.total_liability- balance.total_assets,   #净债务
        balance.total_liability/balance.equities_parent_company_owners,  #产权比率
        indicator.gross_profit_margin, #净利润同比增长率
        (balance.total_assets-balance.total_current_assets)/balance.total_assets, #非流动资产比率
        balance.equities_parent_company_owners/balance.total_assets,     #股东权益比率
        income.total_profit,#利润总额
        indicator.inc_total_revenue_year_on_year,#营收增长率
        valuation.turnover_ratio,  #换手率
        valuation.pe_ratio, #PE
        valuation.pb_ratio, #PB
        valuation.ps_ratio, #PS
        indicator.roa,   #总资产净利率
        ).filter(valuation.code.in_(stock_list)
            ).order_by(valuation.market_cap.asc()).limit(g.stock_num)
    df = get_fundamentals(q)
    dfindex = list(df.code.values)
    df.columns = ['code','流通市值','市值','销售毛利率','净营运资本','净债务','产权比率',
                    '净利润同比增长率','非流动资产比率','股东权益比率',
                    '利润总额','营收增长率','换手率','PE','PB','PS','总资产净利率'  
                   ] #因子，可修改
    del df['code']
    
    
    
    start= context.current_dt
    delta20= datetime.timedelta(days=20)
    delta1= datetime.timedelta(days=1)
    today=start-delta1
    preday=start-delta20
    df['成交金额'] = list(AMO(dfindex,today)[0].values())
    df['随机指标'] = list(KDJ(dfindex,today)[0].values())
    df['情绪指标'] = list(BRAR(dfindex,today)[0].values())
    df['动量线']=list(MTM(dfindex, today, timeperiod=10, unit = '1d', include_now = True).values())
    df['成交量']=list(VOL(dfindex, today, M1=10 ,unit = '1d', include_now = True)[0].values())
    df['累计能量线']=list(OBV(dfindex,check_date=today, timeperiod=10).values())
    df['平均差']=list(DMA(dfindex, today, N1 = 10, unit = '1d', include_now = True)[0].values())
    df['指数移动平均']=list(EMA(dfindex, today, timeperiod=10, unit = '1d', include_now = True).values())
    df['移动平均']=list(MA(dfindex, today, timeperiod=10, unit = '1d', include_now = True).values())
    df['乖离率']=list(BIAS(dfindex,today, N1=10, unit = '1d', include_now = True)[0].values())
    
    df=df.apply(lambda x : (x-np.min(x))/(np.max(x)-np.min(x)))   #归一化
    # print("归一化后的数据：")  
    # print(df)
    
    df['close1']=list(get_price(dfindex, end_date=today,count =1, fq='pre',panel=False)['close'])
    df['close2']=list(get_price(dfindex,end_date=preday,count=1,fq='pre',panel=False)['close'])
    df['return']=df['close1']/df['close2']-1
    df['signal']=np.where(df['return']<0,0,1)
    df['code'] = dfindex
    
    df.set_index('code', inplace=True)  # 将 'code' 设置为索引 
    #print(df)
    # 去除离群点  
    def remove_outliers(df, columns, threshold=1.5):  
        Q1 = df[columns].quantile(0.25)  
        Q3 = df[columns].quantile(0.75)  
        IQR = Q3 - Q1  
        lower_bound = Q1 - threshold * IQR  
        upper_bound = Q3 + threshold * IQR  
        outlier_mask = (df[columns] < lower_bound) | (df[columns] > upper_bound)  
        df = df.loc[~outlier_mask.any(axis=1)]  
        
        return df  

    ##筛选因子指标
    x1=df[['市值','销售毛利率','净营运资本','净债务','产权比率',
                '净利润同比增长率','非流动资产比率','股东权益比率',
                '利润总额','营收增长率','换手率','PE','PB','PS','总资产净利率',
                ]]  #因子指标,可以修改
    y1=df[['signal']]
    # 在删除含NA的行之前，先删除NA比例超过5%的列  
    na_columns = x1.columns[x1.isnull().mean() > 0.05]  # 找出NA比例超过5%的列  
    print("以下因子指标中NA的比例超过5%，将被删除：")  
    print(na_columns)  
    # 删除这些列  
    x1 = x1.drop(columns=na_columns)  
    # 删除含NA的行  
    # 找出x1和y1中同时含有NaN值的行索引  
    nan_rows1 = x1[x1.isnull().any(axis=1)].index.union(y1[y1.isnull().any(axis=1)].index)  
      
    # 使用这些索引来同时删除x1和y1中的对应行  
    x1 = x1.drop(nan_rows1)  
    y1 = y1.drop(nan_rows1)  
  
    #tree=DecisionTreeClassifier()     #决策树分类器
    #tree.fit(x,y)
    #model_cs=pd.DataFrame({'feature':list(x.columns),'importance':tree.feature_importances_}).sort_values('importance',ascending=False)
    rff1=XGBRegressor(n_estimators=10, gamma=0.8, learning_rate=0.1, max_depth=3, random_state=42)
    rff1.fit(x1,y1)
    model_cs1=pd.DataFrame({'feature1':list(x1.columns),'importance1':rff1.feature_importances_}).sort_values('importance1',ascending=False)
    xq1=model_cs1['feature1'][:5]     #取重要性前5的指标
    print('本次选出的因子指标为：\n%s'%xq1)
    
    ##筛选技术指标
    x2=df[['成交金额','随机指标','情绪指标','动量线','成交量','累计能量线',
                '平均差','指数移动平均','移动平均','乖离率'
                ]]  #技术指标,可以修改
    y2=df[['signal']]
    # 在删除含NA的行之前，先删除NA比例超过5%的列  
    na_columns = x2.columns[x2.isnull().mean() > 0.05]  # 找出NA比例超过5%的列  
    print("以下技术指标中NA的比例超过5%，将被删除：")  
    print(na_columns)  
    # 删除这些列  
    x2 = x2.drop(columns=na_columns)  
    # 删除含NA的行  
    nan_rows2 = x2[x2.isnull().any(axis=1)].index.union(y2[y2.isnull().any(axis=1)].index)  
      
    # 使用这些索引来同时删除x1和y1中的对应行  
    x2 = x2.drop(nan_rows2)  
    y2 = y2.drop(nan_rows2)  
    rff2 = XGBRegressor(n_estimators=9, gamma=0.8, learning_rate=0.1, max_depth=3, random_state=42)
    rff2.fit(x2,y2)
    model_cs2=pd.DataFrame({'feature2':list(x2.columns),'importance2':rff2.feature_importances_}).sort_values('importance2',ascending=False)
    xq2=model_cs2['feature2'][:5]     #取重要性前三的指标
    print('本次选出的技术指标为：\n%s'%xq2)
    
    
    ##对筛选数据混合再次筛选
    x3=df[pd.concat([xq1,xq2],axis=0)]
    y3=df[['signal']]
    # 删除含NA的行  
    nan_rows3 = x3[x3.isnull().any(axis=1)].index.union(y3[y3.isnull().any(axis=1)].index)  
      
    # 使用这些索引来同时删除x1和y1中的对应行  
    x3 = x3.drop(nan_rows3)  
    y3 = y3.drop(nan_rows3)  
    rff3 = XGBRegressor(n_estimators=10, gamma=0.8, learning_rate=0.1, max_depth=3, random_state=42)
    rff3.fit(x3,y3)
    model_cs3=pd.DataFrame({'feature3':list(x3.columns),'importance3':rff3.feature_importances_}).sort_values('importance3',ascending=False)
    xq3=model_cs3['feature3'][:4]     #取重要性前三的指标
    print('最终选出的总指标为：\n%s'%xq3)
    # 选择重要性前三的指标对应的数据  
    selected_factors = xq3.tolist()  
    # 在最终选择重要性指标后，将索引'code'添加到DataFrame中作为一列  
    df = df.reset_index()  
    df = df.rename(columns={'index': 'code'})  # 将'index'列重命名为'code'  
      
      
    selected_columns = selected_factors + ['code', '流通市值']  # 确保'code'列被包含  
    df = df[selected_columns]  
    
    
    
    #print(df)  
      
    #聚类+conformal  
    # 定义函数来选择最佳簇数量  
    def select_best_gmm_clusters(X, min_clusters=1, max_clusters=10):  
        bics = []  
        for n_components in range(min_clusters, max_clusters + 1):  
            gmm = GaussianMixture(n_components=n_components, covariance_type='full').fit(X)  
            bics.append(gmm.bic(X))  
          
        # 选择BIC最小的模型，即簇数量  
        best_n_components = np.argmin(bics) + min_clusters  
        print(f'Best number of clusters: {best_n_components}')  
          
        # 使用最佳簇数量重新拟合模型  
        gmm_best = GaussianMixture(n_components=best_n_components, covariance_type='full').fit(X)  
        return gmm_best  
    
    # 因子变量名  
    factor_variable = selected_factors  
    target_variable = '流通市值'  
    
    # 对因子变量和目标变量应用去除离群点函数  
    columns_to_check = factor_variable + [target_variable]  
    df = remove_outliers(df, columns_to_check)  
    
    
    # 删除含NA的行  
    df.dropna(inplace=True)  
    
    # 定义特征X和目标y  
    X = df[factor_variable].values  
    Y = df[target_variable].values  
    
    # 选择最佳簇数量的高斯混合模型   
    gmm_best = select_best_gmm_clusters(X)  
      
    # 获取聚类标签  
    cluster_labels = gmm_best.predict(X)  
      
    # 找到最大的聚类（即包含最多点的聚类，不包括噪声点）  
    cluster_sizes = pd.Series(cluster_labels).value_counts()  
    max_cluster_size = cluster_sizes.idxmax()  
    print("\n最大的聚类标签:", max_cluster_size)  
    
    # 输出最大聚类的大小（样本个数）  
    max_cluster_size_count = cluster_sizes[max_cluster_size]  
    print("最大聚类的大小（样本个数）:", max_cluster_size_count)  
    
    # 为最大类创建DataFrame，不包括噪声点  
    max_cluster_df = df[cluster_labels != -1]  # 移除噪声点  
    max_cluster_df = max_cluster_df[cluster_labels == max_cluster_size]  # 仅选择最大聚类  
 
    # 输出最大聚类的前5行以查看内容  
    print("\n最大聚类的前5行:")  
    print(max_cluster_df.head())  
    
      
    # 将数据集平分为三部分
    # 打乱 DataFrame 的行（这会改变索引，但会保留数据和索引的对应关系）  
    max_cluster_df = max_cluster_df.sample(frac=1, random_state=42).reset_index(drop=True) 
    
    # 计算拆分点  
    fractions = [len(max_cluster_df) // 3] * 2 + [len(max_cluster_df) - 2 * (len(max_cluster_df) // 3)]  
    indices = np.cumsum(fractions).tolist()  # 转换为列表以便索引  
    
    # 使用 iloc 和计算好的索引来拆分 DataFrame  
    a = max_cluster_df.iloc[:indices[0]]  
    b = max_cluster_df.iloc[indices[0]:indices[1]]  
    c = max_cluster_df.iloc[indices[1]:]  
    # 初始化存储预测结果的列表  
    predictions_all = []  
    predictions_all_2 = []  
    # 循环三次，分别使用不同的数据集作为校准集、训练集和测试集  
    for i, (cal_data, train_data,test_data) in enumerate([(a, b, c), (c, a, b), (b, c, a)]):  
        
        X_cal = cal_data[factor_variable].values  
        Y_cal = cal_data[target_variable].values  
        X_train = train_data[factor_variable].values  
        Y_train = train_data[target_variable].values  
        X_test = test_data[factor_variable].values  
        Y_test = test_data[target_variable].values  
        
        
        # 获取测试集的索引和对应的code  
        test_indices = np.arange(len(X_test))  
        test_codes = test_data.iloc[test_indices]['code'].tolist()  
      
        # 建立模型和保形回归器  
        model = XGBRegressor(n_estimators=12, random_state=42)  
        nc = NcFactory.create_nc(model)  
        icp = IcpRegressor(nc)  
      
        # 拟合和校准模型  
        # print(X_train)
        # print(Y_train)
        icp.fit(X_train, Y_train)  
        icp.calibrate(X_cal, Y_cal)  
      
        # 生成预测及预测区间  
        predictions = icp.predict(X_test, significance=0.05)  
        Y_lower = predictions[:, 0]  
        Y_upper = predictions[:, 1]  
        Y_pred = (Y_lower + Y_upper) / 2  
        Y_width = Y_upper - Y_lower  
      
        # 将预测结果与其他信息合并  
        cluster_predictions = pd.DataFrame({  
            'code': test_codes,  
            'Predicted_Interval_{}'.format(chr(97 + i)): Y_pred,  # 使用 a, b, c 标记每次的预测区间  
            'Actual_{}'.format(chr(97 + i)): Y_test,  
            'Width_{}'.format(chr(97 + i)): Y_width,  
            'Lower_Bound_{}'.format(chr(97 + i)): Y_lower,  
            'Upper_Bound_{}'.format(chr(97 + i)): Y_upper  
        })  
      
        # 存储预测结果  
        predictions_all.append(cluster_predictions)  
      
    # 合并三次的预测结果，并计算平均预测区间和预测值  
    # 假设所有的code在三次迭代中都是相同的，可以直接按code合并  
    all_predictions = pd.concat(predictions_all, ignore_index=True)  
    #print(all_predictions)
    # 计算平均预测区间和预测值  
    # 注意：这里假设三次迭代的code顺序完全一致
    all_predictions.fillna(0, inplace=True)
    all_predictions['Predicted'] = (all_predictions['Predicted_Interval_a'] + all_predictions['Predicted_Interval_b'] + all_predictions['Predicted_Interval_c'])  
    all_predictions['Width'] = (all_predictions['Width_a'] + all_predictions['Width_b'] + all_predictions['Width_c'])
    all_predictions['Actual'] = (all_predictions['Actual_a'] + all_predictions['Actual_b'] + all_predictions['Actual_c'])
    #print(all_predictions)
    # 删除临时的预测区间列  
    for col in ['Lower_Bound_a','Lower_Bound_b','Lower_Bound_c','Upper_Bound_a','Upper_Bound_b','Upper_Bound_c',
                'Predicted_Interval_a', 'Predicted_Interval_b', 'Predicted_Interval_c', 'Width_a', 'Width_b', 'Width_c',
                'Actual_a','Actual_b','Actual_c']:  
        if col in all_predictions.columns:  
            all_predictions.drop(columns=col, inplace=True)  
      
    #print(all_predictions)
    
    # 存储预测结果  
    predictions_all_2.append(all_predictions)  
    # print(predictions_all_2)
    
    test_data_with_predictions = pd.concat(predictions_all_2, ignore_index=True)  
    # print("test_data_with_predictions")
    # print(test_data_with_predictions)
    
    # 在计算距离之前，先排除 Actual 为 0 的数据  
    selected_stocks = test_data_with_predictions[test_data_with_predictions['Actual'] != 0] 
      
    # 计算并排序选出的股票离预测区间下界的距离  
    selected_stocks['Distance to Predicted'] = (selected_stocks['Actual'] - selected_stocks['Predicted'])/abs(selected_stocks['Actual'])
    selected_stocks_sorted = selected_stocks.sort_values(by='Distance to Predicted')  
    
    print(selected_stocks_sorted)
    #查看区间宽度
    print("区间宽度为")
    print(all_predictions['Width'].mean())
    
    g.stocknum = g.stocknum_2
    # 使用IQR方法去除离群值  
    Q1 = selected_stocks['Distance to Predicted'].quantile(0.25)  
    Q3 = selected_stocks['Distance to Predicted'].quantile(0.75)  
    IQR = Q3 - Q1  
    filter = (selected_stocks['Distance to Predicted'] >= Q1 - 3 * IQR) & (selected_stocks['Distance to Predicted'] <= Q3 + 3* IQR)  
    selected_stocks_filtered = selected_stocks.loc[filter]  
    
    if (all_predictions['Width'].mean() < 1.4) :
        print("进入反转行情")
        g.stocknum = g.stocknum_2
        # 对数据进行排序 
        selected_stocks_sorted = selected_stocks_filtered.sort_values(by='Distance to Predicted',ascending=True)  
          
        # 打印选出的股票数据（已去除离群值）  
        print('Conformal Regression选出的股票为：\n%s'%selected_stocks_sorted.head())
            
        final_list = selected_stocks_sorted['code'].tolist()
        
    else:
        print("进入突破行情")
        g.stocknum = g.stocknum_1
        # 对数据进行排序 
        selected_stocks_sorted = selected_stocks_filtered.sort_values(by='Distance to Predicted',ascending=False)  
          
        # 打印选出的股票数据（已去除离群值）  
        print('Conformal Regression选出的股票为：\n%s'%selected_stocks_sorted.head())
            
        final_list = selected_stocks_sorted['code'].tolist()

    # print(final_list)
    return final_list
  

 
#  买入信号：   
def stocks_to_buy(context):
    if g.no_trading_today_signal == False:
        day1=context.current_dt
        day2= day1-datetime.timedelta(days=5)
        list_to_buy = get_rff(context, g.feasible_stocks)[:g.stocknum]
        print('买入股票:%s' %list_to_buy)
        
        return list_to_buy 

# 获得卖出信号
# 输入：context（见API文档）, list_to_buy为list类型，代表待买入的股票
# 输出：list_to_sell为list类型，表示待卖出的股票
def stocks_to_sell(context, list_to_buy):
    if g.no_trading_today_signal == False:
        # 对于不需要持仓的股票，全仓卖出
        list_to_sell=[]
        day1=context.current_dt
        day2= day1-datetime.timedelta(days=5)
        for stock_sell in context.portfolio.positions:
            # 股票盈利大于等于100%则卖出
            if context.portfolio.positions[stock_sell].price >= context.portfolio.positions[stock_sell].avg_cost * (1 + g.stopprofit_market):
                list_to_sell.append(stock_sell)
                print('股票止盈，卖出股票:%s' %list_to_sell)
            elif (context.portfolio.positions[stock_sell].price
                        < context.portfolio.positions[stock_sell].avg_cost *(1 - g.stoploss_market)):
                list_to_sell.append(stock_sell)
                print('股票止损，卖出股票:%s' %list_to_sell)
            elif (stock_sell not in list_to_buy):
                list_to_sell.append(stock_sell)
                print('股票更换，卖出股票:%s' %list_to_sell)
                    
        return list_to_sell  
    
# 执行卖出操作
# 输入：list_to_sell为list类型，表示待卖出的股票
# 输出：none
def sell_operation(list_to_sell):
    if g.no_trading_today_signal == False:
        for stock_sell in list_to_sell:
            order_target_value(stock_sell, 0)
            
#4-2 清仓后次日资金可转
def close_account(context):
    g.hold_list = context.portfolio.positions
    if g.no_trading_today_signal == True:
        if len(g.hold_list) != 0:
            for stock in g.hold_list:
                position = context.portfolio.positions[stock]
                close_position(position)
                log.info("卖出[%s]" % (stock))

#3-1 交易模块-自定义下单
def order_target_value_(security, value):
    if value == 0:
        pass
        #log.debug("Selling out %s" % (security))
    else:
        log.debug("Order %s to value %f" % (security, value))
    return order_target_value(security, value)
    
#3-3 交易模块-平仓
def close_position(position):
    
    security = position.security
    order = order_target_value_(security, 0)  # 可能会因停牌失败
    if order != None:
        if order.status == OrderStatus.held and order.filled == order.amount:
            return True
    return False
# 执行买入操作
# 输入：context(见API)；list_to_buy为list类型，表示待买入的股票
# 输出：none
# def buy_operation(context, list_to_buy):
#     for stock_sell in list_to_buy:
#         # 为每个持仓股票分配资金
#         g.capital_unit=context.portfolio.portfolio_value/len(list_to_buy)
#         # 买入在“待买股票列表”的股票
#         for stock_buy in list_to_buy:
#             order_target_value(stock_buy, g.capital_unit)

def buy_operation(context,list_to_buy):
   if g.no_trading_today_signal == False:
        if len(context.portfolio.positions) < g.stocknum:
            num = g.stocknum - len(context.portfolio.positions)
            cash = context.portfolio.cash/num
        else:
            cash = 0
            num = 0
        for stock_sell in list_to_buy[:num+1]:
                order_target_value(stock_sell, cash)
                num = num - 1
                if num == 0:
                    break
        else:
            pass

'''
================================================================================
每天收盘后
================================================================================
'''
# 每天收盘后做的事情
# 进行长运算（本策略中不需要）

def after_trading_end(context):
    #得到当天所有订单
    orders = get_orders()
    for _order in orders.values():
        log.info(_order.order_id)      
        log.info('账户可用资金：',context.portfolio.subportfolios[0].available_cash)
    #     if len(context.portfolio.positions) < g.stocknum:
    #         num = g.stocknum - len(context.portfolio.positions)
    #         cash = context.portfolio.cash/num
    #     else:
    #         cash = 0
    #         num = 0
    #     for stock in stockset[:g.stocknum]:
    #         if stock in sell_list:
    #             pass
    #         else:
    #             stock_buy = stock
    #             order_target_value(stock_buy, cash)
    #             num = num - 1
    #             if num == 0:
    #                 break
    #     g.days += 1
    # else:
    #     g.days = g.days + 1    
            
        
        
'''
========================================================================
保形回归（Conformal Regression）环境配置
========================================================================
'''

#定义base

"""
docstring
"""

# Authors: Henrik Linusson

import abc
import numpy as np

from sklearn.base import BaseEstimator


class RegressorMixin(object):
	def __init__(self):
		super(RegressorMixin, self).__init__()

	@classmethod
	def get_problem_type(cls):
		return 'regression'


class ClassifierMixin(object):
	def __init__(self):
		super(ClassifierMixin, self).__init__()

	@classmethod
	def get_problem_type(cls):
		return 'classification'


class BaseModelAdapter(BaseEstimator):
	__metaclass__ = abc.ABCMeta

	def __init__(self, model, fit_params=None):
		super(BaseModelAdapter, self).__init__()

		self.model = model
		self.last_x, self.last_y = None, None
		self.clean = False
		self.fit_params = {} if fit_params is None else fit_params

	def fit(self, x, y):
		"""Fits the model.

		Parameters
		----------
		x : numpy array of shape [n_samples, n_features]
			Inputs of examples for fitting the model.

		y : numpy array of shape [n_samples]
			Outputs of examples for fitting the model.

		Returns
		-------
		None
		"""

		self.model.fit(x, y, **self.fit_params)
		self.clean = False

	def predict(self, x):
		"""Returns the prediction made by the underlying model.

		Parameters
		----------
		x : numpy array of shape [n_samples, n_features]
			Inputs of test examples.

		Returns
		-------
		y : numpy array of shape [n_samples]
			Predicted outputs of test examples.
		"""
		if (
			not self.clean or
			self.last_x is None or
			self.last_y is None or
			not np.array_equal(self.last_x, x)
		):
			self.last_x = x
			self.last_y = self._underlying_predict(x)
			self.clean = True

		return self.last_y.copy()

	@abc.abstractmethod
	def _underlying_predict(self, x):
		"""Produces a prediction using the encapsulated model.

		Parameters
		----------
		x : numpy array of shape [n_samples, n_features]
			Inputs of test examples.

		Returns
		-------
		y : numpy array of shape [n_samples]
			Predicted outputs of test examples.
		"""
		pass


class ClassifierAdapter(BaseModelAdapter):
	def __init__(self, model, fit_params=None):
		super(ClassifierAdapter, self).__init__(model, fit_params)

	def _underlying_predict(self, x):
		return self.model.predict_proba(x)


class RegressorAdapter(BaseModelAdapter):
	def __init__(self, model, fit_params=None):
		super(RegressorAdapter, self).__init__(model, fit_params)

	def _underlying_predict(self, x):
		return self.model.predict(x)


class OobMixin(object):
	def __init__(self, model, fit_params=None):
		super(OobMixin, self).__init__(model, fit_params)
		self.train_x = None

	def fit(self, x, y):
		super(OobMixin, self).fit(x, y)
		self.train_x = x

	def _underlying_predict(self, x):
		# TODO: sub-sampling of ensemble for test patterns
		oob = x == self.train_x

		if hasattr(oob, 'all'):
			oob = oob.all()

		if oob:
			return self._oob_prediction()
		else:
			return super(OobMixin, self)._underlying_predict(x)


class OobClassifierAdapter(OobMixin, ClassifierAdapter):
	def __init__(self, model, fit_params=None):
		super(OobClassifierAdapter, self).__init__(model, fit_params)

	def _oob_prediction(self):
		return self.model.oob_decision_function_


class OobRegressorAdapter(OobMixin, RegressorAdapter):
	def __init__(self, model, fit_params=None):
		super(OobRegressorAdapter, self).__init__(model, fit_params)

	def _oob_prediction(self):
		return self.model.oob_prediction_
		
#定义BaseScorer
class BaseScorer(sklearn.base.BaseEstimator):
	__metaclass__ = abc.ABCMeta

	def __init__(self):
		super(BaseScorer, self).__init__()

	@abc.abstractmethod
	def fit(self, x, y):
		pass

	@abc.abstractmethod
	def score(self, x, y=None):
		pass
		
#定义BaseModelNc
class BaseModelNc(BaseScorer):
	"""Base class for nonconformity scorers based on an underlying model.

	Parameters
	----------
	model : ClassifierAdapter or RegressorAdapter
		Underlying classification model used for calculating nonconformity
		scores.

	err_func : ClassificationErrFunc or RegressionErrFunc
		Error function object.

	normalizer : BaseScorer
		Normalization model.

	beta : float
		Normalization smoothing parameter. As the beta-value increases,
		the normalized nonconformity function approaches a non-normalized
		equivalent.
	"""
	def __init__(self, model, err_func, normalizer=None, beta=0):
		super(BaseModelNc, self).__init__()
		self.err_func = err_func
		self.model = model
		self.normalizer = normalizer
		self.beta = beta

		# If we use sklearn.base.clone (e.g., during cross-validation),
		# object references get jumbled, so we need to make sure that the
		# normalizer has a reference to the proper model adapter, if applicable.
		if (self.normalizer is not None and
			hasattr(self.normalizer, 'base_model')):
			self.normalizer.base_model = self.model

		self.last_x, self.last_y = None, None
		self.last_prediction = None
		self.clean = False

	def fit(self, x, y):
		"""Fits the underlying model of the nonconformity scorer.

		Parameters
		----------
		x : numpy array of shape [n_samples, n_features]
			Inputs of examples for fitting the underlying model.

		y : numpy array of shape [n_samples]
			Outputs of examples for fitting the underlying model.

		Returns
		-------
		None
		"""
		self.model.fit(x, y)
		if self.normalizer is not None:
			self.normalizer.fit(x, y)
		self.clean = False

	def score(self, x, y=None):
		"""Calculates the nonconformity score of a set of samples.

		Parameters
		----------
		x : numpy array of shape [n_samples, n_features]
			Inputs of examples for which to calculate a nonconformity score.

		y : numpy array of shape [n_samples]
			Outputs of examples for which to calculate a nonconformity score.

		Returns
		-------
		nc : numpy array of shape [n_samples]
			Nonconformity scores of samples.
		"""
		prediction = self.model.predict(x)
		n_test = x.shape[0]
		if self.normalizer is not None:
			norm = self.normalizer.score(x) + self.beta
		else:
			norm = np.ones(n_test)

		return self.err_func.apply(prediction, y) / norm

#定义TcpClassifier
class TcpClassifier(BaseEstimator, ClassifierMixin):
	"""Transductive conformal classifier.

	Parameters
	----------
	nc_function : BaseScorer
		Nonconformity scorer object used to calculate nonconformity of
		calibration examples and test patterns. Should implement ``fit(x, y)``
		and ``calc_nc(x, y)``.

	smoothing : boolean
		Decides whether to use stochastic smoothing of p-values.

	Attributes
	----------
	train_x : numpy array of shape [n_cal_examples, n_features]
		Inputs of training set.

	train_y : numpy array of shape [n_cal_examples]
		Outputs of calibration set.

	nc_function : BaseScorer
		Nonconformity scorer object used to calculate nonconformity scores.

	classes : numpy array of shape [n_classes]
		List of class labels, with indices corresponding to output columns
		 of TcpClassifier.predict()

	See also
	--------
	IcpClassifier

	References
	----------
	.. [1] Vovk, V., Gammerman, A., & Shafer, G. (2005). Algorithmic learning
	in a random world. Springer Science & Business Media.

	Examples
	--------
	>>> import numpy as np
	>>> from sklearn.datasets import load_iris
	>>> from sklearn.svm import SVC
	>>> from nonconformist.base import ClassifierAdapter
	>>> from nonconformist.cp import TcpClassifier
	>>> from nonconformist.nc import ClassifierNc, MarginErrFunc
	>>> iris = load_iris()
	>>> idx = np.random.permutation(iris.target.size)
	>>> train = idx[:int(idx.size / 2)]
	>>> test = idx[int(idx.size / 2):]
	>>> model = ClassifierAdapter(SVC(probability=True))
	>>> nc = ClassifierNc(model, MarginErrFunc())
	>>> tcp = TcpClassifier(nc)
	>>> tcp.fit(iris.data[train, :], iris.target[train])
	>>> tcp.predict(iris.data[test, :], significance=0.10)
	...             # doctest: +SKIP
	array([[ True, False, False],
		[False,  True, False],
		...,
		[False,  True, False],
		[False,  True, False]], dtype=bool)
	"""

	def __init__(self, nc_function, condition=None, smoothing=True):
		self.train_x, self.train_y = None, None
		self.nc_function = nc_function
		super(TcpClassifier, self).__init__()

		# Check if condition-parameter is the default function (i.e.,
		# lambda x: 0). This is so we can safely clone the object without
		# the clone accidentally having self.conditional = True.
		default_condition = lambda x: 0
		is_default = (callable(condition) and
		              (condition.__code__.co_code ==
		               default_condition.__code__.co_code))

		if is_default:
			self.condition = condition
			self.conditional = False
		elif callable(condition):
			self.condition = condition
			self.conditional = True
		else:
			self.condition = lambda x: 0
			self.conditional = False

		self.smoothing = smoothing

		self.base_icp = IcpClassifier(
			self.nc_function,
			self.condition,
			self.smoothing
		)

		self.classes = None

	def fit(self, x, y):
		self.train_x, self.train_y = x, y
		self.classes = np.unique(y)

	def predict(self, x, significance=None):
		"""Predict the output values for a set of input patterns.

		Parameters
		----------
		x : numpy array of shape [n_samples, n_features]
			Inputs of patters for which to predict output values.

		significance : float or None
			Significance level (maximum allowed error rate) of predictions.
			Should be a float between 0 and 1. If ``None``, then the p-values
			are output rather than the predictions.

		Returns
		-------
		p : numpy array of shape [n_samples, n_classes]
			If significance is ``None``, then p contains the p-values for each
			sample-class pair; if significance is a float between 0 and 1, then
			p is a boolean array denoting which labels are included in the
			prediction sets.
		"""
		n_test = x.shape[0]
		n_train = self.train_x.shape[0]
		p = np.zeros((n_test, self.classes.size))
		for i in range(n_test):
			for j, y in enumerate(self.classes):
				train_x = np.vstack([self.train_x, x[i, :]])
				train_y = np.hstack([self.train_y, y])
				self.base_icp.fit(train_x, train_y)
				self.base_icp.calibrate(train_x, train_y)

				ncal_ngt_neq = self.base_icp._get_stats(x[i, :].reshape(1, x.shape[1]))

				ncal = ncal_ngt_neq[:, j, 0]
				ngt = ncal_ngt_neq[:, j, 1]
				neq = ncal_ngt_neq[:, j, 2]

				p[i, j] = calc_p(ncal - 1, ngt, neq - 1, self.smoothing)

		if significance is not None:
			return p > significance
		else:
			return p

	def predict_conf(self, x):
		"""Predict the output values for a set of input patterns, using
		the confidence-and-credibility output scheme.

		Parameters
		----------
		x : numpy array of shape [n_samples, n_features]
			Inputs of patters for which to predict output values.

		Returns
		-------
		p : numpy array of shape [n_samples, 3]
			p contains three columns: the first column contains the most
			likely class for each test pattern; the second column contains
			the confidence in the predicted class label, and the third column
			contains the credibility of the prediction.
		"""
		p = self.predict(x, significance=None)
		label = p.argmax(axis=1)
		credibility = p.max(axis=1)
		for i, idx in enumerate(label):
			p[i, idx] = -np.inf
		confidence = 1 - p.max(axis=1)

		return np.array([label, confidence, credibility]).T
		
		
#定义NcFactory
class NcFactory(object):
	@staticmethod
	def create_nc(model, err_func=None, normalizer_model=None, oob=False,
                      fit_params=None, fit_params_normalizer=None):
		if normalizer_model is not None:
			normalizer_adapter = RegressorAdapter(normalizer_model, fit_params_normalizer)
		else:
			normalizer_adapter = None

		if isinstance(model, sklearn.base.ClassifierMixin):
			err_func = MarginErrFunc() if err_func is None else err_func
			if oob:
				c = sklearn.base.clone(model)
				c.fit([[0], [1]], [0, 1])
				if hasattr(c, 'oob_decision_function_'):
					adapter = OobClassifierAdapter(model, fit_params)
				else:
					raise AttributeError('Cannot use out-of-bag '
					                      'calibration with {}'.format(
						model.__class__.__name__
					))
			else:
				adapter = ClassifierAdapter(model, fit_params)

			if normalizer_adapter is not None:
				normalizer = RegressorNormalizer(adapter,
				                                 normalizer_adapter,
				                                 err_func)
				return ClassifierNc(adapter, err_func, normalizer)
			else:
				return ClassifierNc(adapter, err_func)

		elif isinstance(model, sklearn.base.RegressorMixin):
			err_func = AbsErrorErrFunc() if err_func is None else err_func
			if oob:
				c = sklearn.base.clone(model)
				c.fit([[0], [1]], [0, 1])
				if hasattr(c, 'oob_prediction_'):
					adapter = OobRegressorAdapter(model, fit_params)
				else:
					raise AttributeError('Cannot use out-of-bag '
					                     'calibration with {}'.format(
						model.__class__.__name__
					))
			else:
				adapter = RegressorAdapter(model, fit_params)

			if normalizer_adapter is not None:
				normalizer = RegressorNormalizer(adapter,
				                                 normalizer_adapter,
				                                 err_func)
				return RegressorNc(adapter, err_func, normalizer)
			else:
				return RegressorNc(adapter, err_func)
				
				
				
#定义BaseIcp
class BaseIcp(BaseEstimator):
	"""Base class for inductive conformal predictors.
	"""
	def __init__(self, nc_function, condition=None):
		self.cal_x, self.cal_y = None, None
		self.nc_function = nc_function

		# Check if condition-parameter is the default function (i.e.,
		# lambda x: 0). This is so we can safely clone the object without
		# the clone accidentally having self.conditional = True.
		default_condition = lambda x: 0
		is_default = (callable(condition) and
		              (condition.__code__.co_code ==
		               default_condition.__code__.co_code))

		if is_default:
			self.condition = condition
			self.conditional = False
		elif callable(condition):
			self.condition = condition
			self.conditional = True
		else:
			self.condition = lambda x: 0
			self.conditional = False

	def fit(self, x, y):
		"""Fit underlying nonconformity scorer.

		Parameters
		----------
		x : numpy array of shape [n_samples, n_features]
			Inputs of examples for fitting the nonconformity scorer.

		y : numpy array of shape [n_samples]
			Outputs of examples for fitting the nonconformity scorer.

		Returns
		-------
		None
		"""
		# TODO: incremental?
		self.nc_function.fit(x, y)

	def calibrate(self, x, y, increment=False):
		"""Calibrate conformal predictor based on underlying nonconformity
		scorer.

		Parameters
		----------
		x : numpy array of shape [n_samples, n_features]
			Inputs of examples for calibrating the conformal predictor.

		y : numpy array of shape [n_samples, n_features]
			Outputs of examples for calibrating the conformal predictor.

		increment : boolean
			If ``True``, performs an incremental recalibration of the conformal
			predictor. The supplied ``x`` and ``y`` are added to the set of
			previously existing calibration examples, and the conformal
			predictor is then calibrated on both the old and new calibration
			examples.

		Returns
		-------
		None
		"""
		self._calibrate_hook(x, y, increment)
		self._update_calibration_set(x, y, increment)

		if self.conditional:
			category_map = np.array([self.condition((x[i, :], y[i]))
									 for i in range(y.size)])
			self.categories = np.unique(category_map)
			self.cal_scores = defaultdict(partial(np.ndarray, 0))

			for cond in self.categories:
				idx = category_map == cond
				cal_scores = self.nc_function.score(self.cal_x[idx, :],
				                                    self.cal_y[idx])
				self.cal_scores[cond] = np.sort(cal_scores)[::-1]
		else:
			self.categories = np.array([0])
			cal_scores = self.nc_function.score(self.cal_x, self.cal_y)
			self.cal_scores = {0: np.sort(cal_scores)[::-1]}

	def _calibrate_hook(self, x, y, increment):
		pass

	def _update_calibration_set(self, x, y, increment):
		if increment and self.cal_x is not None and self.cal_y is not None:
			self.cal_x = np.vstack([self.cal_x, x])
			self.cal_y = np.hstack([self.cal_y, y])
		else:
			self.cal_x, self.cal_y = x, y




#定义 IcpRegressor
class IcpRegressor(BaseIcp, RegressorMixin):
	"""Inductive conformal regressor.

	Parameters
	----------
	nc_function : BaseScorer
		Nonconformity scorer object used to calculate nonconformity of
		calibration examples and test patterns. Should implement ``fit(x, y)``,
		``calc_nc(x, y)`` and ``predict(x, nc_scores, significance)``.

	Attributes
	----------
	cal_x : numpy array of shape [n_cal_examples, n_features]
		Inputs of calibration set.

	cal_y : numpy array of shape [n_cal_examples]
		Outputs of calibration set.

	nc_function : BaseScorer
		Nonconformity scorer object used to calculate nonconformity scores.

	See also
	--------
	IcpClassifier

	References
	----------
	.. [1] Papadopoulos, H., Proedrou, K., Vovk, V., & Gammerman, A. (2002).
		Inductive confidence machines for regression. In Machine Learning: ECML
		2002 (pp. 345-356). Springer Berlin Heidelberg.

	.. [2] Papadopoulos, H., & Haralambous, H. (2011). Reliable prediction
		intervals with regression neural networks. Neural Networks, 24(8),
		842-851.

	Examples
	--------
	>>> import numpy as np
	>>> from sklearn.datasets import load_boston
	>>> from sklearn.tree import DecisionTreeRegressor
	>>> from nonconformist.base import RegressorAdapter
	>>> from nonconformist.icp import IcpRegressor
	>>> from nonconformist.nc import RegressorNc, AbsErrorErrFunc
	>>> boston = load_boston()
	>>> idx = np.random.permutation(boston.target.size)
	>>> train = idx[:int(idx.size / 3)]
	>>> cal = idx[int(idx.size / 3):int(2 * idx.size / 3)]
	>>> test = idx[int(2 * idx.size / 3):]
	>>> model = RegressorAdapter(DecisionTreeRegressor())
	>>> nc = RegressorNc(model, AbsErrorErrFunc())
	>>> icp = IcpRegressor(nc)
	>>> icp.fit(boston.data[train, :], boston.target[train])
	>>> icp.calibrate(boston.data[cal, :], boston.target[cal])
	>>> icp.predict(boston.data[test, :], significance=0.10)
	...     # doctest: +SKIP
	array([[  5. ,  20.6],
		[ 15.5,  31.1],
		...,
		[ 14.2,  29.8],
		[ 11.6,  27.2]])
	"""
	def __init__(self, nc_function, condition=None):
		super(IcpRegressor, self).__init__(nc_function, condition)

	def predict(self, x, significance=None):
		"""Predict the output values for a set of input patterns.

		Parameters
		----------
		x : numpy array of shape [n_samples, n_features]
			Inputs of patters for which to predict output values.

		significance : float
			Significance level (maximum allowed error rate) of predictions.
			Should be a float between 0 and 1. If ``None``, then intervals for
			all significance levels (0.01, 0.02, ..., 0.99) are output in a
			3d-matrix.

		Returns
		-------
		p : numpy array of shape [n_samples, 2] or [n_samples, 2, 99}
			If significance is ``None``, then p contains the interval (minimum
			and maximum boundaries) for each test pattern, and each significance
			level (0.01, 0.02, ..., 0.99). If significance is a float between
			0 and 1, then p contains the prediction intervals (minimum and
			maximum	boundaries) for the set of test patterns at the chosen
			significance level.
		"""
		# TODO: interpolated p-values

		n_significance = (99 if significance is None
		                  else np.array(significance).size)

		if n_significance > 1:
			prediction = np.zeros((x.shape[0], 2, n_significance))
		else:
			prediction = np.zeros((x.shape[0], 2))

		condition_map = np.array([self.condition((x[i, :], None))
		                          for i in range(x.shape[0])])

		for condition in self.categories:
			idx = condition_map == condition
			if np.sum(idx) > 0:
				p = self.nc_function.predict(x[idx, :],
				                             self.cal_scores[condition],
				                             significance)
				if n_significance > 1:
					prediction[idx, :, :] = p
				else:
					prediction[idx, :] = p

		return prediction




#定义RegressionErrFunc
class RegressionErrFunc(object):
	"""Base class for regression model error functions.
	"""

	__metaclass__ = abc.ABCMeta

	def __init__(self):
		super(RegressionErrFunc, self).__init__()

	@abc.abstractmethod
	def apply(self, prediction, y):#, norm=None, beta=0):
		"""Apply the nonconformity function.

		Parameters
		----------
		prediction : numpy array of shape [n_samples, n_classes]
			Class probability estimates for each sample.

		y : numpy array of shape [n_samples]
			True output labels of each sample.

		Returns
		-------
		nc : numpy array of shape [n_samples]
			Nonconformity scores of the samples.
		"""
		pass

	@abc.abstractmethod
	def apply_inverse(self, nc, significance):#, norm=None, beta=0):
		"""Apply the inverse of the nonconformity function (i.e.,
		calculate prediction interval).

		Parameters
		----------
		nc : numpy array of shape [n_calibration_samples]
			Nonconformity scores obtained for conformal predictor.

		significance : float
			Significance level (0, 1).

		Returns
		-------
		interval : numpy array of shape [n_samples, 2]
			Minimum and maximum interval boundaries for each prediction.
		"""
		pass




#定义AbsErrorErrFunc
class AbsErrorErrFunc(RegressionErrFunc):
	"""Calculates absolute error nonconformity for regression problems.

		For each correct output in ``y``, nonconformity is defined as

		.. math::
			| y_i - \hat{y}_i |
	"""

	def __init__(self):
		super(AbsErrorErrFunc, self).__init__()

	def apply(self, prediction, y):
		return np.abs(prediction - y)

	def apply_inverse(self, nc, significance):
		nc = np.sort(nc)[::-1]
		border = int(np.floor(significance * (nc.size + 1))) - 1
		# TODO: should probably warn against too few calibration examples
		border = min(max(border, 0), nc.size - 1)
		return np.vstack([nc[border], nc[border]])




#定义RegressorNc
class RegressorNc(BaseModelNc):
	"""Nonconformity scorer using an underlying regression model.

	Parameters
	----------
	model : RegressorAdapter
		Underlying regression model used for calculating nonconformity scores.

	err_func : RegressionErrFunc
		Error function object.

	normalizer : BaseScorer
		Normalization model.

	beta : float
		Normalization smoothing parameter. As the beta-value increases,
		the normalized nonconformity function approaches a non-normalized
		equivalent.

	Attributes
	----------
	model : RegressorAdapter
		Underlying model object.

	err_func : RegressionErrFunc
		Scorer function used to calculate nonconformity scores.

	See also
	--------
	ProbEstClassifierNc, NormalizedRegressorNc
	"""
	def __init__(self,
	             model,
	             err_func=AbsErrorErrFunc(),
	             normalizer=None,
	             beta=0):
		super(RegressorNc, self).__init__(model,
		                                  err_func,
		                                  normalizer,
		                                  beta)

	def predict(self, x, nc, significance=None):
		"""Constructs prediction intervals for a set of test examples.

		Predicts the output of each test pattern using the underlying model,
		and applies the (partial) inverse nonconformity function to each
		prediction, resulting in a prediction interval for each test pattern.

		Parameters
		----------
		x : numpy array of shape [n_samples, n_features]
			Inputs of patters for which to predict output values.

		significance : float
			Significance level (maximum allowed error rate) of predictions.
			Should be a float between 0 and 1. If ``None``, then intervals for
			all significance levels (0.01, 0.02, ..., 0.99) are output in a
			3d-matrix.

		Returns
		-------
		p : numpy array of shape [n_samples, 2] or [n_samples, 2, 99]
			If significance is ``None``, then p contains the interval (minimum
			and maximum boundaries) for each test pattern, and each significance
			level (0.01, 0.02, ..., 0.99). If significance is a float between
			0 and 1, then p contains the prediction intervals (minimum and
			maximum	boundaries) for the set of test patterns at the chosen
			significance level.
		"""
		n_test = x.shape[0]
		prediction = self.model.predict(x)
		if self.normalizer is not None:
			norm = self.normalizer.score(x) + self.beta
		else:
			norm = np.ones(n_test)

		if significance:
			intervals = np.zeros((x.shape[0], 2))
			err_dist = self.err_func.apply_inverse(nc, significance)
			err_dist = np.hstack([err_dist] * n_test)
			err_dist *= norm

			intervals[:, 0] = prediction - err_dist[0, :]
			intervals[:, 1] = prediction + err_dist[1, :]

			return intervals
		else:
			significance = np.arange(0.01, 1.0, 0.01)
			intervals = np.zeros((x.shape[0], 2, significance.size))

			for i, s in enumerate(significance):
				err_dist = self.err_func.apply_inverse(nc, s)
				err_dist = np.hstack([err_dist] * n_test)
				err_dist *= norm

				intervals[:, 0, i] = prediction - err_dist[0, :]
				intervals[:, 1, i] = prediction + err_dist[0, :]

			return intervals
