# 克隆自聚宽文章：https://www.joinquant.com/post/45845
# 标题：SVR机器学习上证综指择时中小板财务选股策略
# 作者：快乐一生

from jqdata import *
import numpy as np
from sklearn.svm import SVR
import pandas as pd

#初始化函数 
def initialize(context):
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)  # 避免引入未来信息
    #set_slippage(PriceRelatedSlippage(0.002))
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0001, close_commission=0.0001, close_today_commission=0, min_commission=5),
                   type='fund')
    log.set_level('order', 'error')
    set_benchmark('000300.XSHG')
    
    g.stock_num = 10 #买入评分最高的前stock_num只股票
    g.curstaut = 0  # 0 当前空仓出BUY时买进  1 满仓出SELL时卖出
    # g.ref_stock = '399101.XSHE' 
    g.ref_stock = '000001.XSHG' 
    g.N = 18 # 计算最新斜率slope，拟合度r2参考最近N天
    g.M = 600 # 计算最新标准分zscore，rsrs_score参考最近M天(600)
    g.K = 8 # 计算 zscore 斜率的窗口大小
    #择时模块 
    g.hold_stock = 'null'
    g.score_thr = -1#-0.68 # rsrs标准分指标阈值
    g.score_fall_thr = -0.5#-0.43 # 当股票下跌趋势时候， 卖出阀值rsrs
    g.idex_slope_raise_thr = 10#12 # 判断大盘指数强势的斜率门限
    
    g.slope_series,g.rsrs_score_history= initial_slope_series() # 除去回测第一天的slope，避免运行时重复加入

    run_daily(my_trade_prepare, time='9:00', reference_security='000300.XSHG')
    run_daily(my_trade, time='9:30', reference_security='000300.XSHG')

                
# 初始化准备数据,除去回测第一天的slope,zscores
def initial_slope_series():
    length = g.N+g.M+g.K
    data = attribute_history(g.ref_stock, length, '1d', ['high', 'low', 'close'])
    multe_data = [get_ols(data.low[i:i+g.N], data.high[i:i+g.N]) for i in range(length-g.N)]
    slopes = [i[1] for i in multe_data]
    r2s = [i[2] for i in multe_data]
    zscores =[(get_zscore(slopes[i+1:i+1+g.M])*r2s[i+g.M])  for i in range(g.K)]
    return (slopes,zscores)
    
## 线性回归：复现statsmodels的get_OLS函数
def get_ols(x, y):
    slope, intercept = np.polyfit(x, y, 1)
    r2 = 1 - (sum((y - (slope * x + intercept))**2) / ((len(y) - 1) * np.var(y, ddof=1)))
    return (intercept, slope, r2)   #斜率、截距、可解释性

## 因子标准化   最新的标准化
def get_zscore(slope_series):
    mean = np.mean(slope_series)
    std = np.std(slope_series)
    return (slope_series[-1] - mean) / std

def get_zscore_slope(z_scores):
    y = z_scores
    x = np.arange(len(z_scores))
    slope, intercept = np.polyfit(x, y, 1)
    return slope
    
# 只看RSRS因子值作为买入、持有和清仓依据，前版本还加入了移动均线的上行作为条件
#这里的大盘择时，提供了第一顺位的超额收益
def get_timing_signal(context,stock):
    #大盘收盘价一阶导数用作择时
    data = attribute_history(g.ref_stock, g.N, '1d', ['high', 'low', 'close'])  #获取g.N天的标的三价格
    intercept, slope, r2 = get_ols(data.low, data.high) #线性三个参数：截距、斜率、可解释度?
    print('intercept, slope, r2',intercept, slope, r2)
    g.slope_series.append(slope)
    # print('g.slope',g.slope_series)
    #这里这个score为何乘以r2，个人推测为对数据进行可信度修正。
    rsrs_score = get_zscore(g.slope_series[-g.M:]) * r2     #标准化打分
    g.rsrs_score_history.append(rsrs_score)
    print('g.rsrs_score_history',g.rsrs_score_history)
    #对近期的rsrs_score进行线性斜率分析
    rsrs_slope = get_zscore_slope(g.rsrs_score_history[-g.K:])
    print('rsrs_slope',rsrs_slope)
    #大盘指数收盘价趋势
    idex_slope = np.polyfit(np.arange(8), data.close[-8:],1)[0].real
    g.slope_series.pop(0)
    g.rsrs_score_history.pop(0)
    
    log.info('rsrs_slope {:.3f}'.format(rsrs_slope)+' rsrs_score {:.3f} '.format(rsrs_score)
    +' idex_slope {:.3f} '.format(idex_slope))
    #动量斜率下行了 ，即将出现下跌
    if(rsrs_slope< 0 and rsrs_score >0):
        return "SELL"
    #指数下行+动量斜率上行+当前动量已小于下跌值了 
    if(idex_slope<0) and (rsrs_slope>0) and (rsrs_score < g.score_fall_thr): return "SELL"
    #大盘上升过程当中，大胆买入
    if(idex_slope>g.idex_slope_raise_thr) and (rsrs_slope>0): return "BUY"
    #大盘可能上涨，这个时候可以买入
    if (rsrs_score> g.score_thr) : return "BUY"
    #elif(idex_slope > 5) : return "BUY"
    else: return "SELL"


#4-2 交易模块-开仓
#买入指定价值的证券,报单成功并成交(包括全部成交或部分成交,此时成交量大于0)返回True,报单失败或者报单成功但被取消(此时成交量等于0),返回False
def open_position(security, value):
	order = order_target_value(security, value)
	if order != None and order.filled > 0:
		return True
	return False

#4-3 交易模块-平仓
#卖出指定持仓,报单成功并全部成交返回True，报单失败或者报单成功但被取消(此时成交量等于0),或者报单非全部成交,返回False
def close_position(position):
	security = position.security
	order = order_target_value(security, 0)  # 可能会因停牌失败
	if order != None:
		if order.status == OrderStatus.held and order.filled == order.amount:
			return True
	return False

#4-1 判断今天是否为账户资金再平衡的日期
def today_is_between(context, start_date, end_date):
    today = context.current_dt.strftime('%m-%d')
    if (start_date <= today) and (today <= end_date):
        # send_dingding('一月跟四月对小市值股票不友好，注意风险！')
        print('一月跟四月对小市值股票不友好，注意风险！')
        return True
    else:
        return False
        
def adjust_position(context, buy_stocks):
    for stock in context.portfolio.positions:
        if stock not in buy_stocks:
            position = context.portfolio.positions[stock]
            close_position(position)
            g.hold_stock = 'null'
        else:
            pass
    #log.info("[%s]已经持有无需重复买入" % (stock))
    position_count = len(context.portfolio.positions)
    if g.stock_num > position_count:
        value = context.portfolio.cash / (g.stock_num - position_count)
        for stock in buy_stocks:
            if context.portfolio.positions[stock].total_amount == 0:
                if open_position(stock, value):
                    if len(context.portfolio.positions) == g.stock_num:
                        g.hold_stock = stock
                        break

def tobuy_stocks(context, buy_stocks):
    position_count = len(context.portfolio.positions)
    if g.stock_num > position_count:
        value = context.portfolio.cash / (g.stock_num - position_count)
        for stock in buy_stocks:
            if context.portfolio.positions[stock].total_amount == 0:
                if open_position(stock, value):
                    if len(context.portfolio.positions) == g.stock_num:
                        g.hold_stock = stock
                        break

# 计算待买入的ETF和择时信号,判断股票动量变化一阶导数, 如果变化太大，则空仓
def my_trade_prepare(context):
    hour = context.current_dt.hour
    minute = context.current_dt.minute
    # 计算当前大盘择时信号
    g.timing_signal = get_timing_signal(context,g.ref_stock)
    if today_is_between(context, '04-05', '04-30'):
        g.timing_signal = 'SELL'
    # g.timing_signal = 'BUY'  # 不用择时
    print(f'今日择时信号:{g.timing_signal}')
    today_prepare(context)
    print('今日自选:')
    print(g.check_out_list)
    


# 交易主函数，先确定ETF最强的是谁，然后再根据择时信号判断是否需要切换或者清仓
def my_trade(context):
    adjust_position(context, g.check_out_list)

def _get_stocks(index_list, dt_date):
    stocks = []
    for index in index_list:
        stocks = stocks + get_index_stocks(index, dt_date)
    stocks = sorted(list(set(stocks))) # filter duplicate, sorted
    return stocks
    
def today_prepare(context):
    # parameter
    n_position = g.stock_num # 持股数
    n_choice = int(1.2*n_position) # 选股数，20%缓冲
    # n_choice = n_position+1 # 选股数，1缓冲

    cdata  = get_current_data() # 获取当前股票数据
    dt_last = context.previous_date # 获取上一个交易日
    
    # 全A市场选股
    # index = '399317.XSHE' # 市场指数
    # stocks = get_index_stocks(index, dt_last) # 获取指数成分股

    # # # 多个指数股集合
    index_list = [
        '399101.XSHE', # 中小板综指
        ]
    # 选股范围 
    stocks = _get_stocks(index_list, dt_last)
    q = query(
            valuation.code,
            valuation.market_cap,  # 市值log_mc
            valuation.pb_ratio > 0,
            indicator.inc_return > 0,
            indicator.inc_total_revenue_year_on_year > 0,
            indicator.inc_net_profit_year_on_year > 0,
            indicator.ocf_to_operating_profit > 5, #经营活动产生的现金流量净额/经营活动净收益 大于5%
        ).filter(
            valuation.code.in_(stocks),
            balance.total_assets > balance.total_liability,
            income.net_profit > 0,
        )
        
    # 获取符合条件的股票的基本面数据，并设置股票代码为索引
    df = get_fundamentals(q, dt_last).fillna(0).set_index('code') # 获取基本面数据，填充缺失值并设置索引
    df = df.fillna(0)  # 填充缺失值
    # 仅保留需要的列，重命名列名
    df.columns = ['log_mc', 'log_NC', 'log_NI', 'log_RD', 'PE','OCF'] # 重命名列名
    # sign ln
    def _sign_ln(X): # 定义 sign ln 函数
        return sign(X) * np.log(1.0 + abs(X))
    # factor value
    df['log_mc'] = _sign_ln(df['log_mc']) # 对数化处理
    df['log_NC'] = _sign_ln(df['log_NC'])
    df['log_NI'] = _sign_ln(df['log_NI'])
    df['log_RD'] = _sign_ln(df['log_RD'])
    df['PE']     = _sign_ln(df['PE'])
    df['OCF']    = _sign_ln(df['OCF'])
    
    # industry factor
    industry_list = get_industries('sw_l1', dt_last).index.tolist() # 获取行业列表
    for sector in industry_list: # 遍历行业列表
        istocks = get_industry_stocks(sector, dt_last) # 获取该行业的股票
        s = pd.Series(0, index=df.index) # 创建一个和 df 索引相同的 Series，用于存储行业因子
        s[set(istocks) & set(df.index)] = 1 # 将行业因子标记为 1
        df[sector] = s # 将行业因子加入到 df 中
    # SVR model
    svr = SVR(kernel='rbf') # 创建支持向量回归模型
    # training model 
    Y = df['log_mc'] # 目标变量为 log_mc 总市值为目标
    X = df.drop('log_mc', axis=1) # 特征变量为除 log_mc 列以外的其他列
    model = svr.fit(X, Y) # 训练模型
    # choice
    r = Y - pd.Series(svr.predict(X), Y.index) # 计算预测误差
    # print('排序前')
    # print(r)
    r = r[r < 0].sort_values().head(n_choice) # 选取预测误差最小的 n_choice 个股票
    # print('排序并选择后')
    # print(r)
    choice = r.index.tolist() # 将选股结果转换为列表
    # choice = stocks  # 全选对比
    # 提前输出信息供人工核对参考
    # sell list
    mesg_check = '今日盘前操作提示:\n卖出:VVVVV\n'
    for s in context.portfolio.positions: # 遍历当前持仓
        if s not in choice: # 如果股票不在选股结果中
            log.info('to sell', s, cdata[s].name) # 输出卖出信息
            mesg_check += "%s %s\n" % (s, cdata[s].name)
    # buy list
    mesg_check += '买进:VVVVV\n'
    for s in choice: # 遍历选股结果
        if s not in context.portfolio.positions: # 如果股票不在当前持仓中
            log.info('to buy', s, cdata[s].name) # 输出买入信息
            mesg_check += "%s %s\n" % (s, cdata[s].name)
    # send_dingding(mesg_check)       
    # save results
    if g.curstaut == 0:
        if g.timing_signal == "BUY":
            g.check_out_list = choice # 将选股结果存储到 g.choice 中
            g.curstaut = 1
        else:
            g.check_out_list = []
    else:
        if g.timing_signal == "SELL":
            g.check_out_list = []
            g.curstaut = 0
        else:
            g.check_out_list = choice # 将选股结果存储到 g.choice 中


#2-6 过滤科创北交标的
def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68':
            stock_list.remove(stock)
    return stock_list

# 2-2 过滤ST及其他具有退市标签的标的
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not (
            current_data[stock].is_st or
            'ST' in current_data[stock].name or
            '*' in current_data[stock].name or
            '退' in current_data[stock].name)]

# 过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]

# 过滤创业版、科创版股票
def filter_gem_stock(context, stock_list):
    return [stock for stock in stock_list if stock[0:3] != '300' and stock[0:3] != "688"]

# 过滤次新股
def filter_new_stock(context, stock_list):
    return [stock for stock in stock_list if (context.previous_date - datetime.timedelta(days=300)) > get_security_info(stock).start_date]
