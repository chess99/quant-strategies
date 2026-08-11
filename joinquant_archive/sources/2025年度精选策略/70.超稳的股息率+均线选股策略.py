# 克隆自聚宽文章：https://www.joinquant.com/post/27782
# 标题：超稳的股息率+均线选股策略
# 作者：策略人生

# 克隆自聚宽文章：https://www.joinquant.com/post/21179
# 标题：自带仓位控制的股息率策略，超稳
# 作者：只看年报来投资

# 导入函数库
from jqdata import *
import pandas as pd
import numpy as np
# 初始化函数，设定基准等等
def initialize(context):
    
    set_param()
    
    run_monthly(main,1,time='9:30')
    
def main(context):
    #1、设置大股票池,返回df，包括code、statDate
    df=getBigStocks()
    #2、财报质量控制,返回code,lrzl,yszzl,zcfzl,ejdtb,ejdhb
    df=controlReport(df)
    #3、设置下单列表
    setSmallStocks(df)
    #4、下单
    orderStock(context)

#1、设置大股票池,返回df，包括code、statDate    
def getBigStocks():
    stocks = get_index_stocks('000300.XSHG')
    q=query(
               income.statDate,
               income.code
             ).filter(
                #income.net_profit>100000000,
                valuation.pe_ratio>0,
                income.code.in_(stocks)#,
                #income.code.in_(['601918.XSHG','601899.XSHG','601958.XSHG','600170.XSHG',
                #    '600631.XSHE','600585.XSHG','600023.XSHG','000333.XSHE','002157.XSHE',
                #    '600104.XSHG'])
                 )
                 
    rets=get_fundamentals(q)#.reset_index(drop=True)
    return rets
def controlReport(df):
    df_qc=pd.DataFrame()
    for i in range(0,len(df)):
        statDate=df.loc[i].statDate
        q=int(int(statDate[5:7]) / 3)
        year=int(statDate[:4])
        statqs=[]
        for kk in range(0,12):
            statq=str(year) + 'q' + str(q)
            statqs.append(statq)
            q=q -1
            if q==0 : 
                q=4
                year= year - 1
        code=df.loc[i].code
        #只看现金分红
        gx=finance.run_query(query(finance.STK_XR_XD.bonus_amount_rmb,finance.STK_XR_XD.report_date).filter(
            finance.STK_XR_XD.code==code,
            finance.STK_XR_XD.report_date<=statDate
            ).order_by(finance.STK_XR_XD.report_date.desc()).limit(12))
       
        gx=gx.fillna(0)
        #统计分红
        one_year=0.0
        two_year=0.0
        three_year=0.0
        for j in range(0,len(gx)):
            report_date=gx.loc[j].report_date
            q=report_date.month//3
            year=report_date.year
            statq=str(year) + 'q' + str(q)
            if statq in (statqs[0],statqs[1],statqs[2],statqs[3]):
                one_year=one_year+gx.loc[j].bonus_amount_rmb
            if statq in (statqs[4],statqs[5],statqs[6],statqs[7]):
                two_year=two_year+gx.loc[j].bonus_amount_rmb
            if statq in (statqs[8],statqs[9],statqs[10],statqs[11]):
                three_year=three_year+gx.loc[j].bonus_amount_rmb
         #市值
        qcap=query(valuation.market_cap).filter(valuation.code==code)
        market_cap=get_fundamentals(qcap).loc[0,'market_cap']*10000 
        
        comp_value=market_cap*0.02
        if one_year>comp_value and two_year>comp_value*0.8 and three_year>comp_value*0.64 and (one_year+two_year+three_year)>market_cap*0.1:
            cc=pd.DataFrame([[code,one_year/market_cap,two_year/market_cap,three_year/market_cap]],columns=['code','gxl','gxl2','gxl3']) 
            df_qc=df_qc.append(cc,ignore_index=True)
    
 
    return df_qc.reset_index(drop=True)

def setSmallStocks(df):
    log.info(df.shape[0])
    if df.shape[0]<=g.stock_num*2: 
        g.bten=[]
        g.bfive=[]
        return 
    df=df.sort_values(by='gxl',ascending=False).head(g.stock_num*16)
    if len(df)<g.stock_num*4:
        df=df.head(len(df) -g.stock_num*2)
    df=df.sort_values(by='gxl2',ascending=False).head(g.stock_num*8)
    df=df.sort_values(by='gxl3',ascending=False).head(g.stock_num*4)
    df=df.sort_values(by='gxl',ascending=False).head(g.stock_num*2)
    #
    g.bten=list(df.head(g.stock_num*2)['code'])
    g.bfive=list(df.head(g.stock_num)['code'])
    #moreinfo(df)
def orderStock(context):
    
    bfive=g.bfive
    bten=g.bten
    
    all_value=context.portfolio.total_value
    for sell_code in context.portfolio.long_positions.keys():
        if sell_code not in bfive:
            #卖掉
            log.info('sell all:',sell_code)
            order_target_value(sell_code,0)
       
            
    for buy_code in bten:
        stock_hitory = attribute_history(buy_code,35,'1d',['close'])
        thirty_mean = stock_hitory['close'][-30:].mean()
        current_data = get_current_data()
        if buy_code not in context.portfolio.long_positions.keys():
            if current_data[buy_code].last_price >= thirty_mean: 
                cash_value=context.portfolio.available_cash
                buy_value=all_value/g.stock_num
        
                if cash_value > buy_value/2 :
                    log.info('buy:'+buy_code+'   ' +str(buy_value))
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


    
    
    
 
