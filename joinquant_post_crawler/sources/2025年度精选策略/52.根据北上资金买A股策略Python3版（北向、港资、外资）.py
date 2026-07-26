# 克隆自聚宽文章：https://www.joinquant.com/post/27792
# 标题：根据北上资金买A股策略Python3版（北向/港资/外资）
# 作者：逆熵者

# 克隆自聚宽文章：https://www.joinquant.com/post/24681
# 标题：根据北上资金买股票的最佳持股时间探讨
# 作者：见路不走2019

import talib
from prettytable import PrettyTable 
import pandas 
import datetime
import time
from jqdata import *


def initialize(context):
    # 设定基准为沪深300
    set_benchmark('000300.XSHG')
    # True为开启动态复权模式，使用真实价格交易
    set_option('use_real_price', True)
    # 设定避免未来函数模式
    set_option("avoid_future_data", True)
    # 股票类交易手续费和滑点
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    set_slippage(FixedSlippage(0.02))
    # 设置日志级别
    log.set_level('order', 'error')
    # 初始化变量
    g.buy_stock_count = 4
    g.days = 0
    g.refresh_rate = 60
    g.nday=2
    # 每天运行
    run_daily(daily,'open')

def daily(context):
    if g.days % g.refresh_rate == 0:
        buy_stocks = select_stocks(context)
        log.info('前%d个交易日港资（北向资金）净买额最高的股票：\n'%g.nday)
        for stock in buy_stocks:
            log.info(show_stock(stock))
        adjust_position(context, buy_stocks)
        log.info(get_portfolio_info_text(context,buy_stocks))
    g.days+=1
        
def select_stocks(context):
    date = context.previous_date
    startdate=date-datetime.timedelta(g.nday)
    trade_days=get_trade_days(startdate,date)
    total_df=pd.DataFrame()
    for day in trade_days:
        q = query(finance.STK_EL_TOP_ACTIVATE).filter(finance.STK_EL_TOP_ACTIVATE.day == day)
        df = finance.run_query(q)
        df['net'] = df.buy - df.sell
        df = df.sort_values(by = ['net'] , axis = 0, ascending = False)
        df = df[(df.link_id != 310003 ) & (df.link_id != 310004 )]
        total_df=pd.concat((total_df,df))
    stock_net=total_df.groupby(total_df['code'])['net'].sum()
    stock_net=pd.DataFrame(stock_net)
    stock_list=list(stock_net.index)
    df_cap=get_fundamentals(query(valuation.code, valuation.circulating_market_cap).filter(valuation.code.in_(stock_list)),date=date)
    df_cap.index=df_cap.code
    #log.info('df_cap',df_cap)
    df_cap=pd.concat((df_cap,stock_net),axis=1)
    df_cap['rate']=(df_cap['net']/100000000/df_cap['circulating_market_cap'])
    df_cap=df_cap.sort_values('rate',ascending=False)
    stock_list = list(df_cap['code'])
    # 过滤掉停牌的和ST的
    stock_list = filter_paused_and_st_stock(stock_list)
    #选取前N只股票放入“目标股票池”
    stock_list = stock_list[:g.buy_stock_count]  
    return stock_list
        
def filter_paused_and_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused 
    and not current_data[stock].is_st and 'ST' not in current_data[stock].
    name and '*' not in current_data[stock].name and '退' not in current_data[stock].name]
    
def adjust_position(context, buy_stocks):
    # 现持仓的股票，如果不在“目标池”中，且未涨停，就卖出
    if len(context.portfolio.positions)>0:
        last_prices = history(1, '1m', 'close', security_list=list(context.portfolio.positions.keys()))
        for stock in list(context.portfolio.positions.keys()):
            if stock not in buy_stocks :
                curr_data = get_current_data()
                if last_prices[stock][-1] < curr_data[stock].high_limit:
                    order_target_value(stock, 0)
    # 依次买入“目标池”中的股票            
    for stock in buy_stocks:
        position_count = len(context.portfolio.positions)
        if g.buy_stock_count > position_count:
            value = context.portfolio.cash / (g.buy_stock_count - position_count)
            if context.portfolio.positions[stock].total_amount == 0:
                order_target_value(stock, value)
                
def shifttradingday(date,shift):
    #获取N天前的交易日日期
    # 获取所有的交易日，返回一个包含所有交易日的 list,元素值为 datetime.date 类型.
    tradingday = get_all_trade_days()
    # 得到date之后shift天那一天在列表中的行标号 返回一个数
    shiftday_index = list(tradingday).index(date)+shift
    # 根据行号返回该日日期 为datetime.date类型
    return tradingday[shiftday_index]

def show_stock(stock):
    '''
    获取股票代码的显示信息    
    :param stock: 股票代码，例如: '603822.SH'
    :return: str，例如：'603822 嘉澳环保'
    '''
    return "%s %s" % (stock[:6], get_security_info(stock).display_name)
    
def get_portfolio_info_text(context,new_stocks,op_sfs=[0]):
    # new_stocks是需要持仓的股票列表
    sub_str = ''
    table = PrettyTable(["仓号","股票", "持仓", "当前价", "盈亏率","持仓比"])  
    for sf_id in range(len(context.subportfolios)):
        cash = context.subportfolios[sf_id].cash
        p_value = context.subportfolios[sf_id].positions_value
        total_values = p_value +cash
        if sf_id in op_sfs:
            sf_id_str = str(sf_id) + ' *'
        else:
            sf_id_str = str(sf_id)
        for stock in list(context.subportfolios[sf_id].long_positions.keys()):
            position = context.subportfolios[sf_id].long_positions[stock]
            if sf_id in op_sfs and stock in new_stocks:
                stock_str = show_stock(stock) + ' *'
            else:
                stock_str = show_stock(stock)
            stock_raite = (position.total_amount * position.price) / total_values * 100
            table.add_row([sf_id_str,
                stock_str,
                position.total_amount,
                position.price,
                "%.2f%%"%((position.price - position.avg_cost) / position.avg_cost * 100), 
                "%.2f%%"%(stock_raite)]
                )
        if sf_id < len(context.subportfolios) - 1:
            table.add_row(['----','---------------','-----','----','-----','-----'])
        sub_str += '[仓号: %d] [总值:%d] [持股数:%d] [仓位:%.2f%%] \n'%(sf_id, total_values,
            len(context.subportfolios[sf_id].long_positions), p_value*100/(cash+p_value))
    log.info('持仓详情:\n' + sub_str + str(table))
