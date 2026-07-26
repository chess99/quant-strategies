# 克隆自聚宽文章：https://www.joinquant.com/post/37233
# 标题：真真正正的诚意之作-2021超十倍
# 作者：Bobby1129

# 导入函数库
from jqdata import *
import datetime
import pandas as pd
from dateutil.relativedelta import relativedelta

pd.set_option('display.max_columns', 16)
pd.set_option('display.width', 5000)

# 初始化函数，设定基准等等
def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # avoid_future_data
    #set_option("avoid_future_data", True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    # log.set_level('order', 'error')

    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')

    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
      # 开盘前运行
    run_daily(before_market_open, time='before_open', reference_security='000300.XSHG')
      # 开盘中运行
    run_daily(deal_stock, time='9:32', reference_security='000300.XSHG')
    run_daily(holder_monitor, time='14:55', reference_security='000300.XSHG')
    run_daily(holder_monitor, time='9:50', reference_security='000300.XSHG')
    ###check how many weeks
    g.weeks = 48
    g.ratio = 0.85
    g.go_up_r = 1.05
    g.up_line = 0.4
    g.cdh = 1.35   ###当前价格超过最高价多少
    g.nb_list = []

## 开盘前运行函数
def before_market_open(context):
    # output datetime
    now_time=context.current_dt
    g.trade_days = get_trade_days(end_date=now_time,count=5)
    check_time=(now_time-datetime.timedelta(days=560)).strftime('%Y-%m-%d')
    #获取所有股票代码
    codes = get_all_securities(date=check_time)
    g.security = some_filter(codes)
    g.already_list = []
    weekday = now_time.weekday()
    if weekday == 0:
        g.nb_list = []

### buy and sell at determined time
def deal_stock(context):
    cur_cash = context.portfolio.available_cash
    if cur_cash>5000 and len(g.already_list)<=4:
        ###buy stock
        security=g.security
        stocks_list = stock_filter(security,context,g.weeks)
        if stocks_list is not None:
            for stock in stocks_list:
                if len(g.already_list) <= 4:
                    if stock not in g.nb_list:
                        g.nb_list.append(stock)
                        position_list = list(context.portfolio.positions.keys())
                        if stock not in position_list:
                            cur_data = get_current_data()
                            if cur_data[stock].last_price == cur_data[stock].high_limit:
                                pass
                            else:
                                buy_status=EMA_ratio(stock,context.current_dt,5,10)
                                sell_status=sell_condition(stock,context.current_dt,'1w',1.06)
                                if buy_status=='good' and sell_status!='sell':
                                    g.already_list.append(stock)
                else:
                    break
            if len(g.already_list)>0:
                unit_cash=cur_cash/(len(g.already_list))
                for stock in g.already_list:
                    order_value(stock,unit_cash)

def holder_monitor(context):
    position_list = list(context.portfolio.positions.keys())
    if len(position_list) > 0:
        for stock in position_list:
            sell_available = context.portfolio.positions[stock].closeable_amount
            if sell_available>0:
                cur_price = context.portfolio.positions[stock].price
                avg_cost = context.portfolio.positions[stock].avg_cost
                if context.current_dt.hour==9:
                    print(cur_price,avg_cost)
                    if cur_price/avg_cost>=0:
                        init_date = context.portfolio.positions[stock].init_time
                        ### just avoid_future_data
                        get_high = get_price(stock,start_date=init_date,end_date=context.current_dt,frequency='minute',fields=['high'])
                        high_price = get_high['high'].max()
                        sell_status = sell_condition(stock,context.current_dt,'1d',1.06)
                        if sell_status == 'sell':
                            order_target_value(stock,0)
                        elif cur_price/high_price<=g.ratio:
                                log.info('######################sell the stock to stop it###########################')
                                order_target_value(stock,0)
                elif context.current_dt.hour==14:
                    init_date = context.portfolio.positions[stock].init_time
                    ### just avoid_future_data
                    get_high = get_price(stock,start_date=init_date,end_date=context.current_dt,frequency='minute',fields=['high'])
                    high_price = get_high['high'].max()
                    sell_status = sell_condition(stock,context.current_dt,'1d',1.02)
                    if sell_status == 'sell':
                        order_target_value(stock,0)
                    elif cur_price/high_price<=g.ratio:
                            log.info('######################sell the stock to stop it###########################')
                            order_target_value(stock,0)
                
###come sell condition
def sell_condition(stock,c_date,frq,ratio):
    cur_week = Pro_Get_Bars(stock,c_date,frq,1)
    print(cur_week)
    gap_oc = cur_week.loc[0,'open']/cur_week.loc[0,'close']
    HL = cur_week.loc[0,'high']-cur_week.loc[0,'low']
    ML = max(cur_week.loc[0,'open'],cur_week.loc[0,'close'])
    US = cur_week.loc[0,'high']-ML
    if HL!=0:
        U_ratio = US/HL
        if gap_oc>ratio or U_ratio>g.up_line:
            return 'sell'
        else:
            pass

###股票的过滤和呈现
def stock_filter(security,context,count):
    check_list = Go_up(context,security)
    st_data = Pro_Get_Bars(check_list,context.current_dt,'1w',count)
    num_list = np.arange(count)
    base_list = num_list[0:-4]
    gap_list = num_list[-4:-1]
    base_data = st_data[st_data['level_1'].isin(base_list)].copy()
    gap_data = st_data[st_data['level_1'].isin(gap_list)].copy()
    cur_data = st_data[st_data['level_1']==num_list[-1]].copy()
    ###deal with base data
    bpMax = base_data.groupby('code').aggregate({'high':'max'})
    bpMin = base_data.groupby('code').aggregate({'low':'min'})
    bvMax = base_data.groupby('code').aggregate({'volume':'max'})
    ###deal with gap data
    gcMax = gap_data.groupby('code').aggregate({'close':'max'})
    gvMax = gap_data.groupby('code').aggregate({'volume':'max'})
    ###deal with cur data
    cur_data = cur_data[['code','level_1','volume','close','open','money']].copy()
    t1 = pd.merge(cur_data,bpMax,left_on='code',right_index=True,how='inner')
    t2 = pd.merge(t1,bpMin,left_on='code',right_index=True,how='inner')
    t3 = pd.merge(t2,bvMax,left_on='code',right_index=True,how='inner')
    t4 = pd.merge(t3,gcMax,left_on='code',right_index=True,how='inner')
    check_data = pd.merge(t4,gvMax,left_on='code',right_index=True,how='inner')
    param = 1####deal_weekday(context.current_dt)
    check_data['t_Raise'] = check_data['close_x']/check_data['high']
    check_data['l_Raise'] = check_data['close_y']/check_data['high']
    check_data['oc'] = check_data['close_x']/check_data['open']
    check_data['range'] = check_data['high']/check_data['low']
    check_data['vol_ratio'] = check_data['volume_x']/(check_data['volume_y']*param)
    check_data['vol_r2'] = check_data['volume_x']/(check_data['volume']*param)
    stocks_df = check_data[(check_data['t_Raise']>1)&(check_data['t_Raise']<g.cdh)&(check_data['l_Raise']<1)&(check_data['oc']>1)&(check_data['vol_ratio']>1)&(check_data['vol_ratio']<2)&(check_data['vol_r2']>1)].copy()
    stocks_df.sort_values('range',axis=0,ascending=True,inplace=True)
    stocks_df=stocks_df[['code','level_1','money','t_Raise','l_Raise','range','vol_ratio','vol_r2']].copy()
    print(stocks_df)
    stock_list = stocks_df['code'].tolist()
    return stock_list

###根据每天的市场情绪决定买入的金额
def Go_up(context,stocks):
    st_data = Pro_Get_Bars(stocks,context.current_dt,'1d',2)
    print(st_data)
    ###############todays
    ydata=st_data[st_data['level_1']==0].copy()
    tdata=st_data[st_data['level_1']==1].copy()
    mer_yt=pd.merge(ydata,tdata,on='code',how='inner')
    mer_yt['raise']=mer_yt['close_y']/mer_yt['close_x']
    mer_yt['oc']=mer_yt['close_y']/mer_yt['open_y']
    final_df=mer_yt[mer_yt['raise']>g.go_up_r].copy()
    #(mer_yt['oc']>1.02).sum()
    return final_df['code'].tolist()

###过滤paused/st/688
def some_filter(stock_df):
    s_df = stock_df[~stock_df.index.str.startswith('688')]
    s_list = s_df.index.tolist()
    cur_data = get_current_data()
    stock_list = [ stock for stock in s_list if not (cur_data[stock].is_st or
                                                    cur_data[stock].paused or
                                                    ('ST' in cur_data[stock].name) or
                                                    ('*' in cur_data[stock].name) or
                                                    ('退' in cur_data[stock].name))]
    return stock_list
        
def EMA_ratio(stock,c_date,f_num,l_num):
    close_data5 = Pro_Get_Bars(stock,c_date,'1w',f_num)
    close_data10 = Pro_Get_Bars(stock,c_date,'1w',l_num)
    ### len(close_data5or10) maybe short than f_num or l_num
    lf = len(close_data5)
    ll = len(close_data10)
    close_data5.loc[:,'cf_num'] = range(1,lf+1)
    close_data10.loc[:,'cf_num'] = range(1,ll+1)
    close_data5.loc[:,'right'] = close_data5['cf_num']/(close_data5['cf_num'].sum())
    close_data10.loc[:,'right'] = close_data10['cf_num']/(close_data10['cf_num'].sum())
    close_data5.loc[:,'righted_num'] = close_data5['close']*close_data5['right']
    close_data10.loc[:,'righted_num'] = close_data10['close']*close_data10['right']
    EMA_first = close_data5['righted_num'].sum()
    EMA_last = close_data10['righted_num'].sum()
    if EMA_first>EMA_last:
        return 'good'
    else:
        return 'bad'

def Pro_Get_Bars(c_code,c_date,units,counts):
    bar_data = get_bars(c_code,end_dt=c_date,count=counts,fields=['date','volume','money','open','close','high','low'],unit=units,df=True,include_now=True)
    bar_data = bar_data.reset_index()
    if 'level_0' in list(bar_data):
        bar_data.rename(columns={'level_0':'code'},inplace=True)
    return bar_data
