# 克隆自聚宽文章：https://www.joinquant.com/post/33823
# 标题：年化46%的北向资金+20日涨幅的创业板策略
# 作者：天然15

# 北向资金数据克隆自聚宽文章：https://www.joinquant.com/post/28989
# 标题：沪深300ETF跟踪北向资金策略
# 作者：pia19

# 导入函数库
from jqdata import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之二，卖出时佣金万分之二，无印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.000, open_commission=0.0002, close_commission=0.0002, min_commission=5), type='fund')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
      # 开盘时运行
    run_daily(market_open, time='open', reference_security='000300.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')

## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    # log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    get_flowin()
    # 给微信发送消息（添加模拟交易，并绑定微信生效）
    # send_message('美好的一天~')

## 开盘时运行函数
def market_open(context):
    # log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    check_flowin(context)
    check_rate20(context)
    check_stop(context)
    #print(g.df.loc[yesterday,'total_flowin'],g.df.loc[yesterday,'total_flowin'])

## 收盘后运行函数
def after_market_close(context):
    # log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    # log.info('一天结束')
    # log.info('##############################################################')

# 获取北向资金布林线 
def get_flowin():
    #沪股通数据  每日净流入
    df_hu = finance.run_query(query(finance.STK_ML_QUOTA.quota_daily,
    finance.STK_ML_QUOTA.quota_daily_balance,finance.STK_ML_QUOTA.day
    ).filter(finance.STK_ML_QUOTA.day>='2017-01-10',finance.STK_ML_QUOTA.link_name=='沪股通'))
    df_hu['flowin_hu'] = df_hu['quota_daily'] - df_hu['quota_daily_balance']
    df_hu = df_hu.drop(columns=['quota_daily','quota_daily_balance'])
    #深股通数据 每日净流入
    df_shen = finance.run_query(query(finance.STK_ML_QUOTA.quota_daily,
    finance.STK_ML_QUOTA.quota_daily_balance,finance.STK_ML_QUOTA.day
    ).filter(finance.STK_ML_QUOTA.day>='2017-01-10',finance.STK_ML_QUOTA.link_name=='深股通'))
    df_shen['flowin_shen'] = df_shen['quota_daily'] - df_shen['quota_daily_balance']
    df_shen = df_shen.drop(columns=['quota_daily','quota_daily_balance'])
    #合并沪深股通
    df = df_hu.set_index('day').join(df_shen.set_index('day'))
    df = df.fillna(0)
    #求北向资金布林线[252,1.5]的上轨和下轨
    df['total_flowin'] = df['flowin_shen'] + df['flowin_hu']
    df['252_std'] = df['total_flowin'].rolling(252).std()
    df['252_mean'] = df['total_flowin'].rolling(252).mean()
    df['lower_interval'] = df['252_mean'] - 1.5*df['252_std']
    df['upper_interval'] = df['252_mean'] + 1.5*df['252_std']
    g.df = df

# 检查昨日的北向资金流入
def check_flowin(context):
    yesterday = context.previous_date
    #print(g.df,yesterday)
    # 取得当前的现金
    cash = context.portfolio.available_cash
    try:
        # 如果昨日北向资金流入突破布林线上轨, 则全部买入
        if g.df.loc[yesterday,'total_flowin'] > g.df.loc[yesterday,'upper_interval']:
            # 用所有 cash 买入股票
            order_value('159915.XSHE', cash)
        # 如果昨日北向资金流入跌破布林线下轨, 则全部卖出
        elif g.df.loc[yesterday,'total_flowin'] < g.df.loc[yesterday,'lower_interval']:
            # 卖出所有股票,使这只股票的最终持有量为0
            order_target('159915.XSHE', 0)
    except:
        pass
    
# 获取昨日的20日涨幅
def get_rate20(fund):
    close_data = get_bars(fund, count=21, unit='1d', fields=['date','close'])
    close_before_21 = close_data['close'][0]
    close_before_1 = close_data['close'][-1]
    rate20=close_before_1/close_before_21-1
    return rate20

# 检查创业板的20日涨幅
def check_rate20(context):
    #创业板 159915
    g.funds=['159915.XSHE'] 
    target_value=context.portfolio.total_value/len(g.funds)
    for fund in g.funds:
        rate20=get_rate20(fund)
        # 若20日涨幅高于5%, 则买入
        if rate20 >= 0.05 and fund not in context.portfolio.positions:
            # 买入LOF基金  买入信号由北向资金信号决定，涨幅信号仅供参考
            # order_target_value(fund, target_value)
            pass
        # 若20日涨幅低于-5%, 则卖出
        elif rate20 <= -0.05 and fund in context.portfolio.positions:
            order_target_value(fund, 0)
    
# 检查止损信号,单笔交易-10%时,无条件止损
def check_stop(context):
    for position in list(context.portfolio.positions.values()):
        fund=position.security
        value=round(position.value,0)
        price=position.price
        avg_cost=position.avg_cost
        rate=round(price/avg_cost-1,2)
        rate20=get_rate20(position.security)
        if rate <=-0.10:
           # 卖出基金
            order_target_value(position.security, 0)
            log.info("触发止损信号: 标的={0},标的价值={1},20日涨幅={2},浮动盈亏={3} ".format(position.security,round(position.value,0),rate20,rate))
            
