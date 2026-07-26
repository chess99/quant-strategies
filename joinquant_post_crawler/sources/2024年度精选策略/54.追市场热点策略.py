# 克隆自聚宽文章：https://www.joinquant.com/post/42186
# 标题：追市场热点策略
# 作者：养家大哥

# 导入函数库
from jqdata import *
from jqlib.technical_analysis import *
import pandas as pd

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    #log.set_level('order', 'error')

    g.stock_num = 3
    g.hold_list = [] #当前持仓的全部股票    
    g.yesterday_HL_list = [] #记录持仓中昨日涨停的股票
    g.candidate_list = []
    g.buy1_stock_lists = []
    g.buy2_stock_lists = []
    
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
    run_weekly(weekly_prepare_stock, 1, time='7:00', reference_security='000300.XSHG')

    # 开盘时刻准备
    run_daily(prepare_stock_list, time='9:30', reference_security='000300.XSHG')
    # 开盘时刻卖出下跌股票
    run_daily(my_trade_sell, time='9:30', reference_security='000300.XSHG')
    # 中午卖出下跌股票
    run_daily(my_trade_sell, time='13:30', reference_security='000300.XSHG')
    # 中午卖出前一天未涨停
    run_daily(check_limit_up, time='13:30', reference_security='000300.XSHG')
    # 早上买入股票
    run_daily(my_trade_buy1, time='9:31', reference_security='000300.XSHG')
    # 中午买入股票
    run_daily(my_trade_buy2, time='13:31', reference_security='000300.XSHG')
    # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')


#1-1 准备股票池，每周更换一次
def weekly_prepare_stock(context):
    candidate_list = []
    yes_day = context.previous_date
    #通过申万的股票分类
    df = get_industries(name='sw_l2', date=yes_day)
    #df = get_concepts()
    df['score'] = -100000
    df['nums'] = 0
    drop_index = []
    for industry_index in df.index:
        check_out_lists = get_industry_stocks(industry_index, yes_day)
        df.loc[industry_index, 'nums'] = len(check_out_lists)
        if(len(check_out_lists)>=20):
            score = stock_sector_score(check_out_lists,10)
            df.loc[industry_index, 'score'] = score
        else:
            drop_index.append(industry_index)
    df = df.drop(drop_index)
    df = df.sort_values(by=['score'], ascending=False) #分数越高即预测未来收益越高，排序默认降序
    industry_indexs = df.index[0:5]
    for industry_index in industry_indexs:
        #log.info("%s : %s : 等分%0d : 数量%0d"%(industry_index, df.loc[industry_index, 'name'],
        #        df.loc[industry_index, 'score'], df.loc[industry_index, 'nums']))
        if(df.loc[industry_index, 'score']>500):
            check_out_lists = get_industry_stocks(industry_index, yes_day)
            candidate_list.extend(check_out_lists)
    candidate_list = list(set(candidate_list))
    candidate_list = filter_new_stock(context, candidate_list)
    candidate_list = filter_kcbj_stock(candidate_list)
    candidate_list = filter_st_stock(candidate_list)
    candidate_list = filter_paused_stock(candidate_list)
    candidate_list = find_strong_stock(context, candidate_list)
    candidate_num  = min(g.stock_num+10, len(candidate_list))
    g.candidate_list = candidate_list[:candidate_num]
    log.info("一周准备的股票LIST %0d,如下:"%(candidate_num))
    log.info(g.candidate_list)


#1-1 准备股票池
def prepare_stock_list(context):
    #获取已持有列表
    g.hold_list= []
    current_data = get_current_data()
    for position in list(context.portfolio.positions.values()):
        stock = position.security
        g.hold_list.append(stock)
    #获取昨日涨停列表
    if g.hold_list != []:
        df = get_price(g.hold_list, end_date=context.previous_date, frequency='daily',\
                       fields=['close','high_limit'], count=1, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        g.yesterday_HL_list = list(df.code)
    else:
        g.yesterday_HL_list = []
    #准备今日可以购买的股票
    g.buy1_stock_lists = []
    g.buy2_stock_lists = []
    candidate_list = find_strong_stock(context, g.candidate_list)
    candidate_list = candidate_list[:min(g.stock_num*2, len(candidate_list))]
    for stock in candidate_list:
        dt = attribute_history(stock, 1,'1d',['close','pre_close','open'])
        log.info("%s close=%0f, pre_close=%0f, pre_open=%0f, cur_open=%0d"\
                %(stock, dt.close[-1], dt.pre_close[-1], dt.open[-1],current_data[stock].day_open))
        if (dt.close[-1]>dt.pre_close[-1]*1.01 and dt.close[-1]>dt.open[-1] and\
            current_data[stock].day_open<dt.close[-1]*0.97):
            g.buy1_stock_lists.append(stock)
        else:
            g.buy2_stock_lists.append(stock)
    log.info("早上待买入的股票:",g.buy1_stock_lists)
    log.info("中午待买入的股票:",g.buy2_stock_lists)
        
##1-2 早上买入股票函数
def my_trade_buy1(context):
    # 根据股票数量分仓
    # 此处只根据可用金额平均分配购买，不能保证每个仓位平均分配
    buy_stocks = g.buy1_stock_lists[:]
    position_count = len(context.portfolio.positions)
    if g.stock_num > position_count:
        value = context.portfolio.cash / (g.stock_num - position_count)
        for stock in buy_stocks:
            if context.portfolio.positions[stock].total_amount == 0:
                if open_position(stock, value):
                    if len(context.portfolio.positions) == g.stock_num:
                        break

##1-3 中午买入股票函数
def my_trade_buy2(context):
    # 根据股票数量分仓
    # 此处只根据可用金额平均分配购买，不能保证每个仓位平均分配
    current_data = get_current_data()
    buy_stocks = g.buy2_stock_lists[:]
    position_count = len(context.portfolio.positions)
    if g.stock_num > position_count:
        value = context.portfolio.cash / (g.stock_num - position_count)
        for stock in buy_stocks:
            dt = attribute_history(stock, 1,'1d',['close'])
            log.info("%s close=%0f, last_price=%0f, high_limit=%0f"%(stock,\
                    dt.close[-1], current_data[stock].last_price, current_data[stock].high_limit))
            if current_data[stock].last_price>dt.close[-1]*1.01 and\
               current_data[stock].last_price<current_data[stock].high_limit and\
               context.portfolio.positions[stock].total_amount == 0:
                if open_position(stock, value):
                    if len(context.portfolio.positions) == g.stock_num:
                        break

#1-4 调整昨日涨停股票
def check_limit_up(context):
    now_time = context.current_dt
    if g.yesterday_HL_list != []:
        #对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
        for stock in g.yesterday_HL_list:
            current_data = get_price(stock, end_date=now_time, frequency='1m',\
                           fields=['close','high_limit'], skip_paused=False, fq='pre',\
                           count=1, panel=False, fill_paused=True)
            if current_data.iloc[0,0] <    current_data.iloc[0,1]:
                send_message("[%s]涨停打开，卖出" % (stock))
                log.info("[%s]涨停打开，卖出" % (stock))
                position = context.portfolio.positions[stock]
                close_position(position)
            else:
                send_message("[%s]涨停，继续持有" % (stock))
                log.info("[%s]涨停，继续持有" % (stock))


# 1-5 卖掉跌幅过大的股票
def my_trade_sell(context):
    sell_str  = ''
    sell_stocks = []
    current_data = get_current_data()
    holding_list = list(context.portfolio.positions)
    if holding_list:
        for stock in holding_list:
            dt = attribute_history(stock, 1,'1d',['close'])
            if (current_data[stock].last_price <= dt.close[-1]*0.98):
                sell_str += '%s '%stock
                sell_stocks.append(stock)
        if(len(sell_stocks)>0):
            send_message("[%s]跌幅过大，卖出" % sell_str)
            log.info("[%s]跌幅过大，卖出" % sell_str)
            for stock in sell_stocks:
                position = context.portfolio.positions[stock]
                close_position(position)
                
                
                    
##1-6 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    log.info('一天结束')
    log.info('##############################################################')

# 自定义下单
# 根据Joinquant文档，当前报单函数都是阻塞执行，报单函数（如order_target_value）返回即表示报单完成
# 报单成功返回报单（不代表一定会成交），否则返回None
def order_target_value_(security, value):
    if value == 0:
        log.debug("Selling out %s" % (security))
    else:
        log.debug("Order %s to value %f" % (security, value))
    
    # 如果股票停牌，创建报单会失败，order_target_value 返回None
    # 如果股票涨跌停，创建报单会成功，order_target_value 返回Order，但是报单会取消
    # 部成部撤的报单，聚宽状态是已撤，此时成交量>0，可通过成交量判断是否有成交
    return order_target_value(security, value)


# 开仓，买入指定价值的证券
# 报单成功并成交（包括全部成交或部分成交，此时成交量大于0），返回True
# 报单失败或者报单成功但被取消（此时成交量等于0），返回False
def open_position(security, value):
    order = order_target_value_(security, value)
    if order != None and order.filled > 0:
        return True
    return False


# 平仓，卖出指定持仓
# 平仓成功并全部成交，返回True
# 报单失败或者报单成功但被取消（此时成交量等于0），或者报单非全部成交，返回False
def close_position(position):
    security = position.security
    order = order_target_value_(security, 0)  # 可能会因停牌失败
    if order != None:
        if order.status == OrderStatus.held and order.filled == order.amount:
            return True
    return False

#2-1 过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]

#2-2 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list
            if not current_data[stock].is_st
            and current_data[stock].last_price < 40
            and 'ST' not in current_data[stock].name
            and '*' not in current_data[stock].name
            and '退' not in current_data[stock].name]

#2-3 过滤科创北交股票
def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68' or stock[:2] == '30':
            stock_list.remove(stock)
    return stock_list

#2-4 过滤涨停的股票
def filter_limitup_stock(context, stock_list):
    #last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or current_data[stock].last_price  <  current_data[stock].high_limit]

#2-5 过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
    #last_prices = history(1, unit='1m', field='close', security_list=stock_list)
    current_data = get_current_data()
    return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
            or current_data[stock].last_price > current_data[stock].low_limit]

#2-6 过滤次新股
def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=375)]

## 计算N天的板块涨跌得分
def stock_sector_score(stock_list, days):
    stk_close     = history(days, unit='1d', field='close', security_list=stock_list, df=True)
    stk_preclose  = history(days, unit='1d', field='pre_close', security_list=stock_list, df=True)
    stk_ratio     = ((stk_close/stk_preclose)-1)*100
    stk_range     = pd.IntervalIndex.from_tuples([(-50,-9),(-9,-6),(-6,-3),(-3,0),(0,3),(3,6),(6,9),(9,30)])
    stk_counts = pd.cut(stk_ratio[stock_list[0]], bins=stk_range).value_counts(sort=False)
    for stock in stock_list[1:]:
        stk_counts = stk_counts+pd.cut(stk_ratio[stock], bins=stk_range).value_counts(sort=False)
    score = stk_counts[-10]*-1000+stk_counts[-7]*-700+stk_counts[-4]*-400+\
            stk_counts[-1]*-100+stk_counts[2]*100+stk_counts[5]*400+\
            stk_counts[8]*700+stk_counts[11]*1000
    score = score/len(stock_list)
    return(score)

#  选择强势股, 待选股票LIST
def find_strong_stock(context, stock_list):
    strong_stk_dict = {}
    yesterday = context.previous_date
    dmi_pdi,dmi_mdi,dmi_adx,dmi_adxr = DMI(stock_list, check_date=yesterday, N= 14, MM = 6, unit='1d', include_now=True)
    for stock in stock_list:
        if(dmi_pdi[stock]>dmi_mdi[stock]):
            strong_stk_dict[stock] = dmi_pdi[stock] - dmi_mdi[stock] + dmi_adx[stock]
    #分数从大到小排列
    return_stk = [y[0] for y in sorted(strong_stk_dict.items(), key=lambda x:x[1], reverse=True)]
    return(return_stk)
    
    
