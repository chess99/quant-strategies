# 克隆自聚宽文章：https://www.joinquant.com/post/36544
# 标题：行业ETF轮动+择时，15年至今年化收益35%，回撤16%
# 作者：Jacobb75

"""

程序运行原理：
1、给定大盘指数：上证，深成指，创业板指数，科创50，沪深300，中证500,1000指数
2、给定17只行业指数基金
3、判断指数基金是否正常上市
4、判断5个大盘是否处于上涨趋势（获取大盘上涨最大的代码）
5、判断17只大盘指数基金的中期BBI指标（多空指标）
6、如果涨幅最好的大盘指数是上涨的（市场今天可以），则买入BBI指标中多头最强的指数基金（大概率也是指数对应的基金)

7、下一周期重新进入1-5的判断，如果大盘都是下跌的，清仓，套现的钱买银华日利
                            如果表现做好的大盘是上涨的，则买入BBI最小的基金，清空持有的基金，套现的钱买银华日利
                            如果买入BBI最小的基金已经持仓，则不操作
如果大盘不好（300etf 5日均线空头排列），清仓，买入银华日利基金；
如果大盘上涨，则买入BBI指标中的多头最强的，第二天循环判断
程序实现了亏小，赢大的可能

为什么选周三运行？
不清楚，只是周三运行表现最好；我判断可能因为周三是周内情绪发酵的拐点，变数最大

为什么选中午11：15交易？
牛市11：15开盘原因：各大机构收盘后制定第二套买卖计划，会在9点30到10点30之间完成，有买入的这段
时间都是上涨的，之后会有一段时间回落，在回落时间段内，我们买入。（一般来说中午收盘前都可以，模型表现差异不大，自己选个时间就好）

"""

# 导入聚宽函数库
import jqdata
from jqlib.technical_analysis  import *
from jqdata import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
   
    set_slippage(FixedSlippage(0.004))
    #没有滑点设置的话使用系统默认的PriceRelatedSlippage(0.00246)
    set_option("avoid_future_data", True)
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')

    set_benchmark('000300.XSHG')
    ### 股票相关设定 ###
    # ETF基金场内交易类每笔交易时的手续费是：买入时佣金万分之一点五，卖出时佣金万分之一点五，无印花税, 每笔交易佣金最低扣0块钱
    set_order_cost(OrderCost(close_tax=0.00, open_commission=0.00015, close_commission=0.00015, min_commission=5), type='fund')
    
    ## 运行函数
    # 开盘时运行
    run_daily(make_sure_etf_ipo, time='9:15')
    run_weekly(market_buy, weekday=3,time='11:15')#每周三中午11：15交易

    # 最强指数涨了多少，可以开仓
    g.dapan_threshold = 0#大盘阈值
    g.signal= 'BUY'
    g.niu_signal = 1 # 牛市就上午开仓，熊市就下午
    g.position = 1
    
    # 基金上市了多久可以买卖
    g.lag1 =20
    g.decrease_days = 0 #递减
    g.increase_days = 0 #递增
    # bbi动量的单位
    g.unit = '30m'
    g.bond = '511880.XSHG'#清仓状态资金买入银华日利货币基金）
    
    #python中的中括号[ ]，代表list列表数据类型

    
    #大盘指数
    g.zs_list = [
        '000001.XSHG',#上证综指
        '399001.XSHE',#深证成指
        '000300.XSHG',#沪深300
        '000905.XSHG',#中证500
        '000852.XSHG',#中证1000
        '399006.XSHE',#创业板
        '000688.XSHG',#科创50
        ]  
        
    #python大括号{ }花括号：代表dict字典数据类型，字典是由键对值组组成。冒号':'分开键和值，逗号','隔开组
    # 指数、基金对, 所有想交易的etf都可以，会自动过滤掉交易时没有上市的
    
    #行业指数：指数对应的基金
    g.ETF_list =  {
        '000986.XSHG':'515220.XSHG', # 传统能源(煤）
        '000827.XSHG':'516070.XSHG', # 新能源
        '399967.XSHE':'512660.XSHG', # 军工
        '000995.XSHG':'159611.XSHE', # 电力
        '000987.XSHG':'159944.XSHE', # 材料
        '000813.XSHG':'516120.XSHG', # 化工
        '000989.XSHG':'159928.XSHE', # 消费
        '399997.XSHE':'512690.XSHG', # 白酒
        '000991.XSHG':'512170.XSHG', # 医药
        '399971.XSHE':'512980.XSHG', # 传媒
        '399986.XSHE':'512800.XSHG', # 银行
        '399975.XSHE':'159841.XSHE', # 证券
        '000993.XSHG':'512480.XSHG', # 信息
        '000922.XSHG':'515080.XSHG', # 中证红利
        '399440.XSHE':'515210.XSHG', # 钢铁
        '399814.XSHE':'159825.XSHE', # 农业
        '399995.XSHE':'516970.XSHG', # 基建
    }
    
    #复制g.EFT_list到g.not_ipo_list
    #copy() 函数用于复制列表，类似于 a[:]
    g.not_ipo_list = g.ETF_list.copy()
    g.available_indexs = []
    
    
    
    
##  交易！
def market_buy(context):
    #log.info(context.current_dt.hour)#信息输出：当前时间的小时段
    
    # for etf in g.ETF_targets:
    #建立df_index表，字段为：指数代码，周期动量
    df_index = pd.DataFrame(columns=['指数代码', '周期动量'])
    # 判断四大指数是否值得开仓
    #建立df_incre表，字段为：大盘代码，周期涨幅，当前价格
    df_incre = pd.DataFrame(columns=['大盘代码','周期涨幅','当前价格'])
    """
    BBI2 = BBI(g.available_indexs, check_date=context.current_dt, timeperiod1=3, timeperiod2=6, timeperiod3=12, timeperiod4=24,unit=unit,include_now=True)
    BBI2 = BBI(股票列表, check_date=日期, timeperiod1=统计天数N1, timeperiod2=统计天数N2, timeperiod3=统计天数N3, timeperiod4=统计天数N4,unit=统计周期,include_now=是否包含当前周期)
    返回结果类型：字典(dict)：键(key)为股票代码，值(value)为数据。
    用法注释：1.股价位于BBI 上方，视为多头市场； 2.股价位于BBI 下方，视为空头市场。
    计算方法：BBI=(3日均价+6日均价+12日均价+24日均价)÷4
    判断指数的BBI，多空指数
    """
    unit =g.unit
    BBI2 = BBI(g.available_indexs, check_date=context.current_dt, timeperiod1=21, timeperiod2=34, timeperiod3=55, timeperiod4=89,unit=unit,include_now=True)#斐波那契数列的中期BBI

    for index in g.available_indexs:#运行中的指数
        df_close = get_bars(index, 1, unit, ['close'],  end_dt=context.current_dt,include_now=True,)['close']#读取index当天的收盘价
        val =   BBI2[index]/df_close[0]#BBI除以交易当天11:15分的价格，大于1表示空头，小于1表示多头
        df_index = df_index.append({'指数代码': index, '周期动量': val}, ignore_index=True)#将数据写入df_index表格，索引重置
    #按'周期动量'进行从大到小的排列。ascending=true表示降序排列,ascending=false表示升序排序，inplace = True：不创建新的对象，直接对原始对象进行修改
    df_index.sort_values(by='周期动量', ascending=False, inplace=True)
    log.info(df_index)
    
    target = df_index['指数代码'].iloc[-1]#读取最后一行的指数代码
    target_bbi = df_index['周期动量'].iloc[-1]#读取最后一行的周期动量

    for index in g.zs_list:#大的指数判断
        df_close = get_bars(index, 3, '1d', ['close'],  end_dt=context.current_dt,include_now=True,)['close']#读取当前日期的前2天日K线图，包括当天的收盘价格，今天的收盘价，这是不是未来指数
        #print(df_close)
        if len(df_close)>2:#表示取得了2天的数据
            increase_previous = (df_close[1] - df_close[0]) / df_close[0]#昨日涨幅
            increase = (df_close[2] - df_close[1]) / df_close[1] #今天的11.15分的收盘价-昨天的收盘价）/昨天的收盘价，大于1表示今天上涨，小于1表示今天下跌
            increase_delta = (df_close[2] - df_close[1]) / df_close[1] - 0.25 * (df_close[1] - df_close[0]) / df_close[0]#今日目前涨幅和昨日涨幅25%比较
            df_incre = df_incre.append({'大盘代码': index, '前周期涨幅': increase,'本周期涨幅': increase,'本周期涨幅变动': increase_delta,'当前价格':df_close[0]}, ignore_index=True)
    #大盘指数按大到小排列
    df_incre.sort_values(by='本周期涨幅', ascending=False, inplace=True)
    print(df_incre)
    #读取最大的大盘代码
    today_increase_previous = df_incre['前周期涨幅'].iloc[0]
    today_increase = df_incre['本周期涨幅'].iloc[0]
    today_increase_delta = df_incre['本周期涨幅变动'].iloc[0]
    today_index_code = df_incre['大盘代码'].iloc[0]
    today_index_close = df_incre['当前价格'].iloc[0]
    holdings = set(context.portfolio.positions.keys())  # 现在持仓的

    update_niu_signal(context,today_index_code)#将今天上涨最大的大盘代码带入函数计算（本来打算用这个做择时，后来发现涨幅最好的大盘指数不如直接用300etf择时好，代码就懒得改了）
    
    if(context.current_dt.hour == 11 and g.niu_signal == 0 and g.signal == 'BUY')    or (context.current_dt.hour == 14 and g.niu_signal == 1):
       log.info('牛熊不匹配，这个时间点不能开仓，并清仓')
       for etf in holdings:
           
            if (etf == g.bond):#要买入的指数已经有仓位
                log.info('相同etf，不需要调仓！@')
                return
            else:
                order_target(etf, 0)
                order_value(g.bond,context.portfolio.available_cash)


       return

    if(today_increase>g.dapan_threshold and today_increase>0.05*today_increase_previous and target_bbi<1):
        #today_increase>g.dapan_threshold表示涨幅最好的大盘指数是上涨的，today_increase>0.05*today_increase_previous 表明今日目前站上昨日收盘价格，此时只要BBI小于1，就购买最小的那个etf
        g.signal = 'BUY'
        g.increase_days+=1
        
    else:#否则就清盘卖出
        g.signal = 'CLEAR'
        g.decrease_days+=1
        
    log.info("-------------increase_days----------- %s" % (g.increase_days))
    log.info("-------------decrease_days----------- %s" % (g.decrease_days))
    
    target_etf = g.ETF_list[target]#读取指数对应的基金

    if(g.signal == 'CLEAR'):#清盘操作
        
        for etf in holdings:
            
            log.info("----~~~---指数集体下跌，卖出---~~~~~~-------- %s" % (etf))
            if (etf == g.bond):#要买入的指数已经有仓位
                log.info('相同etf，不需要调仓！@')
                return
            else:
                order_target(etf, 0)
                order_value(g.bond,context.portfolio.available_cash)
        return
      
    else:
        for etf in holdings:
            
            if (etf == target_etf):#要买入的指数已经有仓位
                log.info('相同etf，不需要调仓！@')
                return 
            else:#将不是当天要买入的ETF的持仓全部卖掉
                order_target(etf, 0)
                log.info("------------------调仓卖出----------- %s" % (etf))
                
        log.info("------------------买入----------- %s" % (target))
        order_value(target_etf,context.portfolio.available_cash*g.position)#全部现金买入，g.position应该是仓位数量，这里默认开一个仓
    


def get_before_after_trade_days(date, count, is_before=True):
    """
    来自： https://www.joinquant.com/view/community/detail/c9827c6126003147912f1b47967052d9?type=1
    date :查询日期
    count : 前后追朔的数量
    is_before : True , 前count个交易日  ; False ,后count个交易日
    返回 : 基于date的日期, 向前或者向后count个交易日的日期 ,一个datetime.date 对象
    """
    all_date = pd.Series(get_all_trade_days())#get_all_trade_days() 获取所有交易日

    if isinstance(date, str):#如果date是字符类型，则修改成日期类型的
        date = datetime.datetime.strptime(date, '%Y-%m-%d').date()
    if isinstance(date, datetime.datetime):#如果date是日期时间类型（年-月-日 时：分：秒），则修改成日期类型的
        date = date.date()

    if is_before:#函数自带的变量
        return all_date[all_date <= date].tail(count).values[0]#tail():读取后几行
    else:
        return all_date[all_date >= date].head(count).values[-1]#head():读取前几行
        
        
        
def make_sure_etf_ipo(context):
    if len(g.not_ipo_list) == 0:#如果列表没有数据，程序结束
        return 
    idxs = []#设置idxs列表变量
    # 确保交易标的已经上市g.lag1个交易日以上
    yesterday = context.previous_date#取得前一交易日的日期
    list_date = get_before_after_trade_days(yesterday, g.lag1)  # 今天的前g.lag1个交易日的日期（注意不是前几个日期，双休日，停牌日不交易）
    all_funds = get_all_securities(types='fund', date=yesterday)  # 上个交易日之前上市的所有基金
    all_idxes = get_all_securities(types='index', date=yesterday)  # 上个交易日之前就已经存在的指数
    for idx in g.not_ipo_list:#按指数做for循环,g.not_ipo_list的键做循环（键=指数，值=基金）
        if idx in all_idxes.index:#all_idxes.index是指数名称
            #读取all_idxes表中，index为idx的记录，并读取start_date字段的内容（index为序号)
            if all_idxes.loc[idx].start_date <= list_date:  # 指数已经在要求的日期前上市
                #将指数对应的基金赋值给symbol
                symbol = g.not_ipo_list[idx]#g.not_ipo_list[idx]是指数对应的基金，指数用index读取，基金用idx读取
                if symbol in all_funds.index:
                    if all_funds.loc[symbol].start_date <= list_date:  # 对应的基金也已经在要求的日期前上市
                        g.available_indexs.append(idx)  # 则列入可交易对象中(指数）
                        idxs.append(idx) #后面删掉这一条，下次就不用折腾了
    for idx in idxs:#将已经上止的指数删除，剩下的就是没有开盘的指数了
        del g.not_ipo_list[idx]
    return




# 短均线金叉，强势期，上午交易（利用300etf择时而非300指数）
def update_niu_signal(context,index):
    include_now = True#表示读取当天的日K线
    unit='1d'
    #-------------------标的指数的5日均线，如果均线朝下表示趋势向下，暂停交易---------------
    ind='510300.XSHG'
    ema_close = get_bars(ind, 1, '1d', ['close'],  end_dt=context.current_dt,include_now=include_now,)['close']
    
    #当天获取5日均线
    ema_5 = EMA(ind,context.current_dt, timeperiod=5, unit = unit, include_now =include_now, fq_ref_date = None)[ind]

    #前一天的5日均线
    ema_5q = EMA(ind,context.previous_date, timeperiod=5, unit=unit, fq_ref_date = None)[ind]

    if ema_close<ema_5<ema_5q:#当价格低于5日均线且5日均线空头排列的时候暂停交易
     g.niu_signal = 0#开仓数量=0
    else:
     g.niu_signal = 1#开仓数量=1








