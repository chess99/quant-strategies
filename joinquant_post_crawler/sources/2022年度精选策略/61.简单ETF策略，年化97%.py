# 克隆自聚宽文章：https://www.joinquant.com/post/36717
# 标题：简单ETF策略，年化97%
# 作者：奶牛哥

'''
#版本：ETF 3.0：
#日期：2022.2.20
#作者：花奶牛

---------------------------------------------------------------------------------
##逻辑设定:  
#A:操作目标 ：ETF池
#B:仓位     ：每次买入满仓、卖出空仓   
#C:买入选股 ：当MA60向上 + 价格<MA60 + MA5向上    
#D.卖出选股 ：cross(ma20,ma10)  
'''

# 导入函数库  
from jqdata import *
from jqlib.technical_analysis import *
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr

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

    #---以下为参数设置区--------
    # 1. ETF池
    g.all_stks=['399306.XSHE','159608.XSHE','159611.XSHE','159613.XSHE','159619.XSHE','159707.XSHE','159713.XSHE','159731.XSHE','512690.XSHG','516950.XSHG','512880.XSHG','516880.XSHG','515030.XSHG','515220.XSHG','515210.XSHG','512710.XSHG','159870.XSHE','159995.XSHE','512150.XSHG','588080.XSHG','159952.XSHE','512800.XSHG','515950.XSHG','159945.XSHE']
    
    # 2. 定义同时持仓股票的数量,即将资金分成几等分
    g.max_number=1 
    
    # 3. 发送提示邮件
    g.is_sendmail=0                     # 是否发送邮件，如需发邮件，请设置为1
    g.mail_subject='ETF3.0:'            # 模拟运行时发提示邮件的标题前缀
    g.mail_sender = ''                  # 发件人邮箱账号，请修改
    g.mail_passwd = ''                  # 发件人邮箱密码，请修改
    g.mail_receiver = ''                # 收件人邮箱账号，请修改
    
    #---以下为全局变量区域---------
    g.stks_buy=[]                       # 买入选股的结果
    g.stks_sell=[]                      # 从持仓中选出的要卖股票，
    g.mail_msg=''                       # 模拟运行时发提示邮件的内容
    g.money=context.portfolio.starting_cash/g.max_number    #默认每个股票分配的总资金
    #-------------------------------------------------

    #买入选股，半夜执行，不受白天交易影响
    run_daily(xuangu_buy,time='2:00')
    
    #卖出选股，半夜执行，不受白天交易影响  
    run_daily(xuangu_sell,time='3:00')
    
    # 买入
    run_daily(buy, time='10:00')
    
    # 卖出或止损
    run_daily(sell,time='10:00')
    

#买入选股
#选出股票的数据，内容为 {代码:(形态，权重)}
def xuangu_buy(context):
    g.stks_buy=[]  # 买入选股，每天默认为空；
    print('###################')
    print_and_mail('-----买入选股-----')
    for stk in g.all_stks:              
        g.security=stk                              #ma()中使用 g.security判断

        # MA60向上 + 价格<MA60 + MA5向上
        price_now=ma(n=1)
        if ma(n=60,ref=2)<=ma(n=60,ref=1) and  ma(n=60,ref=1)<=ma(n=60):
            if price_now<ma(n=60):
                if ma(n=5,ref=1)<ma(n=5) :
                    g.stks_buy.append(stk)
                 
    #选出的股票列表
    if len(g.stks_buy)>0:
        for stk in g.stks_buy: 
            print_and_mail('加入买入池：'+get_name(stk))
    else:
        print_and_mail('备选池：无！')

#卖出选股  
def xuangu_sell(context):
    g.stks_sell=[]  #从持仓中选出的要卖股票，每天默认为空
    
    print_and_mail('-----卖出选股-----')
    
    for stk in context.portfolio.positions.keys():
        g.security=stk #更新全局变量
        print_and_mail('今日持股：{0},盈亏比：{1:.2%}'.format(get_name(g.security),(ma(n=1)-context.portfolio.positions[stk].avg_cost)/context.portfolio.positions[stk].avg_cost)) 
        
        #1.均线下穿
        if cross(20,10) :
            print_and_mail(str(stk) +':均线死叉！')
            g.stks_sell.append(stk)  

    if len(g.stks_sell)>0:           #显示卖出池的股票
        for stk in g.stks_sell:
            print_and_mail('进入卖出池：'+get_name(stk))
    else:
        print_and_mail('卖出池：无！')

    if len(g.stks_buy)>0 or len(g.stks_sell)>0 :
        mail_to(subject=g.mail_subject+str(context.current_dt),msg=g.mail_msg)
        

## 买入
def buy(context):
    print_and_mail('-----买    入-----')
    
    if len(g.stks_buy)==0:
        print('无')
        return
    
    #遍历池中所有的股票，按顺序买入
    for stk in g.stks_buy:
        # 非停牌，
        current_data = get_current_data()
        if current_data[stk].paused==True:
            print_and_mail(get_name(stk)+":停牌，放弃买入！")
            continue

        # 当持仓中已有时，不买
        if stk in context.portfolio.positions.keys():
            print_and_mail(get_name(stk)+":已持仓，放弃买入！")
            continue
        
        # 当持仓数大于最大持仓数时
        if len(context.portfolio.positions)>=g.max_number:   # 每买入一只后都要重新判断是否超过最大限度
            print_and_mail("已达到最大持仓数，放弃买入！")
            continue  

        #买入 
        if context.portfolio.positions.has_key(stk)==False:  
            order_value(stk,g.money)
            # 可能因为涨停买不到
            if context.portfolio.positions.has_key(stk)==True:
                print_and_mail("买入：{0}：总仓位:{1}，均价:{2}".format(get_name(stk),context.portfolio.positions[stk].total_amount,round(context.portfolio.positions[stk].avg_cost,2)))
            else:
                print_and_mail("{0}:买入不成功！".format(get_name(stk)))

# 卖出
def sell(context):

    print_and_mail('-----卖    出-----')
    if len(g.stks_sell)==0:
        print('无')
    
    #遍历卖出股票池，并卖出
    for stk in g.stks_sell:  # stk ：股票代码
        number_old=context.portfolio.positions[stk].total_amount
        #卖出
        order_target(stk,0)
        # 如果全部卖出了，number_new=0，如果还没有，number_new=剩下的仓位
        if context.portfolio.positions.has_key(stk)==True:
            number_new=context.portfolio.positions[stk].total_amount
        else:
            number_new=0
        print_and_mail('卖出：'+get_name(stk)+':'+str(number_old-number_new)+"股")
        print_and_mail('--------------')
        
    if len(g.stks_buy)>0 and len(g.stks_sell)>0 :
        mail_to(subject=g.mail_subject+str(context.current_dt),msg=g.mail_msg)
    

############以下为公共函数区############    
## 个股均线ma,+REF参数  
def ma(type='c',n=5,ref=0,unit='1d'):
    stk=g.security   # 需先设置g.security
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

## N天内的最小值最大值min_max,+REF参数
def min_max(type='l',n=1):
    result=0                #返回的结果
    # 获取过去n天的数据
    data=attribute_history(security=g.security,count=n,unit='1d')
    
    # 从第一条开始到第N条，即为均线需要的数据
    if type.lower()=='h':
        result=data[:]["high"].max()
    if type.lower()=='l':
        result=data[:]["low"].min()
    return result

# 通过代码返回股票名称
def get_name(stk):
    return get_security_info(stk).display_name+':'+stk[:6]
    
# 发邮件功能
def mail_to(subject,msg):
    if g.is_sendmail==0:
        return
    
    print('发送邮件....')
    sender = g.mail_sender                              # 发件人邮箱账号
    passwd = g.mail_passwd                              # 发件人邮箱密码
    receiver = g.mail_receiver                          # 收件人邮箱账号，我这边发送给自己
    msg = MIMEText(str(msg), 'plain','utf-8')
    msg['From'] = formataddr(["花奶牛", sender])        # 括号里的对应发件人邮箱昵称、发件人邮箱账号
    msg['To'] = formataddr(["me", receiver])            # 括号里的对应收件人邮箱昵称、收件人邮箱账号
    msg['Subject'] = subject                            # 邮件的主题，也可以说是标题

    try:
        server = smtplib.SMTP_SSL("smtp.qq.com", 465)                # 发件人邮箱中的SMTP服务器，端口是25
        server.login(sender, passwd)                                 # 括号中对应的是发件人邮箱账号、邮箱密码
        server.sendmail(sender, [receiver], msg.as_string())         # 括号中对应的是发件人邮箱账号、收件人邮箱账号、发送邮件
        server.quit()                                                # 关闭连接

    except Exception:                                                 # 如果 try 中的语句没有执行，则会执行下面的 ret=False
        print("邮件发送失败")
        return
    print("邮件发送成功")
    g.mail_msg=''

# 显示信息，并且添加到g.mail_msg中
def print_and_mail(msg):
    print(msg)
    g.mail_msg+=msg+'\n'

# 通过代码返回股票名称
def get_name(stk):
    return get_security_info(stk).display_name+':'+stk[:6]
