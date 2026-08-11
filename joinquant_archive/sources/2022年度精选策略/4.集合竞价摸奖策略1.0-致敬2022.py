# 克隆自聚宽文章：https://www.joinquant.com/post/36149
# 标题：集合竞价摸奖策略1.0-致敬2022
# 作者：矢南

# 标题：集合竞价摸奖策略1.0
# 作者：矢量化 ；公众号：矢量化
'''
策略思路：
龙头股一般从涨停板开始，涨停板是多空双方最准确的攻击信号，能涨停的个股极有可能是龙头，那么中奖的机会就在涨停板的股票列表里。
打板手法又可以分为打首板，一进二板，二进三板，三进四板，四进五板及更高，博取的是打板次日的情绪或者惯性溢价，所以涨停当日能够
封死涨停及其关键。据网友统计：首板的封死成功率70%；二板的封死成功率20%；三板的封死成功率33%；四板的封死成功率46%；五板的封死
成功率46%。可见，首板成功率较高；二板之后晋级概率较高而且连板的溢价较高；但高板之后因是高位接盘回调幅度相对也较大。故本策略
选的是1板票、3板的股票，力图最高成功率和收益最大化。
1.圈选：昨天收盘后选出1板票、3板票。
2.观察：交易日9:25观察第1步选好的股票，筛选攻击力强的股票，同时技术规避陷阱，准备摸奖。
3.摸奖：开盘即均仓买入第2步选好的股票（或开盘前提高一些价格比如提高1个点挂单）。
4.中奖：等待中奖，或止损
5.策略回测效果：
    集合竞价摸奖策略1.0回测效果：2021年7月15至12月15日，5个月收益122.90%，年化599.72%。
    集合竞价摸奖策略2.0回测效果：2021年7月15至12月15日，5个月收益239.45%，年化1842.21%。
继续努力改进...欢迎进微信群交流分享想法，有兴趣的联系微信：Shi_liang_hua。
'''

# 导入函数库
from jqdata import *
from jqlib.technical_analysis import *
import talib
import warnings
warnings.filterwarnings('ignore')

# 替换代码
def after_code_changed(context):
    unschedule_all()
    set_run_daily()
    
#########################################################################################################
# 初始化函数，设定基准等等
def initialize(context):
    set_option("avoid_future_data", True)
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    log.info('初始函数开始运行且全局只运行一次')
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    #设置运行时间
    set_run_daily()
    # 待买列表
    g.buy_list=[]  

#设置运行时间
def set_run_daily():
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    run_daily(market_open, time='open', reference_security='000300.XSHG')
    run_daily(Call_auction, time='09:25', reference_security='000300.XSHG')
    run_daily(market_open_sell_buy, time='every_bar', reference_security='000300.XSHG')
    run_daily(before_closing, time='14:55', reference_security='000300.XSHG')
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')
    
## 开盘前运行函数
def before_market_open(context):
    g.run_count=0
    
#集合竞价 09:25
def Call_auction(context):
    log.info('函数运行时间(Call_auction)：'+str(context.current_dt.time()))
    morning_observation(context)

## 开盘时运行函数 open
def market_open(context):
    #第一交易
    the_first_deal(context)

## 开盘时运行函数 every_bar
def market_open_sell_buy(context):
    #盘中买卖
    inntraday_trading(context)
    #清理走势差的票
    clearn_every_bar(context)
    #刷新计数
    g.run_count+=1
    if g.run_count==240: 
            g.run_count=0

## 开盘时运行 14:55
def before_closing(context):
    #收盘前卖出
    sell_before_closing(context)

## 收盘后运行函数
def after_market_close(context):
    # 初池
    stock_list=all_limit_up_stocks(context.current_dt.strftime("%Y-%m-%d"))
    # 选股
    consecutive_up_limit_stocks(context,stock_list,context.current_dt)
    #收盘后报告
    day_report(context)
    log.info('##############################################################')

#########################################################################################################
# 早晨观察
def morning_observation(context):
    curr_data=get_current_data()
    # 待买列表缓存
    buy_list_temp=[]
    for s in g.buy_list:
        buy_list_temp=count_call_auction_data(context,s,buy_list_temp)
    g.buy_list=buy_list_temp
    # 列举打印已选中的股票
    if len(g.buy_list)>0:
        for s in g.buy_list:
            log.info('好票 {} {}  \n'.format(s,curr_data[s].name))

# 摸奖函数
def count_call_auction_data(context,s,buy_list_temp):
    date=context.current_dt.strftime("%Y-%m-%d")
    df=gather_call_auction_data(s,date)
    if len(df)>2:
        a1_p_max=df['a1_p'].max()
        a1_p_min=df['a1_p'].min()
        a1_p0=df['a1_p'][-1]
        a1_p1=df['a1_p'][-2]
        a1_p2=df['a1_p'][-3]
        bars=get_bars(s,count=3,unit='1d',fields=['close'],include_now=False)
        if 1.0382<a1_p0/bars['close'][-1]<1.0618 and a1_p0==a1_p_max:
            log.info('A奖 {}'.format(s))
            buy_list_temp.append(s)
    return buy_list_temp

#########################################################################################################
# 第一交易
def the_first_deal(context):
    date = context.current_dt.strftime("%Y-%m-%d")
    for s in list(context.portfolio.positions):
        close_data=get_bars(s,count=3,unit='1d',fields=['open','low','close'],include_now=False)
        if close_data['close'][-1]/close_data['close'][-2]<1.098:
            df=gather_call_auction_data(s, date)
            if len(df)>3:
                a1_p0=df['a1_p'][-1]
                a1_p1=df['a1_p'][-2]
                a1_p2=df['a1_p'][-3]
                if a1_p0<a1_p1 or a1_p1<a1_p2 or a1_p0/close_data['close'][-1]<0.98 or a1_p0<close_data['close'][-1]<close_data['close'][-2]:
                    R = order_target(s, 0)
                    log.info('前一天没涨停，开盘卖出'+str(s))
    if len(g.buy_list)==0:
        return
    for security in g.buy_list:
        if security in list(context.portfolio.positions.keys()):
            continue
        # 买入股票
        R = order_value(security,1/len(g.buy_list)*context.portfolio.total_value)

#########################################################################################################
# 盘中买卖
def inntraday_trading(context):
    for s in list(context.portfolio.positions.keys()):
        if context.portfolio.positions[s].closeable_amount<=0:
            continue
        # 止损线
        stop_line=0.94
        close_data_1d=get_bars(s,count=3,unit='1d',fields=['open','high','low','close'],include_now=False)
        close_data_1m=get_bars(s,count=3,unit='1m',fields=['open','high','low','close'],include_now=False)
        if close_data_1d['close'][-1]/close_data_1d['close'][-2]>1.12:
            stop_line=0.9
        if close_data_1m['close'][-1]/close_data_1d['close'][-1]<stop_line:
            R=order_target(s,0)
            log.info('跌幅超过6%，盘中卖出'+str(s))

# 清理走势差的票
def clearn_every_bar(context):
    curr_data=get_current_data()
    hour=context.current_dt.hour
    minute=context.current_dt.minute
    sells=list(context.portfolio.positions)
    for s in sells: 
        if context.portfolio.positions[s].closeable_amount<=0:
            continue
        dfmcount = attribute_history(s,(g.run_count+1),'1m',['close'],skip_paused=True)
        if dfmcount.close[-1]<dfmcount.close.max():
            df = get_price(s,end_date=context.previous_date,count=10,fields=['open','close','high_limit','volume'],skip_paused=True)
            cond = (df.close>=df.high_limit) & (df.open<0.985*df.high_limit)
            # 跌停开盘，卖
            if curr_data[s].day_open<=curr_data[s].low_limit and curr_data[s].paused==0:
                R = order_target(s, 0)
            # 尾盘未涨停，卖       
            elif minute>55 and hour==14:
                if curr_data[s].last_price<curr_data[s].high_limit:  
                    R = order_target(s, 0)
            else:
                # 止损，卖
                if curr_data[s].last_price<context.portfolio.positions[s].avg_cost*0.94:
                    close_15m = attribute_history(s,89,'15m','close',skip_paused=True).close.values
                    if close_15m[-1]<np.mean(close_15m):
                        R = order_target(s, 0)

# 收盘前卖出
def sell_before_closing(context):
    # 卖出未涨停的股票
    sell_not_limit_up(context)

def sell_not_limit_up(context):
    df = history(1,'1d','close',context.portfolio.positions.keys())
    for s in list(context.portfolio.positions):
        if context.portfolio.positions[s].closeable_amount<=0:
            continue
        close_data = get_bars(s, count=2, unit='1m', fields=['open','high','low','close'],include_now=False)
        close_price = close_data['close'][-1]
        # 1.没涨停，卖
        if close_price/df[s][0]<1.098:
            R = order_target(s, 0)
        # 2.中小板20cm没涨停，卖
        elif close_price/df[s][0]>1.11 and close_price/df[s][0]<1.195:
            R = order_target(s, 0)

#########################################################################################################
# 盘后选股统计涨停股票
def consecutive_up_limit_stocks(context,stock_list, thisDate):
    cur_data = get_current_data()
    stock_list = list(get_fundamentals(query(valuation.code).filter(valuation.circulating_market_cap<100,valuation.code.in_(stock_list)).order_by(indicator.roe.desc())).code)
    limit_stocks_num = len(stock_list)
    stocks = []
    ups = []
    names = []
    limit_stocks = []
    for s in stock_list:
        n = 0
        df = get_price(s,end_date=thisDate,frequency='1d',fields=['pre_close','low','close','high_limit','paused'] ,count=15)
        if df['paused'][-1]!=0 or df['close'][-1]/df['pre_close'][-1]<1.09:
          continue
        flag = False
        for i in range(15):
            if df['close'][-1-i]>=df['high_limit'][-1-i] and df['paused'][-1-i]==0:
                if df['close'][-2-i]>=df['high_limit'][-2-i] and df['paused'][-2-i]==0:
                    n += 1
                elif df['close'][-1-i]>=df['low'][-1-i]+0.05:
                    n += 1
                else:
                    if df['close'][-i]>=df['low'][-i]+0.05:
                        flag=True
                    else:
                        break
            else:
                if n>0:
                    if df['close'][-i]>=df['low'][-i]+0.05:
                        flag = True
                    elif df['close'][-i+1]>=df['low'][-i+1]+0.05:
                        n=n-1
                        flag=True
            if flag==True:
                stocks.append(s)
                ups.append(n)
                names.append(cur_data[s].name)
                break
    df_data = pd.DataFrame(columns = ['code','name','ups'])
    df_data['code'] = stocks
    df_data['name'] = names
    df_data['ups'] = ups
    df_data.index = df_data['code']
    g.day_ups_max = df_data['ups'].max()
    df_data['ups'] = np.where(df_data['ups'] < -1, g.day_ups_max, df_data['ups'])
    # 选出第1板，3板涨停票
    df_data_limit_stocks = df_data[(df_data['ups']==1)|(df_data['ups']==3)]
    # 排除三停和不良不利股票
    limit_stocks = clean_st_688(df_data['code'].tolist())
    # 记录 
    g.buy_list = limit_stocks
    # 列举打印已选中的股票
    if len(g.buy_list)>0:
        log.info(df_data_limit_stocks[['name','ups']])

def all_limit_up_stocks(thisDate):
    trd_date=get_trade_days(end_date=thisDate,count=100)[0]
    stocks=list(get_all_securities(types=['stock'],date=trd_date).index)
    df=get_price(stocks,end_date=thisDate,frequency='1d',fields=['open','close','high','high_limit','paused'], count=1).iloc[:,0]
    df=df[df['paused']==0]
    stocks=df[df['close']==df['high_limit']].index.tolist()
    return stocks

def gather_call_auction_data(s,date):
    start=date+' 09:15:00'
    end=date+' 09:25:00'
    t=get_ticks(s,end,start,None,['time','current','a1_p','a1_v','b1_v'],skip=False) #['time', 'current', 'a1_p', 'a1_v', 'b1_v']#[时间,当前价,一档卖价,一档卖量，一档买量]
    df=pd.DataFrame(t)
    df.time=pd.to_datetime(df.time.astype(int).astype(str))
    df.set_index('time',inplace=True)
    df.current[df.current==0]=df.a1_p[df.current==0]
    return df

# 收盘报告
def day_report(context):
    current_returns=100*context.portfolio.returns
    log.info("当前收益：%.2f%%; 当前持仓数量: %s", current_returns, len(list(context.portfolio.positions.keys())))
    log.info("当前持仓: ")
    current_data = get_current_data()
    for s in context.portfolio.positions:
        cost=context.portfolio.positions[s].avg_cost
        price=context.portfolio.positions[s].price
        syl=(price/cost-1)*100
        log.info("    名称: %s,代码: %s,数量: %s,成本: %s,收益: %.2f%%",current_data[s].name,s\
        ,context.portfolio.positions[s].closeable_amount,context.subportfolios[0].long_positions[s].hold_cost,syl)
    log.info("总资产: {},当前收益：{}".format(context.portfolio.total_value,round(current_returns,2)))

#########################################################################################################
def clean_st_688(stocks):
    curr_data=get_current_data()
    stocks=[s for s in stocks if not (curr_data[s].is_st or('ST' in curr_data[s].name) or('*' in curr_data[s].name) or('退' in curr_data[s].name) or(s.startswith('688')))]
    return stocks

def fit_linear_nor(lis):
    from scipy.stats import linregress
    x=np.arange(len(lis))
    m=linregress(x,lis)[0]
    m1=round(float(m),3)
    return m1
