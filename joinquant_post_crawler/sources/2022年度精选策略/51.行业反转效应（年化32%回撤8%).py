# 克隆自聚宽文章：https://www.joinquant.com/post/36494
# 标题：行业反转效应（年化32%/回撤8%）
# 作者：silent storm

from jqdata import *
import pandas as pd
import numpy as np
from scipy import stats

#初始化函数 
def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    set_slippage(FixedSlippage(0.001))
    set_order_cost(OrderCost(open_tax=0, close_tax=0, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),
                   type='fund')
    
    # 反转参数
    g.rolling = 36 # 滚动月份
    g.s = 3 # 反转短期
    g.m = 6 # 反转中期
    
     #初始相关性函数
    g.initial = True
    run_monthly(industry_selection, monthday = 1, reference_security ='000300.XSHG')
    run_monthly(ETF_selection, monthday = 1, reference_security ='000300.XSHG')
    run_monthly(trade, monthday = 1, reference_security ='000300.XSHG')
    #run_daily(RSRS_adjustment, time = '9:30', reference_security ='000300.XSHG')

# 设置行业的收益计算函数：
def returns_calculation(start_date, end_date, context):
    
    # 初始记录收益率的字典
    returns_dict = {}

    # 设置行业列表：
    industries = get_industries(name = "sw_l1", date = context.current_dt)
    deprecated_industries = ['801060','801070','801090','801100','801190','801220']
    
    # 取出每个行业五年内的收盘价
    for code in list(industries.index):
        if code not in deprecated_industries:
            #从2020年开始，取出历年来的行业收盘价
            df = get_price(get_industry_stocks(code), start_date = start_date, end_date = end_date, frequency = '1d', fields = ['close'], panel = False)
                    
            # 按照时间线合并行业的收盘价：
            df = df.groupby('time').sum()
                    
            # 计算出行业的收益率
            df = df.pct_change().dropna()
            
            # 更新每个行业的column 为行业名称
            name = industries['name'][code]
            df.columns = [name]
            
            # 保存到字典：
            returns_dict[code] = df
    
    # 合并个行业的收益率：
    data = pd.concat(returns_dict.values(), axis = 1)
    return data


# 超额收益相关性的函数：
def correlation_calculation(factor_month, data):
    pooled_dict = {}
    data = data.reset_index().drop('index', axis = 1) # 重制index
    commence_month = 0
    regression_month = factor_month # 作为用数据的节点

    for month in data[factor_month:].index: # 进入当月
        coefficient_dict = {}
        for industry in data.columns: # 进入当个行业
            previous_data = data[industry][commence_month:regression_month] # 取出前N月的数据
            y = data[industry][regression_month] # 取出regress的月超额收益
            coefficient = y / previous_data # 做简单关联性
            coefficient_dict[industry] = coefficient.mean() # 取其关联性平均值

        # 更新此个月份的相关性：
        pooled_dict[month] = coefficient_dict

        # 更新要取的period
        if regression_month < data.iloc[-1:].index[0]: #不超出记录的index
            regression_month += 1
            commence_month += 1
            
    coefficient_df = pd.DataFrame(pooled_dict).T.mean()
    coefficient_df = pd.DataFrame(coefficient_df)
    coefficient_df.columns = [factor_month]
    return coefficient_df
    

# 行业选择函数：
def industry_selection(context):
    
    # 1.以月度为单位取出过去rolling月份的行业收益率(累积式)
    
    #如果第一次开始，则取出前三年的数据：
    if g.initial:
        # 设置要取出的时间：
        year = int(context.current_dt.year - (g.rolling / 12)) # 要取出的年份开始数值
        month = context.current_dt.month 
        start_date = datetime.datetime(year, month, 1, 9, 0, 0)
        end_date = context.previous_date
        data = returns_calculation(start_date, end_date, context)
        g.initial = False
        
        #设置月度行业收益率字典
        sample_dict = {}
        date_list = []
        
        for m in range(1, g.rolling + 1):
            # 如果当前月份小于12月
            if month < 12:
                start = datetime.datetime(year, month, 1, 9, 0, 0)
                end = datetime.datetime(year, month + 1, 1, 9, 0, 0)
                df = pd.DataFrame(data[start:end].sum())
                df.columns = [m]
                sample_dict[m] = df
                month += 1
                
            
            # 如果当前月份是12月
            elif month == 12:
                start = datetime.datetime(year, month, 1, 9, 0, 0)
                month = 1
                year += 1
                end = datetime.datetime(year, month + 1, 1, 9, 0, 0)
                df = pd.DataFrame(data[start:end].sum())
                df.columns = [m]
                sample_dict[m] = df
    
        # 得出rolling月份的行业收益率：
        g.data = pd.concat(sample_dict.values(), axis = 1).T
    
    #如果策略已开始：    
    else:
        # 设置要取出的时间：
        end_date = context.previous_date
        
        #一月份则去年12月份
        if context.current_dt.month == 1:
            year = context.current_dt.year - 1
            month = 12
            start_date = datetime.datetime(year, month, 1, 9, 0, 0)
        
        #否则选择上个月份：
        else:
            year = context.current_dt.year
            month = context.current_dt.month - 1
            start_date = datetime.datetime(year, month, 1, 9, 0, 0)
        
        # 加入上个月度的数据到g.data：
        data = returns_calculation(start_date, end_date, context)
        data = pd.DataFrame(data.sum())
        data.columns = [g.data.index[-1] + 1]
        data = data.T
        g.data = pd.concat([g.data, data], axis = 0)


    # 2.取出rolling月份的数据，计算行业超额收益率
    ex_data = g.data.iloc[-g.rolling:] - g.data.iloc[-g.rolling:].mean()

    #3. 根据短期（2月相隔）和中期反转/轮动相关性（7月), 预测未来一个月的行业超额收益率：
    s_df = correlation_calculation(g.s, ex_data) #短期行业累积收入
    s_sum = pd.DataFrame(ex_data.iloc[-g.s:].mean()) #短期行业收入
    s_data = pd.concat([s_df,s_sum], axis = 1, sort=True)
    s_data['prediction'] = s_data[0] * s_data[g.s] #给出短期预测
        
    m_df = correlation_calculation(g.m, ex_data) #长期行业累积收入
    m_sum = pd.DataFrame(ex_data.iloc[-g.m:].mean()) #长期行业收入
    m_data = pd.concat([m_df,m_sum],axis = 1, sort=True)
    m_data['prediction'] = m_data[0] * m_data[g.m] #给出长期预测
        
    prediction = (s_data['prediction'] + m_data['prediction']) / 2 # 取短中期的平均值看法
    prediction = prediction.sort_values(ascending = False).iloc[-5:] # 取前5个最有可能反转的行业
    print(prediction)
    # 这一个月需要买入的行业
    g.industry_list = []
    for industry in prediction.index:
        g.industry_list.append(industry)

# 标的筛选函数：
def ETF_selection(context):
    pool = {'交通运输I': None, # 太短不传入
        '休闲服务I': None, #太短不传入
        '传媒I':'512980.XSHG', #传媒ETF
        '公用事业I': None, # 太短不传入
        '农林牧渔I':'159825.XSHE', #农业ETF
        '化工I':'516120.XSHG', # 化工50ETF
        '医药生物I':'159929.XSHE', #医药ETF
        '商业贸易I':None,
       '国防军工I':'512810.XSHG', # 军工ETF
       '家用电器I':None,
       '建筑材料I':'159944.XSHE', #材料ETF
       '建筑装饰I':None,
       '房地产I':'512200.XSHG', # 地产ETF
       '有色金属I':'512400.XSHG', #有色ETF
       '机械设备I':None,
       '汽车I':None,
       '煤炭I':'515220.XSHG', # 煤炭ETF
       '环保I':None,
       '电子I':'159997.XSHE',#电子ETF
       '电气设备I':None,
       '石油石化I':None,
       '纺织服装I':None,
       '综合I':None,
       '美容护理I':None,
       '计算机I':'512720.XSHG',#计算机ETF
       '轻工制造I':None,
       '通信I':'515880.XSHG', #通信ETF
       '钢铁I':'515210.XSHG', #钢铁ETF
       '银行I':'512800.XSHG', # 银行ETF
       '非银金融I':'159931.XSHE',#金融ETF
       '采掘I': None,
       '食品饮料I':'159843.XSHE'} #食品饮料ETF
    
    # 记录这个月需要买入的ETF或者股票：
    g.buy_dict = {}
    for industry in g.industry_list:
        if pool[industry]:
            g.buy_dict[industry] = pool[industry] # 则买入ETF
        else:
            industries = get_industries(name = "sw_l1", date = context.current_dt)
            code = industries[industries.name == industry].index[0]
            stocks = get_industry_stocks(code)
            
            #获取股票池
            df = get_fundamentals(query(valuation.code,valuation.pb_ratio,indicator.roe
            ).filter(valuation.code.in_(stocks)))
            #进行pb,roe大于0筛选
            df = df[(df['roe']>0) & (df['pb_ratio']>0)].sort_values('pb_ratio')
            #以股票名词作为index
            df.index = df['code'].values
            #取roe倒数
            df['1/roe'] = 1/df['roe']
            #获取综合得分
            df['point'] = df[['pb_ratio','1/roe']].rank().T.apply(f_sum)
            #按得分进行排序，取指定数量的股票
            df = df.sort_values('point')[:10]
            g.buy_dict[industry] = (list(df.index)) # 买入这个行业的10只价值股
        
               
#运行交易函数  
def trade(context):
    #卖出不在持仓中的股票
    for stock in context.portfolio.positions.keys():
        check = 0
        for code in g.buy_dict.values():
            #如果当前行业是ETF，但不是当前需要购买的，check加一
            if (type(code) == str) and (stock != code):
                check += 1
            #如果当前行业是股票池，且持有股票不在股票池里，check加一
            elif (type(code) == list) and (stock not in code):
                check += 1
        
        # 如果check的数量等于当前要买入的行业，则卖出持有的股票：        
        if check == len(g.buy_dict.values()):
            order_target(stock,0)
        
    #按行业分出该买入的
    cash = context.portfolio.available_cash / len(g.buy_dict.values())
    for code in g.buy_dict.values():
        # 如果是未持有的ETF，则买入：
        if (type(code) == str) and (code not in context.portfolio.positions.keys()):
            order_target_value(code,cash)
        
        #如果是股票池，则找出未买入的股票：
        elif (type(code) == list):
            for stock in code:
                if stock not in context.portfolio.positions.keys():
                    order_target_value(stock,cash/len(code))

#打分工具
def f_sum(x):
    return sum(x)

            
