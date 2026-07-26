# 克隆自聚宽文章：https://www.joinquant.com/post/49082
# 标题：搭建量化交易模型从零开始——择时，选股，仓位管理和因子分析
# 作者：Jacobb75

# 克隆自聚宽文章：https://www.joinquant.com/post/39814
# 标题：持仓95只大容量小市值，媲美金元顺安元启
# 作者：开心果

#选出ROE增长最超预期的前50%，从中再挑基本面好的，小市值但是不能太小。平仓逻辑：涨停没有连续性&止盈，不设止损

from jqdata import *
from jqlib.technical_analysis  import *
from sqlalchemy.sql.expression import *
import pandas as pd
from jqfactor import get_factor_values
import numpy as np
import warnings

def initialize(context):
    # setting
    log.set_level('system','error')
    set_option('use_real_price', True)
    set_option('avoid_future_data', True)
    
    g.benchmark = '000905.XSHG'
    set_benchmark(g.benchmark)
    #交易佣金（万分之1.5）
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.00015, close_commission=0.00015, close_today_commission=0, min_commission=5),type='stock')

    #指数池
    g.index1 = '399303.XSHE'#小盘指数，国证2000
    g.index2 = '000852.XSHG'#大盘指数，中证1000
    
    g.index_pool = [
        g.index1, #小盘
        g.index2, #大盘
    ]
    #动量轮动参数
    g.momentum_day = 144 #判断动量所需天数
    g.j = 12 
    g.w = 12 #每季度作出大小盘强弱判断
    
    #5个因子设定
    g.weights = [1, 1, 1, 1, 1] # 股票打分各因子权重
    
    # strategy
    g.stock_num = 100
    g.buytimes = 3 #每次买入时的建仓次数，先设定为3次
    g.position = 1/g.buytimes
    g.cash = 0 #买入日当天开盘时的可用资金
    g.position_count = 0 #买入日当天开盘时新满足条件的股票数量
    g.a = 0
    run_daily(prepare_stock_list, time='9:05', reference_security='000300.XSHG')
    run_daily(cash_check, time= '9:05')#每个买入日判断每次买入可用资金
    run_daily(position_count, time= '9:05')#每个买入日判断新满足条件的股票数量
    
    run_weekly(my_buy, 3, time='11:10')
    run_weekly(my_buy, 3, time='11:15')
    run_weekly(my_buy, 3, time='11:20')

    #run_time(context,240,my_buy,'11:15:00')#每240分钟运行期货代码一次(每天11:15)
    #run_time(context,240,my_sell,'10:30:00')#每240分钟运行期货代码一次(每天11:15)
    run_daily(check_limit_up, time='9:45')#止盈止损
    run_daily(check_limit_up, time='10:00')#止盈止损
    run_daily(check_limit_up, time='10:15')#止盈止损
    run_daily(check_limit_up, time='10:30')#止盈止损
    run_daily(check_limit_up, time='10:45')#止盈止损
    run_daily(check_limit_up, time='11:00')#止盈止损
    run_daily(check_limit_up, time='11:15')#止盈止损

    run_daily(check_limit_up, time='13:00')#止盈止损
    run_daily(check_limit_up, time='13:15')#止盈止损
    run_daily(check_limit_up, time='13:30')#止盈止损
    run_daily(check_limit_up, time='13:45')#止盈止损
    run_daily(check_limit_up, time='14:00')#止盈止损
    run_daily(check_limit_up, time='14:15')#止盈止损
    run_daily(check_limit_up, time='14:30')#止盈止损
    run_daily(check_limit_up, time='14:45')#止盈止损

    
    
    
    g.selltimes = 3 #每次卖出时的建仓次数，先设定为3次
    g.position_sell = 1/g.selltimes #每次卖出的仓位
    g.stock_amount = {} #每日卖出时检测所有股票持仓数量
    run_daily(stock_amount_check, time='9:05')    
    #run_daily(my_sell, time='9:45')#止盈止损
    #run_daily(my_sell, time='10:00')#止盈止损
    run_daily(my_sell, time='10:15')#止盈止损
    run_daily(my_sell, time='10:30')#止盈止损
    run_daily(my_sell, time='10:45')#止盈止损
    #run_daily(my_sell, time='11:00')#止盈止损
    #run_daily(my_sell, time='11:15')#止盈止损

    #run_daily(my_sell, time='13:00')#止盈止损
    #run_daily(my_sell, time='13:15')#止盈止损
    #run_daily(my_sell, time='13:30')#止盈止损
    #run_daily(my_sell, time='13:45')#止盈止损
    #run_daily(my_sell, time='14:00')#止盈止损
    #run_daily(my_sell, time='14:15')#止盈止损
    #run_daily(my_sell, time='14:30')#止盈止损
    #run_daily(my_sell, time='14:45')#止盈止损


    set_slippage(FixedSlippage(0.04),type='stock')

def run_time(context,x,y,z):
    ind=g.benchmark
    datas = get_price(ind, start_date='2015-04-16 9:30:00', end_date='2015-04-16 15:00:00',frequency='1m').index.tolist()[:-1]#剔除15:00  
    times = [str(t)[-8:] for t in datas]  #提取交易时间
    times.insert(0,z)  
    for t in times[::x]:
        run_daily(y, t)  #对某个函数设置多个运行时间点


    
#1-1 根据动量判断市场风格
def get_index_signal(index_pool):
    score_list = []
    for index in index_pool:
        #分别计算大小盘指数一段时间内预期收益率（最低价格和时间的线性回归斜率*相关系数）的大小，大的强
        data = attribute_history(index, g.momentum_day, '1d', ['low'])
        y = data['log'] = np.log(data.low)
        x = data['num'] = np.arange(data.log.size)
        slope, intercept = np.polyfit(x, y, 1)
        annualized_returns = math.pow(math.exp(slope), 233) - 1
        r_squared = 1 - (sum((y - (slope * x + intercept))**2) / ((len(y) - 1) * np.var(y, ddof=1)))
        score = annualized_returns * r_squared
        score_list.append(score)
    index_dict=dict(zip(index_pool, score_list))
    #print(index_dict)
    sort_list=sorted(index_dict.items(), key=lambda item:item[1], reverse=True) #True为降序
    code_list=[]
    for i in range((len(index_pool))):
        code_list.append(sort_list[i][0])
    best_index = code_list[0]
    return best_index


def my_select(context):
    # 获取选股列表并过滤掉:st,st*,退市,涨停,跌停,停牌
    check_out_list = my_Trader(context)
    #log.info('今日自选股:%s' % check_out_list)
    #log.info('今日股票数量:%s' % g.stock_num)
    return check_out_list
    
def cash_check(context):
    b = context.portfolio.available_cash * g.position
    g.cash = b
    return g.cash
        
def position_count(context):
    c = len(context.portfolio.positions)
    g.position_count = c
    return g.position_count
    
def stock_amount_check(context):
    hold_list = list(context.portfolio.positions)
    l = {}
    for s in hold_list:
        l[s] = context.portfolio.positions[s].amount * g.position_sell
    g.stock_amount = l
    return g.stock_amount

def my_buy(context):
    # 获取选股列表并过滤掉:st,st*,退市,涨停,跌停,停牌
    adjust_position_buy(context, g.cash,  my_select(context))
    
def my_sell(context):
    # 获取选股列表并过滤掉:st,st*,退市,涨停,跌停,停牌
    adjust_position_sell(context, my_select(context), g.position_sell)


def filter_stock(context):
    curr_data = get_current_data()
    yesterday = context.previous_date
    
    # 过滤次新股
    by_date = yesterday
    #by_date = datetime.timedelta(days=1200)
    #by_date = yesterday - datetime.timedelta(days=1200)  # 三年
    initial_list = get_all_securities(date=by_date).index.tolist()


    # 0. 过滤创业板，科创板，st，今天涨跌停的，停牌的
    filtered_list = [stock for stock in initial_list if not (
            (curr_data[stock].day_open == curr_data[stock].high_limit) or
            (curr_data[stock].day_open == curr_data[stock].low_limit) or
            curr_data[stock].paused or
            #curr_data[stock].is_st
            ('ST' in curr_data[stock].name) or
            ('*' in curr_data[stock].name) or
            ('退' in curr_data[stock].name) 
            #(stock.startswith('300')) or
            #(stock.startswith('688')) 
            #(stock.startswith('002'))
    )]
    
    return filtered_list
    
    
                
def my_Trader(context):
    # all stocks
    #df_stocknum = pd.DataFrame(columns=['当前符合条件股票数量'])
    dt_last = context.previous_date

    stocks = filter_stock(context)
    
    # 在df3中筛选出基本面还不错的公司
    df = get_fundamentals(query(
            valuation.code, 
            valuation.turnover_ratio,
            valuation.market_cap, 
            valuation.circulating_market_cap
        ).filter(
            valuation.code.in_(stocks),
            #balance.total_liability / balance.total_assets < 0.8,#资产负债率<80%
            valuation.pb_ratio > 1,
            valuation.pe_ratio > 0,
            valuation.pe_ratio < 200,#市净率>0
            #indicator.inc_return > 2,#净资产收益率>0
            indicator.inc_total_revenue_year_on_year > 30,#营业总收入同比增长率
            #indicator.inc_total_revenue_annual > 30,    #营业总收入环比增长率
            indicator.inc_net_profit_year_on_year > 50,#净利润同比增长率
            #indicator.inc_net_profit_annual > 50,#净利润环比增长率
            indicator.ocf_to_operating_profit > 10,#经营活动产生的现金流量净额/经营活动净收益>5
            
        ).order_by(
            valuation.circulating_market_cap.asc()
            #valuation.market_cap.asc()#市值由小到大排列
		))

    #choice = list(df.code)[int(0 * len(list(df.code))): (int(0 * len(list(df.code))) + g.stock_num)]
    #choice1 = list(df.code)
    
    df.index = df.code
    initial_list = list(df.index)
    
    # 获取前N个单位时间当时的收盘价
    def get_close(stock, n, unit):
        return attribute_history(stock, n, unit, 'close')['close'][0]
    
    # 获取现价相对N个单位前价格的涨幅
    def get_return(stock, n, unit):
        price_before = attribute_history(stock, n, unit, 'close')['close'][0]
        price_now = get_close(stock, 1, '1m')
        if not isnan(price_now) and not isnan(price_before) and price_before != 0:
            return price_now / price_before
        else:
            return 100
    
    #计算单独因子值
    TO, CMC, PN, TV, RE = [], [], [], [], []
    for stock in initial_list:
        #换手率
        to = df.loc[stock]['turnover_ratio']
        TO.append(to)
        #流通市值
        cmc = df.loc[stock]['circulating_market_cap']
        CMC.append(cmc)
        #当前价格
        pricenow = get_close(stock, 1, '1m')
        PN.append(pricenow)
        #21日累计成交量
        total_volume_n = attribute_history(stock, 21, '1d', 'volume')['volume'].sum()
        TV.append(total_volume_n)
        #55日涨幅
        m_days_return = get_return(stock, 55, '1d') 
        RE.append(m_days_return)
    #把因子值合并到表格里数据
    df = pd.DataFrame(index=initial_list,
        columns=['turnover_ratio','circulating_market_cap','price_now','total_volume_n','m_days_return'])
    df['turnover_ratio'] = TO
    df['circulating_market_cap'] = CMC
    df['price_now'] = PN
    df['total_volume_n'] = TV
    df['m_days_return'] = RE
    df = df.dropna()
    #默认的因子值
    m0, m1, m2, m3, m4 = min(TO), min(CMC),min(PN), min(TV), min(RE)
    
    #做大盘小盘强弱的判断市值因子的权重
    
    if (g.j < g.w):
        #print("暂时不做大小盘强弱判断")
        g.j += 1
    elif (g.j==g.w):
        index_signal = get_index_signal(g.index_pool)
        
        if index_signal == g.index_pool[1]:
            print("大盘股强")
            g.j = 0
            g.weights[1] = -g.weights[1] #大盘股强的话，市值越大权重越大
        
        elif index_signal == g.index_pool[0]:
            print("小盘股强")
            g.j = 0
            #小盘股强的话，市值越小权重越大

    temp_list = []
    for i in range(len(list(df.index))):
        score = g.weights[0] * math.log(m0 / df.iloc[i,0]) + g.weights[1] * math.log(m1 / df.iloc[i,1]) + g.weights[2] * math.log(m2 / df.iloc[i,2]) + g.weights[3] * math.log(m3 / df.iloc[i,3]) + g.weights[4] * math.log(m4 / df.iloc[i,4])
        temp_list.append(score)
    df['score'] = temp_list
            
    #排序并返回最终选股列表
    df = df.sort_values(by='score', ascending=False)
    final_list = list(df.index)[(int(0*len(list(df.index)))): (int(0*len(list(df.index))) + g.stock_num)]

    return final_list

#买入
def adjust_position_buy(context,b, buy_stocks):

    if g.a < 0.854:#股票总仓位在0.854以下才考虑买入
        if g.stock_num >= g.position_count:
    
            for stock in buy_stocks:
                if buy_stocks.index(stock) <= g.stock_num - g.position_count:
                    #value = context.subportfolios[0].cash * g.position * (g.stock_num - position_count) / sum(range(1,g.stock_num - position_count+1))#每只股票预期买入的价值并非等权重，排在前边的权重高
                    #psize = b / g.stock_num
                    psize = b * (g.stock_num - g.position_count - buy_stocks.index(stock)) / sum(range(g.stock_num - g.position_count +1))
                    #psize = context.portfolio.total_value * position * (g.stock_num - buy_stocks.index(stock)) / sum(range(g.stock_num +1))
                    #value = context.subportfolios[0].total_value * 2 / (g.stock_num + buy_stocks.index(stock))
                    #psize = context.portfolio.total_value * position * 2 / (g.stock_num + buy_stocks.index(stock))
        
                    
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
                    #目前价格落在10%分位数之下，即认为超卖，可以多买；落在5%分位数以上认为超买，少买
                    
                    #if context.portfolio.available_cash  < psize:
                        #break
                    z = (buy_stocks.index(stock) + 1) / (g.stock_num + 1)
                    #下单规则
                    #if (1 - 0.9 * (1-z)) * psize/G[0][3] > 100 and stock[:2] != '68':#最少买100股以下的就不买了
                    if p < -2:#短期超卖，可以多买
                        #log.info('短期超卖，多买点（150%预期仓位）'+str(stock)+str(get_security_info(stock).display_name))
                        order(stock, int((1 + 5 * (1-z)) * psize/(100 * G[0][3])) * 100, MarketOrderStyle(2 * r))#所有股票都短期超卖？太罕见了，这个情况我就没考虑
                       
                    elif p > 2 and int((1 - 0.5 * (1-z)) * psize/G[0][3] > 100) and stock[:2] != '68':#非科创板短期超买，应该少买，但是至少100股以上
                        #log.info('短期超买，少买点'+str(stock)+str(get_security_info(stock).display_name))
                        order(stock, int((1 - 0.5 * (1-z)) * psize/(100 * G[0][3])) * 100)
                        
                    elif p > 2 and int((1 - 0.5 * (1-z)) * psize/G[0][3] > 200) and stock[:2] == '68':#科创板短期超买，应该少买，但是至少200股以上
                        #log.info('短期超买，少买点（50%预期仓位）'+str(stock)+str(get_security_info(stock).display_name))
                        order(stock, int((1 - 0.5 * (1-z)) * psize/(100 * G[0][3])) * 100, MarketOrderStyle(2 * r))     
                    
                    elif int(1 * psize/(100 * G[0][3])) * 100 > 100 and stock[:2] != '68':#非超买超卖状态，正常建仓
                        order(stock, int(1 * psize/(100 * G[0][3])) * 100, MarketOrderStyle(2 * r))
                    
                    elif int(1 * psize/(100 * G[0][3])) * 100 > 200 and stock[:2] == '68':#非超买超卖状态，正常建仓
                        order(stock, int(1 * psize/(100 * G[0][3])) * 100, MarketOrderStyle(2 * r))                
        
    else:
        log.info('仓位较高，不买入')
        
    a= context.portfolio.positions_value / context.portfolio.total_value    
    log.info('当次买入后仓位:%s' % a)                


#1-3 准备股票池
def prepare_stock_list(context):
    #获取已持有列表
    g.high_limit_list = []
    hold_list = list(context.portfolio.positions)
    if hold_list:
        df = get_price(hold_list, end_date=context.previous_date, frequency='daily',
                       fields=['close', 'high_limit', 'paused'],
                       count=1, panel=False)
        g.high_limit_list = df.query('close==high_limit and paused==0')['code'].tolist()
        
    a= context.portfolio.positions_value / context.portfolio.total_value
    g.a = a
    log.info('昨日仓位:%s' % a)    
    return g.a

        
# 1-5 调整昨日涨停股票
def check_limit_up(context):
     # 获取持仓的昨日涨停列表
    current_data = get_current_data()
    
    if g.high_limit_list:
        for stock in g.high_limit_list:
            G = get_bars(stock, 1, '1d', ['high','low','open','close'],  end_dt=context.current_dt,include_now=True)
            r = np.mean(list(G[0]))
            
            if current_data[stock].last_price < current_data[stock].high_limit and context.portfolio.positions[stock].amount > 0:
                #log.info("[%s]涨停打开，卖出" % stock)
                order_target(stock, 0, MarketOrderStyle(0.8 * r))


#止盈    
def adjust_position_sell(context,s, d):    
    hold_list = list(context.portfolio.positions) 
    d = g.stock_amount
     
    for s in hold_list:
        current_data = get_current_data()
        now_price = current_data[s].last_price
        open_price = current_data[s].day_open
        close_data_1d =get_bars(s, end_dt=context.current_dt, count=2,fields=['close', 'high','volume'], include_now=True)
        p = context.subportfolios[0].positions[s].value #持股价值
        q = d[s] #每次卖出时拟交易的数量
        G = get_bars(s, 1, '1d', ['high','low','open','close'],  end_dt=context.current_dt,include_now=True)
        r = np.mean(list(G[0]))
                    
    
        #非科创板股票止盈
        if close_data_1d['high'][-1]>=context.portfolio.positions[s].avg_cost*2.382 and context.subportfolios[0].positions[s].amount > 1000 and \
                (close_data_1d['high'][-1]-now_price)>= context.portfolio.positions[s].avg_cost*0.05 and s[:2] != '68':

            
            order_target(s, 0)
            #order(s, -int(q/100) * 100)
            log.info('1000股以上非科创板收益大于138.2%后，回撤大于5%时平全部仓位'+str(s)+str(get_security_info(s).display_name))
            
        if close_data_1d['high'][-1]>=context.portfolio.positions[s].avg_cost*1.382 and context.subportfolios[0].positions[s].amount <= 1000 and \
            (close_data_1d['high'][-1]-now_price)>= context.portfolio.positions[s].avg_cost*0.05 and s[:2] != '68':
                
            order_target(s, 0)#不足1000股平仓
            log.info('1000股以下非科创板收益大于38.2%后，回撤大于5%时平全部仓位'+str(s)+str(get_security_info(s).display_name))


        #科创板股票止盈
        if close_data_1d['high'][-1]>=context.portfolio.positions[s].avg_cost*2.382 and \
                (close_data_1d['high'][-1]-now_price)>= context.portfolio.positions[s].avg_cost*0.05 and s[:2] == '68':
                        
            order(s, 0, MarketOrderStyle(0.8 * r))
            log.info('科创板股票收益大于238.2%且持仓股数大于1000股，回撤大于5%时平全部的仓位'+str(s)+str(get_security_info(s).display_name))
        
        if close_data_1d['high'][-1]>=context.portfolio.positions[s].avg_cost*2.382 and \
                (close_data_1d['high'][-1]-now_price)>= context.portfolio.positions[s].avg_cost*0.05 and s[:2] == '68':
                        
            order_target(s, 0, MarketOrderStyle(0.8 * r))
            log.info('科创板股票收益大于161.8%且持仓股数小于1000股，回撤大于5%时平100%的仓位'+str(s)+str(get_security_info(s).display_name))            
                    
                
        #非科创板股票止损1-（（1-0.854）*0.618+0.854）=0.94418
        if now_price < context.portfolio.positions[s].avg_cost*0.94418 and context.subportfolios[0].positions[s].amount > 1000 and s[:2] != '68':
            order_target(s, 0)   
            #log.info('^^^^^^^^^^^^非科创板股票收益小于等于-5%直接平仓,止损^^^^^^^^^^^^'+str(s)+str(get_security_info(s).display_name))     
        
        if now_price < context.portfolio.positions[s].avg_cost*0.94418 and context.subportfolios[0].positions[s].amount <= 1000 and s[:2] != '68':
            order_target(s, 0)   
            #log.info('^^^^^^^^^^^^非科创板股票收益小于等于-5%直接平仓,止损^^^^^^^^^^^^'+str(s)+str(get_security_info(s).display_name))       
            
        #科创板股票止损（1-0.618*1.382=0.854）
        if now_price < context.portfolio.positions[s].avg_cost*0.854 and s[:2] == '68':
            order_target(s, 0, MarketOrderStyle(0.8 * r))   
            #log.info('^^^^^^^^^^^^科创板股票收益小于等于-15%直接平仓,止损^^^^^^^^^^^^'+str(s)+str(get_security_info(s).display_name))      

            
        
        
 
#2-6 过滤科创北交股票
def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68':
            stock_list.remove(stock)
    return stock_list

# 2-2 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not (
            current_data[stock].is_st or
            'ST' in current_data[stock].name or
            '*' in current_data[stock].name or
            '退' in current_data[stock].name)]
            
# end
