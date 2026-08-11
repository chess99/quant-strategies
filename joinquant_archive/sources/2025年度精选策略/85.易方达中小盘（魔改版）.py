# 克隆自聚宽文章：https://www.joinquant.com/post/28287
# 标题：易方达中小盘（魔改版）
# 作者：猪头港

# 导入函数库
from jqdata import *
from jqdata import finance


# 初始化函数，设定基准等等
def initialize(context):
    # 设定基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option("use_real_price", True)
    #set_option('avoid_future_data',True)
    # 设置账户类型: 场外基金账户
    set_subportfolios([SubPortfolioConfig(context.portfolio.cash, 'open_fund')])
    # 设置赎回到账日
    set_redeem_latency(3, 'open_fund')
    
    run_daily(market_open, time='open', reference_security='000300.XSHG')
        # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')
    
    g.day=0
    g.BuyGold=False
    
    #先买10W底仓
    g.s = '110011.OF'
    o = purchase(g.s, 100000)
    log.info(o)
    

    
def market_open(context):
 
    s = g.s
    s1= '000217.OF'
    
    
    
    ## 确定时间是周几
    weekday = context.current_dt.date()
    log.info("今天是 %s" % weekday)
    log.info(g.day)
    #思路还是非常清晰的 先确定好时间
    #然后绘制基金30日均线 这里想来想去 30日效果最好
    
    df=get_extras('acc_net_value', s, count = 60,end_date= context.current_dt.date())
    MA22=np.array(df).mean()
    
    if g.BuyGold==True:
        g.day=g.day+1
    if g.BuyGold==False:
        g.day=0    
    
    # 申购基金
    # 这个地方的思路很坚决，跌破一定范围我就去卖
    # 利用20日乖离率来解决
    if df.iloc[-1].values<MA22:
        if abs(df.iloc[-1].values/MA22-1)>0.03:
            o1 = redeem(s, context.portfolio.subportfolios[0].long_positions['110011.OF'].closeable_amount)
            o =  purchase(s1, 100000)
            g.BuyGold=True
            
    else:
        if g.day>=7:
            o1 = redeem(s1, context.portfolio.subportfolios[0].long_positions['000217.OF'].closeable_amount)
            g.BuyGold=False
        o = purchase(s, 100000)

        
## 收盘后运行函数
def after_market_close(context):
    # 查看融资融券账户相关相关信息(更多请见API-对象-SubPortfolio)
    p = context.portfolio.subportfolios[0]
    log.info('- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -')
    #log.info('查看场外基金账户相关相关信息(更多请见API-对象-SubPortfolio)：')
    log.info('场外基金持有份额：',p.long_positions['110011.OF'].closeable_amount)
    log.info('场外基金持有份额：',p.long_positions['000217.OF'].closeable_amount)
    #log.info('账户所属类型：',p.type)
    #log.info(context.portfolio.available_cash)
    log.info(context.portfolio.total_value)
    log.info('##############################################################')
