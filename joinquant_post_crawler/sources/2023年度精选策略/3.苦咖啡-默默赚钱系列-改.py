# 克隆自聚宽文章：https://www.joinquant.com/post/31267
# 标题：苦咖啡-默默赚钱系列-改
# 作者：jqz1226

# 克隆自聚宽文章：https://www.joinquant.com/post/31232
# 标题：2020年 267%年化 13%回撤 上涨趋势策略修改版
# 作者：苦咖啡

# 克隆自聚宽文章：https://www.joinquant.com/post/30863
# 标题：上涨股策略2020年收益123%
# 作者：scottchenrui

from jqdata import *
import numpy as np
from scipy.stats import linregress


# 初始化函数，设定要操作的股票、基准等等
def initialize(context):
    # 设定基准
    set_benchmark('000300.XSHG')
    # True为开启动态复权模式，使用真实价格交易
    set_option('use_real_price', True)
    # 关闭提示
    log.set_level('order', 'error')

    # 最大建仓数量
    g.max_hold_stock_nums = 2
    # 选出来的股票
    g.target_lists = []

    # 运行函数
    run_weekly(check_stocks, 1, 'open')  # 选股
    run_weekly(trade, 1, 'open')  # 交易


# 股票筛选
def check_stocks(context):
    # type: (Context) -> None
    current_data = get_current_data()

    # 沪深300成分股
    check_out_lists = get_index_stocks("000300.XSHG", date=context.previous_date)

    # 未停牌、未涨跌停、非科创板
    check_out_lists = [stock for stock in check_out_lists if
                       (not current_data[stock].paused) and
                       (current_data[stock].low_limit < current_data[stock].day_open < current_data[
                           stock].high_limit) and
                       (not stock.startswith('688'))
                       ]

    # 昨收盘价不高于500元/股
    s_close_1 = history(1, '1d', 'close', check_out_lists).iloc[-1]
    check_out_lists = list(s_close_1[s_close_1 <= 500].index)

    # 近30个交易日的最高价 / 昨收盘价 <=1.1, 即HHV(HIGH,30)/C[-1] <= 1.1
    high_max_30 = history(30, '1d', 'high', check_out_lists).max()
    s_fall = high_max_30 / s_close_1
    check_out_lists = list(s_fall[s_fall <= 1.1].index)

    # 近7个交易日的交易量均值 与 近180给交易日的成交量均值 相比，放大不超过1.5倍  MA(VOL,7)/MA(VOL,180) <=1.5
    df_vol = history(180, '1d', 'volume', check_out_lists)
    s_vol_ratio = df_vol.iloc[-7:].mean() / df_vol.mean()
    check_out_lists = list(s_vol_ratio[s_vol_ratio <= 1.5].index)

    # 对近120个交易日的股价进行线性回归：入选条件 slope / intercept > 0.005 and r_value**2 > 0.8
    target_dict = {}
    x = np.arange(120)
    for stock in check_out_lists:
        y = attribute_history(stock, 120, '1d', 'close', df=False)['close']
        slope, intercept, r_value, p_value, std_err = linregress(x, y)
        if slope / intercept > 0.005 and r_value > 0.9:  #  
            target_dict[stock] = slope # r_value ** 2

    # 入选股票按照R Square 降序排序, 取前N名
    g.target_lists = []
    if target_dict:
        df_score = pd.DataFrame.from_dict(
            target_dict, orient='index', columns=['score', ]
        ).sort_values(
            by='score', ascending=False
        )
        #
        g.target_lists = list(df_score.index[:g.max_hold_stock_nums])


# 交易函数
def trade(context):
    # 获取 buy_lists 列表
    buy_lists = g.target_lists
    # 卖出操作
    for s in context.portfolio.positions:
        if s not in buy_lists:
            _order = order_target_value(s, 0)
            if _order is not None:
                log.info('卖出: %s (%s)' % (get_security_info(s).display_name, s))

    if buy_lists:
        amount = context.portfolio.total_value / len(buy_lists)
        for stock in buy_lists:
            if stock in context.portfolio.positions:
                _order = order_target_value(stock, amount)
                if _order is not None:
                    log.info('调仓: %s (%s)' % (get_security_info(stock).display_name, stock))

        for stock in buy_lists:
            if stock not in context.portfolio.positions:
                _order = order_target_value(stock, amount)
                if _order is not None:
                    log.info('买入: %s (%s)' % (get_security_info(stock).display_name, stock))
