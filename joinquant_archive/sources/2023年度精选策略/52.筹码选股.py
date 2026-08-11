# 克隆自聚宽文章：https://www.joinquant.com/post/30606
# 标题：筹码选股
# 作者：sonnet_me

from jqdata import *
from datetime import datetime,timedelta
import pandas as pd

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
    #股东人数变动表
    g.shareholder_table=[]
    #十大流通股东持股变动表
    g.institutional_table=[]

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_monthly(main, monthday=1)
    run_daily(func,time="every_bar")
    #调仓月份
    g.tiao=[5,9,11]
    g.stock=[]
    #延迟买入
    g.delay_buy=[]
    #延迟卖出
    g.delay_sell=[]
    g.max_num = 20
    
# 过滤涨跌停板股票
def limit_price(security_list):
    current_data=get_current_data()
    security_list=[stock for stock in security_list if current_data[stock].last_price!=current_data[stock].high_limit]
    security_list=[stock for stock in security_list if current_data[stock].last_price!=current_data[stock].low_limit]
    return security_list
#过滤停牌、退市、ST股票
def tx_filter(security_list):
    current_data=get_current_data()
    security_list = [stock for stock in security_list if not current_data[stock].paused]
    security_list = [stock for stock in security_list if not '退' in current_data[stock].name]
    security_list = [stock for stock in security_list if not current_data[stock].is_st]
    return security_list

def main(context):
    if context.current_dt.month in g.tiao:
        #提取全市场的个股的代码
        # g.stocks = list(get_all_securities(['stock']).index)
        
        g.stocks = get_index_stocks('000905.XSHG')
        #过滤停牌，ST股，退市股
        g.stocks=tx_filter(g.stocks)
        #获取股东户数选股结果的列表
        Buylist1=check_stock1(context,g.stocks)
        # print('股东户数选股结果：',Buylist1,len(Buylist1))
        #获取机构持股选股的列表
        Buylist2=check_stock2(context,g.stocks)
        # print('机构持股选股结果：',Buylist2,len(Buylist2))
        #使用集合去重两个最终的列表
        final_Buylist=list(set(Buylist1+Buylist2))
        print('去重结果：',final_Buylist,len(final_Buylist))
        q = query(
                valuation.code,
                indicator.inc_revenue_annual
            ).filter(
		        valuation.code.in_(final_Buylist)
	        ).order_by(
		        valuation.pe_ratio < 15,
		        indicator.roa.desc()
		    )
        final_Buylist = list(get_fundamentals(q).code)[:g.max_num]
        print('筛选结果：',final_Buylist,len(final_Buylist))
        trade(context,final_Buylist)

#交易函数       
def trade(context,stock_list):
    ## 获取持仓列表
    sell_list = list(context.portfolio.positions.keys())
    #发送交易信息
    send_message('买入列表%s'%(stock_list), channel='weixin')
    # 如果有持仓，则卖出
    if len(sell_list) > 0 :
        for stock in sell_list:
            if stock not in stock_list:
                sell=order_target_value(stock, 0)
                if sell:
                    print(sell.filled)
                if not sell:
                    print('卖出下单失败，等待成交')
                    g.delay_sell.append(stock)
            else:
                stock_list.remove(stock)

    ## 分配资金
    if len(context.portfolio.positions) <g.max_num :
        Num = g.max_num - len(context.portfolio.positions)
        Cash = context.portfolio.cash/Num
    else: 
        Cash = 0

    ## 买入股票
    for stock in stock_list:
        if len(context.portfolio.positions.keys()) < g.max_num:
            chengjiao=order_value(stock, Cash)
            if chengjiao:
                print(chengjiao.filled)
            if not chengjiao:
                print('买入下单失败，等待成交')
                g.delay_buy.append(stock)

#日交易函数，处理trade订单开盘买入失效，在开盘后连续竞价买入    
def func(context):
    if len(g.delay_sell)>0:
        for stock in g.delay_sell:
            sell=order_value(stock,0)
            if sell:
                g.delay_sell.remove(stock)
                print(sell.filled)
            if not sell:
                print('卖出下单失败，等待成交')
            
    if len(g.delay_buy)>0:
        cash=context.portfolio.cash/len(g.delay_buy)
        for stock in g.delay_buy:
            chengjiao=order_value(stock,cash)
            if chengjiao:
                g.delay_buy.remove(stock)
                print(chengjiao.filled)
            if not chengjiao:
                print('买入下单失败，等待成交')
#进行时间转换      
def timechange(context):
    dt1=context.current_dt
    if dt1.month==5:
        #计算月初
        monthstart1 = datetime(dt1.year,dt1.month-1,1)
        dt2=get_trade_days(start_date=monthstart1,end_date=dt1+timedelta(10))[0]
        # dt2=dt1.date()
        monthstart2 = datetime(dt1.year,dt1.month-4,1)
        dt3=get_trade_days(start_date=monthstart2,end_date=dt1+timedelta(10))[0]   # 往前推6个月   5--11
    elif dt1.month==9:
        monthstart1 = datetime(dt1.year,dt1.month-4,1)
        dt2=get_trade_days(start_date=monthstart1,end_date=dt1+timedelta(10))[0]
        monthstart2 = datetime(dt1.year,dt1.month-5,1)
        dt3=get_trade_days(start_date=monthstart2,end_date=dt1+timedelta(10))[0]
    elif dt1.month==11:
        monthstart1 = datetime(dt1.year,dt1.month-2,1)
        dt2=get_trade_days(start_date=monthstart1,end_date=dt1+timedelta(10))[0]
        monthstart2 = datetime(dt1.year,dt1.month-6,1)
        dt3=get_trade_days(start_date=monthstart2,end_date=dt1+timedelta(10))[0]
    else:
        dt2=None
        dt3=None
    return dt2,dt3
    
#进行选股股东户数减少做多的100名    
def check_stock1(context,stocks):
    #获取当前时间
    dt1=context.current_dt
    #获取dt2、dt3时间点
    dt2,dt3=timechange(context)
    # print(dt1.date(),dt2,dt3) #datetime.date,datetime
    # choice_by_shareholder(stocks,dt1,dt2,dt3)
    
    for stock in stocks:
        choice_by_shareholder(stock,dt1,dt2,dt3)
    
    
    
    #把包含dict的列表转换成DataFrame类型数据
    shareholder=pd.DataFrame(g.shareholder_table)
    #对shareholder_ratio列进行降序排序，
    shareholder=shareholder.sort_values('shareholder_ratio',ascending=False)
    # print(shareholder)
    #选取股东户数减少最多的100名
    buylist1=shareholder['code'].head(100)
    #选取公告区间价格涨幅靠前的50个
    # final_buylist1=interval_gain(buylist1,dt1,dt2)
    #以列表的形式返回结果
    return list(buylist1)   
    
#获取股东户数增长率表
def choice_by_shareholder(stock,dt1,dt2,dt3):
    #获取第一个时间段的数据
    q1=query(finance.STK_HOLDER_NUM.code,
    finance.STK_HOLDER_NUM.a_share_holders,
    finance.STK_HOLDER_NUM.pub_date
    ).filter(finance.STK_HOLDER_NUM.code==stock,
    finance.STK_HOLDER_NUM.a_share_holders>10000,
    finance.STK_HOLDER_NUM.pub_date<dt1,
    finance.STK_HOLDER_NUM.pub_date>dt2,
    )
    df1=finance.run_query(q1)
    # print(df1)
    q2=query(finance.STK_HOLDER_NUM.code,
    #获取第二个时间段的数据
    finance.STK_HOLDER_NUM.a_share_holders,
    finance.STK_HOLDER_NUM.pub_date
    ).filter(finance.STK_HOLDER_NUM.code==stock,
    finance.STK_HOLDER_NUM.a_share_holders>10000,
    finance.STK_HOLDER_NUM.pub_date<dt2,
    finance.STK_HOLDER_NUM.pub_date>dt3
    )
    df2=finance.run_query(q2)  
    # print(df2)
    a=len(df1)
    b=len(df2)
    if a>=2:
        shareholder_ratio=(df1['a_share_holders'][a-2]-df1['a_share_holders'][a-1])/df1['a_share_holders'][a-2]
        # print(shareholder_ratio)   # 负数表示比上次发布增加多少
    elif a==1:
        if b>=1:
            shareholder_ratio=(df2['a_share_holders'][b-1]-df1['a_share_holders'][a-1])/df2['a_share_holders'][b-1]
        else:
            shareholder_ratio=None
    else:
        shareholder_ratio=None
    if shareholder_ratio:
        g.shareholder_table.append({'code':stock,'shareholder_ratio':shareholder_ratio})
        g.stock.append(stock)
    else:
        return

#获取十大流通股东机构占比选股结果
def check_stock2(context,stocks):
    #获取当前时间
    dt1=context.current_dt
    #获取时间段
    dt2,dt3=timechange(context)
    for stock in stocks:
        a,c=institutional_shareholder(stock,dt2,dt1)
        #如果当前没有两个数据，则再向前取一个周期
        if c<2:
            a,c=institutional_shareholder(stock,dt3,dt1)
            #如果跨越两个报告期，没有两个数据，要么数据缺失，要么公司没有在法定期内公布季报，直接跳过
            if c<2:
                continue
        # print(a)
        #获取该股机构持股比例的变动率
        institutional_ratio=(a['share_ratio'][c-1]-a['share_ratio'][c-2])/a['share_ratio'][c-2]
        #以字典的形式，把stock的nstitutional_ratio保存在列表中
        g.institutional_table.append({'code':stock,'institutional_ratio':institutional_ratio})
    
    #把列表转换成DataFrame数据类型
    institutional_holder_tabler=pd.DataFrame(g.institutional_table)
    # print(institutional_holder_tabler)
    #对shareholder_ratio列进行降序排序，
    institutional_holder=institutional_holder_tabler.sort_values('institutional_ratio',ascending=False)
    
    # 选取选取机构持股比例增加最多的100名
    buylist2=institutional_holder['code'].head(100)
    #选取区间涨幅前50名的个股
    # final_buylist2=interval_gain(buylist2,dt1,dt2)
    #以列表的形式返回结果
    return list(buylist2)
    

#获取机构持股比例    
def institutional_shareholder(stock,time1,time2):
    q=query(finance.STK_SHAREHOLDER_FLOATING_TOP10.code,
    finance.STK_SHAREHOLDER_FLOATING_TOP10.pub_date,
    finance.STK_SHAREHOLDER_FLOATING_TOP10.company_name,
    finance.STK_SHAREHOLDER_FLOATING_TOP10.shareholder_class,
    finance.STK_SHAREHOLDER_FLOATING_TOP10.share_number,
    finance.STK_SHAREHOLDER_FLOATING_TOP10.share_ratio
    ).filter(finance.STK_SHAREHOLDER_FLOATING_TOP10.code==stock,
    finance.STK_SHAREHOLDER_FLOATING_TOP10.pub_date>time1,
    finance.STK_SHAREHOLDER_FLOATING_TOP10.pub_date<time2,
    finance.STK_SHAREHOLDER_FLOATING_TOP10.shareholder_class!='自然人'#剔除‘自然人’股东
    ).limit(30)
    df=finance.run_query(q)
    #以公布时间为分组条件，对‘share_ratio’列进行按组加总求和
    a=df.pivot_table(index='pub_date',values=['share_ratio'],aggfunc=sum)
    #返回a的长度
    c=len(a)
    return a,c
