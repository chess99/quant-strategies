# 克隆自聚宽文章：https://www.joinquant.com/post/40259
# 标题：回测“一创模拟盘2号”，最终优化，年化39%
# 作者：P5张大猫

# 221116这段代码配合策略生成代码使用，实现策略的执行，具体规则详见策略生成代码
# 221117：完善止盈策略，改为持有后X天，历史最高点回撤5%完善止盈策略
# 221118：增加统计DF，统计每次止盈止损的效果
# 221220：
# 1.用布林线持有的代码，改造而来，核心逻辑还是读取信号文件，然后进行建仓和调仓
# 2.增加牛熊高度的股债平衡算法
# 3.增加一个卖出历史df，更新某只股票的最新卖出时间，防止短期内重复买入

# 221222:增加最短持有期的限制，比如建仓后，至少持有5天后才能卖出

# 230216：修改为原版的持有思路：
# 1.根据动量因子作为牛市、熊市的转向信号（对比当前分钟级指数与历史10天均值的差异）
# 2.如果是牛市，则满仓；如果是熊市，则股票仓位30%，债券70%
# 3.个股没有回撤止盈，只是判断当前持仓列表与目标持仓列表的差异，退出则个股清仓，否则就继续持有（或者根据牛熊比例调整仓位）

# 230217：针对一创模拟盘2号的策略，继续优化持有策略
# 1.重新写了牛熊转换时的调仓逻辑，保证覆盖了各种可能性
# 2.对比原版，发现差别在于牛熊判断必须采用分钟级数据，如果以前一天的收盘价为依据则可能得到完全相反的结论！
# 另外，即便完全拷贝原始代码，年化也只拿到了47%而非74%，可能对于这种高频交易策略而言，很小的代码改动
# （信号生成、分钟级的牛熊判断，代码执行时间点），长时间运行都会导致天差地别的效果。故还是要回到自己能理解的选股和持股策略中。

# 导入函数库
from jqdata import *
from jqfactor import *
import pandas as pd
import numpy as np
from jqdata import finance
import math
import time
from six import BytesIO

# 初始化函数，设定基准等等
def initialize(context):
    # 最大持仓数量
    g.max_stock_count = 5
    
    # 牛熊函数对应参数
    g.MA = ['399008.XSHE', 10] # 均线择时，中小300指数
    g.threshold = 0.003 # 牛熊切换阈值
    g.isbull = False # 是否牛市
    g.bearpercent = 0.5 # 熊市仓位 original=30%
    

    # 买入后，最短持仓时间，才能卖出
    g.hold_interval = 10
    # 距离最近一次卖出时间大于N天，才能再次买入
    g.selldate_interval = 5
    # 最高点回撤5%离场
    g.top_withdraw_ratio =0.03
    
    
    # 要操作的债券
    g.bond = '511010.XSHG'

    # 用这个DF做统计
    g.statistics_df= pd.DataFrame(columns=['code','name','date_buy','price_buy','date_sell','price_sell','ratio','result'])
    
    # 用这个df做卖出的历史记录，防止短期内再买入
    g.sell_history_df= pd.DataFrame(columns=['code','name','last_date_sell'])
    
    #翻译中文名称用，一次性读到内存里面，提高效率 
    g.stocks_allnames_df = get_all_securities()
    
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')

    ### 股票相关设定 ###
   
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
   ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）

      # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
      # 开盘时运行
    run_daily(market_open, time='14:55', reference_security='000300.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')

## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    # log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))
    # 占位，省了报错
    test = 0

    

## 开盘时运行函数
def market_open(context):
    # log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    date = context.current_dt.strftime("%Y-%m-%d")
    # 判断牛熊趋势
    get_bull_bear_signal_minute()

    # 建仓程序
    buy_df = get_df_fromfile(context)
    buylist = buy_df['code'].tolist()
    if len(buylist) == 0:
        log.info('当日无建仓信号')
    else:
        # print(buylist, type(buylist))
        log.info('今日建仓列表:'+ str(buy_df))
        # 调仓
        adjust_position(context, buylist)


 
    

## 收盘后运行函数
def after_market_close(context):
    # log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    # trades = get_trades()
    # for _trade in trades.values():
    #     log.info('成交记录：'+str(_trade))
    log.info('############################一天结束###############################')
    

def on_strategy_end(context):
    date = context.current_dt.strftime("%Y-%m-%d")
    log.info('策略执行结束总资产 = ' + str(context.portfolio.total_value))
    
    
    
    # ******************************************************************************#
    # ******************************************************************************# 
    # ******************************************************************************# 
    # ****************************核心函数都在下面**********************************# 
    # ******************************************************************************# 
    # ******************************************************************************# 
    # ******************************************************************************# 
# 函数2：获取当天的买入信号CSV文件，读取到df中，返回待买入股票列表的df
def get_df_fromfile(context):
    date = context.current_dt.strftime("%Y-%m-%d")
    file_name = '8.Mutifactors/Signal_for_trade_' + date + '.csv'
    log.info('读取买入信号文件：'+ str(file_name))
    result_df=pd.read_csv(BytesIO(read_file(file_name)))
        
    return result_df

                
# 调仓函数，输入是股票list，自动完成调仓操作
def adjust_position(context, buylist):
    date = context.current_dt.strftime("%Y-%m-%d")
    # 第一步：先对比持仓列表与目标列表，把已经退出目标列表的股票清仓,同时也需要达到止盈要求
    for stock in context.portfolio.positions.keys():
        # 计算历史最大回撤
        yesterday = context.previous_date
        avg_cost = context.portfolio.positions[stock].avg_cost
        current_price = context.portfolio.positions[stock].price
        buy_in_date = context.portfolio.positions[stock].init_time.strftime('%Y-%m-%d')
        df_price = get_price(stock, start_date=buy_in_date, end_date=yesterday, frequency='daily', fields=['open', 'high','close'])
        # 最终盈亏比例
        final_profit_ratio = (current_price/avg_cost) - 1
        max_price = df_price['close'].max()
        # 注意别把债券仓位给清了，同时要判断持仓天数限制
        if ((stock != g.bond) and (stock not in buylist) and \
            (current_price > avg_cost) and ((1-(current_price / max_price)) > g.top_withdraw_ratio)):
            cname = get_stock_name(stock)
            order_target_value(stock, 0)
            log.info('个股止盈成功：O(∩_∩)O哈哈~O(∩_∩)O哈哈~ '+str(stock) + str(cname) + '     盈利比例：'+ str(round(final_profit_ratio*100,2)) +'%')
            continue
        # 如果无法止盈，则持股到期后清仓
        if ((stock != g.bond) and (stock not in buylist) and (check_hold_interval(context,stock,g.hold_interval))):
            cname = get_stock_name(stock)
            order_target_value(stock, 0)
            log.info('个股到期清仓： '+str(stock) + str(cname) + '     盈利比例：'+ str(round(final_profit_ratio*100,2)) +'%')
        
    
    # 第二步：判断是否为牛熊转换点，调整现有持仓的股债比例
    # 如果当前趋势为牛市，则股票仓位100%
    if g.isbull:
        log.info('当日牛市，股票满仓')
        mkt_ratio = 1
    # 如果是熊市，则股票仓位30%
    else:
        log.info('当日熊市，股债搭配')
        mkt_ratio = g.bearpercent
    
    # 获取当期总市值
    total_value = round(context.portfolio.total_value,2)
    # 股票目标仓位，要么是满仓，要么是30%
    positions_value_stock = round((total_value * mkt_ratio),2)

    # 债券目标仓位，去掉股票之后的剩余部分
    positions_value_bond = round(total_value - positions_value_stock,2)

    ratio_stock = round((positions_value_stock / total_value),4)
    ratio_bond = round((1 - ratio_stock),4)

    # # 如果遇到熊市，则先把所有股票仓位都清了，再重新买入债券，再买入股票（会有手续费的损失），这段代码逻辑有误，会在连续熊市时持续清仓
    # if g.isbull == False:
    #     for stock in context.portfolio.positions.keys():
    #         if stock != g.bond:
    #             cname = get_stock_name(stock)
    #             order = order_target_value(stock, 0)
    #             log.info('熊市个股清仓成功： '+str(stock) + str(cname) ) 
    
    #如果是牛转熊（当前是熊，且前面是牛（历史仓位无债券）），则降低股票，提高债券 
    if ((g.isbull == False) and (g.bond not in context.portfolio.positions)):
        log.info('牛转熊，触发股债平衡，股票比例：'+ str(ratio_stock * 100) +'%,目标仓位: '+ str(positions_value_stock) \
                    + '; 债券比例:' +str(ratio_bond * 100) +'%,目标仓位: '+ str(positions_value_bond))
        # 先将现有持仓股票等比例卖出，才能买入债券
        for stock in context.portfolio.positions.keys():
            cname = get_stock_name(stock)
            target_value = context.portfolio.positions[stock].value * g.bearpercent
            order = order_target_value(stock, target_value)
            log.info('牛转熊，个股减仓成功： '+str(stock) + str(cname) )    
        # 个股减仓后，再买入债券仓位
        order_target_value(g.bond, positions_value_bond)
        log.info('牛转熊，债券建仓成功：' + str(positions_value_bond))
    
    # 如果是熊转牛（当前是牛，且前面是熊（历史仓位有债券）），则先清仓债券，再给现有持仓股票增加比例
    if((g.isbull == True) and (g.bond in context.portfolio.positions)):
        log.info('熊转牛，触发股债平衡，股票比例：'+ str(ratio_stock * 100) +'%,目标仓位: '+ str(positions_value_stock) \
                    + '; 债券比例:' +str(ratio_bond * 100) +'%,目标仓位: '+ str(positions_value_bond))        
        # 先清仓债券
        order_target_value(g.bond, 0)
        log.info('熊转牛，债券清仓成功： ' )  
        # 再把现有股票仓位补回来
        for stock in context.portfolio.positions.keys():
            cname = get_stock_name(stock)
            # 现有仓位 /0.3，就是目标仓位
            target_value = context.portfolio.positions[stock].value / g.bearpercent
            order_target_value(stock, target_value)
            log.info('熊转牛，个股补仓成功： '+str(stock) + str(cname) )   
        

    # 第三步，如果还有空余仓位，则买入新的股票
    # 排除债券仓位的干扰，计算当前股票仓位数量
    if g.bond in context.portfolio.positions:
        stock_position_count = len(context.portfolio.positions) -1
    else:
        stock_position_count = len(context.portfolio.positions)
    log.info('当前股票仓位数量：'+ str(stock_position_count))
    
    if stock_position_count < g.max_stock_count:
        value = context.portfolio.available_cash / (g.max_stock_count - stock_position_count)
        # 遍历建仓列表，如果没有持仓，就建仓
        for stock in buylist:
            if (stock not in context.portfolio.positions) and (check_selldate_interval(date,stock)):
                cname = get_stock_name(stock)
                order = order_target_value(stock, value)
                log.info('新增股票建仓成功： '+str(stock) + str(cname) + '目标仓位： ' + str(value))
                # 还需要排除债券仓位的影响
                if g.bond in context.portfolio.positions:
                    if len(context.portfolio.positions) == (g.max_stock_count+1):
                            break
                else:
                    if len(context.portfolio.positions) == (g.max_stock_count):
                            break
    else:
        log.info('当前股票仓位数量：'+ str(stock_position_count) + '     仓位已满，无法建仓 ┭┮﹏┭┮')


# 函数，检验某只股票距离上次卖出时间是否大于N天  
# selldate_interval
def check_selldate_interval(date,code):
    if code in g.sell_history_df.values:
        last_date_sell = g.sell_history_df.loc[(g.sell_history_df.code == code)].last_date_sell.values
        print(g.sell_history_df)
        print('last_date_sell:',last_date_sell)
        start =str(last_date_sell)
        end =date
        start = time.mktime(time.strptime(start,'[%Y-%m-%d]'))
        end = time.mktime(time.strptime(end,'%Y-%m-%d'))
        count_days = int((end - start)/(24*60*60))
        if count_days < g.selldate_interval:
            log.info('距离最近卖出时间为：'+ str(count_days) +'天,无法再次购买:'+ str(code))
            return False
        else:
            log.info('距离最近卖出时间为：'+ str(count_days) +'天,可以再次购买:'+ str(code))
            return True
    
    else:
        log.info('卖出历史中无记录，可以建仓:'+ str(code))
        return True

# 函数，检验某只股票买入后持有时间是否足够  
# g.hold_interval = 5
def check_hold_interval(context,code,hold_interval):
    # 此股票的建仓时间
    init_time = context.portfolio.positions[code].init_time
    # date
    current_date = context.current_dt
    start = init_time
    end = current_date
    cname = get_stock_name(code)
    # print('start:',start,type(start))
    # print('end:',end,type(end))
    count_days = (end - start).days
    # print('count_days:',count_days,type(count_days))
    if count_days > hold_interval:
        log.info('持仓时间为：' + str(count_days)+ '天，可以卖出，code：' + str(code) + str(cname))
        return True
    else:
        log.info('持仓时间仅为：' + str(count_days)+ '天，拒绝卖出，code：' + str(code) + str(cname))
        return False



# 获取前n个单位时间当时的收盘价
def get_close_price(security, n, unit='1d'):
    return attribute_history(security, n, unit, 'close')['close'][0]            
# 恢复为原版分钟级数据，否则会得到相反的结论！
def get_bull_bear_signal_minute():
    # 中小300指数的最近1分钟数据
    nowindex = get_close_price(g.MA[0], 1, '1m')
    # 中小300指数的（过去10日收盘价+当前最新价格）的均值
    MAold = (attribute_history(g.MA[0], g.MA[1] - 1, '1d', 'close', True)['close'].sum() + nowindex) / g.MA[1]
    if g.isbull:
        if nowindex * (1 + g.threshold) <= MAold:
            g.isbull = False
    else:
        # 当前指数价格高于历史均值比例超过阈值时，则为牛市
        if nowindex > MAold * (1 + g.threshold):
            g.isbull = True
            
# 返回单只股票的中文名称，为了提高效率，改为一开始做一个g变量
def get_stock_name(stock_code):
    if g.stocks_allnames_df.loc[g.stocks_allnames_df.index == stock_code].empty:
        stock_name = '名称未知'
    else:
        stock_name = g.stocks_allnames_df.loc[g.stocks_allnames_df.index == stock_code]['display_name'][0]
    return stock_name  
    
    


# # 基于指数的动量趋势判断牛熊方向，而非历史分位
# def get_bull_bear_signal_minute():
#     # 中小300指数的最近1分钟数据
#     nowindex = attribute_history(g.MA[0], 1, '1m', 'close')['close'][0]
#     # 中小300指数的（过去10日收盘价+当前最新价格）的均值
#     MAold = (attribute_history(g.MA[0], g.MA[1] - 1, '1d', 'close', True)['close'].sum() + nowindex) / g.MA[1]
#     if g.isbull:
#         if nowindex * (1 + g.threshold) <= MAold:
#             log.info('今日趋势转熊')
#             g.isbull = False
#     else:
#         # 当前指数价格高于历史均值比例超过阈值时，则为牛市
#         if nowindex > MAold * (1 + g.threshold):
#             log.info('今日趋势转牛')
#             g.isbull = True


