# 克隆自聚宽文章：https://www.joinquant.com/post/27759
# 标题：ETF网格交易策略
# 作者：pia19

# 导入函数库
import jqdata

# 初始化函数，设定要操作的股票、基准等等
def initialize(context):
    # 定义一个全局变量, 保存要操作的股票
    # 000001(股票:平安银行)
    g.security = '512900.XSHG'
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    run_daily(market_open, time='14:45:00')
    set_slippage(PriceRelatedSlippage(0.002))
    #设置参数 区间 网格间距 
    uplimit=1.5
    downlimit=0.9
    space=6
    number=3     #cash分隔份数
    #单位间隔
    g.unitprice=(uplimit-downlimit)/space
    #2019-04-01 收盘价格
    g.initialprice=0.976
    #get_price(security=g.security, end_date='2020-06-02',fields='close',count=10)['close'][-2]
    g.initial_buy=downlimit+0*g.unitprice
    g.initial_sell=downlimit+1*g.unitprice
    #将现金分割成几份
    g.cash = context.portfolio.cash/number
    #打印每个买卖区间
    for i in range(0,space+1):
        print(uplimit-i*g.unitprice)
    #run_daily(market_open, time='every_bar', reference_security='000300.XSHG')
    run_daily(after_market, time='after_close', reference_security='000300.XSHG')


# 每个单位时间(如果按天回测,则每天调用一次,如果按分钟,则每分钟调用一次)调用一次
def market_open(context):
    security = g.security
    cash = g.cash
    current_time=context.current_dt
    # 获取股票的收盘价
    close_data = get_price(security=security, end_date=current_time,\
                    frequency='1m', fields='close',count=5)['close'][-1]
    g.current_cash = context.portfolio.available_cash
    if close_data < g.initial_buy:
        order_value(security, cash)
        # 记录这次买入
        log.info("Buying %s" % (security))
    elif close_data > g.initial_sell:
        order_value(security, -cash)
        # 记录这次卖出
        log.info("Selling %s" % (security))
    
def after_market(context):
    close_cash = context.portfolio.available_cash
    print(g.current_cash,close_cash)
    #卖出ETF 则盘后cash余额高于盘中 信号位置上升
    if g.current_cash < close_cash:
        g.initial_buy = g.initial_buy + g.unitprice
        g.initial_sell = g.initial_sell + g.unitprice
        print(g.initial_sell)
    #买入ETF 则盘后cash余额低于盘中 信号位置下降
    elif g.current_cash > close_cash:
        g.initial_buy = g.initial_buy - g.unitprice
        g.initial_sell = g.initial_sell - g.unitprice
        print(g.initial_buy)
    
    
