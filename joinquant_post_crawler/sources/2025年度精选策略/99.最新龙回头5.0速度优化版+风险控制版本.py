# 克隆自聚宽文章：https://www.joinquant.com/post/30071
# 标题：最新龙回头5.0速度优化版+风险控制版本
# 作者：GoodThinker

# 克隆自聚宽文章：https://www.joinquant.com/post/36014
# 标题：龙头3连板打板2个半月年化26倍
# 作者：奶牛哥

'''
策略：3连板后，次日直接买入。  

##逻辑设定:          
0、大盘情绪面 ：关闭，此功能不完善，没起到规避风险的效果  
1、仓位       ：资金2等分，每交买入半仓，待盈利10%后再买入下一只      
2、止损       : 从最高点下跌-15%激活止损
3、股票池     ：大A股，排开新股、停牌、创业板、科创板
4、买入选股   ：3连板
5、买入择时   ：次日开盘直接买入
5、买入       ：直接买入  
5、卖出选股   ：5日线死叉10日线，或短线见顶标志   
6、卖出       ：直接卖出     

##操作频率设定
1. 日线       : 判断大盘情绪、全局选股、买入选股、清理备选池、卖出选股
2. 60分钟线   : 买入择时、买入、短线卖出选股、止损选股、卖出
'''
# 导入函数库
from jqdata import *
from jqlib.technical_analysis import *

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('510300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    
    # 参数初始化
    setting_init(context)
    
    # 全局变量初始化
    bianNiang_init(context)
    
    ## ----周期运行函数------##
    #大盘趋势判断：大多头、震荡、大空头
    run_daily(dapan_day_type,time='1:00')  
    
    # 全局选股，每天一次  
    run_daily(xuangu_JiBenMian,time='2:00')     
    
    # 清理备选池（日线）
    run_daily(qingli_beixuan,time='2:30')
    
    # 买入选股，加入备选股
    run_daily(xuangu_day_buy,time='3:00')
    
    # 卖出选股（日线） 
    run_daily(xuangu_day_sell,time='4:00')
    
    # 买入；卖出选股(止损+短线)；卖出
    run_daily(handle,time='every_bar')
 
 # 参数初始化

# 参数初始化
def setting_init(context):
    # ---全局股票池---
    g.get_stks_all_or_concept="all"    #"concept":概念股   "all"：所有A股股票
    g.get_stks_concept={}
    g.newgu_days=120                   # 上市多少天后不算新股
    g.is_only_st=0                     # 是否仅包含ST股，当=1时，必须g.is_no_ST=0
    g.is_no_ST=0                       # 是否排除ST，默认排除停牌、120天内新股、创业板，科创板,北交所  
    g.is_everyday_qingkong_beixuan=1   # 每天清空备选池，默认为否。当每天不清空时，在每日卖出选股中删除
    
    # ---风控管理---
    #1. 是否开启大盘控制，1：按大盘交易；0.全部按震荡短线行情交易；-1：全部按多头趋势行情
    g.dapan_kz=0              #----全部按空头短线行情--------  
    
    #2. 动态止损点(从最高价回撤的最大幅度，最大亏损-15%)：    
    g.zhishun_one_point=-0.15   # 单只股票的最大回撤幅度，最大亏损-15%，单只股票导致总资金的最大亏损为-5%
    g.is_dtzs=1                 # =1，则开启止损；如果=0，则关闭止损   #不管大盘何种形态，当个股亏损到一定量后无条件止损
   
    # ---仓位管理---
    g.max_number=1                 # 将资金分成几等分
    g.is_stk_yingli_befor_buy=1     # 买入前是否需要现有持仓盈利  
    g.stk_yingli_before_buy=0.1     # 持仓股盈利>10%后再买入下一支，以此循环，确保仓位的盈利  
  
    # ---买入选股因子---

    # 1.  是否启用：限制价格不能超过n日最低价的多少倍
    g.is_max_price_limit=1       
    g.max_price_days=120         #     LLV(c,n)，其中n=120 
    g.max_price=2                #     限制买入价格不能超过LLV(c,days)的倍数  
    
    # 2. 是否启用： 连板涨停:1,(zt=9.9%、4.95%、19.95%)；不要求:0；
    g.is_lianban_zt=1            
    g.lianban_zt_days=3          #    连板天数，默认n=3
    g.lianban_zt_ma60=1          #    连板的同时是否要求MA60均线向上 ，默认:是
    g.lianban_zt_fangliang=1     #    连板期间是否要求放量(v>ma(v,5))，默认：是
    g.lianban_zt_fangliang_days=2#    连板期间要求放量的天数,默认和连板天数一样，并且第3天的量大于前2天任1天
    g.lianban_zt_lastday_fangliang=0  # 连板期间最后1天放量：相对ma(v,5)的倍数
    g.lianban_zt_lastday_normal_zt=0  # 连板期间最后1天要正常涨停，非一字板、非T字板
    g.lianban_zt_pjzf_kz=1            # 连板期间连续n+2天的平均涨幅控制，默认控制
    g.lianban_zt_buy_sort=False  #    当买入股有多只时，排序方式，False是升序 Ture是降序      
    

    #卖出选股因子
    g.is_duanxian_ding=1            # 在60分钟线中判断短期顶部    
    g.is_zhongxian_1020_sc=1        # 在日线中判断：10死叉20日线    
    g.is_zhongxian_510_sc=1         # 在日线中判断：5死叉10日线 

    # ---买入择时设定---  
                                   # 默认是直接买入，不需其它条件
    g.stk_buy_ma_jc=0              # 当买入池中股票分钟线金叉时买入 ;在全局变量初始化中强制设置g.is_everyday_qingkong_beixuan=0   
    g.stk_buy_ma_jc_unit='60m'     # 买入择时的均线周期，默认是30m,备选是60m
    
    # ---卖出择时设定---  
    
    # ---操作频率---
    #部份函数60分钟执行一次
    g.interval=60       # K线中分钟线中的运行频率:此为60分钟线
    g.count=-1          # 记数器,不要在盘中开启策略


# 全局变量初始化
def bianNiang_init(context):
    # ---全局变量区域---
    # 大盘类型，(多头趋势=1；震荡=0；空头趋势=-1) 
    g.dapan_type={}
    
    g.stks_BeiXuan_JibenMian_week=[]    # 基本面股票池：每周一次
    g.stks_BeiXuan=[]               # 备选池:每天一次技术性选股后的池子  
    g.stks_will_buy=[]              # 买入池：从备选池择时后的池子
    g.stks_will_sell_day=[]         # 日线卖出池：每日从持仓中选出
    g.stks_will_sell_bar=[]         # 60分钟线卖出池：每60分钟一次从持仓中选出
    
    g.money=context.portfolio.starting_cash/g.max_number    #默认每个股票分配的总资金-满仓操作，在函数“buy”中根据仓位进行调整
    
    g.zhishun_price=dict()  #全局止损价格，内容为：｛'代码1':止损价,｝，只能提高，不能降低，
    #g.stk_high_price=dict() #全局：买入后的最高收盘价，内容为：｛'代码1':最高价格1,｝用于动态止损，只能提高不能降低；买入时以成本价作为原始最高价
    # ------变量定义完毕------
    
    #-------其它初始化--------
    if g.stk_buy_ma_jc==1:                  # 当买入池中股票60分钟线ma10金叉ma20时买入 ;强制设置g.is_everyday_qingkong_beixuan=0   
        g.is_everyday_qingkong_beixuan=0   # 每天清空备选池，默认为1
    

# 判断当天大盘类型
# 此处只有框架，需进一步完善
def dapan_day_type(context):  
    # 是否开启大盘控制，1：按逻辑规定的规则交易；0:全部按震荡短线行情交易；-1：全部按多头趋势行情;-2：全部按空头行情
    result={"sz":-1,"sh":-1}         #  默认返回值
    if g.dapan_kz==0:                #  0:全部按震荡短线行情交易
        result["sz"]=0
        result["sh"]=0
    elif g.dapan_kz==-1:             # -1：全部按多头趋势行情
        result["sz"]=1
        result["sh"]=1
    elif g.dapan_kz==-2:             # -2：全部按空头趋势行情
        result["sz"]=-1
        result["sh"]=-1
 
    g.dapan_type=result
    print('##################')
    print('----大盘情绪----')
    
    print(result)
    
# 全局选股
def xuangu_JiBenMian(context):
    g.stks_BeiXuan_JibenMian_week=[]            # 基本面股票池：每次清空  
     
    print("-----全局选股-----")               
    
    all_stks=get_all_stks(context)              # 获取所有非ST、非停牌、非新股、非创业板、非科创板、非北交所的股票列表
    if len(all_stks)==0:
        print("all_stks为空，退出选股")
        return
 
    g.stks_BeiXuan_JibenMian_week=all_stks
    print("全局股票池：{0}".format(len(g.stks_BeiXuan_JibenMian_week)))

#买入选股
def xuangu_day_buy(context):
    stks_BeiXuan=g.stks_BeiXuan_JibenMian_week    # 内部备选池每天刷新  
   
    if g.is_everyday_qingkong_beixuan==1:         # 如果每天清空备选池
        g.stks_BeiXuan=[]
    
    print("-----每日选股-----") 
    # 从stks_BeiXuan中选股
    if len(stks_BeiXuan)==0:
        print("g.stks_BeiXuan_JibenMian为空，退出选股")
        return

    # 相对昨日限价：price<LLV(c,n)*1.6 
    if g.is_max_price_limit==1  and len(stks_BeiXuan)>0:
        stks_BeiXuan=max_price_limit(context,stks_BeiXuan)

    # 连板
    if g.is_lianban_zt==1 and len(stks_BeiXuan)>0:
        stks_BeiXuan=is_lianban_zt(context,stks_BeiXuan)
        #stks_BeiXuan=is_qiangshigu(context,stks_BeiXuan)
    
    if len(stks_BeiXuan)>0:
        #print("备选池今日新增:{0}".format(stks_BeiXuan))
        g.stks_BeiXuan+=stks_BeiXuan      
        g.stks_BeiXuan=quchong(g.stks_BeiXuan)                  # 不清空备池，可能会重复
    
    print("备选池共：{0}".format(len(g.stks_BeiXuan)))
    
    # 显示备选股信息
    if len(g.stks_BeiXuan)>0:
        for stk in g.stks_BeiXuan:
            print(get_name(stk))

# 清理备选池（日线）
def qingli_beixuan(context):
   # 当g.stks_BeiXuan每天不清空时，每日检查并删除备选股
    if g.is_everyday_qingkong_beixuan==0:                     # 每日清空为否  
        print("-----每日清理备选池-----")
        for stk in g.stks_BeiXuan:
            g.security=stk                                    # 更新全局变量,ma()要用到g.security变量
            if cross(10,5) or ma(n=10)>=ma(n=5):
                g.stks_BeiXuan.remove(stk)
                print(get_name(stk) + ":均线死叉，清出备选池！") 
    else:
        print("----备选池每日自动清空-----")


#卖出选股 （日线） 
#不管大盘是什么形态，符合日线都要卖出
def xuangu_day_sell(context):
    g.stks_will_sell_day=[]             # 当天清空
    
    print("-----每日卖出选股-----") 
    if len(context.portfolio.positions)==0:   
        print("持仓：无")    
        return
    
    for stk in context.portfolio.positions.keys():
        g.security=stk 
        
        # 10-20均线死叉
        if g.is_zhongxian_1020_sc==1:#  全局开关
            if cross(20,10) or ma(n=20)>=ma(n=10):
                g.stks_will_sell_day.append(stk)
                print(stk + ":(10，20)均线死叉")

        # 5-10均线死叉
        if g.is_zhongxian_510_sc==1:#  全局开关
            if cross(10,5) or ma(n=10)>=ma(n=5):
                g.stks_will_sell_day.append(stk)
                print(stk + ":(5，10)均线死叉")

        # 动态止损在60分钟线内判断

    if len(g.stks_will_sell_day)>0:           
        print('进入日线卖出池：{0}'.format(g.stks_will_sell_day))


# 定时运行函数：包括 买入择时； 买入；卖出选股(止损+短线)；卖出     
def handle(context):
    
    g.count=g.count+1             # 控制代码60分钟执行一次
    if g.count!=g.interval:      
        return       
    else:
        g.count=0                #  条件满足,计数器归零,继续后边的代码
    
    
    print("--------") 
    #买入择时
    buy_zs(context)
        
    #买入
    buy(context)
    
    #卖出选股
    xuangu_bar_sell(context)
    
    #卖出
    sell(context)

# 买入择时
def buy_zs(context):
    stks_will_buy={}                 # 每BAR清空，符合条件的买入池,格式为｛stk:price/llv(c,120)｝，用于排序
    g.stks_will_buy=[]               # 每bar清空
    
    print("-----(60分钟)买入择时-----") 
    #print("测试信息：g.stks_BeiXuan:{0}".format(g.stks_BeiXuan))
    
    # 如果备选股为空
    if len(g.stks_BeiXuan)==0:
        print("备选池：无")
        return
    
    for security in g.stks_BeiXuan:
        #取n天内的平均涨幅，防止短期涨幅过大   
        g.security=security
        
        data=attribute_history(security=security,count=(g.lianban_zt_days+2)+1,unit='1d')   # 如果是3天，则count=3+2+1
        zf=0                                                                          # 5天内总涨幅 
        is_st=stk_is_st(security)                                                     # 是否ST股
        for i in range(g.lianban_zt_days+2):                                          # g.stks_will_buy_sort_days=5
            zf=zf+(data["close"][i+1]/data["close"][i]-1)
        if is_st:                                                                     # 如果是ST股，则涨幅*2，从5%-》10%
            zf=zf*2
            max_zf=1.035                                                            # ST股开盘最大涨幅
        else:
            max_zf=1.07                                                              # 非ST股开盘最大涨幅

        if g.stk_buy_ma_jc==1:                                                       # 分钟线均线金叉才买入
            if cross(10,20,unit=g.stk_buy_ma_jc_unit):                                # 默认是30分钟线，10--20金叉
                stks_will_buy[security]=zf/(g.lianban_zt_days+2) 
        else:                                                                         # 直接买入
            #开盘>7%放弃
            current_data=get_current_data()
            open_new=current_data[security].day_open
            close_ref=ma(type='c',n=1,unit='1d')
            if open_new>close_ref*max_zf:
                print(get_name(security)+"：高开>7%，放弃")
                #g.stks_BeiXuan.remove(security)
            else:
                stks_will_buy[security]=zf/(g.lianban_zt_days+2) 
                # stks_will_buy的格式为｛stk:5天内平均涨幅｝，用于多只票时排序
    
    if len(stks_will_buy)>0:                                                                # 当len()=0时，可能导致g.stks_will_buy（）执行
        g.stks_will_buy=stks_buy_sort(stks_will_buy,g.lianban_zt_buy_sort)                  # 对stks_will_buy排序: 10天内平均涨幅按升序排序,再将返回的列表传给g.stks_will_buy
        print("准备顺序买入：{0}".format(g.stks_will_buy))
    else:
        print("准备买入：无")

## 买入  
def buy(context):
    print("----(60分钟)买入----")
    
    if len(g.stks_will_buy)==0:                       # 当没有选出符合的股票：
        print("买入池：空")
        return
    
    print("共持仓:{0}!".format(len(context.portfolio.positions)))
    
    #遍历买入池中所有的股票，按顺序买入
    for stk in g.stks_will_buy:
        
        # 买入前是否需要现有持仓盈利 ：当天如果买入一只后将无法再买入第二只
        if g.is_stk_yingli_befor_buy==1:          
            # 当持仓数量>0时，需判断是否全部盈利>指定比例(10%)
            is_buy=0    # 是否买入股票的标志，  
            if len(context.portfolio.positions)>0:
                # 判断持仓股票的盈利是否都大于10%
                #g.stk_yingli_before_buy=0.1    # 持仓股盈利>10%后再买入下一支，以此循环，确保仓位的盈利
                for position_stk in context.portfolio.positions.keys():
                    avg_cost=context.portfolio.positions[position_stk].avg_cost
                    price   =context.portfolio.positions[position_stk].price
                    yingli=0                                               # 某只股票的盈亏比
                    if avg_cost!=0:
                        yingli=price/avg_cost-1
                    print("持仓:{0}，盈亏比：{1:.2%}".format(get_name(position_stk),yingli))   # round()取小数点后2位
                
                    if yingli < g.stk_yingli_before_buy:                            # 只要有一只票的涨幅<10%,则将标志is_buy=false, 此时仍计算所有持仓的盈利，并显示
                        is_buy-=1                                                   # is_buy数字就是不达标的股票数量
            if is_buy<0:
                print("有 {0} 只持仓票的盈利没有达到要求，放弃买入！".format(-is_buy))
                break
    
        # 是否超过最大限度，每只都需要判断
        if len(context.portfolio.positions)>=g.max_number:   
            print("已达最大持仓数:{0}，放弃买入！".format(g.max_number))
            print('--')
            break  
        
        # stk对应的大盘：趋势：买入；震荡：买入；空头：只卖不买。   
        # 在选股时已过滤大盘空头行情
        
        # 非停牌，
        current_data = get_current_data()
        if current_data[stk].paused==True:
            print(get_name(stk)+"停牌，放弃买入！")
            continue

        # 当持仓中已有时，不买
        if stk in context.portfolio.positions.keys():
            print(get_name(stk)+"已持仓，放弃买入！")
            continue

        security=stk #取股票代码名称
        #如果没有买过 + 仓位>0时 买入，防止股票池小于3只时重复买入 
        if context.portfolio.positions.has_key(security)==False and g.money!=0:  
            order_value(security,g.money)
            # 可能因为涨停买不到
            if context.portfolio.positions.has_key(security)==True:
                print("买入：{0} ; 数量:{1}; 均价:{2}".format(get_name(security),context.portfolio.positions[security].total_amount,round(context.portfolio.positions[security].avg_cost,2)))
            
                g.stks_BeiXuan.remove(stk)  # 避免同一天重复判断买入
                print("g.stks_BeiXuan中删除:"+stk)
            
                #g.stk_high_price[security]=context.portfolio.positions[security].avg_cost  # 更新买入后的最高价，用于动态止损
                #print('{0}的当前最高价格：{1}'.format(security,context.portfolio.positions[security].avg_cost))
                g.zhishun_price[security]=context.portfolio.positions[security].avg_cost*(1+g.zhishun_one_point) #刚买入时，止损点为-15% 
                print("{0}初始止损价为：{1}".format(get_name(security),g.zhishun_price[security]))
                
            else:
                print("{0}:买入不成功！".format(get_name(security)))
                #if g.is_stk_yingli_befor_buy==1:                                 # 当必须盈利才能买+第一只买入没成功时直接退出
                #    break

## 60分钟线卖出选股(止损 + 短线震荡行情)    
def xuangu_bar_sell(context):
    g.stks_will_sell_bar=[]   #卖出股票池，每bar清空
    
    print("-----(60分钟)卖出/止损选股-----")
    
    if len(context.portfolio.positions)==0:   #如果持仓为空，则返回
        print("持仓：空")
        return
    
    for stk in context.portfolio.positions.keys():

        #动态止损   不管行情如何都必须执行
        if g.is_dtzs==1:
            if is_zhishun(context,stk)>0:
                print(get_name(stk) +':触发止损！')
                g.stks_will_sell_bar.append(stk)
                continue
        
        # 如果股票对应的大盘是多头行情，则使用中线条件选股
        if g.dapan_type[stk_to_dapan(stk)]==1:
            #print(get_name(stk)+"：大盘多头，使用日线条件卖出")
            continue
        
        # 60分钟线中判断短线顶部
        if g.is_duanxian_ding==1:
            dapan=stk_to_dapan(stk)          # STK属于沪市，还是深市?  # 大盘类型，(多头趋势(MA30>MA60 )=1；震荡（短线:MA60向下+ma5>ma10）=0；空头趋势=-1) 
            if g.dapan_type[dapan]==1:       #  如果是多头行情，则执行日线卖出机制 
                continue
        
            #以下为大盘震荡或空头时进行卖出选股
            if is_duanxian_ding(context,stk)==True:
                #print(get_name(stk) +':短线见顶！')  
                g.stks_will_sell_bar.append(stk)
                continue
    print("待卖出：{0}".format(len(g.stks_will_sell_bar)))
 
# 卖出
def sell(context):
    # 在选股环节已经判断了大盘行情
    stks_will_sell=g.stks_will_sell_day+g.stks_will_sell_bar  # 将日线和60分钟线选出的票合并
    g.stks_will_sell_day=[]                                   # 清空g.stks_will_sell_day，防止当天后面继续卖出日线中的票
    
    print("---(60分钟)卖出---")
    # 如果卖出池为空，直接返回
    if len(stks_will_sell)==0:
        print("待卖出：无")
        return
    
    #遍历卖出股票池，并卖出
    for stk in stks_will_sell:  # stk ：股票代码
        security=stk
        number_old=context.portfolio.positions[security].closeable_amount
        #卖出，当数量>100时，卖出
        if number_old>=100:
            order_target(security,0)
            stks_will_sell.remove(stk)  # 卖出池中删除已卖出票
            # 如果全部卖出了，number_new=0，如果还没有，number_new=剩下的仓位
            if context.portfolio.positions.has_key(security)==True:
                number_new=context.portfolio.positions[security].closeable_amount
            else:
                number_new=0
            print('卖出：'+get_name(security)+':'+str(number_old-number_new)+"股~~~")
        else:
            print(get_name(security)+":可卖数不够100股，取消卖出")
        #print('--------------')
    



############以下为内部函数区############

# 返回A股所有符合条件的股票（非新股，非停牌，非创业板、非科创板,非北交所、非ST、概念股）
def get_all_stks(context):
    stock_list=get_all_securities(types=['stock'], date=None)
    
    #过滤新股，上市120天以上
    start_date=(context.current_dt - timedelta(days=g.newgu_days)).date()
    stock_list=stock_list[stock_list['start_date'] < start_date]
    
    # 将stock_list 转换成list
    stock_list=list(stock_list.index)
    
    # 过滤创业板和科创板、北交所
    stock_list=[stock for stock in stock_list if stock[0:1]!='3' ]  # 创业板
    stock_list=[stock for stock in stock_list if stock[0:2]!='68' ]  # 科创板
    stock_list=[stock for stock in stock_list if stock[0:1]!='4' ]  # 北交所
    stock_list=[stock for stock in stock_list if stock[0:1]!='8' ]  # 北交所
    
    # 过滤停牌股票
    current_data = get_current_data()
    stock_list=[stock for stock in stock_list if not current_data[stock].paused]
    
    # 过滤退市股
    stock_list=[stock for stock in stock_list if '退' not in stock]
    
    
    if g.is_only_st==1:                                # 是否仅包含ST股，当=1时，必须g.is_no_ST=0
        stock_list=[stock for stock in stock_list
	          	    if current_data[stock].is_st
		            or 'ST' in stock
		            or '*'  in stock]
        g.is_no_ST=0                                  # 强制不过滤ST股
        
    # 过滤ST
    if g.is_no_ST==1:
        stock_list=[stock for stock in stock_list
	          	    if not current_data[stock].is_st
		            and 'ST' not in stock
		            and '*' not in stock]

    # 过滤概念股  #g.get_stks_all_or_concept="concept"    #"concept":概念股
    if g.get_stks_all_or_concept=="concept":
        concept_stks=get_concept_stks(context)
        stock_list = [stock for stock in stock_list if stock in concept_stks]
    #print("全局股票池共:{0}".format(len(stock_list)))
    return stock_list 

# 返回所有的概念股
def get_concept_stks(context):
    concept_stks=[]
    for concept in g.get_stks_concept.keys():                  # 在全局变量中定义概念字典
        concept_stks+=get_concept_stocks(concept)             # 可能存在重复

    # 去重复并返回
    return quchong(concept_stks)

# 过滤股票:相对昨日限价：price<LLV(c,120)*1.5 
def max_price_limit(context,stks):
    tmp_stks=[]
    for stk in stks:
        if get_price_limit(security=stk)==False:   #超过：true ，未超过：false 
            tmp_stks.append(stk)
    #print("is_max_price_limit->:{0}".format(len(tmp_stks)))    
    return tmp_stks


# 某股票是否超过限价  price<LLV(c,days)*1.5  
def get_price_limit(security='002487.XSHE'):
    '''
    输入：
        security:  要查询股票的代码
    输出：
        result:  近期是否超过限价，超过：true ，未超过：false  
    '''
    data=attribute_history(security=security,count=g.max_price_days+1,unit='1d')
    min_price=data[0:g.max_price_days]["close"].min()
    price=data["close"][-1]                     # 昨天收盘价
    
    if price>min_price*g.max_price:
        return True
    else:
        return False

# 连板
def is_lianban_zt(context,stks):
    tmp_stks=[]  #返回的数组
    for stk in stks:
        if get_lianban_zt(context,security=stk)==True:      #返回值：是：true ，否：false 
            tmp_stks.append(stk)
    #print("is_lianban_zt->:{0}".format(len(tmp_stks)))   
    return tmp_stks
 
#某股票是否连板 + 连板期间持续放量 + 连板最后1天放量+ ma60向上 +最后一天正常涨停 + N天内涨幅正常
def get_lianban_zt(context,security='002487.XSHE'):
    result=True                                                                          # 连板结果，默认：是
    infor=get_name(security)+":"                                                         # 提示语句，最后统一显示
    
    # 区分是否ST，并确定涨停比例
    zt=1.099                                                                             # 默认涨停的涨幅
    if stk_is_st(security)==True:
        zt=1.0495
    # n天连板
    data=attribute_history(security=security,count=g.lianban_zt_days+1,unit='1d')        #取g.lianban_zt_days+1天的K线，用来验证是否连板  
    for i in range(g.lianban_zt_days):
        if data["close"][i]!=0 and data["close"][i+1]/data["close"][i]<zt:
            return False                                                                 # 只要有一天没涨停，就返回false
    
    #连板期间n天放量
    if g.lianban_zt_fangliang==1:
        data=attribute_history(security=security,count=g.lianban_zt_days+4,unit='1d')        # 如g.lianban_zt_days=3，则只需7天的K线:[0 1 2 3 4 5 6] 
        n=0                                                                                  # 放量天数
        for i in range(g.lianban_zt_days):
            if data["volume"][i+4]>=data[i:i+4]["volume"].mean():                            # 判断v>ma(v,5)
                n+=1
        if n<g.lianban_zt_fangliang_days:                                                     # 默认 g.lianban_zt_fangliang_days=3
                infor+="N天内放量达不到，放弃;"
                result=False
                #return False                                                                 # 如果放量天数小于设定，就返回false
                

    #  # 连板期间最后1天成交量>ma(v,5)的倍数,g.lianban_zt_lastday_fangliang=1.5
    if g.lianban_zt_lastday_fangliang>0:
         g.security=security                                                                  # ma()需要用到    
         v    =ma(type='v',n=1)
         v_ma5=ma(type='v',n=5)
         if v<v_ma5*g.lianban_zt_lastday_fangliang:
             infor+="最后1天量能达不到，放弃;" 
             result=False
             #return False

    # ma60向上
    if g.lianban_zt_ma60==1:  
        g.security=security
        if ma(n=60,ref=1)>ma(n=60):
            infor+="MA60向下，放弃;"
            result=False
            #return False
     
    # g.lianban_zt_lastday_normal_zt=1  # 连板期间最后1天要正常涨停，非一字板、非T字板
    if g.lianban_zt_lastday_normal_zt==1:
        data=attribute_history(security=security,count=2,unit='1d')
        ref_c=data['close'][0]
        o=data['open'][1]
        c=data['close'][1]
        l=data['low'][1]
        h=data['high'][1]
        if o==c and l==c:
            infor+="最后1天一字板，放弃;"
            result=False
            #return False
        if o==c and l!=c:
            infor+="最后1天T字板，放弃;"
            result=False    
            #return False

    # 取n天内的平均涨幅，防止短期涨幅过大  
    # 当上面的判断=false时，直接跳过，避免在下面重新=true
    if result==True and  g.lianban_zt_pjzf_kz==1:            # 连板期间连续n+2的平均涨幅控制，默认控制
        data=attribute_history(security=security,count=(g.lianban_zt_days+2)+1,unit='1d')   # 如果是3天，则count=3+2+1
        zf=0                                                        # 5天内总涨幅 
        for i in range(g.lianban_zt_days+2):                                          # g.stks_will_buy_sort_days=5
            zf=zf+(data["close"][i+1]/data["close"][i]-1)
        if stk_is_st(security):                                                             # 如果是ST股，则涨幅*2，从5%-》10%
            zf=zf*2                                   
        
        zf_const=0.08                                         # n天内的平均涨幅的临界点
        if g.lianban_zt_days==2:                              # 当连板2天时，过去连续4天的平均涨幅>6.5%，则放弃(5天按3%,3%,10%,10%为临界涨幅)
            zf_const=0.065
        elif g.lianban_zt_days==3:                            # 当连板3天时，过去连续5天的平均涨幅>7.2%，则放弃(5天按3%,3%,10%,10%,10%为临界涨幅) 
            zf_const=0.072
        elif g.lianban_zt_days==4:                            # 当连板4天时，过去连续6天的平均涨幅>7.6%，则放弃(6天按3%,3%,10%,10%,10%,10%为临界涨幅)  
            zf_const=0.076
        elif g.lianban_zt_days==5:                            # 当连板5天时，过去连续7天的平均涨幅>8%，则放弃(7天按3%,3%,10%,10%,10%,10%,10%为临界涨幅)  
            zf_const=0.08
        
        if zf/(g.lianban_zt_days+2)>zf_const:                 #当g.lianban_zt_days=3时，为5天；当g.lianban_zt_days=4，为6天  
            #g.stks_BeiXuan.remove(security)
            infor+="{0}日平均涨幅>{1:.2%}，放弃".format(g.lianban_zt_days+2,zf_const)
            result=False
            #return False
        else:
            infor+="{0}日平均涨幅:{1:.2%}，OK！".format(g.lianban_zt_days+2,zf/(g.lianban_zt_days+2))
            result=True
    
    print(infor)                                               # 显示提示信息
    return result


#短线顶点(60分钟线)
# 高开>3% + v>ma（v，5） + 跌（突破暴跌，后期反包后可再买入）  
# 暴跌>5% + v>ma(v,5)*1.5
# 日线：5日死叉10日；放量阴线  
def is_duanxian_ding(context,stk):
    is_ding=False                                                      # 见顶标志
   
    #短线顶点(60分钟线)
    # 1. 高开>5% + v>ma（v，5） + 跌（突破暴跌，后期反包后可再买入）
    # 2. 暴跌>5% + v>ma(v,5)*1.5
    data=attribute_history(security=stk,count=11,unit='60m')
    close_ref=data["close"][-2]                                        # 前日收盘价
    open     =data["open"][-1]                                         # 昨日开盘价
    close    =data["close"][-1]                                        # 昨日收盘价       --为了避免未来函数，全部推前1天 
    v        =data["volume"][-1]                                       # 昨日量能
    ma5_v    =data[-5:-1]["volume"].mean()                               # 5日平均量能
    if close_ref!=0:
        # 60分线：高开>5% + v>ma（v，5） + 跌
        if (open-close_ref)/close_ref>=0.05 and v>ma5_v and close<open:
            print("{0}短线见顶:高开+放量+跌".format(get_name(stk)))
            is_ding=True
        # 60分线：暴跌>5% + v>ma(v,5)*1.5
        if (close-close_ref)/close_ref<-0.05 and v>ma5_v*1.5:
            print("{0}短线见顶:放量暴跌".format(get_name(stk)))
            is_ding=True
    
    # 3. MA20下叉MA30 
    g.security=stk                                    #ma()需要使用g.security   
    if ma(n=20,unit='60m')<ma(n=30,unit='60m'):
        print("{0}短线见顶:ma20下叉ma30".format(get_name(stk)))
        is_ding=True
    
    #短线顶点（日线）：
    # 1. 高开放量阴线
    open  =ma(type='o',n=1)                                        # 昨日开盘价
    close =ma(type='c',n=1)                                        # 昨日收盘价       --为了避免未来函数，全部推前1天 
    close_ref=ma(type='c',n=1,ref=1)
    v     =ma(type='v',n=1)
    ma5_v =ma(type='v',n=5)
    if (open-close_ref)/close_ref>0.04 and v>ma5_v and open>close  : 
        print("{0}短线见顶:高开放量阴线".format(get_name(stk)))
        is_ding=True
    return is_ding

############以下为公共函数区############
# 判断是否ST
def stk_is_st(security):
    current_data = get_current_data()
    if  current_data[security].is_st or ( 'ST' in security) or ( '*'  in security):
        return True                                                                        #是ST
    return False

# 对stks_will_buy进行排序:按升序或降序排列，  
# reverse = False 降序
def stks_buy_sort(stks_will_buy,reverse = False): 
    # 参数stks_will_buy为:{stk:和最低价的比}
    result_stks_list=list()   #返回存放股票池的数组，按顺序存放[stk1,stk2....]
    
    bili=list()     #  临时存放stks_will_buy中股票的差值比例    
    for stk in stks_will_buy.keys():
        bili.append(stks_will_buy[stk])      # 将stks_buys列表中的MA值加到ma_tmp中
    bili.sort(reverse=reverse)               # reverse = True是按升序排列
    
    for ma_ in bili:
        for stk in stks_will_buy.keys():
            if ma_ ==stks_will_buy[stk]:                  # 按ma_tmp的顺序将stk放到result_stks_list中
                result_stks_list.append(stk)
    
    return result_stks_list  

#type:类型：c，v,o  
#n:提前天数
#默认操作的股票是常量:g.security
def ref(type='c',n=0):
    stk=g.security
    result=0 #返回的当天结果
    
    # 获取过去n+ref天的数据
    data=attribute_history(security=stk,count=n+1,unit='1d')
    print(data[0:n+1])
    
    # 第一条，即为需要的数据
    if type.lower()=='c':
        result=data[0:1]["close"].mean()
        #print("过去{0}天{1}日均线为：{2}".format(ref,n,result))
    if type.lower()=='v':
        result=data[0:1]["volume"].mean()
    if type.lower()=='o':
        result=data[0:1]["open"].mean()
    
    return result


## 个股均线ma,+REF参数  
#type:类型：C，v
#n:均线的天数
#ref: 均线提前天数
#unit:1d,1m ,60m......
def ma(type='c',n=5,ref=0,unit='1d'):
    stk=g.security
    result=0 #返回的当天结果
    
    # 获取过去n+ref天的数据
    data=attribute_history(security=stk,count=n+ref,unit=unit)
    
    # 从第一条开始到第N条，即为均线需要的数据
    if type.lower()=='c':
        result=data[0:n]["close"].mean()
        #print("过去{0}天{1}日均线为：{2}".format(ref,n,result))
    if type.lower()=='v':
        result=data[0:n]["volume"].mean()
        #print("过去{0}{1}日均量线为：{2}".format(ref,n,result))
    if type.lower()=='o':
        result=data[0:n]["open"].mean()
        #print("过去{0}{1}日开盘价均线为：{2}".format(ref,n,result))    
    
    return result

## x线上穿y线
def cross(x,y,unit='1d'):
    result=False
    ma_x=ma('c',x,0,unit)
    ma_y=ma('c',y,0,unit)
    
    ma_x_ref=ma('c',x,1,unit)
    ma_y_ref=ma('c',y,1,unit)
    
    if ma_x>=ma_y and ma_x_ref<ma_y_ref:
        result=True
    else:
        result=False
    return result


#动态止损,(60分钟线判断一次，便于盘中止损）：
# 返回值：result:止损比例。result>0，则触发止损，=0，则不需要止损。 
def is_zhishun(context,stk):
    result=0 # 默认不止损，当result>0，为止损，同时结果为止损价
    
    if len(g.zhishun_price)==0:
        return result
    
    g.security=stk
    price_new=ma('c',1,unit='60m')  #昨日收盘价  
    price_avg=context.portfolio.positions[g.security].avg_cost  #平均持仓成本
    if price_avg!=0:
        print("{0}盈利：{1:.2%}".format(get_name(stk),(price_new-price_avg)/price_avg))
    
    new_zhishun_price=price_new*(1+g.zhishun_one_point)   #止损价=最高价-15%
   
    # 不断提高止损比例    
    if new_zhishun_price>g.zhishun_price[g.security]:
        g.zhishun_price[g.security]=new_zhishun_price 
    
    if price_new<g.zhishun_price[g.security]:   #现价与全局变量中的止损价对比
        result=g.zhishun_price[g.security] # 返回止损价格
        print('{0}触发止损！，止损价：{1:}'.format(get_name(g.security),result))

    return result  #当result>0，为止损，同时为止损价

# 通过代码返回股票名称
def get_name(stk):
    return get_security_info(stk).display_name+':'+stk[:6]
    
# list去重复
# a:列表
def quchong(a):
    b=[]
    for x in a:
        if x not in b:
            b.append(x)
    return b
    
# 股票对应的大盘  ，返回"sz"、"sh"  
def stk_to_dapan(stock):
    result="sh"
    if stock[0:3]=='000'  or stock[0:3]=='001' or stock[0:3]=='002' or stock[0:3]=='003':
        result="sz"
    elif stock[0:3]=='600' or stock[0:3]=='601'or stock[0:3]=='603' or stock[0:3]=='605':
        result="sh"
    return result 
        
    
    
