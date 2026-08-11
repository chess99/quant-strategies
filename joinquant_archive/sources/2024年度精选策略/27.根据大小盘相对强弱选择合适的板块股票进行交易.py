# 克隆自聚宽文章：https://www.joinquant.com/post/43540
# 标题：根据大小盘相对强弱选择合适的板块股票进行交易
# 作者：Jacobb75

# 克隆自聚宽文章：https://www.joinquant.com/post/10246
# 标题：【量化课堂】RSRS(阻力支撑相对强度)择时策略（上）
# 作者：JoinQuant量化课堂

# 克隆自聚宽文章：https://www.joinquant.com/view/community/detail/28dc6d6605ce7f7471ff05904ccf046f
# 标题：【量化课堂】RSRS(阻力支撑相对强度)择时策略（xia）
# 作者：JoinQuant量化课堂

#导入函数库
from jqdata import *
from jqfactor import get_factor_values
import numpy as np
import pandas as pd

#初始化函数 
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('399317.XSHE')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 将滑点设置为0.02
    set_slippage(FixedSlippage(0.02))
    # 设置交易成本万分之5
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0005, close_commission=0.0005, close_today_commission=0, min_commission=5),type='fund')
    # 过滤order中低于error级别的日志
    log.set_level('system', 'error')
    #指数池
    g.index_pool = [
        '000016.XSHG', #上证50
        '399303.XSHE', #国证2000
    ]
    #动量轮动参数
    g.momentum_day = 89 #判断动量所需天数
    g.position = 1 #仓位

    g.stock_num = 10 #持仓数（如果切换到大盘股，则初始10个，之后根据每期选择出来的股票数量动态调整）
    g.stock_num_small = 30 #持仓数(如果切换到小盘股，持仓数量最多30个)
    g.length = len(get_stock_list_before_open(context)[0])
    
    # 设置交易时间，每月运行
    run_monthly(my_sell, monthday=-10, time='11:00', reference_security='399317.XSHE')# 卖出
    run_monthly(my_buy, monthday=-1, time='11:15', reference_security='399317.XSHE')# 买入
    
    
    
# 模型主体运行函数
def my_select(context):
    # 获取选股列表并过滤掉:st,st*,退市,涨停,跌停,停牌
    check_out_list,g.stock_num = get_stock_list_before_open(context)
    #log.info('今日自选股:%s' % check_out_list)
    log.info('今日股票数量:%s' % g.stock_num)
    return check_out_list


def my_sell(context):
    # 获取选股列表并过滤掉:st,st*,退市,涨停,跌停,停牌
    adjust_position_sell(context, my_select(context))
    
def my_buy(context):
    # 获取选股列表并过滤掉:st,st*,退市,涨停,跌停,停牌
    adjust_position_buy(context, my_select(context))
    
    
    
#0 辅助函数
# 获取前n个单位时间当时的收盘价
def get_close_price(code, n, unit='1d'):
    return attribute_history(code, n, unit, 'close', df=False)['close'][0]
    
def close_position(code):
    order = order_target_value(code, 0) # 可能会因停牌或跌停失败
    if order != None and order.status == OrderStatus.held:
        g.sold_stock[code] = 0



#1-1 根据动量判断市场风格
def get_index_signal(index_pool):
    score_list = []
    for index in index_pool:
        #分别计算大小盘指数一段时间内预期收益率（最低价格和时间的线性回归斜率*相关系数）的大小，大的强
        data = attribute_history(index, g.momentum_day, '1d', ['low'])
        y = data['log'] = np.log(data.low)
        x = data['num'] = np.arange(data.log.size)
        slope, intercept = np.polyfit(x, y, 1)
        annualized_returns = math.pow(math.exp(slope), 250) - 1
        r_squared = 1 - (sum((y - (slope * x + intercept))**2) / ((len(y) - 1) * np.var(y, ddof=1)))
        score = annualized_returns * r_squared
        score_list.append(score)
    index_dict=dict(zip(index_pool, score_list))
    print(index_dict)
    sort_list=sorted(index_dict.items(), key=lambda item:item[1], reverse=True) #True为降序
    code_list=[]
    for i in range((len(index_pool))):
        code_list.append(sort_list[i][0])
    best_index = code_list[0]
    return best_index
    
    
#1-2 去掉次新，创业，科创，st
def filter_stock(context):
    curr_data = get_current_data()
    yesterday = context.previous_date
    
    # 过滤次新股
    #by_date = yesterday
    #by_date = datetime.timedelta(days=1200)
    by_date = yesterday - datetime.timedelta(days=1200)  # 三年
    initial_list = get_all_securities(date=by_date).index.tolist()


    # 0. 过滤创业板，科创板，st，今天涨跌停的，停牌的
    filtered_list = [stock for stock in initial_list if not (
            (curr_data[stock].day_open == curr_data[stock].high_limit) or
            (curr_data[stock].day_open == curr_data[stock].low_limit) or
            curr_data[stock].paused or
            #curr_data[stock].is_st
            ('ST' in curr_data[stock].name) or
            ('*' in curr_data[stock].name) or
            ('退' in curr_data[stock].name) or
            #(stock.startswith('300')) or
            (stock.startswith('688')) 
            #(stock.startswith('002'))
    )]
    
    return filtered_list
    
    
#1-3 大盘价值成长风格
def get_value_stock_list(context):
    print("大盘价值成长风格")
    df_stocknum = pd.DataFrame(columns=['过滤后的股票'])
    yesterday = context.previous_date

    initial_list = filter_stock(context)
    #initial_list = get_index_stocks('000300.XSHG',date=yesterday)

    # 1，流通市值由高到低且≧市场中位数（大盘）
    df1 = get_fundamentals(query(valuation.circulating_cap,
                                 balance.total_current_assets,
                                 balance.total_current_liability,
                                 indicator.inc_return,
                                 income.np_parent_company_owners,
                                 valuation.code).
                           filter(valuation.code.in_(initial_list)),
                           date=context.previous_date)
                           
    df1['current'] = df1['total_current_assets']/df1['total_current_liability']
    current_median = df1['current'].median()
    roe_median = df1['inc_return'].median()
    
    A=[one for one in df1['np_parent_company_owners']  if one>=0]
    np_parent_company_owners_median = np.median(A)

    df1 = df1.sort_values('circulating_cap',ascending=False)
    list_1 = list(df1.code)[:int(0.5*len(list(df1.code)))]
    df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(list_1)}, ignore_index=True)

  
    # 2，最近一季流动比率≧市场中位数（现时经营稳健性）
    df2 = get_fundamentals(query(balance.total_current_assets,
                                 balance.total_current_liability,
                                 valuation.code).
                           filter(valuation.code.in_(list_1)),
                           date=context.previous_date)
    
    df2['current'] = df2['total_current_assets']/df2['total_current_liability']                       
    list_2 = list(df2[df2['current']>current_median].code)
    df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(list_2)}, ignore_index=True)
    
    
    # 3，最近一季扣非ROE≧市场中位数（现时价值性）
    df3 = get_fundamentals(query(indicator.inc_return,
                                 valuation.code).
                           filter(valuation.code.in_(list_2)),
                           date=context.previous_date)
    
    df3 = df3.sort_values('inc_return',ascending=False)
    list_3 = list(df3[df3['inc_return']>roe_median].code)
    df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(list_3)}, ignore_index=True)

    #4.近4个季度自由现金流量均为正值。（持续经营稳定性）
    df4 = get_history_fundamentals(
        list_3,
        fields=[indicator.code, 
                cash_flow.net_operate_cash_flow,
                cash_flow.net_invest_cash_flow,
                cash_flow.fix_intan_other_asset_acqui_cash,
                cash_flow.fix_intan_other_asset_dispo_cash],
        watch_date=yesterday,
        count=4,
        interval='1q'
    ).dropna()

    #df4['FCF'] = df4['net_operate_cash_flow']-df4['net_invest_cash_flow']
    df4['FCF'] = df4['net_operate_cash_flow']- df4['fix_intan_other_asset_acqui_cash']

   
    s_delta_avg = df4.groupby('code')['FCF'].apply(
        lambda x: x.min()>0 
        #lambda x: x.iloc[3]  - x.mean() if len(x) == 4 else 0.0 
        #lambda x: x.iloc[11]  - x.mean() if len(x) == 12 else 0.0 
    ).sort_values(
        ascending=False
    )
    
    list_4 = list(s_delta_avg[s_delta_avg>0].index)
    df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(list_4)}, ignore_index=True)
    
    # 5.近四季营业利润成长率大于10%（持续成长性）
    df5 = get_history_fundamentals(
        list_4,
        fields=[indicator.code, indicator.inc_operation_profit_year_on_year],
        watch_date=yesterday,
        count=4,
        interval='1q'
    ).dropna()
   
    s_delta_avg = df5.groupby('code')['inc_operation_profit_year_on_year'].apply(
        lambda x: x.min()>10
        #lambda x: x.iloc[3]  - x.mean() if len(x) == 4 else 0.0 
        #lambda x: x.iloc[11]  - x.mean() if len(x) == 12 else 0.0 
    ).sort_values(
        ascending=False
    )
    
    list_5 = list(s_delta_avg[s_delta_avg>0].index)
    df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(list_5)}, ignore_index=True)
    
    # 6.连续4个季度归母净利润都大于行业2倍中位数（持续价值性）
    df6 = get_history_fundamentals(
        list_5,
        fields=[indicator.code, income.np_parent_company_owners],
        watch_date=yesterday,
        count=4,
        interval='1q'
    ).dropna()
   
    s_delta_avg = df6.groupby('code')['np_parent_company_owners'].apply(
        lambda x: x.min()> 2 * np_parent_company_owners_median
        #lambda x: x.iloc[3]  - x.mean() if len(x) == 4 else 0.0 
        #lambda x: x.iloc[11]  - x.mean() if len(x) == 12 else 0.0 
    ).sort_values(
        ascending=False
    )
    
    list_6 = list(s_delta_avg[s_delta_avg>0].index)
    #list_6 = list(s_delta_avg[:int(0.5 * len(s_delta_avg))].index)
    df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(list_6)}, ignore_index=True)
    
    # 7.按市净率选低的
    df7 = get_fundamentals(query(valuation.pb_ratio,
                                 valuation.code).
                           filter(valuation.code.in_(list_6)),
                           date=context.previous_date)
    
    df7 = df7.sort_values('pb_ratio',ascending=True)
    list_7 = list(df7[:g.stock_num].code)
    df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(list_7)}, ignore_index=True)
    
    print(df_stocknum)    
    
    stock_list = list_7[:g.stock_num]
    return stock_list,len(list_6)



#1-4 小盘业绩炒作风格

def get_growth_stock_list(context):
    print("小盘业绩炒作风格")
    dt_last = context.previous_date
    initial_list = filter_stock(context)
    #initial_list = get_index_stocks('399303.XSHE',date=yesterday)  

    # all stocks
    df_stocknum = pd.DataFrame(columns=['当前符合条件股票数量'])
  
    df = get_fundamentals(query(
            valuation.code
        ).filter(
            valuation.code.in_(initial_list),
            #valuation.code.in_(list(s_delta_avg[int(0 * len(s_delta_avg)):int(.5 * len(s_delta_avg))].index)),
            valuation.pb_ratio > 0,#市净率>0
            indicator.inc_return > 0, #indicator.inc_return < 0,#净资产收益率>0
            indicator.inc_total_revenue_year_on_year > 0,#营业总收入同比增长率>0
            indicator.inc_net_profit_year_on_year > 0,#净利润同比增长率>0
            indicator.ocf_to_operating_profit > 5,#经营活动产生的现金流量净额/经营活动净收益>5
        ).order_by(
            valuation.market_cap.asc()#市值由小到大排列
		))

    choice = list(df.code)[int(0 * len(list(df.code))): (int(0 * len(list(df.code))) + g.stock_num_small)]
    #choice = df[5 :5 + g.stock_num]
    #choice = choice[::-1]
    df_stocknum = df_stocknum.append({'当前符合条件股票数量': len(df)}, ignore_index=True)
    
    return choice,len(choice)


#2-1 开盘前打印自选股
def get_stock_list_before_open(context):
    index_signal = get_index_signal(g.index_pool)
    if index_signal == '000016.XSHG':
        stock_list,stock_num = get_value_stock_list(context)
    elif index_signal == '399303.XSHE':
        stock_list,stock_num = get_growth_stock_list(context)
        stock_num = g.stock_num_small#(小盘股拿30个最多)
        
    g.stock_list = stock_list
    g.stock_num = stock_num
    #print('今日自选股:{}'.format(stock_list[:g.stock_num]))
    
    return g.stock_list,g.stock_num
    

#交易
def adjust_position_sell(context, buy_stocks):
    index_signal = get_index_signal(g.index_pool)
    for stock in context.portfolio.positions:
            if stock in buy_stocks:
                current_data = get_current_data()
                now_price = current_data[stock].last_price
                open_price = current_data[stock].day_open
                close_data_1d =get_bars(stock, end_dt=context.current_dt, count=2,fields=['close', 'high','volume'], include_now=True)
                time1 = get_price(stock, count = 2, end_date=context.previous_date).index[0].strftime('%Y-%m-%d')
                time2 = context.portfolio.positions[stock].init_time.strftime('%Y-%m-%d')     
                
                if close_data_1d['high'][-1]>=context.portfolio.positions[stock].avg_cost*1.3 and \
                   (close_data_1d['high'][-1]-now_price)>= context.portfolio.positions[stock].avg_cost*0.05:
                       
                    p = context.portfolio.positions[stock].total_amount * 0.2
                    order_target(stock, p)
                    
                    log.info('收益大于30%后，回撤大于5%时平80%的仓位'+str(stock)+str(get_security_info(stock).display_name))
                    
                if  index_signal == '000016.XSHG' and now_price < context.portfolio.positions[stock].avg_cost*0.85:
                    order_target(stock, 0)   
                    log.info('^^^^^^^^^^^^大盘股收益小于等于-15%直接平仓,止损^^^^^^^^^^^^'+str(stock)+str(get_security_info(stock).display_name))  
                
                if  index_signal == '399303.XSHE' and now_price < context.portfolio.positions[stock].avg_cost*0.95:
                    order_target(stock, 0)   
                    log.info('^^^^^^^^^^^^小盘股收益小于等于-5%直接平仓,止损^^^^^^^^^^^^'+str(stock)+str(get_security_info(stock).display_name))  
                    
            if stock not in buy_stocks:
                order_target(stock,0)
                log.info('持仓不在股票池中，平仓 '+str(stock)+str(get_security_info(stock).display_name)) 
                
                

def adjust_position_buy(context, buy_stocks):                
    position_count = len(context.portfolio.positions)
    if g.stock_num >= position_count:
        #value = context.subportfolios[0].cash * g.position / (g.stock_num - position_count)#每只股票的预期买入的价值
        
        for stock in buy_stocks:
            #value = context.subportfolios[0].cash * g.position * (g.stock_num - position_count) / sum(range(1,g.stock_num - position_count+1))#每只股票预期买入的价值并非等权重，排在前边的权重高
            #value = context.subportfolios[0].total_value * (g.stock_num - buy_stocks.index(stock)) / sum(range(g.stock_num +1))
            #value = context.subportfolios[0].total_value * 2 / (g.stock_num + buy_stocks.index(stock))
            psize = context.portfolio.total_value * 2 / (g.stock_num + 4 + buy_stocks.index(stock))

            
            #计算股票的p值（50日均高低开收价格为一个随机变量，这个随机变量目前偏离该分布的程度）；低的股票可以适当多买，高的适当少买
            j = []
            G = get_bars(stock, 1, '1d', ['high','low','open','close'],  end_dt=context.current_dt,include_now=True)
            r = np.mean(list(G[0]))
            H = get_bars(stock, 50, '1d', ['high','low','open','close'],  end_dt=context.current_dt,include_now=True)
        
            for a in H:
                k = list(a)
                q = np.mean(k)
                j.append(q)
        
            p = (r - np.mean(j))/np.std(j)#这个随机变量理论上服从t(5)分布，5%单侧检验临界值选2.13，10%单侧检验临界值1.53
        
            #根据p值调整股票的仓位，每只股票预期买入的价值为value
            #目前价格落在10%分位数之下，即认为超卖，可以多买；落在5%分位数以上认为超买，少买写
            
            if context.portfolio.available_cash < psize:
                break
                
            if stock not in context.portfolio.positions:
                if p < -2:
                    log.info('短期超卖，多买点（150%预期仓位）'+str(stock)+str(get_security_info(stock).display_name))
                    order_target_value(stock, 1.5 * psize)#所有股票都短期超卖？太罕见了，这个情况我就没考虑
   
                elif p > 2:
                    log.info('短期超买，少买点（50%预期仓位）'+str(stock)+str(get_security_info(stock).display_name))
                    order_target_value(stock, 0.5 * psize)
                else:
                    order_value(stock, psize)

                if len(context.portfolio.positions) == g.stock_num:
                    break
                            
