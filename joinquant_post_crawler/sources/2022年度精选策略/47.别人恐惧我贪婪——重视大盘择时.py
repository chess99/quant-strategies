# 克隆自聚宽文章：https://www.joinquant.com/post/37067
# 标题：别人恐惧我贪婪——重视大盘择时
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
    
    
    run_daily(market_1455, time='14:55', reference_security='000300.XSHG')
      # 收盘后运行

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
    g.stock_num = 50
    g.buttun = 0 #代表关
    g.day = 1
'''
=====================3.开盘运行买入阶段主函数====================================
'''


## 开盘时运行函数，获取股票池
def market_open(context):
    log.info('函数运行时间:'+str(context.current_dt.time()))
    ######1 获取时间

    yesterday = context.previous_date
    initial_list = get_index_stocks('000905.XSHG', date = yesterday )
    
    
    #获取市值最大的500支股票并买入
    q = query(valuation.code,valuation.circulating_market_cap).filter(valuation.code.in_(initial_list)).order_by(valuation.circulating_market_cap.desc())
    df = get_fundamentals(q)
    shizhi_list = list(df.code)[0:50]
    
    g.pool = shizhi_list
    


    
    
'''
=====================4.开盘运行买入阶段主函数====================================
'''


## 14:55时运行函数
def market_1455(context):
    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    
    
    #获取数据,000001.XSHG代表上证指数
    current_data_now = get_current_tick('000001.XSHG')

    #获取当前日期
    t_date = context.current_dt.strftime('%Y-%m-%d')
    #获取当前日期
    y_date = context.previous_date.strftime('%Y-%m-%d')

    print("运行当天日期：%s,  当前上证指数分钟价格:%s"%(t_date,current_data_now.current))

    
    #获得昨日跌幅
    df = attribute_history('000001.XSHG', count=2, unit='1d',
            fields=['open', 'close', 'high', 'low', 'volume', 'money'],
            skip_paused=True, df=True, fq='pre')
    
    y1_close = df['close'][0]
    y2_close =  df['close'][1]
    y_cha =  (y2_close-y1_close )/y1_close
    
    
    #获得截止目前为止的跌幅
    t_cha = (current_data_now.current- y2_close)/ y2_close
    
    
    #触发买入条件
    if y_cha <= -0.015 and t_cha <= -0.015 :
        print("昨日跌幅：%s"%(y_cha))
        print("今天跌幅：%s"%(t_cha))
        buy_stock(context,g.pool)
        g.buttun = 1
    else:
        pass
    
    
    #触发卖出条件，买入后的n天清仓
    if g.buttun == 1:
        g.day +=1
    
    
    if g.day%20== 0 :
        for sell_code in context.portfolio.positions.keys():
            order_target_value(sell_code, 0)
        #开关关闭，数据重置
        g.day = 1
        g.buttun =0
        
        
#买入函数
def buy_stock(context,pool):
    
    for buy_code in pool:   # buy pool
        if buy_code not in context.portfolio.long_positions.keys():
            cash_value = context.portfolio.available_cash   #可用现金
            if (g.stock_num - len(context.portfolio.positions)) > 0:  #6最多买6支股票，只要还有名额就可以使用
                buy_value = cash_value / (g.stock_num - len(context.portfolio.positions))
                log.info('buy:  ' + buy_code + '   ' + str(buy_value))
                order_target_value(buy_code, buy_value)




