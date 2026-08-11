# 克隆自聚宽文章：https://www.joinquant.com/post/42256
# 标题：[原创]价值投资+期货对冲V4.0,无惧市场大跌
# 作者：Eddie79163

# 引入库函数
import numpy as np
import pandas as pd
import datetime as dt
from jqdata import *
# 导入函数库
#from jqdata import *
from jqlib.technical_analysis  import *
#import pandas as pd
from jqfactor import get_factor_values
import numpy as np
import warnings

def initialize(context):
    # 设置系统
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    g.benchmark = '000905.XSHG'
    set_benchmark(g.benchmark)
    # 设置信息格式
    log.set_level('order', 'error')
    pd.set_option('display.max_rows', 100)
    pd.set_option('display.max_columns', 10)
    pd.set_option('display.width', 500)
    
    
    #设置初始账户资金分配
    g.stock_share = 0.7#指增子账户占总账户资金比例
    g.future_share = 0.3#期货子账户占总账户资金比例
    g.future_position = 0.35 #期货持仓所需保证金占用的期货子账户资金比例
    set_subportfolios([SubPortfolioConfig(cash=context.portfolio.starting_cash * g.stock_share, type='stock'),
                       SubPortfolioConfig(cash=context.portfolio.starting_cash * g.future_share, type='futures')])
    
    
    # 设置策略
    run_daily(handle_trader,time='13:45')# weekday=1,,force=True) #weekday=1,
    # 设置参数
    g.index = '399317.XSHE' #投资指数
    g.num = 5 #选股数
    g.stocks = [] #股票池
    
    ### 期货相关设定 ###~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    g.future_type = 'IC'
    g.futures_margin_rate = 0.15#保证金比例(现在好像是14%，懒得改了)
    g.unitprice = 200 
    g.long_days = 5 # 几日均线以下开空
    g.short_days = 2 # 几日以上均线开多
    
    #ATR止损模块参数
    g.ATRdays = 20 #计算ATR的时间区间长度
    g.boundrydays  = 5#计算最高最低价格的区间长度
    g.stop = 5 # ATR止损倍数
    
    #根据短期ATR和长期ATR的差确定波动率volatility。如果 短ATR-para*长ATR，表明即将变盘，可适当仓位重
    g.shortdays = 20
    g.longdays = 50
    g.para = 1
    
    # 期货类每笔交易时的手续费是：买入时万分之0.23,卖出时万分之0.23,平今仓为万分之0.23
    set_order_cost(OrderCost(open_commission=0.000023, close_commission=0.000023,close_today_commission=0.0023), type='index_futures')
    # 设定保证金比例
    set_option('futures_margin_rate', g.futures_margin_rate)
    # 设置期货交易的滑点
    set_slippage(StepRelatedSlippage(2))

    # 设置样本序列长度、模型占位、拟合模型时间间隔、时间计数
    g.day = 20#每个月期货到期，20日为一个周期
    g.day_count = int(g.day)
    g.k = 1#初始交易期货手数
    ### 期货相关设定 ###~~~~~~~~~~~~~~~~~~~~~
    
    ### 期货交易运行 ###~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # 开盘前运行
    run_daily( before_market_open_future, time='9:00', reference_security='IF8888.CCFX')
    # 开盘时运行
    #run_daily( market_trade_future, time='11:25', reference_security='IF8888.CCFX')
    
    #run_daily( market_trade_future, time='9:45', reference_security='IF8888.CCFX')
    #run_daily( market_trade_future, time='10:00', reference_security='IF8888.CCFX')
    #run_daily( market_trade_future, time='10:15', reference_security='IF8888.CCFX')
    #run_daily( market_trade_future, time='10:30', reference_security='IF8888.CCFX')
    #run_daily( market_trade_future, time='10:45', reference_security='IF8888.CCFX')
    #run_daily( market_trade_future, time='11:00', reference_security='IF8888.CCFX')
    run_daily( market_trade_future, time='11:15', reference_security='IF8888.CCFX')
    #run_daily( market_trade_future, time='13:00', reference_security='IF8888.CCFX')
    #run_daily( market_trade_future, time='13:15', reference_security='IF8888.CCFX')
    #run_daily( market_trade_future, time='13:30', reference_security='IF8888.CCFX')
    #run_daily( market_trade_future, time='13:45', reference_security='IF8888.CCFX')
    #run_daily( market_trade_future, time='14:00', reference_security='IF8888.CCFX')
    #run_daily( market_trade_future, time='14:15', reference_security='IF8888.CCFX')
    #run_daily( market_trade_future, time='14:30', reference_security='IF8888.CCFX')
    #run_daily( market_trade_future, time='14:45', reference_security='IF8888.CCFX')
    

    ### 期货交易运行 ###~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    
    

def handle_trader(context):
    # 按年更新
    if context.current_dt.month in [5]:
        g.stocks = choice_stocks(context, g.index, g.num)
    # 卖出
    cdata = get_current_data()
    for s in context.portfolio.positions:
        if s not in g.stocks and not cdata[s].paused:
            log.info('sell', s, cdata[s].name)
            order_target(s, 0)
    # 买进
    position = 0.99*context.portfolio.total_value / max(1, len(g.stocks))
    for s in g.stocks:
        if s not in context.portfolio.positions and not cdata[s].paused and\
            context.portfolio.available_cash > position:
            log.info('buy', s, cdata[s].name)
            order_value(s, position)

def choice_stocks(context, index, num):
    # 股票池
    stocks = get_index_stocks(index)
    #stocks = ['601288.XSHE','601988.XSHE','601328.XSHG','601398.XSHG','601658.XSHG','600016.XSHG','601939.XSHG','601818.XSHG']
    # 提取市值，基本面过滤
    sdf = get_fundamentals(query(
            valuation.code,
            valuation.market_cap, #单位，亿元
        ).filter(
            valuation.code.in_(stocks),
            valuation.pb_ratio <3,
            valuation.pb_ratio > 0.0,
            #indicator.gross_profit_margin>0,
            #indicator.pcf_ratio >0,
            indicator.roe>0.1,
            balance.cash_equivalents>0.4*balance.shortterm_loan,
            indicator.roa>0.05*indicator.roe,
            balance.total_assets/balance.total_liability>1,
            indicator.roa>0,
            valuation.pe_ratio > 0,
            valuation.ps_ratio > 0,
            #valuation.pe_ratio < 30,
            valuation.pcf_ratio > 0,
            indicator.inc_revenue_year_on_year >10,
            indicator.inc_net_profit_to_shareholders_year_on_year >10,
            #valuation.pb_ratio > 0.15*valuation.pe_ratio,#市净率
        )).dropna().set_index('code')
    stocks = list(sdf.index)
    #log.info('选股', stocks)
    # 最近三年的股息
    dt_3y = context.current_dt.date() - dt.timedelta(days=3*365)
    ddf = finance.run_query(query(
            finance.STK_XR_XD.code,
            finance.STK_XR_XD.company_name,
            finance.STK_XR_XD.board_plan_pub_date,
            finance.STK_XR_XD.bonus_amount_rmb, #单位，万元
        ).filter(
            finance.STK_XR_XD.code.in_(stocks),
            finance.STK_XR_XD.board_plan_pub_date > dt_3y,
            finance.STK_XR_XD.bonus_amount_rmb > 0
        )).dropna()
    stocks = list(set(ddf.code))
    # 累计分红
    divy = pd.Series(data=zeros(len(stocks)), index=stocks)
    for k in ddf.index:
        s = ddf.code[k]
        divy[s] += ddf.bonus_amount_rmb[k]
    # 建立数据表
    sdf = sdf.reindex(stocks)
    sdf['div_3y'] = divy
    # 计算股息率
    sdf['div_ratio'] = 1e-2 * sdf.div_3y / sdf.market_cap
    # report
    sdf['name'] = [get_security_info(s).display_name for s in sdf.index]
    sdf = sdf.sort_values(by='div_ratio', ascending=False)
    log.info('\n', sdf[:5])
    return list(sdf.head(num).index)
# end



'''
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
资金划转代码
'''
#对冲比例调整+账户间资金划转
def rebalance(context):
    # 计算资产总价值
    total_value = context.portfolio.total_value
    # 计算预期的股票账户价值
    expected_stock_value = total_value * g.stock_share
    
    # 将两个账户的钱调到预期的水平
    transfer_cash(1, 0, min(context.subportfolios[1].transferable_cash, max(0, expected_stock_value-context.subportfolios[0].total_value)))
    transfer_cash(0, 1, min(context.subportfolios[0].transferable_cash, max(0, context.subportfolios[0].total_value-expected_stock_value)))

    # 计算股票账户价值（预期价值和实际价值其中更小的那个）
    stock_value = min(context.subportfolios[0].total_value, expected_stock_value)
    
    
'''
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
CTA部分代码
'''   

## 开盘前运行函数
def before_market_open_future(context):
    
    # 获取当月合约
    g.code_1 = get_future_contracts(g.future_type)[0]
    
    # 交割日
    de_day = get_CCFX_end_date(g.code_1)
    
    #判断是否交割日，确定下一月交易的手数
    if context.current_dt.date() == de_day:
        g.de_day = 1
        #资产全价值的15%（70%指增，30%的CTA，其中30%的50%为保证金专用）
        value = int(context.subportfolios[1].total_value) * g.future_position
        #用于交易头寸的保证金占用  
        margin = int(get_bars(g.benchmark, 1, '1d', ['close'],  end_dt=context.previous_date,include_now=True)['close'][0]) * g.unitprice * g.futures_margin_rate
        #计算最大持仓手数（保证金15%）最高不超过100手
        g.k = min(int(value / margin),100)
        log.info('手数',g.k)
        
    else:
        g.de_day = 0
  
    # 计数，每g.day天拟合一次
    if g.day_count == g.day:
        g.day_count = 0
    else:
        g.day_count += 1

#开盘时运行交易函数(波动率小开仓开1.2倍，波动率大开仓开0.8倍),外加止损模块
def market_trade_future(context):
    
    g.sign = update_niu_signal(context,g.benchmark)
    g.loss_stop = loss_stop(context,g.benchmark)
    g.volatility = volatility(context, g.benchmark)
    
    #如果波动率小，可以按1.5倍加仓；波动率大就正常
    if g.volatility == -1:
       future_position =  int(1.5 *g.k)
    elif g.volatility == 1:
        future_position =  int(1 *g.k)
        
    #开仓信号
    if (len(context.subportfolios[1].long_positions) == 0) & (len(context.subportfolios[1].short_positions) == 0):
        if g.sign > 0:
            order(g.code_1, future_position, side='long', pindex=1)
        elif g.sign < 0:
            order(g.code_1, future_position, side='short', pindex=1)

    #平仓信号
    elif (len(context.subportfolios[1].long_positions) + len(context.subportfolios[1].short_positions)) > 0:
        if g.de_day == 0:
            
            #止损：如果从最大收益处回撤g.stop倍ATR,则止损清仓
            if (len(context.subportfolios[1].long_positions) > 0) & (g.loss_stop == 1):
                order_target(g.code_1, 0, side='long',pindex=1)
            elif (len(context.subportfolios[1].short_positions) > 0) & (g.loss_stop == 1):
                order_target(g.code_1, 0, side='short',pindex=1)
            
            #平开仓：价格上穿或下穿ema线，调整仓位
            elif (len(context.subportfolios[1].long_positions) > 0) & (g.sign == 0):
                order_target(g.code_1, 0, side='long', pindex=1)
                order(g.code_1, future_position, side='short', pindex=1)
            elif (len(context.subportfolios[1].short_positions) > 0) & (g.sign > 0):
                order_target(g.code_1, 0, side='short', pindex=1)
                order(g.code_1, future_position, side='long', pindex=1)
       
        # 交割日平仓
        else:
            if len(context.subportfolios[1].long_positions) > 0:
                order_target(g.code_1, 0, side='long', pindex=1)
            else:
                order_target(g.code_1, 0, side='short', pindex=1)

#ATR波动率信号
def volatility(context,ind):
    ind=g.benchmark
    
    #ATR(security_list, check_date, timeperiod=14)
    current_ATR_a = ATR(ind,context.current_dt, g.shortdays)
    current_ATR_b = ATR(ind,context.current_dt, g.longdays)
    
    k = current_ATR_a[-1][ind] - g.para * current_ATR_b[-1][ind]
    
    if k < 0:
     volatility = -1 #波动率低，可重仓
    elif k > 0:
     volatility = 1 #波动率高，可轻仓
     
    return volatility
    
    
                
#ATR止损信号
def loss_stop(context,ind):
    include_now = True#表示读取当天的日K线
    unit='1d'
    ind=g.benchmark
    
    #ATR(security_list, check_date, timeperiod=14)
    current_ATR = ATR(ind,context.current_dt, g.ATRdays)
    close = get_bars(ind, 1, '1d', ['close'],  end_dt=context.current_dt,include_now=include_now)['close']
    
    high = max(get_bars(ind, g.boundrydays, unit, ['high'],  end_dt=context.previous_date,include_now=include_now)['high'])#5日最高
    low = min(get_bars(ind, g.boundrydays, unit, ['low'],  end_dt=context.previous_date,include_now=include_now)['low'])#5日最低
    
    if (len(context.portfolio.long_positions) > 0) & (close < high - g.stop * current_ATR[-1][ind]):
     loss_stop = 1 #多头止损
    elif (len(context.portfolio.short_positions) > 0) & (close > low + g.stop * current_ATR[-1][ind]):
     loss_stop = 1 #空头止损
    else:
     loss_stop = 0
     
    return loss_stop

#开平仓信号
def update_niu_signal(context,ind):
    include_now = True#表示读取当天的日K线
    unit='1d'

    #-------------------标的指数的5日均线，如果均线朝下表示趋势向下，暂停交易---------------
    ind=g.benchmark
    close = get_bars(ind, 1, '1d', ['close'],  end_dt=context.current_dt,include_now=include_now)['close']
    
    #当天获取5日均线
    current = EMA(ind,context.current_dt, timeperiod=g.long_days, unit = unit, include_now =include_now, fq_ref_date = None)[ind]

    #前一天的5日均线
    previous = EMA(ind,context.previous_date, timeperiod=g.long_days, unit=unit, fq_ref_date = None)[ind]

    #当天获取2日均线
    current_close = EMA(ind,context.current_dt, timeperiod=g.short_days, unit = unit, include_now =include_now, fq_ref_date = None)[ind]
    #当天获取2日均线
    previous_close = EMA(ind,context.previous_date, timeperiod=g.short_days, unit=unit, fq_ref_date = None)[ind]
    
    if close<current:#<previous:#当价格低于5日均线且5日均线空头排列的时候开空
     niu_signal = -1 #开仓数量=0
    elif close>current_close:#>previous_close:#当价格高于5日均线且5日均线多头排列的时候开多
     niu_signal = 1 #开仓数量=1
    else:
     niu_signal = 0
     
    return niu_signal    

# 获取金融期货合约到期日
def get_CCFX_end_date(future_code):
    # 获取金融期货合约到期日
    return get_security_info(future_code).end_date
