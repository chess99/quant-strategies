# 克隆自聚宽文章：https://www.joinquant.com/post/37051
# 标题：三因子策略_年化21%_简单多因子策略框架
# 作者：lastlivingsoul

# 导入函数库
from jqdata import *
from jqlib.alpha191 import *
from jqfactor import get_factor_values
import pandas as pd
import numpy as np
from jqfactor import standardlize,winsorize

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000001.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')

    # g.stocks=stocks_l
    
    # log.info(stocks)
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000001.XSHG')
      # 开盘时运行
    run_daily(market_open, time='open', reference_security='000001.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000001.XSHG')

## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    stocks=list(get_all_securities(types=['stock'], date=context.current_dt).index)
    stocks_st=pd.DataFrame()
    stocks_st['stocks']=stocks
    
    stocks_st['st']=get_extras('is_st',stocks, end_date=context.previous_date,count=1).iloc[0,:].values
    stocks_l=list(stocks_st.loc[stocks_st.st==0,'stocks'].values)
    stocks=stocks_l
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    if context.current_dt.month!=context.previous_date.month:
        # log.info("换月")
        # vroc_001=get_factor_values('000300.XSHG', ['VROC12'], end_date=context.previous_date, count=1)
        # vroc_001_all=get_factor_values('000300.XSHG', ['VROC12'], end_date=context.previous_date, count=100)
        # log.info('mean of vroc is:', vroc_001_all['VROC12'])
        bp0=get_factor_values(stocks, ['growth','residual_volatility','VROC12','size','momentum'], end_date=context.previous_date, count=1)
        
        # log.info(str(context.previous_date))
        bp=bp0['growth']
        size=bp0['size']
        res=bp0['residual_volatility']
        
        vroc=bp0['VROC12']
        vroc.fillna(0,inplace=True)
        vroc_001=vroc.iloc[0,:].values.mean()
        # log.info(standardlize(vroc.iloc[0,:].values, inf2nan=True, axis=1).mean())
        log.info(vroc_001)
        
        mom=bp0['momentum']
        bp2=pd.DataFrame()
        bp2['stocks']=bp.columns
        
        bp2['bp']=winsorize(standardlize(bp.iloc[0,:].values, inf2nan=True, axis=1),qrange=[0.05,0.93], inclusive=True, inf2nan=True, axis=1)
        # data, 
        bp2['residual_volatility']=winsorize(standardlize(res.iloc[0,:].values, inf2nan=True, axis=1),qrange=[0.05,0.93], inclusive=True, inf2nan=True, axis=1)
        bp2['VROC12']=winsorize(standardlize(vroc.iloc[0,:].values, inf2nan=True, axis=1),qrange=[0.05,0.93], inclusive=True, inf2nan=True, axis=1)
        bp2['size']=winsorize(standardlize(size.iloc[0,:].values, inf2nan=True, axis=1),qrange=[0.05,0.93], inclusive=True, inf2nan=True, axis=1)
        bp2['zscore']=bp2['residual_volatility']+bp2['VROC12']+bp2['size']
        # log.info(bp2.bp.mean())
        # bp2['mom']=standardlize(mom.iloc[0,:].values, inf2nan=True, axis=1)
        # bp2['zscore']=standardlize(res.iloc[0,:].values, inf2nan=True, axis=1)+standardlize(vroc.iloc[0,:].values, inf2nan=True, axis=1)+standardlize(mom.iloc[0,:].values, inf2nan=True, axis=1)#+standardlize(size.iloc[0,:].values, inf2nan=True, axis=1)
        # if vroc_001<500000:
        # bp2.bp+bp2.residual_volatility+bp2.size
        # bp2.sort_values(by='size',ascending=False,inplace=True)
        # bp2=bp2.iloc[:1000,:]
        # bp2.sort_values(by='bp',ascending=False,inplace=True)
        # bp2=bp2.iloc[:300,:]
        bp2.sort_values(by='zscore',ascending=True,inplace=True)
        # bp2.sort_values(by='mom',ascending=False,inplace=True)
        # bp2.sort_values(by='bp',ascending=False,inplace=True)
        bp2=bp2.iloc[:50,:]
        # bp2=bp2.iloc[:500,:]
        # bp2.sort_values(by='VROC12',ascending=False,inplace=True)
        # bp2=bp2.iloc[:100,:]
        g.securities=list(bp2.stocks.values)
        # else:
        #     bp2.sort_values(by='bp',ascending=False,inplace=True)
        #     bp2=bp2.iloc[:50,:]
        #     g.securities=list(bp2.stocks.values)
    # a=alpha_022(stocks,end_date=context.previous_date)
    # log.info('!!!!!!!!!',)
    # 给微信发送消息（添加模拟交易，并绑定微信生效）
    # send_message('美好的一天~')
    # a=a*(-1)
    # a.fillna(999,inplace=True)
    # 要操作的股票：平安银行（g.为全局变量）
    # g.securities = list(a.sort_values(ascending=True).index)[:100]
    # log.info(a.sort_values(ascending=True)[:100])
## 开盘时运行函数
def market_open(context):
    
    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    if context.current_dt.month!=context.previous_date.month:
        securities = g.securities
    
        
    
        for security in context.portfolio.positions:
        # log.info('position!!!!!',i)
            if security not in set(securities):
                order_target(security, 0)
        cash = context.portfolio.available_cash
        for security in securities:
            if context.portfolio.positions[security].closeable_amount == 0:
                order_value(security, cash/50)


## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    # trades = get_trades()
    # for _trade in trades.values():
    #     log.info('成交记录：'+str(_trade))
    log.info('一天结束')
    log.info('##############################################################')
