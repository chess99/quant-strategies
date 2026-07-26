# 克隆自聚宽文章：https://www.joinquant.com/post/49226
# 标题：BiLSTM for ETF
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
from sklearn.preprocessing import MinMaxScaler
# 初始化函数
def initialize(context):
    # 设定基准
    set_benchmark('000985.XSHG')
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
    g.stock_num = 3
    g.hold_list = []  # 当前持仓的全部股票
    run_daily(prepare_stock_list, '9:05')
    run_weekly(weekly_adjustment, 1, '9:30')

# 1-1 准备股票池
def prepare_stock_list(context):
    # 获取已持有列表
    g.hold_list = []
    for position in list(context.portfolio.positions.values()):
        stock = position.security
        g.hold_list.append(stock)

model_path = r'机器学习/model_baseline_BiLSTM.pt' #需要查看你自己的模型所在目录
import io
buffer = io.BytesIO(read_file(model_path))
class BiLSTM(nn.Module):
    def __init__(self):
        super(BiLSTM, self).__init__()
        self.n_class=6
        self.n_hidden=10
        self.lstm = nn.LSTM(input_size=self.n_class, hidden_size=self.n_hidden, bidirectional=True)
        # fc
        self.fc = nn.Linear(self.n_hidden * 2, 1)

    def forward(self, X):
        # X: [batch_size, max_len, n_class]
        batch_size = X.shape[0]
        input = X.transpose(0, 1)  # input : [max_len, batch_size, n_class]
        hidden_state = torch.randn(1*2, batch_size, self.n_hidden)   # [num_layers(=1) * num_directions(=2), batch_size, n_hidden]
        cell_state = torch.randn(1*2, batch_size, self.n_hidden)     # [num_layers(=1) * num_directions(=2), batch_size, n_hidden]
        outputs, (_, _) = self.lstm(input, (hidden_state, cell_state)) # [max_len, batch_size, n_hidden * 2]
        outputs = outputs[-1]  # [batch_size, n_hidden * 2]
        model = self.fc(outputs)  # model : [batch_size, n_class]
        return model
model_t1 = BiLSTM()
model_t1.load_state_dict(torch.load(buffer))
model_t1.eval() 
print('模型加载成功')


def get_stock_list(context):
    # 指定日期防止未来数据
    yesterday = context.previous_date
    today = context.current_dt
    initial_list = get_all_securities('etf', yesterday).index.tolist()
    initial_list = filter_new_stock(context, initial_list)
    tensor_list =[]
    ID=[]
    for i in initial_list:
        df = attribute_history(i, 60, '1d')
        if (df['volume'] < 10000000).any() or df.isna().any().any():
            pass
        else:
            scaler = MinMaxScaler()
            normalized_data = scaler.fit_transform(df)
            normalized_df = pd.DataFrame(normalized_data, columns=df.columns)
            df_tensor = torch.Tensor(normalized_df.values)
            tensor_list.append(df_tensor)
            ID.append(i)
    stacked_tensor = torch.stack(tensor_list)
    with torch.no_grad():
        output1 = model_t1(stacked_tensor)
    data = {'ID': ID, 'score': output1.squeeze().tolist()}
    df = pd.DataFrame(data)
    top_N_rows = df.nlargest(g.stock_num , 'score')
    top_N_IDs = top_N_rows['ID'].tolist()
    return top_N_IDs


# 1-3 整体调整持仓
def weekly_adjustment(context):
    target_list = get_stock_list(context)
    # 调仓卖出
    for stock in g.hold_list:
        if stock not in target_list:
            position = context.portfolio.positions[stock]
            close_position(position)
    position_count = len(context.portfolio.positions)
    target_num = len(target_list)
    if target_num > position_count:
        value = context.portfolio.cash / (target_num - position_count)
        for stock in target_list:
            if stock not in list(context.portfolio.positions.keys()):
                if open_position(stock, value):
                    if len(context.portfolio.positions) == target_num:
                        break


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
    
# 2-6 过滤次新股
def filter_new_stock(context, stock_list):
    yesterday = context.previous_date
    return [stock for stock in stock_list if
            not yesterday - get_security_info(stock).start_date < datetime.timedelta(days=375*3)]




