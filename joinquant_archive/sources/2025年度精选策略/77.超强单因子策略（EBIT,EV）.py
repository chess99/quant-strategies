# 克隆自聚宽文章：https://www.joinquant.com/post/24809
# 标题：超强单因子策略（EBIT/EV）
# 作者：乌龟赛跑7

# 导入函数库
from jqdata import *
from jqdata import finance
import time
import datetime
import pandas as pd
from jqfactor import get_factor_values

#显示所有列
pd.set_option('display.max_columns', None)

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
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')


      # 开盘前运行
    run_monthly(before_market_open, monthday=1,time='before_open', reference_security='000300.XSHG')
    
      #开盘时运行
    run_monthly(market_open, monthday=1,time='open', reference_security='000300.XSHG')
    
      # 收盘后运行
    run_monthly(after_market_close,monthday=1, time='after_close', reference_security='000300.XSHG')
    
    #定义交易月份
    g.Transfer_date=list(range(1,13,1))



# 定义获取EBIT/EV且按照从大到小排列的函数；

def get_EBIT_EV(security,watch_date):

    #获取相关数据并形成dataframe
    factor_data = get_factor_values(securities=security, \
                                    factors=['market_cap','financial_liability','financial_assets','EBIT'], end_date=watch_date,count=1)

    df_factor_data=pd.concat([factor_data['market_cap'].T,factor_data['financial_liability'].T,factor_data['financial_assets'].T,factor_data['EBIT'].T],axis=1)

    col1=['market_cap','financial_liability','financial_assets','EBIT']
    df_factor_data.columns=col1

    #计算EBIT/EV
    df_factor_data['EV']=df_factor_data['market_cap']+df_factor_data['financial_liability']-df_factor_data['financial_assets']
    df_factor_data['EBIT/EV']=df_factor_data['EBIT']/df_factor_data['EV']
    

    # 股票代码列表
    stock_list=df_factor_data.index.tolist()
    

    #获取上市日期、证券简称；
    q=query(finance.STK_LIST.code,finance.STK_LIST.name,finance.STK_LIST.start_date).filter(finance.STK_LIST.code.in_(stock_list))
    df=finance.run_query(q)
    df1=df.set_index('code')
    

    df_list=pd.concat([df_factor_data,df1],axis=1,sort=False)
    
     #以EBIT/EV进行排名
    df_list1=df_list.sort_values(by=['EBIT/EV'],ascending=False)


    return df_list1



## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    #log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))

    # 给微信发送消息（添加模拟交易，并绑定微信生效）
    # send_message('美好的一天~')
    
    
    #获取前一个交易日的日期
    previous_day=context.previous_date

        
    # 获取要操作行业的股票代码列表
    g.security = get_index_stocks('000001.XSHG',date=context.previous_date)+get_index_stocks('399001.XSHE',date=context.previous_date)
    
     #建立一个空字典，用来记录买入股票的开仓日期；
    g.entry_dates={code: None for code in g.security}
    
    
    # 获取EBIT/EV的估值数据列表
    EBIT_to_EV_list=get_EBIT_EV(security=g.security,watch_date=previous_day)
    
    g.buy_list=EBIT_to_EV_list.iloc[0:50].index.tolist()
    



## 开盘时运行函数
def market_open(context):
    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
  
   #获取当前交易日期的月份
    current_month=context.current_dt.month
    
    if current_month in g.Transfer_date:
      
        #买入股票列表
        buy_list=g.buy_list
        
        #简记当前组合
        p=context.portfolio
        
        # 获取当前时间数据
        cur_data=get_current_data()
        
        #获取当前交易日期
        current_day=context.current_dt
        
     
        # 卖出股票
        for  code in list(p.positions.keys()):
            if code  not in  buy_list:
                if cur_data[code].paused:
                    continue
                # 卖出股票
                order_target_value(code, 0)
                
            else:
                open_price=cur_data[code].day_open
                num_to_target=(p.total_value/len(buy_list))/open_price//100*100
                order_target(code,num_to_target)
                
                
        #买入股票
        for code in buy_list:
            if code not in p.positions:
                if cur_data[code].paused:
                    continue
                open_price=cur_data[code].day_open
                num_to_buy=(p.total_value/len(buy_list))/open_price//100*100
                # 买入股票
                order_target(code, num_to_buy)
                
                #记录建仓日期
                g.entry_dates[code]=current_day
                
   
   
   

## 收盘后运行函数
def after_market_close(context):
    #获取当前交易的日期
    current_month=context.current_dt.month
    p=context.portfolio
    pos_level=p.positions_value/p.total_value
    record(pos_level=pos_level)
