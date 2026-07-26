# 克隆自聚宽文章：https://www.joinquant.com/post/43194
# 标题：14年初到23年7月，年化37，夏普1.25，稳健高收益！
# 作者：侧耳闻鹿鸣

from jqdata import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000002.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)

    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    g.security=get_index_stocks('000985.XSHG')
    g.q=query(valuation,indicator).filter(valuation.code.in_(g.security))
    run_weekly(period,weekday=1);
    
def period(context):
    df=get_fundamentals(g.q)[['code','inc_net_profit_year_on_year','roe','pb_ratio','pe_ratio','market_cap']]
    df=df[df['roe']>4]
    
    df=df.sort_values('pb_ratio')
    df['pbrank']=df['pb_ratio'].rank()
    df=df.iloc[:100,:]
    
    df=df.sort_values('inc_net_profit_year_on_year')
    df['profitrank']=df['inc_net_profit_year_on_year'].rank()
    df=df.iloc[-50:,:]
    
    
    
    
    
    to_hold=df['code'].values
    
    dff=history(count=100*20,unit='1d',field='close',security_list=to_hold)
    dfff=dff.T
    print(dfff.T)
    dfff_close=dfff.iloc[:,-1:]
    dfff=dfff.iloc[:,::20]
    #要注意这里虽然是20个一统计，但是最近的那一次是按照距离今天20日前的数据！
    dfff_jc=dfff.iloc[:,-1:]
    dfff=dfff.iloc[:,:-1]
    dfff_jc2=pd.concat([dfff_jc,dfff_close],axis=1,ignore_index=True)
    dfff_jc2.columns=['jc','close']
    dfff_jc2=dfff_jc2.T.drop_duplicates().T
    dfff=pd.concat([dfff,dfff_jc2],axis=1,ignore_index=True)
    print(dfff.T)
    
    mal=dfff.mean(axis=1);#mal 2000日均线
    mas=dfff.iloc[:,-20:]
    mas=mas.mean(axis=1);#mas 20日均线
    maa=pd.DataFrame([mas,mal])
    maa=maa.T
    #print(maa.head())
    maa.columns=['mas','mal']
    maa['mac']=maa['mas']-maa['mal']
    
    buy=maa[maa['mac']<0]#短均低于长均
    buy['code']=buy.index
    buy=buy['code'].values
    #print(buy)

    for stock in context.portfolio.positions:
        if stock not in buy:
            order_target_value(stock,0)#手里有但不符合全清空
    
    to_buy=[stock for stock in buy if stock not in context.portfolio.positions]
    #这是符合条件但没有的
    if len(to_buy)>0:
        cash_per_stock=context.portfolio.available_cash/len(to_buy)#把现有的钱平分给这些股票
        for stock in to_buy:
            order_value(stock, cash_per_stock)
    print("现在持有股票数量：",len(context.portfolio.positions))


