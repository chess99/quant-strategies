# 克隆自聚宽文章：https://www.joinquant.com/post/29185
# 标题：大盘股也能穿越牛熊市
# 作者：曹经伟

'''
大盘的五种走势：
反弹、持续上涨、回调、持续下跌、震荡
'''

from kuanke.wizard import *
from jqdata import *
import datetime
import time
import enum
import operator
import numpy as np
import math
import random

import talib
import jqdata as jy

from csv import DictReader
from sys import version_info
from six import StringIO

# 仓位管理
g_symbol_count = 50
g_max_cash_rate = 1.0
#g_balance_rate = min(1.0, g_max_cash_rate / max(g_symbol_count, 4) * 3.5)
g_balance_rate = 0.33
g_balance_rate_per_symbol = g_balance_rate * 1
g_min_available_cash_rate = 1.0 - g_max_cash_rate * 0.95
g_random_index = 1

    
g_benchmark_symbol = '000300.XSHG'
g_log_path = 'log/大盘精准预测.log'


# 初始化函数，设定基准等等
def initialize(context):
    set_benchmark('000300.XSHG')
    set_option('use_real_price', True)
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    
    clear_log(g_log_path)
    initialize_quant_env(context)
    run_daily(timer_event, time='14:30')
    
    
def initialize_quant_env(context):
    g.strategy_manager = StrategyManager()
    g.risk_control = RiskControl()
    g.stock_selector = StockSelector()
    
    g.strategy_manager.ResetStrategy(context, select_random_symbol(g.stock_selector.check_stocks(context), g_random_index, g_symbol_count))

def timer_event(context):
    log.info('+----------+----------+----------+----------+----------+----------+----------+')
    #log.info(datetime_to_string(context.current_dt))
    
    if (context.current_dt.minute % 30 != 0):
        return

    g.risk_control.CheckForBenchmark(context, g_benchmark_symbol)
    
    could_trade = g.risk_control.could_trade_baodie or g.risk_control.could_trade_chaodi
    if not could_trade and len(list(context.portfolio.positions.values())) == 0 and g.strategy_manager.status == 'working':
        if context.current_dt.month % 3 == 0:
            g.strategy_manager.ResetStrategy(context, select_random_symbol(g.stock_selector.check_stocks(context), g_random_index, g_symbol_count))
            g.strategy_manager.status == 'waiting'
        
    
    g.strategy_manager.HandleData(context)    
    if could_trade:
        g.strategy_manager.status = 'working'
        
    if could_trade:
        log.info('%s 大盘预测[多]' % datetime_to_string(context.current_dt))
    else:
        log.info('%s 大盘预测[空]' % datetime_to_string(context.current_dt))


# =============================================================================================
class EnumOrderType(enum.Enum):
    BuyLong = 1
    SellLong = 2
    BuyShort = 3
    SellShort = 4
    
class OrderInfo(object):
    def __init__(self):
        self.strategy_id = ''
        self.side = 'long'
        self.datetime = string_to_datetime('1990-01-01 00:00:00')
        self.amount = 0
        self.price = 0.0


class StrategyBase(object):
    def __init__(self, symbol, index):
        self.symbol = symbol
        self.strategy_index = index

        self.release_price = 0.0 # 发行价
        self.max_price = 0.0
        self.min_price = 10000000.0
        self.first_price = 0.0
        self.last_price = 0.0
        self.first_time = string_to_datetime('1990-01-01 00:00:00')
        self.last_time = string_to_datetime('1990-01-01 00:00:00')
        
        self.order = OrderInfo()
        self.yearly_profit = 0.0
        
        self.value = 0.0 # 股票总市值
        
    @staticmethod
    def GetValuation(symbol, context):
        stmt = query(valuation).filter(valuation.code == symbol)
        rslt = get_fundamentals(stmt, datetime_to_datestring(context.current_dt))
        
        value = 0.0
        if rslt is not None:
            value = rslt['market_cap'][0]
        
        return value

    @staticmethod
    def GetLastPrice(symbol, timeframe):
        vperiod = '1m'
        if (timeframe == 'day'):
            vperiod = '1d'

        #df = attribute_history(symbol, 1, vperiod, ['close'], fq='post')
        df = attribute_history(symbol, 1, vperiod, ['close'])
        if (df['close'] is None):
            return -1.0

        vclose = df['close'][-1]
        return vclose


    def HandleData(self, context):
        last_price = self.GetLastPrice(self.symbol, '1m')
        if math.isnan(last_price) or (last_price <= 0.0):
            return

        if (self.first_price == 0.0):
            self.first_price = last_price

        if (self.first_time == string_to_datetime('1990-01-01 00:00:00')):
            self.first_time = context.current_dt
            
        # TODO 查询太耗时，导致回测时间过长    
        #self.value = self.GetValuation(self.symbol, context)

        self.last_price = last_price
        self.last_time = context.current_dt


        self.max_price = max(self.max_price, self.last_price)
        self.min_price = min(self.min_price, self.last_price)
        if (self.release_price == 0.0):
            self.release_price = self.last_price

        profit = self.last_price / self.first_price
        years = (datetime_to_timestamp(self.last_time) - datetime_to_timestamp(self.first_time)) * 1.0 / (3600 * 24 * 365)
        if (years > 0.1 and profit > 0.0):
            self.yearly_profit = math.pow(profit, 1.0 / years) - 1.0
        
        
    def OpenOrder(self, context, balance_rate, order_side):
        if self.symbol in [position.security for position in list(context.portfolio.positions.values())]:
            return
        
        vbalance = context.portfolio.total_value
        available_cash = context.portfolio.available_cash
        if available_cash < vbalance * balance_rate:
            return
        
        amount = 0
        vorder = order_target_value(self.symbol, vbalance * balance_rate, side=order_side)
        if (vorder is not None and vorder.status == OrderStatus.done):
            write_log(g_log_path, '%s buy  order[%s %s %d] ok.' % (datetime_to_string(context.current_dt), self.symbol, order_side, amount))
            self.order.amount = amount
            self.order.datetime = context.current_dt
            self.order.price = self.last_price
        else:
            write_log(g_log_path, '%s buy  order[%s %s %d] error.' % (datetime_to_string(context.current_dt), self.symbol, order_side, amount))
            

    def CloseOrder(self, context):
        if self.symbol not in [position.security for position in list(context.portfolio.positions.values())]:
            return
        
        vorder = order_target_value(self.symbol, 0, side=self.order.side)
        if (vorder is not None and vorder.status == OrderStatus.done):
            write_log(g_log_path, '%s sell order[%s %s %d] ok.' % (datetime_to_string(context.current_dt), self.symbol, self.order.side, self.order.amount))
        else:
            write_log(g_log_path, '%s sell  order[%s %s %d] error.' % (datetime_to_string(context.current_dt), self.symbol, self.order.side, self.order.amount))      


class StrategyTurtle(StrategyBase):
    def __init__(self, symbol, index):
        super().__init__(symbol, index)
        self.security_info = get_security_info(symbol)
        
        
    def HandleData(self, context):
        super().HandleData(context)
        if (self.first_price <= 0.0):
            return
        
        
        could_trade = g.risk_control.could_trade_baodie or g.risk_control.could_trade_chaodi
        
        last_price = self.GetLastPrice(self.symbol, '1d')
        diff_years = (datetime.date(context.current_dt.year, context.current_dt.month, context.current_dt.day) - self.security_info.start_date).days / 365
        
        #could_trade_price = diff_years > 3 and last_price > 30 * pow(1.2, diff_years - 3)
        could_trade_price = last_price > 50 
        
        could_trade = could_trade and could_trade_price
        
        
        if (not(could_trade)):
            self.CloseOrder(context)
            return
        
        if could_trade:
            if self.CheckForChannel(context, '1d', 60, EnumOrderType.SellLong):
                self.CloseOrder(context)
                
            if self.CheckForChannel(context, '1d', 60, EnumOrderType.BuyLong):
                self.OpenOrder(context, g_balance_rate, 'long')
            elif g.risk_control.could_trade_chaodi:
                self.OpenOrder(context, g_balance_rate, 'long')
        #else:
        #    if self.CheckForChannel(context, '1d', 60, EnumOrderType.SellLong):
        #        self.CloseOrder(context)
                

    def CheckForChannel(self, context, timeframe, period, order_type):
        df = attribute_history(self.symbol, period + 1, timeframe, ['high', 'low', 'close'])
        if (df.shape[0] < period):
            return False

        close_list = df['close']
        if (math.isnan(close_list[0]) or math.isnan(close_list[-1])):
            return False
            
        vhigh = talib.MAX(df['high'], timeperiod=period)[-1]
        vlow = talib.MIN(df['low'], timeperiod=int(period/2))[-1]
        atr = talib.ATR(df['high'], df['low'], df['close'], timeperiod=period)[-1]
        
        channel_upper = vhigh - 2.00 * atr
        channel_lower = vlow  + 0.25 * atr
        
        diff_time = context.current_dt - self.order.datetime
        held_days = diff_time.days
        
        could_trade = False
        if (order_type == EnumOrderType.BuyLong):
            if (self.last_price > channel_upper):
                could_trade = True
                
        elif (order_type == EnumOrderType.SellLong):
            if self.order.price > 0.0:
                profit_rate = (self.last_price - self.order.price) / self.order.price
                loss_rate = (max(self.order.price, vhigh) - self.last_price) / self.order.price
    
                if (loss_rate > 0.15 and held_days > 30) or held_days > 90:       
                    could_trade = True

                
        return could_trade
        
class StrategyManager(object):
    def __init__(self):
        self.strategies = []
        self.status = 'waiting' # waiting working

     
    def ResetStrategy(self, context, strategies):
        self.strategies = []
        for i in range(len(strategies)):
            self.AddStrategy(context, StrategyTurtle(strategies[i], i))

       
    def AddStrategy(self, context, strategy):
        self.strategies.append(strategy)
        write_log(g_log_path, '%s add strategy[%s]' % (strategy.symbol, datetime_to_string(context.current_dt)))

      
    def HandleData(self, context):
        for strategy in self.strategies:
            strategy.HandleData(context)

class IndicatorInfo(object):
    def __init__(self, timeframe, period):
        self.timeframe = timeframe
        self.period = period
        
class RiskControl(object):
    def __init__(self):
        self.could_trade_baodie = False
        self.could_trade_chaodi = False
        
    def CheckForVelocity(self, symbol, period, velocity_min, velocity_max):
        hst = attribute_history(symbol, period, '1d', ['close'])
        close_list = hst['close']
        
        if (len(close_list) == 0):
            return False
        
        if (math.isnan(close_list[0]) or math.isnan(close_list[-1])):
            return False
        
        ma = talib.MA(close_list, timeperiod=period)[-1]
        velocity = (close_list[-1] - close_list[0]) / ma / period
        
        #record(vlc=(velocity-velocity_min)*100)
        return velocity_min <= velocity <= velocity_max
        
    def CheckForBenchmark(self, context, symbol):
        self.could_trade_baodie = self.CheckForVelocity(symbol, 5, -0.008, 0.10)  and check_for_rsi(symbol, '1d', 30, 47.5, 100)
        


class StockSelectorBase(object):
    def __init__(self):
        # 是否过滤停盘
        self.filter_paused = True
        # 是否过滤退市
        self.filter_delisted = True
        # 是否只有ST
        self.only_st = False
        # 是否过滤ST
        self.filter_st = True
        # 股票池
        #self.security_universe_index = ["399101.XSHE"]
        self.security_universe_index = ["000300.XSHG"]
        self.security_universe_user_securities = []
        # 行业列表
        self.industry_list = ["801010","801020","801030","801040","801050","801080","801110","801120","801130","801140","801150","801160","801170","801180","801200","801210","801230","801710","801720","801730","801740","801750","801760","801770","801780","801790","801880","801890"]
        # 去除银行行业
        self.industry_list = [industry for industry in self.industry_list if industry not in ['801190', '801780', '801790']]
        
        # 概念列表
        self.concept_list = []
        
        # 总排序准则： desc-降序、asc-升序
        self.check_out_lists_ascending = 'asc'
    
    ## 财务指标筛选函数
    def financial_statements_filter(self, context, security_list):
        security_list = financial_data_filter_xiaoyu(security_list, valuation.pe_ratio, 300)
    
        return security_list
        
    # 获取选股排序的 input_dict
    def get_check_stocks_sort_input_dict(self):
        input_dict = {
            valuation.circulating_market_cap:('asc',1),
            }
        return input_dict
        
    ## 排序
    def check_stocks_sort(self, context,security_list,input_dict,ascending='desc'):
        if (len(security_list) == 0) or (len(input_dict) == 0):
            return security_list
        else:
            # 生成 key 的 list
            idk = list(input_dict.keys())
            # 生成矩阵
            a = pd.DataFrame()
            for i in idk:
                b = get_sort_dataframe(security_list, i, input_dict[i])
                a = pd.concat([a,b],axis = 1)
            # 生成 score 列
            a['score'] = a.sum(1,False)
            # 根据 score 排序
            if ascending == 'asc':# 升序
                if hasattr(a, 'sort'):
                    a = a.sort(['score'],ascending = True)
                else:
                    a = a.sort_values(['score'],ascending = True)
            elif ascending == 'desc':# 降序
                if hasattr(a, 'sort'):
                    a = a.sort(['score'],ascending = False)
                else:
                    a = a.sort_values(['score'],ascending = False)
            # 返回结果
            return list(a.index)
    
    ## 过滤停牌股票
    def paused_filter(self, context, security_list):
        if self.filter_paused:
            current_data = get_current_data()
            security_list = [stock for stock in security_list if not current_data[stock].paused]
        # 返回结果
        return security_list
    
    ## 过滤退市股票
    def delisted_filter(self, context, security_list):
        if self.filter_delisted:
            current_data = get_current_data()
            security_list = [stock for stock in security_list if not (('退' in current_data[stock].name) or ('*' in current_data[stock].name))]
        # 返回结果
        return security_list
    
    
    ## 过滤ST股票
    def st_filter(self, context, security_list):
        if self.only_st:
            current_data = get_current_data()
            security_list = [stock for stock in security_list if current_data[stock].is_st]
        else:
            if self.filter_st:
                current_data = get_current_data()
                security_list = [stock for stock in security_list if not current_data[stock].is_st]
        # 返回结果
        return security_list
    
    # 过滤涨停股票
    def high_limit_filter(self, context, security_list):
        current_data = get_current_data()
        security_list = [stock for stock in security_list if not (current_data[stock].day_open >= current_data[stock].high_limit)]
        # 返回结果
        return security_list
    
    # 获取股票股票池
    def get_security_universe(self, context, security_universe_index, security_universe_user_securities):
        temp_index = []
        for s in security_universe_index:
            if s == 'all_a_securities':
                temp_index += list(get_all_securities(['stock'], context.current_dt.date()).index)
            else:
                temp_index += get_index_stocks(s)
        for x in security_universe_user_securities:
            temp_index += x
        return  sorted(list(set(temp_index)))
    
    # 行业过滤
    def industry_filter(self, context, security_list, industry_list):
        if len(industry_list) == 0:
            # 返回股票列表
            return security_list
        else:
            securities = []
            for s in industry_list:
                temp_securities = get_industry_stocks(s)
                securities += temp_securities
            security_list = [stock for stock in security_list if stock in securities]
            # 返回股票列表
            return security_list
    
    # 概念过滤
    def concept_filter(self, context, security_list, concept_list):
        if len(concept_list) == 0:
            return security_list
        else:
            securities = []
            for s in concept_list:
                temp_securities = get_concept_stocks(s)
                securities += temp_securities
            security_list = [stock for stock in security_list if stock in securities]
            # 返回股票列表
            return security_list
    
    
class StockSelector(StockSelectorBase):
    def __init__(self):
        super().__init__()
        
    def check_stocks(self, context):
        # 股票池赋值
        check_out_lists = self.get_security_universe(context, self.security_universe_index, self.security_universe_user_securities)
        # 行业过滤
        check_out_lists = self.industry_filter(context, check_out_lists, self.industry_list)
        # 概念过滤
        check_out_lists = self.concept_filter(context, check_out_lists, self.concept_list)
        # 过滤ST股票
        check_out_lists = self.st_filter(context, check_out_lists)
        # 过滤退市股票
        check_out_lists = self.delisted_filter(context, check_out_lists)
        # 财务筛选
        check_out_lists = self.financial_statements_filter(context, check_out_lists)
    
        # 排序
        input_dict = self.get_check_stocks_sort_input_dict()
        check_out_lists = self.check_stocks_sort(context, check_out_lists, input_dict, self.check_out_lists_ascending)
    
        return check_out_lists


# =============================================================================================
def check_for_rsi(symbol, timeframe, period, rsi_min, rsi_max):
    df = attribute_history(symbol, period + 1, timeframe, ['close'])
    close_list = [float(x) for x in df['close']]
    if (math.isnan(close_list[0]) or math.isnan(close_list[-1])):
        return False

    rsi = talib.RSI(np.array(close_list), timeperiod=period)[-1]
    #record(rsi=(rsi-rsi_min)/100*2)
    return (rsi_min < rsi < rsi_max)
    
def select_random_symbol(symbol_pool, idx, symbol_count):
    return symbol_pool[symbol_count*(idx-1):symbol_count*idx]

# =============================================================================================
# 公共函数，时间、日期转换
def datetime_to_string(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def datetime_to_datestring(dt):
    return dt.strftime("%Y-%m-%d")


def string_to_datetime(st):
    return datetime.datetime.strptime(st, "%Y-%m-%d %H:%M:%S")


def string_to_timestamp(st):
    return time.mktime(time.strptime(st, "%Y-%m-%d %H:%M:%S"))


def timestamp_to_string(sp):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(sp))


def datetime_to_timestamp(dt):
    return time.mktime(dt.timetuple())


def timestamp_to_struct(sp):
    return time.localtime(sp)


def timestamp_to_datetime(st):
    return string_to_datetime(timestamp_to_string(st))
    

# =============================================================================================    
def write_log(filename, text):
    write_file(filename, text + '\n', append=True)
    
def clear_log(filename):
    write_file(filename, '', append=False)
    
    
def write_log_xx(filename, text):
    log.info(text)


def value_to_amount(value, price):
    amount = round(value / price * 0.01) * 100
    return amount    
