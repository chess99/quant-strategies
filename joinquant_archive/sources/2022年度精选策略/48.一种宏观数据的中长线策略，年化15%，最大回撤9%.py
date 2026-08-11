# 克隆自聚宽文章：https://www.joinquant.com/post/40154
# 标题：一种宏观数据的中长线策略，年化15%，最大回撤9%
# 作者：Acne Studio

# 导入函数库
from jqdata import *
from jqdata import macro
from decimal import Decimal
import numpy as np
import pandas as pd
import datetime
from scipy import optimize as op


# 初始化函数，设定基准等等
def initialize(context):
    # mode:0表示当前只买债券，1表示长线玩法（依据经济周期止盈），2表示中线玩法（ma5、ma20、ma120均线止盈）
    g.mode = 0
    g.record = 0.0 #记录下单时沪深300的指数点位
    g.times = -1  #翻倍加仓的次数，-1代表这个经济周期中第一次购买股票类标的
    g.order_amount = 0.04  #下单基数
    g.begin_date = '2013-01'  # 获取经济周期数据的起始节点
    g.stock_security = '510300.XSHG'
    g.bond_security = '511010.XSHG'
    g.over_hot = False  # 过热状态标志
    g.yearMa10 = 0.0  #在超跌反弹中沪深300跌破10年年K线时，该年K线的点位
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    run_daily(handle, time = '14:55')

    
def handle(context):
    pre_date = context.previous_date  #前一个交易日
    current_date = context.current_dt.strftime('%Y-%m-%d').split('-')  #当前交易日
    current_date = datetime.date(int(current_date[0]),int(current_date[1]),int(current_date[2]))
    diff_days = (current_date - pre_date).days  #用两个交易日的差值判断今天是否为本周的第一个交易日
    # 1.根据经济周期(使用制造业PMI的分项数据计算)来定投
    if g.mode in [0, 2]:  #防止放水一波变成了复苏阶段
        current_date = current_date.strftime('%Y-%m')
    # 1.1.判断PMI的值是否符合条件（1是利用拟合函数计算斜率，2是PMI值大于等于50，3是PMI同比上涨）
        x = [0,1,2,3,4,5,6,7,8,9,10,11,12]  #横坐标
        y = get_PMI(current_date)  #获取过去十三个月PMI函数的值
        params = op.curve_fit(func,x,y)
        k = 2 * params[0][0] * 12 + params[0][1]  # k是斜率
        if k > 0.0 and y[-1] >= 50.0 and y[0] <= y[-1]:
    # 1.2.如果PMI满足条件，计算当前供需格局（生产指数与新订单指数的百分位）
            provide_and_need = calc_provide_and_need(g.begin_date, current_date)
    # 1.3.如果供需格局处于复苏状态，则计算当前库存格局（原材料库存指数产成品库存指数的百分位）
            if provide_and_need[0] < 50.0 and provide_and_need[1] > 50.0:
                save = calc_save(g.begin_date, current_date)
    # 1.4.判断当前信息是否有效（供需格局在复苏阶段，库存格局在复苏或者过热阶段）
                if save[0] < 50.0:
                    g.mode = 1
    # 1.5.如果有效则启动长线玩法，记录成交时的指数点位，且直至卖出前不再执行1.1、1.2、1.3、1.4步骤
    if g.mode == 1:
        if g.times == -1:
            g.record = float(np.array(get_bars('000300.XSHG', 1, '1d', fields = ['close'], include_now=True, df = True))[0])
        if g.bond_security in context.portfolio.positions.keys():
            order_target(g.bond_security, 0)
        current_price = float(np.array(get_bars('000300.XSHG', 1, '1d', fields = ['close'], include_now=True, df = True))[0])
        fund_price = float(np.array(get_bars(g.stock_security, 1, '1d', fields = ['close'], include_now=True, df = True))[0])
        withdraw = Decimal(str(current_price)) / Decimal(str(g.record)) - Decimal('1.0')
    # 1.6.检查当前价格是否比记录价格低2%，如果是，则买入一笔沪深300ETF（依据1248定投法则）
        if withdraw < Decimal('-0.02') or g.times == -1:
            g.times += 1
            order_func(context.portfolio.total_value, context.portfolio.available_cash, fund_price)
            g.record = float(np.array(get_bars('000300.XSHG', 1, '1d', fields = ['close'], include_now=True, df = True))[0])
    # 1.7.指定每周第一个交易日定投一笔沪深300ETF
        else:
            if diff_days > 2:
                order_func(context.portfolio.total_value, context.portfolio.available_cash, fund_price)
    # 2.根据年K图的移动平均线来定投
    if g.mode in [0, 2]:
        if g.mode == 0:
    # 2.1.将月K线图转换成年K线图
            year_point = change_to_yeak_k()
    # 2.2.计算年K图的移动平均线：ma10
            yearMa10 = year_move_average(year_point)
    # 2.3.如果跌破年K图的ma10，则记录当前ma10的价格，并且买入一个基数的沪深300ETF，尔后根据1248定投法则定投
            current_price = float(np.array(get_bars('000300.XSHG', 1, '1d', fields = ['close'], include_now=True, df = True))[0])
            fund_price = float(np.array(get_bars(g.stock_security, 1, '1d', fields = ['close'], include_now=True, df = True))[0])
            if current_price < yearMa10:
    # 2.4.启动中线玩法（更改mode的值），直至卖出前不再执行2.1、2.2、2.3、2.4步骤
                g.mode = 2
                g.record = yearMa10
                g.times += 1
                if g.bond_security in context.portfolio.positions.keys():  #卖出债券
                    order_target(g.bond_security, 0) 
                order_func(context.portfolio.total_value, context.portfolio.available_cash, fund_price)
    # 2.5.如果当前价格比记录的价格低5%以上，则继续买入一笔沪深300ETF（依据1248定投法则买入）
        if g.mode == 2:
            current_price = float(np.array(get_bars('000300.XSHG', 1, '1d', fields = ['close'], include_now=True, df = True))[0])
            fund_price = float(np.array(get_bars(g.stock_security, 1, '1d', fields = ['close'], include_now=True, df = True))[0])
            withdraw = Decimal(str(current_price)) / Decimal(str(g.record)) - Decimal('1.0')
            if withdraw < Decimal('-0.05'):
                g.times += 1
                order_func(context.portfolio.total_value, context.portfolio.available_cash, fund_price)
                g.record = float(np.array(get_bars('000300.XSHG', 1, '1d', fields = ['close'], include_now=True, df = True))[0])
    # 2.6.指定每周第一个交易日定投一笔沪深300ETF
            else:
                if diff_days > 2:
                    order_func(context.portfolio.total_value, context.portfolio.available_cash, fund_price)
    # 4.右侧买入（仅针对1和2）
    if g.mode in [1, 2]:
    # 4.1.计算日K图的ma5、ma10、ma20、ma30
        ma5 = day_move_average(5, True)
        ma10 = day_move_average(10, True)
        ma20 = day_move_average(20, True)
        ma30 = day_move_average(30, True)
        ma30_pre = day_move_average(30, False)
    # 4.2.如果ma5>ma10>ma20>ma30 且 当天的ma30比前一天高，全仓买入股票类标的
        if ma5 > ma10 > ma20 > ma30 > ma30_pre:
            order_value(g.stock_security, context.portfolio.available_cash)
    # 5.股票类标的止盈操作
    if g.stock_security in context.portfolio.positions.keys():
        sell_stock_security(current_date, context.portfolio.total_value, list(context.portfolio.positions.keys()))
    
    
# 以下是功能函数
def get_PMI(date:str) -> list:
    """获取过去十三个月PMI函数的值"""
    start_date = date
    for i in range(13):
        start_date = calc_last_month(start_date)
    df = macro.run_query(query(
        macro.MAC_MANUFACTURING_PMI.pmi
        ).filter(
        macro.MAC_MANUFACTURING_PMI.stat_month >= start_date,
        macro.MAC_MANUFACTURING_PMI.stat_month < date
        ).order_by(
            macro.MAC_MANUFACTURING_PMI.stat_month.asc()
        ))
    return list(np.array(df['pmi']))

def calc_provide_and_need(start_date:str,end_date:str) -> tuple:
    """这个函数返回生产指数和新订单指数的百分位"""
    end_date = calc_last_month(end_date) #计算上一个月的月份的字符串
    # 查询数据
    df = macro.run_query(query(
        macro.MAC_MANUFACTURING_PMI.stat_month,
        macro.MAC_MANUFACTURING_PMI.produce_idx,
        macro.MAC_MANUFACTURING_PMI.new_orders_idx
        ).filter(
        macro.MAC_MANUFACTURING_PMI.stat_month >= start_date,
        macro.MAC_MANUFACTURING_PMI.stat_month <= end_date
        ).order_by(
        macro.MAC_MANUFACTURING_PMI.stat_month.desc()
        ))
    # 计算生产指数和新订单指数的百分位
    produce_seq = np.array(df['produce_idx'])
    new_orders_seq = np.array(df['new_orders_idx'])
    produce_percent = percentile(produce_seq, df.iloc[0, 1])
    new_orders_percent = percentile(new_orders_seq, df.iloc[0, 2])
    return (produce_percent, new_orders_percent)
    
def calc_save(start_date:str,end_date:str) -> tuple:
    """这个函数返回原材料和产成品库存指数的百分位"""
    end_date = calc_last_month(end_date) #计算上一个月的月份的字符串
    # 查询数据
    df = macro.run_query(query(
        macro.MAC_MANUFACTURING_PMI.stat_month,
        macro.MAC_MANUFACTURING_PMI.raw_material_idx,
        macro.MAC_MANUFACTURING_PMI.finished_produce_idx
        ).filter(
        macro.MAC_MANUFACTURING_PMI.stat_month >= start_date,
        macro.MAC_MANUFACTURING_PMI.stat_month <= end_date
        ).order_by(
        macro.MAC_MANUFACTURING_PMI.stat_month.desc()
        ))
    # 计算生产指数和新订单指数的百分位
    raw_material_seq = np.array(df['raw_material_idx'])
    finished_produce_seq = np.array(df['finished_produce_idx'])
    raw_material_percent = percentile(raw_material_seq, df.iloc[0, 1])
    finished_produce_percent = percentile(finished_produce_seq, df.iloc[0, 2])
    return (raw_material_percent, finished_produce_percent)
    
def order_func(total_cash:float, available_cash:float,fund_price:float):
    """下单函数，total_cash表示总权益，available_cash表示可用资金，current_price表示当前价格"""
    buy_cash = 2 ** g.times * g.order_amount * total_cash
    if buy_cash <= available_cash:
        order_value(g.stock_security, buy_cash)
    else:
        if fund_price * 100 <= available_cash:
            order_value(g.stock_security, available_cash)

def sell_stock_security(current_date, total_cash:float, stock_in_hand:list):
    """卖出股票类标的止盈"""
    if isinstance(current_date, datetime.date):
        current_date = current_date.strftime('%Y-%m')
    # 1.如果mode==1（长线玩法）
    if g.mode == 1:
    # 1.1.计算当前供需格局及其得分(1/3*供 + 2/3*需)
        provide_and_need = calc_provide_and_need(g.begin_date, current_date)
        score = 1/3 * provide_and_need[0] + 2/3 * provide_and_need[1]
    # 1.2.如果极度过热（正态分布中均值+2倍标准差，在这里百分位大于97%），则需要计算库存格局
        if score > 97.0 or g.over_hot:
            g.over_hot = True
            save = calc_save(g.begin_date, current_date)
    # 1.3.如果库存格局是滞涨状态，启用中线玩法
            if save[0] > 50.0 and save[1] < 50.0:
                g.mode = 2
    # 2.如果mode==2（中线玩法）
    if g.mode == 2:
    # 2.1.计算日K图ma5、ma20、ma120移动平均线
        current_price = float(np.array(get_bars('000300.XSHG', 1, '1d', fields = ['close'], include_now=True, df = True))[0])
        ma5 = day_move_average(5, True)   #当天的ma5
        ma5_pre = day_move_average(5, False)    #前一天的ma5
        ma20 = day_move_average(20, True)       #当天的ma20
        ma20_pre = day_move_average(20, False)    #前一天的ma20
        ma120 = day_move_average(120, True)
    # 2.2.当前价格大于ma120 且 前一天ma5>ma20,当天ma5<ma20，则卖出沪深300ETF，买入债券
        if current_price > ma120 and ma5_pre > ma20_pre and ma5 < ma20:
            order_target(g.stock_security, 0)
            g.times = -1
            order_value(g.bond_security, total_cash)  #买入一半的债券
            g.mode = 0
            g.over_hot = False

def change_to_yeak_k() -> dict:  
    """将月K线的收盘点位转化为年K的收盘点位"""
    year_point = dict()  #过去十年的年K线收盘点位
    df = get_bars('000300.XSHG',109,'1M',fields=['date','close'],include_now=True,df=True)  #取九年一个月来计算每一年的收盘点
    df['date'] = df['date'].apply(lambda x:x.strftime('%Y'))  #将时间类型数据转为字符串
    last_point = df.iloc[0,1] #取得df行索引为0的点位
    last_time = df.iloc[0,0]  #取得df行索引为0的年份
    current_point = df.iloc[0,1]
    current_time = df.iloc[0,0]
    for i in range(1,df.shape[0]):  #从行索引为1开始遍历
        last_time = current_time
        last_point= current_point
        current_time = df.iloc[i,0]
        current_point = df.iloc[i,1]
        if not current_time == last_time:
            year_point[last_time] = last_point
        if i == df.shape[0]-1:
            year_point[current_time] = current_point
    return year_point


def year_move_average(year_point:dict) -> float:
    """处理年K图的MA10"""
    ten_year_total = Decimal('0.0')
    for point in year_point.values():
        ten_year_total += Decimal(str(point))
    yearMa10 = float(ten_year_total / Decimal('10.0'))
    return yearMa10

# 以下是辅助函数
def day_move_average(day:int, now:bool) -> float:
    array = np.array(get_bars('000300.XSHG', day, '1d', fields = ['close'], include_now = now, df = True))
    ma = array.mean()
    return ma

def percentile(seq, target) -> float:
    """seq是序列，target是在序列中所需求百分位的目标数"""
    not_less_num = len(np.extract(seq>=target,seq))
    smaller_num = len(np.extract(seq<target,seq))  #比这个小的有多少个数据
    percent = smaller_num * 100 / (not_less_num+smaller_num-1)
    return percent
    
def calc_last_month(date:str) -> str:
    """计算上一个月月份的字符串，返回YYYY-MM"""
    result = ''
    year = int(date.split('-')[0])
    month = int(date.split('-')[1])
    # 计算上一个月的月份
    if month - 1 < 1:
        year -= 1
        month = month + 12 - 1
    else:
        month -= 1
    # 填充月份格式
    if month < 10:
        result = str(year) + '-0' + str(month)
    else:
        result = str(year) + '-' + str(month)
    return result
    
def func(x, A, B, C):
    """拟合函数样式"""
    return A * x ** 2 + B * x + C
    
    
    
