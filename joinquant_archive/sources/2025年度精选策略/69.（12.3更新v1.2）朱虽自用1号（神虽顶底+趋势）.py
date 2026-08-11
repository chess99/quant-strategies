# 克隆自聚宽文章：https://www.joinquant.com/post/29276
# 标题：（12.3更新v1.2）朱虽自用1号（神虽顶底+趋势）
# 作者：Fibonabbit

# 导入函数库
from jqdata import *

top = [False] * 199
topgender = [False] * 199
buttom = [False] * 199
buttomgender = [False] * 199
    
# 初始化函数，设定基准等等
def initialize(context):
    # 设定深圳成指作为基准
    set_benchmark('399001.XSHE')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    
    
    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000001.XSHG')
      # 盘中运行
    run_daily(market_open, time='14:30', reference_security='000001.XSHG')
      # 收盘后运行
    run_daily(after_market_close, time='after_close', reference_security='000001.XSHG')


def ema(c_list,n):#c_list这里是收盘价的时间序列
    y_list=[]
    _n = 1    
    for i in range(len(c_list)): 
        if _n==1:#当价格序列只有一个值时
            y=c_list[0]
        elif _n>1 and _n<=n:#当序列中价格个数小于给定参数值时（例如12个）
            y=c_list[i]*2/(_n+1)+(1-2/(_n+1))*y_list[-1] #这是ema的计算公式
        else:
            y=c_list[i]*2/(n+1)+(1-2/(n+1))*y_list[-1]
        y_list.append(y)
        _n = _n+1 
    return y_list

def macdx(c_list):
    dif=np.array(ema(c_list,12))-np.array(ema(c_list,26))
    dea=ema(dif,9)
    macd=(dif-dea)*2
    return [dif,dea,macd]
    
def trend(high,low):
    shortLong = ema(high,25)
    shortShort= ema(low,25)
    
    longLong = ema(high,90)
    longShort= ema(low,90)
    
    return [shortLong,shortShort,longLong,longShort]

def hasCross(data):#返回两个True/False列表，True为发生Cross
    deadcross = []
    goldcross = []
    for i in range(1,len(data)):
        
        if macdx(data)[2][i]<0 and macdx(data)[2][i-1]>=0:
            deadcross.append(True)
        else:
            deadcross.append(False)
        if macdx(data)[2][i]>0 and macdx(data)[2][i-1]<=0:
            goldcross.append(True)
        else:
            goldcross.append(False)
        
    return [deadcross,goldcross]
    
def barslast(xlist):#返回list中True的距今天数
    barslast = []
    for i in range(len(xlist)):
        if xlist[i] == True:
            barslast.append(199-i)
    return barslast
    
def core_ssdd(deads,golds,close,top,topgender,buttom,buttomgender):

    dif = macdx(close)[0]
    
    #顶部部分——两种情况
    if deads[-1] > golds[-1]: #情况1：最后是红柱
        lastreds = close[-golds[-2]:-deads[-1]] #定义上一个红柱区间
        lastredsdif = dif[-golds[-2]:-deads[-1]] #定义上一个红柱dif值区间
        
        secondreds = close[-golds[-3]:-deads[-2]] #定义上上个红柱区间
        secondredsdif = dif[-golds[-3]:-deads[-2]] #定义上上个绿柱区间
        
        maxredsdif = max(dif[-golds[-1]:])#定义这波红柱最高dif值
        maxlastredsdif = max(lastredsdif)#定义上波红柱最高dif值
        maxsecondredsdif = max(secondredsdif)#定义上上波红柱最高dif值
        
        #顶部结构形成部分
        if barslast(top) and barslast(top)[-1] == 1:
            if dif[-1] <= dif[-2] * 0.99:
                topgender.append(True)
                print('顶部结构形成type1')
                #log.info('结构形成')
            elif barslast(topgender) and barslast(topgender)[-1] == 1 and dif[-1] <= dif[-2] * 1.01:
                topgender.append(True)
                #log.info('结构延续')
            else:
                topgender.append(False)
        else:
            topgender.append(False)
              
        #顶部钝化部分
        if dif[-1] <= maxlastredsdif and maxredsdif <= maxlastredsdif:#若dif不高于上个红峰的dif
            
            if close[-1] > max(lastreds):#若收盘价高于上一个红柱峰
                top.append(True)
                #print('type1 top')
                #log.info('钝化')
            else:
                if barslast(top) and barslast(top)[-1] == 1:
                    top.append(True)
                    #print('type2 top \n')
                    #log.info('钝化')
                else:
                    top.append(False)
                    
        elif dif[-1] > maxlastredsdif and dif[-1] < maxsecondredsdif and maxredsdif < maxsecondredsdif:#dif高于上个红峰但不高于上上个
            if close[-1] > max(secondreds):#若收盘价高于上上个红柱峰
                top.append(True)
                #print('type1 top')
                #log.info('钝化')
            else:
                if barslast(top) and barslast(top)[-1] == 1:
                    top.append(True)
                    #print('type2 top \n')
                    #log.info('钝化')
                else:
                    top.append(False)
        
        else:
            top.append(False)
    
    elif deads[-1] == 1 and (barslast(top) and barslast(top)[-1] == 1): #情况2：上一交易日是红柱钝化但结构形成在绿柱
        #这种情况只考虑结构形成
        #print('checkpoint')
        
        if barslast(top) and barslast(top)[-1] == 1:
            if dif[-1] <= dif[-2] * 0.99:
                top.append(False)
                topgender.append(True)
                print('顶部结构形成type2')
                #log.info('结构形成，形成在绿柱不能延续')
            else:
                top.append(False)
                topgender.append(False)
                #print('未知错误')
        else:
            top.append(False)
            topgender.append(False)
            #print('未知错误')
    
    else:
        top.append(False)
        topgender.append(False)
        
        
    #底部部分——两种情况
    if deads[-1] < golds[-1]: #情况1：最后是绿柱
        lastgreens = close[-deads[-2]:-golds[-1]] #定义上一个绿柱区间
        lastgreensdif = dif[-deads[-2]:-golds[-1]] #定义上一个绿柱dif值区间
        
        secondgreens = close[-deads[-3]:-golds[-2]] #定义上上个绿柱区间
        secondgreensdif = dif[-deads[-3]:-golds[-2]] #定义上上个绿柱dif值区间
        
        mingreensdif = min(dif[-deads[-1]:])#定义这波绿柱最低dif值
        minlastgreensdif = min(lastgreensdif)#定义上波绿柱最低dif值
        minsecondgreensdif = min(secondgreensdif)#定义上上波绿柱最低dif值
        
        #底部结构形成部分
        if barslast(buttom) and barslast(buttom)[-1] == 1:
            if dif[-1] >= dif[-2] * 0.99:
                buttomgender.append(True)
                #log.info('结构形成')
            elif barslast(buttomgender) and barslast(buttomgender)[-1] == 1 and dif[-1] >= dif[-2] * 1.01:
                buttomgender.append(True)
                #log.info('结构延续')
            else:
                buttomgender.append(False)
        else:
            buttomgender.append(False)
               
        #底部钝化部分
        if dif[-1] >= minlastgreensdif and mingreensdif >= minlastgreensdif:#若dif不低于上个绿峰的dif
            
            if close[-1] < min(lastgreens):#若收盘价低于上一个绿柱峰
                buttom.append(True)
                #print('type1 buttom')
                #log.info('钝化')
            else:
                if barslast(buttom) and barslast(buttom)[-1] == 1:
                    buttom.append(True)
                    #print('type2 buttom \n')
                    #log.info('钝化')
                else:
                    buttom.append(False)
                    
        elif dif[-1] < minlastgreensdif and dif[-1] >= minsecondgreensdif and mingreensdif >= minsecondgreensdif:
            #print('checkpoint')
            if close[-1] < min(lastgreens):#若收盘价低于上上个绿柱峰
                buttom.append(True)
                #print('type1 buttom')
                #log.info('钝化')
            else:
                if barslast(buttom) and barslast(buttom)[-1] == 1:
                    buttom.append(True)
                    #print('type2 buttom \n')
                    #log.info('钝化')
                else:
                    buttom.append(False)
            
        else:
            buttom.append(False)
            
    elif golds[-1] == 1 and (barslast(buttom) and barslast(buttom)[-1] == 1): #情况2：上一交易日是绿柱钝化但结构形成在红柱
        #这种情况只考虑结构形成
        #print('checkpoint')
        
        if barslast(buttom) and barslast(buttom)[-1] == 1:
            if dif[-1] >= dif[-2] * 0.99:
                buttom.append(False)
                buttomgender.append(True)
                #log.info('结构形成，形成在红柱不能延续')
            else:
                buttom.append(False)
                buttomgender.append(False)
                #print('未知错误')
        else:
            buttom.append(False)
            buttomgender.append(False)
            #print('未知错误')
               
    else:
        buttom.append(False)
        buttomgender.append(False)
            
    
    
    buttom.pop(0)
    buttomgender.pop(0)
    
    top.pop(0) #把队首的项去掉，维持top序列长度为200
    topgender.pop(0)

    
    return [top,topgender,buttom,buttomgender]

#判断一个list中的数是否连续
def isContinuous(xlist):
    if len(xlist) == 1:
        return True
    else:
        for i in range(1,len(xlist)):
            if xlist[i-1] - xlist[i] != 1:
                return False
        return True
        
#若不连续，找到最近的一个连续子列
def findSublist(xlist):
    while not isContinuous(xlist):
        xlist.pop(0)
    
    return xlist
    
#若近期有结构形成，则触发判断器
#触发条件barslast(topgender)<=golds[-1]
def tradeHelper1(golds,topgender):
    lasttg = topgender[-golds[-1]:]
    n = len(lasttg)
    lasttg = np.append([False]*(199-n),lasttg)
    tgsublist = findSublist(barslast(lasttg))

    if -tgsublist[0] + 24 > 0:
        return True
    
#触发条件barslast(buttomgender)<=deads[-1]
def tradeHelper2(deads,buttomgender):
    lastbg = buttomgender[-deads[-1]:]
    n = len(lastbg)
    lastbg = np.append([False]*(199-n),lastbg)
    bgsublist = findSublist(barslast(lastbg))
    
    if -bgsublist[0] + 24 > 0:
        return True

def isRealT(close,deads,golds):
    dif = macdx(close)[0]
    #当前正在绿柱时触发判断器
    lastredsdif = dif[-golds[-1]:-deads[-1]] #定义上一个红柱dif值区间
    secondredsdif = dif[-golds[-2]:-deads[-2]] #定义上上个红柱dif区间
    thirdredsdif = dif[-golds[-3]:-deads[-3]]  #定义上上上个红柱dif值区间
    
    maxlastredsdif = max(lastredsdif)#定义上波红柱最高dif值
    maxsecondredsdif = max(secondredsdif)#定义上上波红柱最高dif值    
    maxthirdredsdif = max(thirdredsdif)
    
    if maxlastredsdif <= maxsecondredsdif or maxlastredsdif <= maxthirdredsdif:
        return True
    
def isRealB(close,deads,golds):
    dif = macdx(close)[0]
    #当前正在红柱时触发判断器
    lastgreensdif = dif[-deads[-1]:-golds[-1]] #定义上一个绿柱dif值区间
    secondgreensdif = dif[-deads[-2]:-golds[-2]] #定义上上个绿柱dif值区间
    thirdgreensdif = dif[-deads[-3]:-golds[-3]] #定义上上上个绿柱dif值区间
    
    minlastgreensdif = min(lastgreensdif)#定义上波绿柱最低dif值
    minsecondgreensdif = min(secondgreensdif)#定义上上波绿柱最低dif值
    minthirdgreensdif = min(thirdgreensdif)
    
    if minlastgreensdif >= minsecondgreensdif or minlastgreensdif >= minthirdgreensdif:
        return True


## 开盘前运行函数
def before_market_open(context):
    # 输出运行时间
    #log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time()))

    # 交易参考指数说明：本策略使用时间为2017年之后，若硬要用17年之前的数据做回测
    # 则为了保证唯一性，建议选取上证指数作为交易的参考指数
    # 因为上证指数在2017年之前可以看成更加综合的指数，而在2017年之后，深成指更可以代表大小盘股的综合
    # 导致指数结构性变化的原因有很多，如上海上市的股票多偏大盘蓝筹等，而在2017年之前这种分化效应并不明显
    # 纠结于这点的意义不大，不妨直接假设研究者（您）在2017年根据政策和观察到的分化作出了这种判断
    if context.current_dt >= datetime.datetime(2017,1,1):
        g.security = '399001.XSHE'
    else:
        g.security = '000001.XSHG'

## 开盘时运行函数
def market_open(context):
    global top,topgender,buttom,buttomgender
    
    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    security = g.security
    
    # 获取股票14:55时/最高/最低/收盘价格
    today_data = get_bars(security, count=1, unit='1m', fields=['close','high','low'])
    # 取得当前的现金
    cash = context.portfolio.available_cash

    tv = context.portfolio.total_value
    
    datas = get_bars(security, count = 199, unit = '1d', fields = ['close','high','low'])
    closes = np.append(datas['close'], today_data['close'][-1])
    
    highs = np.append(datas['high'], today_data['high'][-1])
    lows = np.append(datas['low'], today_data['low'][-1])
    
    trends = trend(highs,lows)
    
    list1 = hasCross(closes)[0]
    list2 = hasCross(closes)[1]
    deads = barslast(list1)
    golds = barslast(list2)
    
    res = core_ssdd(deads,golds,closes,top,topgender,buttom,buttomgender)
    top = res[0]
    topgender = res[1]
    buttom = res[2]
    buttomgender = res[3]
    
    current_price = today_data['close'][-1]
    #交易标的：深100
    security = '159901.XSHE'
    
    if (topgender[-1] or buttomgender[-1]) and not (topgender[-2] or buttomgender[-2]):
        if topgender[-1]:
            if (current_price*0.76 < trends[1][-1]) and (current_price*0.76 < trends[3][-1]):
                log.info('顶部结构形成')
                order_target_value(security, 0)
            #elif (current_price*0.76>trends[0][-1]) and (current_price*0.88 < trends[3][-1]):
                #order_target_value(security, 0.4*tv)
            #elif (current_price*0.76>trends[2][-1]) and (current_price*0.88 < trends[1][-1]):
            #    order_target_value(security, 0.6*tv)
                
        elif buttomgender[-1]:
            if (current_price*1.5>trends[0][-1]) and (current_price*1.5>trends[2][-1]):
                log.info('底部结构形成')
                order_target_value(security, tv)
            #elif (current_price*1.24>trends[0][-1]) and (current_price*1.24<trends[3][-1]):
            #    order_target_value(security, 0.4*tv)
            #elif (current_price*1.24>trends[2][-1]) and (current_price*1.24<trends[1][-1]):
            #    order_target_value(security, 0.6*tv)
            
    elif (topgender[-2] or buttomgender[-2]):
        if topgender[-2]:
            if topgender[-1]:
                pass
            else:
                if deads[-1]<golds[-1]:#绿柱
                    pass
                elif deads[-1]>golds[-1] and top[-1] == True:
                    pass
        else:
            if buttomgender[-1]:
                pass
            else:
                if deads[-1]>golds[-1]:
                    pass
                elif deads[-1]<golds[-1] and buttom[-1] == True:
                    pass

    else:
        if barslast(topgender) and min(barslast(topgender)) < golds[-1] and tradeHelper1(golds,topgender) and ((deads[-1]<golds[-1] and isRealT(closes,deads,golds)) or (deads[-1]>golds[-1] and top[-1])):
            pass
        elif barslast(buttomgender) and min(barslast(buttomgender))<deads[-1] and tradeHelper2(deads,buttomgender) and ((deads[-1]>golds[-1] and isRealB(closes,deads,golds)) or (deads[-1]<golds[-1] and buttom[-1])):
            log.info('pass')
            pass
            
        else:
            # 如果接近收盘时价格低于长短期趋势下轨，则空仓
            if (current_price < trends[1][-1]) and (current_price < trends[3][-1]):
                # 记录这次交易
                log.info("价格低于长短期趋势下轨, 交易 %s至空仓" % (security))
                # 总仓位0%
                order_target_value(security, 0)
            # 如果接近收盘时价格低于长期趋势下轨但高于短期趋势上轨，则4成仓
            elif (current_price > trends[0][-1]) and (current_price < trends[3][-1]):
                # 记录这次交易
                log.info("价格低于长期趋势下轨但高于短期趋势上轨, 交易 %s至4成仓" % (security))
                # 总仓位40%
                order_target_value(security, 0.4*tv)
            # 如果接近收盘时价格低于短期趋势下轨但高于长期趋势上轨，则6成仓
            elif (current_price > trends[2][-1]) and (current_price < trends[1][-1]):
                # 记录这次交易
                log.info("价格低于短期趋势下轨但高于长期趋势上轨, 交易 %s至6成仓" % (security))
                # 总仓位60%
                order_target_value(security, 0.6*tv)
            # 如果接近收盘时价格高于长短期趋势上轨，则满仓
            elif (current_price > trends[0][-1]) and (current_price > trends[2][-1]):
                # 记录这次交易
                log.info("价格高于长短期趋势上轨, 交易 %s至满仓" % (security))
                # 总仓位100%
                order_target_value(security, tv)
    

    
    

## 收盘后运行函数
def after_market_close(context):
    #log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    #log.info('一天结束')
    log.info('##############################################################')
