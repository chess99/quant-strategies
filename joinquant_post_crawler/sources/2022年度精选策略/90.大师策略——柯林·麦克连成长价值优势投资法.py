# 克隆自聚宽文章：https://www.joinquant.com/post/35642
# 标题：大师策略——柯林·麦克连成长价值优势投资法
# 作者：BAFE

# 导入函数库
from jqdata import *

"""
在做投资时，柯林·麦克连特别重视六个比率：
每股销售成长率：公司过去和未来每股销售成长率能够增加。
现金流量：公司每年必需能够产生正的自由现金流量。
边际获利：寻找边际获利至少10至15%的公司。
可运用资本报酬率：经过调整的可运用资本报酬率至少达两位数。
税负：税负比低得不寻常的公司最可疑，代表该公司是资本密集产业，或是热衷购并，或是作帐技巧高明。
经济价值：发现市场价格低于其经济价值的股票，以高估/低估指数(股价营收比*边际获利乘数)低于1者为准。
选股标准
年度营收成长率> 前一年度营收成长率。
预估营收成长率> 年度营收成长率。
最近三年每股自由现金流量皆> 0。
近四季营业利益率>= 10 %。
最近四季可运用资本报酬率>= 10 %。
最近年度有效税率>= 5 %。
高估/低估指数(股价营收比*边际获利乘数) <= 1。
"""
# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')
    
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    
    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    # run_daily(before_market_open, time='before_open', reference_security='000300.XSHG') 
    #   # 开盘时或每分钟开始时运行
    run_monthly(market_open,  monthday=1, reference_security='000300.XSHG')
    #   # 收盘后运行
    # run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')
    
## 开盘前运行函数     
def before_market_open(context):
    pass
    
## 开盘时运行函数
# 每月开盘运行一次， 按照上一交易日的因子值进行调仓
def market_open(context):
    if context.current_dt.month in [5,9,11]:
        stock_list=cheek_stock(context)
        rebalance_position(context, stock_list)
    else:
        pass
 
def cheek_stock(context):
    # 根据当前时间，获取四个报告期的报告时间
    t1,t2,t3,t4=statDate_value(context)
    # 获取当前市场非ST，未停牌个股，作为初始股池
    temp_list = filter_st_paused(context)   
    # 1、年度营收成长率> 前一年度营收成长率。
    def REVENUE_value(i,date,stocks):
        df=get_fundamentals(query(
         indicator.code,
         indicator.inc_revenue_year_on_year
         ).filter(
            indicator.code.in_(stocks),
            indicator.inc_revenue_year_on_year>0,
                ),statDate=date)
        df.rename(columns={'inc_revenue_year_on_year':'inc_revenue_year_on_year'+str(i)},inplace=True)
        return df
    df11=REVENUE_value(1,t1,temp_list)
    df12=REVENUE_value(2,t2,temp_list)
    df1=df11.merge(df12,on='code')
    df1=df1[df1['inc_revenue_year_on_year1']>df1['inc_revenue_year_on_year2']]
    stock1=set(df1.code.values)
    print('stock1:%d'%len(stock1))
#  2、最近三年每股自由现金流量皆> 0。
    #  自由现金流=经营活动现金流净额-投资活动现金流出
    y =int(context.current_dt.year)
    if context.current_dt.month>=5:
        dt1,dt2,dt3=str(y-1),str(y-2),str(y-3)
    else:
        dt1,dt2,dt3=str(y-2),str(y-3),str(y-4)
    def FCF(i,date,stocks):
        df=get_fundamentals(query(
            cash_flow.code,
            cash_flow.net_operate_cash_flow,#经营活动现金流净额
            cash_flow.fix_intan_other_asset_acqui_cash,#subtotal_invest_cash_outflow
             ).filter(
            cash_flow.code.in_(stocks)
                ),statDate=date)
        df['fix_intan_other_asset_acqui_cash'].fillna(value=0,inplace=True)
        df['FCF']=df['net_operate_cash_flow']-df['fix_intan_other_asset_acqui_cash']
        df=df[df['FCF']>0]
        return set(df['code'].values)
    df21= FCF(1,dt1,stock1)
    df22= FCF(2,dt2,stock1)
    df23= FCF(3,dt3,stock1)
    stock2=list(df21&df22&df23)
    print('stock2:%d'%len(stock2))
    
    # 3、近四季营业利益率>= 10 %。
    def Operating_profit_margin(i,date,stocks):
        df=get_fundamentals(query(
            indicator.code,
            indicator.operation_profit_to_total_revenue
            ).filter(
            indicator.code.in_(stocks),
            indicator.operation_profit_to_total_revenue>10,
                ),statDate=date)
        return df
    df31= Operating_profit_margin(1,t1,stock2)
    df32= Operating_profit_margin(2,t2,stock2)
    df33= Operating_profit_margin(3,t3,stock2)
    df34= Operating_profit_margin(4,t4,stock2)
    stock3=list(set(df31['code'])&set(df32['code'])&set(df33['code'])&set(df34['code']))
    print('stock3:%d'%len(stock3))
    # 4、最近四季可运用资本报酬率>= 10 %。
    # 运用资本报酬率 =（税前和利息前利润总额+利息支出）/运用资本*100%
    # 运用资本（Capital Employed）经常可以用总资产减去流动负债来表示
    
    # def available_capital(i,date,stocks):
    #     df=get_fundamentals(query(
    #         indicator.code,
    #         income.net_profit,
    #         income.interest_income,
    #         income.interest_expense,
    #         income.income_tax_expense,
    #         balance.total_assets,
    #         balance.total_current_liability,
    #         ).filter(
    #         indicator.code.in_(stocks),
    #             ),statDate=date)
    #     df['a1']=df['net_profit']-df['interest_income']+df['interest_expense']+df['income_tax_expense']
    #     df['a2']=df['total_assets']-df['total_current_liability']
    #     df['ratio']=df['a1']/df['a2']
    #     dfx=df[['code','ratio']]
    #     dfx=dfx[dfx['ratio']>=0.05]
    #     return set(dfx['code'].values)
    # d41=available_capital(1,t1,stock3)
    # d42=available_capital(2,t2,stock3)
    # d43=available_capital(3,t3,stock3)
    # d44=available_capital(4,t4,stock3)
    # stock4=list(d41&d42&d43&d44)
    # print('stock4:%d'%len(stock4))
    
    #柯林．麦克连定义：营业利益/(股东权益+长期负债+一年内到期长期负债)。
    def available_capital_1(i,date,stocks):
        df=get_fundamentals(query(
            indicator.code,
            income.operating_profit,
            balance.total_owner_equities,
            balance.total_non_current_liability,
            balance.non_current_liability_in_one_year,
            ).filter(
            indicator.code.in_(stocks),
                ),statDate=date)
        df['non_current_liability_in_one_year'].fillna(value=0,inplace=True)#用0填充'non_current_liability_in_one_year'确实没有的。
        df['a1']=df['total_owner_equities']+df['total_non_current_liability']+df['non_current_liability_in_one_year']
        df['ratio'+str(i)]=df['operating_profit']/df['a1']
        dfx=df[['code','ratio'+str(i)]]
        return dfx
    d41=available_capital_1(1,t1,stock3)
    d42=available_capital_1(2,t2,stock3)
    d43=available_capital_1(3,t3,stock3)
    d44=available_capital_1(4,t4,stock3)
    df4=d41.merge(d42,on='code')
    df4=df4.merge(d43,on='code')
    df4=df4.merge(d44,on='code')
    df4['ratio']=df4['ratio1']+df4['ratio2']+df4['ratio3']+df4['ratio4']
    stock4=df4[df4['ratio']>=0.08]['code'].values
    print('stock4:%d'%len(stock4))
    
    # 5、最近年度有效税率>= 5 %。
    def effective_tax(date,stocks):
        df=get_fundamentals(query(
            indicator.code,
            income.total_profit,
            income.income_tax_expense,
            ).filter(
            indicator.code.in_(stocks),
                ),statDate=date)
        df['tax_ratio']=df['income_tax_expense']/df['total_profit']
        dfx=df[df['tax_ratio']>=0.05]
        return dfx.code.values
    stock5=effective_tax(dt1,stock4)
    print('stock5:%d'%len(stock5))
    return stock5
    
 ###################### 工具 ######################
"""
调仓：
先卖出持仓中不在 stock_list 中的股票
再等价值买入 stock_list 中的股票
"""
def rebalance_position(context, stock_list):
    current_holding = context.portfolio.positions.keys()
    stocks_to_sell = list(set(current_holding) - set(stock_list))
    # 卖出
    bulk_orders(stocks_to_sell, 0)
    total_value = context.portfolio.total_value

    # 买入
    if len(stock_list)==0:
        pass
    else:
        bulk_orders(stock_list, total_value/len(stock_list))

# 批量买卖股票
def bulk_orders(stock_list,target_value):
    for i in stock_list:
        order_target_value(i, target_value)

# 剔除停牌、st股
def filter_st_paused(context):
    temp_list = list(get_all_securities(types=['stock']).index)    
    #剔除停牌股
    all_data = get_current_data()
    temp_list = [stock for stock in temp_list if not all_data[stock].paused]
    #剔除st股
    temp_list = [stock for stock in temp_list if not all_data[stock].is_st]
    return temp_list
    
#时间日期处理
def statDate_value(context):
    dt=context.current_dt
    if 9>dt.month>=5:
        statDate1=str(dt.year)+'q1'
        statDate2=str(dt.year-1)+'q4'
        statDate3=str(dt.year-1)+'q3'
        statDate4=str(dt.year-1)+'q2'
    elif 11>dt.month>=9:
        statDate1=str(dt.year)+'q2'
        statDate2=str(dt.year)+'q1'
        statDate3=str(dt.year-1)+'q4'
        statDate4=str(dt.year-1)+'q3'
    elif dt.month>=11:
        statDate1=str(dt.year)+'q3'
        statDate2=str(dt.year)+'q2'
        statDate3=str(dt.year)+'q1'
        statDate4=str(dt.year-1)+'q4'
    else:
        statDate1=str(dt.year-1)+'q4'
        statDate2=str(dt.year-1)+'q3'
        statDate3=str(dt.year-1)+'q2'
        statDate4=str(dt.year-1)+'q1'
    return statDate1,statDate2,statDate3,statDate4
## 收盘后运行函数  
def after_market_close(context):
    pass
