# 克隆自聚宽文章：https://www.joinquant.com/post/47953
# 标题：国九条 年化130.74% 回撤11%  众神Debug版
# 作者：热情的刀

# 众神Debug版

#蒋老师操刀修改两个模块1-8 动态调仓代码 2.1 筛选审计意见

# 克隆自聚宽文章：https://www.joinquant.com/post/47946
# 标题：国九条后中小板微盘小改，年化135.40%
# 作者：子匀


from jqdata import *
from jqfactor import *
import numpy as np
import pandas as pd
from datetime import time,date
from jqdata import finance

#初始化函数 
def initialize(context):
    # 开启防未来函数
    set_option('avoid_future_data', True)
    # 成交量设置
    #set_option('order_volume_ratio', 0.10)
    # 设定基准
    set_benchmark('399101.XSHE')
    # 用真实价格交易
    set_option('use_real_price', True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(3/10000))
    # 设置交易成本万分之三，不同滑点影响可在归因分析中查看
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=2.5/10000, close_commission=2.5/10000, close_today_commission=0, min_commission=5),type='stock')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    log.set_level('system', 'error')
    log.set_level('strategy', 'debug')
    #初始化全局变量 bool
    g.trading_signal = True  # 是否为可交易日
    g.run_stoploss = True  # 是否进行止损
    g.filter_audit = True  # 是否筛选审计意见
    g.filter_bonus= True   #是否筛选红利
    g.adjust_num = True  # 是否调整持仓数量
    
    #全局变量list
    g.hold_list = [] #当前持仓的全部股票    
    g.yesterday_HL_list = [] #记录持仓中昨日涨停的股票
    g.target_list = []
    g.pass_months = [1,4]  # 空仓的月份
    g.limitup_stocks = []   # 记录涨停的股票避免再次买入
    g.Expected_bonus= [5]  #设定引入超额收益的因子的月份
    
    #全局变量float/str
    g.min_mv = 10  # 股票最小市值要求
    g.max_mv = 10000  # 股票最大市值要求
    g.stock_num = 4  # 持股数量

    g.stoploss_list = []  # 止损卖出列表
    g.other_sale    = []  # 其他卖出列表
    g.stoploss_strategy = 3  # 1为止损线止损，2为市场趋势止损, 3为联合1、2策略
    g.stoploss_limit = 0.09  # 止损线
    g.stoploss_market = 0.05  # 市场趋势止损参数
    g.highest = 50  # 股票单价上限设置
    g.money_etf = '511880.XSHG'  # 空仓月份持有银华日利ETF
    
    # 设置交易运行时间
    run_daily(prepare_stock_list, '9:05')
    run_daily(trade_afternoon, time='14:00', reference_security='399101.XSHE') #检查持仓中的涨停股是否需要卖出
    run_daily(stop_loss, time='10:00') # 止损函数
    run_daily(close_account, '14:50')
    run_weekly(weekly_adjustment,2,'10:00')
    #run_weekly(print_position_info, 5, time='15:10', reference_security='000300.XSHG')

#1-1 准备股票池
def prepare_stock_list(context):
    #获取已持有列表
    g.limitup_stocks = []
    g.hold_list = list(context.portfolio.positions)
    #获取昨日涨停列表
    if g.hold_list:
        df = get_price(g.hold_list, end_date=context.previous_date, frequency='daily', fields=['close','high_limit','low_limit'], count=1, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        g.yesterday_HL_list = df['code'].tolist()
    else:
        g.yesterday_HL_list = []
    #判断今天是否为账户资金再平衡的日期
    g.trading_signal = today_is_between(context)

#1-2 选股模块
def get_stock_list(context):
    final_list = []
    MKT_index = '399101.XSHE'
    initial_list = filter_stocks(context, get_index_stocks(MKT_index))
    # 国九更新：过滤近一年净利润为负且营业收入小于1亿的
    # 国九更新：过滤近一年期末净资产为负的 (经查询没有为负数的，所以直接pass这条)
    # 国九更新：过滤近一年审计建议无法出具或者为负面建议的 (经过净利润等筛选，审计意见几乎不会存在异常)
    q = query(
        valuation.code,
    ).filter(
        valuation.code.in_(initial_list),
        valuation.market_cap.between(g.min_mv,g.max_mv),  # 总市值 circulating_market_cap/market_cap 单位：亿元
        income.np_parent_company_owners > 0,   # 归属于母公司所有者的净利润(元)
        income.net_profit > 0,  # 净利润(元)
        income.operating_revenue > 1e8,  # 营业收入 (元)
        indicator.roe>0,
        indicator.roa>0,
    ).order_by(valuation.market_cap.asc()).limit(g.stock_num*3)
    
    df = get_fundamentals(q)

    final_list = df['code'].tolist()
    
    #筛选审计意见
    if g.filter_audit:
        final_list = filter_audit(context, final_list)
    
    #筛选红利
    if g.filter_bonus: 
        final_list = bonus_filter(context,final_list)

    if final_list:
        last_prices = history(1, unit='1d', field='close', security_list=final_list)
        return [stock for stock in final_list if stock in g.hold_list or last_prices[stock][-1] <= g.highest]
    else:
        # 由于有时候选股条件苛刻，所以会没有股票入选，这时买入银华日利ETF
        log.info('无适合股票，买入ETF')
        return [g.money_etf]        

#1-3 整体调整持仓
def weekly_adjustment(context):
    if g.trading_signal:
        if g.adjust_num:
            new_num = adjust_stock_num(context)
            g.stock_num = new_num
            log.info(f'持仓数量修改为{new_num}')
        g.target_list = get_stock_list(context)[:g.stock_num]
        log.info(str(g.target_list))
        
        sell_list = [stock for stock in g.hold_list if stock not in g.target_list and stock not in g.yesterday_HL_list]
        hold_list = [stock for stock in g.hold_list if stock in g.target_list or stock in g.yesterday_HL_list]
        log.info("卖出[%s]" % (str(sell_list)))
        log.info("已持有[%s]" % (str(hold_list)))

        for stock in sell_list:
            order_target_value(stock, 0)
        
        buy_list = [stock for stock in g.target_list if stock not in g.hold_list]
        buy_security(context, buy_list,len(buy_list))

    else:
        buy_security(context, [g.money_etf],1)
        log.info('该月份为空仓月份，持有银华日利ETF')


#1-4 调整昨日涨停股票
def check_limit_up(context):
    now_time = context.current_dt
    if g.yesterday_HL_list != []:
        #对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
        for stock in g.yesterday_HL_list:
            current_data = get_price(stock, end_date=now_time, frequency='1m', fields=['close','high_limit'], skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True)
            if current_data.iloc[0,0] <    current_data.iloc[0,1]:
                log.info("[%s]涨停打开，卖出" % (stock))
                order_target_value(stock, 0)
                g.other_sale.append(stock)
                g.limitup_stocks.append(stock)
            else:
                log.info("[%s]涨停，继续持有" % (stock))

#1-5 如果昨天有股票卖出或者买入失败造成空仓，剩余的金额当日买入
def check_remain_amount(context):
    addstock_num = len(g.other_sale)
    loss_num = len(g.stoploss_list)
    empty_num = addstock_num + loss_num
    
    g.hold_list = context.portfolio.positions
    if len(g.hold_list) < g.stock_num:   
        # 计算需要买入的股票数量，止损仓位补足货币etf
        # 可替换下一行代码以更换逻辑：改为将清空仓位全部补足股票，而非原作中止损仓位补充货币etf
        # num_stocks_to_buy = min(empty_num,g.stock_num-len(g.hold_list))
        num_stocks_to_buy = min(addstock_num,g.stock_num-len(g.hold_list))
        target_list = [stock for stock in g.target_list if stock not in g.limitup_stocks][:num_stocks_to_buy]
        log.info('有余额可用'+str(round((context.portfolio.cash),2))+'元。买入'+ str(target_list))
        buy_security(context,target_list,len(target_list))
        if loss_num !=0:
            log.info('有余额可用'+str(round((context.portfolio.cash),2))+'元。买入货币基金'+ str(g.money_etf))
            buy_security(context,[g.money_etf],loss_num)
    
    g.stoploss_list = []
    g.other_sale    = []

#1-6 下午检查交易
def trade_afternoon(context):
    if g.trading_signal:
        check_limit_up(context)
        check_remain_amount(context)
        buy_security(context,[g.money_etf],1)
        
#1-7 止盈止损
def stop_loss(context):
    if g.run_stoploss:
        current_positions = context.portfolio.positions
        if g.stoploss_strategy == 1 or g.stoploss_strategy == 3:
            for stock in current_positions.keys():
                price = current_positions[stock].price
                avg_cost = current_positions[stock].avg_cost
                # 个股盈利止盈
                if price >= avg_cost * 2:
                    order_target_value(stock, 0)
                    log.debug("收益100%止盈,卖出{}".format(stock))
                    g.other_sale.append(stock)
                # 个股止损
                elif price < avg_cost * (1 - g.stoploss_limit):
                    order_target_value(stock, 0)
                    log.debug("收益止损,卖出{}".format(stock))
                    g.stoploss_list.append(stock)

        if g.stoploss_strategy == 2 or g.stoploss_strategy == 3:
            stock_df = get_price(security=get_index_stocks('399101.XSHE')
                        ,end_date=context.previous_date, frequency='daily'
                        ,fields=['close', 'open'], count=1, panel=False)
            # 计算成分股平均涨跌，即指数涨跌幅
            down_ratio = (1 - stock_df['close'] / stock_df['open']).mean()
            # 市场大跌止损
            if down_ratio >= g.stoploss_market:
                for stock in current_positions.keys():
                    g.stoploss_list.append(stock)
                    order_target_value(stock, 0)
                    log.debug("大盘惨跌,平均降幅{:.2%}".format(down_ratio))
               
                


#1-8 动态调仓代码
def adjust_stock_num(context):
    arr_close = history(10,'1d','close','399101.XSHE', df=False)['399101.XSHE']
    bias =100*(arr_close[-1]/arr_close.mean()-1)
    #根据差值结果返回数字
    result = \
        3 if bias >= 5 else \
            3 if 2 <= bias else \
                4 if -2 <= bias else  \
                    5 if -5 <= bias else \
                        6
    return result
    

#2 过滤各种股票
def filter_stocks(context, stock_list):
    current_data = get_current_data()
        # 涨跌停和最近价格的判断
    last_prices = history(1, unit='1m', field='close', security_list=stock_list)
        # 过滤标准
    filtered_stocks = []
    for stock in stock_list:
        if current_data[stock].paused:  # 停牌
            continue
        if current_data[stock].is_st:  # ST
            continue
        if '退' in current_data[stock].name:  # 退市
            continue
        if stock.startswith('30') or stock.startswith('68') or stock.startswith('8') or stock.startswith('4'):  # 市场类型
            continue
        if not (stock in context.portfolio.positions or last_prices[stock][-1] < current_data[stock].high_limit):  # 涨停
            continue
        if not (stock in context.portfolio.positions or last_prices[stock][-1] > current_data[stock].low_limit):  # 跌停
            continue
        # 次新股过滤
        start_date = get_security_info(stock).start_date
        if context.previous_date - start_date < timedelta(days=375):
            continue
        filtered_stocks.append(stock)
    return filtered_stocks

#2.1 筛选审计意见
def filter_audit(context, stock_list):
    #剔除近三年内有不合格(opinion_type_id >2 且不是 6)审计意见的股票
    start_date = datetime.date(context.current_dt.year - 3,1,1).strftime('%Y-%m-%d')
    end_date = context.previous_date.strftime('%Y-%m-%d')
    q = query(finance.STK_AUDIT_OPINION).filter(finance.STK_AUDIT_OPINION.code.in_(stock_list),
                                                finance.STK_AUDIT_OPINION.report_type == 0, #0:财务报表审计报告
                                                finance.STK_AUDIT_OPINION.opinion_type_id >2, #1:无保留,2:无保留带解释性说明
                                                finance.STK_AUDIT_OPINION.opinion_type_id != 6,#6:未经审计，季报
                                                finance.STK_AUDIT_OPINION.end_date >= start_date,
                                                finance.STK_AUDIT_OPINION.pub_date <= end_date)
    df = finance.run_query(q)
    bad_companies = df['code'].unique().tolist()
    return [s for s in stock_list if s not in bad_companies]

#2.2 #获取红利列表
def bonus_filter(context,stock_list):
    #print(f'进入红利筛选前,共{len(stock_list)}只股票')
    year=context.previous_date.year
    start_date=datetime.date(year, 1, 1)
    end_date=context.previous_date
    #在指定月份开启超额因子
    if end_date.month in g.Expected_bonus:
        q = query(finance.STK_XR_XD.code,finance.STK_XR_XD.company_name, finance.STK_XR_XD.board_plan_pub_date,finance.STK_XR_XD.bonus_amount_rmb,finance.STK_XR_XD.bonus_ratio_rmb
            ).filter(               
                    #董事会预案发生在今年
                    finance.STK_XR_XD.board_plan_pub_date>start_date,
                    #董事会预案的发布日期小于等于前一日
                    finance.STK_XR_XD.board_plan_pub_date<=end_date,
                    #人民币分红大于0
                    finance.STK_XR_XD.bonus_ratio_rmb>0,
                    #在stock_list中
                    finance.STK_XR_XD.code.in_(stock_list))
        Expected_bonus_df = finance.run_query(q)
        
        if len(Expected_bonus_df)>0:
            bonus_list=Expected_bonus_df['code'].unique().tolist()
            price_df=history(1, unit='1d', field='close', security_list=bonus_list, df=True, skip_paused=False, fq='pre')
            price_df=price_df.T
            price_df.rename(columns={price_df.columns[0]:'Close_now'},inplace=True)
            price_df['code']=price_df.index
            Expected_bonus_df=pd.merge(Expected_bonus_df,price_df,on=('code'),how='left')
            Expected_bonus_df['bonus_ratio']=(Expected_bonus_df['bonus_ratio_rmb'])/Expected_bonus_df['Close_now']
            Expected_bonus_df=Expected_bonus_df.sort_values(by='bonus_ratio',ascending=True)
            bonus_list=Expected_bonus_df['code'].unique().tolist()
        else:
            bonus_list=[]
    else:
        #平日开启非年度分红的
        reprot_date = datetime.date(year-1, 12, 31)
        q = query(finance.STK_XR_XD.code,finance.STK_XR_XD.company_name,finance.STK_XR_XD.a_registration_date, finance.STK_XR_XD.bonus_amount_rmb,finance.STK_XR_XD.bonus_ratio_rmb
            ).filter(
                #年度分红
                finance.STK_XR_XD.report_date ==reprot_date,         
                finance.STK_XR_XD.bonus_type=='年度分红' ,
                #公布日期小于等于前一天
                finance.STK_XR_XD.board_plan_pub_date<=end_date,
                finance.STK_XR_XD.board_plan_bonusnote=='不分配不转增',
                finance.STK_XR_XD.code.in_(stock_list))
    
        no_year_bonus = finance.run_query(q)
        no_year_bonus_list=no_year_bonus['code'].unique().tolist()
        #排除今年不分红的股票
        bonus_list=[code for code in stock_list if code not in no_year_bonus_list]
        bonus_list=short_by_market_cap(context,bonus_list)
       
    log.debug(f'进行实际红利筛选后,原有{len(stock_list)}只股票，筛选后剩余{len(bonus_list)}只股票')
    
    if len(bonus_list)< g.stock_num:
        bonus_list.extend([x for x in stock_list if x not in bonus_list ][:g.stock_num-len(bonus_list)])
    return bonus_list



#3-4 买入模块
def buy_security(context,target_list,num):
    #调仓买入
    position_count = len(context.portfolio.positions)
    target_num = num
    if target_num !=0:
        value = context.portfolio.cash / target_num
        for stock in target_list:
            order_target_value(stock, value)
            log.info("买入[%s]（%s元）" % (stock,value))
            if len(context.portfolio.positions) == g.stock_num:
                break


#4-1 判断今天是否跳过月份
def today_is_between(context):
    # 根据g.pass_month跳过指定月份
    month = context.current_dt.month
    # 判断当前月份是否在指定月份范围内
    if month in g.pass_months:
        # code = '399303.XSHE'
        # close = history(count = 3, unit='1d', field='close', security_list= [code], df = False, skip_paused = False, fq = 'none')[code]
        # if close[-1] > close[-2] * 0.995 and close[-1] > close[-3] * 0.994:
        #     return True
        #判断当前日期是否在指定日期范围内
        return False
    else:
        return True

def close_account(context):
    if not g.trading_signal:
        curr_data = get_current_data()
        if len(g.hold_list) != 0 and g.hold_list != [g.money_etf]:
            for stock in g.hold_list:
                if stock == g.money_etf:
                    continue
                if curr_data[stock].last_price == curr_data[stock].low_limit or curr_data[stock].paused:
                    continue
                order_target_value(stock, 0)
                log.info("卖出[%s]" % (stock))

#5  公共模块
#5-1   根据市值排序
def short_by_market_cap(context,stock_list):
    short_q = query(
            valuation.code,
            valuation.market_cap,  # 总市值 circulating_market_cap/market_cap
        ).filter(
            valuation.code.in_(stock_list),
            valuation.day == context.previous_date,
        ).order_by(valuation.market_cap.asc())
    short_df=get_fundamentals(short_q)
    short_list=short_df['code'].unique().tolist()

    return  short_list

def print_position_info(context):
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
    print('———————————————————————————————————————分割线————————————————————————————————————————')
