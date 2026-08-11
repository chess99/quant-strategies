# 克隆自聚宽文章：https://www.joinquant.com/post/41908
# 标题：桥水 全天候策略 增加一致性度量ES 风险控制
# 作者：aiyquant

# 导入函数库
from jqdata import *

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
    set_option("avoid_future_data", True)

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    set_order_cost(OrderCost(open_commission=0.0003, close_commission=0.0003, min_commission=5), type='fund')

    g.confidencelevel = 2.58
    g.rebalanced_asset_values = {}
    g.raise_rate = -1 #0.3 #触发rebalance的上涨比例, <=0不触发
    g.period = 12
    g.run_count = 0
    
    g.pool = {
        'stock': {'rate':0.3, 'codes':[
                    { 
                      '510310.XSHG':datetime.datetime(2013,3,25),
                      '513100.XSHG':datetime.datetime(2013,5,15),
                      '513500.XSHG':datetime.datetime(2014,1,15),
                    },
                    
                ]},
        
        'mid_bond':{'rate':0.15, 'codes':[
                    {
                     '511010.XSHG':datetime.datetime(2013,3,25)
                    }
                ]},
        
        'long_bond':{'rate':0.4, 'codes':[
                    {'511260.XSHG':datetime.datetime(2017,8,24) #10years
                    },
                    
                ]},
        'gold':{'rate':0.075, 'codes':[
                    {'518880.XSHG':datetime.datetime(2013,7,29)
                    },
                    
                ]},
        'goods':{'rate':0.075, 'codes':[
                    {
                     '510170.XSHG':datetime.datetime(2011,1,25)
                    },
                    
                ]},
    }
    
    g.stock_map_asset = init_stock_map_asset(g.pool)
    
    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    #run_daily(before_market_open, time='before_open', reference_security='000001.XSHG')
      # 开盘时运行
    run_monthly(market_open, monthday=1, time='open', reference_security='000001.XSHG')
      # 收盘后运行
    #run_daily(after_market_close, time='after_close', reference_security='000001.XSHG')

def init_stock_map_asset(pool):
    stock_map_asset = {}
    for asset in pool:
        for stocks in pool[asset]['codes']:
            for code in stocks:
                stock_map_asset[code] = asset
    return stock_map_asset
    
## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    #log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))

    # 给微信发送消息（添加模拟交易，并绑定微信生效）
    # send_message('美好的一天~')

    # 要操作的股票：平安银行（g.为全局变量）
    #g.security = '000001.XSHE'
    pass

def get_trade_target(context):
    dt=context.current_dt
    ret = []
    for asset in g.pool:
        stock_pool = g.pool[asset]['codes']
        target_stocks = []
        for stocks in stock_pool:
            cur_stocks_isOK = False
            for start_dt in stocks.values():
                if dt >= start_dt:
                    cur_stocks_isOK = True
                    break
            if cur_stocks_isOK:
                target_stocks = [k for k in stocks.keys()]
                break
        ret.extend( target_stocks )
    return ret

def calc_asset_max_raise(context):
    asset_values = {}
    for code in context.portfolio.positions:
        asset = g.stock_map_asset[code]
        pos = context.portfolio.positions[code]
        if asset not in asset_values:
            asset_values[asset] = pos.value
        else:
            asset_values[asset] += pos.value
    
    max_raise_ratio = 0
    for asset in g.rebalanced_asset_values:
        if asset in asset_values:
            ratio = asset_values[asset] / g.rebalanced_asset_values[asset]
            if ratio > max_raise_ratio:
                max_raise_ratio = ratio 
    
    return max_raise_ratio
    
## 开盘时运行函数
def market_open(context):
    #log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    if g.run_count % g.period == 0:
        asset_alloc = get_trade_target(context)
        #print(asset_alloc)
        rebalance(context, asset_alloc)
    elif g.raise_rate > 0 and calc_asset_max_raise(context) > g.raise_rate:
            #增加 g.raise_rate > 0 是为了测试的时候
            #可以去掉涨幅触发rebalance的逻辑
            asset_alloc = get_trade_target(context)
            #print(asset_alloc)
            rebalance(context, asset_alloc)
    g.run_count += 1

def stat_cur_asset(context):
    ret = {}
    for code in context.portfolio.positions:
        asset = g.stock_map_asset[code]
        if asset in ret :
            ret[asset].append(code)
        else:
            ret[asset] = [code]
    return ret

def cal_stocks_ratio(context, asset_alloc):
    
    def getdailyreturn(stock, freq, lag):
        hStocks = history(lag, freq, 'close', stock, df=True)
        dailyReturns = hStocks.resample('D',how='last').pct_change().fillna(value=0, method=None, axis=0).values

        return dailyReturns

    def get_stock_ES(stock, freq, lag, confidencelevel):
        if confidencelevel == 1.96:
            a = (1 - 0.95)
        elif confidencelevel == 2.06:
            a = (1 - 0.96)
        elif confidencelevel == 2.18:
            a = (1 - 0.97)
        elif confidencelevel == 2.34:
            a = (1 - 0.98)
        elif confidencelevel == 2.58:
            a = (1 - 0.99)
        elif confidencelevel == 5:
            a = (1 - 0.99999)
        else:
            a = (1 - 0.95)
        
        ES = 0
        if True:
            dailyReturns = getdailyreturn(stock, freq, lag)
            dailyReturns_sort =  sorted(dailyReturns)
    
            count = 0
            sum_value = 0
            for i in range(len(dailyReturns_sort)):
                if i <= int(lag * a):
                    sum_value += dailyReturns_sort[i]
                    count += 1
            if count == 0:
                ES = 0
            else:
                ES = -sum_value / int(lag * a)

        return ES

    
    def stock_risk_ES(stock):
        __portfolio_ES = get_stock_ES(stock, '1d', 120, g.confidencelevel)
        if isnan(__portfolio_ES):
            __portfolio_ES = 0
        #print(__portfolio_ES, stock)
        return __portfolio_ES

    
    total_ratio = 0
    stock_ratio = {}
    new_asset_ratio = {}
    for stock in asset_alloc:
        stock_ratio[stock] = 1./stock_risk_ES(stock)
        total_ratio += stock_ratio[stock]
    
    
    for stock in asset_alloc:
        new_asset_ratio[stock] = stock_ratio[stock] / total_ratio
    
    #print( new_asset_ratio)
    return new_asset_ratio
    
def rebalance(context, asset_alloc):
    new_asset_values = {}
    #cur_asset_codes = stat_cur_asset(context)
    #print(cur_asset_codes)
    #计算新的资产价值
    new_asset_ratio = cal_stocks_ratio(context, asset_alloc)
    for stock in asset_alloc:
        new_asset_values[stock] = context.portfolio.total_value * new_asset_ratio[stock]
    #print(new_asset_values)
    #调整每个资产
    sell_stocks = []
    for stock in context.portfolio.positions:
        #切换掉的标的，先卖再买
        if stock not in new_asset_values:
            order_target_value(stock, 0)
            sell_stocks.append(stock)
        elif new_asset_values[stock] < context.portfolio.positions[stock].value:
            order_target_value(stock, new_asset_values[stock])
            sell_stocks.append(stock)
    for stock in new_asset_values:    
        #reblance 当前资产，如果当前资产不存，持有现金
        if stock not in sell_stocks:
            order_target_value(stock, new_asset_values[stock])
    g.rebalanced_asset_values = new_asset_values

## 收盘后运行函数
def after_market_close(context):
    #log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    #trades = get_trades()
    #for _trade in trades.values():
    #    log.info('成交记录：'+str(_trade))
    #log.info('一天结束')
    #log.info('##############################################################')
    pass
