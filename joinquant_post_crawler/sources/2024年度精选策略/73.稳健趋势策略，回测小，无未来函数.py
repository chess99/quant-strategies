# 克隆自聚宽文章：https://www.joinquant.com/post/43393
# 标题：稳健趋势策略，回测小，无未来函数
# 作者：语桐

import jqdata
from jqlib.technical_analysis  import *
from jqdata import *
import warnings

# 初始化函数
def initialize(context):
    # 滑点高（不设置滑点的话用默认的0.00246）
    set_slippage(FixedSlippage(0.02))
    # 国证A指数作为基准  
    set_benchmark('399317.XSHE') 
    # 用真实价格交易
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    warnings.filterwarnings("ignore")

    # 选股参数
    g.stock_num = 10 # 持仓数
    g.position = 1 # 仓位
    g.bond = '511880.XSHG'
    # 手续费
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0005, close_commission=0.0005, min_commission=5), type='stock')
     
    # 设置交易时间
    #run_weekly(my_trade, weekday=4, time='9:45', reference_security='000852.XSHG')
    run_monthly(my_trade, monthday=-4, time='11:30', reference_security='000852.XSHG')



# 开盘时运行函数
def my_trade(context):
    # 获取选股列表并过滤掉:st,st*,退市,涨停,跌停,停牌
    check_out_list = get_stock_list(context)
    log.info('今日自选股:%s' % check_out_list)
    adjust_position(context, check_out_list)


# 2-2 选股模块
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
    initial_list = get_all_securities(date=by_date).index.tolist()


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
    
    df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(initial_list)}, ignore_index=True)


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
    df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(low_liability_list)}, ignore_index=True)

  
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
    df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(proper_receivable_list)}, ignore_index=True)
    
    
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
    df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(proper_receivable_list1)}, ignore_index=True)

    
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
    df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(roa_list)}, ignore_index=True)
    
    
    '''
    # 4,从proper_receivable_list1中过去十二个季度ROA增长最多(前20%）的股票，按照ROA`增长量降序排列,roa_list
    df3 = get_history_fundamentals(
        proper_receivable_list1,
        fields=[indicator.code,
                income.total_profit, # 净利润
                balance.total_assets,  # 总资产
                balance.bill_receivable,  # 应收票据
                balance.account_receivable,  # 应收账款
                balance.other_receivable,  # 其他应收款
                balance.good_will,  # 商誉
                balance.intangible_assets,  # 无形资产
                balance.inventories,  # 存货
                balance.constru_in_process# 在建工程
                ],
        watch_date=yesterday,
        count=4,
        interval='1q'
    ).dropna()
   
       
    df3['ratio3'] = df3['total_profit'] / (df3['total_assets'] - (df3.sum(axis=1) - df3['total_assets'] - df3['total_profit']))
    
    s_delta_avg = df3.groupby('code')['ratio3'].apply(
        lambda x: x.iloc[3]  - x.mean() if len(x) == 4 else 0.0 
        #lambda x: x.iloc[11]  - x.mean() if len(x) == 12 else 0.0 
    ).sort_values(
        ascending=False
    )
    '''

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
    df_stocknum =  df_stocknum.append({'当前符合条件股票数量': len(pb_list)}, ignore_index=True)
    print(df_stocknum)    
    
    
    
    final_list = pb_list[:g.stock_num]
    return final_list
    
    '''
    last_list = pb_list[:g.stock_num]
    df_stock = pd.DataFrame(columns=['指数代码', '周期动量'])
    unit=g.unit
    BBI2 = BBI(last_list, check_date=context.current_dt, timeperiod1=3, timeperiod2=6, timeperiod3=12, timeperiod4=24,unit=unit,include_now=True)
    for stock in last_list:#运行中的指数
        df_close = get_bars(stock, 1, unit, ['close'],  end_dt=context.current_dt,include_now=True,)['close']
        #读取index当天的收盘价
        val =   BBI2[stock]/df_close[0]#BBI除以交易当天11:15分的价格，大于1表示空头，小于1表示多头
        df_stock = df_stock.append({'股票代码': stock, '周期动量': val}, ignore_index=True)#将数据写入df_index表格，索引重置
    #按'周期动量'进行从大到小的排列。ascending=true表示降序排列,ascending=false表示升序排序，inplace = True：不创建新的对象，直接对原始对象进行修改
    df_stock.sort_values(by='周期动量', ascending=False, inplace=True)
    final_list = df_stock['股票代码'].iloc[-1]#读取最后一行的股票代码
    return final_list
    '''

def adjust_position(context, buy_stocks):
    #order_value(g.bond,context.portfolio.available_cash)
    for stock in context.portfolio.positions:
        if stock not in buy_stocks:
            order_target(stock, 0)
        
    #
    position_count = len(context.portfolio.positions)
    if g.stock_num > position_count:
        value = context.portfolio.cash * g.position / (g.stock_num - position_count)
        for stock in buy_stocks:
            if stock not in context.portfolio.positions:
                order_target_value(stock, value)
                if len(context.portfolio.positions) == g.stock_num:
                    break
                
                
                
                
