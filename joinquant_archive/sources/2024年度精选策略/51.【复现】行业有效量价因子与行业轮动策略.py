#!/usr/bin/env python
# coding: utf-8

# In[1]:


import sys
from pathlib import Path

this_file_path = Path().resolve()
sys.path.append(str(this_file_path.parents[0]))

import pandas as pd
from typing import Dict, List, Tuple
import matplotlib.pyplot as plt


# # 数据获取并转换

# In[16]:


from scr.data_service import get_ts_etf_price,get_ts_index_price


# In[ ]:


etf_price: pd.DataFrame = get_ts_etf_price(
    start_date="2014-01-01",
    end_date="2023-02-17",
    fields=["open", "high", "low", "close", "vol",'amount'],
)
etf_price['vol'] *= 100
etf_price['amount'] *= 1000
etf_price.rename(columns={"vol": "volume"}, inplace=True)
etf_price["factor"] = 1

benchmark: pd.DataFrame = get_ts_index_price(
    "000300.SH",
    "2014-01-01",
    "2023-02-17",
    fields=["open", "high", "low", "close", "volume",'amount'],
)

benchmark['volume'] *= 100
benchmark['amount'] *= 1000
benchmark['factor'] = 1


# In[ ]:


data_all:pd.DataFrame = pd.concat((etf_price,benchmark))


# In[ ]:


ETF_PRICE:str = "../行业有效量价因子/etf_price"


# In[ ]:


for code,df in data_all.groupby('code'):
    csv_name:str = '{1}{0}'.format(*code.split('.')).upper() + ".csv"
    df.to_csv(str(ETF_PRICE/csv_name))


# In[ ]:


#!cd D:\WrokSpace\visualization_stock_market\sqlalchemy_to_data\qlib_scripts && python dump_bin.py dump_all --csv_path D:\WrokSpace\visualization_stock_market\sqlalchemy_to_data\行业有效量价因子\etf_price --qlib_dir D:\WrokSpace\visualization_stock_market\sqlalchemy_to_data\行业有效量价因子\qlib_etf_data --date_field_name "trade_date" --exclude_fields ('code',)


# In[ ]:


get_ipython().system('cd e:\\WorkSpace\\visualization_stock_market\\sqlalchemy_to_data\\qlib_scripts && python dump_bin.py dump_all --csv_path e:\\WorkSpace\\visualization_stock_market\\sqlalchemy_to_data\\行业有效量价因子\\etf_price --qlib_dir e:\\WorkSpace\\visualization_stock_market\\sqlalchemy_to_data\\行业有效量价因子\\qlib_etf_data --date_field_name "trade_date" --exclude_fields (\'code\',)')


# # 初始化qlib

# In[2]:


import qlib
from qlib.workflow import R  # 实验记录管理器
from qlib.data import D # 基础行情数据服务的对象
from qlib.utils import init_instance_by_config, flatten_dict
from qlib.constant import REG_CN
from qlib.workflow.record_temp import SignalRecord, SigAnaRecord


# In[3]:


qlib.init(provider_uri="qlib_etf_data", region=REG_CN) # 初始化


# # 训练模型实例化

# ## 价量因子构造
# 
# |大类因子|因子名称|计算公式|
# |--|--|--|
# |动量|二阶动量|$EWMA(\frac{Close_{t}-mean(Close_{t-window_{1:t}})}{mean(Close_{t-window_{1:t}})}-delay(\frac{Close_{t}-mean(Close_{t-window1:t})}{mean(Close_{t-window1:t})},window2),window)$|
# |动量|动量期限差|$\frac{Close_{t}-Close_{t-window1}}{Close_{t-window_{1}}}-\frac{Close_{t}-Close_{t-window_{2}}}{Close_{t-window2}}$,window1>window2|
# |波动率|成交金额波动|$-STD(Amount)$|
# |波动率|成交量波动|$-STD(Volume)$|
# |换手率|换手率变化|$\frac{Mean(turnover_{t-window_{1:t}})}{Mean(turnover_{t-window_{2:t}})}$,window1>window2|
# |多空对比|多空对比总量|$-\sum^{i=t}_{i=t-window}\frac{Close_{i}-Low_{i}}{Hight_{i}-Close_{i}}$|
# |多空对比|多空对比变化|$EWMA(Volume*\frac{(Close-Low)-(High-Close)}{High-Low},window_{1})-EWNA(Volume*\frac{(Close-Low)-(High-Close)}{High-Low},window_{2})$,$window_1>window_2$|
# |量价背离|量价背离协方差(收盘价)|$-rank\{covariance[rank(Close),rank(Volume),window]\}$|
# |量价背离|量价相关系数(收盘价)|$-correlation(Close,Volume,window)$|
# |量价背离|一阶量价背离|$-correlation[Rank(\frac{Volume_{i}}{Volume_{i-1}}-1),Rank(\frac{Close_{i}}{Open_{i}}-1),window]$|
# |量幅同向|量幅同向|$correlation[Rank(\frac{Volume_{i}}{Volume_{i-1}}-1),Rank(\frac{High_{i}}{Low_{i}}-1),window]$|

# 由于研报未给出具体窗口参数。所以再构造因子时使用了5,10,20,60,120,180这几个常用的窗口期,共生成了192个因子。

# 下图为行业ETF的数量变动情况,在2020年ETF行业占比才到全部行业etf的60%,一共68支，总的来说时间过短。所以后续我们使用全部etf作为标的池。

# In[4]:


industry_etf:pd.DataFrame = pd.read_csv('../行业有效量价因子/qlib_etf_data/instruments/industry_etf.txt',delimiter='\t',header=None,parse_dates=[1,2])
industry_etf.columns = ['symbol','begin_dt','end_dt']

fig,axes = plt.subplots(1,2,figsize=(10,4))
bar_ax = industry_etf["begin_dt"].dt.year.value_counts().sort_index().plot.bar(ax=axes[0])

line_ax = industry_etf["begin_dt"].dt.year.value_counts().div(
    len(industry_etf)
).sort_index().cumsum().plot(marker='o',ax=axes[1])


# In[5]:


###################################
# 参数配置
###################################
# 数据处理器参数配置：整体数据开始结束时间，训练集开始结束时间，股票池
TARIN_PERIODS: Tuple = ("2014-01-01", "2017-12-31")
VALID_PERIODS: Tuple = ("2018-01-01", "2020-12-31")
TEST_PERIODS: Tuple = ("2021-01-01", "2023-02-17")

data_handler_config:Dict = {
    "start_time": TARIN_PERIODS[0],
    "end_time": TEST_PERIODS[1],
    "fit_start_time": TARIN_PERIODS[0],
    "fit_end_time": TARIN_PERIODS[1],
    "instruments": "market",
}

# 任务参数配置
task:Dict = {
    # 机器学习模型参数配置
    "model": {
        # 模型类
        "class": "LGBModel",
        # 模型类所在模块
        "module_path": "qlib.contrib.model.gbdt",
        # 模型类超参数配置，未写的则采用默认值。这些参数传给模型类
        "kwargs": {  # kwargs用于初始化上面的class
            "loss": "mse",
            "colsample_bytree": 0.8879,
            "learning_rate": 0.0421,
            "subsample": 0.8789,
            "lambda_l1": 205.6999,
            "lambda_l2": 580.9768,
            "max_depth": 15,
            "num_leaves": 210,
            "num_threads": 20,
            "early_stopping_rounds": 200,  # 训练迭代提前停止条件
            "num_boost_round": 1000,  # 最大训练迭代次数
        },
    },
    "dataset": {  # 　因子数据集参数配置
        # 数据集类，是Dataset with Data(H)andler的缩写，即带数据处理器的数据集
        "class": "DatasetH",
        # 数据集类所在模块
        "module_path": "qlib.data.dataset",
        # 数据集类的参数配置
        "kwargs": {
            "handler": {  # 数据集使用的数据处理器配置
                "class": "VolumePriceFactor192",  # 数据处理器类，继承自DataHandlerLP
                "module_path": "scr.factor_expr", # 数据处理器类所在模块
                "kwargs": data_handler_config,  # 数据处理器参数配置
            },
            "segments": {  # 数据集时段划分
                "train": TARIN_PERIODS,  # 训练集时段
                "valid": VALID_PERIODS,  # 验证集时段
                "test": TEST_PERIODS,  # 测试集时段
            },
        },
    },
}


# 实例化模型对象
model = init_instance_by_config(task["model"])
# 实例化数据集，从基础行情数据计算出的包含所有特征（因子）和标签值的数据集。
dataset = init_instance_by_config(task["dataset"])  # 类型DatasetH


# In[6]:


# 保存数据方便后续使用
dataset.config(dump_all=True,recursive=True)
dataset.to_pickle(path="dataset.pkl",dump_all=True)


# In[4]:


# 读取dataset
import pickle

with open("dataset.pkl", "rb") as file_dataset:
    dataset = pickle.load(file_dataset)


# # dataset数据查询：特征，标签

# In[7]:


# 返回（原始数据集中）训练集、验证集、测试集的全部特征和标签数据
# dara_key = "raw"表示返回原始数据 不加则是预处理后的数据
df_train, df_valid, df_test =  dataset.prepare(segments=["train", "valid", "test"], data_key = "raw") 


# In[8]:


df_test.head()


# ## 查看特征定义

# In[9]:


fea_expr, fea_name = dataset.handler.get_feature_config()
print('fea_expr',fea_expr)
print()
print('fea_name',fea_name)
print()
print(f'特征个数:{len(fea_expr)}')


# # 模型训练

# In[10]:


# R变量可以理解为实验记录管理器。
with R.start(experiment_name="train"): # 注意，设好实验名
    # 可选：记录task中的参数到运行记录下的params目录
    R.log_params(**flatten_dict(task))

    # 训练模型，得到训练好的模型model
    model.fit(dataset)
    
    # 可选：训练好的模型以pkl文件形式保存到本次实验运行记录目录下的artifacts子目录，以备后用  
    R.save_objects(trained_model=model)

    # 打印本次实验记录器信息，含记录器id，experiment_id等信息
    print('info', R.get_recorder().info)


# # 预测:在测试集上测试

# In[11]:


with R.start(experiment_name="predict"):
 
    # 当前实验的实验记录器：预测实验记录器
    predict_recorder = R.get_recorder()

    # 生成预测结果文件: pred.pkl, label.pkl存放在运行记录目录下的artifacts子目录   
    # 本实验默认是站在t日结束时刻，预测t+2日收盘价相对t+1日开盘价的收益率，计算公式为 Ref($open, -2)/Ref($open, -1) - 1
    sig_rec = SignalRecord(model, dataset, predict_recorder)  # 将训练好的模型、数据集、预测实验记录器传递给信号记录器      
    sig_rec.generate()
    
    # 生成预测结果分析文件，在artifacts\sig_analysis 目录生成ic.pkl,ric.pkl文件
    sigAna_rec = SigAnaRecord(predict_recorder) # 信号分析记录器
    sigAna_rec.generate()

    print('info', R.get_recorder().info)


# # 预测结果查询

# In[5]:


# 加载pkl文件 
with R.start():
    train_recorder = R.get_recorder(experiment_id='1',recorder_id='3b6e1cdcc6fa4bfca9dbb96a8d834e52')
    model = train_recorder.load_object("trained_model")
    predict_recorder = R.get_recorder(experiment_id='2',recorder_id='ea512bd4a0c34b9ca523f8f94fc90bdc')


# In[10]:


# 这个pkl文件记录的是测试集未经数据预处理的原始标签值
label_df = predict_recorder.load_object("label.pkl") 
# 修改列名LABEL0为label 这个label其实就是下一期得收益率
label_df.columns = ['label'] 

pred_df = predict_recorder.load_object("pred.pkl") # 加载测试集预测结果到dataframe

print('label_df', label_df) # 预处理后的测试集标签值 
print('pred_df', pred_df) # 测试集对标签的预测值，score就是预测值


# ## IC,Rank IC查询

# In[14]:


ic_df = predict_recorder.load_object("sig_analysis/ic.pkl")

ric_df = predict_recorder.load_object("sig_analysis/ric.pkl")

# 所有绩效指标
print("list_metrics", predict_recorder.list_metrics())
# IC均值：每日IC的均值，一般认为|IC|>0.03说明因子有效，注意 -0.05也认为有预测效能，说明负相关显著
print("IC", predict_recorder.list_metrics()["IC"])
# IC信息率：平均IC/每日IC标准差,也就是方差标准化后的ic均值，一般而言，认为|ICIR|>0.6,因子的稳定性合格
print("ICIR", predict_recorder.list_metrics()["ICIR"])
# 排序IC均值，作用类似IC
print("Rank IC", predict_recorder.list_metrics()["Rank IC"])
# 排序IC信息率，作用类似ICIR# 此图用于评价因子单调性，组1是因子值最高的一组，组5是因子值最低的一组。
print("Rank ICIR", predict_recorder.list_metrics()["Rank ICIR"])


# In[15]:


# 创建测试集"预测"和“标签”对照表
pred_label_df = pd.concat([pred_df, label_df], axis=1, sort=True).reindex(label_df.index)
pred_label_df.head()


# ## 查看IC及分组收益情况

# In[22]:


from scr.plotting import plot_qlib_factor_dist


# In[17]:


plot_qlib_factor_dist(pred_label_df,no_raise=True)


# ## 模型特征重要性

# In[7]:


# 得到特征重要性系列
if hasattr(model,'get_feature_importance'):
    feature_importance = model.get_feature_importance()

    fea_expr, fea_name = dataset.handler.get_feature_config() # 获取特征表达式，特征名字
    # 特征名，重要性值的对照字典
    feature_importance = {fea_name[int(i.split('_')[1])]: v for i,v in feature_importance.items()}
    pd.Series(feature_importance).sort_values().iloc[-20:].plot.bar()


# # 使用Backtrader根据预测值回测

# In[6]:


from hugos_toolkit.BackTestTemplate import StockSelectStrategy,get_backtesting,AddSignalData
from hugos_toolkit.BackTestReport.tear import analysis_rets


# In[7]:


def get_backtest_data(
    pred_df: pd.DataFrame, start_time: str, end_time: str,market='market'
) -> Tuple[pd.DataFrame, pd.DataFrame]:

    # 定义股票池
    stockpool: List = D.instruments(market=market)
    # 获取test时段的行情原始数据
    raw_data: pd.DataFrame = D.features(
        stockpool,
        fields=["$open", "$high", "$low", "$close", "$volume"],
        start_time=start_time,
        end_time=end_time,
    )
    raw_data: pd.DataFrame = raw_data.swaplevel().sort_index()
    data: pd.DataFrame = pd.merge(
        raw_data, pred_df, how="inner", left_index=True, right_index=True
    ).sort_index()
    data.columns = data.columns.str.replace("$", "", regex=False)
    data: pd.DataFrame = data.reset_index(level=1).rename(
        columns={"instrument": "code"}
    )

    benchmark: pd.DataFrame = D.features(
        ["SH000300"],
        fields=["$close"],
        start_time=start_time,
        end_time=end_time,
    ).reset_index(level=0, drop=True)

    return data, benchmark


# In[8]:


TEST_PERIODS: Tuple = ("2021-01-01", "2023-02-17")


# In[11]:


data,benchmark = get_backtest_data(pred_df,TEST_PERIODS[0],TEST_PERIODS[1])


# In[12]:


benchmark_ret:pd.Series = benchmark['$close'].pct_change()


# In[13]:


bt_result = get_backtesting(
    data,
    "test",
    strategy=StockSelectStrategy,
    mulit_add_data=True,
    feedsfunc=AddSignalData,
    strategy_params={"selnum": 5, "pre": 0.05,'ascending':False,'show_log':False},
)


# ## 回测结果

# In[14]:


algorithm_returns: pd.Series = pd.Series(
    bt_result.result[0].analyzers._TimeReturn.get_analysis()
)


# In[15]:


report = analysis_rets(algorithm_returns,bt_result.result,benchmark_ret)


# In[16]:


for chart in report:
    chart.show()


# # Alpha158因子
# 
# 可以看到华西证券的价量因子虽然在指数上表现较好,但是在ETF上的表现可以说是完全失效的。所以这里我们使用Alpah158因子测试一下其在ETF上的表现如何。

# ## 构建模型

# In[28]:


###################################
# 参数配置
###################################
# 数据处理器参数配置：整体数据开始结束时间，训练集开始结束时间，股票池
TARIN_PERIODS: Tuple = ("2014-01-01", "2019-12-31")
VALID_PERIODS: Tuple = ("2020-01-01", "2020-12-31")
TEST_PERIODS: Tuple = ("2021-01-01", "2023-02-17")


data_handler_config: Dict = {
    "start_time": TARIN_PERIODS[0],
    "end_time": TEST_PERIODS[1],
    "fit_start_time": TARIN_PERIODS[0],
    "fit_end_time": TARIN_PERIODS[1],
    "instruments": "market"
}

# 任务参数配置
task_158: Dict = {
    # 机器学习模型参数配置
    "model": {
        # 模型类
        "class": "LGBModel",
        # 模型类所在模块
        "module_path": "qlib.contrib.model.gbdt",
        # 模型类超参数配置，未写的则采用默认值。这些参数传给模型类
        "kwargs": {
           "loss": "mse",
            "colsample_bytree": 0.8879,
            "learning_rate": 0.0421,
            "subsample": 0.8789,
            "lambda_l1": 205.6999,
            "lambda_l2": 580.9768,
            "max_depth": 15,
            "num_leaves": 210,
            "num_threads": 20,
            "early_stopping_rounds": 200,  # 训练迭代提前停止条件
            "num_boost_round": 1000,  # 最大训练迭代次数
        },
    },
    "dataset": {  # 　因子数据集参数配置
        # 数据集类，是Dataset with Data(H)andler的缩写，即带数据处理器的数据集
        "class": "DatasetH",
        # 数据集类所在模块
        "module_path": "qlib.data.dataset",
        # 数据集类的参数配置
        "kwargs": {
            "handler": {  # 数据集使用的数据处理器配置
                "class": "Alpha158",  # 数据处理器类，继承自DataHandlerLP
                "module_path": "qlib.contrib.data.handler",  # 数据处理器类所在模块
                "kwargs": data_handler_config,  # 数据处理器参数配置
            },
            "segments": {  # 数据集时段划分
                "train": TARIN_PERIODS,  # 训练集时段
                "valid": VALID_PERIODS,  # 验证集时段
                "test": TEST_PERIODS,  # 测试集时段
            },
        },
    },
}


# 实例化模型对象
model_158 = init_instance_by_config(task_158["model"])
# 实例化数据集，从基础行情数据计算出的包含所有特征（因子）和标签值的数据集。
dataset_158 = init_instance_by_config(task_158["dataset"])  # 类型DatasetH


# In[29]:


# 保存数据方便后续使用
dataset_158.config(dump_all=True,recursive=True)
dataset_158.to_pickle(path="dataset_158.pkl",dump_all=True)


# In[18]:


with open("dataset_158.pkl", "rb") as file_dataset:
    dataset_158 = pickle.load(file_dataset)


# ## 执行预测工作流

# In[30]:


with R.start(experiment_name="ts_workflow"): # 注意，设好实验名
    # 可选：记录task中的参数到运行记录下的params目录
    R.log_params(**flatten_dict(task_158))

    ############
    # 训练
    #############
    model_158.fit(dataset_158)
    
    # 训练好的模型以pkl文件形式保存到本次实验运行记录目录下的artifacts子目录  
    R.save_objects(trained_model=model_158)

    ###############
    # 预测
    #############
    # 本次实验的实验记录器
    recorder_158 = R.get_recorder()
    # 生成预测结果文件
    sig_rec = SignalRecord(model_158, dataset_158, recorder_158)
    sig_rec.generate()

    # 生成预测结果分析文件
    sigAna_rec = SigAnaRecord(recorder_158)
    sigAna_rec.generate()

    # 打印本次实验记录器信息，含记录器id，experiment_id等信息
    print('info', R.get_recorder().info)


# In[19]:


# 加载pkl文件 
with R.start():
    recorder_158 = R.get_recorder(experiment_id='3',recorder_id='f183768a9d7844d691af2e6d18911ec7')
    model_158 = recorder_158.load_object("trained_model")
 


# In[20]:


label_158_df:pd.DataFrame = recorder_158.load_object("label.pkl")
label_158_df.columns = ["label"]
pred_158_df = recorder_158.load_object("pred.pkl")
# 创建测试集"预测"和“标签”对照表
pred_label_158_df = pd.concat([pred_158_df, label_158_df], axis=1, sort=True).reindex(
    label_158_df.index
)


# ## IC/Rank IC

# In[23]:


plot_qlib_factor_dist(pred_label_158_df)


# ## 回测

# In[24]:


data_158,benchmark = get_backtest_data(pred_158_df,TEST_PERIODS[0],TEST_PERIODS[1])


# In[25]:


bt_158_result = get_backtesting(
    data_158,
    strategy=StockSelectStrategy,
    mulit_add_data=True,
    feedsfunc=AddSignalData,
    strategy_params={"selnum": 5, "pre": 0.05, "ascending": False,'show_log':False},
)


# In[26]:


algorithm_returns: pd.Series = pd.Series(
    bt_158_result.result[0].analyzers._TimeReturn.get_analysis()
)


# In[27]:


report_158 = analysis_rets(algorithm_returns,bt_158_result.result,benchmark['$close'].pct_change())


# In[28]:


for chart in report_158:
    
    chart.show()


# In[ ]:




