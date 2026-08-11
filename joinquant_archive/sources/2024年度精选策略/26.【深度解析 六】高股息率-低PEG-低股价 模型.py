# 克隆自聚宽文章：https://www.joinquant.com/post/44487
# 标题：【深度解析 六】高股息率-低PEG-低股价 模型
# 作者：加百力

# 导入相关模块
import pandas as pd
from   jqdata import *


# 初始化函数，设置基准等等
# context 是由系统维护的上下文环境
# 包含买入均价、持仓情况、可用资金等资产组合相关信息
def initialize(context):
    
    # 基础交易参数设置

    # 过滤掉order系列API产生的比error级别低的log
    # 默认是 'debug' 参数。最低的级别，日志信息最多
    # 系统推荐尽量使用'debug'参数或不显式设置，方便找出所有错误    
    log.set_level('order', 'error')
    
    # 开启动态复权模式(使用真实价格)
    set_option('use_real_price', True)
    
    # 避免使用未来数据
    set_option('avoid_future_data', True)
    
    # 交易量不超过实际成交量的 0.1    
    set_option('order_volume_ratio',0.1)
    
    # 设定基准
    # '000300.XSHG' 沪深300指数    
    set_benchmark('000300.XSHG')
    
    # 设置滑点
    # 通过归因分析查看不同滑点设置下的收益率
    set_slippage(PriceRelatedSlippage(0))
    
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，
    # 卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣 5 元钱
    set_order_cost(OrderCost(close_tax=0.001,
                   open_commission=0.0003, 
                   close_commission=0.0003, 
                   min_commission=5), 
                   type='stock')
    
    
    # 初始化全局变量
    
    # g. 开头的是全局变量
    # 一经声明整个程序都可以使用
    
    # 最大股票持仓数量
    # 该模型持仓数量大，收益率更高
    # 20只好于10只，10只好于5只
    g.stock_num = 20
    
    # 待买入股票列表
    g.buylist = []
    
    # 昨日涨停股票列表
    g.high_limit_list = []
    
    
    # 在指定时间调用交易函数
    
    # 每天早上 9:00 调用函数获取昨日涨停股票列表
    # 昨日涨停股票需要单独处理
    run_daily(get_high_limit, time='9:00')
    
    # 每月第一个交易日，10:00
    # 通过多重条件过滤股票池
    run_monthly(get_stocks, 1 ,time='10:00')
    
    # 每月第一个交易日 14:55 实际进行交易
    run_monthly(trade_stocks, 1 ,time='14:55')
    
    # 每月第一个交易日 16:00 收盘后在日志中输出市值、股价等数据
    run_monthly(show_cap, 1 ,time='16:00')
    
    # 每日下午 14:40 检查昨日涨停股票并进行处理
    run_daily(check_high_limit, time='14:40')



# 获取股票列表
# 严格过滤股票
# 通过 股息率、PEG、股价 等标准过滤股票
# 截取满足条件和数量的股票，准备交易
def get_stocks(context):

    # 过滤次新股
    # 上市超过 180 天的股票才会被选中
    by_date = context.previous_date - datetime.timedelta(days=180)
    stocks  = get_all_securities(date=by_date).index.tolist()
    
    # 对股票进行全面过滤
    stocks = filter_all_stocks(context,stocks)
    
    
    # 计算筛选后股票的股息率
    # 高股息(全市场最大25%)
    stocks = get_dividend_ratio_filter_list(context, stocks, False, 0, 0.25)
    
    
    # 计算股票的 PEG 数据并排序
    stocks = get_peg(context,stocks)
    
    
    # 排序获得低价股列表
    stocks = filter_highprice_stock(context,stocks)     
    
    
    # 根据最大待持仓股票数量截取股票列表
    g.buylist = stocks[:g.stock_num]



# 交易股票函数
# 根据全局变量 g.buylist 交易股票
# 首先卖出不在待买入股票列表中的股票
# 获得的现金平均分配，买入新的股票
# 标准的 一买一卖 交易方式
def trade_stocks(context):
    
    cdata = get_current_data()
    
    # 卖出不在 待买入股票列表 中的股票
    for s in context.portfolio.positions:
        if (s  not in g.buylist) :
            log.info('Sell', s, cdata[s].name)
            order_target(s, 0)
            
    
    # 买入 待买入股票列表 中的股票
    position_count = len(context.portfolio.positions)
    if g.stock_num > position_count:
        # 前一个循环已经平掉旧仓释放资金
        # 根据待买入股票数量平均分配资金
        psize = context.portfolio.available_cash/(g.stock_num - position_count)
        # 遍历待买入股票列表买入股票
        for s in g.buylist:
            
            if s not in context.portfolio.positions:
                log.info('buy', s, cdata[s].name)
                order_value(s, psize)
                
                if len(context.portfolio.positions) == g.stock_num:
                    break




# 读取并在日志中输出
# 持仓股票的市值及股价数据
def show_cap(context):

    # 获取当前时间的行情数据
    # 获取当前单位时间（当天/当前分钟）的涨跌停价, 是否停牌，当天的开盘价等
    # 回测时, 通过其他获取数据的API获取到的是前一个单位时间(天/分钟)的数据
    # 而有些数据, 我们在这个单位时间是知道的, 比如涨跌停价, 是否停牌, 当天的开盘价    
    current_data = get_current_data()
    
    # 获取持仓股票数据
    hold_stocks = context.portfolio.positions.keys()
    
    # 遍历持仓股票
    # 输出市值、股价等信息
    for s in hold_stocks:
        
        # 查询指定代码的估值表数据
        q  = query(valuation).filter(valuation.code == s)
        df = get_fundamentals(q)
        
        # 在日志中写入股票名称，市值、股价
        log.info(s,current_data[s].name,'市值',df['market_cap'][0],'亿')
        log.info(s,current_data[s].name,'股价',current_data[s].last_price,'元')




# 根据最近一年分红除以当前总市值计算股息率并筛选    
def get_dividend_ratio_filter_list(context, stock_list, sort, p1, p2):
    
    time1 = context.previous_date
    time0 = time1 - datetime.timedelta(days=365)
    
    # 获取分红数据，由于 finance.run_query() 最多返回4000行
    # 以防未来数据超限，最好把 stock_list 拆分后查询再组合
    
    # 某只股票可能一年内多次分红，导致其所占行数大于1，所以interval不要取满4000
    interval = 1000
    list_len = len(stock_list)
    
    
    # 截取不超过 interval 的列表并查询
    
    # 上市公司分红送股（除权除息）数据
    # finance.STK_XR_XD：代表除权除息数据表，记录由上市公司年报、中报、一季报、三季报统计出的分红转增情况
    # code	股票代码
    # a_registration_date	A股股权登记日
    # bonus_amount_rmb	    派息金额(人民币)     单位：万元
    
    q = query(finance.STK_XR_XD.code, 
              finance.STK_XR_XD.a_registration_date, 
              finance.STK_XR_XD.bonus_amount_rmb
        ).filter(
              finance.STK_XR_XD.a_registration_date >= time0,   # 股权登记日在time0 和 time1之间
              finance.STK_XR_XD.a_registration_date <= time1,
              finance.STK_XR_XD.code.in_(stock_list[:min(list_len, interval)]))  # 截取不超过 interval 的列表并查询
              
    df = finance.run_query(q)
    
    
    # 对 interval 的部分分别查询并拼接
    if list_len > interval:
        
        # 将股票列表按照 interval 的标准分成多段
        df_num = list_len     // interval
        
        # 针对每段数据循环查询
        for i in range(df_num):
    
            q = query(finance.STK_XR_XD.code, 
                      finance.STK_XR_XD.a_registration_date, 
                      finance.STK_XR_XD.bonus_amount_rmb
            ).filter(
                finance.STK_XR_XD.a_registration_date >= time0,
                finance.STK_XR_XD.a_registration_date <= time1,
                finance.STK_XR_XD.code.in_(stock_list[interval*(i+1):min(list_len,interval*(i+2))]))
            
            # 查询完成后的数据都追加到 df 数据框末尾
            df = df.append(finance.run_query(q))
    
    # 将可能得到的 na 数据填充为0
    dividend = df.fillna(0)

    # 将股息数据根据股票代码做汇总和累加
    dividend = dividend.groupby('code').sum()
    temp_list = list(dividend.index)    # query查询不到无分红信息的股票，所以temp_list长度会小于stock_list
    
    # 获取市值相关数据
    q = query(valuation.code,valuation.market_cap).\
              filter(valuation.code.in_(temp_list))
              
    cap = get_fundamentals(q, date=time1)
    
    cap = cap.set_index('code')
    
    # 计算股息率
    DR = pd.concat([dividend, cap] ,axis=1)
    
    # 单独计算股息率生成新的一列
    DR['dividend_ratio'] = (DR['bonus_amount_rmb']/10000) / DR['market_cap']
    
    # 按照股息率降序排列
    # 股息率高的股票在前，低的在后
    DR.sort_values(by='dividend_ratio', ascending=sort, inplace=True)
    
    # 截取股息率在 p1 到 p2 之间的股票代码
    final_list = list(DR.index)[int(p1*len(DR)):int(p2*len(DR))]
    
    return final_list




# 计算 PEG 并排序筛选股票

# pe_ratio	市盈率(PE, TTM)	每股市价为每股收益的倍数，反映投资人对每元净利润所愿支付的价格，用来估计股票的投资报酬和风险
# 市盈率（PE，TTM）=（股票在指定交易日期的收盘价 * 截止当日公司总股本）/归属于母公司股东的净利润TTM

# inc_net_profit_year_on_year	净利润同比增长率(%)	
# （当期的净利润-上月（上年）当期的净利润）/上月（上年）当期的净利润绝对值=净利润同比增长率

# PEG 指标
# 百度百科：https://baike.baidu.com/item/PEG%E6%8C%87%E6%A0%87/10904043

# PEG指标(市盈率相对盈利增长比率)是用公司的市盈率除以公司的盈利增长速度
# PEG指标(市盈率相对盈利增长比率)是Jim Slater发明的一个股票估值指标，是在PE（市盈率）估值的基础上发展起来的
# 它弥补了PE对企业动态成长性估计的不足
# 当时他在选股的时候就是选那些市盈率较低，同时它们的增长速度又是比较高的公司
# 这些公司有一个典型特点就是PEG会非常低
def get_peg(context,stocks):

    # 通过 filter 子句限制了PEG的范围
    q = query(valuation.code,
                ).filter(
                    valuation.pe_ratio / indicator.inc_net_profit_year_on_year > -3,
                    valuation.pe_ratio / indicator.inc_net_profit_year_on_year < 3,
                    valuation.code.in_(stocks)
                    )
                    
    df_fundamentals = get_fundamentals(q)       
    
    stocks = list(df_fundamentals.code)
    
    # 对于筛选出来的股票按照 市值升序 排列
    df = get_fundamentals(query(valuation.code).\
                          filter(valuation.code.in_(stocks)).\
                          order_by(valuation.market_cap.asc()))
    
    return  list(df.code)





# 获取昨日涨停股票列表
def get_high_limit(context):
    
    # 清空昨日涨停列表
    g.high_limit_list = []
    
    # 获取当前持仓列表
    hold_list = list(context.portfolio.positions)
    
    # 读取所有持仓股票的昨日收盘价和涨停价数据
    # 从 panel 中截取数据框 - 注意，panel 数据在未来将不再被支持
    # 如果将来无法运行。可以修改这段代码
    # 比如使用 for 循环遍历持仓股票，分析涨停情况
    if hold_list:
        
        df = get_price(hold_list, end_date=context.previous_date, frequency='daily',
                       fields=['close', 'high_limit'],
                       count=1).iloc[:,0,:]
                       
        g.high_limit_list = list(df[df['close'] == df['high_limit']].index)



# 调整昨日涨停股票
def check_high_limit(context):
    
    # 获取持仓的昨日涨停列表
    current_data = get_current_data()
    
    if g.high_limit_list:
        
        for stock in g.high_limit_list:
            
            if current_data[stock].last_price < current_data[stock].high_limit:
                log.info("[%s]涨停打开，卖出" % stock)
                order_target(stock, 0)
            else:
                log.info("[%s]涨停，继续持有" % stock)




# 高效过滤股票函数
def filter_all_stocks(context, stock_list):
    
    curr_data = get_current_data()
    
    return [stock for stock in stock_list if not (
            stock.startswith(('68', '4', '8')) or      # 科创，北交所
            curr_data[stock].paused or
            curr_data[stock].is_st  or  # ST
            ('ST' in curr_data[stock].name) or
            ('*'  in curr_data[stock].name) or
            ('退' in curr_data[stock].name) or
            (curr_data[stock].last_price == curr_data[stock].high_limit)  or
            (curr_data[stock].last_price == curr_data[stock].low_limit)      
    )]



# 过滤价格较高的股票
def filter_highprice_stock(context,stock_list):

	df = history(1, unit='1m', field='close', security_list=stock_list)
	
	price_list = df.values[0].copy()
	
	price_list.sort()
	
	price = price_list[int(0.75*len(df.T))]
	
	return [stock for stock in stock_list if df[stock][-1] < price]
	
			
# end



