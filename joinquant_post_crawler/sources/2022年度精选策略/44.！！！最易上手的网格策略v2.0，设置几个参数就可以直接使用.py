# 克隆自聚宽文章：https://www.joinquant.com/post/36074
# 标题：！！！最易上手的网格策略v2.0，设置几个参数就可以直接使用
# 作者：xfera16

# 导入函数库
from jqdata import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    
    # 开启避免未来数据模式
    set_option("avoid_future_data", True)
    
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    
    # 关闭缓存
    # disable_cache()

    #############################################################################
    #根据自己的想发修改参数！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！
    #############################################################################
    # 设置交易的基金（最好就是一支，规模要大以免回测的成交量超过基金的成交量）
    g.ETF = ['510500.XSHG']
    
    # 设置网格大小
    g.net_range = 0.05
    
    # 设置每一个网格投资金额
    g.per_share = 20000
    
    # 判断第一次买入时参考的过去天数，和上下限
    # 即会自动计算该基金过去g.days日均值（ma(g.days)，如果当前价格在（ma(g.days)-g.down, ma(g.days)+g.up)范围内
    # 那么就作为第一次建仓时的基准价格买入，之后网格的涨跌就参考这个价格
    # 如果不明白什么意思，这里也可以不用改，仅仅是影响初始买入价格，但是这里设置的是大体上在历史均值附近第一次建仓，所以影响不大。
    g.days = 60
    g.down = 0.2
    g.up = 0.2
    
    #############################################################################
    #这后面都不用改！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！！
    #############################################################################
    # 用来记录网格情况,当前处于第几个网格
    g.net = {}
    
    # 记录第一个网格的买入价格
    g.base_price = {}
    
    # 记录每一层网格的买入份数
    g.buy_amount = {}
    
    # 计算最大层数
    g.max_net = int(context.portfolio.available_cash/g.per_share)
        
    # 在每日收盘后，获取现有持仓的成本
    run_daily(cal_avg, '15:30')    
        
    # 每天开盘检查是否有分红或者拆分的情况，并设置调整比例
    run_daily(run_check, '9:30')
    
    # 根据检查是否有分红或者拆分的情况，根据比例调整数据
    run_daily(run_adj, '9:30')
    

# 在每日收盘后，获取现有持仓的成本
def cal_avg(context):
    g.pre_date_avg = {}
    for _, fund in context.portfolio.positions.items():
            # 记录今日收盘的成本，用于明日开盘比较
            g.pre_date_avg[fund.security] =  fund.avg_cost
    log.info(g.pre_date_avg)        
    log.info(g.net)   

# 每天开盘检查是否有分红或者拆分的情况，并设置调整比例
def run_check(context):
    # 设置调整比例（当出现分红或者拆分的时候调整网格的基准）
    g.adj_rate = {}    
    for _, fund in context.portfolio.positions.items():
            if g.pre_date_avg[fund.security] == fund.avg_cost:
                g.adj_rate[fund.security] = 1
            else:
                g.adj_rate[fund.security] = fund.avg_cost/g.pre_date_avg[fund.security]
    log.info(g.adj_rate)       
    
# 根据检查是否有分红或者拆分的情况，根据比例调整数据
def run_adj(context):
    for _, fund in context.portfolio.positions.items():
        g.base_price[fund.security] = g.base_price[fund.security] * g.adj_rate[fund.security]
    
# 每分钟运行
def handle_data(context, data):
    
    # 如果g.ETF中存在为买入的基金，那么获取该基金的过去g.days价格
    # log.info(len(context.portfolio.positions))
    # log.info(len(g.ETF))
    if len(g.net) != len(g.ETF):
        etf_pri = {}
        etf_list = g.ETF[:]
        for etf in g.ETF:
            if etf in g.net:
                etf_list.remove(etf)
        
        
        # 获得过去g.days天该基金的均值
        for etf in etf_list:
            avg_pri = get_bars(etf, count=g.days, unit='1d', fields=['close'])['close'].mean()
            etf_pri[etf] = round(avg_pri, 2)
        log.info("当前备选基金的过去%s日平均价格为：" % (g.days))
        log.info(etf_pri)
        
    # 循环遍历备选ETF列表，进行操作    
    for etf in g.ETF: 
        if etf not in g.net:
            log.info("etf:%s" % (etf))
            base_pri = etf_pri[etf]
            
            cur_pri = get_price(etf, start_date=context.current_dt, end_date=context.current_dt, 
                                    frequency='1m', fields='close', skip_paused=False, fq='pre')
            if cur_pri.empty:
                continue
            cur_pri = cur_pri.close[0]
            log.info("%s的当前价格为:%s, 上下限为:(%s, %s)" % (etf, cur_pri, str(round((1-g.down) * base_pri, 2)), str(round((1+g.up) * base_pri, 2))))
            
            # 当前价格如果大于基础价格的上下限，那么就买入第一份
            
            if cur_pri > (1-g.down) * base_pri and cur_pri < (1+g.up) * base_pri:
                order_res = order_value(etf, g.per_share)
                log.info("%s的当前价格为:%s, 符合第一次买入的条件，买入%s股" % (etf, cur_pri, order_res.filled))
                if order_res and str(order_res.status) in ['held', 'filled']:
                    # log.info("第一次买入" + etf + ": " )
                    # log.info("总额：%s元，数量：%s份，单价：%s元" % (round(order_res.price*order_res.filled, 2), round(order_res.filled, 2), round(order_res.price, 2)))
                    # 记录当前网格
                    g.net[etf] = 1
                    g.base_price[etf] = order_res.price
                    g.buy_amount[etf] = []
                    # g.buy_amount[etf].append(order_res.filled * order_res.price)
                    g.buy_amount[etf].append(order_res.filled * order_res.price)
                    # log.info("当前持有的基金的买入层数为：")
                    # log.info(g.net)    
                    # log.info("每一层的成交金额为")
                    # log.info(g.buy_amount)  
        else:
            # if (context.current_dt.month == 7 and context.current_dt.day == 19) or (context.current_dt.month == 7 and context.current_dt.day == 20):
            #     continue
            cur_pri = get_price(etf, start_date=context.current_dt, end_date=context.current_dt, 
                                    frequency='1m', fields='close', skip_paused=False, fq='pre')
            if cur_pri.empty:
                continue
            cur_pri = cur_pri.close[0]
            
            # 获取当前网格层数
            net_layer = g.net[etf]
            #获取当前基金的买入基准价格
            buy_base_pri = g.base_price[etf]
            if cur_pri > buy_base_pri * ( 1 - net_layer * g.net_range + 0.1):
                if g.net[etf] == 1:
                    log.info(context.portfolio.positions)
                    order_res = order_target(etf, 0)
                    # log.info("当前处于第%s层，  %s的当前价格为:%s" % (g.net[etf], etf, cur_pri))
                    # log.info("buy_base_pri：%s" % (buy_base_pri))
                    # log.info("本层卖出条件为：%s" % (buy_base_pri * ( 1 - net_layer * g.net_range + 0.1)))
                    # log.info("当前价格和buy_base_pri比为%s" % ((cur_pri/buy_base_pri-1)*100))
                    # log.info("符合卖出的条件，由于在第一层，全部卖出，卖出%s股" % (order_res.filled))
                    log.info('订单状态：')
                    log.info(order_res)
                    log.info(context.portfolio.positions)
                    if order_res and str(order_res.status) in ['held', 'filled']:
                        # log.info("第%s层卖出" % (net_layer) + etf + ": ")
                        # log.info("总额：%s元，数量：%s份，单价：%s元" % (round(order_res.price*order_res.filled, 2), round(order_res.filled, 2), round(order_res.price, 2))) 
                        g.buy_amount[etf].pop()
                        g.net[etf] = g.net[etf] - 1
                        if g.net[etf] == 0:
                            del g.net[etf]
                            del g.buy_amount[etf]
                        # log.info("当前持有的基金的买入层数为：")
                        # log.info(g.net)    
                        # log.info("每一层的成交金额为")
                        # log.info(g.buy_amount)
                else:
                    # tmp = (g.buy_amount[etf][0]*( 1 - net_layer * g.net_range + 0.1)/cur_pri) % 100
                    buy_in_rate = ( 1 - (net_layer - 1) * g.net_range)
                    sell_out_rate = ( 1 - (net_layer - 2) * g.net_range)
                    tmp = (g.buy_amount[etf][0]*( 1 + (sell_out_rate - buy_in_rate)/buy_in_rate)/cur_pri) % 100
                    log.info("cur_pri:%s" %  (cur_pri))
                    log.info("buy_in_rate:%s" %  (buy_in_rate))
                    log.info("sell_out_rate:%s" %  (sell_out_rate))
                    log.info("g.buy_amount[etf][0]:%s" %  (g.buy_amount[etf][0]))
                    log.info("g.buy_amount[etf][0]*( 1 + (sell_out_rate - buy_in_rate)/buy_in_rate):%s" %  (g.buy_amount[etf][0]*( 1 + (sell_out_rate - buy_in_rate)/buy_in_rate)))
                    log.info("tmp:%s" %  (g.buy_amount[etf][0]*( 1 + (sell_out_rate - buy_in_rate)/buy_in_rate)/cur_pri))
                    if tmp <= 1:
                        sell_num = (g.buy_amount[etf][0]*( 1 + (sell_out_rate - buy_in_rate)/buy_in_rate)/cur_pri)
                    else:
                        # sell_num = int(g.buy_amount[etf][0]*( 1 + (sell_out_rate - buy_in_rate)/buy_in_rate)/cur_pri) + 100
                        sell_num = int(g.buy_amount[etf][0]*( 1 + (sell_out_rate - buy_in_rate)/buy_in_rate)/cur_pri) + 100
                    order_res = order(etf, -sell_num)
                    log.info("当前处于第%s层，%s的当前价格为:%s, buy_base_pri：%s, 本层卖出条件为：%s,当前价格和buy_base_pri比为%s，符合卖出的条件，卖出%s股" % (g.net[etf], etf, cur_pri, buy_base_pri, buy_base_pri * ( 1 - net_layer * g.net_range + 0.1) ,(cur_pri/buy_base_pri-1)*100 ,sell_num))
    
                    if order_res and str(order_res.status) in ['held', 'filled']:
                        # log.info("第%s层卖出" % (net_layer) + etf + ": ")
                        # log.info("总额：%s元，数量：%s份，单价：%s元" % (round(order_res.price*order_res.filled, 2), round(order_res.filled, 2), round(order_res.price, 2))) 
                        g.buy_amount[etf].pop()
                        g.net[etf] = g.net[etf] - 1
                        if g.net[etf] == 0:
                            del g.net[etf]
                            del g.buy_amount[etf]
                        # log.info("当前持有的基金的买入层数为：")
                        # log.info(g.net)    
                        # log.info("每一层的成交金额为")
                        # log.info(g.buy_amount)  
            
            if cur_pri < buy_base_pri * ( 1 - net_layer * g.net_range):
                if g.net[etf] < g.max_net:
                    order_res = order_value(etf, g.per_share)
                    if order_res and str(order_res.status) in ['held', 'filled']:
                        # log.info("第%s层买入" % (net_layer+1) + etf + ": ")
                        # log.info("总额：%s元，数量：%s份，单价：%s元" % (round(order_res.price*order_res.filled, 2), round(order_res.filled, 2), round(order_res.price, 2)))
                        g.net[etf] = g.net[etf] + 1
                        g.buy_amount[etf].append(order_res.filled * order_res.price)
                        # log.info("当前持有的基金的买入层数为：")
                        # log.info(g.net)    
                        # log.info("每一层的成交金额为")
                        # log.info(g.buy_amount)  
            
    # 当天收盘输出持仓
    if  context.current_dt.hour == 14 and context.current_dt.minute == 59:
        log.info("当前持有的基金的买入层数为：")
        log.info(g.net)    
        log.info("每一层的买入份数为")
        log.info(g.buy_amount)       
        log.info("基金买入成本为：")
        for _, fund in context.portfolio.positions.items():
            log.info('%s当前价格为%s：累计的持仓成本:%s, 当前持仓成本:%s, 当日持仓成本:%s' % (fund.security, fund.price, fund.acc_avg_cost, fund.avg_cost, fund.hold_cost))
            log.info('总仓位：%s' % (fund.total_amount))            
            
            
            
    

   

