# 克隆自聚宽文章：https://www.joinquant.com/post/32253
# 标题：韶华研究之五-ETF轮动，躺赚，夏普2
# 作者：韶华不负

##策略介绍
##参考将就的宽基BBI轮动思路构建，原帖-https://www.joinquant.com/post/32187
##参考yu的三指轮动，原帖-https://www.joinquant.com/post/27798
##参考hugo的复现基金经理的超额收益，https://www.joinquant.com/view/community/detail/51d97afb8d619ffb5219d2e166414d70
##集思录上的ETF页面有较多数据参考，结合hugo的结论，选取10-100亿的，有对应指数的主题基金作为备选，同指数选择ETF发行较早的，规模较大的

# 导入函数库
from jqdata import *
from six import BytesIO
from jqlib.technical_analysis  import *

# 初始化函数，设定基准等等
def initialize(context):
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')
    set_params()    #1 设置策略参数
    set_variables() #2 设置中间变量
    set_backtest()  #3 设置回测条件

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='7:00')
      # 开盘时运行
    run_daily(market_open, time='11:15')    #原版为11:15
      # 收盘后运行
    run_daily(after_market_close, time='20:00')
          # 收盘后运行
    #run_daily(after_market_analysis, time='21:00')

#1 设置策略参数
def set_params():
    #设置全局参数
    g.index ='all'
    #指数列表用于开关仓，代表全场，不变
    g.index_list = [
        '000300.XSHG',  #沪深300，2005/04/08
        '000905.XSHG',  #中证500，2007/01/15
        '000852.XSHG',  #中证1000，2014/10/17
        '000001.XSHG',  #上证
        '399001.XSHE',  #深成指
        '399006.XSHE',  #创业板指
        ]
    #不同的ETF组合，可选
    """
    #简版，三档中证ETF
    g.etf_list = {
        '000300.XSHG':'510300.XSHG',#沪深300,2012/05/28
        '000905.XSHG':'510500.XSHG',#中证500,2013/03/15
        '000852.XSHG':'512100.XSHG',#中证1000,2016/11/04
        }
    """
    """
    #原版，混合ETF
    g.etf_list =  {
        ## '399001.XSHE':'150019.XSHE',#银华锐进
        '399905.XSHE':'159902.XSHE',#中小板指
        '399632.XSHE':'159901.XSHE',#深100etf
        '000016.XSHG':'510050.XSHG',#上证50
        '000010.XSHG':'510180.XSHG',#上证180
        '000852.XSHG':'512100.XSHG',#中证1000etf
        ## '399295.XSHE':'159966.XSHE',# 创蓝筹
        ## '399958.XSHE':'159967.XSHE',# 创成长
        '000015.XSHG':'510880.XSHG',#红利ETF
        ## '399324.XSHE':'159905.XSHE',#深红利
        '399006.XSHE':'159915.XSHE',#创业板
        '000300.XSHG':'510300.XSHG',#沪深300
        '000905.XSHG':'510500.XSHG',#中证500
        '399673.XSHE':'159949.XSHE',#创业板50
        ## '000688.XSHG':'588000.XSHG'#科创50
        }

    """
    """
    #行业版ETF，对应相应的指数行情，先以SW_l1为例
    g.etf_list = {
        '399231.XSHE':'159825.XSHE', #农林牧渔，农林指数-2013/03/04，农业ETF-2020/12/10
        '399232.XSHE':'510410.XSHG', #采掘，采矿指数-2013/03/04，资源ETF-2012/05/11
        '000928.XSHG':'159930.XSHE', #化工，能源指数-2009/02/08，能源ETF-2021/02/23
        #钢铁行业缺
        '000819.XSHG':'512400.XSHG', #有色，有色金属-2012/05/09，有色金属-2017/09/01
        '399811.XSHE':'512480.XSHG', #电子，申万电子-2015/08/03，半导体ETF-2019/06/12
        '000989.XSHG':'159996.XSHE', #家电，全指可选-2011/08/02，家电ETF-2020/02/07
        '399396.XSHE':'159928.XSHE', #食品饮料，国证食品-2012/10/29，消费ETF-2013/09/16
        #纺织服装行业缺
        #轻工制造行业缺
        #...缺了很多，不能代表市场，改用集思录ETF集合
        }
    """
    #集思录ETF
    g.etf_list ={
        '000016.XSHG':'510050.XSHG', #上证50-2004-01-02，50ETF-2005/2/23
        '399330.XSHE':'159901.XSHE', #深证100-2006-01-24，深100ETF-2006/4/24
        '000010.XSHG':'510180.XSHG', #上证180-2002-07-01，180ETF-2006/5/18
        '000015.XSHG':'510880.XSHG', #红利指数-2005-01-04，红利ETF-2007/1/18，代表沪市
        '399324.XSHE':'159905.XSHE', #深证红利-2006-01-24，深红利ETF-2011/1/11，代表深市
        ##'000018.XSHG':'510230.XSHG', #180金融-2007-12-10，金融ETF-2011/5/23，下有更全面的
        '399006.XSHE':'159915.XSHE', #创业板指-2010-06-01，创业板ETF-2011/12/9
        '000300.XSHG':'510300.XSHG', #沪深300-2005-04-08，300ETF-2012/5/28
        '000905.XSHG':'510500.XSHG', #中证500-2007-01-15，500ETF-2013/3/15
        '399673.XSHE':'159949.XSHE', #创业板50-2014-06-18，创业板50ETF-2016/7/22
        ##'399295.XSHE':'159966.XSHE', #创业蓝筹-2019-01-23，创业蓝筹ETF-2019/7/15，已有市场指数代替
        ##'399296.XSHE':'159967.XSHE', #创业成长-2019-01-23，创业成长ETF-2019/7/15，已有市场指数代替
        '000688.XSHG':'588000.XSHG', #科创50-2020-07-23，科创50ETF-2020-09-28

        #'000932.XSHG':'159928.XSHE', #中证消费-2015-02-10，消费ETF-2013/9/16
        ##'000913.XSHG':'512010.XSHG', #300医药-2007-07-02，医药ETF-2013/10/28，下有全指医药
        #'000849.XSHG':'512070.XSHG', #300非银-2012-12-21，证券保险ETF-2014/7/18，代替独立的保险ETF
        #'000991.XSHG':'159938.XSHE', #全指医药-2011-08-02，医药ETF-2015/1/8
        #'000993.XSHG':'159939.XSHE', #全指信息-2011-08-02，信息技术ETF-2015/2/5
        ##'000992.XSHG':'159940.XSHE', #全指金融-2011-08-02，金融ETF-2015/4/17，分成非银和银
        #'399967.XSHE':'512660.XSHG', #中证军工-2013-12-26，军工ETF-2016/8/8
        #'399975.XSHE':'512880.XSHG', #全指证券-2013-07-15，证券ETF-2016/8/8
        #'000827.XSHG':'512580.XSHG', #中证环保-2012-09-25，环保ETF-2017/2/28
        #'399986.XSHE':'512800.XSHG', #中证银行-2013-07-15，银行ETF-2017/8/3
        #'000819.XSHG':'512400.XSHG', #有色金属-2012-05-09，有色ETF-2017/9/1
        #'399241.XSHE':'512200.XSHG', #地产指数-2013-03-04，房地产ETF-2017/9/25
        #'399971.XSHE':'512980.XSHG', #中证传媒-2014-04-15，传媒ETF-2018/1/19
        ##'399417.XSHE':'501057.XSHG', #国证新能车-2014-09-24，新能源车LOF-2018/6/20,已有ETF
        #'399987.XSHE':'512690.XSHG', #中证酒-2014-12-10，酒ETF-2019/5/6
        ##'399441.XSHE':'512290.XSHG', #国证生物医药-2015-01-20，生物医药ETF-2019/5/20，已有更早的医药ETF
        ##'399989.XSHE':'512170.XSHG', #中证医疗-2014-10-31，医疗ETF-2019/6/17，已有更早的医药ETF
        ##'399973.XSHE':'512670.XSHG', #中证国防-2014-04-15，国防ETF-2019-07-05，已有军工ETF
        #'399389.XSHE':'515880.XSHG', #国证通信-2011-12-02，通信ETF-2019/08/16
        ##'000126.XSHG':'515650.XSHG', #消费50-2011-12-09，消费50ETF-2019-10-14，已有更早的消费ETF
        ##'399321.XSHE':'515180.XSHG', #国证红利-2005-01-04，红利ETF-2019-11-26，沪深集合，已有更早的红利指数
        #'399976.XSHE':'515700.XSHG', #中证新能源汽车-2014-11-28，新能车ETF-2019-12-31
        #'399811.XSHE':'159997.XSHE', #中证申万电子指数-2015-08-03，电子ETF-2020-02-27
        #'399363.XSHE':'159998.XSHE', #计算机指数-2009-08-03，计算机ETF-2020-02-27
        #'399365.XSHE':'159825.XSHE', #国证农业-2009-11-04，农业ETF-2020-12-10
        #'399993.XSHE':'159837.XSHE', #中证万得生科-2015-05-08，生物科技ETF-2021-01-14
        #'399808.XSHE':'516160.XSHG', #中证新能源-2015-02-10，新能源ETF-2021-01-22
        }
        
    g.strategy ='Increase'   #以BBI+短期涨幅排序；以周期内Increase排序；
    
    g.gz_etf = '511010.XSHG'    #空仓买国债ETF-2013/3/25    
    g.check_unit = 20    #BBI数据获取的周期单元，短周期-15m/30m，长周期-d/w；Increase数据获取的长度，短周期-5，中周期-20，长周期-60，单位是天
    g.criteria = 0      #阈值，用于判断建仓或清仓
    

#2 设置中间变量
def set_variables():
    #暂时未用，测试用全池
    g.stocknum = 1              #持仓数，0-代表全取
    g.poolnum = 2*g.stocknum    #参考池数
    #换仓间隔，也可用weekly或monthly，暂时没启用
    g.shiftdays = 20            #换仓周期，5-周，20-月，60-季，120-半年
    g.day_count = 0             #换仓日期计数器
    
#3 设置回测条件
def set_backtest():
    ## 设定g.index作为基准
    if g.index == 'all':
        set_benchmark('000300.XSHG')
    else:
        set_benchmark(g.index)
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    log.set_level('order', 'error')    # 设置报错等级
    
## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    all_data = get_current_data()
    g.available_indexs = []
    
    #取截止日是为了保证指数和基金已在场内运行
    by_date =get_trade_days(end_date=lastd_date, count=5)[0]
    all_funds = get_all_securities(types='fund', date=by_date)  # 5个交易日之前上市的所有基金
    all_indexes = get_all_securities(types='index', date=by_date)  # 5个交易日之前就已经存在的指数
    
    #检查指数和基金已在场内，并添加到
    for idx in g.etf_list:
        if idx in all_indexes.index:
            etf = g.etf_list[idx]
            if etf in all_funds.index:
                g.available_indexs.append(idx)
    return

## 开盘时运行函数
def market_open(context):
    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    all_data = get_current_data()
    g.poollist =[]
    g.buylist = []
    
    if g.strategy =='BBI':
        max_change, g.poollist = get_BBI_filter(context)
    elif g.strategy =='Increase':
        max_change, g.poollist = get_increase_filter(context)
    
    g.buylist =g.poollist[:g.stocknum]
    holdings = set(context.portfolio.positions.keys())  # 现在持仓的
    #判断所有指数涨幅是否大于基准，是-建仓，否-清仓
    if max_change <= g.criteria:
        for etf in holdings:
            log.info("---集体下跌，清仓卖出--- %s" % (etf))
            order_target_value(etf, 0)
            return
    else:
        for etf in holdings:
            if etf in g.poollist:
                log.info('---etf在池内，不需要调仓---')
                return 
            else:
                order_target_value(etf, 0)
                log.info("---eft不在池内，卖出--- %s" % (etf))
        
        #清仓后买入前排ETF
        cash = context.portfolio.total_value/g.stocknum
        log.info("---买入前排%s只--- %s" % (g.stocknum, g.buylist))
        for etf in g.buylist:
            #不光新买，旧仓也做平衡均分
            order_target_value(etf, cash)
    
    return

## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    
    return
"""
---------------------------------函数定义-主要策略-----------------------------------------------
"""
#用BBI指标对etf对应的指数进行排序，并取基指涨幅为开关仓标准
def get_BBI_filter(context):
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    all_data = get_current_data()
    poollist =[]
    #创建两个空DF用于后续双因子计算
    df_bbi = pd.DataFrame(columns=['code', 'bbi'])
    df_change = pd.DataFrame(columns=['code', 'change'])
    
    #得到各指数的当期BBI=（3日均价+6日均价+12日均价+24日均价）/4值，单位是30分钟线（对应就是半日-日-一日半-三日）
    BBI2 = BBI(g.available_indexs, check_date=context.current_dt, timeperiod1=3, timeperiod2=6, timeperiod3=12, timeperiod4=24, unit=g.check_unit,include_now=True)
    
    #判断各etf指数的周期BBI比值，输出并排序
    for idx in g.available_indexs:
        #取得是30分钟线最新bar价格
        df_close = get_bars(idx, 1, g.check_unit, ['close'],  end_dt=context.current_dt,include_now=True,)['close']
        #value = BBI2[idx]/df_close[0] #BBI定义，价格高于BBI是多头，低于是空头；按比值看，则是小于1是多头，大于1是空头
        value = BBI2[idx]/all_data[idx].last_price #BBI定义，价格高于BBI是多头，低于是空头；按比值看，则是小于1是多头，大于1是空头
        df_bbi = df_bbi.append({'code': idx, 'bbi': value}, ignore_index=True)
        
    df_bbi.sort_values(by='bbi', ascending=True, inplace=True)  #升序排列
    log.info(df_bbi)
    
    #获取基准指数的今日涨幅，用于判断开关仓
    for idx in g.index_list:
        #原版取得是昨天的收盘价和今天11:15的价格
        df_close = get_bars(idx, 2, '1d', ['close'],  end_dt=context.current_dt,include_now=True)
        change = (df_close['close'][-1] - df_close['close'][0]) / df_close['close'][0]
        df_change = df_change.append({'code': idx, 'change': change}, ignore_index=True)
        
    df_change.sort_values(by='change', ascending=False, inplace=True)  #降序排列
    log.info(df_change)
    #取值最大的一个，用于和阈值-0做比对
    max_change = df_change['change'].values[0]

    for i in range(g.poolnum):
        idx = df_bbi['code'].values[i]
        poollist.append(g.etf_list[idx])

    log.info(poollist)
    
    return max_change,poollist
    
#以etf指数周期内的涨幅来排序，以基准周期内的涨幅来衡量开关仓
def get_increase_filter(context):
    today_date = context.current_dt.date()
    lastd_date = context.previous_date
    all_data = get_current_data()
    poollist =[]
    
    #判断各etf指数的周期涨幅，输出并排序
    df_close = get_price(g.available_indexs,end_date=lastd_date,count =g.check_unit,frequency='daily')  #间接判断对应指数的日行情
    #df_close = get_price(g.etf_list,end_date=lastd_date,count =g.check_unit,frequency='daily') #直接判断ETF日行情
    df_increase = df_close['close'].pct_change(periods=g.check_unit-1).dropna().T
    log.info(df_increase)
    df_increase.columns =['etf_change']
    df_increase.sort_values(by='etf_change', ascending=False, inplace=True)  #降序排列
    
    log.info(df_increase)
    
    #获取基准指数的今日涨幅，用于判断开关仓
    df_change = pd.DataFrame(columns=['code', 'change'])
    for idx in g.index_list:
        #原版取得是昨天的收盘价和今天11:15的价格
        df_close = get_bars(idx, g.check_unit, '1d', ['close'],  end_dt=context.current_dt,include_now=True)
        change = (df_close['close'][-1] - df_close['close'][0]) / df_close['close'][0]
        df_change = df_change.append({'code': idx, 'change': change}, ignore_index=True)
        
    df_change.sort_values(by='change', ascending=False, inplace=True)  #降序排列
    log.info(df_change)
    #取值最大的一个，用于和阈值-0做比对
    max_change = df_change['change'].values[0]
    
    #间接从指数对应到ETF
    for i in range(g.poolnum):
        idx = df_increase.index.values[i]
        poollist.append(g.etf_list[idx])
    
    #poollist = df_increase.index.values.tolist()[:g.poolnum]   #直接取ETF列表

    log.info(poollist)
    
    return max_change,poollist

"""
---------------------------------函数定义-次要过滤-----------------------------------------------
"""


"""
---------------------------------函数定义-辅助函数-----------------------------------------------
"""
