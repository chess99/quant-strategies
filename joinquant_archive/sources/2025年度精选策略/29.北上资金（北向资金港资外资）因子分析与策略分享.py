# 克隆自聚宽文章：https://www.joinquant.com/post/25613
# 标题：北上资金（北向资金/港资/外资）因子分析与策略分享
# 作者：cgzol

import talib
import pandas as pd
import numpy as np
import math
import jqdata
import urllib2
import re
import time,datetime
from jqdata import *
from jqfactor import neutralize
from prettytable import PrettyTable
from jqdata import finance
from jqfactor import get_factor_values
import warnings
#导入需要的数据库
from jqfactor import get_factor_values
from jqdata import finance


def initialize(context):
    disable_cache()
    warnings.filterwarnings("ignore")
    set_commission(PerTrade(buy_cost=0.00025, sell_cost=0.001, min_cost=5))
    set_slippage(FixedSlippage(0))
    set_option('use_real_price', True)
    g.index = '000300.XSHG'#沪深300指数
    set_benchmark(g.index)
    log.set_level('order', 'info')
    log.set_level('history', 'error')
    g.buy_stock_count = 10
    g.day_count = 0
    g.trade_hour = 10
    g.trade_minute = 00

def handle_data(context, data):
    g.pre_date =context.previous_date
    hour = context.current_dt.hour
    minute = context.current_dt.minute
    buy_stocks = []
    if (hour == g.trade_hour) and (minute == g.trade_minute):
        buy_stocks = select_stocks(context,data)
        print('需持有的股票：\n')
        for stock in buy_stocks:
            print(show_stock(stock))
        if len(context.portfolio.positions)>0:
            print('卖出股票：')
            last_prices = history(1, '1m', 'close', security_list=context.portfolio.positions.keys())
            curr_data = get_current_data()
            for stock in context.portfolio.positions.keys():
                if stock not in buy_stocks and last_prices[stock][-1] < curr_data[stock].high_limit:
                    order_target_value(stock, 0)
                    print('卖出股票：',stock)
        print('买入股票：')
        for stock in buy_stocks:
            position_count = len(context.portfolio.positions)
            if g.buy_stock_count > position_count:
                value = context.portfolio.cash / (g.buy_stock_count - position_count)
                if context.portfolio.positions[stock].total_amount == 0:
                    order_target_value(stock, value)
                    print('买入股票：',stock)
        print get_portfolio_info_text(context,buy_stocks)
        g.day_count += 1
        print '计数日：',g.day_count
        
def get_all_stocks():
    stock_list = get_index_stocks(g.index) # 指数成分股
    return stock_list
        
def filter_paused_and_st_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused 
    and not current_data[stock].is_st and 'ST' not in current_data[stock].
    name and '*' not in current_data[stock].name and '退' not in current_data[stock].name]
    
def filter_gem_stock(context, stock_list):
    #过滤创业板股票
    return [stock for stock in stock_list  if stock[0:3] != '300']
    
def filter_inno_stock(security_list) :
    #过滤科创板股票
    return [stock for stock in security_list if stock[0:3] != '688' and stock[0:3] != '787']
    # 返回结果
    
def filter_new_stock(context, stock_list):
    tmpList = []
    for stock in stock_list :
        days_public=(context.current_dt.date() - get_security_info(stock).start_date).days
        # 上市未超过1年
        if days_public > 365 :
            tmpList.append(stock)
    return tmpList

def filter_limit_stock(context, data, stock_list):
    tmpList = []
    curr_data = get_current_data()
    for stock in stock_list:
        # 未涨停，也未跌停
        if curr_data[stock].low_limit < data[stock].close < curr_data[stock].high_limit:
            tmpList.append(stock)
    return tmpList

#获取北向资金持股市值数据
def get_factor_data(stocklist,date):
    df_HK_HOLD = finance.run_query(query(finance.STK_HK_HOLD_INFO.code,finance.STK_HK_HOLD_INFO.share_number).filter(finance.STK_HK_HOLD_INFO.code.in_(stocklist),finance.STK_HK_HOLD_INFO.day == date)).T
    if df_HK_HOLD.empty:
        return pd.DataFrame(columns=[])
    else:
        df_HK_HOLD.columns = df_HK_HOLD.loc['code'].values
        df_HK_HOLD.drop(axis=0,labels=['code'],inplace=True)
        df_HK_HOLD.index = [date]
        df_close_price = get_price(stocklist,end_date=date, frequency='daily', count = 1,fields=['close'], skip_paused=False, fq='pre', panel=True)['close']
        factor_data=df_HK_HOLD * df_close_price #持股数量与收盘股价相乘得出北向资金持股市值
        return factor_data

def select_stocks(context,data):
    '''
    if get_growth_rate(g.index,10) < 0.01:
        print('沪深300指数近10日涨幅小于1%，空仓')
        stock_list = []
        return stock_list
    elif get_growth_rate(g.index,10) >= 0.01:
        print('沪深300指数近10日涨幅大于等于1%，开仓')
    '''
    stock_list = get_all_stocks()
    # 过滤掉停牌的和ST的
    stock_list = filter_paused_and_st_stock(stock_list)
    '''
    #过滤掉创业板
    stock_list = filter_gem_stock(context, stock_list)
    #过滤掉科创板
    stock_list = filter_inno_stock(stock_list)
    # 过滤掉上市超过1年的
    '''
    stock_list = filter_new_stock(context, stock_list)
    # 过滤掉现在涨停或者跌停的
    stock_list = filter_limit_stock(context, data, stock_list)
    factor_data = get_factor_data(stock_list,context.previous_date)
    if factor_data.empty :
        return context.portfolio.positions.keys()
    else:
        stock_list = factor_data.T.sort_index(by = context.previous_date).index.values.tolist()[-g.buy_stock_count:]  
        return stock_list




# 策略看10天涨幅
def get_growth_rate(security, n = 10):
    lc = get_close_price(security, n)
    #c = data[security].close
    c = get_close_price(security, 1, '1m')

    if not isnan(lc) and not isnan(c) and lc != 0:
        return (c - lc) / lc
    else:
        log.error("数据非法, security: %s, %d日收盘价: %f, 当前价: %f" %(security, n, lc, c))
        return 0
        
# 获取前n个单位时间当时的收盘价
def get_close_price(security, n, unit='1d'):
    return attribute_history(security, n, unit, ('close'), True)['close'][0]

def shifttradingday(date,shift):
    #获取N天前的交易日日期
    # 获取所有的交易日，返回一个包含所有交易日的 list,元素值为 datetime.date 类型.
    tradingday = get_all_trade_days()
    print tradingday
    # 得到date之后shift天那一天在列表中的行标号 返回一个数
    shiftday_index = list(tradingday).index(date)+shift
    print shiftday_index
    # 根据行号返回该日日期 为datetime.date类型
    return tradingday[shiftday_index]

def show_stock(stock):
    '''
    获取股票代码的显示信息    
    :param stock: 股票代码，例如: '603822.SH'
    :return: str，例如：'603822 嘉澳环保'
    '''
    return u"%s %s" % (stock[:6], get_security_info(stock).display_name)
    
def get_portfolio_info_text(context,new_stocks,op_sfs=[0]):
    # new_stocks是需要持仓的股票列表
    sub_str = ''
    table = PrettyTable(["仓号","股票", "持仓", "当前价", "盈亏率","持仓比"])  
    for sf_id in range(len(context.subportfolios)):
        cash = context.subportfolios[sf_id].cash
        p_value = context.subportfolios[sf_id].positions_value
        total_values = p_value +cash
        if sf_id in op_sfs:
            sf_id_str = str(sf_id) + ' *'
        else:
            sf_id_str = str(sf_id)
        for stock in context.subportfolios[sf_id].long_positions.keys():
            position = context.subportfolios[sf_id].long_positions[stock]
            if sf_id in op_sfs and stock in new_stocks:
                stock_str = show_stock(stock) + ' *'
            else:
                stock_str = show_stock(stock)
            stock_raite = (position.total_amount * position.price) / total_values * 100
            table.add_row([sf_id_str,
                stock_str,
                position.total_amount,
                position.price,
                "%.2f%%"%((position.price - position.avg_cost) / position.avg_cost * 100), 
                "%.2f%%"%(stock_raite)]
                )
        if sf_id < len(context.subportfolios) - 1:
            table.add_row(['----','---------------','-----','----','-----','-----'])
        sub_str += '[仓号: %d] [总值:%d] [持股数:%d] [仓位:%.2f%%] \n'%(sf_id,
            total_values,
            len(context.subportfolios[sf_id].long_positions)
            ,p_value*100/(cash+p_value))
    print '子仓详情:\n' + sub_str + str(table)
