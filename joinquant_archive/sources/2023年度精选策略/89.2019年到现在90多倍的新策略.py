# 克隆自聚宽文章：https://www.joinquant.com/post/34521
# 标题：2019年到现在90多倍的新策略
# 作者：勤为径也

# 导入函数库
from __future__ import division
from jqdata import *
import datetime

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    set_option("match_by_signal", True) 
    set_option("avoid_future_data", True) # 避免未来数据
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')
    
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG') 
      # 开盘时或每分钟开始时运行
    run_daily(market_open, time='every_bar', reference_security='000300.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')

    g.pool=[]
    g.max_holding=2
    
## 开盘前运行函数     
def before_market_open(context):
    g.pool=select(context)
    
## 开盘时运行函数
def market_open(context):
    pass
 
## 收盘后运行函数  
def after_market_close(context):
    pass

def handle_data(context, data):
    cur_data=get_current_data()
    if(1031 > int(context.current_dt.strftime("%H%M")) > 930):
        if cur_data['000300.XSHG'].last_price>cur_data['000300.XSHG'].day_open:
            toBuy(context);
    if(int(context.current_dt.strftime("%H%M")) ==1450):
        toSell(context);

def toSell(context):
    curr_data = get_current_data()
    hour = context.current_dt.hour
    minute = context.current_dt.minute
    for stock in context.portfolio.positions:
        closeable_amount = context.portfolio.positions[stock].closeable_amount
        if closeable_amount > 0 and curr_data[stock].last_price < curr_data[stock].high_limit:  # 尾盘未涨停
            order_target(stock, 0)  # 卖出
            log.info("卖出： %s %s" % (curr_data[stock].name, stock))
                
def toBuy(context):
    if len(g.pool)==0:
        return
    curr_data = get_current_data()
    if(len(context.portfolio.positions)<g.max_holding):
        per_cash=context.portfolio.available_cash/(g.max_holding-len(context.portfolio.positions))
        for stock in g.pool:
            if stock in context.portfolio.positions:
                continue
            pre_close=attribute_history(stock, 1, '1d', ('close'))['close'][-1]
            if(len(context.portfolio.positions)<g.max_holding):
                if get_current_data()[stock].last_price>pre_close*1.09:
                    order_target_value(stock, per_cash)
                    log.info("买入： %s %s" % (curr_data[stock].name, stock))


## 选股
def select(context):
    endDate=context.previous_date
    trd_days = get_trade_days(end_date=endDate, count=365)
    security_list = get_all_securities('stock', trd_days[0]).index.tolist()
    stk_list=[s for s in security_list if not (s[:2]=='30' or s[:2]=='68')]
    p=get_price(stk_list, count = 120, end_date=endDate, frequency='daily', fields=['close','pre_close','high_limit'])
    df_ZT=(p['close'].iloc[-1]==p['high_limit'].iloc[-1]) & (p['high_limit'].iloc[-1]/p['pre_close'].iloc[-1]>1.09)
    up_limit_list=list(df_ZT[df_ZT==True].index)
    df_250=(p['close'].iloc[-1]<p['close'].max()) & (p['close'].iloc[-1]*1.07>p['close'].max())
    up_max250_list=list(df_250[df_250==True].index)

    temp_list=[]
    if len(up_limit_list)/len(security_list)>0.01:
        temp_list= list(set(up_limit_list).intersection(up_max250_list))
        print(temp_list)
    return temp_list
    
    
    
##
