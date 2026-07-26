# 克隆自聚宽文章：https://www.joinquant.com/post/38623
# 标题：自适应量化终极算法2.0 （全新升级）
# 作者：JinnyKoo

# 导入函数库
import jqdata
from jqlib.technical_analysis  import *
from jqdata import *
import warnings
from datetime import date
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.cluster import KMeans
import time
import math
import datetime
from datetime import date

# 初始化函数
def initialize(context):
    # 滑点高（不设置滑点的话用默认的0.00246）
    set_slippage(FixedSlippage(0.02))
    # 沪深300
    set_benchmark('000300.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    warnings.filterwarnings("ignore")

    # 选股参数
    g.freq = 7
    g.count = 0
    g.position = 1 # 仓位
    g.stock_num = 5
    # 手续费
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0005, close_commission=0.0005, min_commission=5), type='stock')
     
    # 设置交易时间
    run_daily(my_trade, time='9:45', reference_security='000300.XSHG')



# 开盘时运行函数
def my_trade(context):
    # 获取选股列表并过滤掉:st,st*,退市,涨停,跌停,停牌
    if g.count % g.freq == 0:
        check_out_list = get_stock_list(context)
        log.info('今日自选股:%s' % check_out_list)
        adjust_position(context, check_out_list)
    g.count += 1


# 2-2 选股模块
def get_stock_list(context):
    # type: (Context) -> list
    curr_data = get_current_data()
    yesterday = context.previous_date

    # 过滤次新股
    by_date =  yesterday - datetime.timedelta(days=365*3)  # 三年
    initial_list = get_all_securities(date=by_date).index.tolist()
    #initial_list = get_all_securities().index.tolist()
    
    # 食品加工和零售
    # initial_list = get_industry_stocks('C14') +  get_industry_stocks('F52') 
    # 全市场选股
    initial_list = get_all_securities().index.tolist()

    # 0. 过滤创业板，科创板，st，今天涨跌停的，停牌的
    initial_list = [stock for stock in initial_list if not (
            (curr_data[stock].day_open == curr_data[stock].high_limit) or
            (curr_data[stock].day_open == curr_data[stock].low_limit) or
            curr_data[stock].paused or
            curr_data[stock].is_st or
            ('ST' in curr_data[stock].name) or
            ('*' in curr_data[stock].name) or
            ('退' in curr_data[stock].name) or
            (stock.startswith('300')) or
            (stock.startswith('688')) or
            (stock.startswith('002'))
    )]
     # 选出小市值股票，取20%，不然股票数量太多, 有超时错误。
     # 小市值股票也更容易被操盘
    q = query(
        valuation.code,
        valuation.market_cap
    ).filter(
        valuation.code.in_(initial_list)
    ).order_by(
        valuation.market_cap.asc()
    )
    df = get_fundamentals(q)
    initial_list =list(df['code'])[:int(0.2*len(list(df.code)))]
    
    
    # 几个关键参数
    pattern_length = 7  # 选择的形态长度
    predict_window = g.freq  # 预测时间窗口
    num_prototypes = 5   # K 的值
    threshold = 0.1      # 上涨阈值，0.1 代表在predict window 窗口内上涨至少10%
    today = date.today()
    centers, sum_se, sum_dis = get_dtw_centers(initial_list, threshold, predict_window, pattern_length,yesterday, K=num_prototypes)
    # print(sum_se, sum_dis)
    # sum_dis = 2.5
    stocks_to_buy = pattern_match(initial_list, centers, pattern_length, yesterday, sum_dis)
    stocks_buy = [k for k, v in sorted(stocks_to_buy.items(), key=lambda item: item[1])]
    
    return stocks_buy[:g.stock_num]


def adjust_position(context, buy_stocks):
    #order_value(g.bond,context.portfolio.available_cash)
    for stock in context.portfolio.positions:
        if stock not in buy_stocks:
            order_target(stock, 0)
        
    #
    position_count = len(context.portfolio.positions)
    if g.stock_num > position_count:
        value = context.portfolio.cash * g.position / (g.stock_num - position_count)
        for stock in buy_stocks:
            if stock not in context.portfolio.positions:
                order_target_value(stock, value)
                if len(context.portfolio.positions) == g.stock_num:
                    break

# implementation borrowed from  
# https://nbviewer.org/github/alexminnaar/time-series-classification-and-clustering/blob/master/Time%20Series%20Classification%20and%20Clustering.ipynb
def DTWDistance(s1, s2,w):
    DTW={}
    
    w = max(w, abs(len(s1)-len(s2)))
    
    for i in range(-1,len(s1)):
        for j in range(-1,len(s2)):
            DTW[(i, j)] = float('inf')
    DTW[(-1, -1)] = 0
  
    for i in range(len(s1)):
        for j in range(max(0, i-w), min(len(s2), i+w)):
            dist= (s1[i]-s2[j])**2
            DTW[(i, j)] = dist + min(DTW[(i-1, j)],DTW[(i, j-1)], DTW[(i-1, j-1)])
    return math.sqrt(DTW[len(s1)-1, len(s2)-1])
    

def LB_Keogh(s1,s2,r):
    LB_sum=0
    for ind,i in enumerate(s1):
        
        lower_bound=min(s2[(ind-r if ind-r>=0 else 0):(ind+r)])
        upper_bound=max(s2[(ind-r if ind-r>=0 else 0):(ind+r)])
        
        if i>upper_bound:
            LB_sum=LB_sum+(i-upper_bound)**2
        elif i<lower_bound:
            LB_sum=LB_sum+(i-lower_bound)**2
    
    return math.sqrt(LB_sum)
 
   
def k_means_clust(data,num_clust,num_iter,w=5):
    centroids=random.sample(data.tolist(), num_clust)
    counter=0
    for n in range(num_iter):
        counter+=1
        print('iteration: {}'.format(counter))
        assignments={}
        #assign data points to clusters
        for ind,i in enumerate(data):
            min_dist=float('inf')
            closest_clust=None
            for c_ind,j in enumerate(centroids):
                if LB_Keogh(i,j,5)<min_dist:
                    cur_dist=DTWDistance(i,j,w)
                    if cur_dist<min_dist:
                        min_dist=cur_dist
                        closest_clust=c_ind
            if closest_clust in assignments:
                assignments[closest_clust].append(ind)
            else:
                assignments[closest_clust]=[]
    
        #recalculate centroids of clusters
        for key in assignments:
            clust_sum=np.zeros(len(data[0]))
            for k in assignments[key]:
                clust_sum=clust_sum+data[k]
            centroids[key]=[m/len(assignments[key]) for m in clust_sum]
    
    return centroids, assignments


def trend(prices, threshold):
    try:
        x = np.array(range(len(prices))).reshape(-1, 1)
        y = prices
        reg = LinearRegression().fit(x, y)
        #print(reg.coef_)
        if y[0] == 0:
            return -1
        if reg.coef_[0] > 0 and (y[-1] - y[0]) / y[0] >= threshold:
            return 1
        else:
            return -1
    except: # 可能含有NaN
        return -1

# 从后往前扫描量价数据
# 如果在predict window 里面价格上涨，将之前pattern length 长度部分量价等形态保存
def pattern_scan(df, threshold, predict_window, pattern_length):
    res = []
    prices = df['close'].tolist()
    i = len(prices) - 1
    while i > predict_window + pattern_length - 1:
        predict_end = i
        predict_start = i - predict_window + 1
        pattern_end = predict_start - 1
        pattern_start = pattern_end - pattern_length + 1
        if trend(prices[predict_start:predict_end+1], threshold) > 0:
            res.append([df.index[pattern_start], df.index[pattern_end],
                        df.index[predict_start], df.index[predict_end]])
            i = pattern_start - 1
        else:
            i -= 1
    return res
    
    
# 对量价数据进行正则化操作
def normalize(df, patterns):
    normalized_patterns = []
    for r in patterns:
        pattern_start, pattern_end = r[0], r[1]
        df_features = df.loc[pattern_start:pattern_end]
        open_price = (df_features.open / df_features.open[0]).astype('float64')
        close_price = (df_features.close / df_features.close[0]).astype('float64')
        high_price = (df_features.high / df_features.high[0]).astype('float64')
        low_price = (df_features.low / df_features.low[0]).astype('float64')
        volume = (df_features.volume / df_features.volume[0]).astype('float64')
        
        features_data = {'open': open_price, 'high': high_price, 'low': low_price, 'close': close_price,
                         'volume': volume}
        features_df = pd.DataFrame(features_data)
        # features_np = features_df.to_numpy()
        features_np = features_df.values
        flat_features = features_np.reshape(-1)
        normalized_patterns.append(flat_features.tolist())
    return normalized_patterns
    
    
# 对保存的形态进行聚类操作， 使用聚类算法如DTW
def get_dtw_centers(stocks, threshold, predict_window, pattern_length, end_date,K=5):
    all_patterns = []
    s = time.time()
    start_date = end_date -  datetime.timedelta(days=365*3)

    for stock in stocks:
        df = get_price(stock, start_date=start_date,
               end_date=end_date, frequency='daily', fields=None, 
               skip_paused=False, fq='pre', panel=True)
        df = df.iloc[::-1]
        res = pattern_scan(df, threshold, predict_window, pattern_length)
        patterns = normalize(df, res)
        all_patterns += patterns
    se = time.time()
    print("pattern scan time = {}".format(se - s))
    X = np.array(all_patterns)
    X = pd.DataFrame(X).dropna().values
    centers, assigns =k_means_clust(X, 5, 10, 4)
    sum_dis = 0
    for i, t in enumerate(X):
        for k in assigns.keys():
            if i in assigns[k]:
                sum_dis += np.linalg.norm(centers[k] - X[i])
                break
    ce = time.time()
    print("Clustering time = {}".format(ce - se))
    #return centers
    return centers, sum_dis / len(X), sum_dis / len(X)

# 扫描股票，如果发现当前的形态（pattern length） 与 KNN 发现的prototype 之间的距离小于某个阈值，则认定发现上涨趋势的
# 形态，将股票放入待购买股票列表中
def pattern_match(stocks, patterns, pattern_length, end_date, dis):
    start_date = end_date -  datetime.timedelta(days=300) # 300 is a large number to make sure there are enough samples
    # end_date = end_date.strftime("%Y-%m-%d")
    # stocks_buy = []
    stocks_to_buy = {}
    for stock in stocks:
        df = get_price(stock, start_date=start_date,
                       end_date=end_date, frequency='daily', fields=None, 
                       skip_paused=False, fq='pre', panel=True)
        df = df.iloc[::-1]
        current_shape = df.iloc[:pattern_length]     
        df_features = current_shape
        open_price = (df_features.open / df_features.open[0]).astype('float64')
        close_price = (df_features.close / df_features.close[0]).astype('float64')
        high_price = (df_features.high / df_features.high[0]).astype('float64')
        low_price = (df_features.low / df_features.low[0]).astype('float64')
        volume = (df_features.volume / df_features.volume[0]).astype('float64')
        features_data = {'open': open_price, 'high': high_price, 'low': low_price, 'close': close_price,
                         'volume': volume}
        features_df = pd.DataFrame(features_data)
        features_np = features_df.values # update to use to_numpy()
        flat_features = features_np.reshape(-1)

        ds = []
        for p in patterns:
            ds.append(np.linalg.norm(p - flat_features))
        #print(ds)
        if np.min(ds) < dis:
            stocks_to_buy[stock] = np.min(ds)
    return stocks_to_buy
                
