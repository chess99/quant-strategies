# 克隆自聚宽文章：https://www.joinquant.com/post/28893
# 标题：股债波动平衡
# 作者：囚徒

# 导入函数库
from jqdata import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option("use_real_price", True)
    
    log.set_level('order', 'error')
    log.set_level('strategy','info')
    ### 场外基金相关设定 ###
    # 设置账户类型: 场外基金账户
    #set_subportfolios([SubPortfolioConfig(context.portfolio.cash, 'open_fund')])
    # 设置赎回到账日
    #set_redeem_latency(3, 'QDII_fund')
    #set_order_cost(OrderCost(open_tax=0, close_tax=0, open_commission=0.00006, close_commission=0.00006, close_today_commission=0, min_commission=0.0), type='fund')
    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
        # 开盘时运行
    run_daily(market_open, time='open', reference_security='000300.XSHG')
        # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')
    g.buy_info =  df = pd.DataFrame({'cash':[1000.0]},index=[context.current_dt.date()])
    g.ratio_y = 1.0

# 波动率    
def get_volatility(df,down=False):
    # 无数据返回Nan
    if len(df)==0:
        return float(np.NaN)
    
    #前一日收盘价
    df['pre']=df.shift(1)
    # 清除无效数据
    df=df.dropna()
    # 日收益率(当日收盘价/前一日收盘价，然后取对数)
    df['day_volatility']=np.log(df.iloc[:,0]/df['pre'])
    if down:
        #avg = df[df.day_volatility<0.0].day_volatility.mean()
        df.loc[df.day_volatility>0.0,"day_volatility"] = 0

    vol = df['day_volatility'].std()
    mean = df['day_volatility'].mean()
    
    df.loc[df.day_volatility>mean + 3*vol ,"day_volatility"] = mean + 3*vol
    df.loc[df.day_volatility<mean - 3*vol ,"day_volatility"] = mean - 3*vol
    
    # 波动率（年化收益率的方差*sqrt(250)）
    volatility=df['day_volatility'].std()*math.sqrt(250.0)*100

    # 返回值
    return volatility
    
def need_balance(context):
    position = g.position
    x = 0.0
    for s in position.index.values:
        p = position.position[s]
        r = p
        if s in context.portfolio.positions.keys():
            r = context.portfolio.positions[s].value / context.portfolio.total_value
        x += abs(r-p)
    
    return x > 0.05
    
def rebalance(context):
    position = g.position
    sells = []
    for s in position.index.values:
        p = position.position[s]
        r = p
        if s in context.portfolio.positions:
            r = context.portfolio.positions[s].value / context.portfolio.total_value
        if r > p:
            order_target_value(s,context.portfolio.total_value*p)
            sells.append(s)
    
    for s in position.index.values:
        p = position.position[s]
        if s not in sells:
            order_target_value(s,context.portfolio.total_value*p)
        
def market_open(context):
    weekday = context.current_dt.isoweekday()
    if weekday != 5 and len(context.portfolio.positions) > 0:
        return
    #富国天惠 | 兴全轻资 | 国债 | 纳指 | 标普 | 黄金 | 消费 | 医 
    stocks = ['161005.XSHE','163412.XSHE','511010.XSHG','513100.XSHG','513500.XSHG','518880.XSHG','159928.XSHE','512010.XSHG']
    weights = [ 15.0,20.0,2.0,15.0,7.5,4.0,25.0,20.0 ]
    waves = []
    df = history(40, unit='1d', field='close', security_list=stocks, df=True, skip_paused=True, fq='post')
    for s in stocks:
        waves.append( get_volatility(df[[s]],False) )
    
    g.position = pd.DataFrame(data={"weight":weights,"wave":waves},index=stocks)
    g.position["position"] = g.position.weight / (g.position.wave ** 2)
    g.position.position = g.position.position / g.position.position.sum()
    print(g.position)
 
    if context.portfolio.available_cash > 200.0 or need_balance(context):
        rebalance(context)
        #log.info(o)
    # 赎回基金
    '''elif weekday == 3:
        o1 = redeem(s, 4000)
        log.info(o1)
    elif weekday == 4:
        o2 = redeem(s, 3000)
        log.info(o2)
    '''

def compt_df_ratio(df,r,today):
    total = 0.0
    for d in df.index:
        days = (today - d).days
        total += df.cash[d] * power(r,days*1.0/365)
    return total
        
def compt_ratio_y(total_value,r,today):
    iter = 0.01
    mincash = 1.0
    
    min_r = max(r - 1.0,0.0)
    max_r = r + 1.0
    
    tv = compt_df_ratio(g.buy_info,r,today)
    
    if tv > total_value:
        max_r = r
        min_r = max(r - 1.0,0)
        while True:
            tv = compt_df_ratio(g.buy_info,min_r,today)
            #print("%.2f %.2f %.2f %.2f %.2f"%(total_value,tv,r,min_r,max_r))
            if tv > total_value:
                max_r = min_r
                min_r = max(min_r - 1.0,0)
            else:
                break;
    else:
        min_r = r
        max_r = r + 1.0
        while True:
            tv = compt_df_ratio(g.buy_info,max_r,today)
            #print("%.2f %.2f %.2f %.2f %.2f"%(total_value,tv,r,min_r,max_r))
            if tv < total_value:
                min_r = max_r
                max_r += 1.0
            else:
                break;
                
    while True:
        r = (min_r + max_r)/2.0
        tv = compt_df_ratio(g.buy_info,r,today)
        #print("%.2f %.2f %.2f %.2f %.2f"%(total_value,tv,r*100,min_r*100,max_r*100))
        if abs( tv - total_value ) < mincash:
            break;
        if tv < total_value:
            min_r = r
        else:
            max_r = r
        
    return r
        
## 收盘后运行函数
def after_market_close(context):
    return
    # 查看融资融券账户相关相关信息(更多请见API-对象-SubPortfolio)
    days = (context.current_dt.date() - context.run_params.start_date).days
    p = context.portfolio.subportfolios[0]
    if days > 365:
        g.ratio_y = compt_ratio_y(p.total_value,g.ratio_y,context.current_dt.date())
    print("total_value %.2f total_incash %.2f ratio %.2f ratio_y : %.3f%%"%
            (p.total_value,p.inout_cash,p.total_value/p.inout_cash*100,g.ratio_y*100))
    record(ratio = g.ratio_y*100)
    record(e=p.total_value/p.inout_cash*100)
    '''record(total = p.total_value/p.inout_cash)
    log.info('- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -')
    log.info('查看场外基金账户相关相关信息(更多请见API-对象-SubPortfolio)：')
    log.info('场外基金持有份额：',p.long_positions['000311.OF'].closeable_amount)
    log.info('账户所属类型：',p.type)
    log.info('##############################################################')
    '''
