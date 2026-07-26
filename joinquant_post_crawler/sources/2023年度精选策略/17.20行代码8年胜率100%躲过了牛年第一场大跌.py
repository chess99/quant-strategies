# 克隆自聚宽文章：https://www.joinquant.com/post/32112
# 标题：20行代码8年胜率100%躲过了牛年第一场大跌
# 作者：zireego

def initialize(context):
    set_benchmark('000300.XSHG')
    g.st='510300.XSHG'
    g.my='511010.XSHG'
    run_daily(market_open, time='open')
def market_open(context):
    signal = callsignal(context,'000001.XSHG')
    if signal == 0 and context.portfolio.positions[g.st].closeable_amount>0 :
        order_target_value(g.st,0)
        order_target_value(g.my,context.portfolio.available_cash)
    if signal == 1 and context.portfolio.positions[g.st].closeable_amount==0:
        order_target_value(g.my,0)
        order_value(g.st, context.portfolio.available_cash)
def callsignal(context,stock):
    c=attribute_history(stock,count = 32, unit='1d', fields=['close'], skip_paused=True, df=True, fq='pre')['close']
    if c.values.argmax()>22 and c.values.argmin()==0   and c[-1]<c[-30:].mean() and c[-2]<c[-32:-1].mean():
        return 0
    elif c[2]==max(c[2:]) and c[-20:].mean()>c[-30:].mean() and c[-10:].mean()>c[-20:].mean():
        return 1
    return -1
    
    
