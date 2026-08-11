# 克隆自聚宽文章：https://www.joinquant.com/post/33065
# 标题：分享一个最近两年非常有效的因子
# 作者：美吉姆优秀毕业代表

# 克隆自聚宽文章：https://www.joinquant.com/post/7286
# 标题：【重磅更新】因子之 WorldQuant Alpha 101 因子 
# 作者：JoinQuant-PM

# 导入聚宽函数库
import jqdata
# 导入 Alpha_101 因子库
from jqlib.alpha101 import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    
    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 每月第一个交易日，开盘前运行
    run_monthly(before_market_open, 1, time='before_open')
      # 每月第一个交易日，开盘时运行
    run_monthly(market_open, 1, time='open')

## 开盘前运行函数     
def before_market_open(context):
    # 输出运行时间
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    current_security = context.portfolio.positions.keys()
    # 获取前一个交易日的日期
    current_date =  context.previous_date
    # 获取沪深300股票成分股的alpha_024因子值，剔除NaN值后按照因子值做降序排列
    alpha_stocks = alpha_022(current_date,'000300.XSHG').dropna().order(ascending=False)
    #399101.XSHE_1点31  000300_2.76 000905_1.85 000985_1.24 
    
    # 输出因子值最高的前5只股票代码及其因子值
    log.info('\n',alpha_stocks.head(5))
    # 获取降序排序后的股票列表
    alpha_head = list(alpha_stocks.index)
    # 过滤停牌股票，并获取因子值最高的前5只股票代码
    alpha_head = paused_filter(alpha_head)[:5]
    # 得到买入股票列表
    g.stocks_to_buy = list(set(alpha_head)-set(current_security))
    # 得到卖出股票列表
    g.stocks_to_sell = list(set(current_security)-set(alpha_head))

## 开盘时运行函数
def market_open(context):
    # 卖出股票
    for stock in g.stocks_to_sell:
        order_target(stock,0)
        log.info("卖出 %s" % (stock))
    # 按照买入股票列表的股票数量平分买入资金
    try:
        g.cash = context.portfolio.available_cash/len(g.stocks_to_buy)
    except:
        g.cash = 0
    # 买入股票
    for stock in g.stocks_to_buy:
        order_value(stock, g.cash)
        log.info("买入 %s" % (stock))

## 过滤停牌股票,更多函数详见共享函数库：https://www.joinquant.com/algorithm/apishare/list
def paused_filter(security_list):
    current_data = get_current_data()
    security_list = [stock for stock in security_list if not current_data[stock].paused]
    # 返回结果
    return security_list
