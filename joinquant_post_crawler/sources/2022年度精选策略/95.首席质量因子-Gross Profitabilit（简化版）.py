# 克隆自聚宽文章：https://www.joinquant.com/post/37683
# 标题：首席质量因子-Gross Profitabilit（简化版）
# 作者：养鸡小白

# 导入函数库
from jqdata import *
import datetime as dt
# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    set_option('avoid_future_data',True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
 
    run_daily(market_open, time='open', reference_security='000300.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')
    
    
def stock_filter(context,stock_list):
    date = context.current_dt
    curr_data = get_current_data()
    return [stock_list for stock in stock_list if not (
            (curr_data[stock].day_open == curr_data[stock].high_limit) or   # 涨停开盘
            (curr_data[stock].day_open == curr_data[stock].low_limit) or    # 跌停开盘
            curr_data[stock].paused or  # 停牌
            curr_data[stock].is_st or   # ST
            ('ST' in curr_data[stock].name) or
            ('*' in curr_data[stock].name) or
            ('退' in curr_data[stock].name) or
            #(stock.startswith('300')) or    # 创业
            (stock.startswith('688'))   # 科创
    )]

def fun_get_stock_list(context, hold_number, statsDate, security):
        df = get_fundamentals(
            query(valuation.code, valuation.market_cap, valuation.pe_ratio, valuation.ps_ratio, valuation.pb_ratio).filter(
                valuation.code.in_ (security))
        )

        # 1) 总市值全市场从大到小前80%
        fCap = df.sort_values(['market_cap'], ascending=False)
        fCap = fCap.reset_index(drop = True)
        fCap = fCap[0:int(len(fCap)*0.8)]
        sListCap = list(fCap['code'])

        # 2）市盈率全市场从小到大前40%（剔除市盈率为负的股票）
        fPE = df.sort_values(['pe_ratio'], ascending=True)
        fPE = fPE.reset_index(drop = True)
        fPE = fPE[fPE.pe_ratio > 0]
        fPE = fPE.reset_index(drop = True)
        fPE = fPE[0:int(len(fPE)*0.4)]
        sListPE = list(fPE['code'])

        # 3）pb全市场从小到大前40%（剔除pb为负的股票）
        fPB = df.sort_values(['pb_ratio'], ascending=True)
        fPB = fPB.reset_index(drop = True)
        fPB = fPB[fPB.pb_ratio > 0]
        fPB = fPB.reset_index(drop = True)
        fPB = fPB[0:int(len(fPB)*0.4)]
        sListPB = list(fPB['code'])

        # 4）市收率小于2.5
        fPS = df[df.ps_ratio < 2.5]
        sListPS = list(fPS['code'])

        # 5）同时满足上述3条的股票，按照股息率从大到小排序，选出股息率最高的 n 只股票
        good_stocks = list(set(sListCap) & set(sListPE) & set(sListPS) & set(sListPB))
        #print len(good_stocks)
        GP_ratio = {}

        df = get_fundamentals(
            query(income.code, income.total_operating_revenue, income.total_operating_cost, balance.total_assets),
            date = statsDate - dt.timedelta(1)
        )

        df = df.fillna(value = 0)
        df = df[df.total_operating_revenue > 0]
        df = df.reset_index(drop = True)
        df = df[df.total_assets > 0]
        df = df.reset_index(drop = True)
        df = df[df.code.isin(good_stocks)]
        df = df.reset_index(drop = True)
        df['GP'] = 1.0*(df['total_operating_revenue'] - df['total_operating_cost']) / df['total_assets']

        df = df.drop(['total_assets', 'total_operating_revenue', 'total_operating_cost'], axis=1)
        df = df.sort_values(['GP'], ascending=False)
        #print df.head(10)
        stock_list = list(df['code'])

        positions_list = context.portfolio.positions.keys()
        #stock_list = unpaused(stock_list, positions_list)
        #stock_list = remove_st(stock_list, statsDate)
        stock_list = stock_filter(context,stock_list)[0]
        stock_list = stock_list[:hold_number]
        return stock_list

def sell(context,stock_list):
    if len(context.portfolio.positions)>0:
        for stock in context.portfolio.positions.keys():
            if stock not in stock_list:
                order_target_value(stock,0)

def buy(context,stock_list,hold_number):
    if len(context.portfolio.positions)<hold_number:
        n = hold_number-len(context.portfolio.positions)
        cash = context.portfolio.available_cash/n
        for stock in stock_list:
            if stock not in context.portfolio.positions.keys():
                order_target_value(stock,cash)
            if len(context.portfolio.positions)>=hold_number:
                break
    
## 开盘时运行函数
def market_open(context):
    security = get_all_securities(types=['stock'], date=context.current_dt).index.tolist()
    #security = get_index_stocks('000300.XSHG',context.current_dt)
    hold_number = 10
    statsDate = context.current_dt.date()
    stock_list = fun_get_stock_list(context,hold_number,statsDate,security)
    sell(context,stock_list)
    buy(context,stock_list,hold_number)
    
## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    log.info('一天结束')
    log.info('##############################################################')
