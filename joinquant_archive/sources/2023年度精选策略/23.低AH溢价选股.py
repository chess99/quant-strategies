# 克隆自聚宽文章：https://www.joinquant.com/post/31236
# 标题：低AH溢价选股
# 作者：子鹿

from jqdata import finance

def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # True为开启动态复权模式，使用真实价格交易
    set_option('use_real_price', True) 
    # 设定成交量比例
    set_option('order_volume_ratio', 1)
    # 股票类交易手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, \
                             open_commission=0.00015, close_commission=0.00015,\
                             close_today_commission=0, min_commission=0), type='stock')
    # 持仓数量
    g.stocknum = 5
    # 运行函数
    run_weekly(trade, 1, time='9:30')

#交易
def trade(context):
    # 设定查询条件 把ah股票列出
    df = finance.run_query(query(finance.STK_AH_PRICE_COMP.a_code, finance.STK_AH_PRICE_COMP.h_a_comp)\
    .filter(finance.STK_AH_PRICE_COMP.day==context.previous_date).\
                order_by(finance.STK_AH_PRICE_COMP.h_a_comp))
    buy_list =list(df['a_code'])
    #log.info("df:\n%s", df)
    
    # 过滤停牌/ST股票
    buy_list = filter_paused_stock(buy_list)
    buy_list = filter_st_stock(buy_list)
    buy_list = delisted_filter(buy_list)
    buy_list = buy_list[:g.stocknum]
    
    #卖出股票
    for stk in context.portfolio.positions.keys():
        if stk not in buy_list:
            order_target_value(stk, 0)
            log.info("sell %s \\r\\n\\", stk)

    #买入股票
    for stk in buy_list:
        if stk not in context.portfolio.positions.keys():
            current_price = get_bars(stk, 1, '1m', ['close'], include_now=True, end_dt=context.current_dt,df=True).iloc[-1]['close'] 
            total_cash = context.portfolio.available_cash
            if total_cash < current_price*100:
                continue    #不够买100股，不处理  
            cw = 1.0/g.stocknum
            target_val = context.portfolio.total_value*cw
            
            #新买入股票        
            order_cash = min(total_cash, target_val)
            ret = order_value(stk, order_cash)
            if ret:
                log.info("buy [%s], val:%s, cw:%s\\r\\n\\",stk, order_cash, cw)    #新买入
            else:
                log.info("Failed to buy stk[%s] value(%s) to weight:%s\\r\\n\\",stk, order_cash, cw)    #新买入失败    

#过滤停牌/ST股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].is_st]#过滤st
def delisted_filter(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not '退' in current_data[stock].name]#过滤st                
