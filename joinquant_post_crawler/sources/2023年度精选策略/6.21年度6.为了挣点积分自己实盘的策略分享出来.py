# 克隆自聚宽文章：https://www.joinquant.com/post/32660
# 标题：如何删帖呢
# 作者：iron911

# 风险及免责提示：该策略由聚宽用户在聚宽社区分享，仅供学习交流使用。
# 原文一般包含策略说明，如有疑问请到原文和作者交流讨论。
# 原文网址：https://www.joinquant.com/post/32660
# 标题：为了挣点积分，自己实盘的策略分享出来
# 作者：iron911

# 改进：iron911
# 克隆自聚宽文章：https://www.joinquant.com/post/32536
# 标题：稳定盈利的etf轮动3000%收益
# 作者：顺势交易者

from jqdata import *
from pandas.core.frame import DataFrame
import talib

'''

持仓原则：
    1、对泸深指数的成交量进行统计，如果连续6（lag）天成交量小于7（lag0)天成交量的，空仓处理（购买货币基金511880 银华日利或国债 511010 ）
    2、13个交易日内（lag1）涨幅大于1的，并且“均线差值”大于0的才进行考虑。
    3、对符合考虑条件的ETF的涨幅进行排序，买涨幅最高的三个。
'''
def initialize(context):
    set_params()
    set_variables()
    set_backtest()
    run_daily(ETFtrade1, time='11:30')
    if g.signal == 'sell_the_stocks':
        run_daily(ETFtrade2, time='13:00')
    else:
        run_daily(ETFtrade2, time='14:40')

#1 设置参数
def set_params():
    # 设置基准收益
    set_benchmark('000300.XSHG')
    g.use_dynamic_target_market = True #是否动态改变大盘热度参考指标
    #g.target_market = '000300.XSHG'
    g.target_market = '399001.XSHE'
    g.empty_keep_stock = '511880.XSHG'#闲时买入的标的
    #g.empty_keep_stock = '601318.XSHG'#闲时买入的标的
    g.signal = 'KEEP'  #交易信号初始化
    g.emotion_rate = 0 #市场热度
    g.emotion_p = 0   #大盘成交量均线突破天数
    g.emotion_n = 0   #大盘成交量均线跌破天数
    g.lag = 5  #大盘成交量连续跌破均线的天数，发出空仓信号
    g.lag0 = 7  #大盘成交量监控周期
    g.lag1 = 13  #比价均线周期
    g.lag2 = 13  #价格涨幅计算周期
    g.last = [] #持仓股票代码初始化
    g.buy = [] #购买股票列表
    g.clear = []
    g.df = pd.DataFrame()
    g.ETFList = {
  
        #'399975.XSHE':'512880.XSHG',#证券ETF
        '399632.XSHE':'159901.XSHE',#深100etf
        '162605.XSHE':'162605.XSHE',#景顺鼎益
        '161005.XSHE':'161005.XSHE',#富国天惠
        '000016.XSHG':'510050.XSHG',#上证50
        '000010.XSHG':'510180.XSHG',#上证180
        '000015.XSHG':'510880.XSHG',#红利ETF
        '399324.XSHE':'159905.XSHE',#深红利
        '399006.XSHE':'159915.XSHE',#创业板
        '000300.XSHG':'510300.XSHG',#沪深300
        '000905.XSHG':'510500.XSHG',#中证500   
        '399673.XSHE':'159949.XSHE'#创业板50
    }

    g.IdxList=dict(zip(g.ETFList.values(),g.ETFList.keys()))

    stocks_info = "\n股票池:\n"
    for security in g.ETFList.values():
        s_info = get_security_info(security)
        stocks_info+="【%s】%s 上市间间:%s\n"%(s_info.code,s_info.display_name,s_info.start_date)
    log.info(stocks_info)
#设置中间变量
def set_variables():
    return

#设置回测条件
def set_backtest():
    set_option("avoid_future_data", True)
    set_option('use_real_price', True) #用真实价格交易
    log.set_level('order', 'error')


'''
=================================================
每天开盘前
=================================================
'''
#每天开盘前要做的事情
def before_trading_start(context):
    set_slip_fee(context) 

# 根据不同的时间段设置滑点与手续费
def set_slip_fee(context):
    # 将滑点设置为0
    set_slippage(FixedSlippage(0)) 
    # 设置手续费
    set_commission(PerTrade(buy_cost=0.0005, sell_cost=0.0005, min_cost=5))


'''
=================================================
每日交易时
=================================================
''' 
def ETFtrade1(context):
    g.signal = get_signal(context)
    
def ETFtrade2(context):
    if g.signal == 'sell_the_stocks':
        for stock in context.portfolio.positions.keys():
            if (stock == g.empty_keep_stock):
                continue
            log.info("正在卖出 %s" % stock)
            order_target_value(stock, 0)
    elif g.signal == 'KEEP':
        log.info("交易信号:持仓不变")
    elif g.signal == 'BUY':
        if g.empty_keep_stock in context.portfolio.positions.keys():
            order_target_value(g.empty_keep_stock, 0)
        g.last = list(context.portfolio.positions.keys())
        g.buy.sort()
        g.last.sort()
        ratio = len(g.buy)
        cash = context.portfolio.total_value/ratio
        for code in g.last:#先进行清仓处理，如果持仓股票不在购买清单中
            if code not in g.buy:
                log.info("正在清空 %s" % code)
                order_target_value(code,0)
                g.clear.append(code)
        for code in g.clear:#从g.last删除已经卖出的标的
            g.last.remove(code)
        g.clear = [] #清除临时列表
        for code in g.last:#如果持仓在购买清单中判断调仓
            if code in g.buy:
                positions_dict = context.portfolio.positions
                for position in list(positions_dict.values()):    
                    if position.value/cash > 1.5:
                        log.info("正在调仓 %s" % position.security)
                        order_target_value(position.security,cash)
        for code in g.buy:
            if code not in g.last:
                log.info("正在买入 %s" % code)
                order_value(code,cash)
                g.last.append(code)
        g.buy = []
        current_returns = 100*context.portfolio.returns
        log.info("当前收益：%.2f%%，当前持仓%s",current_returns,g.last)
    if len(context.portfolio.positions)==0:
            order_target_value(g.empty_keep_stock, context.portfolio.available_cash)

#获取信号
def get_signal(context):
    i=0 # 计数器初始化
    # 创建保持计算结果的DataFrame
    g.df = pd.DataFrame()
    for k in g.ETFList.values():
        security = k# key()以指数计算交易信号，values()以基金计算交易信号
    # 获取股票的收盘价
        close_data = attribute_history(security, g.lag1, '1d', ['close'],df=False)
    # 获取股票现价
        current_data = get_current_data()
        current_price = current_data[security].last_price
    # 获取股票的阶段收盘价涨幅
        cp_increase = (current_price/close_data['close'][g.lag2-g.lag1]-1)*100
    # 取得平均价格
        ma_n1 = close_data['close'].mean()
    # 计算前一收盘价与均值差值    
        pre_price = (current_price/ma_n1-1)*100
        g.df.loc[i,'股票代码'] = security # 把标的股票代码添加到DataFrame
        g.df.loc[i,'股票名称'] = get_security_info(security).display_name # 把标的股票名称添加到DataFrame
        g.df.loc[i,'周期涨幅%'] = cp_increase # 把计算结果添加到DataFrame
        g.df.loc[i,'均线差值%'] = pre_price # 把计算结果添加到DataFrame
        i=i+1
    # 对计算结果表格进行从大到小排序
    g.df = g.df.fillna(-100)
    g.df.sort_values(by='周期涨幅%',ascending=False,inplace=True) # 按照涨幅排序
    g.df.reset_index(drop=True, inplace=True) # 重新设置索引
    if g.use_dynamic_target_market:
        g.target_market = g.IdxList[str(g.df.iloc[-1,0])] #不用最高的来处理

    if EmotionMonitor(context) == -1: # 大盘情绪不好发出空仓信号
        log.info("交易信号:大盘成交量持续低均线，空仓")
        g.last = []
        g.buy = []
        return 'sell_the_stocks'    
    log.info("\n行情统计,%s 热度%f%%:\n%s" % (g.target_market,g.emotion_rate,g.df))
    #send_message("\n行情统计结果表:\n%s" % (g.df))
    if g.df.iloc[0,2] <0.1 or g.df.iloc[0,3] <0: # 均不符合买入条件    
        if len(g.last) == 0:# 持仓为空
            log.info("交易信号:继续保持空仓状态")
            return 'KEEP'# 持仓保持不变
        else:# 持仓不为空
            log.info("交易信号:空仓")
            g.last = []
            g.buy = []
            return 'sell_the_stocks' 
    #删除不符合要求的标的
    for t in g.df.index:
        if g.df.loc[t,'周期涨幅%'] <0.1 or g.df.loc[t,'均线差值%'] <0:
            g.df=g.df.drop(t)
    # 表不为空,持有排名前三名的股
    if g.df.shape[0] > 12 :
        g.buy.append(str(g.df.iloc[0,0]))
        g.buy.append(str(g.df.iloc[1,0]))
        g.buy.append(str(g.df.iloc[2,0]))
        log.info("交易信号:持有 %s" % (g.buy))
        return 'BUY'
    # 表不为空,持有排名前两名的股
    if g.df.shape[0] > 12 :# 表不为空,持有排名前两名的股
        g.buy.append(str(g.df.iloc[0,0]))
        g.buy.append(str(g.df.iloc[1,0]))
        log.info("交易信号:持有 %s" % (g.buy))
        return 'BUY'    
    else: # 持第一名的股
        g.buy.append(str(g.df.iloc[0,0]))                
        log.info("交易信号:持有 %s" % (g.buy))
        return 'BUY'

# 大盘行情监控函数
def EmotionMonitor(context):
    try:
        volume = attribute_history(g.target_market,100, '1d', ('volume'))['volume'].values
        v_ma_lag0 = talib.MA(volume,g.lag0)
        vol = volume / v_ma_lag0 - 1
        g.emotion_rate = round(vol[-1] * 100,2)
        for i in range(30):
            if vol[-1]>=0:
                if vol[-1-i]<0:
                    return 1 if (i >= 3) else 0
            else:
                if vol[-1-i]>=0:
                    return -1 if (i >= g.lag) else 0
    except:
        return 1
