# 克隆自聚宽文章：https://www.joinquant.com/post/44328
# 标题：【深度解析 二】资产负债与ROA模型
# 作者：加百力

# 导入函数库
from   jqdata import *
import warnings


# 初始化函数，设置基准等等
# context 是由系统维护的上下文环境
# 包含买入均价、持仓情况、可用资金等资产组合相关信息
def initialize(context):
    
    # 设置的滑点较高（不设置滑点的话用默认的0.00246）
    set_slippage(FixedSlippage(0.02))
    
    # 设置沪深300股指作为基准
    # 如果不设置，默认的基准也是沪深300股指
    set_benchmark('000300.XSHG') 
    
    # 开启动态复权模式(使用真实价格)
    set_option('use_real_price', True)
    
    # 避免使用未来数据
    set_option('avoid_future_data', True)
    
    # 过滤掉order系列API产生的比error级别低的log
    # 默认是 'debug' 参数。最低的级别，日志信息最多
    # 系统推荐尽量使用'debug'参数或不显式设置，方便找出所有错误
    log.set_level('order', 'error')
    
    # 过滤 'ignore' 级别的警告信息
    warnings.filterwarnings('ignore')


    # g. 开头的是全局变量
    # 一经声明整个程序都可以使用
    
    # 选股参数
    
    # 最大股票持仓数量
    g.stock_num = 5
    
    # 仓位比例。计算仓位时使用
    g.position = 1  

    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣 5 元钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
     
    # 设置交易时间
    # 每个月第一个交易日，上午 10:00 调用 my_trade() 函数
    run_monthly(my_trade, monthday=1, time='10:00', reference_security='000300.XSHG')
    



# 交易函数
# 过滤、筛选、排序生成待买入股票列表
# 并根据待交易股票列表开仓或调整仓位
def my_trade(context):
    
    # 过滤：次新股，ST,ST*,退市,涨停,跌停,停牌 股票
    # 根据 资产负债率、不良资产率、优质资产周转率、ROA 增长量等财务指标过滤、排序股票
    # 生成待买入股票列表
    check_out_list = get_stock_list(context)
    
    # 在日志中输出今日准备购买的股票列表
    log.info('今日准备购买的股票:%s' % check_out_list)
    
    # 调整头寸规模
    # 卖出不再列表中的股票
    # 买入新选出的股票
    adjust_position(context, check_out_list)




# 选股模块
def get_stock_list(context):
    
    # 获取当前时间的行情数据
    # 获取当前单位时间（当天/当前分钟）的涨跌停价, 是否停牌，当天的开盘价等
    # 回测时, 通过其他获取数据的API获取到的是前一个单位时间(天/分钟)的数据
    # 而有些数据, 我们在这个单位时间是知道的, 比如涨跌停价, 是否停牌, 当天的开盘价
    curr_data = get_current_data()
    
    # 获取前一个交易日的日期
    yesterday = context.previous_date
    
    # 生成数据框保存每次过滤后，符合条件股票数量
    df_stocknum = pd.DataFrame(columns=['当前符合条件股票数量'])
    
    
    # 过滤次新股
    # datetime.timedelta(days=1200) 获得时间变化量
    # 365*3=1095 天。1200 日是 3 年还多 3 个月
    # by_date 是三年多前的 老日期
    by_date = yesterday - datetime.timedelta(days=1200)
    
    
    # get_all_securities(date=by_date) by_date 日期时在交易的所有股票数据
    # get_all_securities() 可以查询正在交易的 股票、基金、期货、期权 信息
    # 默认查询的时股票数据
    # date=by_date 指定查询的日期是三年多前的 老日期
    # .index 获得的数据类型是 数据框。这个数据框的行索引正是 股票代码
    # .tolist() 转换成列表数据类型
    initial_list = get_all_securities(date=by_date).index.tolist()
    


    # 对初步得到的股票列表做过滤
    # 过滤 当时已经 涨停、跌停 的股票
	# 过滤 当日暂停交易 的股票    
	# 过滤 含有 ST、* 及退市标签 的股票
	# 外围 [] 用于生成列表
	# 内部是一个 for...in 表达式
	# 针对 initial_list 股票列表中的每一只股票代码做分析过滤
	# 括号里面是连续的 or 逻辑表达式，只要满足一个条件就为 True
	# 小括号外面 not 取否。任何一个条件成立都会被过滤掉
    initial_list = [stock for stock in initial_list if not (
            (curr_data[stock].day_open == curr_data[stock].high_limit) or
            (curr_data[stock].day_open == curr_data[stock].low_limit) or
            curr_data[stock].paused  or
            ('ST' in curr_data[stock].name) or
            ('*'  in curr_data[stock].name) or
            ('退' in curr_data[stock].name) 
    )]
    
    
    # 扩展 df_stocknum 数据框的数据
    # 加入当前符合条件的股票数量
    # 每进行一次过滤都更新这个数据框
    df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(initial_list)}, ignore_index=True)
    

    # 1、选出资产负债率由高到低后 70% 的股票代码保存在 low_liability_list
    # get_fundamentals()查询当前日期的财务数据
    # query() 生成 query 查询对象
    # balance.code, balance.total_liability, balance.total_assets
    # 查询 balance 表中的股票代码、负债合计、资产总计 数据    
    # total_liability: 负债合计是指企业所承担的能以，将以资产或劳务偿还的债务，偿还形式包括货币、资产或提供劳务
    # total_assets：资产总计
    # valuation.code.in_(initial_list) 过滤条件
    # 估值表中的股票代码必须在 initial_list 中
    # .dropna() 去除 na 数据
    df = get_fundamentals(
        query(
            balance.code, balance.total_liability, balance.total_assets
        ).filter(
            valuation.code.in_(initial_list)
        )
    ).dropna()
    
    # 用 0 填充 na 数据
    df = df.fillna(0)
    
    # 计算资产负债率
    df['ratio'] = df['total_liability'] / df['total_assets']
    
    # 按照 资产负债率 对数据框进行排序
    # 使用 降序方式 排序
    # 资产负债率高的排在前面，低的排在后面
    df = df.sort_values(by = 'ratio',ascending=False)
    

    # low_liability_list 低负债股票列表
    # [int(0.3*len(list(df.code))):] 列表切片
    # 取出资产负债率由高到低后 70% 的股票代码
    low_liability_list = list(df.code)[int(0.3*len(list(df.code))):]
    
    # 经过本轮过滤后剩下多少股票
    df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(low_liability_list)}, ignore_index=True)

  

    # 2、从low_liability_list中选出不良资产比率在总体中[10%-90%]范围内的的股票代码保存在 proper_receivable_list 中
    df1 = get_fundamentals(
        query(balance.code,
              balance.total_assets,     # 总资产
              balance.bill_receivable,  # 应收票据
              balance.account_receivable,  # 应收账款
              balance.other_receivable,  # 其他应收款
              balance.good_will,  # 商誉
              balance.intangible_assets,  # 无形资产
              balance.inventories,  # 存货
              balance.constru_in_process,# 在建工程
              ).filter(
            balance.code.in_(low_liability_list)
        )
    ).dropna()
    
    df1 = df1.fillna(0)


    # bad_assets 计算
    # 针对每只股票把除去 total_assets 的各个部分加在一起
    df1['bad_assets'] = df1.sum(axis=1) - df1['total_assets']   
    
    # 计算不良资产率
    df1['ratio1'] =  df1['bad_assets'] / df1['total_assets']
    
    # 按照 不良资产率 对数据框做排序
    # 使用 降序方式 排序
    # 不良资产率高的在前，低的在后
    df1 = df1.sort_values(by = 'ratio1',ascending=False)
    
    # [int(0.1*len(list(df1.code))) : int(0.9*len(list(df1.code)))]
    # 不良资产比率在总体中[10%-90%]范围内的的股票代码
    proper_receivable_list = list(df1.code)[int(0.1*len(list(df1.code))):int(0.9*len(list(df1.code)))]
    
    # 筛选过滤后剩下的股票数量
    df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(proper_receivable_list)}, ignore_index=True)
    
    
    # 3、从 proper_receivable_list 中选出 优质资产周转率前75% 的股票代码，存入proper_receivable_list1
    df2 = get_fundamentals(
        query(balance.code,
              balance.total_assets,  # 总资产
              balance.bill_receivable,  # 应收票据
              balance.account_receivable,  # 应收账款
              balance.other_receivable,  # 其他应收款
              balance.good_will,  # 商誉
              balance.intangible_assets,  # 无形资产
              balance.inventories,  # 存货
              balance.constru_in_process,# 在建工程
              income.total_operating_revenue # 营业收入
              ).filter(
            balance.code.in_(proper_receivable_list)
        )
    ).dropna()
   
    df2 = df2.fillna(0)
    
    # 总资产中减去各种不良资产，剩下比较优质的资产
    df2['good_assets'] = df2['total_assets'] - (df2.sum(axis=1) - df2['total_assets'] - df2['total_operating_revenue'])
    
    # 营业收入除以优质资产得到 优质资产周转率
    df2['ratio2'] = df2['total_operating_revenue'] / df2['good_assets']
    
    # 按照 优质资产周转率 对数据框做排序
    # 使用 降序方式 排序
    # 优质资产周转率 最高的在前，最低的在后
    df2 = df2.sort_values(by = 'ratio2',ascending=False)
    
    # [:int(0.75*len(list(df2.code)))] 选出 优质资产周转率前75% 的股票代码
    proper_receivable_list1 = list(df2.code)[:int(0.75*len(list(df2.code)))]
    
    # 筛选过滤后剩下的股票数量
    df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(proper_receivable_list1)}, ignore_index=True)

    # 如果没有满足条件的股票则直接返回空列表
    if len(proper_receivable_list1) == 0:
        return []
    
    
    # 4、从 proper_receivable_list1 中筛选前四个季度ROA增长最多(前20%）的股票
    # 按照 ROA 增长量降序排列保存在 roa_list
    # get_history_fundamentals() 获取多个季度/年度的历史财务数据
    # fields：要查询的财务数据的列表, 季度数据和年度数据可选择的列不同
    # watch_date：观察日期, 如果指定, 将返回 watch_date 日期前(包含该日期)发布的报表数据
    # 获取前 4 个季度指定股票的 股票代码 和 roa 数据
    # df3 数量较大可以达到 2000 多条
    df3 = get_history_fundamentals(
        proper_receivable_list1,
        fields=[indicator.code, indicator.roa],
        watch_date=yesterday,
        count=4,
        interval='1q'
    ).dropna()
    
   
    # 对 roa 数据做汇总和计算
    # 同一只股票的 roa 数据汇总到一起
    # lambda 表达式计算：第 4 季度 roa 相对于 roa 平均值的增长
    # 按照 降序方式 排序，增长最大的在前，最小的在后面
    s_delta_avg = df3.groupby('code')['roa'].apply(
        lambda x: x.iloc[3]  - x.mean() if len(x) == 4 else 0.0 
    ).sort_values(
        ascending=False
    )
    
    # 取前四个季度ROA增长最多(前20%）的股票
    roa_list = list(s_delta_avg[:int(0.2 * len(s_delta_avg))].index)
    
    # 筛选过滤后剩下的股票数量
    df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(roa_list)}, ignore_index=True)
    
    

    # 5、从过去四个季度ROA增长量前20%的股票中
    # 选出市净率大于 0.7 的股票，按照市净率升序排列
    # 选出前g.stock_num个，保存在final_list
    # pb_ratio 市净率(PB) 每股股价与每股净资产的比率
    # ps_ratio 市销率(PS, TTM) 市销率为股票价格与每股销售收入之比，市销率越小，通常被认为投资价值越高
    # 按照 市净率 升序方式 排列。市净率小的在前，大的在后
    pb_list = get_fundamentals(
        query(
            valuation.code
        ).filter(
            valuation.code.in_(roa_list),
            valuation.pb_ratio > 0.7,
            valuation.ps_ratio < 3,
        ).order_by(
            valuation.pb_ratio.asc()
        )
    )['code'].tolist()
    
    # 筛选过滤后剩下的股票数量
    df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(pb_list)}, ignore_index=True)
    
    # 当前符合条件股票数量
    print(df_stocknum) 
    
    # 根据 最大股票持仓数量 截取准备交易的股票列表
    final_list = pb_list[:g.stock_num]
    
    # 返回最终的待交易股票列表
    return final_list
    


# 调整仓位
# 第一次全仓买入股票
# 之后，每次卖出不在列表中的过时股票
# 买入新选出来的股票
def adjust_position(context, buy_stocks):

    # 遍历当前持仓的每只股票
    # 如果这只股票不在买入列表中就全部清仓
    for stock in context.portfolio.positions:
        if stock not in buy_stocks:
            order_target(stock, 0)
        
    # 获取当前资产组合中持仓数量
    position_count = len(context.portfolio.positions)
    
    # 如果最大持仓量大于现有持仓量，说明还有买入空间
    if g.stock_num > position_count:
        
        # 资产组合中剩余现金除以准备买入的股票数量
        # 平均分配剩余资金
        value = context.portfolio.cash * g.position / (g.stock_num - position_count)
        
        # 遍历待买入列表中的每一只股票
        for stock in buy_stocks:
            
            # 如果这只股票不在持仓列表中就买入 value 额度
            if stock not in context.portfolio.positions:
                order_target_value(stock, value)
                
                # 如果持仓列表长度等于最大持仓量，说明已经买够股票
                # 直接跳出循环
                if len(context.portfolio.positions) == g.stock_num:
                    break
