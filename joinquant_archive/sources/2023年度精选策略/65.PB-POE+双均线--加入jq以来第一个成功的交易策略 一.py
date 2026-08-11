# 克隆自聚宽文章：https://www.joinquant.com/post/35005
# 标题：PB-POE+双均线--加入jq以来第一个成功的交易策略 一
# 作者：帅帅Hiber

'''
先通过财务数据选出一批优质股票，ROE>7, PB<20, 市值>800亿
再根据均线决定是否买入，短期均线在长期均线之上则买入
每天开盘买入，持有五个交易日，然后换仓
选出最好的五只股票
'''

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
    # 运行函数
    run_daily(trade)

## 选出小市值股票
def check_stocks(context):
    # 设定查询条件
    q =  query(
              valuation.code
          ).filter(
              valuation.market_cap > 800,
              valuation.pb_ratio < 20,
              indicator.roe > 7,
          ).order_by(
              # 按一定顺序排列
              (indicator.roe - valuation.pb_ratio).desc()
          ).limit(100) # 最多返回100个

    # 选出低市值的股票，构成buylist
    df = get_fundamentals(q)
    buylist = []
    for i in df['code']:
        security = i
        # 获取股票的收盘价
        close_data_MAs = attribute_history(security, 10, '1d', ['close'])
        # 取得过去17天的平均价格
        MAs = close_data_MAs['close'].mean()
        # 获取股票的收盘价
        close_data_MAl = attribute_history(security, 60, '1d', ['close'])
        # 取得过去115天的平均价格
        MAl = close_data_MAl['close'].mean()
        # 取得上一时间点价格 
        current_price = close_data_MAs['close'][-1]
        # 取得上上一时间点价格
        last_price = close_data_MAs['close'][-2]
        #目前价格在长线上方，短线在长线上方
        if current_price > MAl and MAs > MAl:
           buylist.append(security) 

    # 过滤停牌股票
    buylist = filter_paused_stock(buylist)

    return buylist[:g.stocknum]
  
def check_holding(context):
    sell_list = []
    holding_list = list(context.portfolio.positions.keys())
    for security in holding_list:
        # 获取股票的收盘价
        close_data_MAs = attribute_history(security, 10, '1d', ['close'])
        # 取得过去17天的平均价格
        MAs = close_data_MAs['close'].mean()
        # 获取股票的收盘价
        close_data_MAl = attribute_history(security, 60, '1d', ['close'])
        # 取得过去115天的平均价格
        MAl = close_data_MAl['close'].mean()
        
        current_price = close_data_MAs['close'][-1]
        
        if current_price < MAs and MAs < MAl:
           sell_list.append(security) 
           
    return sell_list
        
## 交易函数
def trade(context):
    if g.days%g.refresh_rate == 0: #这里的意思是g.days可以被g.refresh_rate整除（days是rates的倍数）
    
        ## 获取持仓列表和买入列表，删除其中的重复项，即不需要卖出的股票
        now_list = list(context.portfolio.positions.keys())
        stock_list = check_stocks(context)
        sell = []
        buy=[]
        for stock in now_list:
            if stock not in stock_list:
                sell.append(stock)
        
        for stock in stock_list:
            if stock not in now_list:
                buy.append(stock)
                    
        # 如果有需要调仓的股票，卖出
        if len(sell) > 0 :
            for stock in sell:
                order_target_value(stock, 0)
        #分钱
        if len(buy) > 0:
            Cash = context.portfolio.cash/len(buy)
        else:
            Cash = 0
        ## 买入股票
        for stock in buy:
                 order_value(stock, Cash)
        # 天计数加一
        g.days = 1
    else:
        g.days += 1
        sell_list = check_holding(context)
        if len(sell_list) > 0 :
            for stock in sell_list:
                order_target_value(stock, 0)
        

# 过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]
