# 克隆自聚宽文章：https://www.joinquant.com/post/36975
# 标题：短线策略-2022年两个半月收益45%-无未来函数
# 作者：zk001

# 克隆自聚宽文章：https://www.joinquant.com/post/36906
# 标题：2022年三个月收益51%，超短线实盘交易策略！无未来函数
# 作者：御风起浪

# 克隆自聚宽文章：https://www.joinquant.com/post/36786
# 标题：14个月200%，超短线实盘交易策略！无未来函数
# 作者：随波逐浪9

# 导入函数库
from jqdata import *
from jqlib.technical_analysis import *
import numpy as np
from datetime import datetime
# 初始化函数，设定基准等等
def initialize(context):
    enable_profile()
    # log.set_level('order', 'error')
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 关闭未来函数
    # set_option("avoid_future_data", True)
    
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 设置交易成本万分之三
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),type='fund')
    # 股票购买限制
    g.buy_stock_limit = 1

def initHandleParam():
    g.buy_list = []

## 开盘前运行函数
def before_trading_start(context):
    # 初始化参数
    initHandleParam()
    
    start = datetime.now()
    
    # 获取股票池
    prev_date = context.previous_date
    stock_pool=get_stock_pool(prev_date)
    
    # 通过不同的条件筛选股票
    dx1 = stock_filter1(stock_pool,prev_date)
    print('dx1:{}'.format(len(dx1)))
    
    dx2 = stock_filter2(dx1,prev_date)
    print('dx2:{}'.format(len(dx2)))
    
    dx3 = stock_filter3(dx2,prev_date)
    print('dx3:{}'.format(len(dx3)))
    
    dx4 = stock_filter4(dx3,prev_date)
    print('dx4:{}'.format(len(dx4)))
    
    end = datetime.now()
    print('选股{}'.format(end-start))
    
    g.buy_list = dx4
    g.buy_list.sort()
    print('%s:共找到%d只股票可以购买.%s'%(context.current_dt,len(g.buy_list),g.buy_list))


## 开盘时运行函数
def handle_data(context,data):
    
    start = datetime.now()
    
    current_data = get_current_data()
    # 卖出
    for stock in context.portfolio.positions.keys():
        # 如果在买入列表中，则跳过
        if stock in g.buy_list:
            continue
        
        # 如果可卖出仓位为0，或者跌停、涨停，则跳过
        price = data[stock].close
        if context.portfolio.positions[stock].closeable_amount == 0  \
        or current_data[stock].low_limit == price \
        or current_data[stock].high_limit == price \
        :
            continue
        
        # 否则，清空该股票
        print('%s卖出(自动):自动卖出:成本价:%s,当前价:%s'%(stock,context.portfolio.positions[stock].avg_cost,price))
        sell_stock(stock,0)

    # 判断是否买满
    if g.buy_stock_limit <= len(context.portfolio.positions.keys()):
        return 
    
    # 买入
    for stock in g.buy_list:
        price = data[stock].close
        if context.portfolio.available_cash < (price * 100) \
        or current_data[stock].low_limit == price \
        or current_data[stock].high_limit == price \
        or stock in context.portfolio.positions.keys() \
        :
            continue
        print('%s买入(自动):自动买入:当前价:%s'%(stock,price))
        buy_stock(context,stock)
    
    end = datetime.now()
    print('交易{}'.format(end-start))

####################################买卖操作######################################
# 购买股票
def buy_stock(context,stock):
    # 计算今天还需要买入的股票数量
    need_count = g.buy_stock_limit - len(context.portfolio.positions.keys())
    if need_count == 0:
        return
    # 把现金分成几份,
    buy_cash = context.portfolio.available_cash / need_count
    # 买入这么多现金的股票
    order_value(stock, buy_cash)
    # 记录这次买入
    # log.info("购买： %s" % (stock))
#出售股票
def sell_stock(stock,value):
    # 全部卖出
    order_target(stock, value)
    # 记录这次卖出
    # log.info("卖出： %s" % (stock))


####################################选股操作######################################

def get_stock_pool(cur_date):
    '''
        获取指定日期的股票池
    '''
    
    # 获取全部股票
    df_all_stocks = get_all_securities(['stock'],cur_date)[['display_name']]
    
    # 过滤创业板(30开头)、科创板(688开头)、北交所上市(82、83、87、88开头)
    filter1 = (df_all_stocks.index.str.startswith('30'))|(df_all_stocks.index.str.startswith('688'))|(df_all_stocks.index.str.startswith('8'))
    
    # 过滤ST、*、退市股票
    filter2 = df_all_stocks.display_name.str.contains('ST|\*|退')
    
    filtered_stocks = df_all_stocks.loc[(~filter1)&(~filter2)].index.tolist()
    return filtered_stocks


def stock_filter1(stock_pool,cur_date):
    '''
        过滤条件1：利用均值和成交量
            收盘价ma20、ma30上升，前日ma5>ma10，昨日ma5<ma10
            成交量前日ma5>ma10，昨日ma5的1.2倍>ma10
    '''
    
    def caculate_close_ma(stock_data):
        prev1_ma5 = stock_data.iloc[-5:].mean()
        prev1_ma10 = stock_data.iloc[-10:].mean()
        prev1_ma20 = stock_data.iloc[-20:].mean()
        prev1_ma30 = stock_data.iloc[-30:].mean()

        prev2_ma5 = stock_data.iloc[-6:-1].mean()
        prev2_ma10 = stock_data.iloc[-11:-1].mean()
        prev2_ma20 = stock_data.iloc[-21:-1].mean()
        prev2_ma30 = stock_data.iloc[-31:-1].mean()
        return prev1_ma5,prev1_ma10,prev1_ma20,prev1_ma30,prev2_ma5,prev2_ma10,prev2_ma20,prev2_ma30

    def caculate_close_ma_5_10(stock_data):
        prev1_ma5 = stock_data.iloc[-5:].mean()
        prev1_ma10 = stock_data.iloc[-10:].mean()

        prev2_ma5 = stock_data.iloc[-6:-1].mean()
        prev2_ma10 = stock_data.iloc[-11:-1].mean()
        return prev1_ma5,prev1_ma10,prev2_ma5,prev2_ma10

    def caculate_close_ma_20_30(stock_data):
        prev1_ma20 = stock_data.iloc[-20:].mean()
        prev1_ma30 = stock_data.iloc[-30:].mean()

        prev2_ma20 = stock_data.iloc[-21:-1].mean()
        prev2_ma30 = stock_data.iloc[-31:-1].mean()
        return prev1_ma20,prev1_ma30,prev2_ma20,prev2_ma30

    def caculate_volume_ma(stock_data):
        prev1_ma5 = stock_data.iloc[-5:].mean()
        prev1_ma10 = stock_data.iloc[-10:].mean()

        prev2_ma5 = stock_data.iloc[-6:-1].mean()
        prev2_ma10 = stock_data.iloc[-11:-1].mean()
        return prev1_ma5,prev1_ma10,prev2_ma5,prev2_ma10

    # 获取股票，并转换形状
    price_raw=get_price(security=stock_pool, end_date=cur_date, frequency='daily', fields=['close','volume'], count=31, panel=False,skip_paused=False)
    close=price_raw.pivot(index='time',columns='code',values='close')
    volume=price_raw.pivot(index='time',columns='code',values='volume')
    
    # 方式1：
#     # 按股票计算均值
#     stock_ma=pd.DataFrame()
#     stock_ma[['close_prev1_ma5','close_prev1_ma10','close_prev1_ma20','close_prev1_ma30','close_prev2_ma5','close_prev2_ma10','close_prev2_ma20','close_prev2_ma30']]=close.apply(caculate_close_ma,axis=0,result_type="expand").T
#     stock_ma[['volume_prev1_ma5','volume_prev1_ma10','volume_prev2_ma5','volume_prev2_ma10']]=volume.apply(caculate_volume_ma,axis=0,result_type="expand").T

#     # 按条件选择股票
#     # 收盘价ma20、ma30上升，前日ma5>ma10，昨日ma5<ma10
#     # 成交量前日ma5>ma10，昨日ma5的1.2倍>ma10
#     condition = (stock_ma['close_prev1_ma20']>stock_ma['close_prev2_ma20']) \
#             & (stock_ma['close_prev1_ma30']>stock_ma['close_prev2_ma30']) \
#             & (stock_ma['close_prev2_ma5']>stock_ma['close_prev2_ma10']) \
#             & (stock_ma['close_prev1_ma5']<stock_ma['close_prev1_ma10']) \
#             & (stock_ma['volume_prev2_ma5']>stock_ma['volume_prev2_ma10']) \
#             & ((stock_ma['volume_prev1_ma5']*1.2)>stock_ma['volume_prev1_ma10'])

#     stock_list = stock_ma[condition].index.tolist()

    # 方式2：逐级缩小计算的股票规模，速度快一些
    # 先筛选 ma5下穿ma10
    stock_ma=pd.DataFrame()
    stock_ma[['close_prev1_ma5','close_prev1_ma10','close_prev2_ma5','close_prev2_ma10']]=close.apply(caculate_close_ma_5_10,axis=0,result_type="expand").T
    condition1 = (stock_ma['close_prev2_ma5']>stock_ma['close_prev2_ma10']) \
        & (stock_ma['close_prev1_ma5']<stock_ma['close_prev1_ma10'])
    stocks1 = stock_ma[condition1].index.tolist()
    close_cross_down = close[stocks1]
    # print(len(stocks1))

    # 再筛选 收盘价ma20、ma30上升
    stock_ma=pd.DataFrame()
    stock_ma[['close_prev1_ma20','close_prev1_ma30','close_prev2_ma20','close_prev2_ma30']]=close_cross_down.apply(caculate_close_ma_20_30,axis=0,result_type="expand").T
    condition2 = (stock_ma['close_prev1_ma20']>stock_ma['close_prev2_ma20']) \
        & (stock_ma['close_prev1_ma30']>stock_ma['close_prev2_ma30'])
    stocks2 = stock_ma[condition2].index.tolist()
    volume2 = volume[stocks2]
    # print(len(stocks2))

    # 最后筛选 成交量前日ma5>ma10，昨日ma5的1.2倍>ma10
    stock_ma=pd.DataFrame()
    stock_ma[['volume_prev1_ma5','volume_prev1_ma10','volume_prev2_ma5','volume_prev2_ma10']]=volume2.apply(caculate_volume_ma,axis=0,result_type="expand").T
    condition3 = (stock_ma['volume_prev2_ma5']>stock_ma['volume_prev2_ma10']) \
        & ((stock_ma['volume_prev1_ma5']*1.2)>stock_ma['volume_prev1_ma10'])

    stock_list = stock_ma[condition3].index.tolist()

    return stock_list

def stock_filter2(stock_pool,cur_date):
    '''
        macd_dif>0 macd_dea>0
        MACD 0到0.1之间
    '''
    if len(stock_pool)==0: return []
    stock_list = []
    macd_dif, macd_dea, macd_macd = MACD(security_list = stock_pool, check_date = cur_date, SHORT = 12, LONG = 26, MID = 9)
    for stock in stock_pool:
        # MACD 0到0.1之间
        if macd_dif[stock] > 0 and macd_dea[stock] > 0 \
        and 0 < macd_dif[stock]-macd_dea[stock] < 0.1 :
            stock_list.append(stock)
    return stock_list

def stock_filter3(stock_pool,cur_date):
    '''
        前日与昨日一跌一涨
    '''
    if len(stock_pool)==0: return []
    change_pct_raw=get_money_flow(security_list=stock_pool, end_date = cur_date,count = 2,fields=['sec_code','date','change_pct'])
    change_pct = change_pct_raw.pivot(index='sec_code',columns='date',values='change_pct')
    if change_pct.shape[0]==0 or change_pct.shape[1]!=2:
        return
    condition=(change_pct.iloc[:,-2]*change_pct.iloc[:,-1])<0
    stock_list=change_pct[condition].index.tolist()
    return stock_list

def stock_filter4(stock_pool,cur_date):
    '''
        开盘价低于昨日收盘价
    '''
    if len(stock_pool)==0: return []
    stock_list = []
    current_data=get_current_data()
    price=get_price(security=stock_pool, end_date=cur_date, frequency='1d', fields=['close'], count=1,panel=False, skip_paused=False)[['code','close']]
    for row in price.itertuples():
        code = getattr(row,'code')
        pre_close = getattr(row,'close')
        if current_data[code].day_open<pre_close:
            stock_list.append(code)
    return stock_list




                
