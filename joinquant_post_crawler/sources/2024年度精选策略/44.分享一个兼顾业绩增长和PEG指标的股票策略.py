# 克隆自聚宽文章：https://www.joinquant.com/post/42593
# 标题：分享一个兼顾业绩增长和PEG指标的股票策略
# 作者：芹菜1303

#导入函数库
from jqdata import *
from jqfactor import get_factor_values
import numpy as np
import pandas as pd
import time,datetime

#初始化函数 
def initialize(context):
    set_benchmark('399101.XSHE')# "399101.XSHE" '399300.XSHE'
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 设置交易成本万分之三
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),type='fund')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    #选股参数
    g.stock_num = 4 #持仓数
    # 设置交易时间，每天运行
    g.ref_stock = '000300.XSHG' #用ref_stock做择时计算的基础数据
    g.N = 18 # 计算最新斜率slope，拟合度r2参考最近N天
    g.M = 600 # 计算最新标准分zscore，rsrs_score参考最近M天
    g.score_threshold = 0.7 # rsrs标准分指标阈值
    g.mean_day = 30 #计算结束ma收盘价，参考最近mean_day
    g.mean_diff_day = 2 #计算初始ma收盘价，参考(mean_day + mean_diff_day)天前，窗口为mean_diff_day的一段时间
    g.slope_series = initial_slope_series()[:-1] # 除去回测第一天的slope，避免运行时重复加入
    g.fzts=22#买入时，反正银子阈值
    g.rate=1#反转系数，默认1，数值越小，跌的越深  
    g.weights = [3,9,8,4,10]
    g.sellrank = 10 # 排名多少位之后(不含)卖出
    g.buyrank = 9 # 排名多少位之前(含)可以买入
    #原版是每周调仓一次
    run_daily(my_trade, time='9:30', reference_security='000300.XSHG')
    run_daily(print_trade_info, time='15:30', reference_security='000300.XSHG')

#2-2 选股模块
def get_stock_list(context):
    initial_list = get_all_securities().index.tolist()
    initial_list = filter_new_stock(context,initial_list)
    initial_list = filter_kcb_stock(context, initial_list)
    initial_list = filter_st_stock(initial_list)
    initial_list = filter_kcb_stock(context, initial_list)
    #函数变量说明（context,股票列表，因子名称，排序，取值范围-开始，取值范围-结束）排序：选择升序-小到大(默认true)，或者降序-大到小（false）
    initial_list = growth_profit(context,initial_list)#归母净利润增长率最大的50%
    initial_list = peg(context,initial_list)#PEG最小的50%
    initial_list = get_factor_filter_list(context, initial_list, 'TVSTD20',True, 0, 0.3)#20日成交金额的标准差
    # final_list=initial_list
    final_list=get_stock_rank_m_m(context,initial_list)
    return final_list

#2-1 选股模块
def get_factor_filter_list(context,stock_list,jqfactor,sort,p1,p2):
    yesterday = context.previous_date
    score_list = get_factor_values(stock_list, jqfactor, end_date=yesterday, count=1)[jqfactor].iloc[0].tolist()
    df = pd.DataFrame(columns=['code','score'])
    df['code'] = stock_list
    df['score'] = score_list
    df.dropna(inplace=True)
    df.sort_values(by='score', ascending=sort, inplace=True)
    filter_list = list(df.code)[int(p1*len(stock_list)):int(p2*len(stock_list))]
    print(f"{jqfactor}筛选的数量：{len(filter_list)}")
    return filter_list
    
#PEG因子选股 PE/归母公司净利润(TTM)增长率 排序从大到小排序，取前10%，大概有300只股票
def peg(context,stock_list):
    qq = query(
        income.code,
       (valuation.pe_ratio / indicator.inc_net_profit_to_shareholders_year_on_year).label('peg')
      ).filter(
        income.code.in_(stock_list),
      )
    ret=get_fundamentals(qq)
    #0.08是选择中的最优化解
    ret=ret[(ret['peg']>0.08)]#剔除peg是负数的记录
    ret.sort_values(by='peg', ascending=True, inplace=True)#按peg从小到大排序
    target_stocks=list(ret['code'][0:int(len(ret)*0.5)])
    print("PEG筛选数量:{0}".format(len(target_stocks)))
    return target_stocks
    
#营业收入同比增长率    
def growth_profit(context,stock_list):
    qq = query(
        income.code,
        indicator.inc_net_profit_to_shareholders_year_on_year,#归母公司股东净利润同比增长率
      ).filter(
        income.code.in_(stock_list),
      ).order_by(indicator.inc_net_profit_to_shareholders_year_on_year.desc())#按归母净利润同比增长率从大到小排序
    ret=get_fundamentals(qq)
    target_stocks=list(ret['code'][0:int(len(ret)*0.5)])
    print("净利润增长前10%筛选数量:{0}".format(len(target_stocks)))
    return target_stocks

#3-1 过滤模块-过滤停牌股票
#输入选股列表，返回剔除停牌股票后的列表
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]

#3-2 过滤模块-过滤ST及其他具有退市标签的股票
#输入选股列表，返回剔除ST及其他具有退市标签股票后的列表
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list
            if not current_data[stock].is_st
            and 'ST' not in current_data[stock].name
            and '*' not in current_data[stock].name
            and '退' not in current_data[stock].name]

#3-3 过滤模块-过滤涨停的股票
#输入选股列表，返回剔除未持有且已涨停股票后的列表
def filter_limitup_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    # 已存在于持仓的股票即使涨停也不过滤，避免此股票再次可买，但因被过滤而导致选择别的股票
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] < current_data[stock].high_limit]

#3-4 过滤模块-过滤跌停的股票
#输入股票列表，返回剔除已跌停股票后的列表
def filter_limitdown_stock(context, stock_list):
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or last_prices[stock][-1] > current_data[stock].low_limit]

#3-5 过滤模块-过滤科创板
#输入股票列表，返回剔除科创板后的列表
def filter_kcb_stock(context, stock_list):
    return [stock for stock in stock_list  if stock[0:3] != '688']

#3-6 过滤次新股
#输入股票列表，返回剔除上市日期不足250日股票后的列表
def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=250)]

#4-1 交易模块-自定义下单
#报单成功返回报单(不代表一定会成交),否则返回None,应用于
def order_target_value_(security, value):
    if value == 0:
        log.debug("Selling out %s" % (security))
    else:
        log.debug("Order %s to value %f" % (security, value))
    # 如果股票停牌，创建报单会失败，order_target_value 返回None
    # 如果股票涨跌停，创建报单会成功，order_target_value 返回Order，但是报单会取消
    # 部成部撤的报单，聚宽状态是已撤，此时成交量>0，可通过成交量判断是否有成交
    return order_target_value(security, value)

#4-2 交易模块-开仓
#买入指定价值的证券,报单成功并成交(包括全部成交或部分成交,此时成交量大于0)返回True,报单失败或者报单成功但被取消(此时成交量等于0),返回False
def open_position(security, value):
    order = order_target_value_(security, value)
    if order != None and order.filled > 0:
        return True
    return False

#4-3 交易模块-平仓
#卖出指定持仓,报单成功并全部成交返回True，报单失败或者报单成功但被取消(此时成交量等于0),或者报单非全部成交,返回False
def close_position(position):
    security = position.security
    order = order_target_value_(security, 0)  # 可能会因停牌失败
    if order != None:
        if order.status == OrderStatus.held and order.filled == order.amount:
            return True
    return False

#4-4 交易模块-调仓
#当择时信号为买入时开始调仓，输入过滤模块处理后的股票列表，执行交易模块中的开平仓操作
def adjust_position(context, buy_stocks):
    for stock in context.portfolio.positions:
        if stock not in buy_stocks:
            log.info("[%s]已不在应买入列表中" % (stock))
            position = context.portfolio.positions[stock]
            close_position(position)
        else:
            log.info("[%s]已经持有无需重复买入" % (stock))
    # 根据股票数量分仓
    # 此处只根据可用金额平均分配购买，不能保证每个仓位平均分配
    position_count = len(context.portfolio.positions)
    if g.stock_num > position_count:
        value = context.portfolio.cash / (g.stock_num - position_count)
        for stock in buy_stocks:
            if stock not in context.portfolio.positions:
                if open_position(stock, value):
                    if len(context.portfolio.positions) == g.stock_num:
                        break
def get_ols(x, y):
    slope, intercept = np.polyfit(x, y, 1)
    r2 = 1 - (sum((y - (slope * x + intercept))**2) / ((len(y) - 1) * np.var(y, ddof=1)))
    return (intercept, slope, r2)

def initial_slope_series():
    data = attribute_history(g.ref_stock, g.N + g.M, '1d', ['high', 'low'])
    return [get_ols(data.low[i:i+g.N], data.high[i:i+g.N])[1] for i in range(g.M)]

# 因子标准化
def get_zscore(slope_series):
    mean = np.mean(slope_series)
    std = np.std(slope_series)
    return (slope_series[-1] - mean) / std

# 只看RSRS因子值作为买入、持有和清仓依据，前版本还加入了移动均线的上行作为条件
def get_timing_signal(context,stock):
    g.mean_diff_day = 5
    # 30+5 天。不知道为何？
    close_data = attribute_history(g.ref_stock, g.mean_day + g.mean_diff_day, '1d', ['close'])
    high_low_data = attribute_history(g.ref_stock, g.N, '1d', ['high', 'low'])
    intercept, slope, r2 = get_ols(high_low_data.low, high_low_data.high)
    g.slope_series.append(slope)
    rsrs_score = get_zscore(g.slope_series[-g.M:]) * r2
    if rsrs_score > g.score_threshold: return "BUY"
    elif rsrs_score < -g.score_threshold: return "SELL"
    else: return "KEEP"

#4-5 交易模块-择时交易
#结合择时模块综合信号进行交易
def my_trade(context):
    #获取选股列表并过滤掉:st,st*,退市,涨停,跌停,停牌
    check_out_list = get_stock_list(context)
    check_out_list = filter_limitup_stock(context, check_out_list)
    check_out_list = filter_limitdown_stock(context, check_out_list)
    check_out_list = filter_paused_stock(check_out_list)
    check_out_list = check_out_list[:g.stock_num]
    print('今日自选股:{}'.format(check_out_list))
    #调仓
    '''
    adjust_position(context, check_out_list)
    '''
    g.timing_signal = get_timing_signal(context,g.ref_stock)
    if g.timing_signal == 'SELL':
        for stock in context.portfolio.positions:
            position = context.portfolio.positions[stock]
            close_position(position)
    elif g.timing_signal == 'BUY' or g.timing_signal == 'KEEP':
            adjust_position(context, check_out_list)
    else: pass
    
    record(cash=context.portfolio.available_cash/context.portfolio.total_value*100) 


#5-1 复盘模块-打印
#打印每日持仓信息
def print_trade_info(context):
    #打印当天成交记录
    trades = get_trades()
    for _trade in trades.values():
        print('成交记录：'+str(_trade))
    #打印账户信息
    for position in list(context.portfolio.positions.values()):
        securities=position.security
        cost=position.avg_cost
        price=position.price
        ret=100*(price/cost-1)
        value=position.value
        amount=position.total_amount    
        print('代码:{}'.format(securities))
        print('成本价:{}'.format(format(cost,'.2f')))
        print('现价:{}'.format(price))
        print('收益率:{}%'.format(format(ret,'.2f')))
        print('持仓(股):{}'.format(amount))
        print('市值:{}'.format(format(value,'.2f')))
        print('———————————————————————————————————')
    print('———————————————————————————————————————分割线————————————————————————————————————————')
    
# 后备股票池进行综合排序筛选
def get_stock_rank_m_m(context,stock_list):
    rank_stock_list = get_fundamentals(query(
        valuation.code, valuation.market_cap, valuation.circulating_market_cap
        ).filter(valuation.code.in_(stock_list)
        ).order_by(valuation.circulating_market_cap.asc()).limit(100))
        
    # 5日累计成交量
    volume5d = [attribute_history(stock, 1200, '1m', 'volume', df=False)['volume'].sum() for stock in rank_stock_list['code']]
    # 60日涨幅
    increase60d = [get_growth_rate60(stock,80) for stock in rank_stock_list['code']]
    #print("涨幅：{0}".format(increase60d))
    # 当前价格
    current_price = [get_close_price(stock, 1, '1m') for stock in rank_stock_list['code']]
    
    # 当前价格最低的
    min_price = min(current_price)
    
    # 60日涨幅最小的
    min_increase60d = min(increase60d)
    
    # 流通市值最小的
    min_circulating_market_cap = min(rank_stock_list['circulating_market_cap'])
    
    # 总市值最小的
    min_market_cap = min(rank_stock_list['market_cap'])
    
    # 5日累计成交量最小的
    min_volume = min(volume5d)

    # 按权重各项取对数累加
    #最小值/单个值肯定小于1，自然对色的结果肯定是负数，数字越小表示单个值比最小值越大
    totalcount = [[i, 
                            math.log(min_volume / volume5d[i]) * g.weights[3] + 
                            math.log(min_price / current_price[i]) * g.weights[2] + 
                            math.log(min_circulating_market_cap / rank_stock_list['circulating_market_cap'][i]) * g.weights[1] + 
                            math.log(min_market_cap / rank_stock_list['market_cap'][i]) * g.weights[0] + 
                            math.log(min_increase60d / increase60d[i]) * g.weights[4]] 
                            
                for i in rank_stock_list.index]
    
    # 累加后排序
    totalcount.sort(key=lambda x:x[1])
    # 保留最多g.sellrank设置的个数股票代码返回
    slist=[rank_stock_list['code'][totalcount[-1-i][0]] for i in range(min(g.sellrank, len(rank_stock_list)))]
    #剔除-触发上标准差的股票，如果大盘触发上标准差的情况下，个股触发标准差，就会有清空持仓的效果
    #slist=bzc(context,slist)
    return slist
    
# 获取股票现价和60日以前的价格涨幅    
def get_growth_rate60(code,s):
    price60d = attribute_history(code, s, '1d', 'close', False)['close'][0]
    pricenow = get_close_price(code, 1, '1m')
    #isnan() 判断是否是NaN
    if not isnan(pricenow) and not isnan(price60d) and price60d != 0:
        return pricenow / price60d
    else:
        return 100

# 获取前n个单位时间当时的收盘价
def get_close_price(code, n, unit='1d'):
    return attribute_history(code, n, unit, 'close', df=False)['close'][0]
