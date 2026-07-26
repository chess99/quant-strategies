# 克隆自聚宽文章：https://www.joinquant.com/post/37633
# 标题：别人恐惧我贪婪3——年化20%的股债组合
# 作者：潜水的白鱼

# 导入函数库
from jqdata import *

'''
=====================1.初始化函数调用====================================
'''
# 初始化函数，设定基准等等
def initialize(context):
    #盘前默认参数设置
    set_parameter()
    
    #策略运行
    run_daily(market_open, time='9:31', reference_security='000300.XSHG')
    
    #尾盘运行
    run_daily(market_1455, time='14:55', reference_security='000300.XSHG')
    

'''
=====================2.盘前默认参数设置====================================
'''
def set_parameter():
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    #基本参数定义，股票池
    g.pool = []
    
    #buttun=1表示的是持有宽基指数，buttun=0表示持有国债
    g.buttun = 0 #代表关
    g.day = 1
'''
=====================3.开盘运行买入阶段主函数====================================
'''


## 开盘时运行函数，获取股票池
def market_open(context):
    
    #股票池为你选择的指数512100为中证1000etf
    g.pool = ['512100.XSHG']
    #国债etf
    g.nationaldabt = ['511010.XSHG']
    
'''
=====================4.开盘运行买入阶段主函数====================================
'''


## 14:55时运行函数
##g.buttun表示的是持有状态，如果为0，持有国债；如果为1持有股票
def market_1455(context):

    #获取数据,000001.XSHG代表上证指数
    current_data_now = get_current_tick('000001.XSHG')

    #获取当前日期
    t_date = context.current_dt.strftime('%Y-%m-%d')
    #获取当前日期
    y_date = context.previous_date.strftime('%Y-%m-%d')

    # print("运行当天日期：%s,  当前上证指数分钟价格:%s"%(t_date,current_data_now.current))

    
    #获得昨日跌幅
    df = attribute_history('000001.XSHG', count=2, unit='1d',
            fields=['open', 'close', 'high', 'low', 'volume', 'money'],
            skip_paused=True, df=True, fq='pre')
    
    y1_close = df['close'][0]
    y2_close =  df['close'][1]
    y_cha =  (y2_close-y1_close )/y1_close
    
    
    #获得截止目前为止的跌幅
    t_cha = (current_data_now.current- y2_close)/ y2_close
    
    
    #触发买入条件,先清掉持有的国债
    if y_cha <= -0.015 and t_cha <= -0.014 :
        
        #检查是否以及持有指数了，持有时再遇跌幅不必重置
        handcode_list = []
        for code in context.portfolio.positions.keys():
            handcode_list.append(code)
       
        if g.pool[0] not in handcode_list:
            #卖出国债
            order_target_value(g.nationaldabt[0], 0)
            
            #买入指数
            cash_value = context.portfolio.available_cash
            order_target_value(g.pool[0], cash_value)
        
        g.buttun = 1
    else:
        pass
    
    
    #触发卖出条件，买入后的n天清仓
    if g.buttun == 1:
        g.day +=1
    
    
    print(g.day)
    
    if g.day%20 == 0 :
        #卖出指数
        order_target_value(g.pool[0], 0)
        print("day%s"%(g.day))
        
        #买入国债
        cash_value = context.portfolio.available_cash
        order_target_value(g.nationaldabt[0], cash_value)
        

        #开关关闭，数据重置
        g.day = 1
        g.buttun =0
        
        

        
