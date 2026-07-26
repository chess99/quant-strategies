# 克隆自聚宽文章：https://www.joinquant.com/post/41155
# 标题：wywy1995大神机器学习策略年化提升35pt
# 作者：斯科尔斯

# https://www.joinquant.com/view/community/detail/30684f8d65a74eef0d704239f0eec8be?type=1&page=5
#导入函数库
from jqdata import *
from jqfactor import *
import numpy as np
import pandas as pd
import statsmodels.api as sm


#初始化函数 
def initialize(context):
    # 设定基准
    set_benchmark('000300.XSHG')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 设置交易成本万分之三，不同滑点影响可在归因分析中查看
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003, close_today_commission=0, min_commission=5),type='stock')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    #初始化全局变量
    g.stock_num = 10
    g.hold_list = [] #当前持仓的全部股票    
    g.target_list = []
    g.yesterday_HL_list = [] #记录持仓中昨日涨停的股票
    g.not_buy_again = []
    g.factor_list = [
        'price_no_fq', #技术指标因子 不复权价格因子
        'total_profit_to_cost_ratio', #质量类因子 成本费用利润率
        'inventory_turnover_rate' #质量类因子 存货周转率
        ]
    # 设置交易运行时间
    run_daily(prepare_stock_list, time='9:05', reference_security='000300.XSHG')
    # 为了实盘的时候，买掉股票后可以立马成交，从而可以买入新股票，所以选择9:24
    run_weekly(weekly_adjustment, 1, time='9:30', reference_security='000300.XSHG')
    run_daily(trade_morning,time='9:26',reference_security='000300.XSHG')
    run_daily(trade_afternoon, time='13:00', reference_security='000300.XSHG') #检查持仓中的涨停股是否需要卖出
    #run_daily(print_position_info, time='15:10', reference_security='000300.XSHG')



#1-1 准备股票池
def prepare_stock_list(context):
    #获取已持有列表
    g.hold_list= []
    for position in list(context.portfolio.positions.values()):
        stock = position.security
        g.hold_list.append(stock)
    #获取昨日涨停列表
    if g.hold_list != []:
        df = get_price(g.hold_list, end_date=context.previous_date, frequency='daily', fields=['close','high_limit'], count=1, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        g.yesterday_HL_list = list(df.code)
    else:
        g.yesterday_HL_list = []
    #提早准备今日股票list
    g.target_list = get_stock_list(context)    
    

#1-2 选股模块
def get_stock_list(context):
    yesterday = context.previous_date
    initial_list = get_all_securities().index.tolist()
    initial_list = filter_new_stock(context, initial_list)
    initial_list = filter_kcbj_stock(initial_list)
    initial_list = filter_st_stock(initial_list)
    factor_values = get_factor_values(initial_list, [
        g.factor_list[0],
        g.factor_list[1],
        g.factor_list[2],
        ], end_date=yesterday, count=1)
    df = pd.DataFrame(index=initial_list, columns=factor_values.keys())
    df[g.factor_list[0]] = list(factor_values[g.factor_list[0]].T.iloc[:,0])
    df[g.factor_list[1]] = list(factor_values[g.factor_list[1]].T.iloc[:,0])
    df[g.factor_list[2]] = list(factor_values[g.factor_list[2]].T.iloc[:,0])
    df = df.dropna()
    coef_list = [
        -6.123355346008858e-05,
        -0.002579342458393642,
        -2.194257357346814e-06
        ]
    df['total_score'] = coef_list[0]*df[g.factor_list[0]] + coef_list[1]*df[g.factor_list[1]] + coef_list[2]*df[g.factor_list[2]]
    df = df.sort_values(by=['total_score'], ascending=False) #分数越高即预测未来收益越高，排序默认降序
    complex_factor_list = list(df.index)[:max(int(0.1*len(list(df.index))),g.stock_num)]
    q = query(valuation.code,valuation.circulating_market_cap,indicator.eps).filter(valuation.code.in_(complex_factor_list)).order_by(valuation.circulating_market_cap.asc())
    df = get_fundamentals(q)
    df = df[df['eps']>0]
    final_list  = list(df.code)
    
    final_list = filter_paused_stock(final_list)
    final_list = filter_limitup_stock(context, final_list)
    final_list = filter_limitdown_stock(context, final_list)
    return final_list

#1-3 整体调整持仓
def weekly_adjustment(context):
    g.not_buy_again = []
    target_list = g.target_list
    #获取应买入列表 
    #截取不超过最大持仓数的股票量
    target_list = target_list[:min(g.stock_num, len(target_list))]
    #调仓卖出
    for stock in g.hold_list:
        if (stock not in target_list) and (stock not in g.yesterday_HL_list):
            log.info("卖出[%s]" % (stock))
            position = context.portfolio.positions[stock]
            close_position(position)
        else:
            log.info("持有[%s]" % (stock))
    #调仓买入
    buy_security(context,target_list)
    #记录已买入的股票
    for position in list(context.portfolio.positions.values()):
        stock = position.security
        g.not_buy_again.append(stock)

    #微信通知 
    if context.run_params == 'sim_trade':
        weixin_message_text = '\n卖出:'.join(list(set(g.hold_list).difference(set(target_list))))\
            +'\n买入:'.join(list(set(target_list).difference(set(g.hold_list))))
        send_message(weixin_message_text,channel='weixin')
        #send_email(list(set(g.hold_list).difference(set(target_list))),list(set(target_list).difference(set(g.hold_list))))

#1-4 调整昨日涨停股票
def check_limit_up(context):
    now_time = context.current_dt
    if g.yesterday_HL_list != []:
        #对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
        for stock in g.yesterday_HL_list:
            current_data = get_price(stock, end_date=now_time, frequency='1m', fields=['close','high_limit'], skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True)
            if current_data.iloc[0,0] < current_data.iloc[0,1]:
                log.info("[%s]涨停打开，卖出" % (stock))
                position = context.portfolio.positions[stock]
                close_position(position)
            else:
                log.info("[%s]涨停，继续持有" % (stock))
    

#1-5 如果昨天有股票卖出或者买入失败，剩余的金额今天早上买入
def check_remain_amount(context):
    g.hold_list= []
    for position in list(context.portfolio.positions.values()):
        stock = position.security
        g.hold_list.append(stock)
    if len(g.hold_list) < g.stock_num:
        print('有余额可用，多买入一只'+str(context.portfolio.cash))
        target_list = g.target_list
        #剔除本周一曾买入的股票，不再买入
        target_list = filter_not_buy_again(target_list)
        target_list = target_list[:min(g.stock_num, len(target_list))]
        buy_security(context,target_list)

#1-6 下午检查交易
def trade_afternoon(context):
    check_limit_up(context)
    check_remain_amount(context)
    
def trade_morning(context):
    # 周一不执行，因为周一主交易代码，这里只是补充,0代表周一  
    if context.current_dt.weekday() in (2,3,4,5):
        check_remain_amount(context)

#2-1 过滤停牌股票
def filter_paused_stock(stock_list):
	current_data = get_current_data()
	return [stock for stock in stock_list if not current_data[stock].paused]

#2-2 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
	current_data = get_current_data()
	return [stock for stock in stock_list
			if not current_data[stock].is_st
			and 'ST' not in current_data[stock].name
			and '*' not in current_data[stock].name
			and '退' not in current_data[stock].name]

#2-3 过滤科创北交股票
def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68' or stock[0] == '3':
            stock_list.remove(stock)
    return stock_list

#2-4 过滤涨停的股票
def filter_limitup_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] < current_data[stock].high_limit]

#2-5 过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] > current_data[stock].low_limit]

#2-6 过滤次新股
def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=375)]


#2-7 删除本周一买入的股票
def filter_not_buy_again(stock_list):
    return [stock for stock in stock_list if stock not in g.not_buy_again]

#3-1 交易模块-自定义下单
def order_target_value_(security, value):
	if value == 0:
		log.debug("Selling out %s" % (security))
	else:
		log.debug("Order %s to value %f" % (security, value))
	return order_target_value(security, value)

#3-2 交易模块-开仓
def open_position(security, value):
	order = order_target_value_(security, value)
	if order != None and order.filled > 0:
		return True
	return False

#3-3 交易模块-平仓
def close_position(position):
	security = position.security
	order = order_target_value_(security, 0)  # 可能会因停牌失败
	if order != None:
		if order.status == OrderStatus.held and order.filled == order.amount:
			return True
	return False

#3-4 卖出模块
def buy_security(context,target_list):
    #调仓买入
    position_count = len(context.portfolio.positions)
    target_num = len(target_list)
    if target_num > position_count:
        value = context.portfolio.cash / (target_num - position_count)
        for stock in target_list:
            if stock not in context.portfolio.positions:
                if open_position(stock, value):
                    log.info("买入[%s]（%s元）" % (stock,value))
                    g.not_buy_again.append(stock) #持仓清单，后续不希望再买入
                    if len(context.portfolio.positions) == target_num:
                        break

#4-1 打印每日持仓信息
def print_position_info(context):
    #打印当天成交记录
    trades = get_trades()
    for _trade in trades.values():
        print('成交记录：'+str(_trade))
    #打印账户信息
    for position in list(context.portfolio.positions.values()):
        securities=position.security
        cost=position.avg_cost
        price=position.price
        ret=100*(price/cost-1)
        value=position.value
        amount=position.total_amount    
        print('代码:{}'.format(securities))
        print('成本价:{}'.format(format(cost,'.2f')))
        print('现价:{}'.format(price))
        print('收益率:{}%'.format(format(ret,'.2f')))
        print('持仓(股):{}'.format(amount))
        print('市值:{}'.format(format(value,'.2f')))
        print('———————————————————————————————————')
    print('———————————————————————————————————————分割线————————————————————————————————————————')

#4-2 发送邮件通知
def send_email(sell_list,buy_list):
    import smtplib 
    from email.mime.text import MIMEText 
    from email.header import Header
    
    sender = '<redacted-email>' #发送的邮箱 
    receiver = '<redacted-email>' #要接受的邮箱（注:测试中发送其他邮箱会提示错误） 
    smtpserver = 'smtp.sina.com'  
    username = '<redacted-email>' #发送的邮箱 
    password = '<redacted-secret>' #你的邮箱密码 或 口令 
    subject = '量化交易信号' 
    message = sell_list.to_json()+'\n'+buy_list.to_json
    msg = MIMEText(message,'plain','utf-8') #中文需参数‘utf-8'，单字节字符不需要 
    msg['Subject'] = Header(subject, 'utf-8') #邮件主题 msg['from'] = sender #发送的邮箱
    msg['from'] = sender #发送的邮箱

    smtp = smtplib.SMTP_SSL(smtpserver, 465) 
    try: 
        smtp.login(username, password) # 登陆 
        smtp.sendmail(sender, receiver, msg.as_string()) #发送 
        log.info('邮件发送成功') 
    except smtplib.SMTPException: 
        log.info('邮件发送失败')  
        print("Error: 无法发送邮件")
    smtp.quit() # 结束
    
def after_code_changed(context):
    # 取消所有定时运行
    unschedule_all()
    # 设置交易运行时间
    run_daily(prepare_stock_list, time='9:05', reference_security='000300.XSHG')
    # 为了实盘的时候，买掉股票后可以立马成交，从而可以买入新股票，所以选择9:24卖出，26买入
    run_weekly(weekly_adjustment, 1, time='9:30', reference_security='000300.XSHG')
    run_daily(trade_morning,time='9:26',reference_security='000300.XSHG')
    run_daily(trade_afternoon, time='13:00', reference_security='000300.XSHG') #检查持仓中的涨停股是否需要卖出
    #run_daily(print_position_info, time='15:10', reference_security='000300.XSHG')
