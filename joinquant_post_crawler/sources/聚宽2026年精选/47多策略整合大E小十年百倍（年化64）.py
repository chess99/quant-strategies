# 克隆自聚宽文章：https://www.joinquant.com/post/51000
# 标题：多策略整合_大E小_十年百倍（年化64%回撤28%）
# 作者：komunling

import numpy as np
import pandas as pd
import math
import datetime

from jqdata import *
from kuanke.wizard import *

def initialize(context):
    # 此处根据需要分配资金比例
    # 如需只跑ETF策略，则设置为[0.0,1.0,0.0]
    # 0=大白马策略、1=ETF策略、2=小市值策略
    g.portfolio_value_proportion = [0.15,0.35,0.50]

    # 设置基准，这里使用ETF策略中用到的基准来保持一致性
    set_benchmark('159915.XSHE')
    set_option('use_real_price', True)
    set_option("avoid_future_data", True)
    set_slippage(PriceRelatedSlippage(0.001))
    #set_slippage(FixedSlippage(0.001))
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0001, 
                             close_commission=0.0001, close_today_commission=0, 
                             min_commission=5), type='stock')
    log.set_level('system', 'error')

    # 创建子组合：0=大白马策略、1=ETF策略、2=小市值策略
    set_subportfolios([
        SubPortfolioConfig(context.portfolio.starting_cash*g.portfolio_value_proportion[0], 'stock'),   
        SubPortfolioConfig(context.portfolio.starting_cash*g.portfolio_value_proportion[1], 'stock'),    
        SubPortfolioConfig(context.portfolio.starting_cash*g.portfolio_value_proportion[2], 'stock'),   
    ])

    # 全局变量初始化
    g.sells = []
    g.risks = []
    g.m_days = 25 # 动量参考天数
    g.etf_pool = [
        '513100.XSHG', #纳指100
        '159915.XSHE', #创业板100
        '513520.XSHG', #日经
        '511010.XSHG', #国债
        '518880.XSHG', #黄金ETF
    ]

    # 初始化白马策略实例
    params_bmzh = {
        'max_hold_count': 1,
        'max_select_count': 3,
    }
    g.bmzh_strategy = BMZH_Strategy(context, subportfolio_index=0, name='大白马股攻防转换策略', params=params_bmzh)

    # 初始化外盘ETF策略实例
    params_wpetf = {
        'max_hold_count': 1,
        'max_select_count': 2,
    }
    g.wpetf_strategy = WPETF_Strategy(context, subportfolio_index=1, name='ETF轮动策略', params=params_wpetf, 
                                      etf_pool=g.etf_pool, m_days=g.m_days, sells=g.sells, risks=g.risks)
    
    # 初始化小市值策略实例
    params_xszgjt = {
        'max_hold_count': 3,
        'max_select_count': 10,
        'use_empty_month': True,
        'empty_month': [1,4],
        'use_stoplost': True,
    }
    g.xszgjt_strategy = XSZ_GJT_Strategy(context, subportfolio_index=2, name='小市值国九条策略', params=params_xszgjt)

    # 根据资金比例决定是否运行策略调度
    # 如果白马策略资金为0则不调度相关函数，同理对小市值策略

    # 定时执行计划
    if g.portfolio_value_proportion[0] > 0:
        run_monthly(bmzh_market_temperature, 1, time='5:00')
        run_monthly(bmzh_select,1, time='7:40')
        run_monthly(bmzh_adjust,1, time='9:35')

    if g.portfolio_value_proportion[1] > 0:
        run_daily(wpetf_trade, '9:35')  # ETF策略交易调度

    if g.portfolio_value_proportion[2] > 0:
        run_daily(xszgjt_day_prepare, time='7:30')
        run_weekly(xszgjt_select, 2, time='7:40')
        run_daily(xszgjt_open_market, time='9:30')
        run_weekly(xszgjt_adjust, 2, time='9:35')
        run_daily(xszgjt_sell_when_highlimit_open, time='11:20')
        run_daily(xszgjt_sell_when_highlimit_open, time='14:50')


def bmzh_select(context):
    g.bmzh_strategy.select(context)

def bmzh_adjust(context):
    g.bmzh_strategy.adjustwithnoRM(context)

def bmzh_market_temperature(context):
    g.bmzh_strategy.Market_temperature(context)

def wpetf_trade(context):
    # 当ETF策略有资金时才运行
    if g.portfolio_value_proportion[1] > 0:
        g.wpetf_strategy.trade(context)

def xszgjt_day_prepare(context):
    g.xszgjt_strategy.day_prepare(context)

def xszgjt_select(context):
    g.xszgjt_strategy.select(context)

def xszgjt_adjust(context):
    g.xszgjt_strategy.adjust(context)

def xszgjt_open_market(context):
    g.xszgjt_strategy.close_for_empty_month(context)
    g.xszgjt_strategy.close_for_stoplost(context)

def xszgjt_sell_when_highlimit_open(context):
    g.xszgjt_strategy.sell_when_highlimit_open(context)


########################################
# 下方为策略类定义和辅助函数(保留框架)
########################################

def polynomial(x):
    x_points = np.array([1, 10, 20, 30, 40, 50, 60, 70, 80, 90, 99])
    y_points = np.array([50, 2, 0.1,  0,  0,  0, 0, 0, -0.1, -2, -50])
    coefficients = np.polyfit(x_points, y_points, deg=5)
    polynomial_f = np.poly1d(coefficients)
    return polynomial_f(x)


class Strategy:
    def __init__(self, context, subportfolio_index, name, params):
        self.subportfolio_index = subportfolio_index
        self.name = name
        self.params = params
        self.max_hold_count = self.params.get('max_hold_count', 1)
        self.max_select_count = self.params.get('max_select_count', 5)
        self.use_empty_month = self.params.get('use_empty_month', False)
        self.empty_month = self.params.get('empty_month', [])
        self.use_stoplost = self.params.get('use_stoplost', False)
        self.stoplost_silent_days = self.params.get('stoplost_silent_days', 20)
        self.stoplost_level = self.params.get('stoplost_level', 0.2)
        
        self.select_list = []
        self.stoplost_date = None
        self.hold_list = []
        self.history_hold_list = []
        self.not_buy_again_list = []
        self.yestoday_high_limit_list = []
        self.no_trading_today_signal = self.params.get('no_trading_today_signal', False)

    def day_prepare(self, context):
        subportfolio = context.subportfolios[self.subportfolio_index]
        self.hold_list = list(subportfolio.long_positions)
        self.history_hold_list.append(self.hold_list)
        if len(self.history_hold_list) > 20:
            self.history_hold_list = self.history_hold_list[-20:]
        temp_set = set()
        for lists in self.history_hold_list:
            for stock in lists:
                temp_set.add(stock)
        self.not_buy_again_list = list(temp_set)
        
        if self.hold_list:
            df = get_price(self.hold_list, end_date=context.previous_date, frequency='daily', fields=['close','high_limit'], count=1, panel=False, fill_paused=False)
            df = df[df['close'] == df['high_limit']]
            self.yestoday_high_limit_list = list(df.code)
        else:
            self.yestoday_high_limit_list = []
        
        self.check_empty_month(context)
        self.check_stoplost(context)

    def stockpool_index(self, context, index_code, pool_id=1):
        lists = list(get_index_stocks(index_code))
        if pool_id == 1:
            current_data = get_current_data()
            lists = [stock for stock in lists if not 
                        (
                            (current_data[stock].day_open == current_data[stock].high_limit) or
                            (current_data[stock].day_open == current_data[stock].low_limit) or
                            current_data[stock].paused or
                            current_data[stock].is_st or
                            ('ST' in current_data[stock].name) or
                            ('*' in current_data[stock].name) or
                            ('退' in current_data[stock].name) or
                            (stock.startswith('30')) or  
                            (stock.startswith('68')) or  
                            (stock.startswith('8')) or   
                            (stock.startswith('4'))      
                        )
                     ]
        return lists

    def select(self, context):
        if self.use_empty_month and context.current_dt.month in self.empty_month:
            self.select_list = []
            return
        if self.stoplost_date is not None:
            self.select_list = []
            return
        self.select_list = []

    def print_trade_plan(self, context, select_list):
        # 可根据需要打印交易计划
        pass

    def check_empty_month(self, context):
        subportfolio = context.subportfolios[self.subportfolio_index]
        if self.use_empty_month and context.current_dt.month in self.empty_month and len(subportfolio.long_positions) > 0:
            content = context.current_dt.date().strftime("%Y-%m-%d") + self.name + ': 进入空仓期\n'
            for stock in subportfolio.long_positions:
                content += stock + "\n"
            print(content)

    def close_for_empty_month(self, context):
        subportfolio = context.subportfolios[self.subportfolio_index]
        if self.use_empty_month and context.current_dt.month in self.empty_month and len(subportfolio.long_positions) > 0:
            self.sell(context, list(subportfolio.long_positions))

    def check_stoplost(self, context):
        subportfolio = context.subportfolios[self.subportfolio_index]
        if self.use_stoplost:
            if self.stoplost_date is None:
                if subportfolio.long_positions:
                    last_prices = history(1, unit='1m', field='close', security_list=subportfolio.long_positions)
                    for stock in subportfolio.long_positions:
                        position = subportfolio.long_positions[stock]
                        if (position.avg_cost - last_prices[stock][-1]) / position.avg_cost > self.stoplost_level:
                            self.stoplost_date = context.current_dt.date()
                            print(self.name + ': 开始止损')
                            break
            else:
                if (context.current_dt.date() - self.stoplost_date).days >= self.stoplost_silent_days:
                    self.stoplost_date = None
                    print(self.name + ': 退出止损')

    def close_for_stoplost(self, context):
        subportfolio = context.subportfolios[self.subportfolio_index]
        if self.use_stoplost and self.stoplost_date is not None and len(subportfolio.long_positions) > 0:
            self.sell(context, list(subportfolio.long_positions))


    def adjust(self, context):
        if self.use_empty_month and context.current_dt.month in self.empty_month:
            return
        if self.stoplost_date is not None:
            return
        
        hold_list = list(context.subportfolios[self.subportfolio_index].long_positions)
        sell_stocks = [stock for stock in hold_list if stock not in self.select_list[:self.max_hold_count]]
        self.sell(context, sell_stocks)
        self.buy(context, self.select_list)

    def adjustwithnoRM(self, context):
        # 不进行风险管理的调仓
        hold_list = list(context.subportfolios[self.subportfolio_index].long_positions)
        sell_stocks = [stock for stock in hold_list if stock not in self.select_list[:self.max_hold_count]]
        self.sell(context, sell_stocks)
        self.buy(context, self.select_list)


    def sell_when_highlimit_open(self, context):
        if self.yestoday_high_limit_list:
            for stock in self.yestoday_high_limit_list:
                if stock in context.subportfolios[self.subportfolio_index].long_positions:
                    current_data = get_price(stock, end_date=context.current_dt, frequency='1m', fields=['close','high_limit'], 
                                             skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True)
                    if current_data.iloc[0,0] < current_data.iloc[0,1]:
                        self.sell(context, [stock])
                        content = context.current_dt.date().strftime("%Y-%m-%d") + ' ' + self.name + ': {}涨停打开，卖出\n'.format(stock)
                        print(content)

    def buy(self, context, buy_stocks):
        subportfolio = context.subportfolios[self.subportfolio_index]
        buy_count = self.max_hold_count - len(subportfolio.long_positions)
        if buy_count > 0 and buy_stocks:
            value = subportfolio.available_cash / buy_count
            for stock in buy_stocks:
                if stock not in subportfolio.long_positions:
                    self.__open_position(stock, value)
                    buy_count -= 1
                    if buy_count <= 0:
                        break

    def sell(self, context, sell_stocks):
        subportfolio = context.subportfolios[self.subportfolio_index]
        for stock in sell_stocks:
            if stock in subportfolio.long_positions:
                closed = self.__close_position(stock)
                if closed and self.subportfolio_index == 1:
                    # 只在ETF子组合记录卖出，如果有需要
                    pass

    def __open_position(self, security, value):
        order = order_target_value(security, value, pindex=self.subportfolio_index)
        if order and order.filled > 0:
            return True
        return False

    def __close_position(self, security):
        order = order_target_value(security, 0, pindex=self.subportfolio_index)
        if order and order.status == OrderStatus.held and order.filled == order.amount:
            return True
        return False


    # 过滤函数
    def filter_kcbj_stock(self, stock_list):
        # 去除科创、北交所
        return [s for s in stock_list if not (s.startswith('4') or s.startswith('8') or s.startswith('68'))]

    def filter_paused_stock(self, stock_list):
        current_data = get_current_data()
        return [stock for stock in stock_list if not current_data[stock].paused]

    def filter_st_stock(self, stock_list):
        current_data = get_current_data()
        return [stock for stock in stock_list
                if not current_data[stock].is_st
                and 'ST' not in current_data[stock].name
                and '*' not in current_data[stock].name
                and '退' not in current_data[stock].name]

    def filter_highlimit_stock(self, context, stock_list):
        subportfolio = context.subportfolios[self.subportfolio_index]
        last_prices = history(1, unit='1m', field='close', security_list=stock_list)
        current_data = get_current_data()
        return [stock for stock in stock_list if (stock in subportfolio.long_positions)
                or last_prices[stock][-1] < current_data[stock].high_limit]

    def filter_lowlimit_stock(self, context, stock_list):
        subportfolio = context.subportfolios[self.subportfolio_index]
        last_prices = history(1, unit='1m', field='close', security_list=stock_list)
        current_data = get_current_data()
        return [stock for stock in stock_list if (stock in subportfolio.long_positions)
                or last_prices[stock][-1] > current_data[stock].low_limit]

    def filter_new_stock(self, context, stock_list, days):
        return [stock for stock in stock_list if (context.previous_date - get_security_info(stock).start_date) >= datetime.timedelta(days=days)]

    def filter_locked_shares(self, context, stock_list, days):
        df = get_locked_shares(stock_list=stock_list, start_date=context.previous_date.strftime('%Y-%m-%d'), forward_count=days)
        df = df[df['rate1'] > 0.2]
        filterlist = list(df['code'])
        return [stock for stock in stock_list if stock not in filterlist]

    def print_position_info(self, context):
        trades = get_trades()
        for _trade in trades.values():
            print('成交记录：'+str(_trade))
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


# 白马股攻防转换策略（BMZH策略）
class BMZH_Strategy(Strategy):
    def __init__(self, context, subportfolio_index, name, params):
        super().__init__(context, subportfolio_index, name, params)
        self.market_temperature = "warm"
    
    def select(self, context):
        self.select_list = self.__get_rank(context)[:self.max_select_count]
        self.print_trade_plan(context, self.select_list)
    
    def __get_rank(self, context):
        initial_list = super().stockpool_index(context, "000300.XSHG")

        if self.market_temperature == "cold":
            q = query(
                valuation.code
            ).filter(
                valuation.pb_ratio > 0,
                valuation.pb_ratio < 1,
                cash_flow.subtotal_operate_cash_inflow > 0,
                indicator.adjusted_profit > 2.5e8,
                income.operating_revenue > 10e8,
                income.net_profit > 2.5e8,
                cash_flow.subtotal_operate_cash_inflow/indicator.adjusted_profit > 2.0,
                indicator.inc_return > 1.5,
                indicator.inc_net_profit_year_on_year > -15,
                valuation.code.in_(initial_list)
            ).order_by((indicator.roa/valuation.pb_ratio).desc()).limit(self.max_select_count + 1)
        elif self.market_temperature == "warm":
            q = query(
                valuation.code
            ).filter(
                valuation.pb_ratio > 0,
                valuation.pb_ratio < 1,
                cash_flow.subtotal_operate_cash_inflow > 0,
                indicator.adjusted_profit > 2.5e8,
                income.operating_revenue > 10e8,
                income.net_profit > 2.5e8,
                cash_flow.subtotal_operate_cash_inflow/indicator.adjusted_profit>1.0,
                indicator.inc_return > 2.0,
                indicator.inc_net_profit_year_on_year > 0,
                valuation.code.in_(initial_list)
            ).order_by((indicator.roa/valuation.pb_ratio).desc()).limit(self.max_select_count + 1)
        else: # hot
            q = query(
                valuation.code
            ).filter(
                valuation.pb_ratio > 3,
                cash_flow.subtotal_operate_cash_inflow > 0,
                indicator.adjusted_profit > 2.5e8,
                income.operating_revenue > 10e8,
                income.net_profit > 2.5e8,
                cash_flow.subtotal_operate_cash_inflow/indicator.adjusted_profit>0.5,
                indicator.inc_return > 3.0,
                indicator.inc_net_profit_year_on_year > 20,
                valuation.code.in_(initial_list)
            ).order_by(indicator.roa.desc()).limit(self.max_select_count + 1)

        check_out_lists = list(get_fundamentals(q).code)
        return check_out_lists

    def Market_temperature(self, context):
        # 获取沪深300指数的历史价格数据
        hist = attribute_history('000300.XSHG', 600, '1d', fields=('close'), df=False)
        index300 = hist['close']

        # 1. 市场长期位置market_height: 最近5日均值相对600日内高低点所处的位置
        market_height = (np.mean(index300[-5:]) - min(index300)) / (max(index300) - min(index300))
        
        # 2. 短期动量指标：RSI（相对强弱指标）
        #   RSI通常是14天周期，这里取14天作为短期参考
        short_hist = attribute_history('000300.XSHG', 30, '1d', fields=('close'), df=False)
        close_30 = short_hist['close']
        rsi = self.__calculate_RSI(close_30, period=20) #14
        
        # 3. 波动率指标：使用布林带宽度或简单年度化波动率来衡量市场热度
        #   布林带宽度 = (上轨 - 下轨) / 中轨, 此处选择20天布林带作为参考
        bb_width = self.__calculate_bollinger_width(close_30, period=30) #20
        
        # 根据上述三个维度指标判断市场温度
        # 设定一些阈值(需根据实际测试微调)：
        #   market_height低(<0.2)且RSI低于30，波动率低 => cold
        #   market_height高(>0.8)且RSI>70, 波动率高 => hot
        #   否则 => warm
        # 同时可加更多条件，如RSI介于30-70之间，bb_width适中等。
        
        if market_height < 0.30 or (rsi < 30 and bb_width < 0.05):
            self.market_temperature = "cold"
        elif market_height > 0.70 or (rsi > 70 and bb_width > 0.1):
            self.market_temperature = "hot"
        else:
            self.market_temperature = "warm"
        
        # 可根据市场温度记录一些指标，如temp，用于回测观察
        if self.market_temperature == "hot":
            temp = 400
        elif self.market_temperature == "warm":
            temp = 300
        else:
            temp = 200
            
        if context.run_params.type != 'sim_trade':
            record(temp=temp)

    def __calculate_RSI(self, prices, period=14):
        """ 计算RSI指标 """
        deltas = np.diff(prices)
        ups = deltas[deltas>0].sum()
        downs = -deltas[deltas<0].sum()
        if downs == 0:
            return 100
        rs = ups/downs
        return 100 - (100/(1+rs))

    def __calculate_bollinger_width(self, prices, period=20, nbdev=2):
        """ 
        计算布林带宽度 
        布林带上轨 = MA + nbdev*std
        下轨 = MA - nbdev*std
        中轨 = MA
        宽度 = (上轨-下轨)/中轨
        """
        ma = np.mean(prices[-period:])
        std = np.std(prices[-period:])
        upper = ma + nbdev*std
        lower = ma - nbdev*std
        if ma == 0:
            return 0
        width = (upper - lower)/ma
        return width

class WPETF_Strategy(Strategy):
    def __init__(self, context, subportfolio_index, name, params, etf_pool, m_days, sells, risks):
        super().__init__(context, subportfolio_index, name, params)
        self.etf_pool = etf_pool
        self.m_days = m_days
        self.sells_global = sells
        self.risks_global = risks

    def get_rank(self, etf_pool):
        score_list = []
        risks_d = 0
        for etf in etf_pool:
            df = attribute_history(etf, self.m_days, '1d', ['close'])
            y = np.log(df['close'])
            x = np.arange(len(y))
            weights = np.exp(np.linspace(-1, 0, num=len(y)))        
            coeffs = np.polyfit(x[-25:], y[-25:], 1)
            slope, intercept = coeffs
            coeffs_s = np.polyfit(x[-15:], y[-15:], 1)
            slope_s, intercept_s = coeffs_s

            coeffs2 = np.polyfit(x[-25:], y[-25:], 2, w=weights[-25:])
            curve2, slope2, intercept2 = coeffs2

            # 平滑曲线
            y_smooth = np.convolve(y[-25:], np.ones(5)/5, mode='valid')
            x_smooth = np.arange(len(y_smooth))
            coeffs2_smooth = np.polyfit(x_smooth, y_smooth, 2, w=weights[-(len(y_smooth)):])
            curve2_smooth, slope2_smooth, intercept2_smooth = coeffs2_smooth

            moving_average = df['close'].rolling(window=20).mean()
            recent_close = df['close'].iloc[-1]
            recent_ma = moving_average.iloc[-1]

            changes = np.diff(y[-10:])
            gains = changes[changes > 0].sum()
            losses = -changes[changes < 0].sum()
            if losses == 0:
                losses = 1e-6
            RS = gains / losses
            RSI = 100 - (100 / (1 + RS))

            if ((recent_close > recent_ma) and ((curve2_smooth < -0.0003) or (curve2 < -0.0006))):
                slope_adjust = 0
            elif ((recent_close < recent_ma) and ((curve2_smooth > 0.0003) or (curve2 > 0.0006))):
                slope_adjust = slope + 0.005
            else:
                slope_adjust = slope
            annualized_returns = math.pow(math.exp(slope_adjust), 250) - 1
            annualized_returns_s = math.pow(math.exp(slope_s), 250) - 1

            y_fit = np.polyval(coeffs, x[-25:])
            ss_res = np.sum((y[-25:] - y_fit) ** 2)
            ss_tot = np.sum((y[-25:] - np.mean(y[-25:])) ** 2)
            r_squared = 1 - (ss_res / ss_tot)

            y_fit_s = np.polyval(coeffs_s, x[-15:])
            ss_res_s = np.sum((y[-15:] - y_fit_s)**2)
            ss_tot_s = np.sum((y[-15:] - np.mean(y[-15:]))**2)
            r_squared_s = 1 - (ss_res_s / ss_tot_s)

            combined_score = annualized_returns * r_squared 
            combined_score_s = annualized_returns_s * r_squared_s 
            if (r_squared_s >= 0.8) and (combined_score_s > combined_score):
                combined_score = combined_score_s

            if RSI > 95:
                combined_score = 0
            if RSI < 10:
                combined_score = combined_score + polynomial(RSI)/8
            if combined_score >= 25:
                combined_score = 0

            if etf in self.sells_global[-2:]:
                combined_score = 0

            risks_d += combined_score
            score_list.append((etf, combined_score))

        self.risks_global.append(risks_d)
        sorted_list = sorted(score_list, key=lambda x:x[1], reverse=True)
        filtered = [x[0] for x in sorted_list if x[1] > 0.01]
        return filtered

    def trade(self, context):
        target_num = 1
        target_list = self.get_rank(self.etf_pool)[:target_num]

        subportfolio = context.subportfolios[self.subportfolio_index]
        hold_list = list(subportfolio.long_positions)
        sell_tag = ''

        # 卖出不在目标列表中的ETF
        for etf in hold_list:
            if etf not in target_list:
                order_target_value(etf, 0, pindex=self.subportfolio_index)
                sell_tag = etf
                print('sell ' + str(etf))
            else:
                print('keep: ' + str(etf))
        if sell_tag != '':
            self.sells_global.append(sell_tag)

        # 买入目标ETF
        hold_list = list(subportfolio.long_positions)
        if len(hold_list) < target_num and len(target_list) > 0:
            value = subportfolio.available_cash / (target_num - len(hold_list))
            for etf in target_list:
                if etf not in hold_list:
                    order_target_value(etf, value, pindex=self.subportfolio_index)
                    print('buy ' + str(etf))

# 小市值国九条策略
class XSZ_GJT_Strategy(Strategy):
    def __init__(self, context, subportfolio_index, name, params):
        super().__init__(context, subportfolio_index, name, params)
        self.new_days = 350
        self.highest = 50

    def select(self, context):
        if self.use_empty_month and context.current_dt.month in self.empty_month:
            log.info('月份判断关仓期')
            return
        if self.stoplost_date is not None:
            return
        self.select_list = self.__get_rank(context)[:self.max_select_count]
        self.print_trade_plan(context, self.select_list)
    
    def __get_rank(self, context):
        # 第一个筛选
        initial_list = self.stockpool_index(context,'399101.XSHE')
        initial_list = self.filter_new_stock(context, initial_list, self.new_days)
        initial_list = self.filter_locked_shares(context, initial_list, 90)
        
        q = query(valuation.code,valuation.market_cap).filter(
            valuation.code.in_(initial_list),
            valuation.market_cap.between(5,30)
        ).order_by(valuation.market_cap.asc())
        df_fun = get_fundamentals(q)
        df_fun = df_fun[:100]
        initial_list = list(df_fun.code)
        initial_list = self.filter_paused_stock(initial_list)
        initial_list = self.filter_highlimit_stock(context, initial_list)
        initial_list = self.filter_lowlimit_stock(context, initial_list)

        q = query(valuation.code,valuation.market_cap).filter(
            valuation.code.in_(initial_list)
        ).order_by(valuation.market_cap.asc())
        df_fun = get_fundamentals(q)
        df_fun = df_fun[:50]
        final_list_1  = list(df_fun.code)

        # 第二个筛选
        lists2 = self.stockpool_index(context,'399101.XSHE')
        lists2 = self.filter_new_stock(context, lists2, self.new_days)
        lists2 = self.filter_locked_shares(context, lists2, 90)
        
        q = query(
            valuation.code,
            valuation.market_cap,
            income.np_parent_company_owners,
            income.net_profit,
            income.operating_revenue
        ).filter(
            valuation.code.in_(lists2),
            valuation.market_cap.between(10,50),
            income.np_parent_company_owners > 0,
            income.net_profit > 0,
            income.operating_revenue > 1e8
        ).order_by(valuation.market_cap.asc()).limit(50)
        
        df = get_fundamentals(q)
        final_list_2 = list(df.code)

        last_prices = history(1, unit='1d', field='close', security_list=final_list_2)
        final_list_2 = [stock for stock in final_list_2 if (stock in self.hold_list) or (last_prices[stock].iloc[0] <= self.highest)]

        target_list = list(dict.fromkeys(final_list_1 + final_list_2))
        target_list = target_list[:self.max_select_count*3]
        df_fun = get_fundamentals(query(
            valuation.code,
            indicator.roe,
            indicator.roa,
        ).filter(
            valuation.code.in_(target_list)
        ).order_by(
            valuation.market_cap.asc()
        ))
        final_list = df_fun.set_index('code').index.tolist()
        return final_list

