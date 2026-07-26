#!/usr/bin/env python
# coding: utf-8

# In[1]:


from jqdata import *
import pandas as pd
import numpy as np
import datetime
from scipy import stats
warnings.filterwarnings("ignore")
from scipy.optimize import curve_fit
print('done')


# In[2]:


# 季度时期调用函数(1个最新季度和13个过往季度<==确保能有12个sample)：
def season_selection(end_date):
    year = int(end_date[:4])
    if int(end_date[5]) > 0:
        month = int(end_date[5:7])
    else:
        month = int(end_date[6])

    # 确认最近的季度时间，取当前月份的前一个季度（例如2/3月份则取去年12月4季度的数据）
    month_dict = {3:4,6:1,9:2,12:3}
    for m in month_dict.keys():
        if month <= m:
            start_month = month_dict[m]
            break
    if start_month != 4:
        start_year = year
        start_season = str(year) + 'q' + str(start_month)
    else:
        start_year = year - 1
        start_season = str(start_year) + 'q' + str(start_month)
    
    # 取出过后的13个季度，合并到一起作为取出的季度
    sample = []
    while len(sample) < 13:
        if start_month > 1:
            start_month -= 1
            season = str(start_year) + 'q' + str(start_month)
            sample.append(season)
        
        else:
            start_month = 4
            start_year -= 1
            season = str(start_year) + 'q' + str(start_month)
            sample.append(season)

    return start_season, sample


# In[3]:


# 转债成长因子（营业收入超额预期）：
def SUE_factoring(stock_list, end_date):
    # 取出过去14个季度的营业收入数据，计算最新季度数据对应过去数据的超预期准值（standardised）
    start_season, sample = season_selection(end_date)
    q = query(income.code,income.statDate,income.operating_revenue).filter(income.code.in_(stock_list))
    newest_profit = get_fundamentals(q,statDate = start_season)
    
    # 如果当前最新的数据还没有更新，则取sample里最新的
    if newest_profit.empty:
        newest_profit = get_fundamentals(q,statDate = sample[0])
        sample = sample[1:]
    
    # 然后取出12个最新的数据,计算过往平均值和标准差：
    sample_data = {}
    for date in sample[-12:]:
        sample_data[date] = get_fundamentals(q,statDate = date)
    sample_data = pd.concat(sample_data.values(), axis = 0)
    mean_data = sample_data.groupby('code').mean()
    mean_data.columns = ['mean']
    std_data = sample_data.groupby('code').std()
    std_data.columns = ['std']
    
    # 合并数据，计算成长因子——超额预期营业收入:
    newest_profit = newest_profit.merge(mean_data, on = 'code', how = 'left')
    newest_profit = newest_profit.merge(std_data, on = 'code', how = 'left')
    newest_profit['SUE_drift'] = (newest_profit['operating_revenue'] - newest_profit['mean']) / newest_profit['std']
    
    return newest_profit


# In[4]:


#估值合成因子计算函数:
def epbp_factoring(stock_list, end_date): 
    
    # 这里取的估值倒数都是最新季度的(这里数据是按天更新，但是无法取固定日期的数据，所以还是取最新季度日期的来避免使用未来数据)
    start_season, sample = season_selection(end_date)
    v = get_fundamentals(query(valuation).filter(valuation.code.in_(stock_list)),statDate = start_season)
    #
    if v.empty:
        v = get_fundamentals(query(valuation).filter(valuation.code.in_(stock_list)),statDate = sample[0])

    # 整理数据倒数
    #ep_ttm（用归母净利润TTM计算 的pe的倒数）
    v['ep_ttm'] = 1 / v['pe_ratio']
    #bp_lr（用最新的归母股东权益计算的pb的倒数）
    v['bp_lr'] = 1 / v['pb_ratio']
    
    #合并因子
    v = v.filter(['code','pubDate','ep_ttm','bp_lr'])
    v['epbp_factor'] = v['ep_ttm'] + v['bp_lr']
    
    return v


# In[5]:


# 长期动量计算函数 <==可转债的上涨空间由正股的收益预期所决定，这里取正股动量因子
def momentom_factoring(stock_list, end_date):
    # 初始字典，取出每只股票过去6个月，即126个交易日的总收益趋势：
    return_data = {}
    for stock in stock_list:
        price = get_price(security = stock, end_date = end_date, count = 126, fields = ['close'])
        returns = (price.iloc[-1]['close'] / price.iloc[0]['close']) - 1
        return_data[stock] = returns
    return_data = pd.DataFrame({'return_126D':return_data})
    
    return return_data


# In[6]:


#修正溢价率使用反比例函数计算
def premium_factoring(c_list, start_date, end_date):
    #首先先算出当日转股价值：
    fixed_data = {'code':[],'convert_list':[],'premium_list':[]}
    
    for b in c_list:
        convert = bond.run_query(query(bond.CONBOND_DAILY_CONVERT.date,bond.CONBOND_DAILY_CONVERT.code,
                            bond.CONBOND_DAILY_CONVERT.convert_premium_rate).filter(
            bond.CONBOND_DAILY_CONVERT.code == b,
            bond.CONBOND_DAILY_CONVERT.date <= end_date,
            bond.CONBOND_DAILY_CONVERT.date >= start_date))

        # 取最近有溢价率的日期作为记录期
        c_date = convert['date'].iloc[-1]

        #取出对应转债价格
        price = bond.run_query(query(bond.CONBOND_DAILY_PRICE.date,bond.CONBOND_DAILY_PRICE.code,
                                     bond.CONBOND_DAILY_PRICE.close).filter(
            bond.CONBOND_DAILY_PRICE.code == b,
            bond.CONBOND_DAILY_PRICE.date == c_date))

        # 计算当前转股价值：
        convert_premium = convert['convert_premium_rate'].iloc[-1]
        convert_value = price['close'][0] / (convert_premium + 1)
        
        # 加入到数据list
        if convert_premium and convert_value:
            fixed_data['code'].append(b)
            fixed_data['premium_list'].append(convert_premium)
            fixed_data['convert_list'].append(convert_value)
    
    # 初始回归数据
    fixed_data = pd.DataFrame(fixed_data)
    x = np.array(fixed_data['convert_list']) #转股价值作为自变量
    y = np.array(fixed_data['premium_list']) #溢价率作为反比力函数（来表示负相关性）
    
    # 使用scipy的curvefit计算反比函数的回归值(这里的residual函数会自动生成，无需考虑)
    params = np.array([1,1]) # intial_guess
    def funcinv(x, a, b):
        return (a / x) + b # 这里的反比例是转股价值的提升是溢价率的下降
    res = curve_fit(funcinv, x, y, params)

    # 拟合修正溢价率:
    a = res[0][0]
    b = res[0][1]
    fixed_data['fixed_premium'] = (a / fixed_data['convert_list']) + b
    
    return fixed_data


# In[7]:


# 交易量因子（转债成交的强弱变化函数）（cv_volume_NDCMN）
def volume_factoring(c_list, end_date, year, month, day):
    '''短期平均效益量相对于长期平均交易量的变化率'''
    
    # 取出两周相对于三个月的成交量比例：
    ratio_data = {}
    short_date = datetime.datetime(year,month,day) - datetime.timedelta(days = 14) #短期为2星期
    long_date = datetime.datetime(year,month,day) - datetime.timedelta(days = 90) # 中期为3个月
    for b in c_list:
        short_volume = bond.run_query(query(bond.CONBOND_DAILY_PRICE.date,bond.CONBOND_DAILY_PRICE.code,
                        bond.CONBOND_DAILY_PRICE.volume).filter(
            bond.CONBOND_DAILY_PRICE.code == b,
            bond.CONBOND_DAILY_PRICE.date >= short_date,
            bond.CONBOND_DAILY_PRICE.date <= end_date))
        short_volume = short_volume['volume'].sum() # 取交易量总和
        
        long_volume = bond.run_query(query(bond.CONBOND_DAILY_PRICE.date,bond.CONBOND_DAILY_PRICE.code,
                        bond.CONBOND_DAILY_PRICE.volume).filter(
            bond.CONBOND_DAILY_PRICE.code == b,
            bond.CONBOND_DAILY_PRICE.date >= long_date,
            bond.CONBOND_DAILY_PRICE.date <= end_date))
        long_volume = long_volume['volume'].sum()  # 取交易量总和
        
        # 记录比例：
        ratio_data[b] = short_volume / long_volume
    
    ratio_data = pd.DataFrame({"cv_volume_NDCMN": ratio_data})   
    return ratio_data


# In[18]:


# 高位转折因子（避免过度使用动量因子）：
def skew_factoring(c_list, end_date, year, month, day):
    '''成交量加权的价格偏度因子，识别出近期价格分布极端左偏的转债'''
    
    exchange_code = {}
    skewness_data = {}
    short_date = datetime.datetime(year,month,day) - datetime.timedelta(days = 90) # 三月前日期
    long_date = datetime.datetime(year,month,day) - datetime.timedelta(days = 183) # 六月前日期
    
    # 取出3/6月的收盘数据
    for b in c_list:
        short_volume = bond.run_query(query(bond.CONBOND_DAILY_PRICE.date,bond.CONBOND_DAILY_PRICE.code,
                        bond.CONBOND_DAILY_PRICE.volume, bond.CONBOND_DAILY_PRICE.close,
                                            bond.CONBOND_DAILY_PRICE.exchange_code).filter(
            bond.CONBOND_DAILY_PRICE.code == b,
            bond.CONBOND_DAILY_PRICE.date >= short_date,
            bond.CONBOND_DAILY_PRICE.date <= end_date))
        
        long_volume = bond.run_query(query(bond.CONBOND_DAILY_PRICE.date,bond.CONBOND_DAILY_PRICE.code,
                        bond.CONBOND_DAILY_PRICE.volume, bond.CONBOND_DAILY_PRICE.close).filter(
            bond.CONBOND_DAILY_PRICE.code == b,
            bond.CONBOND_DAILY_PRICE.date >= long_date,
            bond.CONBOND_DAILY_PRICE.date <= end_date))
        
        # 加权取出skewness
        short_volume['v_close'] = short_volume['volume'] * short_volume['close']
        long_volume['v_close'] = long_volume['volume'] * long_volume['close']
        s_skew = short_volume['v_close'].skew()
        l_skew = long_volume['v_close'].skew()
        skewness_data[b] = (s_skew + l_skew) / 2
        
        # 取出交易后缀
        exchange_code[b] = short_volume.exchange_code[0]
        
    skewness_data = pd.DataFrame({'exchange_code':exchange_code, "cv_close_skew_63D": skewness_data})   
    return skewness_data


# In[ ]:


# 择券主函数：
def convertible_selection(start_date, end_date):
    # 筛选出当前有转股溢价率数据的可转债
    convert = bond.run_query(query(bond.CONBOND_DAILY_CONVERT).filter(
        bond.CONBOND_DAILY_CONVERT.date >= start_date,
        bond.CONBOND_DAILY_CONVERT.date <= end_date))
    convert = convert.groupby('code').mean().filter(['convert_premium_rate'])
    c_list = list(convert.index)

    # 筛选出具有正股信息的转债
    c_stock = bond.run_query(query(bond.CONBOND_BASIC_INFO.code,
                                 bond.CONBOND_BASIC_INFO.company_code).filter(
        bond.CONBOND_BASIC_INFO.convert_code != None,
        bond.CONBOND_BASIC_INFO.code.in_(c_list)))
    
    # 避开房地产行业的可转债，以免买入债低不可信的转债：
    industry = get_industry(list(c_stock.company_code), date = end_date)
    stock_list = []
    for stock in list(c_stock.company_code):
        if 'sw_l1' in industry[stock].keys():
            if industry[stock]['sw_l1']['industry_code'] != '801180':
                stock_list.append(stock)

    #筛选出到期事件大于一年的转债 & 上市多于一周的转债，来避免上市初期成交量的显著交易差：
    year = int(end_date[:4])
    if int(end_date[5]) > 0:
        month = int(end_date[5:7])
    else:
        month = int(end_date[6])
    if int(end_date[-2])>0:
        day = int(end_date[-2:0])
    else:
        day = int(end_date[-1])
    forward_ending = datetime.datetime(year,month,day) + datetime.timedelta(days = 365)
    issue_limit = datetime.datetime(year,month,day) - datetime.timedelta(days = 7)
    maturity = bond.run_query(query(bond.CONBOND_BASIC_INFO).filter(
        bond.CONBOND_BASIC_INFO.maturity_date >= forward_ending,
        bond.CONBOND_BASIC_INFO.issue_start_date < issue_limit,
        bond.CONBOND_BASIC_INFO.code.in_(c_list)))
    c_list = list(maturity.code)
    
    # 转债成长因子(与转债收益成正相关,越高排名越大)
    growth_factor = SUE_factoring(stock_list, end_date)
    growth_factor = growth_factor.filter(['code','SUE_drift'])
    growth_factor.columns = ['company_code','SUE_drift']
    growth_factor['growth_rank'] = growth_factor['SUE_drift'].rank()
    
    # 合成估值因子（与转债收益成负相关,越高排名越低）
    epbp_factor = epbp_factoring(stock_list, end_date)
    epbp_factor = epbp_factor.filter(['code','epbp_factor'])
    epbp_factor.columns = ['company_code','epbp_factor']
    epbp_factor['value_rank'] = epbp_factor['epbp_factor'].rank(ascending = False)
    
    # 长期动量因子（与转债收益成正相关,越高排名越大）
    momentom_factor = momentom_factoring(stock_list, end_date)
    momentom_factor = momentom_factor.reset_index()
    momentom_factor.columns = ['company_code','return_126D']
    momentom_factor['momentom_rank'] = momentom_factor['return_126D'].rank()
    
    # 修正溢价率因子(与转债收益成负相关,越高排名越低）
    convert_premium_factor = premium_factoring(c_list, start_date, end_date)
    convert_premium_factor = convert_premium_factor.filter(['code','fixed_premium'])
    convert_premium_factor['convert_premium_rank'] = convert_premium_factor['fixed_premium'].rank(ascending = False)
    
    # 交易量因子（与转债收益成正相关,越高排名越大）
    volume_factor = volume_factoring(c_list, end_date, year, month, day)
    volume_factor = volume_factor.reset_index()
    volume_factor.columns = ['code','cv_volume_NDCMN']
    volume_factor['volume_rank'] = volume_factor['cv_volume_NDCMN'].rank()
    
    # 高位转折因子（与转债收益成负相关,越高排名越低）
    reverse_factor = skew_factoring(c_list, end_date, year, month, day)
    reverse_factor = reverse_factor.reset_index()
    reverse_factor.columns = ['code','exchange_code','cv_close_skew_63D']
    reverse_factor['reverse_rank'] = reverse_factor['cv_close_skew_63D'].rank(ascending = False)
    
    # 整理合并所有因子，按因子排名进行筛选：
    data = maturity.filter(['code','company_code'])
    data = data.merge(growth_factor, on = 'company_code', how = 'left')
    data = data.merge(epbp_factor, on = 'company_code', how = 'left')
    data = data.merge(momentom_factor, on = 'company_code', how = 'left')
    data = data.merge(convert_premium_factor, on = 'code', how = 'left')
    data = data.merge(volume_factor, on = 'code', how = 'left')
    data = data.merge(reverse_factor, on = 'code', how = 'left')

    # 取出总体因子排名靠20的转债
    data['points'] = data['growth_rank'] + data['value_rank'] + data['momentom_rank'] + data['convert_premium_rank'] + data['volume_rank'] + data['reverse_rank']
    data = data.sort_values('points', ascending = False)
    data['code'] = data['code'] +'.'+ data['exchange_code']
    buy_list = list(data['code'].iloc[:20])
    
    return buy_list


# In[20]:


# 运行择券函数
start_date = '2022-01-01'
end_date = '2022-02-01'
buy_list = convertible_selection(start_date, end_date)
print('可转债因子筛选结果前20名为: %s'%  buy_list)


# In[ ]:





# In[21]:


# 双低策略的整体思路
def basic_selection(start_date, end_date, bond_preference = 0.5, stock_preference = 0.5):
    # 筛选出当前有转股溢价率数据的可转债
    convert = bond.run_query(query(bond.CONBOND_DAILY_CONVERT).filter(
        bond.CONBOND_DAILY_CONVERT.date >= start_date,
        bond.CONBOND_DAILY_CONVERT.date <= end_date))
    convert = convert.groupby('code').mean().filter(['convert_premium_rate'])
    c_list = list(convert.index)

    #筛选出到期事件大于一年的转债 & 上市多于一周的转债，来避免上市初期成交量的显著交易差：
    year = int(end_date[:4])
    if int(end_date[5]) > 0:
        month = int(end_date[5:7])
    else:
        month = int(end_date[6])
    if int(end_date[-2])>0:
        day = int(end_date[-2:0])
    else:
        day = int(end_date[-1])
    forward_ending = datetime.datetime(year,month,day) + datetime.timedelta(days = 365)
    issue_limit = datetime.datetime(year,month,day) - datetime.timedelta(days = 5)
    maturity = bond.run_query(query(bond.CONBOND_BASIC_INFO).filter(
        bond.CONBOND_BASIC_INFO.maturity_date >= forward_ending,
        bond.CONBOND_BASIC_INFO.issue_start_date < issue_limit,
        bond.CONBOND_BASIC_INFO.code.in_(c_list)))
    c_list = list(maturity.code)

    # 避开房地产行业的可转债，以免买入债低不可信的转债：
    c_stock = bond.run_query(query(bond.CONBOND_BASIC_INFO.code,
                                 bond.CONBOND_BASIC_INFO.company_code).filter(
        bond.CONBOND_BASIC_INFO.convert_code != None,
        bond.CONBOND_BASIC_INFO.code.in_(c_list)))
    
    industry = get_industry(list(c_stock.company_code), date = end_date)
    stock_list = []
    for stock in list(c_stock.company_code):
        if 'sw_l1' in industry[stock].keys():
            if industry[stock]['sw_l1']['industry_code'] != '801180':
                stock_list.append(stock)
                
    #正股筛选，避免买入垃圾股 (正股PB不可低于1, PE ratio大于10，增加正股在牛市上涨的机率）         
    v = get_fundamentals(query(valuation.code,valuation.pb_ratio,valuation.pe_ratio).filter(
        valuation.code.in_(stock_list),
        valuation.pb_ratio > 1,
        valuation.pe_ratio >= 10))
    v.columns = ['company_code','pb_ratio','pe_ratio']
    c_list = list(v.merge(c_stock, on = 'company_code', how = 'left').code)
    
    #获取可转债价格，暂定低价格为130以内的转债
    p_dict = {}
    exchange_code = {}
    for b in c_list:
        p = bond.run_query(query(bond.CONBOND_DAILY_PRICE).filter(
            bond.CONBOND_DAILY_PRICE.code == b,
            bond.CONBOND_DAILY_PRICE.date >= start_date,
            bond.CONBOND_DAILY_PRICE.date <= end_date))
        # 如果月度收盘价未曾达到过130（即还有一定的稳定收入空间），则记录上个月度的平均收盘价：
        if p.max()['close'] < 130:
            p_dict[b] = p.mean()['close']
            exchange_code[b] = p.exchange_code[0]
    price = pd.DataFrame({'close':p_dict,'exchange_code':exchange_code}).reset_index()
    price.columns = ['code','close','exchange_code']

    # 合并所有信息：
    convert = convert.reset_index()
    data = price.merge(convert, on = 'code', how = 'left')
    
    # 双低指数 = 收盘价*债性偏好 + 转鼓溢价率*股性偏好
    data['points'] = (data['close'] * bond_preference) + (data['convert_premium_rate'] * stock_preference)
    data = data.sort_values('points', ascending = True)
    
    # 取前20名转债points最低的：
    data['code'] = data['code'] +'.'+ data['exchange_code']
    buy_list = list(data.iloc[:20].code)
    
    # 取20名-30名之间作为日换手backup：
    backup_list = list(data.iloc[20:30].code)
    
    return buy_list, backup_list


# In[22]:


# 月度根据上月交易数据进行分析，并筛选出前20名双低转债：
start_date = '2022-01-01'
end_date = '2022-02-01'

# 偏股转债选择(在牛市/或转债市场存在泡沫时，债性偏弱，策略应该注重股性)
buy_list, backup_list = basic_selection(start_date, end_date,bond_preference = 0.3, stock_preference = 0.7)
print('月度开始买入: %s'%  buy_list)


# In[23]:


# 日监督函数：
def daily_prevention(buy_list, backup_list, current_date):
    #1.5个准差值的布林带初始设置
    n_std = 1.5 
    
    # 取单纯的代码：
    buy_code = [code[:6] for code in buy_list]
    backup_code = [code[:6] for code in backup_list]
    
    #取日期
    year = int(current_date[:4])
    if int(current_date[5]) > 0:
        month = int(current_date[5:7])
    else:
        month = int(current_date[6])
    if int(current_date[-2])>0:
        day = int(current_date[-2:0])
    else:
        day = int(current_date[-1])
    
    # 取出滚动30天的转债溢价率以及统计数据
    s_date = datetime.datetime(year,month,day) - datetime.timedelta(days = 30)
    convert = bond.run_query(query(bond.CONBOND_DAILY_CONVERT).filter(
        bond.CONBOND_DAILY_CONVERT.code.in_(buy_code),
        bond.CONBOND_DAILY_CONVERT.date >= s_date,
        bond.CONBOND_DAILY_CONVERT.date < current_date))
    exchange_code = pd.DataFrame(convert.groupby('code').max()['exchange_code'])
    std = pd.DataFrame(convert.groupby('code').std()['convert_premium_rate']).dropna()
    mean = pd.DataFrame(convert.groupby('code').mean()['convert_premium_rate'])
    
    # 计算当日的布林带作为溢价过高的触发条件（只需upper）
    convert = std.merge(mean, on = 'code', how = 'left')
    convert.columns = ['standard_deviation','mean']
    convert['upper_threshold'] = convert['mean'] +  convert['standard_deviation'] * n_std
    
    # 布林带若某日的转债溢价率大于n个准值差，则视为双低失效，卖出：
    current_convert = bond.run_query(query(bond.CONBOND_DAILY_CONVERT).filter(
        bond.CONBOND_DAILY_CONVERT.code.in_(buy_code),
        bond.CONBOND_DAILY_CONVERT.date == current_date))
    current_convert = pd.DataFrame(current_convert.groupby('code').max()['convert_premium_rate'])
    convert = convert.merge(current_convert, on = 'code', how = 'left')
    convert = convert.merge(exchange_code, on = 'code', how = 'left')
    bail_out = convert[convert['convert_premium_rate'] >= convert['upper_threshold']]
    
    if not bail_out.empty:
        bail_out = bail_out.reset_index()
        bail_out['exchange_code'] = bail_out['code']+'.'+bail_out['exchange_code']
        bail_out = list(bail_out.exchange_code)
        print('双低策略失效的转债为: %s' % bail_out)
        print('换手持有备用转债: %s' % backup_list[:len(bail_out)])

current_date = '2022-02-07'
daily_prevention(buy_list, backup_list, current_date)


# In[ ]:





# In[24]:


# 验证关联性函数（溢价率飙升和下一周交易日的转债价格的下跌幅度）
def correlation_calculation(year):
    #初始相关性数据
    corr_dict = {'correlation':[],'p_value':[]}
    
    # 初始月数据日期
    date_list = []
    for month in range(1,13):
        date_list.append(datetime.datetime(year,month,1))


    # 取出当年每个月份的相关性：
    for e_date in date_list:
        s_date = date_list[0] - datetime.timedelta(days = 30)

        # 取出当月的溢价率
        convert_data = bond.run_query(query(bond.CONBOND_DAILY_CONVERT).filter(
                bond.CONBOND_DAILY_CONVERT.date >= s_date,
                bond.CONBOND_DAILY_CONVERT.date < e_date))
        convert_data = convert_data.filter(['date','code','convert_premium_rate'])
        convert = convert_data.groupby('code').mean().filter(['convert_premium_rate'])
        ex_code = list(convert.index)

        # 对应取出当月转债的价格
        corr_data = {}
        for b in ex_code:
            price_data = bond.run_query(query(bond.CONBOND_DAILY_PRICE).filter(
                        bond.CONBOND_DAILY_PRICE.code == b,
                        bond.CONBOND_DAILY_PRICE.date >= s_date,
                        bond.CONBOND_DAILY_PRICE.date < e_date))
            # lag取出溢价率暴增后转债收益
            price_data = price_data.filter(['date','close'])
            future_data = price_data.shift(-5).dropna()
            price_data['price_change'] = ((future_data['close']/price_data['close']) - 1) * 100

            # 合并信息加入dict
            c_data = convert_data[convert_data['code'] == b]
            c_data = c_data.merge(price_data, on = 'date', how = 'left').dropna()
            corr_data[b] = c_data

        # 总体验证溢价率超过50%下一个交易日的转债收益：
        corr_data = pd.concat(corr_data.values(), axis = 0, sort = False)
        extreme_data = corr_data[corr_data['convert_premium_rate'] > 50]
        x = extreme_data['convert_premium_rate']
        y = extreme_data['price_change']
        
        # 计入数据：
        corr_dict['correlation'].append(stats.pearsonr(x,y)[0])
        corr_dict['p_value'].append(stats.pearsonr(x,y)[1])
        
    return corr_dict


# In[25]:


# 依次取出过去4年的数据：
demonstration = {}
for year in range(2017,2022):
    demonstration[year] = pd.DataFrame(correlation_calculation(year))
    print('done')
demonstration = pd.concat(demonstration.values(), axis = 0)


# In[27]:


# 数据显示，p_value过高，correlation且为正值，
# 接下来一个星期的收益和溢价率的暴增不具有显著相关性，可转债本身的价格在接下来的交易日并没有具体的走向
# 预测转债接下来的价格走向应该在更微观的思路去考虑？
demonstration.dropna().mean()


# In[ ]:




