# 克隆自聚宽文章：https://www.joinquant.com/post/34748
# 标题：【复现】FFScore财务模型
# 作者：Hugo2046

from typing import (List,Tuple,Dict,Callable,Union)

import datetime as dt
import numpy as np
import pandas as pd

from jqdata import *
from jqfactor import (calc_factors,Factor,winsorize_med,neutralize,standardlize)

enable_profile()  # 开启性能分析
# 初始化函数，设定基准等等

def initialize(context):

    set_backtest()
    set_params()
    set_variables()
    before_trading_start(context)
    run_monthly(trade,1, 'open', reference_security='000300.XSHG')

def set_params():
    
    # 用于打分的因子
    g.sel_fields = ['DELTA_ROE', 'ROA2', 'DELTA_MARGIN', 'DELTA_CATURN', 'DELTA_ROA2','DLTA_LIQUID']

def set_variables():
    
    pass

def set_backtest():
    '''回测所需设置'''

    set_option("avoid_future_data", True)  # 避免数据
    set_option("use_real_price", True)  # 真实价格交易
    set_option('order_volume_ratio', 1)  # 根据实际行情限制每个订单的成交量
    set_benchmark('000905.XSHG')  # 设置基准
    #log.set_level("order", "debuge")
    log.set_level('order', 'error')


# 每日盘前运行 设置不同区间手续费
def before_trading_start(context):

    # 手续费设置
    # 将滑点设置为0.002
    set_slippage(FixedSlippage(0.002))

    # 根据不同的时间段设置手续费
    c_dt = context.current_dt

    if c_dt > dt.datetime(2013, 1, 1):
        set_commission(PerTrade(buy_cost=0.0003, sell_cost=0.0013, min_cost=5))

    elif c_dt > dt.datetime(2011, 1, 1):
        set_commission(PerTrade(buy_cost=0.001, sell_cost=0.002, min_cost=5))

    elif c_dt > dt.datetime(2009, 1, 1):
        set_commission(PerTrade(buy_cost=0.002, sell_cost=0.003, min_cost=5))

    else:
        set_commission(PerTrade(buy_cost=0.003, sell_cost=0.004, min_cost=5))
        
'''股票池过滤'''

# 筛选股票池
class Filter_Stocks(object):
    '''
    获取某日的成分股股票
    1. 过滤st
    2. 过滤上市不足N个月
    3. 过滤当月交易不超过N日的股票
    ---------------
    输入参数：
        index_symbol:指数代码,A等于全市场,
        watch_date:日期
    '''
    
    def __init__(self,symbol:str,watch_date:str)->None:
        
        if isinstance(watch_date,str):
            
            self.watch_date = pd.to_datetime(watch_date).date()
            
        else:
            
            self.watch_date = watch_date
            
        self.symbol = symbol
        self.get_index_component_stocks()
        
    def get_index_component_stocks(self)->list:
        
        '''获取指数成分股'''
        
        if self.symbol == 'A':
            
            wd:pd.DataFrame = get_all_securities(types=['stock'],date=self.watch_date)
            self.securities:List = wd.query('end_date != "2200-01-01"').index.tolist()
        else:
            
            self.securities:List = get_index_stocks(self.symbol,self.watch_date)
    
    def filter_paused(self,paused_N:int=1,threshold:int=None)->list:
        
        '''过滤停牌股
        -----
        输入:
            paused_N:默认为1即查询当日不停牌
            threshold:在过paused_N日内停牌数量小于threshold
        '''
        
        if (threshold is not None) and (threshold > paused_N):
            raise ValueError(f'参数threshold天数不能大于paused_N天数')
            
        
        paused = get_price(self.securities,end_date=self.watch_date,count=paused_N,fields='paused',panel=False)
        paused = paused.pivot(index='time',columns='code')['paused']
        
        # 如果threhold不为None 获取过去paused_N内停牌数少于threshodl天数的股票
        if threshold:
            
            sum_paused_day = paused.sum()
            self.securities = sum_paused_day[sum_paused_day < threshold].index.tolist()
        
        else:
            
            paused_ser = paused.iloc[-1]
            self.securities = paused_ser[paused_ser == 0].index.tolist()
    
    def filter_st(self)->list:
        
        '''过滤ST'''
              
        extras_ser = get_extras('is_st',self.securities,end_date=self.watch_date,count=1).iloc[-1]
        
        self.securities = extras_ser[extras_ser == False].index.tolist()
    
    def filter_ipodate(self,threshold:int=180)->list:
        
        '''
        过滤上市天数不足以threshold天的股票
        -----
        输入：
            threhold:默认为180日
        '''
        
        def _check_ipodate(code:str,watch_date:dt.date)->bool:
            
            code_info = get_security_info(code)
            
            if (code_info is not None) and ((watch_date - code_info.start_date).days > threshold):
                
                return True
            
            else:
                
                return False

        self.securities = [code for code in self.securities if _check_ipodate(code,self.watch_date)]
    
    def filter_industry(self,industry:Union[List,str],level:str='sw_l1',method:str='industry_name')->list:
        '''过略行业'''
        ind = get_stock_ind(self.securities,self.watch_date,level,method)
        target = ind.to_frame('industry').query('industry != @industry')
        self.securities = target.index.tolist()
        
def get_stock_ind(securities:list,watch_date:str,level:str='sw_l1',method:str='industry_code')->pd.Series:
    
    '''
    获取行业
    --------
        securities:股票列表
        watch_date:查询日期
        level:查询股票所属行业级别
        method:返回行业名称or代码
    '''
    
    indusrty_dict = get_industry(securities, watch_date)

    indusrty_ser = pd.Series({k: v.get(level, {method: np.nan})[
                             method] for k, v in indusrty_dict.items()})
    
    indusrty_ser.name = method.upper()
    
    return indusrty_ser
    
# 标记得分
def sign(ser: pd.Series) -> pd.Series:
    '''标记分数,正数为1,负数为0'''
    
    return ser.apply(lambda x: np.where(x > 0, 1, 0))
    
    
# 涉及到的13个财务指标获取
class F13_Score(Factor):
    
    '''获取FScore及FFScore中提到的因子'''
    name = 'F13_Score'
    max_window = 1
    watch_date = None
    
    dependencies = ['roa', 'roa_4', 'net_operate_cash_flow', 'total_assets',
        'total_assets_1', 'total_assets_4', 'total_assets_5',
        'operating_revenue', 'operating_revenue_4','pb_ratio',
        'total_current_assets','total_current_assets_1','total_current_assets_4','total_current_assets_5',
        'total_non_current_assets', 'total_non_current_liability',
        'total_non_current_assets_4', 'total_non_current_liability_4',
        'total_current_assets', 'total_current_liability',
        'total_current_assets_4', 'total_current_liability_4',
        'gross_profit_margin', 'gross_profit_margin_4', 'paidin_capital',
        'paidin_capital_4','roe', 'roe_4','total_profit','total_profit_4','financial_expense','financial_expense_4']
    
    def calc(self,data:dict)->None:
        
        roe: pd.DataFrame = data['roe']
        
        roa1: pd.DataFrame = data['roa'] # 单位为百分号
        
        # 息税前利润（EBIT）除以资产总值
        # 利息支出项大多数情况时缺失的所以这里用财务费用代替
        roa2 = data['total_profit'] + data['financial_expense'] / (
            data['total_current_assets'] +
            data['total_current_assets_1']).mean()
        
        roa2_4 = data['total_profit_4'] + data['financial_expense_4'] / (
            data['total_current_assets_4'] +
            data['total_current_assets_5']).mean()
        
        delta_roa2 = roa2 / roa2_4 - 1
        
        cfo: pd.DataFrame = data['net_operate_cash_flow'] / \
            data['total_assets']

        delta_roa1: pd.DataFrame = roa1 / data['roa_4'] - 1
        
        delta_roe: pd.DataFrame = roe / data['roe_4'] - 1
            
        accrual: pd.DataFrame = cfo - roa1 * 0.01

        # 杠杆变化
        ## 变化为负数时为1，否则为0 取相反
        leveler: pd.DataFrame = data['total_non_current_liability'] / \
            data['total_non_current_assets']

        leveler1: pd.DataFrame = data['total_non_current_liability_4'] / \
            data['total_non_current_assets_4']

        delta_leveler: pd.DataFrame = -(leveler / leveler1 - 1)

        # 流动性变化
        liquid: pd.DataFrame = data['total_current_assets'] / \
            data['total_current_liability']

        liquid_1: pd.DataFrame = data['total_current_assets_4'] / \
            data['total_current_liability_4']

        delta_liquid: pd.DataFrame = liquid / liquid_1 - 1

        # 毛利率变化
        delta_margin: pd.DataFrame = data['gross_profit_margin'] / \
            data['gross_profit_margin_4'] - 1

        # 是否发行普通股权
        eq_offser: pd.DataFrame = data['paidin_capital'] / data[
            'paidin_capital_4'] - 1
        
        # 流动资产周转率
        caturn_1 = data['operating_revenue'] / (
            data['total_current_assets'] +
            data['total_current_assets_1']).mean()
        caturn_2 = data['operating_revenue_4'] / (
            data['total_current_assets_4'] +
            data['total_current_assets_5']).mean()
        
        # 流动资产周转率同比
        delata_caturn = caturn_1 / caturn_2 - 1
        
        # 总资产周转率
        total_asset_turnover_rate: pd.DataFrame = data[
            'operating_revenue'] / (data['total_assets'] +
                                          data['total_assets_1']).mean()

        total_asset_turnover_rate_1: pd.DataFrame = data[
            'operating_revenue_4'] / (data['total_assets_4'] +
                                            data['total_assets_5']).mean()

        # 总资产周转率同比
        delta_turn: pd.DataFrame = total_asset_turnover_rate / \
            total_asset_turnover_rate_1 - 1
        
        indicator_tuple: Tuple = (roe, delta_roe,roa1,delta_roa1,roa2,delta_roa2, accrual, delta_leveler,
                                  delta_liquid, delta_margin,eq_offser,delata_caturn, delta_turn,data['pb_ratio'])

        # 储存计算FFscore所需原始数据
        self.basic: pd.DataFrame = pd.concat(indicator_tuple).T.replace([-np.inf,np.inf],np.nan)

        self.basic.columns = [
            'ROE', 'DELTA_ROE','ROA1','DELTA_ROA1','ROA2','DELTA_ROA2','ACCRUAL', 'DELTA_LEVER', 
            'DLTA_LIQUID', 'DELTA_MARGIN', 'EQ_OFFSER', 'DELTA_CATURN', 'DELTA_TURN','PB_RATIO']
            
        return sign(self.basic[g.sel_fields]).sum(axis=1)
        
def prepare_pb_ratio(pb_df:pd.DataFrame,watch_date:dt.date)->pd.Series:
    '''对pb预处理'''
    
    pb_ser = pb_df.set_index('code')['pb_ratio']
    
    return (pb_ser.pipe(winsorize_med)
                  .pipe(standardlize)
                  .pipe(neutralize,how='sw_l1',date=watch_date))
        
def trade(context):
    
    bar_time = context.previous_date
    
    # 获取股票池
    stock_pool_func = Filter_Stocks('A', bar_time)
    stock_pool_func.filter_paused(22, 21)  # 过滤22日停牌超过21日的股票
    stock_pool_func.filter_st()  # 过滤st
    stock_pool_func.filter_ipodate(180)  # 过滤次新
    stock_pool_func.filter_industry(['金融服务I','非银金融I'])

    securities = stock_pool_func.securities  # 股票池
    
    # 财务因子
    f:Dict = calc_factors(securities,[F13_Score()],start_date=bar_time,end_date=bar_time)
    f:pd.Series = f['F13_Score'].iloc[-1].sort_values(ascending=False)
    
    # 高分组合
    score:List = f[f > 4].index.tolist()[:200]
   
    # pb因子
    pb:pd.DataFrame = get_valuation(securities,
                        end_date=bar_time,
                        fields=['pb_ratio'],
                        count=1)
    
    # 过滤负值
    pb = pb.query('pb_ratio > 0')
    pb:pd.Series = prepare_pb_ratio(pb,bar_time)
    
    t: float = pb.quantile(0.2)  # 20%分位数
  
    low_pb: List = pb[pb <= t].sort_values().index.tolist()[:200]
    
    target: List = list(set(score).intersection(low_pb))
    
    
    for hold in context.portfolio.long_positions:
        
        if hold not in target:
            
            order_target(hold,0)
    
    everStock = context.portfolio.total_value / len(target)
    
    for b in target:
        
        order_target_value(b,everStock)
                    
    record(持仓=len(context.portfolio.long_positions),目标=len(target))
    
    
