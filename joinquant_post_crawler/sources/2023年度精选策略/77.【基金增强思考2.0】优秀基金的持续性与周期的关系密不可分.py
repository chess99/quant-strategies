# 克隆自聚宽文章：https://www.joinquant.com/post/34966
# 标题：【基金增强思考2.0】优秀基金的持续性与周期的关系密不可分
# 作者：潜水的白鱼

# 克隆自聚宽文章：https://www.joinquant.com/post/34957
# 标题：【基金增强思考1】好的基金是否具有持续性
# 作者：潜水的白鱼

# 导入函数库
from jqdata import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option("use_real_price", True)
    log.set_level('order', 'error')
    log.set_level('system', 'error')
    ### 场外基金相关设定 ###
    # 设置账户类型: 场外基金账户
    set_subportfolios([SubPortfolioConfig(context.portfolio.cash, 'open_fund')])
    # 设置赎回到账日
    set_redeem_latency(3, 'QDII_fund')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
        # 开盘时运行
    
    run_monthly(market_open_sell,1,time='open', reference_security='000300.XSHG')
    
    run_monthly(market_open_buy, 5,time='open', reference_security='000300.XSHG')

    g.adjustpositions = False #把开关闭上
    g.days = 180
    g.num = 30
    g.monthnum = 0 #三个月轮回一次，
   
    
    
def market_open_sell(context):
    
    if (g.monthnum  % 6 ==0): #如果不是开仓日，不进行计算
        log.info('今天是换仓日，开仓卖东西')
        #2，计数器+1
        g.adjustpositions = True  #打开开关
        g.monthnum += 1
    else:
        log.info('今天是旁观日，持仓')
        #2，计数器+1
        g.monthnum += 1
        g.adjustpositions = False #关上开关
        return
    #不进行卖出操作
    
    
    # for f in context.portfolio.positions:
    #     amount = context.portfolio.positions[f].closeable_amount
    #     o1 = redeem(f,amount)
    #     log.info("清仓：",f)
    
            
def market_open_buy(context):
    if g.adjustpositions == True:
        log.info('今天是换仓日，开仓买基金')
    else:
        log.info('今天是旁观日，不买')
        return
    g.adjustpositions = False #把开关闭上
    
    
    fund_list = get_fund_by_rank(context.current_dt,g.days,g.num)
    print(context.portfolio.positions)
    allcash = context.portfolio.available_cash
    print('cash:%s'%(allcash))
    buylist = fund_list - context.portfolio.positions.keys()
    print('本次待买%s个'%len(buylist))
    percash = int(allcash/len(buylist))
    for s in fund_list:
        o = purchase(s, percash)
        log.info("申购：",s,percash)


# 获取过去90天中选100只基金，表现最好的20只基金
def get_fund_by_rank(current_day,days, x):
    trade_days = get_trade_days(current_day - datetime.timedelta(days=days),(current_day - datetime.timedelta(days=1)))
    day1 = trade_days[0]
    day2 = trade_days[-1]  
    
    #已经获得所有开发基金了
    all_open_fund = get_all_securities(['open_fund'])
    all_open_fund = all_open_fund[(all_open_fund['type'] == 'stock_fund') & (all_open_fund['start_date'] <= day1)]
    
    
    #获得基金的排名
    df1 = get_extras('acc_net_value', all_open_fund.index.tolist(), start_date=day1, end_date=day1)
    df1 = df1.T
    df1.columns = ['acc_net_value1']
    df2 = get_extras('acc_net_value', all_open_fund.index.tolist(), start_date=day2, end_date=day2)
    df2 = df2.T
    df2.columns = ['acc_net_value2']
    df_fund = pd.concat([df1, df2], join='inner', axis=1)
    df_fund['rate'] = (df_fund['acc_net_value2'] - df_fund['acc_net_value1']) / df_fund['acc_net_value1']
    
    #收益率>25%的基金
    d_num = 0 
    for rate in  df_fund['rate']:
        if rate > 0.40:
            d_num += 1 
        else:
            pass
    print('1%s,2:%s'%(day1,day2))
    print(d_num)
    
    # if d_num <= 20 :
    #     df_fund = df_fund.sort_values(['rate'], ascending=False, inplace=False).head(20)
    # else:
    #      df_fund1 = df_fund.sort_values(['rate'], ascending=False, inplace=False)
    #      df_fund = df_fund1.head(20)
    
    df_fund = df_fund.sort_values(['rate'], ascending=False, inplace=False).head(100)
    
    
    print( df_fund)

    return df_fund.index.tolist()
    

