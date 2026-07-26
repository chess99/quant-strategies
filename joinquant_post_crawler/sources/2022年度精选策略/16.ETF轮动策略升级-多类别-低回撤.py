# 克隆自聚宽文章：https://www.joinquant.com/post/35959
# 标题：ETF轮动策略升级-多类别-低回撤
# 作者：宋兵乙

# 调整为每日收盘后运行计算交易信号，第二个交易日进行交易

from jqdata import *
import pandas as pd
import talib as ta
import smtplib
from email.header import Header
from email.mime.text import MIMEText

import prettytable as pt

def initialize(context):
    
    g.purchases = []
    g.sells = []
    # 设置交易参数
    set_params()
    
    set_option("avoid_future_data", True)
    set_option('use_real_price', True)      # 用真实价格交易
    set_benchmark('000300.XSHG')
    log.set_level('order', 'error')
    #
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 手续费: 采用系统默认设置
    set_order_cost(OrderCost(open_tax=0, close_tax=0, \
        open_commission=0.00005, close_commission=0.00005,\
        close_today_commission=0, min_commission=0), type='stock')
        
    # 开盘前运行
    run_daily(before_market_open, time='21:00', reference_security='000300.XSHG')
 
    # 21:00 计算交易信号
    run_daily(get_signal, time='21:00')
    # 9:35 进行交易
    run_daily(ETF_trade, time='9:32')


# 设置参数
def set_params():

    g.target_market = '000300.XSHG'
    
    g.moment_period = 13                # 计算行情趋势的短期均线
    g.ma_period = 10                    # 计算行情趋势的长期均线
    
    g.type_num = 5                      # 品种数量

    g.ETF_targets =  {
        # # A股指数ETF
        '000300.XSHG':'510300.XSHG',        # 沪深300
        '399006.XSHE':'159915.XSHE',        # 创业板

        # # 国际期货
        '518880.XSHG':'518880.XSHG',        # 黄金ETF
        '501018.XSHG':'501018.XSHG',        # 南方原油
        '161226.XSHE':'161226.XSHE',        # 白银基金
        
        # # 国内期货
        '159985.XSHE':'159985.XSHE',        # 豆粕ETF
        '159981.XSHE':'159981.XSHE',        # 能源化工ETF
        '159980.XSHE':'159980.XSHE',        # 有色期货
        
        # # 全球股指
        '513100.XSHG':'513100.XSHG',        # 纳斯达克ETF
        '513030.XSHG':'513030.XSHG',        # 德国ETF
        '513520.XSHG':'513520.XSHG',        # 日经ETF
        '164824.XSHE':'164824.XSHE',        # 印度基金

        # # REITs
        '180301.XSHE':'180301.XSHE',        # 盐田港REITs
        '180801.XSHE':'180801.XSHE',        # 绿能REITs
        '180101.XSHE':'180101.XSHE',        # 蛇口产业园
        '184801.XSHE':'184801.XSHE',        # 前海REITs
    }
    
    # A股指数
    g.local_stocks  = [
        '510300.XSHG',        # 沪深300
        '159915.XSHE',        # 创业板
        
        ]
    # 全球股指
    g.global_stocks = [
        '513100.XSHG',        # 纳斯达克ETF
        '164824.XSHE',        # 印度基金
        '513030.XSHG',        # 德国ETF
        '513520.XSHG',        # 日经ETF
    ]
    # 国内期货
    g.local_futures = [
        '159980.XSHE',        # 有色期货
        '159981.XSHE',        # 能源化工ETF
        '159985.XSHE',        # 豆粕ETF
        
        ]
    # 全球期货
    g.global_futures = [
        '161226.XSHE',        # 白银基金
        '518880.XSHG',        # 黄金ETF
        '501018.XSHG',        # 南方原油
        
        ]
    # REITs
    g.REITs = [
        '180101.XSHE',        # 蛇口产业园
        '180301.XSHE',        # 盐田港REITs
        '180801.XSHE',        # 绿能REITs
        '180201.XSHE',        # 广州广河REITs
        '184801.XSHE',        # 前海REITs
        ]
    
    # 打印品种上市信息
    stocks_info = "\n股票池:\n"
    for security in g.ETF_targets.values():
        s_info = get_security_info(security)
        stocks_info += "【%s】%s 上市日期:%s\n" % (s_info.code, s_info.display_name, s_info.start_date)
    log.info(stocks_info)

def get_before_after_trade_days(date, count, is_before=True):
    """
    来自： https://www.joinquant.com/view/community/detail/c9827c6126003147912f1b47967052d9?type=1
    date :查询日期
    count : 前后追朔的数量
    is_before : True , 前count个交易日  ; False ,后count个交易日
    返回 : 基于date的日期, 向前或者向后count个交易日的日期 ,一个datetime.date 对象
    """
    all_date = pd.Series(get_all_trade_days())
    if isinstance(date, str):
        date = datetime.datetime.strptime(date, '%Y-%m-%d').date()
    if isinstance(date, datetime.datetime):
        date = date.date()

    if is_before:
        return all_date[all_date <= date].tail(count).values[0]
    else:
        return all_date[all_date >= date].head(count).values[-1]

def before_market_open(context):

    # 确保交易标的已经上市g.moment_period个交易日以上
    yesterday = context.previous_date
    list_date = get_before_after_trade_days(yesterday, g.moment_period+1)  # 今天的前g.moment_period个交易日的日期
    g.ETFList = {}
    
    #筛选品种，将上时间不足的品种排除
    all_funds = get_all_securities(types='fund', date=yesterday)   # 上个交易日之前上市的所有基金
   
    for idx in g.ETF_targets:

        symbol = g.ETF_targets[idx]
        if symbol in all_funds.index:
            if all_funds.loc[symbol].start_date <= list_date:  # 对应的基金也已经在要求的日期前上市
                g.ETFList[idx] = symbol                              # 则列入可交易对象中
    return

# 每日交易时
def ETF_trade(context):
    
    # 1. 卖出
    if len(g.sells)>0:
        for code in g.sells:
            log.info("卖出: %s" % code)
            order_target(code, 0)
    
    # 2. 买入
    if len(g.purchases)>0:
        for code in g.purchases:
            log.info('买入: %s' % code)
            order_target(code,g.df_etf[g.df_etf['基金代码'] == code]['股数'].values)

# 获取信号
def get_signal(context):
   
    # 创建保持计算结果的DataFrame
    g.df_etf = pd.DataFrame(columns=['基金代码', '基金名称','涨幅','均线状态','股数'])
    g.df_local_stocks = pd.DataFrame(columns=['基金代码', '基金名称','涨幅','均线状态','股数'])
    g.df_global_stocks = pd.DataFrame(columns=['基金代码', '基金名称','涨幅','均线状态','股数'])
    g.df_local_futures = pd.DataFrame(columns=['基金代码', '基金名称','涨幅','均线状态','股数'])
    g.df_global_futures = pd.DataFrame(columns=['基金代码', '基金名称','涨幅','均线状态','股数'])
    g.df_reits = pd.DataFrame(columns=['基金代码', '基金名称','涨幅','均线状态','股数'])
    
    total_value = context.portfolio.total_value
    current_data = get_current_data()
    print("\n总资产:{:.2f}万".format(context.portfolio.total_value/10000))
    
    # 获取当前时间
    current_time = context.current_dt
    
    for mkt_idx in g.ETFList:
        security = g.ETFList[mkt_idx]  # 指数对应的基金
        
        etf_name = get_security_info(security).display_name
        # 获取股票现价
        price_data = get_price(security, end_date=current_time, frequency='1d', fields=['close','high','low'], count=g.moment_period+1)
        
        # 今日收盘价
        now_close = price_data['close'][-1]
        # g.moment_period日前收盘价
        previous_close = price_data['close'][-g.moment_period]
       
        # 计算均线
        ma_filter = ta.MA(price_data.close.values, g.ma_period)[-1]
        
        # 计算动量
        ma_status = now_close - ma_filter
        moment = (now_close - previous_close)/previous_close * 100

        # 计算持仓数量
        amount = int(total_value / now_close / g.type_num /100)*100
            
        g.df_etf = g.df_etf.append({'基金代码': security, 
                                '基金名称': etf_name,
                                '涨幅': moment,
                                '均线状态': ma_status,
                                '股数': amount,
                                },
                                ignore_index=True)
    g.df_etf.sort_values(by='涨幅' ,axis=0, ascending=False, inplace=True)
                            
    tb = pt.PrettyTable()
    
    #添加列数据
    tb.add_column('Index',g.df_etf.index)
    tb.add_column('ETF Code',list(g.df_etf['基金代码']))
    tb.add_column('Name',list(g.df_etf['基金名称']))
    tb.add_column('Moment',list(g.df_etf['涨幅'].values.round(2)))
    tb.add_column('Ma_Status',list(g.df_etf['均线状态'].values.round(2)))
    tb.add_column('Amount',list(g.df_etf['股数']))
    log.info('\n行情统计: \n%s' % tb)
    
    # 根据涨幅和均线状态筛选品种
    g.df_etf_buy = g.df_etf.copy()
    g.df_etf_buy = g.df_etf_buy[g.df_etf_buy['涨幅'] > 0]
    g.df_etf_buy = g.df_etf_buy[g.df_etf_buy['均线状态']  > 0]
    # 根据品种类别分为不同的DataFrame
    g.df_local_stocks = g.df_etf_buy.loc[g.df_etf_buy['基金代码'].isin(g.local_stocks)]
    g.df_global_stocks = g.df_etf_buy.loc[g.df_etf_buy['基金代码'].isin(g.global_stocks)]
    g.df_local_futures = g.df_etf_buy.loc[g.df_etf_buy['基金代码'].isin(g.local_futures)]
    g.df_global_futures = g.df_etf_buy.loc[g.df_etf_buy['基金代码'].isin(g.global_futures)]
    g.df_reits = g.df_etf_buy.loc[g.df_etf_buy['基金代码'].isin(g.REITs)]
    
     # 现在持仓的
    g.holdings = set(context.portfolio.positions.keys())
    g.targets = []
    
    if len(g.df_local_stocks) > 0:
        g.targets.append(g.df_local_stocks.iloc[0]['基金代码'])
    if len(g.df_global_stocks) > 0:
        g.targets.append(g.df_global_stocks.iloc[0]['基金代码'])
    if len(g.df_local_futures) > 0:
        g.targets.append(g.df_local_futures.iloc[0]['基金代码'])
    if len(g.df_global_futures) > 0:
        g.targets.append(g.df_global_futures.iloc[0]['基金代码'])
    if len(g.df_reits) > 0:
        g.targets.append(g.df_reits.iloc[0]['基金代码'])
    
    content = '交易计划：\n'
            
    g.sells = [i for i in g.holdings if i not in (g.targets)]
    g.purchases = [i for i in g.targets if i not in (list(g.holdings))] 
    
    # 1. 卖出不在targets中的
    if len(g.sells)>0:

        df_sells = g.df_etf.loc[g.df_etf['基金代码'].isin(g.sells)]
        tb = pt.PrettyTable()
        #添加列数据
        # tb.add_column('Index',df_sells.index)
        tb.add_column('ETF Code',list(df_sells['基金代码']))
        tb.add_column('Name',list(df_sells['基金名称']))
        
        str_more = '\n计划卖出: \n' + str(tb)
        content = content + str_more
        
        log.info(str_more)
        send_message(str_more)
    
    if len(g.purchases)>0:
        
        df_purchase = g.df_etf.loc[g.df_etf['基金代码'].isin(g.purchases)]
        tb = pt.PrettyTable()
        #添加列数据
        tb.add_column('Index',df_purchase.index)
        tb.add_column('ETF Code',list(df_purchase['基金代码']))
        tb.add_column('Diaplay Name',list(df_purchase['基金名称']))
        tb.add_column('Amount',list(df_purchase['股数']))
        
        str_more = '\n计划买入：\n' + str(tb)
        content = content + str_more
        
        log.info(str_more)
        send_message(str_more)
        
    if (len(g.sells) == 0) and (len(g.purchases) == 0):
        
        str_more = '\n无交易计划: \n'
        content = content + str_more
        
        log.info('\n无交易计划: \n')
        send_message('\n无交易计划: \n')
    title = str(current_time)[:10] + '_ETF_轮动交易计划'
    # sendEmail(title, content)
            
    return
