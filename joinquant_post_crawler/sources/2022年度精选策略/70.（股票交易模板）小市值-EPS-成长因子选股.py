# 克隆自聚宽文章：https://www.joinquant.com/post/36426
# 标题：（股票交易模板）小市值-EPS-成长因子选股
# 作者：大蠢驴小疯子

# 导入函数库
from jqdata import *
from jqfactor import get_factor_values
'''
    自建股票交易模板
    模板结构:
        1.initialize                初始化函数
        2.before_market_open        开盘前运行函数
        3.market_open               开盘时运行函数
        4.after_market_close        收盘后运行函数
        5.filter_stock              剔除无效股票函数
        6.get_stock_list            选股策略实现函数
    策略逻辑：
        1.小市值策略为基础
        2.每周运行一次
        3.尝试不同因子选股策略(本次选择成长因子)
        4.增加择时策略（暂时没有）
'''

'''初始化函数，设定基准等等'''
def initialize(context):
    '''交易系统设置'''
    # 设定沪深300作为基准
    # set_benchmark('000300.XSHG')
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)    
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')

    '''股票相关设定'''
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),type='fund')

    '''自有超参设置'''
    # 持仓数量
    g.stock_num = 5

    ''' 运行相关函数'''
    # 开盘前运行
    run_weekly(before_market_open, weekday=1, time='9:00', reference_security='000300.XSHG')
    # 开盘时运行
    run_weekly(market_open, weekday=1, time='9:30', reference_security='000300.XSHG')
    # 收盘后运行
    run_weekly(after_market_close, weekday=1, time='15:00', reference_security='000300.XSHG')

'''开盘前运行函数'''
def before_market_open(context):
    # 输出运行时间
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))

    # 给微信发送消息（添加模拟交易，并绑定微信生效）
    # send_message('美好的一天~')

    # 构建自选股
    stock_list = get_stock_list(context)
    stock_list = stock_list[:g.stock_num]
    g.security = stock_list
    print('今日自选股:{}'.format(stock_list))

'''开盘时运行函数'''
def market_open(context):
    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    buy_stocks = [stock for stock in g.security]
    '''判断当前持仓是否包含自选股中的股票'''
    for stock in context.portfolio.positions:
        if stock not in g.security:
            log.info("[%s]不在应买入列表中，清仓处理！" % (stock))
            position = context.portfolio.positions[stock]
            security = position.security
            order = order_target_value(security, 0)  # 可能会因停牌失败
        else:
            log.info("[%s]已经持有无需重复买入" % (stock))
            buy_stocks.remove(stock)
    print('-----------------------------------------------------------')
    print('剩余待买入自选股：',buy_stocks)
    print('-----------------------------------------------------------')
    # 根据股票数量分仓
    # 此处只根据可用金额平均分配购买，不能保证每个仓位平均分配
    buy_stocks_num = len(buy_stocks)
    if buy_stocks_num > 0:
        value = context.portfolio.cash / buy_stocks_num
        for stock in buy_stocks:
            order_target_value(stock, value)

'''收盘后运行函数'''
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
        
    #打印账户信息
    for position in list(context.portfolio.positions.values()):
        securities=position.security
        cost=position.avg_cost
        price=position.price
        ret=100*(price/cost-1)
        value=position.value
        amount=position.total_amount    
        print('代码:{}'.format(securities))
        print('成本价:{}'.format(format(cost,'.2f')))
        print('现价:{}'.format(price))
        print('收益率:{}%'.format(format(ret,'.2f')))
        print('持仓(股):{}'.format(amount))
        print('市值:{}'.format(format(value,'.2f')))
        print('—————————————————一天结——————————————————')
    print('######################################分割线######################################')

'''剔除无效股票函数'''
def filter_stock(context,stock_list):
    '''
        参数说明：
            1.stock_list        待处理股票列表
            2.del_paused        剔除停牌股
            3.del_st            剔除ST股
            4.del_delist        剔除退市股
            5.del_hl            剔除涨停股
            6.del_dl            剔除跌停股
            7.del_kcb           剔除科创板股
    '''
    current_data = get_current_data()
    yesterday = context.previous_date
    # 剔除上市不满250天的股票
    stock_list = [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=250)]
    # 剔除科创板
    stock_list = [stock for stock in stock_list  if stock[0:3] != '688']
    # 剔除ST
    stock_list = [stock for stock in stock_list if not current_data[stock].is_st]
    stock_list = [stock for stock in stock_list if not 'ST' in current_data[stock].name]
    stock_list = [stock for stock in stock_list if not '*' in current_data[stock].name]
    stock_list = [stock for stock in stock_list if not '退' in current_data[stock].name]
    # 剔除停牌
    stock_list = [stock for stock in stock_list if not current_data[stock].paused]
    # 剔除退市
    # 剔除涨停
    stock_list = [stock for stock in stock_list if not current_data[stock].day_open >= current_data[stock].high_limit]
    # 剔除跌停
    stock_list = [stock for stock in stock_list if not current_data[stock].day_open <= current_data[stock].low_limit]
    return stock_list
    
'''选股策略实现函数'''
def get_stock_list(context):
    '''
    选股策略：
        1.按流通市值挑选小市值股票
        2.每股收益EPS>0
        3.growth成长因子选股
    '''
    
    '''1.聚宽sales_growth成长因子选股'''
    yesterday = context.previous_date
    initial_list = get_all_securities().index.tolist()
    initial_list = filter_stock(context, initial_list)
    jqfactor = 'growth'
    score_list = get_factor_values(initial_list, jqfactor, end_date=yesterday, count=1)[jqfactor].iloc[0].tolist()
    df = pd.DataFrame(columns=['code','score'])
    df['code'] = initial_list
    df['score'] = score_list
    df = df.dropna()
    df.sort_values(by='score', ascending=False, inplace=True)
    x_list = list(df.code)[0:int(0.1*len(initial_list))]
    
    '''2.每股收益EPS和流通市值选股'''
    q = query(valuation.code,valuation.circulating_market_cap,indicator.eps
            ).filter(valuation.code.in_(x_list),indicator.eps>0
            ).order_by(valuation.circulating_market_cap.asc()
            )
    df = get_fundamentals(q)
    final_list = list(df.code)
    return final_list
