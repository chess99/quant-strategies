# 克隆自聚宽文章：https://www.joinquant.com/post/47771
# 标题：穿越牛熊2.0(非小市值):年化50%的cta策略
# 作者：wsd518

# 导入函数库
from jqdata import *

## 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('I8888.XDCE')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')

    ### 期货相关设定 ###
    # 设定账户为金融账户
    set_subportfolios([SubPortfolioConfig(cash=context.portfolio.starting_cash, type='index_futures')])
    # 期货类每笔交易时的手续费是：买入时万分之0.23,卖出时万分之0.23,平今仓为万分之23
    set_order_cost(OrderCost(open_commission=0.000023, close_commission=0.000023,close_today_commission=0.0023), type='index_futures')
    # 设定保证金比例
    set_option('futures_margin_rate', 0.15)
    g.tradecode=''
    g.flag=0

    # 设置期货交易的滑点
    set_slippage(StepRelatedSlippage(2))
    # 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'IF8888.CCFX'或'IH1602.CCFX'是一样的）
    # 注意：before_open/open/close/after_close等相对时间不可用于有夜盘的交易品种，有夜盘的交易品种请指定绝对时间（如9：30）
      # 开盘前运行
    run_monthly(month_open, -5,  time='9:01', reference_security='I8888.XDCE')
    run_daily(day_open,   time='9:02', reference_security='I8888.XDCE')
    return

def get_近月合约(date):
    ftpd=get_all_securities(['futures'])
    ftpd['start_date']=[str(d)[0:10] for d in ftpd['start_date'].tolist()]
    ftpd['end_date']=[str(d)[0:10] for d in ftpd['end_date'].tolist()]
    ftpd['pz']=[str(x)[0:-4].upper() for x in ftpd['name'].tolist()]
    ftpd['month']=[str(x)[-2::] for x in ftpd['name'].tolist()]
    ftpd=ftpd[ftpd['pz']=='I']
    month1=str(100+(int(date[-5:-3])+1)%12)[1::]
    month2=str(100+(int(date[-5:-3])+2)%12)[1::]
    if month1=='00':
        month1='12'
    if month2=='00':
        month2='12'
    ftpd=ftpd[(ftpd['start_date']<date)&(ftpd['end_date']>date)]
    code1=ftpd[ftpd['month']==month1].index.tolist()[0]
    code2=ftpd[ftpd['month']==month2].index.tolist()[0]
    
    return code1,code2



## 开盘时运行函数
def month_open(context):

    ## 交易
    date=str(context.current_dt.date() )[0:10]
    code1,code2=get_近月合约(date)
    g.tradecode=code2
    #如有持仓，先平仓
    if code1 in context.portfolio.positions.keys():
        order_target(code1, 0, side='long')
    
    if isdown(context)==-1:
        g.flag=0
        return
    
    #计算开仓数量
    total_value = context.portfolio.total_value
    price=get_bars(g.tradecode, 1, unit='1d',fields=['close'],)[0][0]
    amount=int(total_value/(price*100))
    #开仓
    order_target(g.tradecode, amount, side='long')
    g.flag=1
    return 

## 开盘时运行函数
def day_open(context):
    if g.tradecode=="":
        return
    if isdown(context)==-1 and g.flag==1:
        order_target(g.tradecode, 0, side='long')
        g.flag=0
        return
    if isdown(context)==0 and g.flag==0:
        #计算开仓数量
        total_value = context.portfolio.total_value
        price=get_bars(g.tradecode, 1, unit='1d',fields=['close'],)[0][0]
        amount=int(total_value/(price*100))
        #开仓
        order_target(g.tradecode, amount, side='long')
        g.flag=1
    
    return 

#判断均线是否空头排列
def isdown(context):
    pricedata=get_bars('I8888.XDCE', 60, unit='1d',fields=['close'],df=True)
    price=pricedata.iloc[-1,0]
    ma20=pricedata.iloc[-20::,0].mean()
    ma60=pricedata['close'].mean()
    if price<ma20 and ma20<ma60:
        return -1
    else:
        return 0


