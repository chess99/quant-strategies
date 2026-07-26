# 克隆自聚宽文章：https://www.joinquant.com/post/46874
# 标题：首版+2版龙虎榜挖掘V2.0，年化1400
# 作者：xxzlw

# 导入函数库
from jqdata import *
from collections import OrderedDict
# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
      # 开盘前运行
    g.muster = [] #目标
    g.amount = 1 #最大持股
    g.isbull = False # 是否牛市
      
    set_slippage(PriceRelatedSlippage(0.000))
    run_daily(prepare, time='9:15')
    run_daily(buy, time='9:26')
    
    # run_daily(sell, time='9:35')
    # run_daily(sell, time='10:00')
    # run_daily(sell, time='10:30')
    run_daily(sell, time='11:00')
    run_daily(sell, time='11:29')
    run_daily(sell, time='13:00')
    run_daily(sell, time='13:30')
    run_daily(sell, time='14:00')
    run_daily(sell, time='14:30')
    run_daily(sell, time='14:45')
    run_daily(sell, time='14:55')


def sell(context):
        current_data = get_current_data()     
        for position in list(context.portfolio.positions.values()):
            code=position.security
            name = get_security_info(code).display_name
            cost=position.avg_cost
            nowprice = current_data[code].last_price
            closeable_amount = position.closeable_amount
            high_limit = current_data[code].high_limit
            #小于成本
            target_price = high_limit*0.99
            # if code[:2] == '30':
            #   target_price = high_limit*0.83
            if nowprice !=high_limit and closeable_amount>0:
                order_target_value(code, 0)
                print('______________成本价卖出_______________')
                print("卖出[%s]" % (name))
        

def buy_prepare(context):
    result_stocks = []
    if g.muster is not None and len(g.muster)>0: 
        
    	current_data = get_current_data()
    	for stock in g.muster:
    	    price_data =  get_price(stock, count=1, panel=False,end_date=context.previous_date, frequency='daily', fields=['open', 'close', 'high_limit', 'low_limit', 'volume'])
    	    day_open = current_data[stock].day_open
    	    yesterday_high_limit = price_data['high_limit'][-1]
    	    high_limit = current_data[stock].high_limit
    	   # 大于昨日涨停且开盘不是涨停
    	    if yesterday_high_limit*1.04<= day_open and day_open<high_limit:
    	   # if day_open<price_data['close'][-1]*0.98:
    	        result_stocks.append(stock)
    # 	if len(result_stocks)>0:
    # 	    result_stocks = sorted(result_stocks, key=lambda x: get_price(x, count=1, panel=False, end_date=context.previous_date, frequency='daily', fields=['volume'])['volume'][-1], reverse=False)
    
    return result_stocks
    


# def buy(context):
    
    
#     #开盘再次判断
#     g.muster = buy_prepare(context)
    
#     if g.muster is not None and len(g.muster)>0:
#         for s in g.muster:
            
#             order_target_value(s, context.portfolio.total_value/len(g.muster)) # 调整标的至目标权重

def buy(context):
    available_slots = g.amount - len(context.portfolio.positions)
    if available_slots <= 0: 
        print("满仓无需开仓")
        return
    allocation = context.portfolio.cash / available_slots
    
    #开盘再次判断
    g.muster = buy_prepare(context)
    
    if g.muster is not None and len(g.muster)>0:
        for s in g.muster:
            if len(context.portfolio.positions) == g.amount:
                break
                # (为适应注册制挂单限制0.02,换成限价单,当前价格浮动百分之  之内,这里浮动0.017)
                
            name = get_security_info(s).display_name
            print('buy [{} {}]'.format(s,name))
            
            current_data = get_current_data()
            last_price = current_data[s].last_price
            
            nums = math.floor( int(allocation/last_price) )
            int_nums = int(nums // 100 ) * 100 # 取整除 - 返回商的整数部分（向下取整） 再乘以 100 
            order(s, int_nums) # 使用order 买入指定的仓位

def turnover_ratio(context,stock_list):
    result_stocks = []
    # 遍历股票清单
    for stock in stock_list:
        turnover_ratio = get_valuation(stock, end_date=context.previous_date, count=1, fields=['turnover_ratio']).iloc[0]['turnover_ratio']
        # print(turnover_ratio)
        if turnover_ratio<50 :
            result_stocks.append(stock)
    # 使用get_valuation方法查询多只股票的换手率数据
    if len(result_stocks)>0:
        turnover_data = get_valuation(result_stocks, end_date=context.previous_date, count=1, fields=['circulating_market_cap'])
        
        # 根据换手率字段对数据进行排序
        sorted_turnover_data  = turnover_data.sort_values('circulating_market_cap', ascending=False)
        # print(sorted_turnover_data)
        # 输出排序后的股票列表
        result_stocks = sorted_turnover_data['code'].tolist()
    
    return result_stocks   
    
# def HY_sum(stock_list,context):
#     result_stocks = []

#     industry_count = {}
#     current_data = get_current_data()
#     # 遍历股票清单
#     for stock in stock_list:
#         industry_code = current_data[stock].industry_code
        
#         # 统计行业股票数量
#         if industry_code in industry_count:
#             industry_count[industry_code] += 1
#         else:
#             industry_count[industry_code] = 1
    
#     for stock_code in stock_list:
#         industry_code = current_data[stock_code].industry_code
#         if industry_code in industry_count:
#             if industry_count[industry_code]>1 :
#                 result_stocks.append(stock_code)
    
#     return result_stocks   
    
def HY_sum(stock_list,context):
    result_stocks = []

    industry_count = {}
    current_data = get_current_data()
    # 遍历股票清单
    for stock in stock_list:
        res = get_concept(security=[stock], date=context.previous_date)
        concept_names = [concept['concept_name'] for concept in res[stock]['jq_concept']]
        # print(concept_names)
        for industry_code in concept_names:
            # 统计行业股票数量
            if industry_code in industry_count:
                industry_count[industry_code] += 1
            else:
                industry_count[industry_code] = 1
    
    # print(industry_count)
    for stock_code in stock_list:
        res = get_concept(security=[stock], date=context.previous_date)
        concept_names = [concept['concept_name'] for concept in res[stock]['jq_concept']]
        cont_num = 0 
        for industry_code in concept_names:
            if industry_count[industry_code] >= 2:
                cont_num = cont_num+1
                if cont_num>=1 :
                    result_stocks.append(stock_code)
                    break
    
    return result_stocks 

def prepare(context):
    #龙虎榜
    g.muster = get_billboard_list(stock_list=None, end_date = context.previous_date, count =1)
    g.muster = g.muster[g.muster['net_value']>0]
    g.muster = pd.DataFrame(g.muster).sort_values('net_value', ascending=False)
    g.muster = g.muster[g.muster['buy_rate']>4]
    g.muster = pd.DataFrame(g.muster).sort_values('buy_rate', ascending=False)
    g.muster = list(g.muster['code'])
    g.muster = list(OrderedDict.fromkeys(g.muster))
    #条件过滤
    g.muster = filter_kcbj_stock(g.muster)
    
    g.muster = HY_sum(g.muster,context)
    
    g.muster = filter_paused_stock(g.muster)
    g.muster = filter_st_stock(g.muster)
    g.muster = filter_limitup_stock(context, g.muster)
    g.muster = filter_limitdown_stock(context, g.muster)
    
    #首版挖掘
    g.muster = find_stock_with_criteria(context,g.muster)
    g.muster = turnover_ratio(context,g.muster)
    
    print('备选清单:')
    print(g.muster)
    
def find_stock_with_criteria(context,rankList_jk, days=18):
    result_stocks = []
    current_data = get_current_data()
    for stock_code in rankList_jk:
        
        # 获取最近20日的涨跌停价格数据
        price_data = get_price(stock_code, count=days, panel=False,end_date=context.previous_date, frequency='daily', fields=['open', 'close', 'high_limit', 'low_limit', 'volume'])
        
        # 判断昨日是否涨停
        if price_data['close'].iloc[-1] == price_data['high_limit'].iloc[-1]:
            
            #统计是否为首日涨停
            limit_up_count = sum(price_data['high_limit'] == price_data['close'])
            if limit_up_count==1 or   limit_up_count==2:
            
                # 计算最近20日的交易量
                volume_data = price_data['volume']
                # 计算均量
                avg_volume_20_days = np.mean(volume_data[:-3])
                avg_volume_3_days = np.mean(volume_data[-3:])
                
                # 判断最近3日交易量逐步递增且最近3日均量是最近20日均量的2倍
                if  avg_volume_20_days*4 <avg_volume_3_days < avg_volume_20_days*6 :
                    
                    result_stocks.append(stock_code)

    return result_stocks
    
#2-1 过滤停牌股票
def filter_paused_stock(stock_list):
	current_data = get_current_data()
	return [stock for stock in stock_list if not current_data[stock].paused]

#2-2 过滤ST及其他具有退市标签的股票
def filter_st_stock(stock_list):
	current_data = get_current_data()
	return [stock for stock in stock_list
			if not current_data[stock].is_st
			and 'ST' not in current_data[stock].name
			and '*' not in current_data[stock].name
			and '退' not in current_data[stock].name]

# 2-3 过滤科创北交股票 30为创业板
def filter_kcbj_stock(stock_list):
    for stock in stock_list[:]:
        if stock[0] == '4' or stock[0] == '8' or stock[:2] == '68' or stock[0] == '9' or stock[0] == '2' :
            stock_list.remove(stock)
    return stock_list

#2-4 过滤涨停的股票
def filter_limitup_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] < current_data[stock].high_limit]

#2-5 过滤跌停的股票
def filter_limitdown_stock(context, stock_list):
	last_prices = history(1, unit='1m', field='close', security_list=stock_list)
	current_data = get_current_data()
	return [stock for stock in stock_list if stock in context.portfolio.positions.keys()
			or last_prices[stock][-1] > current_data[stock].low_limit]

#2-6 过滤次新股
def filter_new_stock(context,stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=144)]
