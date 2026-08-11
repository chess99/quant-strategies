# 克隆自聚宽文章：https://www.joinquant.com/post/45273
# 标题：别人“拿的住”的股票最赚钱
# 作者：hayy

# 导入函数库
from jqdata import *
from jqfactor import *
# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.0005, open_commission=0.0001, close_commission=0.0001, min_commission=1), type='stock')
    
    g.buyList = []
      # 开盘时运行
    #run_weekly(market_open, 1, time='open')
    run_monthly(market_open, 20, time='open')

## 运行函数
def market_open(context):
    # 加上大盘情绪衡量
    dp = attribute_history('000300.XSHG', 250, unit='1d',fields=['open', 'close', 'volume'],skip_paused=True, df=True, fq='pre')
    if dp.iloc[230:250,:].volume.mean() > np.percentile(dp.volume, 25):
        g.buyList = get_buyCode(context)
    else:
        g.buyList = []
    
    rebalance_position(context, g.buyList)

def get_buyCode(context):
    factor_series = pd.Series()
    vol_20 = pd.Series()
    for code in get_index_stocks('000300.XSHG'):
        min_data = attribute_history(code, 240*20, unit='1m',fields=['open', 'close', 'volume'],skip_paused=True, df=True, fq='pre')
        min_data.volume[min_data.volume<1] = 1
        min_data.insert(loc=0, column='log_v', value=np.log(min_data.volume)) 
        #高频波动率，日内分钟涨跌幅的标准差，20日20个数据
        vol_series = []
        for i in range(0,20):
            day_data = min_data[i*240:(i+1)*240]
            day_data = day_data.iloc[1:236,:]
            day_data.insert(loc=0, column='sy', value=day_data.close/day_data.open-1)  # 使用开盘价计算日内分钟收益
            vol_daily = weight_std(day_data.sy, day_data.log_v)  # 每日的收益率序列标准差 使用成交量加权
            #vol_daily = day_data.sy.std()  # 每日的收益率序列标准差
            vol_series.append(vol_daily)
        vol_series = pd.Series(vol_series)
        if vol_series.mean() == 0 : continue
        uid = vol_series.std()/vol_series.mean()
        factor_series[code] = uid
        
        #传统20日波动率
        d_data = attribute_history(code, 20, unit='1d',fields=['pre_close', 'close', 'volume'],skip_paused=True, df=True, fq='pre')
        d_data.insert(loc=0, column='sy', value=d_data.close/d_data.pre_close-1)
        vol_20[code] = d_data.sy.std()
      
    # 对传统波动率中性化取残差  
    slope, intercept = np.polyfit(vol_20, factor_series, 1)
    y_hut = slope*vol_20+intercept
    factor_series = factor_series-y_hut
    
    factor_series = factor_series.sort_values(ascending=True)
    return factor_series.index[0:10]

def weight_std (series, w):
    return np.sqrt((np.square(series-series.mean())*w).sum()/w.sum())

def rebalance_position(context, stock_list):
    current_holding = context.portfolio.positions.keys()
    stocks_to_sell = list(set(current_holding) - set(stock_list))
    # 卖出
    bulk_orders(stocks_to_sell, 0)
    total_value = context.portfolio.total_value

    if len(stock_list) >0 :
        # 买入
        bulk_orders(stock_list, total_value/len(stock_list))

# 批量买卖股票
def bulk_orders(stock_list,target_value):
    for i in stock_list:
        order_target_value(i, target_value)
