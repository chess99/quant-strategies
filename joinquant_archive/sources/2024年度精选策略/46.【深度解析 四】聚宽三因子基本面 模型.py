# 克隆自聚宽文章：https://www.joinquant.com/post/44409
# 标题：【深度解析 四】聚宽三因子基本面 模型
# 作者：加百力

# 导入模块
from jqdata import *
from jqfactor import get_factor_values

# ------------------------------------------------------------------------
# 初始化函数

# 初始化函数，设置基准等等
# context 是由系统维护的上下文环境
# 包含买入均价、持仓情况、可用资金等资产组合相关信息
def initialize(context):
    
    # 设定基准
    # '000905.XSHG' 中证500指数
    set_benchmark('000905.XSHG')
    
    
    # 开启动态复权模式(使用真实价格)
    set_option('use_real_price', True)
    
    
    # 避免使用未来数据
    set_option("avoid_future_data", True)
    
    
    # 将滑点设置为 0
    # 可以在 归因分析 中查看不同滑点情况的收益曲线
    set_slippage(FixedSlippage(0))
    
    
    # 交易量不超过实际成交量的 0.1
    set_option('order_volume_ratio', 0.1)    
    
    
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，
    # 卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣 5 元钱
    set_order_cost(OrderCost(close_tax=0.001,
                   open_commission=0.0003, 
                   close_commission=0.0003, 
                   min_commission=5), 
                   type='stock')

                   
    # 过滤掉order系列API产生的比error级别低的log
    # 默认是 'debug' 参数。最低的级别，日志信息最多
    # 系统推荐尽量使用'debug'参数或不显式设置，方便找出所有错误
    log.set_level('order', 'error')
    
    
    # 初始化全局变量
    
    # g. 开头的是全局变量
    # 一经声明整个程序都可以使用
    
    # 最大股票持仓数量
    g.stock_num = 10
    
    # 限制交易天数。某只股票平仓之后 限制交易天数 内不会再购买
    # 避免某些股票刚刚平仓或止损，又重新买入
    g.limit_days = 20
    
    
    # 昨日涨停股列表
    g.high_limit_list = []
    
    # 当日持仓股票列表
    g.hold_list = []
    
    # 历史持仓股票列表
    # 每个元素是 当日（或前几日）持仓列表
    g.history_hold_list = []
    
    # 不再重复买入列表    
    g.not_buy_again_list = []
    
    
    # 设置交易时间
    # 每个交易日都运行
    
    # 每个交易日的 9:00 开始准备股票列表
    run_daily(prepare_stock_list, time='9:00')
    
    # 每周第一个交易日 09:40 调整仓位
    run_weekly(weekly_adjustment, weekday=1, time='09:40')
    # run_monthly(weekly_adjustment, 1, time='09:40')
    
    # 每个交易日 14:00 调用 check_limit_up() 处理昨日涨停股票
    # 如果今日还是涨停则继续持仓
    # 反之则直接平仓这只股票
    run_daily(check_limit_up, time='14:00')
    
    # 每个交易日 15:30
    # 输出持仓的每只股票的仓位信息
    run_daily(print_position_info, time='15:30')


# ------------------------------------------------------------------------
# 1、股票排序、过滤、调仓相关函数

# 1-1 根据股票列表获取指定的因子数据、排序后截取指定范围的股票
# context, 上下文环境参数
# stock_list,待处理股票列表
# jqfactor,要获取的因子名称
# sort,排序方式
# p1,待截取数据的起始位置
# p2,待截取数据的结束位置
def get_factor_filter_list(context,stock_list,jqfactor,sort,p1,p2):
    
    # 取前一个交易日的日期
    yesterday = context.previous_date
    
    # get_factor_values() 获取质量因子、基础因子、情绪因子、成长因子、风险因子、每股因子等数百个因子数据
    # get_factor_values(securities, factors, start_date, end_date, count)
    # securities:股票池，单只股票（字符串）或一个股票列表
    # factors:   因子名称，单个因子（字符串）或一个因子列表
    # start_date:开始日期，字符串或 datetime 对象，与 coun t参数二选一
    # end_date:  结束日期， 字符串或 datetime 对象，可以与 start_date 或 count 配合使用
    # count:     截止 end_date 之前交易日的数量（含 end_date 当日），与 start_date 参数二选一
    
    # 返回值是一个 dict： key 是因子名称， value 是 pandas.dataframe
    # dataframe 的 index 是日期， column 是股票代码， value 是因子值
    # 为了防止单次返回数据时间过长，每次调用 api 请求的因子值(因子数股票数交易日数)不能超过 200000 个    
    score_list = get_factor_values(stock_list, 
                                   jqfactor, 
                                   end_date=yesterday, 
                                   count=1)[jqfactor].iloc[0].tolist()
    
    # 生成一个两列的数据框
    # 列名分别是：'code','score'
    df = pd.DataFrame(columns=['code','score'])
    
    # 将股票列表和因子数据列表赋值到数据框中
    df['code'] = stock_list
    df['score'] = score_list
    
    # 删除数据框中的na数据
    df = df.dropna()
    
    # 根据 score 列对数据框排序
    # 根据 sort 参数决定是否为升序
    # 用排序结果直接修改原数据框
    df.sort_values(by='score', ascending=sort, inplace=True)
    
    # 将 code 列转换成列表
    # 使用冒号表达式，截取指定范围的股票代码
    # int() 转换为整数。方便计算截取的范围
    filter_list = list(df.code)[int(p1*len(df)):int(p2*len(df))]
    
    # 返回通过因子过滤后的股票列表
    return filter_list




# 1-2 获取股票列表
# context,上下文环境参数
# 过滤科创、北交、ST股
# 并截取 长期毛利率增长、每股净资产、非线性市值 最小的前 10% 股票，通过 流通市值 升序排序
# 最后对三类股票取并集去重，返回股票列表
def get_stock_list(context):
    
    # 获取前一个交易日的日期
    yesterday = context.previous_date
    
    # get_all_securities(date=by_date) by_date 日期时在交易的所有股票数据
    # get_all_securities() 可以查询正在交易的 股票、基金、期货、期权 信息
    # 默认查询的是股票数据
    # .index 获得的数据类型是 数据框。这个数据框的行索引正是 股票代码
    # .tolist() 转换成列表数据类型
    
    # 一次性获取当时所有上市的股票
    # 再通过后续的过滤函数做过滤
    initial_list = get_all_securities().index.tolist()
    
    # 过滤 科创板、北交所 股票
    initial_list = filter_kcbj_stock(initial_list)
    
    # 过滤 ST 股票
    initial_list = filter_st_stock(initial_list)
    
    # 过滤次新股
    # 已经上市至少 250 日的股票
    initial_list_1 = filter_new_stock(context, initial_list, 250)
    
    
    
    # 因子数据的含义可以在 因子库 中查找
    # 链接：https://www.joinquant.com/help/api/help#name:factor_values
    
    # 1、选取长期毛利率增长最小的前 10% 的股票
    test_list = get_factor_filter_list(context, 
                                       initial_list_1,
                                       'DEGM_8y',      # 长期毛利率增长	过去8年(1+DEGM)的累成 ^ (1/8) - 1
                                       True,           
                                       0, 0.1)
    
    
    
    # 财务指标数据可以通过 股票数据 查询
    # 链接：https://www.joinquant.com/help/api/help#Stock:%E8%8E%B7%E5%8F%96%E5%8D%95%E5%AD%A3%E5%BA%A6%E5%B9%B4%E5%BA%A6%E8%B4%A2%E5%8A%A1%E6%95%B0%E6%8D%AE
    
    # query()生成一个 query 对象
    # query(valuation.code,valuation.circulating_market_cap) 查询 valuation 表的 股票代码、流通市值 字段
    # indicator.eps 查询 indicator 表的 eps 字段。eps 是每股收益(元)。每股收益(摊薄)＝净利润/期末股本；分子从单季利润表取值，分母取季度末报告期股本值；净利润指归属于母公司股东的净利润(元)
    # filter(valuation.code.in_(test_list))。过滤条件是股票代码必须在 test_list 列表中。注意不是 in 而是 in_
    # order_by(valuation.circulating_market_cap.asc()。按照流通市值升序排列。小市值股票在前，大市值股票在后
    q = query(valuation.code,
              valuation.circulating_market_cap,
              indicator.eps).\
              filter(valuation.code.in_(test_list)).\
              order_by(valuation.circulating_market_cap.asc()
              )
              
    # get_fundamentals() 读取指定日期的股票查询数据
    # date=yesterday。查询的时前一个交易日的数据
    # 读取结果以数据框的形式赋值给 df               
    df = get_fundamentals(q, date=yesterday)
    
    
    # 对数据框进行过滤
    # 要求 eps 每股收益必须大于0
    df = df[ df['eps']>0 ]
    
    # 从长期毛利率增长角度，满足条件的前5只股票
    roa_list = list(df.code)[:5]

    
    
    # 2、选取每股净资产最小的前 10% 的股票
    test_list = get_factor_filter_list(context, 
                                       initial_list_1, 
                                       'net_asset_per_share',   # 每股净资产
                                       True, 
                                       0, 0.1)
    
    # 这部分的函数调用与上面相同
    q = query(valuation.code,
              valuation.circulating_market_cap,
              indicator.eps).\
              filter(valuation.code.in_(test_list)).\
              order_by(valuation.circulating_market_cap.asc())
              
    df = get_fundamentals(q, date=yesterday)
    
    df = df[df['eps']>0]
    
    # 从每股净资产角度，满足条件的前5只股票
    reps_list = list(df.code)[:5]
    
    
    
    # 3、选取非线性市值最小的前 10% 的股票
    # 过滤次新股
    # 要求上市时间至少是125天以上
    # 注意这里使用的是 initial_list 列表
    # 还未进行 250 日次新股过滤
    # 只进行了 科创、北交、ST 过滤
    initial_list_2 = filter_new_stock(context, initial_list, 125)
    
    test_list = get_factor_filter_list(context, 
                                       initial_list_2, 
                                       'non_linear_size',  # 非线性市值。描述了无法由规模因子解释的但与规模有关的收益差异，通常代表中盘股
                                       True, 
                                       0, 0.1)

    # 这部分的函数调用与上面相同                                   
    q = query(valuation.code,
              valuation.circulating_market_cap,
              indicator.eps).\
              filter(valuation.code.in_(test_list)).\
              order_by(valuation.circulating_market_cap.asc())
    
    df = get_fundamentals(q, date=yesterday)
    
    df = df[df['eps']>0]
    
    # 从非线性市值角度，满足条件的前5只股票
    nls_list = list(df.code)[:5]
    
    
    # 并集去重
    # 三个列表先转换成 集合类型数据，逐个调用 union() 函数
    # 完成并集操作，同时去掉同名股票代码
    union_list = list( set(roa_list).union(set(reps_list)).union(set(nls_list)) )
    
    # 还是按照流通市值升序排列
    q = query(valuation.code,
              valuation.circulating_market_cap).\
              filter(valuation.code.in_(union_list)).\
              order_by(valuation.circulating_market_cap.asc())
              
    df = get_fundamentals(q, date=yesterday)
    
    final_list = list(df.code)
    
    # 返回三个集合的去重并集
    return final_list




#1-3 准备股票池
# 模型运行需要多个股票列表
# 这个函数用于维护这些股票列表
# 每个交易日的 9:00 开始准备这些股票列表
def prepare_stock_list(context):
    
    # 获取已持仓股票列表
    # 清空持仓列表
    # 删除旧的持仓信息
    g.hold_list = []
    
    # for 循环遍历持仓信息
    # append() 方法扩展持仓列表
    for position in list(context.portfolio.positions.values()):
        stock = position.security
        g.hold_list.append(stock)
        
    # 获取最近一段时间持有过的股票列表
    # 将当前持仓列表加入历史持仓列表中
    # 这个过程每天都要进行一次
    # 当前持仓列表以单个元素的形式加入。每个交易日一个元素
    g.history_hold_list.append(g.hold_list)
    
    # 通过测量历史持仓的长度判断有多少个持仓列表
    # 如果已经超过限制天数，则说明积累的持仓记录足够多了
    if len(g.history_hold_list) >= g.limit_days:
        
        # 用末尾的持仓记录替换整个持仓记录
        g.history_hold_list = g.history_hold_list[-g.limit_days:]
    
    # 定义一个临时的集合变量
    temp_set = set()
    
    # 此时的 g.history_hold_list 是由多个 当日持仓列表 组成的大列表
    # 遍历每一个当日持仓列表
    for hold_list in g.history_hold_list:
        # 针对每个当日持仓列表中的股票做分析
        for stock in hold_list:
            # 在临时集合中加入个股
            # 使用集合来去除重复股票
            temp_set.add(stock)
            
    # 历史持仓集合转换成列表
    # 保存在 不重复买入 列表中
    g.not_buy_again_list = list(temp_set)
    
    # 获取昨日涨停列表
    # 如果持仓列表不为空则进行分析
    if g.hold_list != []:
        
        # 读取持仓列表中股票的 收盘价 和 涨停价信息
        df = get_price(g.hold_list, 
                       end_date=context.previous_date, 
                       frequency='daily', 
                       fields=['close','high_limit'], 
                       count=1, 
                       panel=False, 
                       fill_paused=False)
        
        # 抽取 收盘价 和 涨停价相同的股票数据
        df = df[ df['close'] == df['high_limit'] ]
        
        # 将涨停股的股票代码转换成列表保存在 昨日涨停股列表 中
        g.high_limit_list = list(df.code)
        
    else:
        
        # 持仓列表为空，则 昨日涨停股列表也为空
        g.high_limit_list = []




#1-4 整体调整持仓
# 每周第一个交易日 09:40 调整仓位
def weekly_adjustment(context):
    
    # 获取应买入列表
    
    # 对股票进行过滤，使用三大财务指标筛选股票并排序
    target_list = get_stock_list(context)
    
    # 过滤停牌股票
    target_list = filter_paused_stock(target_list)
    
    # 过滤涨停/跌停股票
    target_list = filter_limitup_stock(context, target_list)
    target_list = filter_limitdown_stock(context, target_list)
    
    # 过滤最近买过且涨停过的股票
    recent_limit_up_list = get_recent_limit_up_stock(context, target_list, g.limit_days)
    
    # 生成股票黑名单
    # 近期禁止交易股票 和 涨停股票取交集
    black_list = list(set(g.not_buy_again_list).intersection(set(recent_limit_up_list)))
    
    # 目标股票是黑名单之外的股票
    # for...in 表达式。选择不在黑名单中的股票
    target_list = [stock for stock in target_list if stock not in black_list]
    
    # 截取不超过最大持仓数的股票量
    target_list = target_list[:min(g.stock_num, len(target_list))]
    
    

    # 调仓卖出
    # 遍历当前持仓列表中的每一只股票
    for stock in g.hold_list:
        
        # 如果不在目标列表，也不在 昨日涨停列表中则平仓卖出股票
        if (stock not in target_list) and (stock not in g.high_limit_list):
            # 在日志中记录卖出股票名称
            log.info("卖出[%s]" % (stock))
            # context.portfolio.positions 中读取股票仓位
            position = context.portfolio.positions[stock]
            # 调用 close_position() 平仓
            close_position(position)
        else:
            # 无需卖出或昨日涨停则不操作
            log.info("已持有[%s]" % (stock))
            
    
    # 调仓买入
    # 计算持仓股票数
    position_count = len(context.portfolio.positions)
    # 计算要买入的股票数
    target_num = len(target_list)
    # 如果要买入的股票数大于持仓股票数
    if target_num > position_count:
        # 为待买入股票平均分配剩余现金
        # 前期已经先行平老仓，释放了现金
        value = context.portfolio.cash / (target_num - position_count)
        
        # 遍历待买入列表中的每一只股票
        for stock in target_list:
            # 如果这只股票的当前仓位为0
            if context.portfolio.positions[stock].total_amount == 0:
                # 买入之前计算额度的股票
                if open_position(stock, value):
                    # 如果持仓数量已经达到要买入的股票数量
                    # 则直接跳出循环
                    if len(context.portfolio.positions) == target_num:
                        break




# 1-5 调整昨日涨停股票
# 每个交易日 14:00 调用 check_limit_up() 处理昨日涨停股票
# 对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
def check_limit_up(context):
    
    # 获取当前日期
    now_time = context.current_dt
    
    # 如果昨日涨停股票列表不为空
    if g.high_limit_list != []:
        
        # 对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
        # 遍历昨日涨停股票列表中的每一只股票
        for stock in g.high_limit_list:
            
            # 读取股票一分钟级别的 收盘价、涨停价 数据
            current_data = get_price(stock, 
                                     end_date=now_time, 
                                     frequency='1m', 
                                     fields=['close','high_limit'], 
                                     skip_paused=False, 
                                     fq='pre', 
                                     count=1, 
                                     panel=False, 
                                     fill_paused=True)
            
            # 如果当前价格小于涨停价 
            if current_data.iloc[0,0] < current_data.iloc[0,1]:
                # 日志中记录，涨停打开将要卖出的股票名称
                log.info("[%s]涨停打开，卖出" % (stock))
                # 获取当前要卖出的股票仓位
                position = context.portfolio.positions[stock]
                # 调用函数平仓
                close_position(position)
            else:
                # 日志中记录，仍然涨停，继续持有股票名称
                log.info("[%s]涨停，继续持有" % (stock))


# ------------------------------------------------------------------------
# 2、过滤股票相关函数


# 2-1 过滤停牌股票
def filter_paused_stock(stock_list):
    
    # 获取当前时间的行情数据
    # 获取当前单位时间（当天/当前分钟）的涨跌停价, 是否停牌，当天的开盘价等
    # 回测时, 通过其他获取数据的API获取到的是前一个单位时间(天/分钟)的数据
    # 而有些数据, 我们在这个单位时间是知道的, 比如涨跌停价, 是否停牌, 当天的开盘价    
	current_data = get_current_data()
	return [stock for stock in stock_list if not current_data[stock].paused]



# 2-2 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
    
	current_data = get_current_data()
	
	return [stock for stock in stock_list
			if not current_data[stock].is_st
			and 'ST' not in current_data[stock].name
			and '*'  not in current_data[stock].name
			and '退' not in current_data[stock].name]



#2-3 获取最近 N 个交易日内 有涨停 的股票
def get_recent_limit_up_stock(context, stock_list, N):
    
    # 获取前一个交易日的日期
    stat_date = context.previous_date
    
    # 定义存在涨停现象的股票列表
    # 开始阶段为空列表
    new_list = []
    
    # 遍历股票列表中每只股票
    for stock in stock_list:
        
        # 读取前 N 个交易日的股价日线数据，收盘价、涨停价
        df = get_price(stock, 
                       end_date=stat_date, 
                       frequency='daily', 
                       fields=['close','high_limit'], 
                       count=N, 
                       panel=False, 
                       fill_paused=False)
        
        # 选取收盘价和涨停价相同的记录，存入数据框
        df = df[ df['close'] == df['high_limit'] ]
        
        # 如果数据框中条目数大于0，表示存在涨停现象
        if len(df) > 0:
            # 在列表中追加存在涨停现象的股票代码
            new_list.append(stock)
            
    return new_list



#2-4 过滤涨停的股票
def filter_limitup_stock(context, stock_list):
    
    # 获取历史数据，可查询多个标的单个数据字段，返回数据格式为 DataFrame 或 Dict(字典)
    # 读取所有股票前一分钟的收盘价
	last_prices = history(1, 
	                      unit='1m', 
	                      field='close', 
	                      security_list=stock_list)
	
	current_data = get_current_data()
	
	# 保留两种类型的股票
	# 已经在持仓列表中的股票
	# 前一分钟收盘价小于涨停价的股票
	# 如果这只股票已经在持仓列表中，即使涨停也不处理（准备继续持有）
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] < current_data[stock].high_limit]



#2-5 过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
    
	last_prices = history(1, 
	                      unit='1m', 
	                      field='close', 
	                      security_list=stock_list)
	
	current_data = get_current_data()
	
	# 保留两种类型的股票
	# 已经在持仓列表中的股票
	# 前一分钟收盘价大于跌停价的股票
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] > current_data[stock].low_limit]



#2-6 过滤科创北交股票
def filter_kcbj_stock(stock_list):
    
    # 遍历股票列表中的每一只股票
    for stock in stock_list:
        # 股票首字母是字符串 4、8、68 的过滤
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68':
            # 从列表中删除这只股票
            stock_list.remove(stock)
            
    # 返回过滤后的股票列表        
    return stock_list



#2-7 过滤次新股
def filter_new_stock(context, stock_list, d):
    
    # 获取前一个交易日的日期
    yesterday = context.previous_date
    
    # get_security_info() 获取单个标的信息
    # display_name: 中文名称
    # name: 缩写简称
    # start_date: 上市日期, [datetime.date] 类型
    # end_date: 退市日期（股票是最后一个交易日，不同于摘牌日期）， [datetime.date] 类型, 如果没有退市则为2200-01-01
    # type: 股票、基金、金融期货、期货、债券基金、股票基金、QDII 基金、货币基金
    # 混合基金、场外基金，'stock'/ 'fund' / 'index_futures' / 'futures' / 'etf'/'bond_fund' 
    # 'stock_fund' / 'QDII_fund' / 'money_market_fund' / ‘mixture_fund' / 'open_fund'
    # parent: 分级基金的母基金代码
    return [stock for stock in stock_list if

            # 昨天的日期减去股票上市日期必须大于指定的天数
            yesterday - get_security_info(stock).start_date > datetime.timedelta(days=d)
           ]


# ------------------------------------------------------------------------
# 3、交易操作相关函数


# 3-1 自定义下单函数
# 同系统的 order_target_value() 相比
# 增加了在日志中写入操作说明的内容
def order_target_value_(security, value):
    
    # value 为 0 则清空这只股票
	if value == 0:
	    # 通过 log.debug() 在日志中写入卖出股票操作
		log.debug("Selling out %s" % (security))
	else:
		log.debug("Order %s to value %f" % (security, value))
		
	return order_target_value(security, value)



# 3-2 开仓
def open_position(security, value):
    
    # 针对股票下单买入
	order = order_target_value_(security, value)
	
	# 分析调用函数后的返回结果
	if order != None and order.filled > 0:
	    # 返回下单操作的分析结果
		return True
		
	return False



# 3-3 平仓
def close_position(position):
    
	security = position.security
	
	# 可能会因停牌失败
	order = order_target_value_(security, 0)  
	
	# 分析调用函数后的返回结果
	if order != None:
		if order.status == OrderStatus.held and order.filled == order.amount:
		    # 返回下单操作的分析结果
			return True
			
	return False



# ------------------------------------------------------------------------
# 4、收盘记录日志相关函数

# 4-1 打印每日持仓信息
def print_position_info(context):
    
    # 打印当天成交记录
    trades = get_trades()
    
    for _trade in trades.values():
        print('成交记录：' + str(_trade))
    
    # 打印账户持仓信息
    for position in list(context.portfolio.positions.values()):
        
        # 持仓股票代码
        securities=position.security
        # 头寸的持仓均价
        cost=position.avg_cost
        # 头寸的当前价格
        price=position.price
        # 头寸的收益率
        ret=100*(price/cost-1)
        # 头寸的市值
        value=position.value
        # 持仓股票的数量
        amount=position.total_amount    
        
        print('代码:{}'.format(securities))
        print('成本价:{}'.format(format(cost,'.2f')))
        print('现价:{}'.format(price))
        print('收益率:{}%'.format(format(ret,'.2f')))
        print('持仓(股):{}'.format(amount))
        print('市值:{}'.format(format(value,'.2f')))
        print('———————————————————————————————————')
    print('———————————————————————————————————————分割线————————————————————————————————————————')


    
