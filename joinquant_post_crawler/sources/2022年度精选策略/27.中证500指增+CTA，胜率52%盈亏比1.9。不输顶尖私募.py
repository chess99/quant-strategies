# 克隆自聚宽文章：https://www.joinquant.com/post/37685
# 标题：中证500指增+CTA，胜率52%盈亏比1.9。不输顶尖私募
# 作者：Jacobb75

# 导入函数库
from jqdata import *
from jqlib.technical_analysis  import *
import pandas as pd
from jqfactor import get_factor_values
import numpy as np
import warnings

# 初始化函数，设定基准等等
def initialize(context):
    # 设定中证500作为基准
    g.benchmark = '000905.XSHG'
    set_benchmark(g.benchmark)

    # 开启动态复权模式(真实价格)
    # 用真实价格交易
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    log.set_level('order', 'error')
    warnings.filterwarnings("ignore")
    
    #设置初始账户资金分配
    g.stock_share = 0.7#指增子账户占总账户资金比例
    g.future_share = 0.3#期货子账户占总账户资金比例
    g.future_position = 0.35 #期货持仓所需保证金占用的期货子账户资金比例
    set_subportfolios([SubPortfolioConfig(cash=context.portfolio.starting_cash * g.stock_share, type='stock'),
                       SubPortfolioConfig(cash=context.portfolio.starting_cash * g.future_share, type='futures')])


    ### 股票相关设定 ###~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    #选股参数
    g.stock_num = 20 # 持仓数
    ### 股票相关设定 ###~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    
    ### 期货相关设定 ###~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    g.future_type = 'IC'
    g.futures_margin_rate = 0.15#保证金比例(现在好像是14%，懒得改了)
    g.unitprice = 200 
    g.long_days = 6 # 几日均线以下开空
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
    ### 期货相关设定 ###~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    ### 股票交易运行 ###~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    run_monthly(my_select, monthday=-1, time='9:30', reference_security=g.benchmark)# 选股
    run_monthly(my_buy, monthday=-1, time='11:15', reference_security=g.benchmark)# 买入指数增强选出的股票
    run_monthly(my_sell, monthday=10, time='10:30', reference_security=g.benchmark)# 月中卖出调仓换股
    run_monthly(rebalance, monthday=10, time='11:00', reference_security=g.benchmark)# 股票和期货账户间资金划转
    ### 股票交易运行 ###~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
    

    ### 期货交易运行 ###~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


'''
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
指数增强部分代码
'''
# 开盘时运行函数
def my_select(context):
    # 获取选股列表并过滤掉:st,st*,退市,涨停,跌停,停牌
    check_out_list,g.position = get_stock_list(context)
    #log.info('今日自选股:%s' % check_out_list)
    #print("本月仓位：",g.position)
    return check_out_list


def my_sell(context):
    # 获取选股列表并过滤掉:st,st*,退市,涨停,跌停,停牌
    adjust_position_sell(context, my_select(context))
    
def my_buy(context):
    # 获取选股列表并过滤掉:st,st*,退市,涨停,跌停,停牌
    adjust_position_buy(context, my_select(context))


# 2-2 选股+仓位管理
# 选出资产负债率后20%且大于0，优质资产周转率前20%，roa改善最多的股票列表
def get_stock_list(context):
    # type: (Context) -> list
    curr_data = get_current_data()
    yesterday = context.previous_date
    df_stocknum = pd.DataFrame(columns=['当前符合条件股票数量'])
    # 过滤次新股
    #by_date = yesterday
    #by_date = datetime.timedelta(days=1200)
    by_date = yesterday - datetime.timedelta(days=1200)  # 三年
    initial_list = get_index_stocks('000905.XSHG',date=by_date)
    #initial_list = get_index_stocks('399311.XSHE',date=by_date) + get_index_stocks('399303.XSHE',date=by_date)

    #initial_list = get_all_securities(date=by_date).index.tolist()


    # 0. 过滤创业板，科创板，st，今天涨跌停的，停牌的
    initial_list = [stock for stock in initial_list if not (
            (curr_data[stock].day_open == curr_data[stock].high_limit) or
            (curr_data[stock].day_open == curr_data[stock].low_limit) or
            curr_data[stock].paused
            #curr_data[stock].is_st
            #('ST' in curr_data[stock].name) or
            #('*' in curr_data[stock].name) 
            #('退' in curr_data[stock].name) or
            #(stock.startswith('300')) or
            #(stock.startswith('688')) or
            #(stock.startswith('002'))
    )]
    
    #df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(initial_list)}, ignore_index=True)


    # 1，选出资产负债率由高到低后70%的，low_liability_list
    df = get_fundamentals(
        query(
            balance.code, balance.total_liability, balance.total_assets
            #balance.code, balance.total_non_current_liability,balance.total_non_current_assets
        ).filter(
            valuation.code.in_(initial_list)
        )
    ).dropna()
    #
    
    df = df.fillna(0)
    df['ratio'] = df['total_liability'] / df['total_assets']  # 资产负债率
    df = df.sort_values(by = 'ratio',ascending=False)
    
    low_liability_list = list(df.code)[int(0.3*len(list(df.code))):]
    #df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(low_liability_list)}, ignore_index=True)

  
    # 2，从low_liability_list中选出不良资产比率在总体中[20%-80%]范围内的的股票，proper_receivable_list
    df1 = get_fundamentals(
        query(balance.code,
              balance.total_assets,  # 总资产
              balance.bill_receivable,  # 应收票据
              balance.account_receivable,  # 应收账款
              balance.other_receivable,  # 其他应收款
              balance.good_will,  # 商誉
              balance.intangible_assets,  # 无形资产
              balance.inventories,  # 存货
              balance.constru_in_process,# 在建工程
              ).filter(
            balance.code.in_(low_liability_list)
        )
    ).dropna()
    
    df1 = df1.fillna(0)
    df1['bad_assets'] = df1.sum(axis=1) - df1['total_assets']   # 其中bad_assets占的比例
    df1['ratio1'] =  df1['bad_assets'] / df1['total_assets']
    df1 = df1.sort_values(by = 'ratio1',ascending=False)
    
    proper_receivable_list = list(df1.code)[int(0.1*len(list(df1.code))):int(0.9*len(list(df1.code)))]
    #df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(proper_receivable_list)}, ignore_index=True)
    
    
    # 3，从proper_receivable_list中选出优质资产周转率前75%的公司，proper_receivable_list1
    df2 = get_fundamentals(
        query(balance.code,
              balance.total_assets,  # 总资产
              balance.bill_receivable,  # 应收票据
              balance.account_receivable,  # 应收账款
              balance.other_receivable,  # 其他应收款
              balance.good_will,  # 商誉
              balance.intangible_assets,  # 无形资产
              balance.inventories,  # 存货
              balance.constru_in_process,# 在建工程
              income.total_operating_revenue# 营业收入
              ).filter(
            balance.code.in_(proper_receivable_list)
        )
    ).dropna()
   
    df2 = df2.fillna(0)
    df2['good_assets'] = df2['total_assets'] - (df2.sum(axis=1) - df2['total_assets'] - df2['total_operating_revenue'])  # 其中bad_assets占的比例
    df2['ratio2'] = df2['total_operating_revenue'] / df2['good_assets']
    df2 = df2.sort_values(by = 'ratio2',ascending=False)
    
    proper_receivable_list1 = list(df2.code)[:int(0.75*len(list(df2.code)))]
    #df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(proper_receivable_list1)}, ignore_index=True)

    
    # 4,从proper_receivable_list1中过去十二个季度ROA增长最多(前20%）的股票，按照ROA`增长量降序排列,roa_list
    df3 = get_history_fundamentals(
        proper_receivable_list1,
        fields=[indicator.code, indicator.roa],
        watch_date=yesterday,
        count=4,
        interval='1q'
    ).dropna()
   
    s_delta_avg = df3.groupby('code')['roa'].apply(
        lambda x: x.iloc[3]  - x.mean() if len(x) == 4 else 0.0 
        #lambda x: x.iloc[11]  - x.mean() if len(x) == 12 else 0.0 
    ).sort_values(
        ascending=False
    )
    
    roa_list = list(s_delta_avg[:int(0.2 * len(s_delta_avg))].index)
    #df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(roa_list)}, ignore_index=True)

    # 5.从过去五个季度ROA增长量前20%的股票中选出市净率大于0的按照资产负债率升序排列选出前g.stock_num个，final_list
    pb_list = get_fundamentals(
        query(
            valuation.code
        ).filter(
            valuation.code.in_(roa_list),
            #valuation.pb_ratio < 2,
            valuation.pb_ratio > 0.7,
            valuation.ps_ratio < 3,
            #valuation.ps_ratio > 0
            #indicator.ocf_to_operating_profit > 1,
            #indicator.eps > 0
            #indicator.roa
        ).order_by(
            valuation.pb_ratio.asc()
            #indicator.eps.desc()
            #valuation.circulating_market_cap.desc()
        )
    )['code'].tolist()
    indicator.ocf_to_operating_profit
    df_stocknum =  df_stocknum.append({'满足条件股票数量': len(pb_list)}, ignore_index=True)
    #print(df_stocknum)    
   
    final_list = pb_list[:g.stock_num]
    #position = 0.118 if len(pb_list) < 15 else 0.5 if len(pb_list) > 15 and len(pb_list) < 37 else 0.927# 仓位
    position = 1

    return final_list, position


def adjust_position_sell(context, buy_stocks):
    #order_value(g.bond,context.portfolio.available_cash)
    for stock in context.portfolio.positions:
        if stock not in buy_stocks:
            order_target(stock, 0)
            #print("卖出：", stock)
        
def adjust_position_buy(context, buy_stocks):
    position_count = len(context.portfolio.positions)
    if g.stock_num > position_count:
        value = context.portfolio.cash * g.position / (g.stock_num - position_count)
        for stock in buy_stocks:
            if stock not in context.portfolio.positions:
                order_target_value(stock, value)
                #print("买入：", stock)
                if len(context.portfolio.positions) == g.stock_num:
                    break

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
