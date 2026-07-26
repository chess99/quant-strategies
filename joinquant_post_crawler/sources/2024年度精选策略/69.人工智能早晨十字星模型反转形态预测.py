# 克隆自聚宽文章：https://www.joinquant.com/post/44949
# 标题：人工智能早晨十字星模型（反转形态预测）
# 作者：MarioC

from jqdata import *
from jqfactor import *
import numpy as np
import pandas as pd
import pickle
import pandas as pd
import torch
import torch.nn as nn
from tqdm import tqdm
industry_code = ['HY001', 'HY002', 'HY003', 'HY004', 'HY005', 'HY006', 'HY007', 'HY008', 'HY009', 'HY010', 'HY011']


# 初始化函数
def initialize(context):
    # 设定基准
    set_benchmark('000985.XSHG')#000037 #'000985.XSHG'
    # 用真实价格交易
    set_option('use_real_price', True)
    # 打开防未来函数
    set_option("avoid_future_data", True)
    # 将滑点设置为0
    set_slippage(FixedSlippage(0))
    # 设置交易成本万分之三，不同滑点影响可在归因分析中查看
    set_order_cost(OrderCost(open_tax=0, close_tax=0.001, open_commission=0.0003, close_commission=0.0003,
                             close_today_commission=0, min_commission=5), type='stock')
    # 过滤order中低于error级别的日志
    log.set_level('order', 'error')
    # 初始化全局变量
    g.no_trading_today_signal = False
    g.stock_num = 3
    g.hold_list = []  # 当前持仓的全部股票
    g.yesterday_HL_list = []  # 记录持仓中昨日涨停的股票

                     






    # 设置交易运行时间
    run_daily(prepare_stock_list, '9:05')
    run_weekly(weekly_adjustment, 1, '9:30')
    # run_monthly(weekly_adjustment, 1, '9:30')
    run_daily(check_limit_up, '14:00')  # 检查持仓中的涨停股是否需要卖出
    run_daily(close_account, '14:50')


def min_max_scaling(lst):
    min_val = min(lst)
    max_val = max(lst)
    scaled_lst = [(x - min_val) / (max_val - min_val) for x in lst]
    return scaled_lst
# 1-1 准备股票池
def prepare_stock_list(context):
    # 获取已持有列表
    g.hold_list = []
    for position in list(context.portfolio.positions.values()):
        stock = position.security
        g.hold_list.append(stock)
    # 获取昨日涨停列表
    if g.hold_list != []:
        df = get_price(g.hold_list, end_date=context.previous_date, frequency='daily', fields=['close', 'high_limit'],
                       count=1, panel=False, fill_paused=False)
        df = df[df['close'] == df['high_limit']]
        g.yesterday_HL_list = list(df.code)
    else:
        g.yesterday_HL_list = []


model_path1 = r'ZCSZX_0.pt'
model_path2 = r'ZCSZX_1.pt'
model_path3 = r'ZCSZX_2.pt'

class model(nn.Module):

    def __init__(self,
                 fc1_size=2000,
                 fc2_size=1000,
                 fc3_size=100,
                 fc1_dropout=0.2,
                 fc2_dropout=0.2,
                 fc3_dropout=0.2,
                 num_of_classes=50):
        super(model, self).__init__()

        self.f_model = nn.Sequential(
            nn.Linear(2816, fc1_size),  # 887
            nn.BatchNorm1d(fc1_size),
            nn.ReLU(),
            nn.Dropout(fc1_dropout),
            nn.Linear(fc1_size, fc2_size),
            nn.BatchNorm1d(fc2_size),
            nn.ReLU(),
            nn.Dropout(fc2_dropout),
            nn.Linear(fc2_size, fc3_size),
            nn.BatchNorm1d(fc3_size),
            nn.ReLU(),
            nn.Dropout(fc3_dropout),
            nn.Linear(fc3_size, 2),

        )

        self.conv_layers1 = nn.Sequential(
            nn.Conv1d(6, 16, kernel_size=1),
            nn.BatchNorm1d(16),
            nn.Dropout(fc3_dropout),
            nn.ReLU(),
            nn.MaxPool1d(kernel_size=2),
            nn.Conv1d(16, 32, kernel_size=1),
            nn.BatchNorm1d(32),
            nn.Dropout(fc3_dropout),
            nn.ReLU(),
        )

        self.conv_2D = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=2),
            nn.BatchNorm2d(16),
            nn.Dropout(fc3_dropout),
            nn.ReLU(),
            nn.MaxPool2d(kernel_size=2),
            nn.Conv2d(16, 32, kernel_size=2),
            nn.BatchNorm2d(32),
            nn.Dropout(fc3_dropout),
            nn.ReLU(),
        )
        hidden_dim = 32
        self.lstm = nn.LSTM(input_size=hidden_dim, hidden_size=hidden_dim, num_layers=4, batch_first=True,
                            # dropout=fc3_dropout,
                            bidirectional=True)

        for name, module in self.named_modules():
            if isinstance(module, nn.Linear):
                nn.init.kaiming_normal_(module.weight, mode='fan_in', nonlinearity='relu')
            if isinstance(module, nn.Conv2d):
                nn.init.kaiming_normal_(module.weight, mode='fan_in', nonlinearity='relu')
            if isinstance(module, nn.Conv1d):
                nn.init.kaiming_normal_(module.weight, mode='fan_in', nonlinearity='relu')

    def forward(self, x):
        min_vals, _ = torch.min(x, dim=1, keepdim=True)
        max_vals, _ = torch.max(x, dim=1, keepdim=True)
        x = (x - min_vals) / (max_vals - min_vals + 0.00001)

        xx = x.unsqueeze(1)
        xx = self.conv_2D(xx)
        xx = torch.reshape(xx, (xx.shape[0], xx.shape[1] * xx.shape[2] * xx.shape[3]))
        x = x.transpose(1, 2)
        x = self.conv_layers1(x)
        out = x.transpose(1, 2)
        out2, _ = self.lstm(out)
        out2 = torch.reshape(out2, (out2.shape[0], out2.shape[1] * out2.shape[2]))

        IN = torch.cat((xx, out2), dim=1)
        out = self.f_model(IN)
        return out
            
import io
buffer = io.BytesIO(read_file(model_path1))

model_t1 = model()
model_t1.load_state_dict(torch.load(buffer))
model_t1.eval()  # 0.54

buffer = io.BytesIO(read_file(model_path2))
model_t2 = model()
model_t2.load_state_dict(torch.load(buffer))
model_t2.eval()  # 0.54

buffer = io.BytesIO(read_file(model_path3))
model_t3 = model()
model_t3.load_state_dict(torch.load(buffer))
model_t3.eval()  # 0.54

print('模型加载成功')
# 1-2 选股模块
def get_stock_list(context):
    # 指定日期防止未来数据
    yesterday = context.previous_date


    today = context.current_dt
    initial_list = get_all_securities('stock', today).index.tolist()
    initial_list = filter_all_stock2(context, initial_list)

    
    tensor_list =[]
    for i in initial_list:
        df = attribute_history(i, 60, '1d')
        df_tensor = torch.Tensor(df.values)
        tensor_list.append(df_tensor)

    stacked_tensor = torch.stack(tensor_list)
    tensor_list=[]
    with torch.no_grad():
        output1 = model_t1(stacked_tensor)
        output2 = model_t2(stacked_tensor)
        output3 = model_t3(stacked_tensor)
        output = output1+ output2 + output3
        output = output[:, 1]
        


    data = {'ID': initial_list, 'score': output.squeeze().tolist()}

    df = pd.DataFrame(data)
        
    N = g.stock_num 
    top_N_rows = df.nlargest(N, 'score')
    top_N_IDs = top_N_rows['ID'].tolist()

    return top_N_IDs
    


# 1-3 整体调整持仓
def weekly_adjustment(context):
    if g.no_trading_today_signal == False:
        # 获取应买入列表
        target_list = get_stock_list(context)
        # 调仓卖出
        for stock in g.hold_list:
            if (stock not in target_list) and (stock not in g.yesterday_HL_list):
                log.info("卖出[%s]" % (stock))
                position = context.portfolio.positions[stock]
                close_position(position)
            else:
                log.info("已持有[%s]" % (stock))
        # 调仓买入
        position_count = len(context.portfolio.positions)
        print(position_count)
        target_num = len(target_list)
        print(target_num)
        if target_num > position_count:
            print(context.portfolio.cash)
            
            value = context.portfolio.cash / (target_num - position_count)
            for stock in target_list:
                if context.portfolio.positions[stock].total_amount == 0:
                    if open_position(stock, value):
                        if len(context.portfolio.positions) == target_num:
                            break

# 1-4 调整昨日涨停股票
def check_limit_up(context):
    now_time = context.current_dt
    if g.yesterday_HL_list != []:
        # 对昨日涨停股票观察到尾盘如不涨停则提前卖出，如果涨停即使不在应买入列表仍暂时持有
        for stock in g.yesterday_HL_list:
            current_data = get_price(stock, end_date=now_time, frequency='1m', fields=['close', 'high_limit'],
                                     skip_paused=False, fq='pre', count=1, panel=False, fill_paused=True)
            if current_data.iloc[0, 0] < current_data.iloc[0, 1]:
                log.info("[%s]涨停打开，卖出" % (stock))
                position = context.portfolio.positions[stock]
                close_position(position)
            else:
                log.info("[%s]涨停，继续持有" % (stock))


            
def filter_all_stock2(context, stock_list):
    # 过滤次新股（新股、老股的分界日期，两种指定方法）
    # 新老股的分界日期, 自然日180天
    # by_date = context.previous_date - datetime.timedelta(days=180)
    # 新老股的分界日期，120个交易日
    by_date = get_trade_days(end_date=context.previous_date, count=180)[0]
    all_stocks = get_all_securities(date=by_date).index.tolist()
    stock_list = list(set(stock_list).intersection(set(all_stocks)))

    curr_data = get_current_data()
    print(curr_data)
    return [stock for stock in stock_list if not (
            stock.startswith(( '3','68', '4', '8')) or  # 创业，科创，北交所
            curr_data[stock].paused or
            curr_data[stock].is_st or  # ST
            ('ST' in curr_data[stock].name) or
            ('*' in curr_data[stock].name) or
            ('退' in curr_data[stock].name) or
            (curr_data[stock].day_open == curr_data[stock].high_limit) or  # 涨停开盘, 其它时间用last_price
            (curr_data[stock].day_open == curr_data[stock].low_limit)  # 跌停开盘, 其它时间用last_price
    )]
    
def order_target_value_(security, value):
    if value == 0:
        log.debug("Selling out %s" % (security))
    else:
        log.debug("Order %s to value %f" % (security, value))
    return order_target_value(security, value)


# 3-2 交易模块-开仓
def open_position(security, value):
    order = order_target_value_(security, value)
    if order != None and order.filled > 0:
        return True
    return False


# 3-3 交易模块-平仓
def close_position(position):
    security = position.security
    order = order_target_value_(security, 0)  # 可能会因停牌失败
    if order != None:
        if order.status == OrderStatus.held and order.filled == order.amount:
            return True
    return False


# 4-2 清仓后次日资金可转
def close_account(context):
    if g.no_trading_today_signal == True:
        if len(g.hold_list) != 0:
            for stock in g.hold_list:
                position = context.portfolio.positions[stock]
                close_position(position)
                log.info("卖出[%s]" % (stock))


def get_industry_name(i_Constituent_Stocks, value):
    return [k for k, v in i_Constituent_Stocks.items() if value in v]


# 缺失值处理
def replace_nan_indu(factor_data, stockList, industry_code, date):
    # 把nan用行业平均值代替，依然会有nan，此时用所有股票平均值代替
    i_Constituent_Stocks = {}
    data_temp = pd.DataFrame(index=industry_code, columns=factor_data.columns)
    for i in industry_code:
        temp = get_industry_stocks(i, date)
        i_Constituent_Stocks[i] = list(set(temp).intersection(set(stockList)))
        data_temp.loc[i] = mean(factor_data.loc[i_Constituent_Stocks[i], :])
    for factor in data_temp.columns:
        # 行业缺失值用所有行业平均值代替
        null_industry = list(data_temp.loc[pd.isnull(data_temp[factor]), factor].keys())
        for i in null_industry:
            data_temp.loc[i, factor] = mean(data_temp[factor])
        null_stock = list(factor_data.loc[pd.isnull(factor_data[factor]), factor].keys())
        for i in null_stock:
            industry = get_industry_name(i_Constituent_Stocks, i)
            if industry:
                factor_data.loc[i, factor] = data_temp.loc[industry[0], factor]
            else:
                factor_data.loc[i, factor] = mean(factor_data[factor])
    return factor_data


# 数据预处理
def data_preprocessing(factor_data, stockList, industry_code, date):
    # 去极值
    factor_data = winsorize_med(factor_data, scale=5, inf2nan=False, axis=0)
    # 缺失值处理
    factor_data = replace_nan_indu(factor_data, stockList, industry_code, date)
    # 标准化处理
    factor_data = standardlize(factor_data, axis=0)

    return factor_data
