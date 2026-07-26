# 克隆自聚宽文章：https://www.joinquant.com/post/24679
# 标题：基于大盘PE标准差偏离度的聪明基金定投策略
# 作者：逆熵者

'''
========================================================================
# 指数基金PE估值弹性定投
# 作者: 逆熵者
大约一年的定投资金作为初始资金建立底仓，每月向账户中固定增加资金
每周四定投，根据PE估值调整用完所有资金或卖掉所有持仓所需的周数
根据PE移动平均线和标准差划定高低线
低于低线采取买入模式，越低买光全部资金所需周数越少
高于高线采取卖出模式，越高卖出所有持仓所需周数越少
两线之间为合理区间，按照预订周数定投
========================================================================
'''

# 导入函数库
from jqdata import *
from jqlib.technical_analysis import *
import numpy as np
import datetime

'''
========================================================================
# 初始化函数，设定基准等等
========================================================================
'''
def initialize(context):
    # 设置对比基准
    g.benchmark = '000300.XSHG'
    set_benchmark(g.benchmark)
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 避免未来函数
    set_option("avoid_future_data", True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 初始化高低估线
    g.stdpeH = 1.5
    g.stdpeL = 1.2
    g.now_pe = 1
    ######实盘无效#######
    # 为全部交易品种设定固定金额滑点（单位元）
    set_slippage(FixedSlippage(0.02))
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万3，卖出时佣金万分3，加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    ### 场内基金设定 ###
    # 场内基金类每笔交易时的手续费是：买入时佣金万3，卖出时佣金万3，加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003 , close_commission=0.0003, min_commission=5), type='fund')

# 修改代码后运行
def after_code_changed(context): # 修改代码后运行
    # 设置交易标的
    g.security = '510300.XSHG'
    # 设置日志过滤等级
    log.set_level('order', 'error')
    g.weeks = 50 #正常估值时多少周投完本金
    # 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分）
    # 每天开盘前运行
    run_daily(before_market_open, time='before_open', reference_security=g.security)
    # 每周倒数第二天运行交易函数
    run_weekly(market_open, -2, time='open', reference_security=g.security)
    # 每天收盘后运行
    run_daily(after_market_close, time='after_close', reference_security=g.security)
    # 每周开盘前运行
    run_weekly(code_run_weekly, 1, time='before_open')
    # 每月第6个交易日增加账户资金(发工资)
    run_monthly(wages_monthily, 6, time='before_open')


'''
========================================================================
# 每天开盘前运行函数
========================================================================
'''
def before_market_open(context):
    # 日志输出运行时间
    log.info('=====================美好的一天开始了==========================')
    log.info('【开盘前】(before_market_open)：'+str(context.current_dt.time()))
    # 获取昨天时间
    g.date = date = context.previous_date

    previous_date = context.previous_date

    # 给微信发送消息（添加模拟交易，并绑定微信生效）
    # send_message('总资产：%s元'%context.portfolio.total_value)
    # send_message('持股市值：%s元'%context.portfolio.positions_value)
    # send_message('当前持仓：%s'%context.portfolio.positions.keys())
    log.info('总资产：%s元' % context.portfolio.total_value)
    log.info('持股市值：%s元' % context.portfolio.positions_value)


'''
========================================================================
# 开盘时运行交易函数
========================================================================
'''
def market_open(context):
    # 日志输出运行时间
    log.info('【开盘时】(market_open):'+str(context.current_dt.time()))
    # 计算当前估值
    qtt = QuantTiming(context.previous_date,g.security)
    # g.ema_speed = qtt.ema_speed()
    g.now_pe = qtt.now()
    
    # 获取目标周数
    target_weeks = qtt.how_many_weeks()
    # # 获取当前仓位
    # now_position = float(context.subportfolios[0].positions_value) / float(context.subportfolios[0].total_value)
    if target_weeks < 0:
        # 计算目标价值(周数为负，所以值为负)
        target_value = context.portfolio.positions_value + context.portfolio.positions_value / target_weeks
        log.info("【卖出】 %s" % (g.security))
        # 卖出
        order_target_value(g.security, target_value)
    elif target_weeks > 0:
        # 计算目标价值(周数为正，所以值为正)
        target_value = context.portfolio.positions_value + context.portfolio.available_cash / target_weeks
        log.info("【买入】 %s" % (g.security))
        # 买入
        order_target_value(g.security, target_value)
    else:
        pass

'''
========================================================================
# 每天收盘后运行函数
========================================================================
'''
def after_market_close(context):
    # 日志输出运行时间
    log.info(str('【收盘后】(after_market_close):'+str(context.current_dt.time())))
    # 得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    if g.now_pe > g.stdH:
        g.pe_status = '高估'
    elif g.now_pe < g.stdL:
        g.pe_status = '低估'
    else:
        g.pe_status = '合理'
    # 记录当天的PE
    g.last_pe = g.now_pe
    log.info('大盘状态：%s'%g.pe_status)
    log.info('PE宏观高估线：%s'%g.stdH)
    log.info('大盘标准化PE：%s'%g.now_pe)
    log.info('PE宏观低估线：%s'%g.stdL)
    log.info('当前仓位比例：%f'%(context.portfolio.positions_value/context.portfolio.total_value))
    # log.info('大盘MA变化率：%s'%g.ema_speed)
    log.info('##########################一天结束############################')
    log.info(' ')
    # 绘制相关参考图线
    record(
        PE=g.now_pe, 
        高估=g.stdH, 
        低估=g.stdL, 
        当前仓位=1 + 0.5 * context.portfolio.positions_value/context.portfolio.total_value, 
    )


'''
========================================================================
## 设定每周运行
========================================================================
'''
def code_run_weekly(context):
    qtt = QuantTiming(context.previous_date,g.security)
    g.stdpeH,g.stdpeL = qtt.std()
    # 高低估线
    g.stdH = g.stdpeH
    g.stdL = g.stdpeL
    
# 每月发工资后账户增加5000元
def wages_monthily(context):
    inout_cash(5000, pindex=0)

'''
========================================================================
# 功能函数库
========================================================================
'''
# 择时类
class QuantTiming:
    def __init__(self,date,security):
        self.date = date 
        self.security = security
    
    '''
    ========================================================================
    # 定投买卖所需周数信号
    ========================================================================
    '''
    def how_many_weeks(self):
        if g.now_pe > g.stdH:
            # 如果当前PE高于高线，高出N个百分点，就减少N倍卖出所需周数，比如高10%，则所需周数减小10倍
            weeks = g.weeks / (((g.stdH - g.now_pe) / g.stdH) * 100)
        elif g.now_pe < g.stdL:
            # 如果当前PE低于低线，低出N个百分点，就减少5N%的投入所需周数，比如低20%，则所需周数为0
            weeks = g.weeks * (1 - ((g.stdL - g.now_pe) / g.stdL) * 5)
            if weeks <= 0:
                weeks = 1
        else:
            weeks = g.weeks
        return weeks

    '''
    ========================================================================
    # 大盘PE择时相关函数
    ========================================================================
    '''
    # 查询PE等数据修正后归为V
    def Q(self,count):
        q=query(finance.STK_EXCHANGE_TRADE_INFO).filter(
            finance.STK_EXCHANGE_TRADE_INFO.date <= self.date,
            finance.STK_EXCHANGE_TRADE_INFO.exchange_code == '322002',
        ).order_by(finance.STK_EXCHANGE_TRADE_INFO.date.desc()).limit(count)
        df=finance.run_query(q)
        DF = df[['date','pe_average','turnover_ratio']]
        DF = DF.copy()
        #DF['V'] = DF.apply(lambda x: np.sqrt(x.volume/1000)/ np.sqrt(x.circulating_market_cap) * np.log(x.pe_average), axis=1) # 
        DF['V'] = DF.apply(lambda x: np.log10(x.pe_average), axis=1)
        return DF
    
    # 获得中位数±一定范围的标准差
    def std(self):
        section = self.Q(2500).V
        mean = section.mean()
        median = section.median()
        std = section.std()
        return median+0.05*std,median-0.25*std
    
    # 获得现在的数据值
    def now(self):
        return self.Q(1).V[0]
