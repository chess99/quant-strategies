# 克隆自聚宽文章：https://www.joinquant.com/post/37611
# 标题：致敬经典作品——小兵哥《一致性风险度量》——极速版
# 作者：jqz1226

# 克隆自聚宽文章：https://www.joinquant.com/post/2116
# 标题：一致性风险度量（桥水全天候为例）
# 作者：小兵哥

import datetime as dt
import math
from jqdata import *
# from kuanke.user_space_api import *


def initialize(context):
    set_benchmark('511010.XSHG')
    set_option('use_real_price', True)
    # 关闭部分log
    log.set_level('order', 'error')
    set_slippage(FixedSlippage(0.002))
    # 交易记录，
    g.transactionRecord, g.trade_ratio, g.positions = {}, {}, {}
    g.hold_periods, g.hold_cycle = 0, 30

    g.QuantLib = QuantLib()

    # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
    # 开盘时运行
    run_daily(market_open, time='open', reference_security='000300.XSHG')
    # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')


# initialize parameters
def fun_initialize(context):
    """
    因为模拟交易时，会保留参数历史赋值，重新赋值需改名。
    为了避免参数变更后在模拟交易里不生效，单独赋值一次，
    需保留状态的参数，不能放此函数内
    """

    # g.equity = ['510300.XSHG','510500.XSHG','159915.XSHE','510050.XSHG']
    g.equity = ['510300.XSHG']
    # g.commodities = ['160216.XSHE','518880.XSHG','162411.XSHE']
    g.commodities = ['518880.XSHG']
    # g.bonds = ['511010.XSHG','511220.XSHG']
    g.bonds = ['511010.XSHG']
    # g.money_fund = ['513100.XSHG','513500.XSHG']
    g.money_fund = ['513100.XSHG']

    g.confidence_level = 2.58

    # 上市不足 60 天的剔除掉
    # g.equity = g.QuantLib.fun_delNewShare(context, g.equity, 60)
    # g.commodities = g.QuantLib.fun_delNewShare(context, g.commodities, 60)
    # g.bonds = g.QuantLib.fun_delNewShare(context, g.bonds, 60)
    # g.money_fund = g.QuantLib.fun_delNewShare(context, g.money_fund, 60)

    g.pools = g.equity + g.commodities + g.bonds + g.money_fund

    # 统计交易资料
    for stock in g.pools:
        if stock not in g.transactionRecord:
            g.QuantLib.fun_createTransactionRecord(context, stock)


def before_market_open(context):
    # 初始化参数
    fun_initialize(context)

    # 此段代码仅用于发微信，可以跳过
    g.message = ""
    g.message += "Returns（盘前）：" + str(round(context.portfolio.returns, 5) * 100) + "%\n"
    g.hold = {}
    for stock in g.pools:
        if stock in context.portfolio.positions:
            g.hold[stock] = context.portfolio.positions[stock].total_amount
        else:
            g.hold[stock] = 0


def after_market_close(context):
    # 此段代码仅用于发微信，可以跳过
    message = ""
    for stock in g.pools:
        beforeAmount = g.hold[stock]
        if stock in context.portfolio.positions:
            afterAmount = context.portfolio.positions[stock].total_amount
        else:
            afterAmount = 0
        #
        if beforeAmount == afterAmount:
            message += stock + " : " + str(afterAmount) + "\n"
        elif beforeAmount < afterAmount:
            message += stock + " : " + str(afterAmount) + "(+" + str(afterAmount - beforeAmount) + ")\n"
        else:
            message += stock + " : " + str(afterAmount) + "(" + str(afterAmount - beforeAmount) + ")\n"

    message += "Returns（盘后）：" + str(round(context.portfolio.returns, 5) * 100) + "%"
    g.message += message

    g.message += g.QuantLib.fun_print_transactionRecord(context)
    # send_message(g.message)
    log.info(g.message)


def market_open(context):
    g.tradeRecord = ""

    if g.hold_periods == 0 or need_rebalance(context):
        rebalance(context)
        g.hold_periods = g.hold_cycle
    else:
        g.tradeRecord = ""
        g.hold_periods -= 1

    #
    fun_trade(context, g.trade_ratio)

    if g.tradeRecord != "":  # 如果打印记录不为空，则发微信
        message = "\n 今日调仓 \n"
        message += g.tradeRecord
        # send_message(message)
        log.info(message)


def rebalance(context):
    # type: (Context) -> NoReturn
    trade_ratio = fun_calc_trade_ratio(context)

    g.trade_ratio = trade_ratio

    for stock in trade_ratio:
        if stock in context.portfolio.positions:
            g.positions[stock] = context.portfolio.positions[stock].price
        else:
            g.positions[stock] = 0.0


def fun_calc_trade_ratio(context):
    # type: (Context) -> dict
    # def __fun_calc_stockWeight(stock_list):
    #     __ratio = {}
    #     for stock in stock_list:
    #         __ratio[stock] = 1 / len(stock_list)
    # 
    #     return __ratio

    def __fun_getdailyreturn(stock, freq, lag):
        # type: (str, str, int) -> np.ndarray
        hStocks = history(lag, freq, 'close', stock, df=True)
        # daily_returns = hStocks.resample('D', how='last').pct_change().fillna(value=0, method=None, axis=0).values
        daily_returns = hStocks.resample('D').last().pct_change().fillna(value=0, method=None, axis=0).iloc[:, 0].values
        return daily_returns

    def __fun_get_portfolio_ES(ratio, freq, lag, confidence_level):
        # type: (dict, str, int, float) -> float
        if confidence_level == 1.96:
            a = (1 - 0.95)
        elif confidence_level == 2.06:
            a = (1 - 0.96)
        elif confidence_level == 2.18:
            a = (1 - 0.97)
        elif confidence_level == 2.34:
            a = (1 - 0.98)
        elif confidence_level == 2.58:
            a = (1 - 0.99)
        elif confidence_level == 5:
            a = (1 - 0.99999)
        else:
            a = (1 - 0.95)

        ES = 0
        if ratio:
            daily_returns = __fun_getdailyreturn(list(ratio.keys())[0], freq, lag)
            dailyReturns_sort = sorted(daily_returns)

            count = 0
            sum_value = 0
            for i in range(len(dailyReturns_sort)):
                if i < (lag * a):
                    sum_value += dailyReturns_sort[i]
                    count += 1
            if count == 0:
                ES = 0
            else:
                ES = -(sum_value / (lag * a))

        return ES

    # def __fun_calc_stock_risk_VaR(stock_list):
    #     __portfolio_VaR = 0
    #     # __stock_ratio = g.QuantLib.fun_calc_stockWeight(stock_list)
    #     __stock_ratio = {}
    #     if stock_list:
    #         __stock_ratio[stock_list[0]] = 1
    #         daily_returns = __fun_getdailyreturn(stock_list[0], '1d', 120)
    #         __portfolio_VaR = 1 * g.confidence_level * np.std(daily_returns)
    # 
    #         if math.isnan(__portfolio_VaR):
    #             __portfolio_VaR = 0
    # 
    #     return __portfolio_VaR, __stock_ratio

    def __fun_calc_stock_risk_ES(stock_list):
        # type: (list) -> (float, dict)
        __stock_ratio = {}
        if stock_list:
            __stock_ratio[stock_list[0]] = 1

        __portfolio_ES = __fun_get_portfolio_ES(__stock_ratio, '1d', 120, g.confidence_level)
        if math.isnan(__portfolio_ES):
            __portfolio_ES = 0

        return __portfolio_ES, __stock_ratio

    def __fun_calc_trade_ratio(trade_ratio, stock_list, __equity_ratio, position, all_position):
        # type: (dict, list, dict, float, float) -> dict
        for stock in stock_list:
            if stock in trade_ratio:
                trade_ratio[stock] += round((__equity_ratio[stock] * position / all_position), 3)
            else:
                trade_ratio[stock] = round((__equity_ratio[stock] * position / all_position), 3)
        return trade_ratio

    equity_ES, equity_ratio = __fun_calc_stock_risk_ES(g.equity)
    commodities_ES, commodities_ratio = __fun_calc_stock_risk_ES(g.commodities)
    bonds_ES, bonds_ratio = __fun_calc_stock_risk_ES(g.bonds)
    money_fund_ES, money_fund_ratio = __fun_calc_stock_risk_ES(g.money_fund)

    max_ES = max(equity_ES, commodities_ES, bonds_ES, money_fund_ES)

    equity_position, commodities_position, bonds_position, money_fund_position = 0, 0, 0, 0
    if equity_ES:
        equity_position = max_ES / equity_ES
    if commodities_ES:
        commodities_position = max_ES / commodities_ES
    if bonds_ES:
        bonds_position = max_ES / bonds_ES
    if money_fund_ES:
        money_fund_position = max_ES / money_fund_ES

    total_position = equity_position + commodities_position + bonds_position + money_fund_position

    __ratio = {}

    __ratio = __fun_calc_trade_ratio(__ratio, g.equity, equity_ratio, equity_position, total_position)
    __ratio = __fun_calc_trade_ratio(__ratio, g.commodities, commodities_ratio, commodities_position, total_position)
    __ratio = __fun_calc_trade_ratio(__ratio, g.bonds, bonds_ratio, bonds_position, total_position)
    __ratio = __fun_calc_trade_ratio(__ratio, g.money_fund, money_fund_ratio, money_fund_position, total_position)

    log.info('仓位:%s' % __ratio)
    return __ratio


def fun_trade(context, buyDict):
    # type: (Context, dict) -> NoReturn
    def __fun_tradeStock(_context, _stock, ratio):
        # type: (Context, str, float) -> NoReturn
        total_value = _context.portfolio.total_value
        if _stock in g.money_fund:
            g.QuantLib.fun_tradeBond(_context, _stock, total_value * ratio)
        else:
            curPrice = history(1, '1d', 'close', _stock, df=False)[_stock][-1]
            if _stock in context.portfolio.positions:
                curValue = _context.portfolio.positions[_stock].total_amount * curPrice
            else:
                curValue = 0.0
            #
            Quota = total_value * ratio
            deltaValue = abs(Quota - curValue)
            if deltaValue / Quota >= 0.25 and deltaValue > 1000:
                if Quota > curValue:
                    avg_cost = g.transactionRecord[_stock]['avg_cost']
                    if curPrice > avg_cost:  # 如果亏损，不加仓
                        cash = _context.portfolio.available_cash
                        if cash >= Quota * 0.25:
                            g.QuantLib.fun_trade(_context, _stock, Quota)
                else:
                    g.QuantLib.fun_trade(_context, _stock, Quota)

    buy_list = list(buyDict.keys())

    my_hold_stock = list(context.portfolio.positions.keys())
    portfolioValue = context.portfolio.total_value

    # 已有仓位
    holdDict = dict()
    if my_hold_stock:
        h_hold_stocks = history(1, '1d', 'close', my_hold_stock, df=False)
        for stock in my_hold_stock:
            tmpW = round((context.portfolio.positions[stock].total_amount * h_hold_stocks[stock][0]) / portfolioValue, 2)
            holdDict[stock] = float(tmpW)

    # 对已有仓位做排序
    tmpDict = {}
    for stock in holdDict:
        if stock in buyDict:
            tmpDict[stock] = round((buyDict[stock] - holdDict[stock]), 2)
    tradeOrder = sorted(tmpDict.items(), key=lambda d: d[1], reverse=False)

    # 先卖掉持仓减少的标的
    _tmplist = []
    for idx in tradeOrder:
        stock = idx[0]
        __fun_tradeStock(context, stock, buyDict[stock])
        _tmplist.append(stock)

    # 交易其他股票
    for i in range(len(buy_list)):
        stock = buy_list[i]
        if len(_tmplist) != 0:
            if stock not in _tmplist:
                __fun_tradeStock(context, stock, buyDict[stock])
        else:
            __fun_tradeStock(context, stock, buyDict[stock])


def need_rebalance(context):
    # type: (Context) -> bool
    """
    持仓中，有资产价格变化幅度超过15%，就需要重新balance
    """
    for stock in context.portfolio.positions:
        curPrice = context.portfolio.positions[stock].price
        oldPrice = g.positions[stock]
        if oldPrice != 0:
            if abs(curPrice - oldPrice) / oldPrice > 0.15:
                return True


class QuantLib(object):

    def __init__(self, _period='1d'):
        """
        周期 period  （支持’Xd’,’Xm’, X是一个正整数）
        """

        # self.period = _period

        # self.context = None
        # self.data = None
        pass

    def fun_tradeBond(self, context, stock, Value):
        # type: (Context, str, float) -> NoReturn
        curPrice = history(1, '1d', 'close', stock, df=False)[stock][-1]
        if stock in context.portfolio.positions:
            curValue = float(context.portfolio.positions[stock].total_amount * curPrice)
        else:
            curValue = 0.0
        #
        deltaValue = abs(Value - curValue)
        if deltaValue > (curPrice * 100):
            if Value > curValue:
                cash = context.portfolio.available_cash
                if cash > (curPrice * 100):
                    self.fun_trade(context, stock, Value)
            else:
                # 如果是银华日利，多卖 100 股，避免个股买少了
                if stock == '511880.XSHG':
                    Value -= curPrice * 100
                self.fun_trade(context, stock, Value)

    # 剔除上市时间较短的产品
    def fun_delNewShare(self, context, equity, delta_day):
        # type: (Context, list, int) -> list
        deltaDate = context.current_dt.date() - dt.timedelta(delta_day)

        tmpList = []
        for stock in equity:
            if get_security_info(stock).start_date < deltaDate:
                tmpList.append(stock)

        return tmpList

    def fun_trade(self, context, stock, value):
        # type: (Context, str, float) -> NoReturn
        g.tradeRecord += stock + " 调仓到 " + str(round(value, 2)) + "\n"
        # self.fun_setCommission(context, stock)
        order_target_value(stock, value)
        self.fun_record(context, stock)

    # def fun_setCommission(self, context, stock):
    #     if stock in g.equity or stock in g.commodities:
    #         set_commission(PerTrade(buy_cost=0.0003, sell_cost=0.0003, min_cost=5))
    #     elif (stock in g.money_fund) or (stock in g.bonds):
    #         set_commission(PerTrade(buy_cost=0.0000, sell_cost=0.0000, min_cost=0))
    #     else:
    #         set_commission(PerTrade(buy_cost=0.0003, sell_cost=0.0013, min_cost=5))

    def fun_record(self, context, stock):
        # type: (Context, str) -> NoReturn
        tmpDict = g.transactionRecord.copy()
        # myPrice = history(1, '1d', 'close', stock, df=False)[stock]
        myPrice = context.portfolio.positions[stock].price
        newAmount = context.portfolio.positions[stock].total_amount
        #
        myAmount = tmpDict[stock]['amount']
        myAvg_cost = tmpDict[stock]['avg_cost']
        if myAmount != newAmount:
            # 买入
            if myAmount <= newAmount:
                myAvg_cost = ((myAvg_cost * myAmount) + myPrice * (newAmount - myAmount)) / newAmount
                # g.positions[stock] = context.portfolio.positions[stock].price
                tmpDict[stock]['buy_times'] += 1
            # 卖光
            elif newAmount == 0:
                if myPrice >= myAvg_cost:
                    tmpDict[stock]['win'] += 1
                else:
                    tmpDict[stock]['loss'] += 1
                myMargin = (myPrice - myAvg_cost) * myAmount
                if myMargin < 0:
                    if myMargin <= tmpDict[stock]['max_loss']:
                        tmpDict[stock]['max_loss'] = float(round(myMargin, 2))
                        tmpDict[stock]['max_loss_date'] = context.current_dt

                tmpDict[stock]['Margin'] += float(round(myMargin, 2))
                tmpDict[stock]['sell_times'] += 1
            # 没卖光
            elif myAmount > newAmount:
                myAvg_cost = ((myAvg_cost * myAmount) - (myPrice * (myAmount - newAmount))) / newAmount
                # g.positions[stock] = context.portfolio.positions[stock].price
                tmpDict[stock]['sell_times'] += 1

        g.tradeRecord += stock + " 持股从 " + str(myAmount) + " 变为 " + str(newAmount) + \
                         " 占比 " + str(
            100 * round((myPrice * newAmount) / context.portfolio.total_value, 2)) + "%\n"

        # renew after trade
        if newAmount == 0:
            myAvg_cost = 0
            tmpDict[stock]['standPrice'] = 0
        elif myAvg_cost > tmpDict[stock]['standPrice']:
            tmpDict[stock]['standPrice'] = float(myAvg_cost)

        myAmount = newAmount
        tmpDict[stock]['amount'] = float(myAmount)
        tmpDict[stock]['avg_cost'] = float(myAvg_cost)
        g.transactionRecord = tmpDict.copy()

    def fun_createTransactionRecord(self, context, stock):
        # type: (Context, str) -> NoReturn
        g.transactionRecord[stock] = {'amount': 0, 'avg_cost': 0, 'buy_times': 0,
                                      'sell_times': 0, 'win': 0, 'loss': 0, 'max_loss': 0, 'max_loss_date': 0,
                                      'Margin': 0,
                                      'standPrice': 0}

    def fun_print_transactionRecord(self, context):
        # type: (Context) -> str
        tmpDict = g.transactionRecord.copy()
        tmpList = list(tmpDict.keys())
        message = "\n" + "stock, Win, loss, buy_times, sell_times, Margin, max_loss, max_loss_date, avg_cost\n"
        for stock in tmpList:
            message += stock + ", "
            message += str(tmpDict[stock]['win']) + ", " + str(tmpDict[stock]['loss']) + " , "
            message += str(tmpDict[stock]['buy_times']) + ", " + str(tmpDict[stock]['sell_times']) + ", "
            message += str(tmpDict[stock]['Margin']) + ", "
            message += str(tmpDict[stock]['max_loss']) + ", " + str(tmpDict[stock]['max_loss_date']) + ", "
            message += str(tmpDict[stock]['avg_cost']) + "\n"
        message += "Returns = " + str(round(context.portfolio.returns, 5) * 100) + "%\n"

        g.transactionRecord = tmpDict.copy()

        return message
