# 克隆自聚宽文章：https://www.joinquant.com/post/31510
# 标题：勾股神器2: 代码40行，年化一百点。
# 作者：edjoin

from jqdata import *  # 导入函数库
import talib,numpy

# 初始化函数，设定基准等等
def initialize(context):  
    context.bx_cash = {}  #北向资金占比字典
    context.BENCH = '000300.XSHG'  # 设定沪深300作为基准
    set_benchmark(context.BENCH)
    context.pool = get_index_stocks(context.BENCH)
    set_option('use_real_price', True)  # 开启动态复权模式(真实价格)
    log.set_level('system', 'error')  # 输出内容到日志 log.info()
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, 
        close_commission=0.0003, min_commission=5), type='stock')
    run_daily(bx_strategy, time='open')
    
def bx_cashflow(context,threshold=0):
    table = finance.STK_HK_HOLD_INFO
    q = query(table.day, table.code, table.share_ratio).filter(
            table.link_id.in_(['310001', '310002']),
            table.day.in_([context.previous_date]))
    df = finance.run_query(q)
    df_top = df[df['share_ratio']>threshold]  #北向资金占比大于threshold%
    return df_top.set_index('code')['share_ratio'].to_dict()

def bx_strategy(context,trade_limit=0.3,ratio=3):
    bx_dict = bx_cashflow(context,ratio)
    holds = list(context.portfolio.positions)
    for security in bx_dict:
        if (security in context.bx_cash) and (security in context.pool):
            change = bx_dict[security]-context.bx_cash[security]
            if abs(change)<trade_limit: continue
            if change<-trade_limit and (security in holds): #order_target(security,0)
                order_target(security,0)
            if change>trade_limit and (security not in holds): 
                a = get_bars(security,unit='1d',count=100,fields=['close'])['close']
                rsi = talib.RSI(numpy.array(a))[-1]
                if len(holds)>=10 or rsi<40 or rsi>80: continue
                order_value(security,context.portfolio.total_value*0.2)
    context.bx_cash = bx_dict 
