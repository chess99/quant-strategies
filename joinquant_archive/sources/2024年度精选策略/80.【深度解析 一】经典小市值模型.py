# 克隆自聚宽文章：https://www.joinquant.com/post/44300
# 标题：【深度解析 一】经典小市值模型
# 作者：加百力

# 导入函数库
from jqdata import *


# 初始化函数，设置基准等等
# context 是由系统维护的上下文环境
# 包含买入均价、持仓情况、可用资金等资产组合相关信息
def initialize(context):
    
    # g. 开头的是全局变量
    # 一经声明整个程序都可以使用
    
    # 设置持股数量
    g.stocknum = 10
    
    # 待买入股票列表
    g.buylist = []           
    
    # 设置沪深300股指作为基准
    # 如果不设置，默认的基准也是沪深300股指
    set_benchmark('000300.XSHG')
    
    # 开启动态复权模式(使用真实价格)
    set_option('use_real_price', True)
    
    # 交易量不超过实际成交量的 0.1
    set_option('order_volume_ratio', 0.1)
    
    # 在日志中写入字符串
    # 整个回测过程中，只会在开始阶段写入一次
    log.info('初始函数开始运行且全局只运行一次')
    
    # 过滤掉order系列API产生的比error级别低的log
    # 默认是 'debug' 参数。最低的级别，日志信息最多
    # 系统推荐尽量使用'debug'参数或不显式设置，方便找出所有错误
    log.set_level('order', 'error')
    
    # 设置滑点
    # 0.02 的滑点设置还比较高
    set_slippage(FixedSlippage(0.02))
    
    # 止损函数在每个交易日的 9:45 都被调用一次
    # 主要是为了尽量控制风险
    # 止损函数调用时间在开仓、调仓函数之前
    run_daily(stoploss, '9:45') 


    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣 5 元钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')


    # 每周只在第一个交易日进行股票筛选、过滤、排序、开仓、调仓等操作
    
    # 开盘时运行 filter_stocks() 函数
    # 筛选、过滤生成待买入股票列表为交易做准备 
    run_weekly(filter_stocks,1,'09:30') 
    
    # 开盘后 10:00 进行开仓、调仓操作
    run_weekly(market_open,1,'10:00') 
    


## 筛选、排序股票，生成待交易股票列表
def filter_stocks(context):
    
    # 在日志中输出该函数运行的时间
    # 回测历史数据时就是当时的日期时间
    log.info(str('函数运行时间（filter_stocks）:' + str(context.current_dt.time())))
    
    
    # 获取当前时间的行情数据
    # 获取当前单位时间（当天/当前分钟）的涨跌停价, 是否停牌，当天的开盘价等
    # 回测时, 通过其他获取数据的API获取到的是前一个单位时间(天/分钟)的数据
    # 而有些数据, 我们在这个单位时间是知道的, 比如涨跌停价, 是否停牌, 当天的开盘价
    curr_data = get_current_data()
    
    # 获取 上证综指和深证综指 的成份股
    # 这个股票范围也很关键
    # 如果换成其他一些股票指数的成分股，收益率可能大幅下降
    scu = get_index_stocks('000001.XSHG') + get_index_stocks('399106.XSHE')
    
    
    # 过滤 开盘就涨停、跌停 的股票
	# 过滤 当日暂停交易 的股票    
	# 过滤 含有 ST、* 及退市标签 的股票
	# 外围 [] 用于生成列表
	# 内部是一个 for...in 表达式
	# 针对 scu 股票列表中的每一只股票代码做分析过滤
	# 括号里面是连续的 or 逻辑表达式，只要满足一个条件就为 True
	# 小括号外面 not 取否。任何一个条件成立都会被过滤掉
    scu = [stock for stock in scu if not (
            (curr_data[stock].day_open == curr_data[stock].high_limit) or
            (curr_data[stock].day_open == curr_data[stock].low_limit) or
            curr_data[stock].paused  or
            ('ST' in curr_data[stock].name) or
            ('*' in curr_data[stock].name)  or
            ('退' in curr_data[stock].name)
    )]
    
    
    
    # 获取市值最小的股票列表
    
    # query()生成一个 query 对象
    # query(valuation.code,valuation.market_cap) 查询 valuation 表的 股票代码、总市值 字段
    # filter(valuation.code.in_(scu))。过滤条件是股票代码必须在 scu 列表中。注意不是 in 而是 in_
    # order_by(valuation.market_cap.asc())。按照市值升序排列。小市值股票在前，大市值股票在后
    # limit(g.stocknum) 限制只取 g.stocknum 数量的股票
    q = query(valuation.code,valuation.market_cap).filter(valuation.code.in_(scu)).order_by(valuation.market_cap.asc()).limit(g.stocknum)
    
    # get_fundamentals() 读取指定日期的股票查询数据
    # date = context.previous_date。对前一个交易日的股票数据做筛选、排序
    # 读取结果以数据框的形式赋值给 df 
    df = get_fundamentals(q,date = context.previous_date)
    
    # 将 df 数据框中的 code 列数据转换成列表类型数据
    stocklist = list(df['code'])
    
    # 将待买入股票列表赋值给全局变量
    g.buylist = stocklist


# 止损函数
# 每天检查是否有股票触发止损条件
# 如有触发则立即卖出平仓
def stoploss(context):
    
    # 使用 for 循环遍历 context.portfolio.positions 当前持仓的每一只股票
    for stock in context.portfolio.positions:
        
        # 读取每只持仓股票的买入均价赋值给 cost 变量
        cost = context.portfolio.positions[stock].avg_cost
        
        # 读取每只持仓股票的当前价格
        price = context.portfolio.positions[stock].price
        
        # 计算每只持仓股票当前的收益率
        ret = price/cost-1
        
        # 如果收益率小于 -0.2 表示浮亏已经突破 -20%
        if ret < -0.2:
            
            # 清仓该只股票
            # order_target() 将该只股票的持仓量调整为 0
            order_target(stock,0)
            
            # 在日志中写入"触发止损"这个字符串
            log.info('触发止损')
                

                
## 开盘时运行函数
def market_open(context):
    
    # 在日志中写入函数运行时间
    log.info(str('函数运行时间（market_open）:'+str(context.current_dt.time())))
    
    # 如果待买入股票列表长度为 0，表示没有要操作的股票
    # 则直接返回
    if(len(g.buylist) == 0):
        return
    
    # 待买入股票列表中有要买入的股票
    # 则调用 rebalance() 函数开仓或调仓
    rebalance(context,g.buylist)



# 调仓 rebalance() 函数
# 第一个参数为上下文环境
# 第二个参数为待买入股票列表
def rebalance(context,buylist):
    
    # 根据当前资产组合的价值，计算每只股票应持仓金额
    every_stock = context.portfolio.portfolio_value/len(buylist)
    
    # 如果当前没有持仓就全部买入。等额分配资金
    if len(list(context.portfolio.positions.keys())) == 0 :
        
        # for 循环对待买入列表中的每只股票都进行购买操作
        for stock_to_buy in buylist :
            
            # 根据 every_stock 价值买入股票
            order_target_value(stock_to_buy, every_stock)
            
    # 如果有持仓，先卖出已经持有但不在待买入列表中的股票
    # 卖出已经过时的股票
    else:
        
        # 遍历每一只持仓股票代码
        for stock_to_sell in list(context.portfolio.positions.keys()):
            
            # 如果这只股票代码不在买入列表中，说明已经过时应该清仓
            if stock_to_sell not in buylist:
                
                # 清仓这只股票
                # 股票的持仓价值额度为0
                order_target_value(stock_to_sell, 0)
        
        # 为buylist里的每支股票调整仓位
        # 这句非常重要
        # 一方面会买入当前未持仓的列表中的股票
        # 另一方面也会影响其他持仓股票的仓位
        # 低于资产组合平均价值的股票会加仓
        # 高于资产组合平均价值的股票会减仓
        # 实验证明调仓对于提高收益率很有帮助
        for i in buylist:
            order_target_value(i, every_stock)
            
