# 克隆自聚宽文章：https://www.joinquant.com/post/27018
# 标题：【多因子选股模型框架】(单因子各项指标评分细则)
# 作者：酷安克L2

# 导入函数库
from jqdata import *
import numpy as np 
import pandas as pd 
from jqfactor import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

      # 开盘时运行
    run_monthly(market_open, -1,time='open', reference_security='000300.XSHG')
    
    # 购买股数
    g.num = 30

def market_open(context):
    log.info(context.current_dt)
    # 直接调用即可
    get_stocks_filtered()
    
    # 获取前一天因子数据
    q = query(
        valuation.code,
        income.operating_profit / income.operating_revenue, 
        indicator.roa,
        indicator.gross_profit_margin,
        income.net_profit,
        indicator.gross_profit_margin * income.operating_revenue / balance.total_assets,
        valuation.pb_ratio,
        valuation.ps_ratio,
        valuation.pe_ratio,
        valuation.turnover_ratio,
        ).filter(
            valuation.code.in_(g.stocklist)
            )
            
    df = get_fundamentals(q).set_index('code')
    df = clean_factor(context,df)
    
    score_select(context,df)
    rebalance(context)
    

def score_select(context,df):
    """
    打分选股函数:
    这里前四个因子是正相关,后五个是负相关
    """
    for i in range(len(df.columns)):
        # 前五个正向打分
        if i < 5 :
            df.iloc[:,i] = df.iloc[:,i].rank()
        # 后四个逆向打分
        else:
            df.iloc[:,i] = df.iloc[:,i].rank(ascending=False)

    g.buylist = list(df.sum(axis=1).sort_values(ascending=False)[:g.num].index)
    
def rebalance(context):
    """调仓函数,先卖后买"""
    # 卖出
    for stock in context.portfolio.positions.keys():
        if stock not in g.buylist:
            order_target_value(stock,0)
    
    # 买入
    cash = context.portfolio.total_value / len(g.buylist)
    for stock in g.buylist:
        order_target_value(stock,cash)
        

def get_stocks_filtered(indexID='000300.XSHG'):
    """
    获取筛选后的股票池
    """
    '''
    获取某一天筛选后的指数成份股
    :param tradedate: 指定某一天
    :param indexID:
    :return:
    '''
    stocklist = []
    # 获取当天指数成份股列表
    stock_index = get_index_stocks(indexID)
    # 判断当天是否是st,返回的是df
    for stock in stock_index:
        curr_dt = get_current_data()[stock]
        # 判断是否是st或者停牌
        if not (curr_dt.is_st or curr_dt.paused):
            stocklist.append(stock)
    
    g.stocklist = stocklist
            
    


def clean_factor(context,factors):
    """
    数据清洗函数
    """
    """
    缺失值,去极值,标准化,行业市值中性化
    """
    # 用列均值填充空值
    factors = factors.fillna(factors.mean())
    # 去极值
    factors = winsorize_med(factors, scale=10, inclusive=True, inf2nan=True, axis=0)
    # 标准化
    factors = standardlize(factors, inf2nan=True, axis=0)
    # 行业市值中性化
    factors = neutralize(factors,['sw_l1', 'market_cap'] ,date=context.current_dt.strftime('%Y-%m-%d'),axis=0)
    
    return factors
