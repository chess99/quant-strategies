# 克隆自聚宽文章：https://www.joinquant.com/post/36092
# 标题：价值策略重开，再次向Jqz1226致敬
# 作者：南开小楼

from jqdata import *
import statsmodels.api as sm
import pandas as pd
import numpy as np
import datetime
import scipy.stats as stats
import warnings
warnings.filterwarnings('ignore')





def initialize(context):
    set_param(context) #设置参数
    
    #9:00先计算mode2_flag如果为0则用rsrs计算mode1_flag，取flag为1的模式的buy_list作为当日操作
    run_monthly(mode2_pe_check_month, 1,time='09:00')
    run_weekly(mode2_pe_check_week, 1,time='09:05')
    run_daily(before_markt_open, time='09:10', reference_security='000300.XSHG')
    
    
    #9:16卖出flag为1的不在buy_list的股票
    run_daily(before_markt_open_trade_sell, time='09:16', reference_security='000300.XSHG')
    
    
    #9:26买入flag为1的buy_list的股票
    run_daily(before_markt_open_trade_buy, time='09:26', reference_security='000300.XSHG')
    # run_daily(before_markt_open_trade_buy, time='09:27', reference_security='000300.XSHG')
    # run_daily(before_markt_open_trade_buy, time='09:28', reference_security='000300.XSHG')
    # run_daily(before_markt_open_trade_buy, time='09:29', reference_security='000300.XSHG')
    
    #开盘复核买入
    run_daily(markt_open_trade, time='09:30', reference_security='000300.XSHG')
    
    #模式2的票盘中交易
    run_daily(mode2_stop_loss, '10:30', reference_security='000300.XSHG')
    run_daily(mode2_stop_loss, '11:30', reference_security='000300.XSHG')
    run_daily(mode2_stop_loss, '13:30', reference_security='000300.XSHG')
    run_daily(mode2_stop_loss, '14:30', reference_security='000300.XSHG')
    run_daily(mode2_stop_holds, '14:50', reference_security='000300.XSHG')

    
    
    #10:00买入etf_list 中的股票
    run_daily(during_markt_open_trade, time='10:00', reference_security='000300.XSHG')
    
    
    #周一到周四尾盘卖出511880，买入逆回购（需券商支持自动购买1日逆回购），周五持有511880
    run_weekly(before_markt_close_trade, weekday=1, time='14:50', reference_security='000300.XSHG')
    run_weekly(before_markt_close_trade, weekday=2, time='14:50', reference_security='000300.XSHG')
    run_weekly(before_markt_close_trade, weekday=3, time='14:50', reference_security='000300.XSHG')
    run_weekly(before_markt_close_trade, weekday=4, time='14:50', reference_security='000300.XSHG')
    #收盘后打印持仓情况
    run_daily(after_market_close,time='after_close', reference_security='000300.XSHG')
    
    

    
def set_param(context):
    #1.初始化系统参数
    set_base_param(context)
    #2.初始化股票参数
    set_mode1_param(context)
    set_mode2_param(context)

    
def set_base_param(context):
    #显示所有列
    pd.set_option('display.max_columns', None)
    #显示所有行
    pd.set_option('display.max_rows', None)
    #设置value的显示长度为100，默认为50
    pd.set_option('max_colwidth',100)
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    #风险参考基准
    g.security = '000300.XSHG'
    #卖出股票后对冲基金
    g.etf_list = '511880.XSHG'
    
    #统计持仓量的历史天数
    g.days_number = 15
    
    #用于存放历史value的list，len为g.days_number
    g.old_portfolio_values = []
    
    #30 天清理一次g.risky_stocks
    g.days_count = 0
    
    g.risk_incr_pct = 0.1
    
    g.risk_flag = 0
    
    g.risky_stocks = []
    
    
def set_mode1_param(context):
    #模式1买入列表
    g.mode1_buy_list=[]
    #模式1买入总数量
    g.mode1_stock_num = 5
    #模式1判断开仓方向
    g.mode1_flag = 0
    #中间列表
    g.fin=pd.DataFrame()


def set_mode2_param(context):
    #模式2买入列表
    g.mode2_temp_list = []
    g.mode2_buy_list = []
    #模式2买入总数量
    g.mode2_stock_num = 2
    #模式2判断开仓方向
    g.mode2_flag = 0


def before_markt_open(context):
    log.info("-------------------------------------------------------------------")

    if g.mode2_flag == 1:
		log.info("Pe上行，操作股票:")
		
		mode2_check_stock(context)
    else:
        log.info("Pe下行或超出中位数值，空仓:")
        mode1_check_rsrs(context)


def mode1_check_rsrs(context):
    previous_date = context.current_dt - datetime.timedelta(days=1)
    hs300_data = get_price('000300.XSHG',end_date=previous_date,count=1150,fields=['high','low']) 
    hs300_rsrs = calc_rsrs(hs300_data['high'].values,hs300_data['low'].values,hs300_data['high'].index,800,18)
    zscore_rightdev = hs300_rsrs.RSRS_negative_r.iloc[-1]
   
    log.info("【RSRS斜率: %.2f】",zscore_rightdev)
    if zscore_rightdev > 0.7:
        g.mode1_flag = 1
        
        
    if zscore_rightdev < -0.7:
        g.mode1_flag = 0
    if g.mode1_flag == 1:
        log.info("    市场风险在合理范围,持有股票")
        mode1_check_stock(context)
    if g.mode1_flag == 0:
        log.info("    市场风险过大，持有货币基金")

    
'''
#=================================交易流程=======================================#
'''


def before_markt_open_trade_sell(context):
    etf_list = g.etf_list
    #队列装满以后，每天比较上上周的账户value 和上周的账户value
    if len(g.old_portfolio_values) == g.days_number:
        incr_rate = (g.old_portfolio_values[-6] - g.old_portfolio_values[-11])/g.old_portfolio_values[-11]
    else:
        incr_rate = 0
    log.info('incr_rate is:',incr_rate)
    log.info('g.risk_incr_pct is:',g.risk_incr_pct)
    #判别账户value是否暴涨
    if incr_rate >= g.risk_incr_pct:
            sell_list = context.portfolio.positions.keys()
            sell_list = [s for s in sell_list if s != etf_list]
            #计算沪深300 是否黄昏之星,如果是risk_flag == 1
            dp_df_2w = attribute_history(count = 2, unit='5d', security='000300.XSHG')
            dp_stock_last_2w = dp_df_2w.iloc[0]
            dp_stock_last_1w = dp_df_2w.iloc[1]
            #计算上上周涨幅
            log.info('dp_stock_last_2w.close is:',dp_stock_last_2w.close)
            log.info('dp_stock_last_2w.open is:',dp_stock_last_2w.open)
            dp_cr_last_2w = (dp_stock_last_2w.close - dp_stock_last_2w.open)/dp_stock_last_2w.open
            dp_ub_rate_last_1w = 0
            dp_ba_rate_last_1w = 0
            #计算上周上影线/箱体高度比例，比例越大上影线越长
            if dp_stock_last_1w.close >= dp_stock_last_1w.open:
                dp_ub_rate_last_1w = (dp_stock_last_1w.high - dp_stock_last_1w.close)/(dp_stock_last_1w.close - dp_stock_last_1w.open + 0.00001)
            else:
                dp_ub_rate_last_1w = (dp_stock_last_1w.high - dp_stock_last_1w.open)/(dp_stock_last_1w.open - dp_stock_last_1w.close + 0.00001)
            #如果上周股价下跌，计算箱体高度/振幅比例,比例越大箱体越长
            if dp_stock_last_1w.close <= dp_stock_last_1w.open:
                dp_ba_rate_last_1w = (dp_stock_last_1w.open - dp_stock_last_1w.close)/(dp_stock_last_1w.high - dp_stock_last_1w.low+0.00001)
            log.info('dp_cr_last_2w is:',dp_cr_last_2w)
            log.info('dp_ub_rate_last_1w is:',dp_ub_rate_last_1w)
            log.info('dp_ba_rate_last_1w is:',dp_ba_rate_last_1w)
            if dp_cr_last_2w >= 0.04 and (dp_ub_rate_last_1w > 2 or dp_ba_rate_last_1w > 1/3):
                log.info('大盘黄昏之星，g.risk_flag = 1')
                g.risk_flag = 1
                g.days_count = 0
                #判别个股是否黄昏之星
                for sell_code in sell_list:
                    log.info('sell_code is:',sell_code)
                    df_2w = attribute_history(count =2, unit='5d', security=sell_code)
                    stock_last_2w = df_2w.iloc[0]
                    stock_last_1w = df_2w.iloc[1]
                    #计算上上周涨幅
                    cr_last_2w = (stock_last_2w.close - stock_last_2w.open)/stock_last_2w.open
                    ub_rate_last_1w = 0
                    ba_rate_last_1w = 0
                    #计算上影线/箱体高度比例，比例越大上影线越长
                    if stock_last_1w.close >= stock_last_1w.open:
                        ub_rate_last_1w = (stock_last_1w.high - stock_last_1w.close)/(stock_last_1w.close - stock_last_1w.open + 0.00001)
                    else:
                        ub_rate_last_1w = (stock_last_1w.high - stock_last_1w.open)/(stock_last_1w.open - stock_last_1w.close + 0.00001)
                    #如果上周股价下跌，计算箱体高度/下影线比例,比例越大箱体越长
                    if stock_last_1w.close <= stock_last_1w.open:
                        ba_rate_last_1w = (stock_last_1w.open - stock_last_1w.close)/(stock_last_1w.high - stock_last_1w.low+0.00001)
                    log.info('cr_last_2w is:',cr_last_2w)
                    log.info('ub_rate_last_1w is:',ub_rate_last_1w)
                    log.info('ba_rate_last_1w is:',ba_rate_last_1w)
                    #if cr_last_2w >= 0.09 and (cr_last_2w > 2 or cr_last_2w > 1/3):
                    if cr_last_2w >= 0.09 and (ub_rate_last_1w > 2 or ba_rate_last_1w > 1/3):
                        code_number = context.portfolio.positions[sell_code].closeable_amount
                        log.info('可平仓数 is:',code_number)
                        if  code_number > 0:
                            last_price = history(1, unit='1d', field='close', security_list=sell_code).iloc[-1,0]
                            limit_price = last_price*0.91 #即为跌停价
                            order_target_value(sell_code,0,LimitOrderStyle(limit_price))
                            g.risky_stocks.append(sell_code)
                            log.info("【该股黄昏之星且前期涨幅过快，执行竞价减仓交易】")
                            log.info('    执行竞价减仓交易: %s,  委托价格: %.2f',sell_code,limit_price)

            
    
    mode1_buy_list=g.mode1_buy_list
    all_value=context.portfolio.total_value
    
    # 如果上一时间点的RSRS斜率小于卖出阈值, 则空仓卖出
    if g.mode1_flag == 0 and g.mode2_flag == 0:    
        # 卖出所有股票,使这只股票的最终持有量为0
        sell_list = context.portfolio.positions.keys()
        sell_list = [s for s in sell_list if s != etf_list]
        # 记录这次卖出
        for sell_code in sell_list:
            last_price = history(1, unit='1d', field='close', security_list=sell_code).iloc[-1,0]
            limit_price = last_price*0.91 #即为跌停价
            order_target_value(sell_code,0,LimitOrderStyle(limit_price))
            log.info("【执行竞价清仓交易】")
            log.info('    竞价清仓股票: %s,  委托价格: %.2f',sell_code,limit_price)

    # 调仓，卖出不在mode1_buy_list中的股票    
    if g.mode1_flag == 1:
        sell_list = context.portfolio.long_positions.keys()
        sell_list = [s for s in sell_list if s not in g.mode2_buy_list]
        sell_list = [s for s in sell_list if s not in g.mode1_buy_list]
        
        
        for sell_code in sell_list:
            last_price = history(1, unit='1d', field='close', security_list=sell_code).iloc[-1,0]
            limit_price = last_price*0.91 #即为跌停价
            order_target_value(sell_code,0,LimitOrderStyle(limit_price))
            log.info("【执行竞价调仓交易】")
            log.info('    竞价调仓卖出: %s,  委托价格: %.2f',sell_code,limit_price)

    if g.mode2_flag == 1:
        sell_list = context.portfolio.long_positions.keys()
        sell_list = [s for s in sell_list if s not in g.mode2_buy_list]
        for sell_code in sell_list:
            last_price = history(1, unit='1d', field='close', security_list=sell_code).iloc[-1,0]
            limit_price = last_price*0.91 #即为跌停价
            order_target_value(sell_code,0,LimitOrderStyle(limit_price))
            log.info("【执行竞价调仓交易】")
            log.info('    竞价调仓卖出: %s,  委托价格: %.2f',sell_code,limit_price)


        #mode2的卖出
    
def before_markt_open_trade_buy(context):
    #当mode1为1时，进行rsrs行业周期股操作
    
    etf_list = g.etf_list
    mode1_buy_list=g.mode1_buy_list
    all_value=context.portfolio.total_value
    current_data = get_current_data()
    log.info('g.mode1_flag is:',g.mode1_flag)
    log.info('g.mode2_flag is:',g.mode2_flag)
    log.info('g.risk_flag is:',g.risk_flag)
    #没有超买发生并且rsrs适中才调仓
    if g.mode1_flag == 1 and g.risk_flag == 0:
        for buy_code in g.mode1_buy_list :
            if buy_code not in context.portfolio.long_positions.keys():
                cash_value=context.portfolio.available_cash
                buy_value=all_value/g.mode1_stock_num
                
                if cash_value > buy_value/3 :
                    if cash_value > buy_value:
                        buy_value_num = buy_value
                    else:
                        buy_value_num = cash_value
                    #order_target_value(buy_code,buy_value)
                    current_data = get_current_data()
                    limit_price = current_data[buy_code].last_price*1.02
                    order_target_value(buy_code,buy_value_num,LimitOrderStyle(limit_price))
                    log.info("【执行竞价调仓交易】")
                    log.info('    竞价调仓买入: %s,  委托价格: %.2f',buy_code,limit_price)
                else:
                    break
    #pe反转并且没有超买发生            
    if g.mode2_flag == 1 and g.risk_flag == 0:
        for buy_code in g.mode2_buy_list:
            
            if buy_code not in context.portfolio.long_positions.keys():
                cash_value=context.portfolio.available_cash
                buy_value=all_value/g.mode2_stock_num
                
                if cash_value > buy_value/3 :
                    if cash_value > buy_value:
                        buy_value_num = buy_value
                    else:
                        buy_value_num = cash_value
                    current_data = get_current_data()
                    limit_price = current_data[buy_code].last_price*1.02
                    order_target_value(buy_code,buy_value_num,LimitOrderStyle(limit_price))
                    log.info("【执行竞价调仓交易】")
                    log.info('    竞价调仓买入: %s,  委托价格: %.2f',buy_code,limit_price)
                else:
                    break
    
        
    
    
def markt_open_trade(context):
    
    etf_list = g.etf_list
    all_value=context.portfolio.total_value
    
    cash_value=context.portfolio.available_cash
    log.info('【开盘后可用现金:   %s】',cash_value)

    current_data = get_current_data()
    
    if g.mode2_flag == 1 and g.risk_flag == 0:
        for buy_code in g.mode2_buy_list:
            if buy_code not in context.portfolio.long_positions.keys():
                cash_value=context.portfolio.available_cash
                buy_value=all_value/g.mode2_stock_num
                
                if cash_value > buy_value/3 :
                    if cash_value > buy_value:
                        buy_value_num = buy_value
                    else:
                        buy_value_num = cash_value
                    current_data = get_current_data()
                    limit_price = current_data[buy_code].last_price*1.02
                    order_target_value(buy_code,buy_value_num,LimitOrderStyle(limit_price))
                    log.info("【执行开盘调仓交易】")
                    log.info('    开盘调仓买入: %s,  委托价格: %.2f',buy_code,limit_price)
                else:
                    break

    if g.mode1_flag == 1 and g.risk_flag == 0:
        for buy_code in g.mode1_buy_list:
            if buy_code not in context.portfolio.long_positions.keys():
                cash_value=context.portfolio.available_cash
                buy_value=all_value/g.mode1_stock_num
                
                if cash_value > buy_value/3 :
                    if cash_value > buy_value:
                        buy_value_num = buy_value
                    else:
                        buy_value_num = cash_value
                    current_data = get_current_data()
                    limit_price = current_data[buy_code].last_price*1.02
                    order_target_value(buy_code,buy_value_num,LimitOrderStyle(limit_price))
                    log.info("【执行开盘调仓交易】")
                    log.info('    开盘调仓买入: %s,  委托价格: %.2f',buy_code,limit_price)
                else:
                    break





def during_markt_open_trade(context):
    #10:00如果可用资金大于10000，并且够买1手511880则买511880
    
    etf_list = g.etf_list
    cash_value=context.portfolio.available_cash
    if cash_value > 10000:
        current_data = get_current_data()
        
        if cash_value > current_data[etf_list].last_price*101:
            log.info("【执行开盘买入ETF】")
            log.info('    调仓买入: %s,  买入市值: %.2f',etf_list,cash_value)
            order_target_value(etf_list,cash_value)
            
    
    
            
            

    cash_value=context.portfolio.available_cash
    log.info('【盘中调仓后可用现金:   %s】',cash_value)


def before_markt_close_trade(context):
    #15:50卖出511880
    etf_list = g.etf_list
    sell_list = context.portfolio.positions.keys()
    if etf_list in sell_list:
        order_target_value(etf_list,0)
        log.info("【执行收盘卖出交易】")
        log.info('    调仓卖出: %s,  卖出市值: %.2f',etf_list,context.portfolio.positions[etf_list].value)
  


def after_market_close(context):
    #插入历史持仓value，保持len 不大于g.days_number
    if g.days_count < 20:
        g.days_count = g.days_count + 1
    else:
        g.risky_stocks = []
        g.days_count = 0
        g.risk_flag  = 0
    g.old_portfolio_values.append(context.portfolio.portfolio_value)
    if len(g.old_portfolio_values) > g.days_number:
        g.old_portfolio_values.pop(0)
        
        
    #盘后统计收益
    if len(context.portfolio.positions.keys()) != 0:
        #log.info("当前收益：%.2f%%,当前持仓: %s", current_returns, list(context.portfolio.positions.keys()))
        log.info("【当前持仓: 】")
        current_data = get_current_data()
        for s in context.portfolio.positions.keys():
            # 获取名称
            name = current_data[s].name
            # 获取股票持有成本
            cost = context.portfolio.positions[s].avg_cost
            # 获取股票现价
            price = context.portfolio.positions[s].price
            # 获得数量
            total_amount = context.portfolio.positions[s].total_amount
            #获得标的总仓位
            total_amount_value = context.portfolio.positions[s].total_amount * cost
            #获得收益率
            avg_cost = context.subportfolios[0].long_positions[s].avg_cost
            # 计算收益率
            syl = (price / cost - 1)*100
            log.info("    股票:%s(%s),数量:%s,成本:%s,收益:%.2f%%,市值:%.2f",name,s,total_amount,avg_cost,syl,total_amount_value)
    current_returns = 100 * context.portfolio.returns   
    log.info("【总资产: %s,当前收益：%.2f%%】",context.portfolio.total_value,current_returns)
       




'''
=========================mode1选股流程==============================
'''
def mode1_check_stock(context):
    #log.info("【今日选股: 】")
    # 1、基本控制,返回Series，index:code, column:statDate
    s_stat_date = mode1_controlBasic(context)
    # 2、质量控制,
    df_fin = mode1_controlReport(s_stat_date, 6)
    # 3、进一步过滤或排序
    mode1_stocks_rank(df_fin)
    
def mode1_controlBasic(context):
    # type: (Context) -> pd.Series
    # 基本条件：净利润>0, PE(0,25), 资产负债率 < 90%，确保数量少于3000家公司
    q = query(
        income.code
    ).filter(
        income.net_profit > 0,  # 净利润大于0
        valuation.pe_ratio > 0,  # PE [0,25]
        valuation.pe_ratio < 35,
        #valuation.market_cap > 20,
        balance.total_liability / balance.total_assets < 0.9  # 资产负债率 < 90%
    )
    primary_stks = list(get_fundamentals(q)['code'])

    # J金融，K房地产 行业
    notcall=finance.run_query(
        query(finance.STK_COMPANY_INFO.code,).filter(
            finance.STK_COMPANY_INFO.industry_id.in_([
                'J66'#货币金融服务
                ,'J67'#资本市场服务
                #,'J68'#保险业
                'J69'#其他金融业
                ,'K70'#房地产业
                ,'N78'#公共设施管理业
                ,'O79'#居民服务业
                ])
            )
        )
    notcall_stks = list(notcall['code'])

    # 筛选条件：符合基本条件的 1）非 J金融，K房地产；2）非次新股； 3)正常上市的(排除了st, *st, 退)。
    date_500days_ago = context.previous_date - datetime.timedelta(days=500)  # 500天之前的日期
    compinfo = finance.run_query(query(
        finance.STK_LIST.code,
    ).filter(
        finance.STK_LIST.code.in_(primary_stks),  # 符合基本条件
        ~finance.STK_LIST.code.in_(notcall_stks),  # 非 J金融，K房地产
        finance.STK_LIST.start_date < date_500days_ago,  # 非次新
        finance.STK_LIST.state_id == 301001  # 正常上市
    ))
    call_stks = list(compinfo['code'])
    
    # 查询最后报告时间
    q = query(
        income.statDate,
        income.code
    ).filter(
        income.code.in_(call_stks),
    )
    rets = get_fundamentals(q)
    
    rets = rets.set_index('code')

    return rets.statDate
def mode1_controlReport(s, period):
    # type: (pd.Series, int) -> pd.DataFrame
    stat_date_stocks = {sd: [stock for stock in s.index if s[stock] == sd] for sd in set(s.values)}  # {报告日期：股票列表}
    qt = query(
        income.statDate,
        income.code,
        income.operating_revenue,  # 营业收入
        indicator.adjusted_profit,  # 扣非净利润
        balance.bill_receivable,  # 应收票据
        balance.account_receivable,  # 应收账款
        balance.advance_peceipts,  # 预收账款
        # cash_flow.net_operate_cash_flow,  # 经营现金流
        # cash_flow.fix_intan_other_asset_acqui_cash,  # 购固取无
        # balance.total_assets,  # 资产总计
        # balance.total_liability,  # 负债合计
        # balance.shortterm_loan,  # “短期借款”
        # balance.longterm_loan,  # “长期借款”
        # balance.non_current_liability_in_one_year,  # “一年内到期的非流动性负债”
        # balance.bonds_payable  # “应付债券”、
    )
    # 分别取多期数据
    data_quarters = [[], [], []]
    for stat_date in stat_date_stocks.keys():  # 一个报告日 -> 6个季度 -> 2个季度一组，共3组
        lqt = qt.filter(balance.code.in_(stat_date_stocks[stat_date]))
        #
        arr_quarters = mode1_get_past_quarters(stat_date, period)
        for i in range(len(arr_quarters)):  # 3组
            #
            df_two_quarter = pd.DataFrame()
            for statq in arr_quarters[i]:  # 每组两个季度
                oneData = get_fundamentals(lqt, statDate=statq)
                if len(oneData) > 0:
                    df_two_quarter = df_two_quarter.append(oneData)
            #
            if len(df_two_quarter) > 0:
                df_two_quarter = df_two_quarter.fillna(0)
                data_quarters[i].append(df_two_quarter)

    # 2个季度一组，共3组, 对应3个df
    df_qr01 = pd.concat(data_quarters[0]) if len(data_quarters[0]) > 1 else data_quarters[0][0]
    df_qr23 = pd.concat(data_quarters[1]) if len(data_quarters[1]) > 1 else data_quarters[1][0]
    df_qr45 = pd.concat(data_quarters[2]) if len(data_quarters[2]) > 1 else data_quarters[2][0]

    # 合并01和23，计算一年的应收账款周转率
    df_year = df_qr01.append(df_qr23)
    # 按公司分组，求sum: 营业收入，扣非净利润，mean：应收票据，应收账款，预付账款, count: statDate
    group_by_code = df_year.groupby('code')
    df_year_count = group_by_code[['statDate']].count()
    df_year_sum = group_by_code[['operating_revenue', 'adjusted_profit']].sum()
    df_year_mean = group_by_code[['account_receivable', 'bill_receivable', 'advance_peceipts']].mean()
    df_year_code = pd.concat([df_year_count, df_year_sum, df_year_mean], axis=1)
    df_year_code['receivable'] = df_year_code['account_receivable'] + df_year_code['bill_receivable'] - df_year_code[
        'advance_peceipts']
    df_year_code['ar_turnover_rate'] = df_year_code['operating_revenue'] / df_year_code['receivable'].replace(0, np.inf)
    ## 够四个季度的， 应收账款周转率 > 6 或者 <=0
    df_year_code = df_year_code[(df_year_code.statDate == 4) & (
            (df_year_code['ar_turnover_rate'] > 6.0) | (df_year_code['ar_turnover_rate'] <= 0))]

    ## 01, 23, 45 分别计算adjusted_profit之和
    df_qr01_code = df_qr01.groupby('code')[['adjusted_profit']].sum()
    df_qr01_code.columns = ['qr01']
    df_qr23_code = df_qr23.groupby('code')[['adjusted_profit']].sum()
    df_qr23_code.columns = ['qr23']
    df_qr45_code = df_qr45.groupby('code')[['adjusted_profit']].sum()
    df_qr45_code.columns = ['qr45']
    ## 合并，计算环比，同比
    df_comp = pd.concat([df_qr01_code, df_qr23_code, df_qr45_code], axis=1)
    df_comp['hb'] = df_comp['qr01'] / df_comp['qr23']
    df_comp['tb'] = df_comp['qr01'] / df_comp['qr45']

    # 合并： df_year_code, df_comp
    #df_rets = pd.concat([df_year_code[['adjusted_profit']], df_comp[['hb', 'tb']]], axis=1, sort=False).dropna()
    df_rets = pd.concat([df_year_code[['adjusted_profit']], df_comp[['hb', 'tb']]], axis=1,join_axes=[df_year_code.index]).dropna()
    # df_rets = df_rets[(df_rets.tb > 0)]  # (df_rets.hb>0) &
    return df_rets
def mode1_stocks_rank(df_fin):
    if len(df_fin) <= 0:
        return
    # 5、PE<20
    q_cap = query(valuation.code, valuation.market_cap).filter(valuation.code.in_(list(df_fin.index)))
    df_cap = get_fundamentals(q_cap).set_index('code')
    df_pe = pd.concat([df_fin, df_cap], axis=1)  # df_pe.merge(df_cap)
    df_pe['pe'] = df_pe['market_cap'] * 100000000 / df_pe['adjusted_profit']
    df_pe = df_pe[(df_pe['pe'] < 20) & (df_pe['pe'] > 0)]
    df_pe = df_pe.sort(['pe'], ascending=True).reset_index(drop=False)
    df_pe['pes'] = 100 - df_pe.index * 100 / len(df_pe)
    df_pe = df_pe.sort(['hb'], ascending=False).reset_index(drop=True)
    df_pe['hbs'] = 100 - df_pe.index * 100 / len(df_pe)
    df_pe = df_pe.sort(['tb'], ascending=False).reset_index(drop=True)
    df_pe['tbs'] = 100 - df_pe.index * 100 / len(df_pe)
    df_pe['s'] = df_pe['pes'] * 1.0 + df_pe['hbs'] * 0.5 + df_pe['tbs'] * 0.4
    df_pe = df_pe.sort(['s'], ascending=False).reset_index(drop=True)
    #print(df_pe[['code', 'hb', 'tb', 'pe', 's']][:10])
    g.mode1_buy_list = list(df_pe.code[:10])
    
    current_data = get_current_data()
    
    if len(g.mode1_buy_list)>0:
        log.info("【今日选股:】")
        i = 0
        for s in g.mode1_buy_list:
            i += 1
            if i < 10:
                log.info("    %d . %s,%s" % (i,s,current_data[s].name))
            else:
                log.info("    %d. %s,%s" % (i,s,current_data[s].name))
def mode1_get_past_quarters(stat_date, num):
    # type: (str, int) -> np.ndarray
    '''
    参数：'2019-09-30', 6, 两个季度一组，共三组
    返回：array([['2019q3', '2019q2'], ['2019q1', '2018q4'], ['2018q3', '2018q2']])
    '''
    date_stat = datetime.datetime.strptime(stat_date, '%Y-%m-%d').date()
    year = date_stat.year
    month = date_stat.month
    #
    list_quarter = []
    for i in range(num):
        if month < 3:
            year -= 1
            month = 12
        quarter = (month - 1) // 3 + 1
        list_quarter.append('{}q{}'.format(year, quarter))
        #
        month -= 3
    #
    return np.array(list_quarter).reshape(3, 2)


#用numpy计算线性回归100天大约13毫秒左右
def calc_rsrs(high,low,index,M,N):
    start=len(high)-M
    arr_ret=np.empty([M,5],dtype=np.float32)
    for i in np.arange(0,M):
        x=low[start+i-N+1:start+i+1]
        y=high[start+i-N+1:start+i+1]
        A = np.vstack((x, np.ones(len(x)))).T
        model,resid = np.linalg.lstsq(A, y)[:2]
        r2 = 1 - resid / (y.size * y.var())
        arr_ret[i,0]=model[0]
        arr_ret[i,1]=r2
    arr_ret[:,2]=stats.zscore(arr_ret[-M:,0])
    arr_ret[:,3]=arr_ret[-M:,2]*arr_ret[-M:,1]
    arr_ret[:,4]=arr_ret[-M:,0]*arr_ret[-M:,3]
    df1=pd.DataFrame(arr_ret,columns=['rsrs','r2','zscore','RSRS_revise','RSRS_negative_r'],index=index[-M:])
    return df1


    
'''
============================mode2选股流程=====================
'''


def mode2_pe_check_month(context):
	
	g.mode2_temp_list = []
	g.mode2_buy_list = []
	start = '2005-01-01'  # 时间序列范围
	end = context.previous_date
	time_list = list(pd.date_range(start, end, freq='M'))
	#print("time_list:",time_list)
	# 获取数据
	sector = '000300.XSHG'
	pe_data = []
	for date in time_list:
		_ret_val = np.nan
		stocks = get_index_stocks(sector, date=date)
		if stocks:
			q = query(valuation.code, valuation.market_cap, valuation.pe_ratio).filter(valuation.code.in_(stocks))
			df = get_fundamentals(q, date)
			_ret_val = avg_calc(df)
		
		if not np.isnan(_ret_val):
			pe_data.append(_ret_val)
	
		pe_arr = np.array(pe_data)
		zws_50 = np.median(pe_arr)

	g.mode2_flag = 0
	if len(pe_arr) >= 3:
		
		if pe_arr[-2] < pe_arr[-1] < zws_50:
			#log.info("Pe上行，操作股票:")
			g.mode2_flag = 1
			

def mode2_pe_check_week(context):
	start = '2009-01-01'  # 时间序列范围
	end = context.previous_date
	time_list = list(pd.date_range(start, end, freq='w-mon'))[-5:]
	# 获取数据
	sector = '000300.XSHG'
	pe_data = []
	for date in time_list:
		_ret_val = np.nan
		stocks = get_index_stocks(sector, date=date)
		if stocks:
			q = query(valuation.code, valuation.market_cap, valuation.pe_ratio).filter(valuation.code.in_(stocks))
			df = get_fundamentals(q, date)
			_ret_val = avg_calc(df)
		if not np.isnan(_ret_val):
			pe_data.append(_ret_val)
		pe_arr = np.array(pe_data)
	g.mode2_flag = 0
	if len(pe_arr) >= 3:
		if pe_arr[-2] > pe_arr[-1] :
			g.mode2_flag = 0
	

def mode2_check_stock(context):  # 根据7日涨幅降序排列，取涨得最快的
    #g.mode2_buy_list = []
    deltadays = 120  # 次新股的上市自然天数界限
    delta_date = context.previous_date - datetime.timedelta(deltadays)

    # 去掉上市不足120个交易日的次新股之后的全市场股票
    stock_list = list(get_all_securities(types=['stock'], date=delta_date).index)

    # 条件1：与8天前相比，收盘价上涨了20%
    h = history(8, '1d', 'close', stock_list)
    #s = (h.iloc[-1] / h.iloc[0]).sort_values(ascending=False)  # 按照7日涨幅降序排列
    s = (h.iloc[-1] / h.iloc[0]) # 按照7日涨幅降序排列
    s.sort(ascending=False)
    stock_list = list(s[s > 1.2].index)

    # 条件2：过滤掉：1）三停：涨停、跌停、停牌；2）三特：st, *st, 退；3）科创
    curr_data = get_current_data()
    stock_list = [stock for stock in stock_list if not (
            (curr_data[stock].day_open == curr_data[stock].high_limit) or
            (curr_data[stock].day_open == curr_data[stock].low_limit) or
            curr_data[stock].paused or
            curr_data[stock].is_st or
            ('ST' in curr_data[stock].name) or
            ('*' in curr_data[stock].name) or
            ('退' in curr_data[stock].name) or
            (stock.startswith('688'))
    )]
    # 条件3：没在龙虎榜；或者在龙虎榜中，但净流入不小于负数1个亿
    if len(stock_list) > 0:
        df_bb = get_billboard_list(stock_list, end_date=context.previous_date, count=1)
        s_bb = df_bb.groupby('code')['net_value'].sum()
        for stock in s_bb.index:
            if s_bb.loc[stock] < -100000000:
                stock_list.remove(stock)

    # 确定目标
    print("g.mode2_buy_list :",g.mode2_buy_list )
    
    g.mode2_temp_list = stock_list[:5]
    print("g.mode2_temp_list :",g.mode2_temp_list )
    #可能写的有问题
    g.mode2_buy_list = g.mode2_temp_list + [code for code in g.mode2_buy_list if code not in g.mode2_temp_list]
    current_data = get_current_data()
    
    if len(g.mode2_buy_list)>0:
        log.info("【今日选股:】")
        i = 0
        for s in g.mode2_buy_list:
            i += 1
            if i < 10:
                log.info("    %d . %s,%s" % (i,s,current_data[s].name))
            else:
                log.info("    %d. %s,%s" % (i,s,current_data[s].name))


def mode2_stop_loss(context):
    # type: (Context) -> None
    current_data = get_current_data()
    sell_list = context.portfolio.positions
    sell_list = [s for s in sell_list if s not in g.mode1_buy_list]
    for stock in sell_list:
        if context.portfolio.positions[stock].closeable_amount > 0:
            n_pre_close = attribute_history(stock, 1, '1d', 'close', df=False)['close'][-1]
            if current_data[stock].last_price < 0.94 * n_pre_close:  # 下跌超过6%
                order_target(stock, 0)
                log.info("【执行盘中调仓交易】")
                log.info('    盘中调仓卖出: %s,  委托价格: %.2f',stock,current_data[stock].last_price)
                


def mode2_stop_holds(context):
    # type: (Context) -> None
    current_data = get_current_data()
    sell_list = context.portfolio.positions
    sell_list = [s for s in sell_list if s not in g.mode1_buy_list]
    for stock in sell_list:
        if context.portfolio.positions[stock].closeable_amount > 0:
            n_pre_close = attribute_history(stock, 1, '1d', 'close', df=False)['close'][-1]
            if current_data[stock].last_price < 1.04 * n_pre_close:  # 一天都没有涨到4%，放弃
                order_target(stock, 0)
                log.info("【执行盘中调仓交易】")
                log.info('    盘中调仓卖出: %s,  委托价格: %.2f',stock,current_data[stock].last_price)
                


def avg_calc(df):
    try:
        avg = sum(df['market_cap']) / sum(df['market_cap'] / df['pe_ratio'])
    except:
        avg = np.nan
    return avg

    
    

'''    
=============================rsrs指标=========================
'''





def after_code_changed(context):
    # 取消所有定时运行
    unschedule_all()
    
     #9:00先计算mode2_flag如果为0则用rsrs计算mode1_flag，取flag为1的模式的buy_list作为当日操作
    run_monthly(mode2_pe_check_month, 1,time='09:00')
    run_weekly(mode2_pe_check_week, 1,time='09:05')
    run_daily(before_markt_open, time='09:10', reference_security='000300.XSHG')
    
    
    #9:16卖出flag为1的不在buy_list的股票
    run_daily(before_markt_open_trade_sell, time='09:16', reference_security='000300.XSHG')
    
    
    #9:26买入flag为1的buy_list的股票
    #run_daily(before_markt_open_trade_buy, time='09:26', reference_security='000300.XSHG')
    #run_daily(before_markt_open_trade_buy, time='09:27', reference_security='000300.XSHG')
    run_daily(before_markt_open_trade_buy, time='09:28', reference_security='000300.XSHG')
    #run_daily(before_markt_open_trade_buy, time='09:29', reference_security='000300.XSHG')
    
    #开盘复核买入
    run_daily(markt_open_trade, time='09:30', reference_security='000300.XSHG')
    
    #模式2的票盘中交易
    run_daily(mode2_stop_loss, '10:30', reference_security='000300.XSHG')
    run_daily(mode2_stop_loss, '11:30', reference_security='000300.XSHG')
    run_daily(mode2_stop_loss, '13:30', reference_security='000300.XSHG')
    run_daily(mode2_stop_loss, '14:30', reference_security='000300.XSHG')
    run_daily(mode2_stop_holds, '14:50', reference_security='000300.XSHG')

    
    
    #10:00买入etf_list 中的股票
    run_daily(during_markt_open_trade, time='10:00', reference_security='000300.XSHG')
    
    
    #周一到周四尾盘卖出511880，买入逆回购（需券商支持自动购买1日逆回购），周五持有511880
    run_weekly(before_markt_close_trade, weekday=1, time='14:50', reference_security='000300.XSHG')
    run_weekly(before_markt_close_trade, weekday=2, time='14:50', reference_security='000300.XSHG')
    run_weekly(before_markt_close_trade, weekday=3, time='14:50', reference_security='000300.XSHG')
    run_weekly(before_markt_close_trade, weekday=4, time='14:50', reference_security='000300.XSHG')
    #收盘后打印持仓情况
    run_daily(after_market_close,time='after_close', reference_security='000300.XSHG')

    
