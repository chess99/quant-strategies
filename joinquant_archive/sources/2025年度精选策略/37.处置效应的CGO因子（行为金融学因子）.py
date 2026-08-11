# 克隆自聚宽文章：https://www.joinquant.com/post/27009
# 标题：处置效应的CGO因子（行为金融学因子）
# 作者：BAFE

"""
CGO改写，考虑停牌股
"""
import jqdata

market = 'all'
# market='000300.XSHG'
# 是否进行中性化处理
RISK_NEUTRALIZE = False

def initialize(context):
    if market == 'all':
        set_benchmark('000905.XSHG')
    else:
        set_benchmark(market)
    set_option('use_real_price', True)
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG') 
    run_daily(market_open, time='open', reference_security='000300.XSHG')
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')
    g.signal = 0
    g.code_list=[]
    
def before_market_open(context):
    """
    计算CGO，返回字典
    """
    # 重置初始股池
    g.code_list=[]
    if g.signal % 5 != 0:
        return
    if market == 'all':
        g.code_list = get_all_securities().index
        g.code_list = new_filter(context, g.code_list, 220)
        g.code_list=tx_filter(g.code_list)
        g.code_list=limit_price(g.code_list)
    else:
        g.code_list = get_index_stocks(market)
        g.code_list = new_filter(context, g.code_list, 220)
        g.code_list=tx_filter(g.code_list)
        g.code_list=limit_price(g.code_list)
        
    date_list=jqdata.get_trade_days(end_date=context.previous_date, count=100)
    # 1. 前100个交易日的成交均价
    df_avg,dict_close=avg_dict(g.code_list)
    g.code_list=list(df_avg)
    # 2. 获取前100个交易日的换手率
    df_turnover=turnover_ratio(g.code_list,date_list) 
       
    # 3. 计算CGO
    g.cgo_dict = {}
    for code in g.code_list:
        rp = calculate_rp(df_avg[code], df_turnover[code])
        cgo = dict_close[code] / rp - 1
        if not np.isnan(cgo):
            g.cgo_dict[code] = cgo
    if RISK_NEUTRALIZE:
        g.cgo_dict = neutralize_risk(g.cgo_dict)

def market_open(context):
    """
    基于cgo结果下单
    """
    if g.signal % 5 != 0:
        return
    sort_tuple = sorted(g.cgo_dict.items(), key=lambda x:x[1])
    rank_list = [line[0] for line in sort_tuple]
    adjust_position_trival(context, rank_list, 10)

def after_market_close(context):
    g.signal += 1

#-----------------------工具函数------------------------------
# 1. 前100个交易日的成交均价,及最近的收盘价
def avg_dict(code_list):
    avg_dict = {}
    latest_close = {}
    for code in g.code_list:   
        df = attribute_history(code, 100, '1d', ['avg', 'close','paused'], skip_paused=False, df=False) # 因需要记录日期，所以不能用dict形式
        close = df['close']
        avg = df['avg']
        paused = df['paused']
        # 当日停牌，直接跳过
        if paused[-1]:
            continue
        # 排除停牌过多情况    
        if sum(paused) > 50:
            continue
        # 排除近10日跌停情况
        if sum((close[-10:] / close[-11:-1] - 1) < -0.095) > 0:
            continue
        latest_close[code] = close[-1] # 记录最新收盘价
        avg_dict[code] = avg
    return pd.DataFrame(avg_dict),latest_close

# 2、返回换手率
def turnover_ratio(code_list,date_list):
    for k,date in enumerate(date_list):
        q = query(valuation.code,valuation.turnover_ratio).filter(valuation.code.in_(code_list))
        df = get_fundamentals(q, date=date)
        if k==0:
            df1=df
        else:
            df1=df1.merge(df,on='code',how='outer')#用‘outer，方式合并，’nan填充缺失
    df2=df1.set_index(['code'])#以代码为索引
    df3=df2.T#进行转置
    df3.reset_index(drop=True, inplace=True)#重新设置索引
    df3.fillna(0,inplace=True)#用0填充所有缺失值
    return df3

def calculate_rp(avg_list, turnover_list):
    """
    输入均价和换手率
    输出参考价格
    """
    turnover_list = np.array(turnover_list)
    func=lambda i: turnover_list[i] / 100 * np.prod(1 - turnover_list[i + 1:] / 100)
    weighted_turnover_list =list(map(func, range(len(turnover_list))))
    weighted_turnover_list = np.array(weighted_turnover_list) / sum(weighted_turnover_list)
    return sum(avg_list * weighted_turnover_list)  
    
def adjust_position_trival(context, rank_list, n=10):
    """
    调仓函数,输入排好序的列表和购买数量，按均仓调整
    包含微小调整
    """
    rank_list = [code for code in rank_list if get_current_data()[code].paused!=1]
    buy_list = []
    old_dict = {}
    for code in context.portfolio.positions:
        old_dict[code] = context.portfolio.positions[code].value
        if get_current_data()[code].paused == 1:
            buy_list.append(code)

    buy_list.extend(rank_list[:n-len(buy_list)])
    if len(buy_list) == 0:
        for code in context.portfolio.positions:
            order_target(code, 0)
        return
    cur_asset = context.portfolio.total_value
    new_dict = dict.fromkeys(buy_list, cur_asset/len(buy_list))
    all_code = list(set(old_dict) | set(new_dict))
    delta_dict = dict.fromkeys(all_code, 0)
    for code in all_code:
        if code not in old_dict: # 旧的没有新的有，买
            delta_dict[code] = new_dict[code]
        elif code not in new_dict:# 旧的有新的没有，卖
            delta_dict[code] = -old_dict[code]
        else:
            delta = new_dict[code] - old_dict[code]
            delta_dict[code] = delta
    buy_dict = {}
    sell_dict = {}
    for code in delta_dict:
        price = get_current_data()[code].day_open
        if delta_dict[code] < 0:
            sell_dict[code] = delta_dict[code] / price
        else:
            buy_dict[code] = delta_dict[code] / price

    for code in sell_dict:
        order(code,sell_dict[code])

    for code in buy_dict:
        order(code,buy_dict[code])

def regress(x, y):
    """
    回归
    """
    k = np.dot(np.dot(np.linalg.inv(np.dot(x.T, x)), x.T), y)
    b = np.mean(y) - np.mean(x) * k
    sigma = y - np.dot(x, k)
    return k, b, sigma

def neutralize_risk(factor_dict):
    """
    风险中性化（市值、行业）
    输入因子字典，输出新的字典
    """
    keys = factor_dict.keys()
    keys = sorted(keys) 
    values = []
    for i in range(len(keys)):
        values.append(factor_dict[keys[i]])
    values = np.array(values)
    y = values
    idx = -np.isnan(y)
    keys_available = np.array(keys)[idx]
    y = y[idx]
    
    mv = get_mv(keys_available)
    industries = []
    
    for code in keys_available:
        single_industry = get_current_data()[code].industry_code
        if single_industry is None:
            industries.append('Z')
        else:
            industries.append(single_industry[0])
    mv = np.array(mv) * 1e8

    industry_set = list(set(industries))
    industry_code = []
    for i in range(len(keys_available)):
        idx = industry_set.index(industries[i])
        industry_code.append(idx)
    
    lnmv = np.log(mv)
    x = np.zeros((len(keys_available), len(industry_set)))
    x[range(len(keys_available)), industry_code] = 1
    x = np.column_stack((x, lnmv.reshape(-1, 1)))
    if len(x) == 0 or len(y) == 0:
        sigma = y
    else:
        sigma = regress(x, y.reshape(-1, 1))[2]

    new_dict = dict.fromkeys(keys, np.nan)
    for i in range(len(keys_available)):
        new_dict[keys_available[i]] = sigma[i]
    return new_dict

def get_mv(code_list):
    """
    获取市值数据
    """
    df = get_fundamentals(query(valuation).filter(valuation.code.in_(code_list)).order_by(valuation.code))
    return df['market_cap']


# 过滤新股
def new_filter(context, security_list, delta):
    delta_date = context.current_dt.date() - datetime.timedelta(delta)
    security_list = [stock for stock in security_list if get_security_info(stock).start_date < delta_date]
    return security_list  
   
# 过滤涨跌停板股票
def limit_price(security_list):
    current_data=get_current_data()
    security_list=[stock for stock in security_list if current_data[stock].last_price!=current_data[stock].high_limit]
    security_list=[stock for stock in security_list if current_data[stock].last_price!=current_data[stock].low_limit]
    return security_list
    
#过滤停牌、退市、ST股票
def tx_filter(security_list):
    current_data=get_current_data()
    security_list = [stock for stock in security_list if not current_data[stock].paused]
    security_list = [stock for stock in security_list if not '退' in current_data[stock].name]
    security_list = [stock for stock in security_list if not current_data[stock].is_st]
    return security_list
