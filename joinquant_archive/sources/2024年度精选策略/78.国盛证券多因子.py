# 克隆自聚宽文章：https://www.joinquant.com/post/43307
# 标题：国盛证券多因子
# 作者：璇天凤舞

# 导入函数库
from jqdata import *
import numpy as np
import pandas as pd
from six import BytesIO, StringIO
import json 

def set_params():
    # g.benchmark = '000300.XSHG' # (HS300) 
    g.benchmark = '000001.XSHG' # (SZZS)
    g.buy_list = []
    g.stock_num = 10   # 持仓最大股票数
    g.sample_windows = 252 # 样本窗口长度
    
# 初始化函数，设定基准等等
def initialize(context):
    set_params()
    
    set_benchmark(g.benchmark)                  # 设定沪深300作为基准
    set_option('use_real_price', True)          # 开启动态复权模式(真实价格)
    log.info('初始函数开始运行且全局只运行一次')# 输出内容到日志 log.info()
    log.set_level('order', 'error')             # 过滤掉order系列API产生的比error级别低的log
    
    ## 运行函数（reference_security为运行时间的参考标的；传入的标的只做种类区分，因此传入'000300.XSHG'或'510300.XSHG'是一样的）
    run_weekly(before_market_open,  weekday=1, time='before_open', reference_security='000300.XSHG')  # 开盘前运行
    run_weekly(market_open,         weekday=1, time='9:31',        reference_security='000300.XSHG')  # 开盘时运行
    run_weekly(after_market_close,  weekday=1, time='after_close', reference_security='000300.XSHG')  # 收盘后运行

def set_trader(dt):
    # 设置交易费率
    set_slippage(FixedSlippage(0)) # 将滑点设置为0
    # 根据不同的时间段设置手续费
    if dt>datetime.datetime(2013,1, 1):
        # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
        set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003, close_commission=0.0003, min_commission=5), type='stock')
    elif dt>datetime.datetime(2011,1, 1):
        set_order_cost(OrderCost(close_tax=0.001, open_commission=0.001, close_commission=0.001, min_commission=5), type='stock')

## 开盘前运行函数
def before_market_open(context):
    log.info('函数运行时间(before_market_open)：'+str(context.current_dt.time())) # 输出运行时间
    set_trader(context.current_dt)
    
    yesterday = context.previous_date
    current_dt = context.current_dt
    
    score_df = get_comb_factor(current_dt)

    #data_file = 'data/1_Volability/{}.csv'.format(str(current_dt.date())) # 1. 波动性
    #data_file = 'data/2_Growth/{}.csv'.format(str(current_dt.date())) # 2. 成长
    #data_file = 'data/3_Reverse/{}.csv'.format(str(current_dt.date())) # 3. 反转
    #data_file = 'data/4_Leverage/{}.csv'.format(str(current_dt.date())) # 4.杠杆
    #data_file = 'data/5_Dividend/{}.csv'.format(str(current_dt.date())) # 5.红利
    #data_file = 'data/6_Value/{}.csv'.format(str(current_dt.date())) # 6.价值
    #data_file = 'data/7_Liquidity/{}.csv'.format(str(current_dt.date())) # 7.流动性
    #data_file = 'data/8_Profit/{}.csv'.format(str(current_dt.date())) # 8.盈利
    #data_file = 'data/9_Quality/{}.csv'.format(str(current_dt.date())) # 9.质量
    
    #data_df = pd.read_csv(BytesIO(read_file(data_file)), index_col=0)
    
# 1. 波动性
    #score_df = data_df['ivol_1y'].dropna().sort_values(ascending=False)
    #score_df = data_df['ivr_1y'].dropna().sort_values(ascending=False)
    #score_df = data_df['ivol_1m'].dropna().sort_values(ascending=False)
    #score_df = data_df['ivr_1m'].dropna().sort_values(ascending=False)
    #score_df = data_df['ret_std_1m'].dropna().sort_values(ascending=False)
# 2. 成长
    #score_df = data_df['yoy_bps'].dropna().sort_values() # yoy_bps 成长 (当期 BPS-去年同期 BPS)/去年同期 BPS 绝对值,其中 BPS 表示每股帐面价值
    #score_df = data_df['yoy_orps'].dropna().sort_values() # yoy_orps 成长 每股营业收入同比增长率
    #score_df = data_df['yoy_eps'].dropna().sort_values() # yoy_eps 成长 每股收益同比增速
    #score_df = data_df['yoy_tot_equity'].dropna().sort_values() # yoy_tot_equity 成长 (当期股东权益-去年同期股东权益)/去年同期股东权益绝对值
    #score_df = data_df['yoy_total_assets'].dropna().sort_values() # yoy_total_assets 成长 (当期总资产-去年同期总资产)/去年同期总资产绝对值
    #score_df = data_df['yoy_orps_q'].dropna().sort_values() # yoy_orps_q 成长 单季度每股营业收入同比增长率
    #score_df = data_df['yoy_eps_q'].dropna().sort_values() # yoy_eps_q 成长 单季度每股收益同比增速
    #score_df = data_df['yoy_ocfps'].dropna().sort_values() # yoy_ocfps 成长 每股经营现金流同比增速
    #score_df = data_df['yoy_ocfps_q'].dropna().sort_values() # yoy_ocfps_q 成长 单季度每股经营现金流同比增速
    #score_df = data_df['yoy_np'].dropna().sort_values() # yoy_np 成长 净利润同比增速
    #score_df = data_df['yoy_np_q'].dropna().sort_values() # yoy_np_q 成长 单季度净利润同比增速
    #score_df = data_df['yoy_or'].dropna().sort_values() # yoy_or 成长 营业收入同比增速
    #score_df = data_df['yoy_or_q'].dropna().sort_values() # yoy_or_q 成长 单季度营业收入同比增速
    #score_df = data_df['yoy_op'].dropna().sort_values() # yoy_op 成长 经营利润同比增速
    #score_df = data_df['yoy_op_q'].dropna().sort_values() # yoy_op_q 成长 单季度经营利润同比增速
    #score_df = data_df['yoy_ocf'].dropna().sort_values() # yoy_ocf 成长 经营现金流同比增速
    #score_df = data_df['yoy_ocf_q'].dropna().sort_values() # yoy_ocf_q 成长 单季度经营现金流同比增速
    #score_df = data_df['yoy_roe'].dropna().sort_values() # yoy_roe 成长 (当期 ROE-去年同期 ROE)/去年同期 ROE 绝对值
# 3. 反转
    #score_df = data_df['clo_5d_60d'].dropna().sort_values(ascending=False)
    #score_df = data_df['mom_252d'].dropna().sort_values(ascending=False)
    #score_df = data_df['reverse_20d'].dropna().sort_values(ascending=False)
    #score_df = data_df['close_max_div_min_20d'].dropna().sort_values(ascending=False)
    #score_df = data_df['return_max_20d'].dropna().sort_values(ascending=False)
# 4.杠杆    
    #score_df = data_df['current_ratio'].dropna().sort_values(ascending=False)
    #score_df = data_df['debt_asset_ratio'].dropna().sort_values(ascending=False)
    #score_df = data_df['current_liab_ratio'].dropna().sort_values(ascending=False)
# 5.红利
    #score_df = -data_df['dividend_yield_ratio'].dropna().sort_values()
# 6.价值
    #score_df = -data_df['market_cap'].dropna().sort_values(ascending=False)
    #score_df = -data_df['circulating_market_cap'].dropna().sort_values(ascending=False)
    #score_df = -data_df['bp'].dropna().sort_values(ascending=False) # 股东权益(报告期)/总市值
    #score_df = -data_df['ep'].dropna().sort_values(ascending=False) # ep 价值 市盈率倒数
    #score_df = -data_df['cfp'].dropna().sort_values(ascending=False) # cfp 价值 市现率倒数
    #score_df = -data_df['sp'].dropna().sort_values(ascending=False) # sp 价值 市销率倒数
    #score_df = -data_df['fcffp'].dropna().sort_values(ascending=False) # fcffp 价值 企业自由现金流 ttm/总市值
    #score_df = -data_df['ocfp'].dropna().sort_values(ascending=False) # ocfp 价值 经营现金流_TTM/总市值
    #score_df = -data_df['value_residual'].dropna().sort_values() # value_residual 价值 总市值的对数对账面价值对数，净利润对数以及负债合计对数 做横截面回归的取残差
# 7.流动性
    #score_df = data_df['amt_1m_3m'].dropna().sort_values(ascending=False)
    #score_df = data_df['corr_close_turnover'].dropna().sort_values(ascending=False)
    #score_df = data_df['illiq'].dropna().sort_values(ascending=False)
    #score_df = data_df['ln_volume_mean_1m'].dropna().sort_values(ascending=False)
    #score_df = data_df['turnover_mean_1m'].dropna().sort_values(ascending=False)
# 8.盈利
    #score_df = data_df['roe'].dropna().sort_values(ascending=False)
    #score_df = data_df['eps_adjust'].dropna().sort_values(ascending=False)
    #score_df = data_df['grossmargin_ratio'].dropna().sort_values(ascending=False)
    #score_df = data_df['grossprofit_assets'].dropna().sort_values(ascending=False)
    #score_df = data_df['grossprofit'].dropna().sort_values(ascending=False)
    #score_df = data_df['roa'].dropna().sort_values(ascending=False)
    #score_df = data_df['roic'].dropna().sort_values(ascending=False)
# 9.质量
    #score_df = data_df['safexp_operrev'].dropna().sort_values(ascending=False) # 质量 (销售费用_TTM+管理费用_TTM+财务费用_TTM)/营业收入_TTM
    #score_df = data_df['adm_exp_ratio'].dropna().sort_values() # 质量 管理费用_TTM/营业收入_TTM
    #score_df = data_df['bps'].dropna().sort_values() # 质量 (归属母公司股东的权益-其他权益工具)/总股本
    #score_df = data_df['currency_ratio'].dropna().sort_values() # 质量 经营活动产生的现金净流量/净利润
    #score_df = data_df['asset_turnover'].dropna().sort_values() # 质量 营业收入_TTM/平均总资产
    #score_df = data_df['inv_turnover'].dropna().sort_values() # 质量 营业成本_TTM/平均存货
    #score_df = data_df['fina_exp_ratio'].dropna().sort_values() # 质量 财务费用_TTM/营业收入_TTM
    #score_df = data_df['fix_ratio'].dropna().sort_values() # 质量 固定资产/归属母公司股东权益
    #score_df = data_df['networkcap_assets'].dropna().sort_values() # 质量 净运营资本/总资产(其中净营运资本=流动资产-流动负债)
    #score_df = data_df['moneycap_assets'].dropna().sort_values() # 质量 现金/总资产

    # index_stocks = get_index_stocks(g.benchmark, date=current_dt)
    # scored_index_stocks = [s for s in score_df.index if s in index_stocks]
    # g.buy_list = scored_index_stocks[:g.stock_num]

    #挑选出 11:00 的收盘价不等于涨停价的
    # min_df = get_price(score_df.index.tolist(), 
    #                     end_date='{} 9:40:00'.format(str(current_dt.date())),
    #                     count=1, 
    #                     fields=['close','high_limit','low_limit'],
    #                     frequency='1m').iloc[:,0]
    # q_stocks = min_df[min_df.close!=min_df.high_limit].index.tolist()  

    g.buy_list = score_df.index.tolist()[:g.stock_num]

def get_comb_factor(current_dt):
    fac_dict = {}
    fac_dict['1_Volability'] = [('ivr_1m',True)
                               ]
    fac_dict['2_Growth'] = [ ('yoy_eps_q',False) # 单季度每股收益同比增速
                            ,('yoy_np_q',False) # 单季度净利润同比增速
                            ,('yoy_op_q',False) # 单季度经营利润同比增速
                            ,('yoy_ocf_q',False) # 单季度经营现金流同比增速
                            ]
    fac_dict['3_Reverse'] = [('mom_252d',True)
                            ]
    fac_dict['4_Leverage'] = [   ('current_ratio',False) # 流动资产/流动负债
                                ,('debt_asset_ratio',False) # 资产/负债
                                ,('current_liab_ratio',True) # 流动负债/总资产
                             ]
    fac_dict['5_Dividend'] = [('dividend_yield_ratio',True) # 股息率
                             ]
    fac_dict['6_Value'] = [  ('bp',False) # 股东权益(报告期)/总市值
                            ,('cfp',False) # 市现率倒数
                            ,('sp',False) # 市销率倒数
                            ,('value_residual',True) # 总市值的对数 v.s. [账面价值对数，净利润对数以及负债合计对数]做横截面回归的取残差
                        ]
    fac_dict['7_Liquidity'] = []
    fac_dict['8_Profit'] = [ ('roe',False) # roe_ttm
                            ,('eps_adjust',False) # 扣除非经常损益后的净利润/总股本
                            ,('grossmargin_ratio',False) # 毛利_TTM/TTM营业总收入
                            ,('grossprofit',False) # (营业收入-营业支出)/营业收入
                            ,('roic',False) # roic_ttm
                            ]
    fac_dict['9_Quality'] = [ ('safexp_operrev',True) # (销售费用_TTM+管理费用_TTM+财务费用_TTM)/营业收入_TTM
                             ,('asset_turnover',False) # 营业收入_TTM/平均总资产
                             ,('fix_ratio',False) # 固定资产/归属母公司股东权益
                            ]
    
    final_df = pd.DataFrame()
    for k in fac_dict:
        if len(fac_dict[k])>0:
            data_file = 'data/{}/{}.csv'.format(k, str(current_dt.date()))
            data_df = pd.read_csv(BytesIO(read_file(data_file)), index_col=0)
            data_df[k] = 0
            for (v,is_asc) in fac_dict[k]:
                v_score_df = data_df[v].dropna().sort_values(ascending=is_asc)
                v_stocks = v_score_df.index[:len(v_score_df)//10] # 10%排名的stocks
                data_df.loc[v_stocks, k] += 1
            final_df[k] = data_df[k]/len(fac_dict[k])
    score_df = final_df.sum(axis=1).sort_values(ascending=False)
    return score_df
    
## 开盘时运行函数
def market_open(context):
    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    
    hold_list=list(context.portfolio.positions.keys()) 
    log.info('g.hold_list:' + str(hold_list))
    buy_list = g.buy_list
    log.info('buy_list:'+ str(buy_list)) 
    
    for s in hold_list:
        if s not in buy_list:
            order_target_value(s, 0)
    
    capital_unit = context.portfolio.total_value / len(buy_list)
    #capital_unit = context.portfolio.available_cash / len(buy_list)
    log.info('capital_unit:' + str(capital_unit))
    for s in buy_list:
        order_target_value(s, capital_unit)

## 收盘后运行函数
def after_market_close(context):
    log.info(str('函数运行时间(after_market_close):'+str(context.current_dt.time())))
    #得到当天所有成交记录
    trades = get_trades()
    for _trade in trades.values():
        log.info('成交记录：'+str(_trade))
    log.info('一天结束')
    log.info('##############################################################')

# 过滤【次新 + 科创北交 + ST退市 + 停牌】
def filter_stocks(all_security_df, yesterday, current_dt):
    all_security_df['index'] = all_security_df.index

    # 过滤次新股
    filter_fn = lambda t: (yesterday - t) >= datetime.timedelta(days=375)
    all_security_df = all_security_df[all_security_df['start_date'].apply(filter_fn)]

    # 过滤科创北交
    filter_fn = lambda t: t[0] != '4' and t[0] != '8' and t[:2] != '68'
    all_security_df = all_security_df[all_security_df['index'].apply(filter_fn)]

    # 过滤ST及其他具有退市标签的股票
    st_df = get_extras('is_st', all_security_df.index, start_date=current_dt, end_date=current_dt, df=True).T
    st_list = st_df[st_df==True].dropna().index
    filter_fn = lambda t: ("ST" in t or "*" in t or "退" in t)
    all_security_df = all_security_df[(~all_security_df['index'].isin(st_list)) & (~all_security_df['display_name'].apply(filter_fn))]
    
    # 过滤停牌
    susp_df = get_price(all_security_df.index.tolist(), \
                        end_date=current_dt, count=1, frequency='daily', \
                        fields='paused', panel=False)
    unsusp_stocks = susp_df[susp_df['paused'] < 1]["code"].tolist() # 得到当日未停牌股票代码list:
    days=7 # 过滤出前7天没有停牌过的Stocks
    feasible_stocks=[s for s in unsusp_stocks if sum(attribute_history(s, days, unit='1d',fields=('paused'),skip_paused=False))[0]==0]
    return feasible_stocks

