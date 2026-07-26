# 克隆自聚宽文章：https://www.joinquant.com/post/43051
# 标题：随机森林量价多因子选股 短线交易
# 作者：随云浪

'''
交易时间：当日09:30（买）- 次日14:59（卖）
其他设定：不考虑滑点，印花税1‰，佣金2.5‱、最低5元
'''
# 导入函数库
from jqdata import *
from jqlib.optimizer import *
from jqfactor import Factor
import numpy as np
import pandas as pd
#import jqfactor

#import cPickle as pickle
from six import BytesIO 
# import joblib

# 读取研究环境的预测结果
df = pd.read_csv(BytesIO(read_file("predict.csv")),index_col=0)
df2 = pd.read_csv(BytesIO(read_file("target.csv")),index_col=0)

mae_df = df-df2
mae_df = mae_df.abs().rolling(10).mean()
mae_df = mae_df.shift(2)
# 选top3
top = 5

# 双排序
# indexlist = df['2022-08':].index.tolist()
# dict_position = {}
# for x in indexlist:

#     temp = pd.concat([df.loc[x],-mae_df.loc[x]],axis=1,keys=['s1', 's2']).dropna()
    
#     dict_position[x] = temp.sort_values(by=['s1', 's2'],ascending=False).head(top).index.tolist()
    
# 预测值排序
indexlist = df['2022-08':].index.tolist()
dict_position = {}

for x in indexlist:
    # 排序选股
    temp = df.loc[x].sort_values(ascending=False).head(top).index.tolist()
    
    dict_position[x] = temp 

 
# print(dict_position)

# 开盘前运行函数
def before_market_open(context):
    '''
    盘后运行函数，可选实现
    '''


        
    if g.wait_list:
        # 等权买入
        # optimized_weight = pd.Series(data=[1.0/len(g.wait_list)]*len(g.wait_list),
        #                             index=g.wait_list)
        # 组合优化 最小风险                            
        optimized_weight = portfolio_optimizer(date=context.previous_date,
                                    securities = g.wait_list,
                                    target = MinVariance(count=240),
                                    constraints = [WeightConstraint(low=0.9, high=1.0),
                                                  ],
                                    bounds=[],
                                    default_port_weight_range=[0., 1.0],
                                    ftol=1e-09,
                                    return_none_if_fail=True)
        
   
                                    
        print(optimized_weight)
        g.buy= optimized_weight.sort_values(ascending=False)
    else:
        g.buy= pd.Series(dtype=float)
## 收盘后运行函数
def after_market_close(context):
    '''
    盘后运行函数，选择明天要买入的股票
    
    '''
    now = context.current_dt.date()
    print(now)
    # print(dict_position[str(now)])
    if str(now) in dict_position:
        g.wait_list= dict_position[str(now)]
    else:
        g.wait_list= []
    print(g.wait_list)

# 初始化函数，设定基准等等
def initialize(context):
    # 设定500等权作为基准
    g.benchmark = '000300.XSHG'
    g.wait_list = []
    g.buy = pd.Series(dtype=float)
    # g.buy = []
    context.f = True
    set_benchmark(g.benchmark)
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0002, close_commission=0.0002, min_commission=5),type='stock')
    # 滑点
    set_slippage(FixedSlippage(0.0))
    # 初始化因子设置
    factor_analysis_initialize(context)
    # 定义股票池
    set_stockpool(context)
    # 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
    run_daily(set_stockpool, time='before_open', reference_security='000300.XSHG')
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    run_daily(sell, time='14:59', reference_security='000300.XSHG')
    run_daily(buy, time='09:30', reference_security='000300.XSHG')
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')

# 定义股票池
def set_stockpool(context):
    # 获取股票池
    #stocks = get_index_stocks('000300.XSHG',date='2020-01-21')
    stocks2 = get_index_stocks('000300.XSHG')
    #stocks3 = list(set(stocks)&set(stocks2))
    #stocks = get_index_stocks(g.benchmark,context.previous_date)
    paused_series = get_price(stocks2,end_date=context.current_dt,count=1,fields='paused')['paused'].iloc[0]
    # g.stock_pool 为因子挖掘的对象股票池，用户不可对此股票池进行二次筛选
    g.stock_pool =  paused_series[paused_series==False].index.tolist()

# 定义需要用到的全局变量
def factor_analysis_initialize(context):
    # g.weight_method 为加权方式, "avg"按平均加权

    # g.sell为卖出股票权重列表
    g.sell = pd.Series(dtype=float)
    # g.buy为买入股票权重列表
    g.buy = pd.Series(dtype=float)
    # g.d 为获取昨天的时间点
    g.d = context.previous_date


# 买入股票
def buy(context):
    
    long_cash = context.portfolio.total_value
    
    # 全仓买入 隔天交易
    # if context.portfolio.positions:
    #     return
    # if not g.buy.empty:
    #     for s in g.buy.index:
            # order_target_value(s, g.buy.loc[s] *1* long_cash)
            
            # 低开买入
            # price = get_price(s,end_date=context.current_dt,count=1,frequency='1d',fields=['open','pre_close'])
            # if price['open'].iloc[-1]< price['pre_close'].iloc[-1]:
            #     order_target_value(s, g.buy.loc[s] *1* long_cash)
    
    # 每日都买 半仓买入
    if not g.buy.empty:
        for s in g.buy.index:
            order_target_value(s, g.buy.loc[s] *0.5* long_cash) 
            
            # 低开买入
            # price = get_price(s,end_date=context.current_dt,count=1,frequency='1d',fields=['open','pre_close'])
            # if price['open'].iloc[-1]< price['pre_close'].iloc[-1]:
            #     order_target_value(s, g.buy.loc[s] *0.5* long_cash)       
            
# 卖出股票
def sell(context):
    for s in context.portfolio.positions.keys():
        order_target_value(s, 0)

# 过滤涨停股票
def high_limit_filter(context, security_list):
    current_data = get_current_data()
    security_list = [stock for stock in security_list if not (current_data[stock].last_price==current_data[stock].high_limit)]
    # 返回结果
    return security_list

