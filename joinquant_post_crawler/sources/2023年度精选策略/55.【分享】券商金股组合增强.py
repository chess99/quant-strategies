# 克隆自聚宽文章：https://www.joinquant.com/post/33881
# 标题：【分享】券商金股组合增强
# 作者：Hugo2046

'''
Author: Hugo
Date: 2021-05-19 10:38:22
LastEditTime: 2021-06-24 14:45:25
LastEditors: Hugo
Description: 券商金股策略

每月初（第2个交易日）获取券商的金股数据（此部分数据来源于手动整理的文件gold_stock_20210609.csv）其数据结构
见read_gold_stock；
每周使用动量因子对月初获取的金股进行筛选，获取得分前N的股票(g.handle_num进行控制)；
'''

from jqdata import *
from jqfactor import (Factor,calc_factors)
# 聚宽的组合优化
from jqlib.optimizer import (portfolio_optimizer,
                             MaxProfit,
                             MaxSharpeRatio,
                             RiskParity,
                             MinVariance,
                             WeightConstraint, Bound)

import functools
from dateutil.parser import parse

from scipy import stats
from scipy import optimize
import statsmodels.api as sm
from sklearn.covariance import ledoit_wolf

import numpy as np
import pandas as pd
import datetime as dt
from typing import (List, Tuple, Union,Callable)
from six import BytesIO  # 文件读取


def initialize(context):

    set_params()
    set_variables()
    set_backtest()
    g.in_week = 5  # 周内第五个交易日

    # 每月的第五个交易日调仓
    run_monthly(get_target_securities, 2, 'open',
                reference_security='000300.XSHG')
    run_weekly(trade_func, g.in_week, 'open', reference_security='000300.XSHG')

# 配置基础参数


def set_params():

    # 是否使用因子进行辅助
    # 为True使用动量因子,False使用券商推荐率
    g.use_factor = True

    # 设置持仓
    g.handle_num = 15

    # 获取金股数据
    read_gold_stock()
    
    # 是否组合优化
    # 可选项:MaxSharpeRatio，MaxProfit,MinVariance,RiskParity
    # False为不组合优化
    g.optimizer_mod = 'MaxProfit'  # 'MaxSharpeRatio'

# 基础变量


def set_variables():

    g.base_target: pd.DataFrame = None  # 储存当月金股

# 回测设置


def set_backtest():

    set_option("avoid_future_data", True)  # 避免数据
    set_option("use_real_price", True)  # 真实价格交易
    set_option('order_volume_ratio', 1)  # 根据实际行情限制每个订单的成交量
    set_benchmark('000300.XSHG')  # 设置基准
    #log.set_level("order", "debuge")
    log.set_level('order', 'error')


# 每日盘前运行 设置不同区间手续费
def before_trading_start(context):

    # 手续费设置
    # 将滑点设置为0.002
    set_slippage(FixedSlippage(0.002))

    # 根据不同的时间段设置手续费
    dt = context.current_dt

    if dt > datetime.datetime(2013, 1, 1):
        set_commission(PerTrade(buy_cost=0.0003, sell_cost=0.0013, min_cost=5))

    elif dt > datetime.datetime(2011, 1, 1):
        set_commission(PerTrade(buy_cost=0.001, sell_cost=0.002, min_cost=5))

    elif dt > datetime.datetime(2009, 1, 1):
        set_commission(PerTrade(buy_cost=0.002, sell_cost=0.003, min_cost=5))

    else:
        set_commission(PerTrade(buy_cost=0.003, sell_cost=0.004, min_cost=5))


'''读取金股的储存文件'''


def read_gold_stock() -> None:

    # 读取储存金股的文件 起始日期2019年7月
    '''
    文件结构：
        ----------------------------------------------
        |所属日期|推荐机构|股票名称|所属行业|股票代码 |
        ----------------------------------------------
        |2019/7/1|安信证券|科大讯飞|  计算机|002230.SZ|
        -----------------------------------------------
    '''
    g.gold_stock_frame = pd.read_csv(BytesIO(read_file('gold_stock_20210609.csv')),
                                     index_col='所属日期', parse_dates=['所属日期'])

    # 过滤港股
    g.gold_stock_frame = g.gold_stock_frame[(
        g.gold_stock_frame['股票代码'].str[-2:] != 'HK')]
    # 股票代码转为聚宽的代码格式
    g.gold_stock_frame['股票代码'] = g.gold_stock_frame['股票代码'].apply(
        normalize_code)
    # 将索引转为年-月形式
    g.gold_stock_frame.index = g.gold_stock_frame.index.strftime('%Y-%m')


'''其他'''

@functools.lru_cache()
def get_weekofyear_date() -> pd.DataFrame:
    '''
    获取 周度交易日期
    ------
        return index=date columns date num_week:周度中的第N个交易日
    '''
    idx = get_all_trade_days()
    days = pd.DataFrame(idx, index=pd.DatetimeIndex(idx), columns=['date'])
    days['num_week'] = days.groupby([
        days.index.year, days.index.weekofyear
    ])['date'].transform(lambda x: range(1,
                                         len(x) + 1))

    return days

def get_num_weekly_trade_days(days: pd.DataFrame, N: int) -> pd.Series:
    '''
    获取周度的第N个交易日
    ------
    输入参数:
        days:index=date columns date num_week
        N:第N个交易日
    ------
    return pd.DataFrame
           index-datetime.datetime columns-datetime.date
    '''

    cond = days.groupby([days.index.year, days.index.weekofyear
                         ])['num_week'].apply(lambda x: x == min(len(x), N))
    target = days[cond]

    return target.drop(columns=['num_week'])
    
def get_past_weekly_days(watch_date: str, weekly_n: int, count: int) -> list:
    '''
    查询过去N期的周度节点日期
    ------
    输入参数:
        watch_date:观察期
        weekly_n:周内第N个交易日
        count:获取前N期
    -----
        return list-datetime.date
    '''

    if isinstance(watch_date, str):
        watch_date = parse(watch_date)

    days = get_weekofyear_date()
    weekly = get_num_weekly_trade_days(days.loc[:watch_date], weekly_n)

    return weekly['date'].iloc[-count - 1:].values.tolist()
    
def get_next_returns(factor_df: pd.DataFrame,
                     last_date: str = None) -> pd.DataFrame:
    '''
    获取下期收益率
    ------
    输入:
        factor_df:MuliIndex-level0-datetime.date level1-code columns - factors
        last_date:最后一期时间
    '''
    if last_date:
        days = pd.to_datetime(
            factor_df.index.get_level_values('date').unique().tolist() +
            [last_date])
    else:
        days = pd.to_datetime(
            factor_df.index.get_level_values('date').unique().tolist())

    dic = {}
    for s, e in zip(days[:-1], days[1:]):

        stocks = factor_df.loc[s.date()].index.get_level_values(
            'code').unique().tolist()

        a = get_price(stocks, end_date=s, count=1, fields='close',
                      panel=False).set_index('code')['close']

        b = get_price(stocks, end_date=e, count=1, fields='close',
                      panel=False).set_index('code')['close']

        dic[s] = b / a - 1

    df = pd.concat(dic).to_frame('next_ret')

    df.index.names = ['date', 'code']
    return df
    
def prepare_data(securities: list, watch_date: str, N: int,
                 count: int) -> Tuple[pd.DataFrame, pd.DataFrame]:
    '''
    获取当期股票池 过去N期的因子值及未来期收益率
    T期没有未来期收益,仅T-1至T-N期有
    ------
    输入参数:
        securities:股票列表
        watch_date:观察期
        N:周度交易日
        count:过去N期
    ------
    return 
        factor_df, next_ret
    '''

    periods = get_past_weekly_days(watch_date, N, count)

    f_dict = {}

    for trade in periods:

        f_dict[trade] = get_momentum_factor(securities, trade)

    f_df = pd.concat(f_dict, names=['date', 'code'])

    next_ret = get_next_returns(f_df)

    return f_df, next_ret


def composition_factors(securities:list,watchDt:str,in_week: int,window: int) -> pd.DataFrame:
    '''
    获取回测范围内的因子合成值
    ------
    输入参数
        securities:金股数据表
        in_week:每周的最后一日进行调仓
        num_trade:每月的第N个交易日获取到金股并交易
        window:回看窗口期为12周
    
    '''
   
    # 获取T至T-N期因子值
    f_df, next_ret = prepare_data(securities, watchDt, in_week, window)

    # 调用因子合成类
    fw = FactorWeight(f_df, next_ret)

    # 获取不同因子合成的值
    method_dic = {
        '等权法': fw.fac_eqwt(),
        '历史因子收益率加权法': fw.fac_ret_half(False),
        '历史因子收益率半衰加权法': fw.fac_ret_half(True),
        '历史因子IC加权法': fw.fac_ic_half(2),
        '最大化IC_IR加权法': fw.fac_maxicir_samp(),
        '最大化 IC_IR 加权法(Ledoit)': fw.fac_maxicir(),
        '最大化IC_IR加权法': fw.fac_maxic()
    }

    df = pd.concat((ser for ser in method_dic.values()), axis=1)
    df.columns = list(method_dic.keys())

    
    return df
    
def time2str(watch_date: dt.datetime, fmt='%Y-%m-%d') -> str:
    '''日期转文本'''
    if isinstance(watch_date, (dt.datetime, dt.date)):
        return watch_date.strftime(fmt)
    else:
        return time2str(parse(watch_date))



'''金股筛选指标'''

# 计算券商推荐率


def get_net_promoter_score(target_df: pd.DataFrame) -> pd.Series:
    '''计算券商推荐率'''

    return target_df.groupby('股票代码')['推荐机构'].count() / len(target_df['推荐机构'].unique())


'''因子构造'''

# 因子合成方法
class FactorWeight(object):
    '''
    参考:《20190104-华泰证券-因子合成方法实证分析》
    -------------
    传入T期因子及收益数据 使用T-1至T-N期数据计算因子的合成权重
    
    现有方法：
    1. fac_eqwt 等权法
    2. fac_ret_half 历史因子收益率（半衰）加权法
    3. fac_ic_half 历史因子 IC（半衰）加权法
    4. fac_maxicir_samp 最大化 IC_IR 加权法 样本协方差
       fac_maxicir  Ledoit压缩估计方法计算协方差
    5. fac_maxic 最大化IC加权法 Ledoit压缩估计方法计算协方差
    ------
    输入参数:
        factor:MuliIndex level0为date,level1为code,columns为因子值
            -----------------------------------
                date    |    asset   |
            -----------------------------------
                        |   AAPL     |   0.5
                        -----------------------
                        |   BA       |  -1.1
                        -----------------------
            2014-01-01  |   CMG      |   1.7
                        -----------------------
                        |   DAL      |  -0.1
                        -----------------------
                        |   LULU     |   2.7
                        -----------------------

        next_returns：下期收益率,结构与factor相同
    '''
    def __init__(self, factor: pd.DataFrame,
                 next_returns: pd.DataFrame) -> None:

        self.factor, self.next_returns = factor.align(next_returns,
                                                      join='left',
                                                      axis=0)

        # 数据格式整理
        self.factor.index.names = ['date', 'code']
        self.next_returns.index.names = ['date', 'code']

        self._split_data()  # 拆分数据
        self.IC = self._calc_ic(self.past_factor,
                                self.past_returns)  # 计算Rank IC

    def _split_data(self) -> None:
        '''
        将原有数据拆分为当期(T期)与前序T-1至T-N期
        '''

        self.last_day = self.factor.index.get_level_values(
            'date').max()  # 获取当期日期
        self.last_factor = self.factor.loc[self.last_day]  # 获取当期因子

        # 前期数据
        self.past_factor = (
            self.factor.unstack().sort_index().iloc[:-1].stack())

        self.past_returns = (
            self.next_returns.unstack().sort_index().iloc[:-1].stack())

        self.past_returns.name = 'next_ret'

    def fac_eqwt(self) -> pd.Series:
        '''等权合成'''

        return self.last_factor.mean(axis=1)

    def fac_ret_half(self, halflife: bool = True) -> pd.Series:
        '''
        历史因子收益率(半衰)加权法

        最近一段时期内历史因子收益率的算术平均值（或半衰权重下的加权平均值）作为权重进行相加
        如果这六个因子的历史因子收益率均值分别是 1、2、3、4、5、6，则每个因子的权重分别为：
        1/（1+2+3+4+5+6）= 1/21、2/（1+2+3+4+5+6）= 2/21、3/21、4/21、5/21、
        6/21，即为 4.76%、9.52%、14.29%、19.05%、23.81%、28.57%
        ---------
            halflife:默认为True使用半衰期加权,False为等权 
        '''

        # 获取因子收益率
        factor_returns = self._get_factor_return(self.past_factor,
                                                 self.past_returns)

        ret_mean = factor_returns.mean()

        # 使用半衰期
        if halflife:

            self.weight = ret_mean / ret_mean.sum()

        else:
            # 未使用半衰期
            self.weight = ret_mean

        # 因子合成
        return (self.last_factor.mul(self.weight).sum(axis=1))

    def fac_ic_half(self, halflife: int = None) -> pd.Series:
        '''
        历史因子 IC（半衰）加权法

        按照最近一段时期内历史RankIC的算术平均值（或半衰权重下的加权平均值）作为权重进行相加，
        得到新的合成后因子
        ------
        输入参数:
            halflife:半衰期,1,2,4等 通常使用2
        '''

        if halflife:

            # 构造半衰期
            ic_weight = self._build_halflife_wight(self.IC.shape[0], halflife)

            self.weight = self.IC.apply(
                lambda x: np.average(x, weights=ic_weight))

            return (self.last_factor.mul(self.weight).sum(axis=1))

        else:

            self.weight = self.IC.mean()

            return (self.last_factor.mul(self.weight).sum(axis=1))

    def fac_maxicir_samp(self,
                         explicit_solutions: bool = False,
                         fill_Neg: str = 'normal') -> pd.Series:
        '''
        最大化 IC_IR 加权法

        以历史一段时间的复合因子平均IC值作为对复合因子下一期IC值的估计，
        以历史 IC 值的协方差矩阵作为对复合因子下一期波动率的估计
        ------
        输入参数：
            explicit_solutions 为True时使用显示解,False使用约束解
            fill_Neg:当使用显示解时对小于0部分的处理
                     normal:使用0填充
                     mean:使用IC均值填充
        '''

        # 显示解
        if explicit_solutions:

            self.weight = self._explicit_solutions_icir(self.IC, fill_Neg)

        else:

            # 约束解
            self.weight = self._opt_icir(self.IC, fill_Neg,
                                         self._target_func_samp)

        return (self.last_factor.mul(self.weight).sum(axis=1))

    def fac_maxicir(self, fill_Neg: str = 'normal') -> pd.Series:

        # 约束解
        self.weight = self._opt_icir(self.IC, fill_Neg, self._target_func)

        return (self.last_factor.mul(self.weight).sum(axis=1))

    def fac_maxic(self) -> pd.Series:
        '''
        最大化 IC 加权法
        
        $max IC = \frac{w.T * IC}{\sqrt{w.T * V *w}}
        
        𝑉是当前截面期因子值的相关系数矩阵(由于因子均进行过标准化,自身方差为1,因此相关系数矩阵亦是协方差阵)
        协方差使用压缩协方差矩阵估计方式
        
        使用约束解
        '''

        z_score = (self.past_factor.fillna(0) -
                   self.past_factor.mean()) / self.past_factor.std()

        V = ledoit_wolf(z_score)[0]
        mean_ic = self.IC.mean()

        size = len(mean_ic)
        np.random.seed(42)

        # s.t w >= 0
        bounds = tuple((0, None) for _ in range(size))

        res = optimize.minimize(
            fun=lambda w: -np.divide(w.T @ mean_ic, np.sqrt(w @ V @ w.T)),
            x0=np.random.randn(size),
            bounds=bounds)

        if res['success']:

            self.weight = pd.Series(res['x'], index=mean_ic.index.tolist())

        else:

            logging.warning('优化失败')

        return (self.last_factor.mul(self.weight).sum(axis=1))

    @staticmethod
    def _calc_ic(factor: pd.DataFrame, next_ret: pd.Series) -> pd.Series:
        '''计算Rank IC'''
        def scr_ic(group: pd.DataFrame) -> pd.DataFrame:

            f_cols = [col for col in group.columns if col != 'next_ret']

            return pd.Series({
                col: stats.spearmanr(group[col], group['next_ret'])[0]
                for col in f_cols
            })

        df = pd.concat((factor, next_ret), axis=1)

        return df.fillna(0).groupby(level='date').apply(scr_ic)

    @staticmethod
    def _build_halflife_wight(T: int, H: int) -> np.array:
        '''
        生成半衰期权重

        $w_t = 2^{\frac{t-T-1}{H}}(t=1,2,...,T)$
        实际需要归一化,w^{'}_{t}=\frac{w_t}{\sumw_t}
        ------

        输入参数:
            T:期数
            H:半衰期参数
        '''

        periods = np.arange(1, T + 1)

        return np.power(2, np.divide(periods - T - 1, H)) * 0.5

    @staticmethod
    def _get_factor_return(factor: pd.DataFrame,
                           next_returns: pd.Series) -> pd.DataFrame:
        '''
        获取因子收益
        '''

        df = pd.concat((factor, next_returns), axis=1).fillna(0)
        f_col = [col for col in df.columns if col != 'next_ret']

        def ols(endog: pd.Series, exog: pd.DataFrame) -> pd.DataFrame:
            '''使用wls回归获取因子收益'''

            X = sm.add_constant(exog)
            model = sm.OLS(endog, X)
            results = model.fit()

            return results.params

        factor_ret = df.groupby(
            level='date').apply(lambda x: ols(x['next_ret'], x[f_col]))

        return factor_ret.drop(columns='const')

    @staticmethod
    def _explicit_solutions_icir(ic: pd.DataFrame, fill_Neg: str) -> pd.Series:
        '''
        计算ic ir的显示解
        ------
        输入参数:
            ic:过去一段时间的ic数据
            window:计算ic均值的滚动期

        '''
        mean_ic = ic.mean()
        std_ic = ic.std()

        ic_ir = mean_ic / std_ic

        if fill_Neg == 'normal':

            ic_ir = np.where(ic_ir < 0, 0, ic_ir)

        elif fill_Neg == 'mean':

            ic_ir = np.where(ic_ir < 0, mean_ic, ic_ir)

        return ic_ir

    def _opt_icir(self, ic: pd.DataFrame, fill_Neg: str,
                  target_func: Callable) -> pd.Series:
        '''
        约束条件下优化失败时调用，_explicit_solutions_icir函数
        ------
        输入参数:
            mean_ic:index-因子名 value-因子在一段时间内得ic均值

        '''

        size = ic.shape[1]
        np.random.seed(42)
        # s.t w >= 0
        bounds = tuple((0, None) for _ in range(size))

        res = optimize.minimize(fun=target_func,
                                x0=np.random.randn(size),
                                args=ic,
                                bounds=bounds)

        if res['success']:

            return pd.Series(res['x'], index=ic.columns.tolist())

        else:

            logging.warning(f'计算失败')

            return self._explicit_solutions_icir(ic, fill_Neg)

    @staticmethod
    def _target_func_samp(w: np.array, ic: pd.DataFrame) -> float:
        '''
        使用样本协方差
        最大化IC IR的目标函数
        ------
        输入参数:
            w:因子合成的权重
            ic:IC均值向量 数据为因子在过去一段时间的IC均值
        '''

        mean_ic = ic.mean()

        return -np.divide(w.T @ mean_ic, np.sqrt(w @ ic.cov() @ w.T))

    @staticmethod
    def _target_func(w: np.array, ic: pd.DataFrame) -> float:
        '''
        使用ledoit协方差
        最大化IC IR的目标函数
        ------
        输入参数:
            w:因子合成的权重
            ic:IC均值向量 数据为因子在过去一段时间的IC均值
        '''
        mean_ic = ic.mean()

        return -np.divide(w.T @ mean_ic, np.sqrt(w @ ledoit_wolf(ic)[0] @ w.T))
        
        
# 振幅因子


class AF_factor(object):

    '''
    lamb为切分变量
    group为高低分组high,low两个参数
    '''

    def __init__(self, securities: Union[str, list], watch_date: str, N: int) -> None:

        self.securities = securities

        self.watch_date = watch_date

        self._N = N

        self.max_window = N + 2

    def get_data(self):
        '''数据获取'''

        data = get_price(self.securities,
                         end_date=self.watch_date,
                         count=self.max_window,
                         fields=['close', 'high', 'low', 'paused'], panel=False)

        self.data = data.pivot(index='time', columns='code')

    def calc(self, lamb: float, group: str) -> pd.Series:
        '''因子计算'''
        self.lamb = round(lamb, 2)
        self.group = group

        af_df = self._calc_af()
        af_df = af_df.iloc[-self._N:]

        cond1 = self._q_split()
        cond1 = cond1.iloc[-self._N:]

        cond2 = self._get_paused()
        cond2 = cond2.iloc[-self._N:]

        cond = cond1 * cond2

        ser = (af_df * cond).mean()
        ser.name = self.name
        return ser

    def _q_split(self) -> pd.DataFrame:
        '''分割'''
        close = self.data['close']

        cond = close.rank(pct=True) >= self.lamb

        if self.group == 'high':

            return close.rank(pct=True, ascending=False) <= self.lamb

        elif self.group == 'low':

            return close.rank(pct=True, ascending=True) <= self.lamb

        else:
            raise ValueError('group参数仅能为high,low.')

    def _calc_af(self) -> pd.DataFrame:
        '''计算振幅'''
        return self.data['high'] / self.data['low'] - 1

    def _get_paused(self) -> pd.DataFrame:
        '''一字跌停后一日标记为False'''
        close_df = self.data['close']
        high_df = self.data['high']
        low_df = self.data['low']
        paused = self.data['paused']  # 停牌

        # 跌停
        cond1 = (close_df / close_df.shift(1) - 1) < -0.09
        # 一字
        cond2 = (high_df == low_df)

        res = (cond1 & cond2)
        res = (paused + res).astype(bool)

        return (~res).shift(1)

    def v_factor(self, lamb: float = 0.5) -> pd.Series:

        return self.calc(lamb, 'high') - self.calc(lamb, 'low')

    @property
    def name(self) -> str:

        return f'AF_{round(self.lamb,2)}_{self.group}'

# 聪明钱因子


class Q_factor(object):

    def __init__(self, securities: Union[str, list], watch_date: str, N: int = 10, frequency: str = '30m', mod: str = 'normal') -> None:

        self.securities = securities
        self.watch_date = watch_date
        self.frequency = frequency
        self.N = N
        self._get_count()
        self.mod = mod  # normal传统 ln对数

    def get_data(self):

        self.data = get_price(self.securities,
                              end_date=self.watch_date,
                              count=self.minute_count * self.N, frequency='30m',
                              fields=['close', 'volume', 'open'],
                              panel=False)

    def _get_count(self):
        '''计算一日需要多少个周期'''
        ALL_DAY = 240  # 一个完整交易日分钟数

        if self.frequency[-1] != 'm':

            raise ValueError('frequency参数必须是X minute(X必须是整数)')

        self.minute_count = ALL_DAY / int(self.frequency.replace('m', ''))

    def calc(self, beta: float = -0.5) -> pd.Series:

        self.beta = round(beta, 2)
        # 文章貌似没说涨停股的处理...如果涨停对此因子的影响应该很大
        data = (self.data.query('volume != 0')
                         .pivot(index='time', columns='code'))

        close_df = data['close']
        vol_df = data['volume']
        open_df = data['open']

        ret_df = close_df / open_df - 1
        abs_ret = ret_df.abs()

        if self.mod == 'normal':

            # St = |Rt|/√Vt，其中𝑅𝑡为第 t 分钟涨跌幅，𝑉𝑡为第 t 分钟成交量
            S = abs_ret / vol_df.pow(beta)

        else:

            # 分钟涨跌幅绝对值除以分钟成交量对数值
            S = abs_ret / np.log(vol_df)

        # 降序排列【从大到小排序】
        S_rank = S.rank(ascending=False)

        concat_df = pd.concat(
            (S_rank.stack(), vol_df.stack(), close_df.stack()), axis=1, sort=True)
        concat_df.columns = ['rank', 'vol', 'close']

        ser = concat_df.groupby(level='code').apply(self.calc_Q)
        ser.name = self.name
        return ser

    # @staticmethod
    def calc_Q(self, df: pd.DataFrame) -> float:

        def vwap(df: pd.DataFrame) -> float:
            '''计算vwap'''

            try:

                v = np.average(df['close'], weights=df['vol'])

            except ZeroDivisionError:

                print(self.watch_date)
                print(df)
                print(sort_df['vol'])
                raise ValueError('ZeroDivisionError')

            return v

        def _add_flag(sort_df: pd.DataFrame) -> pd.Series:
            '''
            标记将分钟数据按照指标St从大到小进行排序，
            取成交量累积占比前20%的分钟
            '''

            cum_df = sort_df['vol'].cumsum() / sort_df['vol'].sum()

            cond = (cum_df <= 0.2)

            if (sort_df[cond].empty) and (cum_df.iloc[0] > 0.2):

                return sort_df.iloc[:1, :]

            return sort_df[cond]

        # 将分钟数据按照指标St从大到小进行排序，取成交量累积占比前20%的分钟,视为聪明钱交易
        sort_df = (df.reset_index()
                     .set_index('rank')
                     .sort_index())

        smart_df = _add_flag(sort_df)
        # 计算聪明钱交易的成交量加权平均价VWAPsmart
        vwap_smart = vwap(smart_df)
        # 计算所有交易的成交量加权平均价VWAPall
        vwap_all_f = vwap(sort_df)

        return vwap_smart / vwap_all_f

    @property
    def name(self) -> str:

        return f'Q_{self.N}_{self.frequency}_{self.beta}'

# 动量因子


class RetN_momentum(object):

    def __init__(self, securities: Union[str, list], watch_date: str, max_window: int) -> None:

        self.securities = securities
        self.watch_date = watch_date
        self.max_window = max_window + 1

    def get_data(self) -> None:
        '''数据获取'''
        data = get_price(self.securities, end_date=self.watch_date,
                         count=self.max_window, fields=['high', 'low', 'close'], panel=False)
        self.data = data.pivot(index='time', columns='code')

    def calc(self, mod: str, lamb: float, group: str = None) -> pd.Series:
        '''因子计算

        mod:为计算方法，sort排序分割,q分位数分割,lamb按阈值进行分割
        group:高低分组 high/low
        当mod为sort时 lamb及q无效
        '''
        self.mod = mod
        self.lamb = lamb

        mod_dic = {'sort': self._sort_split,
                   'q': self._lamb_quantile, 'lamb': self._lamb_split}

        af_df = self._get_AF(self.data).iloc[1:]
        pct_chg = self.data['close'].pct_change().iloc[1:]

        cond = mod_dic[self.mod](af_df=af_df, lamb=self.lamb)

        if self.mod == 'sort' and self.group == 'A':

            # 低振幅
            return (~cond * pct_chg).sum()

        elif self.mod == 'sort' and self.group == 'B':

            # 高振幅
            return (cond * pct_chg).sum()

        elif self.mod == 'q':
            # q模式下
            return (cond * pct_chg).sum()

        elif self.mod == 'lamb':
            # lamb模式
            return (cond * pct_chg).sum()

    @staticmethod
    def _get_AF(data: pd.DataFrame) -> pd.DataFrame:
        '''计算振幅'''

        return data['high'] / data['low'] - 1

    @staticmethod
    def _lamb_quantile(af_df: pd.DataFrame, lamb: int) -> pd.DataFrame:
        '''获取大于lmb的部分 

        True/False表示 True表示大于lmb的部分
        '''

        quantile = af_df.apply(lambda x: pd.qcut(
            x.rank(method='first'), 10, duplicates='drop', labels=list(range(1, 11))))

        return quantile == lmb

    @staticmethod
    def _lamb_split(af_df: pd.DataFrame, lamb: int) -> pd.DataFrame:

        return af_df.rank(pct=True) <= lamb

    def _sort_split(self, af_df: pd.DataFrame, **kwds) -> pd.DataFrame:
        '''按排名计算

        True/False表示 True表示大于N/2的部分
        '''

        return af_df.rank() > (self.max_window // 2)

    @property
    def name(self):

        return f'Ret{self.max_window-1}_{self.lamb}_momentum' if self.mod != 'sort' else f'Ret{self.max_window-1}_{self.group}_momentum'

class RPS(Factor):
    
    import warnings
    warnings.filterwarnings("ignore")

    name = 'RPS'
    max_window = 23
    dependencies = ['close']
    
    def calc(self, data)->pd.Series:
        
        close_df = data['close']
        pct_chg = close_df.pct_change().iloc[1:]
        rps = 1 - pct_chg.rank(axis=1).div(pct_chg.count(axis=1),axis=0)
        rps = rps.mean()
        
        return rps
        
'''因子处理'''


def get_momentum_factor(gold_stocks: list, watch_date: str) -> pd.DataFrame:

    # 振幅因子 升序
    af = AF_factor(gold_stocks, watch_date, 20)
    af.get_data()
    af_ser = af.v_factor(0.5)
    af_ser.name = 'AF'

    # 聪明钱因子 降序
    q = Q_factor(gold_stocks, watch_date)
    q.get_data()
    q_ser = q.calc(0.5)
    q_ser.name = 'smart_q'

    # 动量 降序
    rm = RetN_momentum(gold_stocks, watch_date, 120)
    rm.get_data()
    rm_ser = rm.calc('lamb', 0.3)
    rm_ser.name = 'RM'

    return pd.concat((af_ser, q_ser, rm_ser), axis=1, sort=True)


def score_indicators(factor_df: pd.DataFrame, ind_direction: Union[bool, dict]) -> pd.DataFrame:
    '''对因子打分
    ind_direction:设置所有因子的排序方向，'ascending'表示因子值越大分数越高，'descending'表示因子值越小分数越高；
    当为dict时，可以分别对不同因子的排序方向进行设置
    '''

    if isinstance(ind_direction, bool):

        ind_direction = {col: ind_direction for col in factor_df.columns}

    return pd.concat((factor_df[col].rank(ascending=asc) for col, asc in ind_direction.items()), axis=1, sort=True)


'''组合优化'''


def opt_pos_weight(securities: list, watch_date: Union[dt.date, str], window: int = 120, mod: str = False) -> pd.Series:
    '''获取对应的组合优化权重'''

    if not mod:

        return None

    target_func = {'MaxSharpeRatio': MaxSharpeRatio(rf=0.03, weight_sum_equal=1.0, count=window),
                   'MaxProfit': MaxProfit(count=window),
                   'MinVariance': MinVariance(count=window),
                   'RiskParity': RiskParity(count=window, risk_budget=None)}

    return portfolio_optimizer(date=watch_date,
                               securities=securities,
                               target=target_func[mod],
                               constraints=WeightConstraint(
                                   low=0.3, high=1.0),
                               bounds=Bound(low=0.05, high=1.0))


'''交易'''


def trade_func(context):

    # 是否使用因子
    if g.use_factor:

        securities = g.base_target['股票代码'].unique().tolist()

        watch_date = context.previous_date

        
        score_df = composition_factors(securities,watch_date,g.in_week,12)

        # 打分
        target = score_df['等权法'].nlargest(g.handle_num).index.tolist()

    

    else:
        # 计算推荐率
        nps_ser = get_net_promoter_score(g.base_target)
        target = nps_ser.nlargest(g.handle_num).index.tolist()

    # 是否进行组合优化
    if g.optimizer_mod:
        optimized_weight = opt_pos_weight(
            target, context.previous_date, 120, g.optimizer_mod)

    else:

        optimized_weight = None

    # 优化失败，给予警告
    if type(optimized_weight) == type(None):

        if g.optimizer_mod:
            print('警告：组合优化失败')

        order2list(context, target)

    else:

        order2dict(context, optimized_weight)


def get_target_securities(context) -> pd.DataFrame:
    '''获取当月金股'''
    watch_date = time2str(context.previous_date, '%Y-%m')

    if watch_date in g.gold_stock_frame.index:

        g.base_target = g.gold_stock_frame.loc[watch_date]

    else:
        raise ValueError(f'数据储存{watch_date}不在金股数据中')
    



def order2dict(context, target_dict: dict) -> None:

    if not isinstance(target_dict, (dict, pd.Series)):
        raise ValueError('target_dict类型必须为dict')

    # 先卖出不在股票池中的股票
    for hold in context.portfolio.long_positions:

        if hold not in target_dict:

            order_target(hold, 0)

    total_value = context.portfolio.total_value

    for stock, w in target_dict.items():

        order_target_value(stock, w * total_value)  # 调整标的至目标权重


def order2list(context, target: list) -> None:

    if isinstance(target, str):

        target = [target]

    if target:

        # 先卖出不在股票池中的股票
        for hold in context.portfolio.long_positions:

            if hold not in target:

                order_target(hold, 0)

        # 等权持有
        veryStock = context.portfolio.total_value / len(target)

        for stock in target:

            order_target_value(stock, veryStock)
