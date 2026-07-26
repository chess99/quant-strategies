# 克隆自聚宽文章：https://www.joinquant.com/post/33126
# 标题：最新解密--追涨龙头打板策略-适合近期实盘行情
# 作者：GoodThinker

# 克隆自聚宽文章：https://www.joinquant.com/post/25562
# 标题：涨停板策略，只买涨停板
# 作者：小微微

# 导入函数库
from jqdata import *
from jqlib.technical_analysis import *
import datetime as dt
#欢迎一起交流学习，探索出打板策略
#作者：山背小微 2020-02-17

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
    g.count=30
    g.buy_stock_list=[] #记录每天筛选出来的股票
    g.max_number_stock=3
    g.stop_loss_per = 0.96 #允许跌4%
    g.stop_win = 0.6 #卖出止赢
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
      # 开盘时运行
    run_daily(market_open, time='09:33', reference_security='000300.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')
    
    run_daily(stop_win, time='14:50', reference_security='000300.XSHG')
    
    run_daily(stop_down_loss, time='9:40', reference_security='000300.XSHG')

def stop_down_loss(context):
    #判断盘中是不是高开低走，是就清仓
    if(len(context.portfolio.positions.keys())>0):
        for stock in context.portfolio.positions.keys():
             last_price_dict = get_current_data()
             current_price=last_price_dict[stock].last_price 
             closeable_amount = context.portfolio.positions[stock].closeable_amount
             if(closeable_amount>0):
                 df = get_price(stock, end_date=context.current_dt, frequency='daily', fields=['open'], skip_paused=True, fq='pre', count=1)
                 if df.empty:
                    continue
                 today_open_price = df['open'][0]
                 if(current_price<0.97*today_open_price):
                       sell_stock(stock,0)
                       log.info(str(get_security_info(stock).display_name)+"  盘中高开低走,卖出止损")
                 else:
                       log.info(str(get_security_info(stock).display_name)+"   盘中高开低走,不用止损")
                 
    
def print_stock_info(stock_list):
    if(stock_list is None):
        return
    if(len(stock_list)<0):
        return 
    for stock in stock_list:
        stock_name = get_security_info(stock).display_name
        log.info(str(stock)+ "   "+ str(stock_name))


def search_can_buy_stock(context):
    #寻找类似模塑科技那样的股票
    stock_list = Get_all_security_list(context)
    #寻找昨天涨停板股票
    up_limted_stock_list = find_predata_up_limted(context,stock_list)
    #筛选出昨天涨停板，并且昨日收盘价>5日移动平均线>10日移动平均线>20日移动平均线>60日移动平均线
    if(up_limted_stock_list is None):
        return None
    stock_list=[]
    for stock in up_limted_stock_list:
        ma_5 = MA(stock,context.previous_date,5,'1d')
        ma_10 = MA(stock,context.previous_date,10,'1d')
        ma_20 = MA(stock,context.previous_date,20,'1d')
        ma_60 = MA(stock,context.previous_date,60,'1d')
        df = get_price(stock, end_date=context.previous_date, frequency='daily', fields=['close'], skip_paused=True, fq='pre', count=1)
        if df.empty:
            continue
        pre_close_price = df['close'][0]
        if(pre_close_price>ma_5[stock] and ma_5[stock]>ma_10[stock] and ma_10[stock]>ma_20[stock] and ma_20[stock]>ma_60[stock]):
            stock_list.append(stock)
    
    return stock_list
    
    
    
## 开盘前运行函数
def before_market_open(context):
    g.buy_stock_list  = search_can_buy_stock(context)
    
def stop_loss(context):
    #开盘判断是否要止损,如果当前价格相对持仓成本跌了4% 或者当前价格相对昨日收盘价跌了4% 就止损
    if(len(context.portfolio.positions.keys())>0):
        for stock in context.portfolio.positions.keys():
             last_price_dict = get_current_data()
             current_price=last_price_dict[stock].last_price 
             closeable_amount = context.portfolio.positions[stock].closeable_amount
             cost_price = context.portfolio.positions[stock].avg_cost
             df = get_price(stock, end_date=context.previous_date, frequency='daily', fields=['close'], skip_paused=True, fq='pre', count=1)
             if df.empty:
                 continue
             pre_close_price = df['close'][0]
             if((closeable_amount>0 and current_price<g.stop_loss_per*pre_close_price) or(closeable_amount>0 and current_price<g.stop_loss_per*cost_price)):
                  sell_stock(stock,0)
                  log.info(str(get_security_info(stock).display_name)+"  开盘卖出止损")
             else:
                 log.info(str(get_security_info(stock).display_name)+"   开盘不用止损")
    
    
def buy_stock(context,stock):
    if(stock in  context.portfolio.positions.keys()):
           pass
    else:
           buy_value = context.subportfolios[0].total_value/g.max_number_stock
           if(context.subportfolios[0].available_cash>=buy_value):
                Order_object = order_value(stock, buy_value)
                if(Order_object is not None):
                    log.info( "买入股票:  "+str(get_security_info(stock).display_name) + "  买入价格：  "+str(Order_object.price)+"  买入数量: " +str(Order_object.amount)+" 成交金额: " +str(buy_value))
                
                else:
                    log.info(str(get_security_info(stock).display_name)+ ' ************* 下买单失败 **************') 
                   
           else:
                log.info("买入股票： "+str(get_security_info(stock).display_name)+ ' ************* 资金不足 **************')
    
def sell_stock(stock,stock_number):
        order_result=order_target(stock,stock_number)
        if(order_result is not None):
            log.info(str(get_security_info(stock).display_name)+' ------卖出成功----')
        else:
            log.info(str(get_security_info(stock).display_name)+ ' --------卖出失败--------')

## 开盘时运行函数
def market_open(context):
    #log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    stop_loss(context)  #开盘判断是否要止损
    #买股票
    if(g.buy_stock_list is None):
        return
    if(len(g.buy_stock_list)>0):
        code_len = len(g.buy_stock_list)
        if(code_len>g.max_number_stock):
            g.buy_stock_list = g.buy_stock_list[0:g.max_number_stock]
        if(check_position_number(context)==False):
            return
        for stock in g.buy_stock_list:
            if(check_position_number(context)==False):
               return
            buy_stock(context,stock)

def stop_win(context):
    #收盘价判断是否清除仓位
    if(len(context.portfolio.positions.keys())>0):
        for stock in context.portfolio.positions.keys():
             last_price_dict = get_current_data()
             current_price=last_price_dict[stock].last_price 
             closeable_amount = context.portfolio.positions[stock].closeable_amount
             cost_price = context.portfolio.positions[stock].avg_cost
             price_change = (current_price -cost_price)/cost_price
             df = get_price(stock, end_date=context.previous_date, frequency='daily', fields=['close'], skip_paused=True, fq='pre', count=1)
             if df.empty:
                 continue
             pre_close_price = df['close'][0]
             if(closeable_amount>0 and price_change>g.stop_win):
                  sell_stock(stock,0)
                  log.info(str(get_security_info(stock).display_name)+"  卖出止赢")
                  
             elif(closeable_amount>0 and current_price<g.stop_loss_per*pre_close_price):
                  sell_stock(stock,0)
                  log.info(str(get_security_info(stock).display_name)+"  跌破昨日收盘价4%,尾盘卖出")
             else:
                 log.info(str(get_security_info(stock).display_name)+"   尾盘没有卖出操作")

def check_position_number(context):
    #检查持仓数量，决定是否买入新股票
    stock_number = len(context.portfolio.positions.keys())
    if(stock_number==g.max_number_stock):
        log.info('持仓已满，不再买入新股票')
        return False
    else:
        return True
           
## 收盘后运行函数
def after_market_close(context):
    #log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    pass
    
def Get_all_security_list(context):
    security_list=[]
    stocks = list(get_all_securities(['stock']).index)
    for stock in stocks:
         security_obj = get_security_info(stock)
         if(str(security_obj.type) == 'stock'):
             if(context.current_dt.date()<security_obj.end_date and security_obj.start_date<context.current_dt.date()):#过滤掉退市的公司和相关新股
                     security_list.append(stock)
             else:
                     pass
         else:
             log.info('不是股票类型') 
             
    #log.info('包括停牌在内所有公司数量 = ',len(security_list))
    ####
    security_list = filter_st_and_paused(security_list)
    
    #log.info('去除ST和停牌的公司数量： ',len(security_list)) 
    
    security_list = filter_kc_ban(security_list)
    
    #log.info('去除科创板的公司数量： ',len(security_list)) 
    
    #security_list = filter_gem_stock(security_list)
    
    #log.info('去除创业板的公司数量： ',len(security_list)) 
    
    security_list =filter_new(context,security_list,g.count)
    
    #log.info('去除上市不足30天的数量： ',len(security_list)) 
    
    security_list = industry_filter(context, security_list, g.industry_list)
    
    return security_list

    
def filter_new(context, equity, deltaday):
    deltaDate = context.current_dt.date() - dt.timedelta(deltaday)

    tmpList = []
    for stock in equity:
        if get_security_info(stock).start_date < deltaDate:
            tmpList.append(stock)

    return tmpList  
    
def filter_st_and_paused(stock_list):
     current_data = get_current_data()
     retult_list=[]
     for stock in stock_list:
         if( not current_data[stock].is_st and not current_data[stock].paused):
             retult_list.append(stock)
     return retult_list
     


def filter_kc_ban(stock_list):
    #过滤科技板
    return [stock for stock in stock_list if stock[0:3] != '688']
    
#过滤创业板    
def filter_gem_stock(stock_list):
    return [stock for stock in stock_list if stock[0:3] != '300']    
    
#查找昨天是不是涨停板：
def find_predata_up_limted(context , stock_list):
    if(len(stock_list)<0):
        return None
    df_data = get_price(stock_list, end_date=context.previous_date, frequency='daily', fields=['close', 'high_limit','low_limit'], skip_paused=True, fq='pre', count=1, panel=False)
    ##
    df = df_data[df_data['high_limit']==df_data['close']]
    up_limit_list = df.code.values.tolist()          
    return up_limit_list  


industry_list1 = ["801010","801020","801030","801040","801050","801080","801110","801130","801140","801150","801160","801170","801180","801200","801210","801230","801710","801720","801730","801740","801750","801760","801770","801780","801790","801880","801890"]
industry_list2 = ["801080","801110","801130","801140","801150","801200","801210","801230","801730","801740","801750","801760","801770","801880","801890"]
g.industry_list= list(set(industry_list1).union(set(industry_list2)))
def industry_filter(context, security_list, industry_list):
    if len(industry_list) == 0:
        # 返回股票列表
        return security_list
    else:
        securities = []
        for s in industry_list:
            temp_securities = get_industry_stocks(s)
            securities += temp_securities
        security_list = [stock for stock in security_list if stock in securities]
        # 返回股票列表
        return security_list
        
    
    
 
    
    
  
