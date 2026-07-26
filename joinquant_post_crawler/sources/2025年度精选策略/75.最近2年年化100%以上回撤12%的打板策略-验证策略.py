# 克隆自聚宽文章：https://www.joinquant.com/post/28552
# 标题：最近2年年化100%以上回撤12%的打板策略-验证策略
# 作者：大思维者

# enable_profile()
# 作者：大思维者
# 微信：DSWZ1990
# 导入函数库


# from __future__ import division #用于/相除的时候,保留真实结果.小数，python2专用
from jqdata import *
import json #Python2 输出中文列表使用


# # 触及涨停打板----验证策略，首板策略思路

# 1）股票池：前3天不涨停，前三天至少一天主力吸筹（均线涨幅大于3%）
# 2),11::30筛选上午股票池中触及涨停的股票，按触及涨停时间排序
# 3）把11:30选出的股票列表，按卖出时间分成两部分,记录股票，离开盘涨停分钟数组成列表，before_selling_list，after_selling_list
#         卖出之前：计算可以买的数量（最大持仓数-开盘持仓数），按顺序买入before_selling_list中的股票
#         卖出之后：按持仓数量g.number_of_positions，按顺序买after_selling_list中的股票
# 4）每天十点判断一次卖出，没涨停的卖出，涨停的留到下一天



# 初始化函数，设定基准等等
def initialize(context):
    set_benchmark('000001.XSHG')# 设定上证作为基准
    set_option('use_real_price', True)# 开启动态复权模式(真实价格)
    log.info('初始函数开始运行且全局只运行一次')# 输出内容到日志 log.info()
    log.set_level('order', 'error') # 过滤掉order系列API产生的比error级别低的log
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')# 手续费是：买入万三，卖出万三加千分之一印花税, 最低扣5块钱
    set_option("match_by_signal", True)  # 强制撮合，仅支持限价单。
    set_option("avoid_future_data", True) # 避免未来数据
    g.buy_list=[]
    g.minute=60 # 卖出里开盘分钟数
    g.buy_stock_count=10  # 最大持仓数量
    g.limit_lists=[] # 筛序出的触及涨停股票列表
    g.position_count=[] #卖出以后持仓数
    g.number_of_positions=0 # 初始持仓数量0
    
# 替换代码
def after_code_changed(context):

    unschedule_all()
    # 开盘前运行
    run_daily(before_open, '9:30')
    run_daily(Screening_stock_purchases, '11:30')
    # run_daily(buy, '15:00')
    run_daily(sell, '10:30')
    
# 开盘前数据获取    
def before_open(context):
    g.open_positions=len(context.portfolio.positions) #开盘前持仓数量
    
    g.open_time=context.current_dt #开盘时间
    log.info('===================================================')
    log.info('开盘持仓数：',g.open_positions)
# 筛选股票买入    
def Screening_stock_purchases(context):
    
    QA=list(get_all_securities().index)# 全A股列表
    QA= filter_specials(context,QA) #过滤科创板，ST，停牌，退市，上市半年内的新股,1元股,99元以上股
    QA=No_limit_for_three_days(context,QA) # 前3天不涨停
    QA=attracting_funds(context,QA) #主力吸筹
    log.info('')
    log.info('今日筛选股票池数量：',len(QA))
    QA=zt(context,QA) # 上午触及涨停的
    log.info('上午触及涨停数量：',len(QA))
    
    before_selling_list=before_selling(context,QA,g.minute,g.limit_lists)#卖出之前触及涨停的
    log.info('卖出时间之前：数量：%s'%len(before_selling_list),before_selling_list)
    before_selling_list=before_selling_list[:g.buy_stock_count-g.open_positions]  #卖出之前触及涨停的，取（最大持仓数-开盘持仓）个买入
    
    
    after_selling_list=after_selling(context,QA,g.minute,g.limit_lists) #卖出之后触及涨停的
    log.info('卖出时间之后：数量：%s'%len(after_selling_list),after_selling_list)

    for stock_and_time in before_selling_list:
        if g.number_of_positions<10:
            
            buy(context,stock_and_time)
            g.number_of_positions+=1
            log.info('当前持仓数量：',g.number_of_positions,stock_and_time)
    for stock_and_time in after_selling_list:
        if g.number_of_positions<10:
            
            buy(context,stock_and_time)   
            g.number_of_positions+=1     
            log.info('持仓数量：',g.number_of_positions,stock_and_time)


  
def before_selling(context,stock_list,minute,limit_lists): # 卖出前可买列表及触及涨停时间离开盘分钟数
    lists=[]
    for stock_and_time in limit_lists: # 触及涨停股票和触及涨停离开盘分钟数
        if stock_and_time[0] in stock_list:
            if stock_and_time[-1]<minute:
                lists.append(stock_and_time) # 卖出时间前涨停的
    stock_list=lists
    stock_list=sorted(stock_list, key=lambda y:y[-1], reverse = False) # 涨停时间顺序，从小到大
    
    return stock_list
    
def after_selling(context,stock_list,minute,limit_lists):  #卖出后可买列表及触及涨停时间离开盘分钟数
    lists=[]
    for stock_and_time in limit_lists: # 触及涨停股票和触及涨停离开盘分钟数
        if stock_and_time[0] in stock_list:
            if stock_and_time[-1]>=minute:
                lists.append(stock_and_time) # 卖出时间前涨停的
    stock_list=lists
    stock_list=sorted(stock_list, key=lambda y:y[-1], reverse = False) # 涨停时间顺序，从小到大
    return stock_list  
    
# 股票代码列表=》股票名称列表
def stock_name(lists):
    a=[]
    for i in lists:
        a.append(get_security_info(i).display_name)
    lists =json.dumps(a,ensure_ascii=False)   
    return lists  

# 买入股票
def buy(context,stock_and_time):
    # log.info(stock_and_time)
    g.zzc=round(context.portfolio.total_value,2) # 获取总资产
    high_limit=get_current_data()[stock_and_time[0]].high_limit
    limit_time=g.open_time+datetime.timedelta(minutes=stock_and_time[-1])
    
    order_value(stock_and_time[0], g.zzc/g.buy_stock_count,LimitOrderStyle(high_limit)) # 实盘，按股数下单
    log.info(limit_time,"买入股票：%s "%get_security_info(stock_and_time[0]).display_name,stock_and_time[0],"下单后，剩余资金：",round(context.portfolio.cash,2),"第%s分钟检测到触及涨停"%stock_and_time[1])
    

# 卖出股票,不涨停卖出
def sell(context):
    if len(context.portfolio.positions)!=0:
        # log.info(context.current_dt,"可用资金：",round(context.portfolio.cash,2))
        for position in list(context.portfolio.long_positions.values()):
            mc=get_security_info(position.security).display_name# 股票，名称
            cccb = round(context.subportfolios[0].long_positions[position.security].acc_avg_cost,2)#持仓成本
            day_open=get_current_data()[position.security].day_open
            last_price=get_current_data()[position.security].last_price
            low_limit=get_current_data()[position.security].low_limit
            high_limit=get_current_data()[position.security].high_limit
            sl=context.portfolio.positions[position.security].total_amount# 持仓数量
            if position.closeable_amount>0  and high_limit != last_price:# 可卖数量大于0，不涨停卖出
                
                order_target_value(position.security, 0,LimitOrderStyle(last_price))
                g.number_of_positions+=-1
                log.info("卖出股票：%s  "%get_security_info(position.security).display_name,position.security,'最新价格：%s'%last_price,'个股盈亏：%s'%round((((last_price-cccb)*100/cccb)-0.15),2)+'%')
                log.info('当前持仓数量：',g.number_of_positions)
            else:
                log.info("涨停！继续持有==》》%s   "%get_security_info(position.security).display_name,position.security,'最新价格：%s'%last_price,'个股盈亏：%s'%round((((last_price-cccb)*100/cccb)-0.15),2)+'%')
                log.info('当前持仓数量：',g.number_of_positions)
    g.position_count=len(context.portfolio.positions)
    log.info('卖出以后持仓数量：',g.position_count)
    
# 3天中主力必须吸筹1天以上。判断主力吸条件：均线大于昨天收盘价的1.03
def attracting_funds(context,stock_list):
    stock_avg=history(3, unit='1d', field='avg', security_list=stock_list, df=False, skip_paused=True, fq='pre')
    stock_close=history(4, unit='1d', field='close', security_list=stock_list, df=False, skip_paused=True, fq='pre')
    stock_list = [stock for stock in stock_list  if
                    stock_avg[stock][-1]>=stock_close[stock][-2]*1.03
                    or stock_avg[stock][-2]>=stock_close[stock][-3]*1.03
                    or stock_avg[stock][-3]>=stock_close[stock][-4]*1.03
                ]
    return   stock_list         

# 前三天不涨停
def No_limit_for_three_days(context,stock_list):
    stock_close=history(3, unit='1d', field='close', security_list=stock_list, df=False, skip_paused=True, fq='pre')
    stock_high_limit=history(3, unit='1d', field='high_limit', security_list=stock_list, df=False, skip_paused=True, fq='pre')
    stock_list = [stock for stock in stock_list if stock_close[stock][-1] != stock_high_limit[stock][-1]]
    stock_list = [stock for stock in stock_list if stock_close[stock][-2] != stock_high_limit[stock][-2]]
    stock_list = [stock for stock in stock_list if stock_close[stock][-3] != stock_high_limit[stock][-3]]
    return   stock_list

                
# 筛序盘中触及涨停的
def zt(context,stock_list):

    stock_high=history(120, unit='1m', field='high', security_list=stock_list, df=False, skip_paused=True, fq='pre') 
    stock_list = [stock for stock in stock_list if stock_high[stock].max()==get_current_data()[stock].high_limit]# 最高价等于涨停价，筛选触及涨停的股票
    
    # log.info('stock_list',stock_list) 

    lists=[] # 股票列表初始化
    g.limit_lists=[] # 股票+触及涨停离开盘分钟数
    for stock in stock_list:
        for i in range(0,120): # 120个分钟最高价，等于涨停价低位置确定触及涨停的时间
            if stock_high[stock][i]==get_current_data()[stock].high_limit:
                lists.append(stock)
                g.limit_lists.append([stock,i+1])
                break
    # log.info('股票代码及触及涨停离开盘的分钟数',g.limit_lists)        
    stock_list=lists   
    return   stock_list
    
# 过滤器，过滤停牌，ST，科创，新股，1元股，一字板（可选择过滤）
def filter_specials(context,stock_list):
    curr_data = get_current_data()
    stock_list=[stock for stock in stock_list if stock[0:3] != '688'] #过滤科创板'688' 
    # stock_list=[stock for stock in stock_list if stock[0:3] != '300'] #过滤创业板'300' 
    stock_list = [stock for stock in stock_list if not curr_data[stock].is_st]
    stock_list = [stock for stock in stock_list if not curr_data[stock].paused] 
    stock_list = [stock for stock in stock_list if 'ST' not in curr_data[stock].name]
    stock_list = [stock for stock in stock_list if '*'  not in curr_data[stock].name]
    stock_list = [stock for stock in stock_list if '退' not in curr_data[stock].name]
    stock_list = [stock for stock in stock_list if  curr_data[stock].day_open>1] # 过滤一元股
    
    stock_list = [stock for stock in stock_list if  curr_data[stock].high_limit<99] # 过滤99以上元股
    stock_list = [stock for stock in stock_list if curr_data[stock].day_open!= curr_data[stock].high_limit] # 过滤一字板
    return   stock_list  
