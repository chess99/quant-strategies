# 克隆自聚宽文章：https://www.joinquant.com/post/30806
# 标题：欧奈尔CANSLIM策略初探三
# 作者：韭菜饺子

# 导入函数库
from jqdata import *
import pandas as pd
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
import numpy as np

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')
    
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    
    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG') 
      # 开盘时或每分钟开始时运行
    run_daily(loss_ctrl, time='every_bar', reference_security='000300.XSHG')
    run_monthly(market_open, 1, 'open')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')
    g.max_value = None
    g.last_value = None
    
## 开盘前运行函数     
def before_market_open(context):
    pass

def loss_ctrl(context):
    if g.max_value is None:
        g.max_value = context.portfolio.total_value
    if g.last_value is None:
        g.last_value = context.portfolio.total_value
        
    k = context.portfolio.total_value/g.last_value-1
    if k<-0.09:
        for code in context.portfolio.positions:
            order_target(code, 0)
        log.info('市值极速下跌清仓')
        
    k = context.portfolio.total_value/g.max_value-1
    if k<-0.15:
        for code in context.portfolio.positions:
            order_target(code, 0)
        log.info('最大市值下跌清仓')
        g.max_value = context.portfolio.total_value
            
    if context.portfolio.total_value>g.max_value:
        g.max_value = context.portfolio.total_value
    g.last_value = context.portfolio.total_value

    
## 开盘时运行函数
def market_open(context):
    
    ## 先处理下跌减仓，腾出现金

    for code, pos in context.portfolio.positions.items():
        price_df = attribute_history(code, count=20)
        k = price_df.iloc[-1].close/price_df.iloc[0].close-1
        if k < 0:
        # k = pos.price/pos.avg_cost-1
        # if k<-0.1:
            order_target(code, 0)

    stocks = list(context.portfolio.positions.keys())
    if stocks:
        r = get_patterns(stocks, context.current_dt, unit='1M', n=3, N=10)
        stocks = r[r!=0].index.values.tolist()
        if stocks:
            cash = context.portfolio.available_cash/len(stocks)
            for code in stocks:
                order_value(code, cash)

    if len(context.portfolio.positions) > 0:
        return
    
    g.trade_time = None
    
    day = context.previous_date
    
    K = 1
    HS300 = get_price('000300.XSHG', count=250, end_date=day, panel=False)
    up = HS300.iloc[-1].close>HS300.close.mean()
    if not up:
        K = .5
    
    ## 
    
    # stocks = get_all_securities(types=['stock'], date=day).index.values.tolist()
    ## 排除市值位于全市场最小的 20%的股票；
    f_df = get_fundamentals(query(
            valuation,
        ), date=day).set_index('code').dropna()
    r = f_df.circulating_market_cap.rank()/f_df.shape[0]
    stocks = r[r>0.2].index.values.tolist()
    
    stocks = filter_st_paused_stock(stocks, day)
    stocks = filter_new_stock(stocks, day, 30)
    if not stocks:
        return
    
    ## 净利润增长
    # r = get_INPYY(stocks, day)
    
    ## 营业收入增长率位于前 1/3
    r = get_IRYY(stocks, day)
    r = r.rank(ascending=False)/len(r)
    stocks = r[r<.3].index.values.tolist()

    ## RPS 因子位于前 2/3
    r = get_rps1(stocks, day)
    r = r.rank(ascending=False)/len(r)
    stocks = r[r<0.6].index.values.tolist()

    ## 机构持股比例增长率位于前 1/3 
    r = get_share_ratio(stocks, day)
    r = r.rank(ascending=False)/len(r)
    stocks = r[r<.3].index.values.tolist()
    
    if not stocks:
        return
    
    ## 挑选满足“基底”形态的股票，
    r = get_patterns(stocks, context.current_dt, unit='1M', n=3, N=10)
    stocks = r[r!=0].index.values.tolist()
    
    if not stocks:
        return
    
    cash = context.portfolio.available_cash*K/len(stocks)
    for code in stocks:
        order_value(code, cash)
        
    g.trade_time = context.current_dt
 
## 收盘后运行函数  
def after_market_close(context):
    pass


# 过滤停牌股票
def filter_st_paused_stock(stock_list, date):
    p_df = get_price(stock_list, count=1, end_date=date, fields=['paused'], panel=False)
    p_df = p_df.set_index('code')
    return [stock for stock in stock_list if not p_df.loc[stock].paused
        and 'ST' not in get_security_info(stock).display_name
        and '*' not in get_security_info(stock).display_name
        and '退' not in get_security_info(stock).display_name]
    
def filter_new_stock(stocks, day, N=90):
    if isinstance(day, datetime):
        day = day.date()
    return [stock for stock in stocks if (day-get_security_info(stock, day).start_date).days>N]

def get_patterns_num(df, n=6):
    
    B = -1
    C1 = df.close.values[B]>df.open.values[B]
    B_close = df.close.values[B]
    N = df.shape[0]
    
    oc_maxs = df[['open', 'close']].max(axis='columns')
    
    for num in range(n, N+1):
        A = N-num
        MAXA = oc_maxs[A]
        C2 = MAXA<B_close
        C3 = np.max(oc_maxs[A+1:B])<MAXA
        C = C1 & C2 & C3
        if C:
            return num

def get_patterns(stocks, date, unit='1M', n=3, N=10):
    num_l = []    
    p_df = get_bars(stocks, count=N, end_dt=date, unit=unit, 
                         fields=['open', 'close'], df=True)
    for code in stocks:#p_df.index.levels[0].values:
        if code in p_df.index:
            df = p_df.loc[code]
            num = get_patterns_num(df, n=n)
        else:
            num = 0
        num_l.append(num if num else 0)
    return pd.Series(num_l, index=stocks)
    
def get_rps1(stocks, date):
    p_df = get_price(stocks, count=250, end_date=date, panel=False)
    r = p_df.groupby('code').apply(lambda x:x.iloc[-1].close/x.iloc[0].close-1)
    return r
    
def get_rps2(stocks, date):
    p_df = get_price(stocks, count=250, end_date=date, panel=False)
    r = p_df.groupby('code').apply(lambda x:(x.iloc[-1].close-x.close.min())*100/(x.close.max()-x.close.min()))
    return r    

## 净利润增长
def get_INPYY(stocks, day):
    f_df = get_fundamentals(query(
            indicator,
        ).filter(
            indicator.code.in_(stocks),
        ), date=day).dropna().set_index('code')
    return f_df.inc_net_profit_year_on_year
    
## 营业收入增长率
def get_IRYY(stocks, day):
    f_df = get_fundamentals(query(
            indicator,
        ).filter(
            indicator.code.in_(stocks),
        ), date=day).dropna().set_index('code')
    return f_df.inc_revenue_year_on_year

def get_nearest_quqter(year, month):
    return {
        1:(year-1,9),
        2:(year-1,9),
        3:(year-1,9),
        
        4:(year,1),
        5:(year,1),
        6:(year,1),

        7:(year,4),
        8:(year,4),
        9:(year,4),

        10:(year,7),
        11:(year,7),
        12:(year,7),
    }[month]

    
def get_share_ratio(stocks, day):
    year = day.year
    month = day.month
    
    y1,m1 = get_nearest_quqter(year, month)
    y2,m2 = get_nearest_quqter(y1, m1)
    
    sr_l = []
    for code in stocks:
        df1 = finance.run_query(query(
            finance.STK_SHAREHOLDER_FLOATING_TOP10
        ).filter(
            finance.STK_SHAREHOLDER_FLOATING_TOP10.code==code,
            finance.STK_SHAREHOLDER_FLOATING_TOP10.pub_date>f'{y1}-{m1}-1',
            finance.STK_SHAREHOLDER_FLOATING_TOP10.pub_date<f'{y1}-{m1+3}-1',
        ))        

        df2 = finance.run_query(query(
            finance.STK_SHAREHOLDER_FLOATING_TOP10
        ).filter(
            finance.STK_SHAREHOLDER_FLOATING_TOP10.code==code,
            finance.STK_SHAREHOLDER_FLOATING_TOP10.pub_date>f'{y2}-{m2}-1',
            finance.STK_SHAREHOLDER_FLOATING_TOP10.pub_date<f'{y2}-{m2+3}-1',
        ))
        
        if not df1.empty and not df2.empty:
            sr1 = df1.share_ratio.sum()
            sr2 = df2.share_ratio.sum()
            sr = sr1/sr2-1
        else:
            sr = 0
        
        sr_l.append(sr)
    return pd.Series(sr_l, index=stocks)

