# 克隆自聚宽文章：https://www.joinquant.com/post/39510
# 标题：近几年一直有效的股票BOLL择时策略
# 作者：勤奋的大海龟

# 导入函数库
from jqdata import *
from jqfactor import get_factor_values
from jqlib.technical_analysis import *
import urllib3

g.loss_price = {}
g.max_cash = 200000

# 初始化函数，设定基准等等
def initialize(context):
    run_type = context.run_params.type
    log.info('开始 {} 交易.'.format(run_type))
    set_benchmark('000002.XSHG')
    set_option('use_real_price', True) # 用真实价格交易
    set_option("avoid_future_data", True) # 打开防未来函数
    set_slippage(FixedSlippage(0)) # 将滑点设置为0
    # 设置交易成本万分之三
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.00012,\
                close_commission=0.0003, close_today_commission=0, min_commission=5),\
                type='fund')
    log.set_level('order', 'error') # 过滤order中低于error级别的日志
    g.strat_name = '' # 策略名称，用于保存持仓列表
    g.yesterday_list = []  # 上一交易日持仓
    g.stock_list = [] # 今天的持股
    g.limit_price = [1, 100] # 股价限制

    # 生成持仓列表 time='before_open'  9:00
    run_daily(before_market_open, time='8:30', reference_security='000300.XSHG')
    # 开始交易
    run_daily(market_open, time='9:35', reference_security='000300.XSHG')
    # 止损
    # run_daily(hold_check, time='13:01')


## 开盘前运行函数，获取股票列表
def before_market_open(context):
    all_stock = set()
    # BOLL
    s1_stocks = Boll399101Strat().get_stock_list(context)
    all_stock.update(filter_price_stocks(context, s1_stocks, 20))

    # 合并股票
    g.stock_list = list(all_stock)
    

'''
按股价过滤
'''
def filter_price_stocks(context, stock_list, limit_count):
    min_price, max_price = g.limit_price[0], g.limit_price[1]
    new_list = []
    cur_data = get_current_data()
    for stock in stock_list:
        cur_price = cur_data[stock].last_price
        if (cur_price > max_price and stock not in context.portfolio.positions) \
            or cur_price < min_price:
            log.info(stock, cur_price, '超出限价范围', g.limit_price)
            continue
        new_list.append(stock)
        if len(new_list) >= limit_count:
            break
    return new_list[:limit_count]


'''
持仓检查，盘中动态止损：早盘结束后，若60分钟周期跌破MA20均线则卖出 
'''
def hold_check(context):
    N = 20
    for stk in context.portfolio.positions:
        stk_dict = context.portfolio.positions[stk]
        if stk_dict.closeable_amount == 0:
            continue
        dt = attribute_history(stk,N+2,'60m',['close'])
        dt['man'] = dt.close/dt.close.rolling(N).mean()
        if dt.man[-1] >= 1.0:
            continue
        log.info("盘中止损，卖出：{}".format(stk))
        close_position(stk_dict)


'''
开盘前确定今天持仓
'''
def market_open(context):
    print('入选股票:{}'.format(g.stock_list))
    adjust_position(context, g.stock_list)

'''
开仓买入
'''
def open_position(security, value):
    order = order_target_value_(security, value)
    if order != None and order.filled > 0:
        return True
    return False

'''
平仓卖出
'''
def close_position(position):
    security = position.security
    order = order_target_value_(security, 0)  # 可能会因停牌失败
    if order != None:
        if order.status == OrderStatus.held and order.filled == order.amount:
            return True
    return False
    
def get_pos_amount(context,stock):
    if stock in context.portfolio.positions:
        return context.portfolio.positions[stock].total_amount
    return 0

'''
调整仓位
'''
def adjust_position(context, buy_stocks):
    # 清仓不在的股票
    for stock in context.portfolio.positions:
        if stock not in buy_stocks:
            position = context.portfolio.positions[stock]
            close_position(position)
    # 平均分配资金
    position_count = len(context.portfolio.positions)
    if len(buy_stocks) <= position_count:
        return
    
    # 计算每股买多少钱
    value = int(context.portfolio.cash / (len(buy_stocks) - position_count))
    value = min(value, g.max_cash)
    value = int(int(value / 100) * 100) # 按100取整
    for stock in buy_stocks:
        # 已有持仓不买
        if get_pos_amount(context, stock) != 0:
            continue
        data = attribute_history(stock, 1, '1m', ['close']).close
        if value / data[0] < 110:
            continue
        
        open_position(stock, value)
        if len(context.portfolio.positions) >= len(buy_stocks):
            break

'''
下单交易
'''
def order_target_value_(security, value):
    if value == 0:
        log.debug("卖出 %s" % (security))
    else:
        log.debug("调整 %s 市值到 %f" % (security, value))
    # 如果股票停牌，创建报单会失败，order_target_value 返回None
    # 如果股票涨跌停，创建报单会成功，order_target_value 返回Order，但是报单会取消
    # 部成部撤的报单，聚宽状态是已撤，此时成交量>0，可通过成交量判断是否有成交
    return order_target_value(security, value)

'''
收盘后运行函数
'''
def after_market_close(context):
    log.info(str('收盘后:'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    log.info('一天结束')

'''
策略选择基类
'''
from typing import overload
class StratBase:
    # 获取今日持仓列表
    @overload
    def get_stock_list(self, context):
        pass
	    
    #过滤停牌股票
    def filter_paused_stock(self, stock_list):
        current_data = get_current_data()
        return [stock for stock in stock_list if not current_data[stock].paused]

    #过滤ST及其他具有退市标签的股票
    def filter_st_stock(self, stock_list):
        current_data = get_current_data()
        return [stock for stock in stock_list
                if not current_data[stock].is_st
                and 'ST' not in current_data[stock].name
                and '*' not in current_data[stock].name
                and '退' not in current_data[stock].name]
    
    #过滤涨停的股票
    def filter_limitup_stock(self, context, stock_list):
        last_prices = history(1, unit='1m', field='close', security_list=stock_list)
        current_data = get_current_data()
        # 已存在于持仓的股票即使涨停也不过滤，避免此股票再次可买，但因被过滤而导致选择别的股票
        return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
                or last_prices[stock][-1] < current_data[stock].high_limit]
    
    #过滤跌停的股票
    def filter_limitdown_stock(self, context, stock_list):
        last_prices = history(1, unit='1m', field='close', security_list=stock_list)
        current_data = get_current_data()
        return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
                or last_prices[stock][-1] > current_data[stock].low_limit]
    
    #过滤科创板
    def filter_kcb_stock(self, context, stock_list):
        return [stock for stock in stock_list  if stock[0:3] != '688']
    
    #过滤次新股
    def filter_new_stock(self, context,stock_list):
        yesterday = context.previous_date
        return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=250)]

    # 因子数据获取
    def get_factor_filter_list(self, context,stock_list, jqfactor, sort, p):
        yesterday = context.previous_date
        score_list = get_factor_values(stock_list, jqfactor, \
                end_date=yesterday, count=1)[jqfactor].iloc[0].tolist()
        df = pd.DataFrame(columns=['code','score'])
        df['code'] = stock_list
        df['score'] = score_list
        df = df.dropna()
        df = df[df['score']>0]
        df.sort_values(by='score', ascending=sort, inplace=True)
        filter_list = list(df.code)[0:int(p*len(stock_list))]
        return filter_list


class Boll399101Strat(StratBase):
    N = 20
    def get_stock_list(self, context):
        # stock_pool = ['002322.XSHE']
        stock_pool = get_index_stocks("399101.XSHE") # 000300.XSHG 399101.XSHE
        q = query(valuation.code).filter(valuation.code.in_(stock_pool)
        ).order_by(valuation.circulating_market_cap.asc()
        ).limit(50)
        stock_pool = list(get_fundamentals(q).code)
        
        final_list = []
        # 取数据，计算BOLL
        for stock in stock_pool:
            data = attribute_history(stock, self.N+5, '1d', ['close']).close
            yestClose = data[-1]
            yestClose2 = data[-2]
            yestClose3 = data[-3]
            meandelta = data.mean()
            prev_low = data[-10:-2].min()
            stddelta = data.rolling(self.N).std()
            stddev = stddelta[-1]
            upperbound = meandelta + stddev * 2
            lowerbound = meandelta - stddev * 2
            
            if get_pos_amount(context, stock) > 0:
                final_list.append(stock)
                # 止损止盈利
                # lossPrice = context.portfolio.positions[stock].avg_cost * 0.9
                lossPrice = g.loss_price[stock]
                if yestClose < lossPrice:
                    final_list.remove(stock)
                elif (yestClose2 > upperbound or yestClose3 > upperbound) and yestClose < min(yestClose2,yestClose3):
                    final_list.remove(stock)
                    
            elif yestClose2 < lowerbound and yestClose > yestClose2 and yestClose > prev_low:
                final_list.append(stock)
                g.loss_price[stock] = prev_low

        return final_list

'''
黄金分割线
'''
