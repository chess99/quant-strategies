# 克隆自聚宽文章：https://www.joinquant.com/post/33618
# 标题：最简强者恒强策略
# 作者：囚徒

# 导入函数库
from jqdata import *
import pandas as pd

# 初始化函数，设定基准等等
def initialize(context):
    # 设定基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option("use_real_price", True)
    
    log.set_level('order', 'error')
    #log.set_level('strategy','error')
    
        # 开盘时运行
    run_monthly(market_open,monthday = 1, time='open', reference_security='000300.XSHG')
    
    run_monthly(select_stocks,monthday=1,time='9:00')

def select4hy(hycode):
    hys = get_industry_stocks(hycode)
    hys = [ s for s in hys if s in g.allstocks ]
    q = query(valuation.code,valuation.market_cap,valuation.circulating_market_cap,valuation.turnover_ratio)
    #df = get_fundamentals( q.filter(valuation.code.in_(hys)) )
    dfp = get_fundamentals_continuously(q.filter(valuation.code.in_(hys)), end_date=None,count=1, panel=False)
    
    df = dfp.groupby(by='code')['market_cap'].agg('mean')
    df = df.to_frame()
    df.columns = ['market_cap']
    df = df.sort_values(by='market_cap',ascending=False).head(10)
    return df.index.values.tolist()
    
def select_stocks(context):
    df = get_all_securities(['stock'])
    df = df[df.start_date < context.previous_date - datetime.timedelta(60)]
    g.allstocks = df.index.values.tolist()
    stocks = []
    hys =  ['801124','801120' ,'801156' ,'801150'	,'801194']
    g.cnt = len(hys)
    for hy in hys:
        codes = select4hy(hy)
        #print(codes)
        cnt = 0
        for code in codes:
            if code not in stocks:
                stocks.append(code)
                cnt += 1
                if cnt == 1:
                    break;
        #print(stocks)
    g.stocks = stocks[:]
    print(stocks)
    return stocks
        
def market_open(context):
    for s in context.portfolio.positions:
        if s not in g.stocks:
            order_target(s, 0)
    
    cnt = g.cnt
    for s in context.portfolio.positions:
        if context.portfolio.positions[s].total_amount > 50:
            cnt-=1
            
    if cnt == 0:
        return
    
    position = context.portfolio.available_cash / cnt
    for s in g.stocks:
        if s not in context.portfolio.positions :
            order_value(s, position)
            

    
