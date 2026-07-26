# 克隆自聚宽文章：https://www.joinquant.com/post/44521
# 标题：【深度解析 七】BBI指标-大盘涨跌-宽基轮动 模型
# 作者：加百力

# 参考文章：https://www.joinquant.com/post/32543

# 导入函数模块
import jqdata
from   jqlib.technical_analysis  import *
from   jqdata import *


# 初始化函数，设定基准等等
def initialize(context):

    # 过滤掉order系列API产生的比error级别低的log
    # 默认是 'debug' 参数。最低的级别，日志信息最多
    # 系统推荐尽量使用'debug'参数或不显式设置，方便找出所有错误    
    log.set_level('order', 'error')
    
    # 开启动态复权模式(使用真实价格)
    set_option('use_real_price', True)
    
    # 避免使用未来数据
    set_option('avoid_future_data', True)
    
    # 交易量不超过实际成交量的 0.1    
    set_option('order_volume_ratio',0.1)
    
    # 设定基准
    # '000300.XSHG' 沪深300指数    
    set_benchmark('000300.XSHG')
    
    # 设置滑点
    set_slippage(FixedSlippage(0.001))
    
    # 基金和股票的手续费设置有些不同
    set_order_cost(OrderCost(close_tax=0.000, 
                   open_commission=0.00006, 
                   close_commission=0.00006, 
                   min_commission=0), type='fund')



    # 初始化全局变量
    
    # g. 开头的是全局变量
    # 一经声明整个程序都可以使用

    # 最强指数涨了多少，可以开仓
    g.dapan_threshold =0
    g.signal= 'BUY'
    

    # 基金上市了多久可以买卖
    g.lag = 20
    g.decrease_days = 0 
    g.increase_days = 0 
    
    # bbi动量的单位
    g.unit = '30m'
    # g.unit = '1d'
    
    
    g.zs_list = [
        '000001.XSHG', # 上证
        '399001.XSHE', # 深成指
        '399006.XSHE', # 创业板指数
        '000852.XSHG', # 中证1000指数
        '000015.XSHG'  # 红利指数
        ]
        
        
    
    # 指数、基金对, 所有想交易的etf都可以，会自动过滤掉交易时没有上市的
    g.ETF_list =  {
      
        '399905.XSHE':'159902.XSHE',  # 中小板指
        '399632.XSHE':'159901.XSHE',  # 深100etf
        '000016.XSHG':'510050.XSHG',  # 上证50
        '000010.XSHG':'510180.XSHG',  # 上证180
        
        '000852.XSHG':'512100.XSHG',  # 中证1000etf
        '399295.XSHE':'159966.XSHE',  # 创蓝筹
        '399958.XSHE':'159967.XSHE',  # 创成长
        '000015.XSHG':'510880.XSHG',  # 红利ETF
        '399324.XSHE':'159905.XSHE',  # 深红利
        '399006.XSHE':'159915.XSHE',  # 创业板
        '000300.XSHG':'510300.XSHG',  # 沪深300
        '000905.XSHG':'510500.XSHG',  # 中证500
        '399673.XSHE':'159949.XSHE',  # 创业板50
        '000688.XSHG':'588000.XSHG'   # 科创50

    }
    
    
    g.not_ipo_list = g.ETF_list.copy()
    
    g.available_indexs = []

    # 每日9:15调用函数
    # 分析 ETF 上市情况
    run_daily(check_etf, time='9:15')

    
    # 每日 11:15 实际进行交易
    run_daily(check_trade, time='11:15')
    # run_daily(check_trade, time='14:45')
    # run_weekly(check_trade, weekday=1,time='11:15')
  


# 获取指定日期之前或之后 N 个交易日的日期
def get_N_trade_date(date, N, is_before=True):
    
    # get_all_trade_days() 获取所有交易日
    # 获取所有交易日, 不需要传入参数
    # 返回一个包含所有交易日的 numpy.ndarray, 每个元素为一个datetime.date类型
    # 注： 需导入 jqdata 模块，即在策略或研究起始位置加入 import jqdata
    all_date = pd.Series(get_all_trade_days())
    
    # 如果输入数据是字符串就对数据进行转换
    # 最后用 date() 得到日期数据
    if isinstance(date, str):
        date = datetime.datetime.strptime(date, '%Y-%m-%d').date()
    
    # 如果date参数的数据类型为 datetime.datetime
    # 则直接使用date()函数获取日期
    if isinstance(date, datetime.datetime):
        date = date.date()

    # 如果是准备获取更早期的数据
    if is_before:
        
        # 这里的写法非常巧妙
        return all_date[all_date <= date].tail(N).values[0]
    
    # 否则是获取更晚的数据
    else:
        return all_date[all_date >= date].head(N).values[-1]    

    

# 确认ETF已经上市交易
# 对待交易基金列表中的每只基金都做分析判断是否可以交易
# 有可能在列表中的基金在回测的时间点还不能交易
def check_etf(context):
    
    # 在初始化函数中已经赋值待交易的 ETF 列表
    # 至少刚开始回测时不会为空
    if len(g.not_ipo_list) == 0:
        return 
    
    idxs = []
    
    # 确保交易标的已经上市g.lag个交易日以上
    yesterday = context.previous_date
    
    # 今天的前g.lag个交易日的日期
    list_date = get_N_trade_date(yesterday, g.lag)  
  
    # 上个交易日之前上市的所有基金
    all_funds = get_all_securities(types='fund', date=yesterday) 
    
    # 上个交易日之前就已经存在的指数
    all_idxes = get_all_securities(types='index', date=yesterday) 
    
    # 遍历待交易基金列表中的每只ETF
    for idx in g.not_ipo_list:
        
        if idx in all_idxes.index:
            
            # 指数已经在要求的日期前上市
            if all_idxes.loc[idx].start_date <= list_date:  
                
                symbol = g.not_ipo_list[idx]
                
                if symbol in all_funds.index:
                    
                    # 对应的基金也已经在要求的日期前上市
                    if all_funds.loc[symbol].start_date <= list_date:
                        
                        # 将这只基金加入可交易列表中
                        g.available_indexs.append(idx)  
                        
                        idxs.append(idx)
    
    # 删除不可交易列表中的对应基金
    for idx in idxs:
        
        del g.not_ipo_list[idx]
    
    log.info('输出不可交易基金列表：')    
    log.info(g.not_ipo_list)
    
    return    


    
## 分析市场行情，进行交易
def check_trade(context):
    
    
    log.info("-----今天的交易开始了-----------------------------------------")
    

    # for etf in g.ETF_targets:
    # 建立数据框保存 指数代码 和 周期动量两列数据
    df_index = pd.DataFrame(columns=['指数代码', '周期动量'])
    
    # 分析四大指数，判断是否值得开仓
    df_incre = pd.DataFrame(columns=['大盘代码','周期涨幅','当前价格'])


    # 
    # BBI-多空均线
    # BBI(security_list, check_date, timeperiod1=3, timeperiod2=6, timeperiod3=12, 
    #     timeperiod4=24, unit = '1d', include_now = True, fq_ref_date = None)
    # 参数：
    # security_list：标的列表
    # check_date：要查询数据的日期
    # timeperiod1：统计的天数 N1
    # timeperiod2：统计的天数 N2
    # timeperiod3：统计的天数 N3
    # timeperiod4：统计的天数 N4
    # unit：统计周期，默认为 '1d', 支持如下周期: '1m', '5m', '15m', '30m', '60m', '120m', '1d'
    # '1w', '1M'. '1w' 表示一周, ‘1M' 表示一月
    # include_now：是否包含当前周期，默认为 True
    # fq_ref_date：复权基准日，默认为 None
    # 返回：
    # BBI 的值
    # 返回结果类型：
    # 字典(dict)：键(key)为标的代码，值(value)为数据。
    # 如： {'000001.XSHE': 9.223020833333333, '603177.XSHG': nan, '000002.XSHE': 20.7265625,
    #       '601211.XSHG': 18.572187500000002}
    # 
    # 1.股价位于BBI 上方，视为多头市场
    # 2.股价位于BBI 下方，视为空头市场。
    
    # 对所有可交易的指数计算 BBI 数据
    BBI2 = BBI(g.available_indexs, 
               check_date=context.current_dt, 
               timeperiod1=3, 
               timeperiod2=6, 
               timeperiod3=12, 
               timeperiod4=24,
               unit = g.unit,
               include_now=True)
    
    
    # 遍历每一个可用指数计算周期动量并生成数据框
    for index in g.available_indexs:
        
        # get_bars 获取历史数据(包含快照数据)，可查询单个或多个标的多个数据字段，返回数据格式为 numpy.ndarray或DataFrame
        # get_bars(security, count, unit='1d',fields=['date', 'open','high','low','close'],
        # include_now=False, end_dt=None, fq_ref_date=None, df=False)
        # 获取各种时间周期的 bar 数据， bar 的分割方式与主流股票软件相同， 而且支持返回当前时刻所在 bar 的数据
        # get_bars 开盘时取的bar高开低收都是当天的开盘价，成交量成交额为0
        # get_bars 没有跳过停牌选项，所获取的数据都是不包含停牌的数据，如果bar个数少于count个，则返回实际个数，并不会填充
        df_close = get_bars(index, 1, 
                            g.unit, ['close'],  
                            end_dt=context.current_dt,
                            include_now=True)['close']

        val =   BBI2[index]/df_close[0]
        
        # 将指数代码和周期动量追加到数据框
        df_index = df_index.append({'指数代码': index, '周期动量': val}, ignore_index=True)
    
    # 基于 周期动量 对数据框做降序排序
    df_index.sort_values(by='周期动量', ascending=False, inplace=True)
    
    log.info("输出排序后的指数代码和周期动量")
    log.info(df_index)

    # 选取周期动量最小的指数代码    
    target = df_index['指数代码'].iloc[-1]
    target_bbi = df_index['周期动量'].iloc[-1]

    
    # 遍历分析大盘指数，计算周期涨幅，生成数据框
    for index in g.zs_list:
        
        # 读取昨日和今日的大盘指数数据
        df_close = get_bars(index, 2, '1d', ['close'],  
                            end_dt=context.current_dt,
                            include_now=True)['close']
        
        # 如果成功读取到两组数据
        if len(df_close) > 1:
            
            # 计算这两天的收益率
            increase = (df_close[1] - df_close[0]) / df_close[0]
            
            # 将数据追加到数据框中
            df_incre = df_incre.append({'大盘指数': index, 
                                        '周期涨幅': increase,
                                        '当前数值': df_close[0]}, 
                                        ignore_index=True)
    
    # 大盘指数按照周期涨幅降序排列
    df_incre.sort_values(by='周期涨幅', ascending=False, inplace=True)
    
    log.info("输出大盘数据")
    log.info(df_incre)
    
    # 保存周期涨幅最大的大盘指数和当前数值
    today_increase = df_incre['周期涨幅'].iloc[0]
    today_index_code = df_incre['大盘代码'].iloc[0]
    today_index_close = df_incre['当前数值'].iloc[0]
    
    # 最强指数的涨幅大于阈值并且周期动量最小指数的 BBI 数值小于1
    # 设置交易信号。或者买入，或者全部清仓
    if(today_increase > g.dapan_threshold and target_bbi < 1):
        g.signal = 'BUY'
        g.increase_days += 1
        
    else:
        g.signal = 'CLEAR'
        g.decrease_days += 1
  
    
    
    # 获取现有持仓名称
    holdings = set(context.portfolio.positions.keys()) 
    
    # 输出上涨、下跌天数
    log.info("-------------increase_days----------- %s" % (g.increase_days))
    log.info("-------------decrease_days----------- %s" % (g.decrease_days))
    
    
    # 列表中读取待交易的目标 ETF
    target_etf = g.ETF_list[target]
    

    if(g.signal == 'CLEAR'):
        
        for etf in holdings:
            
            log.info("----~~~---指数集体下跌，卖出---~~~~~~-------- %s" % (etf))
              
            order_target(etf, 0)
            
            return
    else:
        
        for etf in holdings:
            
            if (etf == target_etf):
                log.info('相同etf，不需要调仓！@')
                return 
            else:
                order_target(etf, 0)
                log.info("------------------调仓卖出----------- %s" % (etf))

            
        
        log.info("------------------买入----------- %s" % (target))
        
        # 全仓买入目标 ETF
        order_value(target_etf,context.portfolio.available_cash)
        
        
