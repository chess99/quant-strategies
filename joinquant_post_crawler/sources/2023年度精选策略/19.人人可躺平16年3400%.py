# 克隆自聚宽文章：https://www.joinquant.com/post/33859
# 标题：人人可躺平16年3400%（评论必回复）
# 作者：逆流的鱼

# 克隆自聚宽文章：https://www.joinquant.com/post/18
# 标题：量化投资学习【常见策略】4- 布林线1（不带开口收口判断）
# 作者：Kris

import numpy as np
import math
# 定义一个全局变量, 保存要操作的证券

security = '162605.XSHE'
set_benchmark('162605.XSHE')
# 初始化此策略
# 设置我们要操作的股票池, 这里我们只操作一支股票
set_universe([security])
#设置回测条件
set_commission(PerTrade(buy_cost=0.0001, sell_cost=0.0001, min_cost=0.1))
set_slippage(FixedSlippage(0))
#计算时采用的天数
days=20
#bolling轨策略
def Bolling(context,current_price,paused):
     #用price保存days天的股票收盘价
    price=history(days,'1d','close',security_list=None)
    #转成array方便数据处理
    price=np.array(price)
    #计算中轨线
    middle=price.sum()/days
    #计算标准差
    std=np.std(price)
    #计算上轨线
    up=middle+2.75*std
    #计算下轨线
    down=middle-1*std
    #如果股价跌破下轨线则买入
    if middle-0.5*std<current_price<middle+0.5*std:
        if paused==False:
            cash=context.portfolio.cash
            num_of_shares=int(cash/current_price)
            if num_of_shares>0:
                order(security,+num_of_shares)
                log.info("buying %s" %(security))
            
   
    #如果突破上轨线则卖出
    elif current_price>up or current_price<down:
        if paused==False:
            order_target(security,0)
            log.info("selling %s" %(security))
  
# 每个单位时间(如果按天回测,则每天调用一次,如果按分钟,则每分钟调用一次)调用一次
def handle_data(context, data):
    #判断股票当前是否停牌
    if data[security].paused==False:
        paused=False
    else:
        paused=True
    #取得股票当前价格
    current_price=data[security].price
    Bolling(context,current_price,paused)
   
   
