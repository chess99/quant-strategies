# 克隆自聚宽文章：https://www.joinquant.com/post/32543
# 标题：【不含未来！】宽基etf轮动8年50倍年化60%
# 作者：将就

# 克隆自聚宽文章：https://www.joinquant.com/post/10087
# 标题：短周期交易型阿尔法191因子 之 Alpha011
# 作者：JoinQuant-PM

# 导入聚宽函数库
import jqdata
# 导入alpha191 因子函数库
from jqlib.technical_analysis  import *
from jqdata import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
   
    set_slippage(FixedSlippage(0.001))
    set_option("avoid_future_data", True)
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')


    set_benchmark('000300.XSHG')
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.000, open_commission=0.00006, close_commission=0.00006, min_commission=0), type='fund')
    
    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    # run_daily(market_open, time='9:34')
    #   # 开盘时运行
    
    run_daily(make_sure_etf_ipo, time='9:15')
    # run_weekly(market_buy, weekday=1,time='14:30')
    # run_weekly(market_buy, weekday=2,time='11:15')
    run_daily(market_buy, time='11:15')
    # run_daily(market_buy, time='14:45')

    # 最强指数涨了多少，可以开仓
    g.dapan_threshold =0
    g.signal= 'BUY'
    g.niu_signal = 1 # 牛市就上午开仓，熊市就下午
    g.position = 1
    # 基金上市了多久可以买卖
    g.lag1 =20
    g.decrease_days = 0 
    g.increase_days = 0 
    # bbi动量的单位
    g.unit = '30m'
    # g.bond = '511880.XSHG'
    g.zs_list = [
        '000001.XSHG', # 上证
        '399001.XSHE', # 深成指
        '399006.XSHE', # 创业板指数
        '000852.XSHG', # 中证1000指数
        '000015.XSHG'# 红利指数
        ]
      # 指数、基金对, 所有想交易的etf都可以，会自动过滤掉交易时没有上市的
    g.ETF_list =  {
      
        '399905.XSHE':'159902.XSHE',#中小板指
        '399632.XSHE':'159901.XSHE',#深100etf
        '000016.XSHG':'510050.XSHG',#上证50
        '000010.XSHG':'510180.XSHG',#上证180
        
        '000852.XSHG':'512100.XSHG',#中证1000etf
        '399295.XSHE':'159966.XSHE',# 创蓝筹
        '399958.XSHE':'159967.XSHE',# 创成长
        '000015.XSHG':'510880.XSHG',#红利ETF
        '399324.XSHE':'159905.XSHE',#深红利
        '399006.XSHE':'159915.XSHE',#创业板
        '000300.XSHG':'510300.XSHG',#沪深300
        '000905.XSHG':'510500.XSHG',#中证500
        '399673.XSHE':'159949.XSHE',#创业板50
        '000688.XSHG':'588000.XSHG'#科创50

    }
    g.not_ipo_list = g.ETF_list.copy()
    g.available_indexs = []
    
##  交易！
def market_buy(context):
    log.info(context.current_dt.hour)
    
    # for etf in g.ETF_targets:
    df_index = pd.DataFrame(columns=['指数代码', '周期动量'])
    # 判断四大指数是否值得开仓
    df_incre = pd.DataFrame(columns=['大盘代码','周期涨幅','当前价格'])


    unit =g.unit
    BBI2 = BBI(g.available_indexs, check_date=context.current_dt, timeperiod1=3, timeperiod2=6, timeperiod3=12, timeperiod4=24,unit=unit,include_now=True)
    
    for index in g.available_indexs:
        df_close = get_bars(index, 1, unit, ['close'],  end_dt=context.current_dt,include_now=True,)['close']

        val =   BBI2[index]/df_close[0]
        
        df_index = df_index.append({'指数代码': index, '周期动量': val}, ignore_index=True)
    
    df_index.sort_values(by='周期动量', ascending=False, inplace=True)
    log.info(df_index)
    
    target = df_index['指数代码'].iloc[-1]
    target_bbi = df_index['周期动量'].iloc[-1]
    
    
    for index in g.zs_list:
        df_close = get_bars(index, 2, '1d', ['close'],  end_dt=context.current_dt,include_now=True,)['close']
        if len(df_close)>1:
            
            increase = (df_close[1] - df_close[0]) / df_close[0]
            df_incre = df_incre.append({'大盘代码': index, '周期涨幅': increase,'当前价格':df_close[0]}, ignore_index=True)
    
    df_incre.sort_values(by='周期涨幅', ascending=False, inplace=True)
    
    today_increase = df_incre['周期涨幅'].iloc[0]
    today_index_code = df_incre['大盘代码'].iloc[0]
    today_index_close = df_incre['当前价格'].iloc[0]
    
    # # update_niu_signal(context,today_index_code)
    # if(context.current_dt.hour == 11 and g.niu_signal == 0 and g.signal == 'BUY')    or (context.current_dt.hour == 14 and g.niu_signal == 1):
    #     log.info('牛熊不匹配，这个时间点不能开仓')
    #     return
     
    if(today_increase>g.dapan_threshold and target_bbi<1):
        g.signal = 'BUY'
        g.increase_days+=1
        
    else:
        g.signal = 'CLEAR'
        g.decrease_days+=1
        
        
    
    
    
  
        
    holdings = set(context.portfolio.positions.keys())  # 现在持仓的
    
    log.info("-------------increase_days----------- %s" % (g.increase_days))
    log.info("-------------decrease_days----------- %s" % (g.decrease_days))
    target_etf = g.ETF_list[target]
    

    if(g.signal == 'CLEAR'):
        
        for etf in holdings:
            
            log.info("----~~~---指数集体下跌，卖出---~~~~~~-------- %s" % (etf))
              
            order_target(etf, 0)
            # order_value(g.bond,context.portfolio.available_cash)
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
        order_value(target_etf,context.portfolio.available_cash*g.position)
    


def get_before_after_trade_days(date, count, is_before=True):
    """
    来自： https://www.joinquant.com/view/community/detail/c9827c6126003147912f1b47967052d9?type=1
    date :查询日期
    count : 前后追朔的数量
    is_before : True , 前count个交易日  ; False ,后count个交易日
    返回 : 基于date的日期, 向前或者向后count个交易日的日期 ,一个datetime.date 对象
    """
    all_date = pd.Series(get_all_trade_days())
    if isinstance(date, str):
        date = datetime.datetime.strptime(date, '%Y-%m-%d').date()
    if isinstance(date, datetime.datetime):
        date = date.date()

    if is_before:
        return all_date[all_date <= date].tail(count).values[0]
    else:
        return all_date[all_date >= date].head(count).values[-1]
def make_sure_etf_ipo(context):
    if len(g.not_ipo_list) == 0:
        return 
    idxs = []
    # 确保交易标的已经上市g.lag1个交易日以上
    yesterday = context.previous_date
    list_date = get_before_after_trade_days(yesterday, g.lag1)  # 今天的前g.lag1个交易日的日期
  
    all_funds = get_all_securities(types='fund', date=yesterday)  # 上个交易日之前上市的所有基金
    all_idxes = get_all_securities(types='index', date=yesterday)  # 上个交易日之前就已经存在的指数
    for idx in g.not_ipo_list:
        if idx in all_idxes.index:
            if all_idxes.loc[idx].start_date <= list_date:  # 指数已经在要求的日期前上市
                symbol = g.not_ipo_list[idx]
                if symbol in all_funds.index:
                    if all_funds.loc[symbol].start_date <= list_date:  # 对应的基金也已经在要求的日期前上市
                        g.available_indexs.append(idx)  # 则列入可交易对象中
                        idxs.append(idx) #后面删掉这一条，下次就不用折腾了
    for idx in idxs:
        del g.not_ipo_list[idx]
    log.info(g.not_ipo_list)
    return

# 短均线金叉，强势期，上午交易
def update_niu_signal(context,index):
    include_now = True
    unit='1d'
    # df_close = get_bars(index, 1, '1d', ['close'],  end_dt=context.current_dt,include_now=include_now,)['close']

    ema_short = EMA(index,context.current_dt, timeperiod=5, unit = unit, include_now =include_now, fq_ref_date = None)[index]
    ema_middle = EMA(index,context.current_dt, timeperiod=20, unit = unit, include_now =include_now, fq_ref_date = None)[index]
    ema_long = EMA(index,context.current_dt, timeperiod=60, unit = unit, include_now =include_now, fq_ref_date = None)[index]
    
   
    if ema_short> ema_middle>ema_long:
        g.position = 1
        
    elif ema_short< ema_middle<ema_long:    
        
        g.niu_signal = 0
    else:
        
        g.niu_signal = 1






