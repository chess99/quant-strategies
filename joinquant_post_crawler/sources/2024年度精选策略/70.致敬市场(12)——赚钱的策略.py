# 克隆自聚宽文章：https://www.joinquant.com/post/41444
# 标题：致敬市场(12)——赚钱的策略
# 作者：Gyro^.^

# 分红养家
def initialize(context):
    log.set_level('order', 'error') # 信息过滤
    set_option('use_real_price', True)  #使用真实价格
    set_option('avoid_future_data', True) # 避免未来数据
    run_daily(iUpdate, time='10:00') # 更新

def iUpdate(context):
    # 参数
    index = '399310.XSHE' # 国证50
    n = 50 # 50只股票
    rente_ratio = 0.05 # 年金利率，5%
    cash_ratio = 2*rente_ratio # 现金储备率
    treasury_ratio = 0.4 # 债券仓位，40%
    treasury_fund = '000012.XSHG' # 债券基金，国债指数
    cur_data = get_current_data()
    # 每年第一天分红，再平衡
    if context.current_dt.year > context.previous_date.year:
        # 分红额度
        rente = int(rente_ratio * context.portfolio.total_value)
        # 分红
        log.info('!!!分红+++', rente, int(context.portfolio.available_cash))
        inout_cash(-rente)
        # 再平衡
        if not cur_data[treasury_fund].paused:
            treasury_size = treasury_ratio * context.portfolio.total_value
            log.info('再平衡', treasury_fund)
            order_target_value(treasury_fund, treasury_size)
    # 股票池
    stocks = get_index_stocks(index)
    # 卖出
    for s in context.portfolio.positions:
        if s not in stocks and\
            not cur_data[s].paused:
            log.info('sell', s, cur_data[s].name)
            order_target(s, 0)
    # 买进
    cash_size = cash_ratio * context.portfolio.total_value
    position_size = (1.0 - cash_ratio - treasury_ratio)/n * context.portfolio.total_value
    for s in stocks:
        if  context.portfolio.available_cash < cash_size:
            break # 现金不够，不买
        if s not in context.portfolio.positions and\
            not cur_data[s].paused:
            log.info('buy', s, cur_data[s].name)
            order_value(s, position_size)
    # 记录净值，万元
    record(NetValue = context.portfolio.total_value/10000)
# end
