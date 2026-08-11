# 克隆自聚宽文章：https://www.joinquant.com/post/41913
# 标题：融券做空,3年35倍多！已模拟2年半，动态跑盘收益惊人！
# 作者：naruto

#融资融券-震荡指数做空隔日开盘平
'''
【原理】
要求振幅大于15%，这样就说明当日最低价是低于昨日收盘价的，因为，如果最低价大于等于昨日收盘价，即使涨停，震荡是小于等于10%的。
大于15%，还说明一点，盘中最低价跌幅超过5%，这样即使当日涨停，根据我们打板的经验，次日都会低开的。
扩散思路：以后扩幅后，可以设置成涨停的1.5倍振幅。
'''

# 导入函数库
from jqdata import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')

    ### 融资融券相关设定 ###
    # 设置账户类型: 融资融券账户
    set_subportfolios([SubPortfolioConfig(cash=context.portfolio.cash, type='stock_margin')])

    ## 融资相关设定
    # 设定融资利率: 年化8%, 默认8%
    set_option('margincash_interest_rate', 0.08)
    # 设置融资保证金比率: 150%, 默认100%
    set_option('margincash_margin_rate', 1.5)

    ## 融券相关设定
    # 设定融券利率: 年化10%, 默认10%
    set_option('marginsec_interest_rate', 0.10)
    # 设定融券保证金比率: 150%, 默认100%
    set_option('marginsec_margin_rate', 1.5)
    
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    # 为股票设定滑点为百分比滑点
    set_slippage(PriceRelatedSlippage(0.00246),type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
      # 开盘时运行
    run_daily(market_open, time='open', reference_security='000300.XSHG')
        #尾盘运行
    run_daily(clear_close, time='14:55', reference_security='000300.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')


## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    g.buylist0=[]

## 开盘时运行函数
def market_open(context):
    log.info('开始还券。。。。。。。。。。。。。。。。。。。。')
    rq_stock = context.portfolio.short_positions
    
    # 融券操作
    for stock in rq_stock:
        current_price = get_bars(stock, count=1, unit='5m', fields=['close'],include_now=True)['close'][-1]
        # print(rq_stock[stock].total_amount)
        log.info("买券还券:%s" % [stock,current_price,rq_stock[stock].total_amount])
        marginsec_close(stock, rq_stock[stock].total_amount)

def clear_close(context):
    log.info('开始融券卖出。。。。。。。。。。。。。。。。。。。。')
    
    # 全市场A股，包括科创板
    # security = list(get_all_securities(['stock']).index)#index返回代码，start_date返回上市日期，对照api查看
    #获取融券标的股票列表
    security=get_marginsec_stocks(date=context.current_dt)
    
    current_data=get_current_data()
    zf_dict={}
    for s in security:
        cc=get_bars(s, count=2, unit='1d',fields=['high','low','close'],include_now=True)
        if current_data[s].paused==False and len(cc['close'])==2:
            zf=(cc['high'][-1]-cc['low'][-1])/cc['close'][0]*100
            if (cc['high'][-1]-cc['low'][-1])/(current_data[s].high_limit-cc['close'][0])>1.5:
                zf_dict[s]=zf
            else:
                pass
    
    #利用字典来获取排序股票代码
    dm=sorted(zf_dict.items(),key=lambda x:x[1],reverse=True)#.items是按照（股票,时间）一起排序
    # print('dm_sumf: %s' % dm)
    print('len(dm_sumf): %s' % len(dm))
    buylist=[s[0] for s in dm]#这个写法比较有创意,而且是list
    g.buylist0=buylist[:10]
    print('融券卖出:%s' % g.buylist0)

    if len(g.buylist0)>0:
        position_per_money=context.portfolio.total_value/len(g.buylist0) #因为不足g.stocksnum的也会交易
        # 融券操作
        for stock in g.buylist0:
            current_price = get_bars(stock, count=1, unit='5m', fields=['close'],include_now=True)['close'][-1]
            position_per_money_n=int(position_per_money/current_price/100)*100#int()向下取整
            log.info("融券卖出:%s" % [stock,current_price,position_per_money_n])
            marginsec_open(stock, position_per_money_n)

## 收盘后运行函数
def after_market_close(context):
    # 查看融资融券账户相关相关信息(更多请见API-对象-SubPortfolio)
    p = context.portfolio.subportfolios[0]
    log.info('- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -')
    log.info('查看融资融券账户相关相关信息(更多请见API-对象-SubPortfolio)：')
    log.info('总资产：',p.total_value)
    log.info('净资产：',p.net_value)
    log.info('总负债：',p.total_liability)
    log.info('融资负债：',p.cash_liability)
    log.info('融券负债：',p.sec_liability)
    log.info('利息总负债：',p.interest)
    log.info('可用保证金：',p.available_margin)
    log.info('维持担保比例：',p.maintenance_margin_rate)
    log.info('账户所属类型：',p.type)
    log.info('##############################################################')
