# 克隆自聚宽文章：https://www.joinquant.com/post/31867
# 标题：布林线追龙头战法
# 作者：fishsome

# 导入函数库
from jqdata import *

#1.股价处于盘整状态时，股价下碰支撑线买入，上碰阻力线卖出。
#2.股价连续上涨时，会沿着中线和阻力线形成的通道上升。当股价不能再触及阻力线时，则上涨趋势减弱，应卖出。
#ma25 ma60 ma200全部向上
#3.当股价连续下跌时，会沿着中线和支撑线形成的下降通道下跌，当股价不能再触及支撑线时，下跌趋势减弱，应买入。

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')
    g.redbull = False
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之1，卖出时佣金万分之1加千分之一印花税, 每笔交易佣金最低扣0块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0001, close_commission=0.0001, min_commission=0), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
      # 开盘时运行
    run_daily(market_open, time='open', reference_security='000300.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')
    
    g.stocksnum =8
    g.period =  20  
    g.days = 0
    g.buy_sell_num = 0

## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
   # log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
   # log.info('函数运行前10天！！！！！！！！！：'+str(context.current_dt+datetime.timedelta(days=-10)))
    # 给微信发送消息（添加模拟交易，并绑定微信生效）
    # send_message('美好的一天~')

    # 要操作的股票：平安银行（g.为全局变量）
    g.security = '600519.XSHG'

## 开盘时运行函数
def market_open(context):
    
    scu = get_index_stocks('000002.XSHG')
    q = query(valuation.code).filter(valuation.code.in_(scu),
            valuation.pe_ratio  > 15, valuation.pe_ratio < 100 ,
            indicator.gross_profit_margin>40,
            ).order_by(
                valuation.market_cap.desc(),valuation.pe_ratio.asc()
            ).limit(20)
    df = get_fundamentals(q) 
    buylist = list(df['code'])

    for stock in context.portfolio.positions:
        if stock not in buylist:
            order_target(stock,0)

    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    for security in buylist:
        #security = g.security
        # 获取股票的收盘价
        his_201 = his = attribute_history(security, count=201, unit='1d',fields=['close'],skip_paused=True, df=True, fq='pre')
                      #1至201日的均线是昨日的              #0到200日的均线是前日的ma200线
        sma200 = round(his_201['close'][1:].mean()-his_201['close'][:-1].mean(),4)
        sma60 = round(his_201['close'][-60:].mean()-his_201['close'][-61:-1].mean(),4)
        sma25 = round(his_201['close'][-25:].mean()-his_201['close'][-26:-1].mean(),4)
        
       # sma60 = round(get_price(security, count=60, end_date=context.current_dt, frequency='daily', fields=['close'], 
       # skip_paused=True, fq='pre', panel=True).mean()['close'] - get_price(security, count=60, end_date=context.previous_date, frequency='daily', fields=['close'], 
        #skip_paused=True, fq='pre', panel=True).mean()['close'],4)
        
       # sma25 = round(get_price(security, count=25, end_date=context.current_dt, frequency='daily', fields=['close'], 
       # skip_paused=True, fq='pre', panel=True).mean()['close'] - get_price(security, count=25, end_date=context.previous_date, frequency='daily', fields=['close'], 
       # skip_paused=True, fq='pre', panel=True).mean()['close'],4)
        log.info('sma200============:' + str(sma200))
        close_data = get_bars(security, count=5, unit='1d', fields=['close'])
        # 取得过去五天的平均价格
        MA5 = close_data['close'].mean()
        # 取得上一时间点价格
        current_price = close_data['close'][-1]
        log.info('current_price============:' + str(current_price))

        # 取得当前的现金
        cash = context.portfolio.available_cash
        
        ######布林20日均线上下轨计算
        price20=attribute_history(security,20,'1d',('close','open','low','high'),skip_paused=True)
        #创建一个num*days的二维数组来保存收盘价数据
        lastLowestprice = price20['low'][-1]
        lastHiggstprice = price20['high'][-1]
        if price20['close'][-1] >  price20['open'][-1]:
            pricelower = price20['open'][-1]
            pricehiger = price20['close'][-1]
        else: 
            pricelower = price20['close'][-1]
            pricehiger = price20['open'][-1]
    
        #创建一个数组来保存中轨信息
    
        mid=round(np.mean(price20['close']),2)
        std=round(np.std(price20['close']),2)
        #用up来保存昨日的上轨线
    
        bollUp=mid+2*std
        #用down来保存昨日的下轨线
        bollDown=mid-2*std
        
    
        minchange = round(current_price/10000,4)#最小价格波动变动误差千元股与几元股的误差不同
        avg_cost = context.portfolio.positions[security].avg_cost 
        position_per_stk = context.portfolio.total_value/g.stocksnum
        # 如果三红线，价格在20日线下方, 则全仓买入
        if (sma200 >minchange) and (sma60 >minchange) and (sma25 >minchange):
            
            if current_price < mid and (cash > 100*current_price):
                # 记录这次买入
                log.info("价格高于均价 1%%, 买入 %s" % (security))
                # 用所有 cash 买入股票
                order_target_value(security, position_per_stk)
            if lastHiggstprice<bollUp and  avg_cost*1.2 < current_price  and context.portfolio.positions[security].closeable_amount > 0:
                order_target(security, 0)
                log.info("全部跌落布林上轨，卖出！ %s" % (security))
                
        # 如果含有两条负线,  则空仓卖出
        if ( ((sma200 <-minchange) and (sma60 < -minchange)) or ((sma25 <-minchange) and (sma60 < -minchange)) or ((sma200 <-minchange) and (sma25 < -minchange))) and context.portfolio.positions[security].closeable_amount > 0:
            # 记录这次卖出
            log.info("两条负线, 卖出 %s" % (security))
            log.info("sma25 ma60 sma200====" + str(sma25) +str(sma60) + str(sma200) )
    
            # 卖出所有股票,使这只股票的最终持有量为0
            order_target(security, 0)
        #实体掉进中线卖出
        #if  lastHiggstprice<mid and context.portfolio.positions[security].closeable_amount > 0:
         #   order_target(security, 0)
    
## 收盘后运行函数
def after_market_close(context):
    #log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    #log.info('一天结束')
    #log.info('##############################################################')
 
