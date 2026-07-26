# 克隆自聚宽文章：https://www.joinquant.com/post/44758
# 标题：人工智能强化学习DQN交易智能体（回馈社区公开训练代码）
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
    set_benchmark('000065.XSHE')#000037
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

    run_daily(adjustment,  '9:30')
    # run_weekly(adjustment, 1, '9:30')



model_path1 = r'tgt_net.pt'

class DQN(nn.Module):
    def __init__(self, input_shape, n_actions):
        super(DQN, self).__init__()
        units = 32
        self.fc1 = nn.Linear(input_shape, units)
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(units, n_actions)

    def forward(self, x):
        x = self.fc1(x)
        x = self.relu(x)
        x = self.fc2(x)
        return x
            
import io
buffer = io.BytesIO(read_file(model_path1))

model_t1 = DQN(6,3)
model_t1.load_state_dict(torch.load(buffer))
model_t1.eval()  # 0.54


print('模型加载成功')
def get_action(context):
    yesterday = context.previous_date
    today = context.current_dt
    initial_list ='000065.XSHE'
    

    df = attribute_history(initial_list, 7, '1d')
    df['涨跌幅'] = df['close'].pct_change() 
    print(df)
    df = df.dropna()

    print(df['涨跌幅'].values)
    df_tensor = torch.Tensor(df['涨跌幅'].values)
    output1 = model_t1(df_tensor)
    action = np.argmax(output1.detach().squeeze(0)) #1:买入 2：卖出 0：持有

    return action
    


# 1-3 整体调整持仓
def adjustment(context):

        initial_list ='000065.XSHE'
        action = get_action(context)
        print(action)
        # 调仓卖出
        value = context.portfolio.cash
        print(value)
        if action == 1:
            log.info("买入")
            open_position(initial_list, value)
        if action == 2:
            log.info("卖出")
            position = context.portfolio.positions[initial_list]
            close_position(position)
        else:
            log.info("持有")


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

        if len(g.hold_list) != 0:
            for stock in g.hold_list:
                position = context.portfolio.positions[stock]
                close_position(position)
                log.info("卖出[%s]" % (stock))

