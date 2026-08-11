# 克隆自聚宽文章：https://www.joinquant.com/post/30457
# 标题：追涨大师（超额142）
# 作者：张仨06

'''
   该策略意思为抓第一次涨停、近段时间有上升趋势且近30日未涨过百分之13个点的股票，满仓持有，择盈、择时卖出。
'''
# 导入函数库
from jqdata import *
import math
## 初始化函数，设定要操作的股票、基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # True为开启动态复权模式，使用真实价格交易
    set_option('use_real_price', True) 
    # 设定成交量比例
    set_option('order_volume_ratio', 1)
    # 股票类交易手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, \
                             open_commission=0.0003, close_commission=0.0003,\
                             close_today_commission=0, min_commission=5), type='stock')
    # 持仓数量
    g.stocknum = 1
    # 购买时的价格
    g.buy_price = 0
    # 记录持股时间
    g.day ={}
  
    # run_daily(check_stocks, time='7:00', reference_security='000300.XSHG')
    run_daily(trade, time='9:50', reference_security='000300.XSHG')
# 来自于作者叶松的代码，主要用于拟合线性回归
def fit_linear(context,count,security1):
    '''
    count:拟合天数
    '''
    from sklearn.linear_model import LinearRegression
    security = security1
    df = history(count=count, unit='1d', field='close', security_list=security, df=True, skip_paused=False, fq='pre')
   
    df.drop(index=[context.previous_date])
    model = LinearRegression()
    x_train = np.arange(0,len(df[security])).reshape(-1,1)
    y_train = df[security].values.reshape(-1,1)
    
    
    model.fit(x_train,y_train)
    
    # # 计算出拟合的最小二乘法方程
    # # y = mx + c 
    c = model.intercept_
    m = model.coef_
    c1 = round(float(c),2)
    m1 = round(float(m),2)
    # print("最小二乘法方程 : y = {} + {}x".format(c1,m1))
    return m1    
# 筛选出主板良性股
def filter_paused_stock(context,stock_list):
    curr_data = get_current_data()
    stock_list = [stock for stock in stock_list if not curr_data[stock].is_st]
    stock_list = [stock for stock in stock_list if not curr_data[stock].paused] 
    stock_list = [stock for stock in stock_list if '退' not in curr_data[stock].name]
    stock_list = [stock for stock in stock_list if  (context.current_dt.date()-get_security_info(stock).start_date).days>360]
    stock_list=[stock for stock in stock_list if stock[0:2] != '68'] 
    stock_list=[stock for stock in stock_list if stock[0:3] != '300']
    return stock_list
# 选出有近段时间有上升趋势且近30日未涨过百分之13个点的股票
def check_stocks(context):
    Stock_slope = {}
    list0 = []
    # 获取股票
    stocks = list(get_all_securities(['stock'],context.previous_date).index)
    stocks1 = filter_paused_stock(context,stocks)
    # 选出第一次涨停的股票
    df11 = get_money_flow(stocks1 ,None, (context.previous_date + datetime.timedelta(days=-1)).strftime("%Y-%m-%d"), ["sec_code",'change_pct'], 1)
    df22 = df11[df11['change_pct']<9].copy()
    buylist111 = list(df22['sec_code'])
    df55 = get_money_flow(buylist111 ,None, context.previous_date, ["sec_code",'change_pct'], 1)
    df66 = df55[df55['change_pct']>9.7].copy()
    buylist222 = list(df66['sec_code'])
    df77 = get_money_flow(buylist222 ,None, context.previous_date, ["sec_code","net_pct_main"], 1)
    # 选出主力占比为正的股票
    df88 = df77[df77['net_pct_main']>0].copy()
    buylist = list(df88['sec_code'])
    # 选出近段时间有上升趋势且近30日未涨过百分之13个点的股票
    for Stock111 in buylist:
        try:
            df33 = get_money_flow(Stock111 ,None, context.previous_date , ["sec_code",'change_pct'], 30)
            rate_2 = df33['change_pct'][:2].sum()
            rate_3 = df33['change_pct'][:3].sum()
            rate_4 = df33['change_pct'][:4].sum()
            rate_5 = df33['change_pct'][:5].sum()
            rate_10 = df33['change_pct'][:15].sum()
            rate_20 = df33['change_pct'][:20].sum()
            rate_30 = df33['change_pct'][:30].sum()
            if rate_2>13:
                continue
            if rate_3>13:
                continue
            if rate_4>13:
                continue
            if rate_5>13:
                continue
            if rate_10>13:
                continue
            if rate_20>13:
                continue
            if rate_30>13:
                continue
            slope360 = fit_linear(context,360,Stock111)
            slope120 = fit_linear(context,121,Stock111)
            slope90 = fit_linear(context,91,Stock111)
            slope60 = fit_linear(context,61,Stock111)
            slope45 = fit_linear(context,46,Stock111)
            slope30 = fit_linear(context,31,Stock111)
            if slope30<0:
                continue
            if slope45<0:
                continue
            if slope60<0:
                continue
            if slope90<0:
                continue
            if slope360<0:
                continue
            # 将120日的拟合斜率与股票配对储存起来
            Stock_slope[Stock111] = slope120
        except:
            pass
    mix_slope = 0
    mix_code1= ''
    # 将120日拟合斜率最大的股票选出
    for Stock111 in Stock_slope:
        if Stock_slope[Stock111]>=mix_slope:
            mix_slope = Stock_slope[Stock111]
            mix_code1 = Stock111
    if mix_code1 != '':        
        list0.append(mix_code1)
    log.info(Stock_slope)
    return list0
# 开盘时的交易函数
def trade(context):
    # 获取购买列表
    stock_list = check_stocks(context)
    # 获取持仓列表
    sell_list = list(context.portfolio.positions.keys())
    count = len(sell_list)
    # 准备卖出
    if count > 0 :
        for stock in sell_list:
            g.day[stock] +=1
            stock_name = str(stock)
            open_price = get_current_data()[stock_name].day_open
            now_price = get_current_data()[stock_name].last_price
            # 如果从购买到现在涨了5%，卖出
            if now_price > 1.05*g.buy_price:
                order_target_value(stock,0)
                continue
            # 如果股票持有19日，卖出
            if g.day[stock] == 19:
                order_target_value(stock,0)
                continue
            rate = (open_price-now_price)/now_price
            # 如果股票今日到现在涨了4%。卖出
            if rate>0.04:
                order_target_value(stock,0)
    # 分配资金
    if len(context.portfolio.positions) < g.stocknum :
        Num = g.stocknum - len(context.portfolio.positions)
        Cash = context.portfolio.cash/Num
    else: 
        Cash = 0

    # 到点买来
    if not context.portfolio.positions.keys():
        if len(stock_list)!=0:
    # 买入股票
            for stock in stock_list:
                stock_name = str(stock)
                g.buy_price = get_current_data()[stock_name].last_price
                order_value(stock, Cash)
                g.day[stock] = 0

            
 

   
