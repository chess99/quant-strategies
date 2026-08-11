# 克隆自聚宽文章：https://www.joinquant.com/post/24224
# 标题：RSRS择时+货币基金--6年8倍行业周期股策略
# 作者：南开小楼

# 克隆自聚宽文章：https://www.joinquant.com/post/22062
# 标题：稳定高回报周期股策略
# 作者：只看年报来投资

# 导入函数库
import statsmodels.api as sm
from pandas.stats.api import ols
from jqdata import *
import pandas as pd
import numpy as np
import datetime 
# 初始化函数，设定基准等等
def initialize(context):
    
    set_param()
    set_parameter(context)
    
    run_monthly(main,1,time='9:30')
    
def handle_data(context, data):
    security = g.security
    # 填入各个日期的RSRS斜率值
    beta=0
    r2=0
    if g.init:
        g.init = False
    else:
        #RSRS斜率指标定义
        prices = attribute_history(security, g.N, '1d', ['high', 'low'])
        highs = prices.high
        lows = prices.low
        X = sm.add_constant(lows)
        model = sm.OLS(highs, X)
        beta = model.fit().params[1]
        g.ans.append(beta)
        #计算r2
        r2=model.fit().rsquared
        g.ans_rightdev.append(r2)
    # 计算标准化的RSRS指标
    section = g.ans[-g.M:]
    # 计算均值序列
    mu = np.mean(section)
    # 计算标准化RSRS指标序列
    sigma = np.std(section)
    zscore = (section[-1]-mu)/sigma  
    #计算右偏RSRS标准分
    zscore_rightdev= zscore*beta*r2
    # 如果上一时间点的RSRS斜率大于买入阈值, 则全仓买入
    if zscore_rightdev > g.buy:# and corrcoef(array([trade_vol10['volume'], g.RSRS_stdratio_rev_list[:context.previous_date].tail(10)]))[0,1] > 0and MA20>MA20_2:
        # 记录这次买入
        log.info("市场风险在合理范围")
        #满足条件运行交易
        if '511880.XSHG' in context.portfolio.positions.keys():
            order_target('511880.XSHG', 0)
        orderStock(context)
    # 如果上一时间点的RSRS斜率小于卖出阈值, 则空仓卖出
    elif (zscore_rightdev < g.sell) and (len(context.portfolio.positions.keys()) > 0):
        # 记录这次卖出
        log.info("市场风险过大，保持空仓状态")
        
        # 卖出所有股票,使这只股票的最终持有量为0
        sell_list = set(context.portfolio.positions.keys()) - set(g.etf_list)
        print(sell_list)
        #sell_list = set(context.portfolio.positions.keys()) - set('511880.XSHG')
        #for sell_code in context.portfolio.positions.keys():
        for sell_code in sell_list:
            log.info('sell all:',sell_code)
            order_target(sell_code, 0)
        cash_value=context.portfolio.available_cash
        print(('cash',cash_value))
        order_target('511880.XSHG',cash_value)
def main(context):
    #1、设置大股票池,返回df，包括code、statDate
    df=getBigStocks()
    #2、质量控制,
    df=controlReport(df,context)
    #3、进一步过滤或排序
    setSmallStocks(df)
    #4、下单
    #orderStock(context)
    
def getBigStocks():
    
    #银行、房地产             
    notcall=finance.run_query(query(finance.STK_COMPANY_INFO.code).filter(
            finance.STK_COMPANY_INFO.industry_id.in_(['J66','J67','J68','J69','K70'])
            )
        )
    q=query(
               income.statDate,
               income.code
             ).filter(
                income.net_profit>0,
                #income.code.in_(stocks),
                ~income.code.in_(list(notcall['code']))
                 )
    rets=get_fundamentals(q)

    rets.index=rets.code
    del rets['code']
    return rets
def controlReport(df,context):
    s=df.statDate
    df_return=pd.DataFrame()
    #log.info('All num',len(s))
    
    #0.PE<25
    q_cap=query(valuation.code,valuation.pe_ratio,valuation.market_cap).filter(valuation.code.in_(list(df.index)))
    df_cap=get_fundamentals(q_cap)
    df_cap=df_cap[(df_cap['pe_ratio']<25) & (df_cap['pe_ratio']>0)]
    ll=list(df_cap.code)
    s=s[ll]
    #log.info('After PE num',len(s))
    #1、上市天数>500
    compinfo=finance.run_query(query(
        finance.STK_LIST.code,
        finance.STK_LIST.name,
        finance.STK_LIST.start_date
        ).filter(finance.STK_LIST.code.in_(ll)))
    td=datetime.date(context.current_dt.year,context.current_dt.month,context.current_dt.day)
    compinfo.index=compinfo.code
    s_com=compinfo.start_date
    ll=[code for code in s.index if (td -s_com[code]).days>500 ]
    log.info('After days',len(ll))
    
    #负债率
    q_profit=query(balance.code,balance.statDate,
                    balance.total_liability,balance.total_assets
            ).filter(balance.code.in_(ll))
    df_profit=get_fundamentals(q_profit)
    df_profit=df_profit[df_profit['total_liability']/df_profit['total_assets']<0.9]
    ll=list(df_profit.code)
    s=s[ll]
    #log.info('after fzbl:',len(s))
    
    fin_data=get_fin_data(s,6)
    df_fin=pd.concat(fin_data)
    for code in list(s.index):
        # rets=df_fin[df_fin['code']==code].sort_values(by='statDate',ascending=False).reset_index(drop=True)
        rets=df_fin[df_fin['code']==code].sort(['statDate'],ascending=False).reset_index(drop=True)

        if len(rets)<6 :continue 
        if min(rets.adjusted_profit)<=0 or min(rets.operating_revenue)<=0:continue 
        #1.应收账款周转率>6
        year_operating_revenue=sum(rets.operating_revenue[0:4]) #年营业收入
        bill_receivable=np.mean(rets.bill_receivable[0:4])
        account_receivable=np.mean(rets.account_receivable[0:4])
        advance_peceipts=np.mean(rets.advance_peceipts[0:4])
        receivable=bill_receivable+account_receivable - advance_peceipts
        if receivable<=0:
            yszkzzl=100
        else:
            yszkzzl=year_operating_revenue/receivable  #应收周转率
        if yszkzzl<=6:continue
    
        #4、两个季度加起来的同比和环比
        ejd=rets.loc[0,'adjusted_profit']+rets.loc[1,'adjusted_profit']
        hb=ejd/(rets.loc[2,'adjusted_profit']+rets.loc[3,'adjusted_profit'])
        tb=ejd/(rets.loc[4,'adjusted_profit']+rets.loc[5,'adjusted_profit'])

        profit=sum(rets.adjusted_profit[0:4])
        cc=pd.DataFrame([[code,hb,tb,profit]],columns=('code','hb','tb','profit'))
        df_return=df_return.append(cc)
    


    return df_return
    
def setSmallStocks(df_pe):
    if len(df_pe)<=0:return
    #5、PE<20
    q_cap=query(valuation.code,valuation.market_cap).filter(valuation.code.in_(list(df_pe.code)))
    df_cap=get_fundamentals(q_cap)
    df_pe=df_pe.merge(df_cap)
    df_pe['pe']=df_pe['market_cap']*100000000/df_pe['profit']
    df_pe=df_pe[(df_pe['pe']<20) & (df_pe['pe']>0)]

    df_pe=df_pe.sort(['pe'],ascending=True).reset_index(drop=True)
    df_pe['pes']=100 - df_pe.index*100/len(df_pe)
    
    df_pe=df_pe.sort(['hb'],ascending=False).reset_index(drop=True)
    df_pe['hbs']=100 - df_pe.index*100/len(df_pe)
    df_pe=df_pe.sort(['tb'],ascending=False).reset_index(drop=True)
    df_pe['tbs']=100 - df_pe.index*100/len(df_pe)
    
    df_pe['s']=df_pe['pes']*1.0+df_pe['hbs']*0.5+df_pe['tbs']*0.4
    df_pe=df_pe.sort(['s'],ascending=False).reset_index(drop=True)
    #log信息
    df_pe=df_pe[['code','hb','tb','pe']]
    #moreinfo(df_pe)
    
    g.bten=list(df_pe.head(g.stock_num*2)['code'])
    g.bfive=list(df_pe.head(g.stock_num)['code'])

def orderStock(context):
  
    bfive=g.bfive
    bten=g.bten

    all_value=context.portfolio.total_value
    
    for sell_code in context.portfolio.long_positions.keys():
        if sell_code not in bten:
            #卖掉
            log.info('sell all:',sell_code)
            order_target_value(sell_code,0)
        #else:
        #    log.info('sell part:',sell_code)
        #    order_target_value(sell_code,all_value/g.stock_num)
            
    for buy_code in bten:
        if buy_code not in context.portfolio.long_positions.keys():
            cash_value=context.portfolio.available_cash
            buy_value=all_value/g.stock_num
            
           
            if cash_value > buy_value/3 :
                log.info('buy:'+buy_code+'   ' +str(buy_value)+'   ' +str(buy_value))
                    
                order_target_value(buy_code,buy_value)
                       
def set_param():
    g.bten=[]
    g.bfive=[]
    g.stock_num = 5
    g.fin=pd.DataFrame()
     #显示所有列
    pd.set_option('display.max_columns', None)
    #显示所有行
    pd.set_option('display.max_rows', None)
    #设置value的显示长度为100，默认为50
    pd.set_option('max_colwidth',100)
   

    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')
    
     ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
def set_parameter(context):
    # 设置RSRS指标中N, M的值
    #统计周期
    g.N = 18
    #统计样本长度
    g.M = 1100
    #首次运行判断
    g.init = False
    g.etf_list = ['511880.XSHG']
    #风险参考基准
    g.security = '000300.XSHG'
    # 设定策略运行基准
    set_benchmark(g.security)
    #记录策略运行天数
    g.days = 0
    # 买入阈值
    g.buy = 0.7
    g.sell = -0.7
    #用于记录回归后的beta值，即斜率
    g.ans = []
    #用于计算被决定系数加权修正后的贝塔值
    g.ans_rightdev= []
    g.blacklist = [
        #'''
        "002807.XSHE","600036.XSHG","600908.XSHG","601229.XSHG","002142.XSHE",
        "600000.XSHG","600016.XSHG","601166.XSHG","600926.XSHG","601128.XSHG","002839.XSHE",
        "600919.XSHG","600015.XSHG","601988.XSHG","601998.XSHG","601939.XSHG","601997.XSHG",
        "601169.XSHG","000001.XSHE","601818.XSHG","601328.XSHG","601398.XSHG","601288.XSHG",
        "601009.XSHG","603323.XSHG"
        #'''
        ]   
    # 计算2005年1月5日至回测开始日期的RSRS斜率指标
    # 获得回测前一天日期，千万避免未来数据
    previous_date = context.current_dt - datetime.timedelta(days=2)
    prices = get_price(g.security, '2005-01-05', previous_date, '1d', ['high', 'low'])
    highs = prices.high
    lows = prices.low
    g.ans = []
    for i in range(len(highs))[g.N:]:
        data_high = highs.iloc[i-g.N+1:i+1]
        data_low = lows.iloc[i-g.N+1:i+1]
        X = sm.add_constant(data_low)
        model = sm.OLS(data_high,X)
        results = model.fit()
        g.ans.append(results.params[1])
        #计算r2
        g.ans_rightdev.append(results.rsquared)
    
def  moreinfo(df):
    codes=list(df.code)
    
    compinfo=finance.run_query(query(
        finance.STK_LIST.code,
        finance.STK_LIST.name,
        finance.STK_LIST.start_date
        ).filter(finance.STK_LIST.code.in_(codes)))
    stock_score=pd.merge(df,compinfo)
    log.info(stock_score)
    
def get_fin_data(s,period):
    stat_date_stocks = { sd:[stock for stock in s.index if s[stock]==sd] for sd in set(s.values) }
    qt= query(
                income.statDate,
                income.code,
                income.operating_revenue, #营业收入
                indicator.adjusted_profit,#扣非净利润
                balance.bill_receivable,#应收票据
                balance.account_receivable,#应收账款
                balance.advance_peceipts,#预收账款
                cash_flow.net_operate_cash_flow,#经营现金流
                cash_flow.fix_intan_other_asset_acqui_cash,#购固取无
                balance.total_assets,# 资产总计
                balance.total_liability,# 负债合计
                balance.shortterm_loan,#“短期借款”
                balance.longterm_loan,#“长期借款”
                balance.non_current_liability_in_one_year,#“一年内到期的非流动性负债”
                balance.bonds_payable#“应付债券”、
                )
    ret_data=[]
    #分别取多期数据
    for i in range(0,period):
        one_period=pd.DataFrame()
        for stat_date in stat_date_stocks.keys():
            statq=popStatQ(stat_date,i)
            lqt=qt.filter(balance.code.in_(stat_date_stocks[stat_date]))
            oneData=get_fundamentals(lqt,statDate=statq)
            if len(oneData)>0:one_period=one_period.append(oneData)
        one_period=one_period.fillna(0)
        if len(one_period)>0:ret_data.append(one_period)
    return ret_data
    
#往前推期数，得到q
def popStatQ(stat_date,num) :

    year=int(stat_date[:4])
    q=int(stat_date[5:7])//3
    q-=num
    while q<=0:
        q+=4
        year -=1
    return str(year)+'q'+str(q)
        
  
   

