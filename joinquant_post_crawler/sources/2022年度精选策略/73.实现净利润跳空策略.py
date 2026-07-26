# 克隆自聚宽文章：https://www.joinquant.com/post/37724
# 标题：实现净利润跳空策略
# 作者：金融界懒羊羊

from jqdata import *
## 初始化函数，设定要操作的股票、基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # True为开启动态复权模式，使用真实价格交易
    set_option('use_real_price', True) 
    # 设定成交量比例
    set_option('order_volume_ratio', 1)
    # 股票类交易手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, \
                             open_commission=0.0003, close_commission=0.0003,\
                             close_today_commission=0, min_commission=5), type='stock')
    # 持仓数量
    g.stocknum = 5 
    # 交易日计时器
    g.days = 0 
    # 调仓频率
    g.refresh_rate = 30
    # 选取行业数
    g.indnum = 3
    
    #根据大盘止损，如不想加入大盘止损，注释下句即可
    #run_daily(dapan_stoploss, time='open') 
    # 运行函数
    run_daily(trade, 'every_bar')

## 选出标的股票
def check_stocks(context):
    #筛选净利润环比增长超过20%的股票
    Stocks = get_fundamentals(query(
            valuation.code,
            indicator.inc_net_profit_annual,
        ).filter(
            indicator.inc_net_profit_annual > 0.2, #净利润环比增长率(%)大于20%
        ))
    #筛选跳空的股票
    temp = get_bars(Stocks['code'].values.tolist(), 2, unit='1d',fields=['date','open','close'],include_now=False)
    jump = []
    for i in list(set(temp.keys())):
        min1 = min(temp[i][0][1],temp[i][0][2])
        max2 = max(temp[i][1][1],temp[i][1][2])
        if(min1 > max2):
            jump.append(1)
        else:
            jump.append(0)
    Stocks['jump'] = pd.DataFrame(jump)
    Stocks = Stocks[Stocks['jump'] > 0]
    #筛选在前g.indnum个行业中的stock
    Stocks_afterind = getstocklist_byindustry(list(Stocks['code']),g.indnum)
    Stocks = Stocks[Stocks.code.isin(Stocks_afterind)]
    Stocks.sort_values(by="inc_net_profit_annual" , inplace=True, ascending=False) 
    #返回筛选后的股票代码
    Codes = list(Stocks['code'])
    # 过滤停牌股票
    buylist = filter_paused_stock(Codes)

    return buylist[:g.stocknum]
  
## 交易函数
def trade(context):
    if g.days%g.refresh_rate == 0:

        ## 获取持仓列表
        sell_list = list(context.portfolio.positions.keys())
        
        ## 选股
        stock_list = check_stocks(context)
        
        # 如果有持仓，则卖出当前不在stock_list中的股票
        if len(sell_list) > 0 :
            for stock in sell_list:
                if(stock not in stock_list):
                    order_target_value(stock, 0)

        ## 分配资金
        if len(context.portfolio.positions) < g.stocknum :
            Num = g.stocknum - len(context.portfolio.positions)
            Cash = context.portfolio.cash/Num
        else: 
            Cash = 0

        ## 买入股票
        for stock in stock_list:
            if len(context.portfolio.positions.keys()) < g.stocknum:
                order_value(stock, Cash)

        # 天计数加一
        g.days = 1
    else:
        g.days += 1

# 过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]
    
# 统计满足净利润跳空的股票的行业及对应数量，根据行业满足净利润跳空标的数量进行排序，并根据最终选取行业的数量返回要买入的stock_list
def getstocklist_byindustry(Codes,num):
    sw_l1 = pd.DataFrame(np.zeros(len(list(set(get_industries(name="sw_l1")['name'])))).reshape(1,-1),columns = list(set(get_industries(name="sw_l1")['name'])))
    for code in Codes:
        try:
            sw_l1[get_industry(security=code)[code]['sw_l1']['industry_name']] = sw_l1[get_industry(security=code)[code]['sw_l1']['industry_name']] + 1
        except:
            log.info(" %s 不存在申万行业数据" % (code))
    sw_l1 = sw_l1.T
    sw_l1.sort_values(by = 0 , inplace=True, ascending=False) 
    sw_l1 = sw_l1[0:num].T
    industry_list = list(sw_l1.columns)
    result_list = []
    for code in Codes:
        try:
            if(get_industry(security=code)[code]['sw_l1']['industry_name'] in industry_list):
                result_list.append(code)
        except:
            log.info(" %s 不存在申万行业数据" % (code))
    return result_list
        
## 根据局大盘止损，具体用法详见dp_stoploss函数说明
def dapan_stoploss(context):
    stoploss = dp_stoploss(kernel=2, n=3, zs=0.1)
    if stoploss:
        if len(context.portfolio.positions)>0:
            for stock in list(context.portfolio.positions.keys()):
                order_target(stock, 0)

## 大盘止损函数
def dp_stoploss(kernel=2, n=10, zs=0.03):
    '''
    方法1：当大盘N日均线(默认60日)与昨日收盘价构成“死叉”，则发出True信号
    方法2：当大盘N日内跌幅超过zs，则发出True信号
    '''
    # 止损方法1：根据大盘指数N日均线进行止损
    if kernel == 1:
        t = n+2
        hist = attribute_history('000300.XSHG', t, '1d', 'close', df=False)
        temp1 = sum(hist['close'][1:-1])/float(n)
        temp2 = sum(hist['close'][0:-2])/float(n)
        close1 = hist['close'][-1]
        close2 = hist['close'][-2]
        if (close2 > temp2) and (close1 < temp1):
            return True
        else:
            return False
    # 止损方法2：根据大盘指数跌幅进行止损
    elif kernel == 2:
        hist1 = attribute_history('000300.XSHG', n, '1d', 'close',df=False)
        if ((1-float(hist1['close'][-1]/hist1['close'][0])) >= zs):
            return True
        else:
            return False
    
