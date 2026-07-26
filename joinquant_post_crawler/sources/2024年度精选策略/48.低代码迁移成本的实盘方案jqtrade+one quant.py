# 克隆自聚宽文章：https://www.joinquant.com/post/45671
# 标题：低代码迁移成本的实盘方案:jqtrade+one quant
# 作者：拉姆达投资

# -*- coding: utf-8 -*-
############## 以下部分只有本地实盘需要,本地实盘取消注释 ############
##  python -m jqtrade start_task -c test_samll_cap.py -n 小市值策略
# from jqdatasdk import *
# import datetime
# auth("账号", '密码')

# def get_current_price(codes):
#     """获取当前价格"""
#     data = get_price(codes,end_date=datetime.datetime.now(),count=1,frequency='1m',fields='close',panel=False)
#     if isinstance(codes,str):
#         return  data.close.iloc[0]
#     else :
#         return data.set_index('code').close


# from trade_tool import *  # 导入工具包(全局变量对象和重新封装了的下单函数)
# # 创建/重载全局变量对象
# g = GlobalState('test_samll_cap_state.pkl')


##################### 以下为策略代码 ################
import pandas as pd
import datetime
# 初始化函数，设定基准等等
def process_initialize(context):

    # 输出内容到日志 log.info()  ,可以在启动策略时加上 -o 路径 参数输出日志到log文件
    log.info('运行 process_initialize')
    # 股票池
    # g.delete_global("security_universe_index")
    # g.delete_global("stock_num")
    g.security_universe_index = "399101.XSHE" 
    g.stock_num = 5 
    # set_options( 
    #     account_no="资金账号", # 资金账号
    #     order_dir = "D:\\交易软件\\安信OneQuant测试版\\csvTemplate\\DMA算法\\",#这里需要改为实际路径
    #     ) #本地实盘取消注释
#     run_daily(check_class, time='15:30')
    run_daily(my_trade, time='09:40')
    # my_trade(context)


## 开盘时运行函数
def my_trade(context):
    
    codes = get_index_stocks(g.security_universe_index)
    
    q = query(valuation.code).filter(valuation.code.in_(codes)).order_by(valuation.circulating_market_cap.asc()).limit(100)
    codes = list(get_fundamentals(q).code)
    codes = filter_st_stock(context,codes) 
    codes = filter_limit_stock(context, codes)
    codes = filter_new_stock(context,codes)
    codes = codes[:g.stock_num]
    adjust_position(context, codes, g.stock_num)
    

# 交易
def adjust_position(context, buy_stocks, stock_num):
    position_codes = list(context.portfolio.positions.keys())
    for stock in position_codes:
        if stock not in buy_stocks:
            log.info("stock [%s] in position is not buyable" % (stock))
            position = context.portfolio.positions[stock]
            order_target(stock, 0)
            # order_target(stock, 0, LimitOrderStyle(0) ) 
            # order_target(stock, 0, RatioLimitOrderStyle(position.price, 0.015), context) # 本地实盘取消注释
        else:
            log.info("stock [%s] is already in position" % (stock))
    position_count = len(context.portfolio.positions)
    if stock_num > position_count:
        value = context.portfolio.cash / (stock_num - position_count)
        
        for stock in buy_stocks:
            if stock not in context.portfolio.positions.keys():
                order_target_value(stock, value)  #one quant不支持市价单
                
                # now_price = get_current_price(stock) #使用order_target_value/order_value时需要传递最新价    # 本地实盘取消注释
                # order_target_value(stock, value, LimitOrderStyle(0), context, now_price) # price为0时以对手盘为委托价下单,now_price用于计算仓位
                # order_target_value(stock, value, RatioLimitOrderStyle(now_price, 0.015), context) # RatioLimitOrderStyle 以当前价*(1+0.015) (卖出时当前价*(1-0.015))为委托价下单 # 本地实盘取消注释
                if len(context.portfolio.positions) == stock_num:
                    break



# 过滤停牌股票
def filter_paused_stock(stock_list):
    current_data = get_current_data()
    return [stock for stock in stock_list if not current_data[stock].paused]
# 过滤ST
def filter_st_stock(context,stock_list):
    st_data = get_extras('is_st', stock_list, end_date=context.current_dt, count=1).iloc[0]
    filter_st = st_data[st_data == False].index.tolist() 
    return filter_st
# 过滤涨停和跌停的股票
def filter_limit_stock(context, stock_list):
    pdata = get_price(stock_list,count=1,frequency='1m',end_date=context.current_dt,fields=['close','high_limit','low_limit'],panel=False)
    filter_limit = pdata[(pdata.high_limit>pdata.close)&(pdata.low_limit<pdata.close)].code.tolist()
    return filter_limit

# 过滤科创板
def filter_kcb_stock(context, stock_list):
    return [stock for stock in stock_list  if not stock.startswith('68')]
# 过滤次新股
def filter_new_stock(context,stock_list):
    sdata = get_all_securities()
    sdata.start_date = pd.to_datetime(sdata.start_date).dt.date
    sdata = sdata.loc[stock_list]
    filter_new = sdata[(sdata.start_date - context.current_dt.date()) <= datetime.timedelta(days=250) ].index.tolist()
    return filter_new
    
    
def check_class(context):
	log.info("------------------以下为portfolio对象-------------------")
	log.info([context.portfolio.total_value ,
			context.portfolio.available_cash ,
			context.portfolio.locked_cash ,
				])
	log.info("------------------以下为position对象-------------------")
	position = context.portfolio.positions['000001.XSHE']
	log.info([position.security , #code
			position.total_amount ,
			position.closeable_amount ,
			position.avg_cost ,
			position.acc_avg_cost ,
			position.side ,
			position.price ,
			position.value ]		
		 )
	log.info("------------------以下为order对象-------------------")
	o = list(get_orders().values())
	if o :
		o= o[0]
	log.info(o )
    
    
    
    
    
    
    
    
    
