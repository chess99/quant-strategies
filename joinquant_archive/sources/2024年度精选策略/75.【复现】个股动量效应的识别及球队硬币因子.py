#!/usr/bin/env python
# coding: utf-8

# # 引言
# 
# 本文参考:
# > 20220611-方正证券-多因子选股系列研究之四：个股动量效应识别及“球队硬币”因子构建
# > 
# > Moskowitz T J. Asset pricing and sports betting[J]. Journal of Finance, Forthcoming, 2021.
# 
# 从个股角度来看，由于部分股票在月度频率上呈现的是动量效应，正是这些动量效应的存在，削弱了传统反转因子的效果。因此，如何有效识别个股的动量效应，并将其因子值加以翻转，使其成为名副其实的反转因子，是改进传统反转因子表现的重要途径之一。
# 
# 本文中我们将使用日度开盘价、收盘价和换手率等数据，分别从日间 涨跌幅、日内涨跌幅和隔夜涨跌幅的角度考察，通过简单的变换，在三种维度上都实现了对传统反转因子的明显改进，并最终构建了“球 队硬币”因子。“球队硬币”因子的选股能力和稳定性远超常规的日频量价因子，甚至超过了大部分分钟数据构造的选股因子。
# 
# # 对应理论运用
# 
# ## “可知性”
# 
# Moskowitz（2021）论述了当人们抛一枚硬币时，如果上次抛出了正面，人们倾向于猜测下次是反面，这是因为人们对抛硬币这件活动本 身比较了解，对于其发生的概率比较确定，即“抛硬币”这件事的 “可知性”较高，因此人们会以“反转”的眼光来看待“抛硬币”；而 当一个新赛季开始时，如果让人们猜测哪只球队会夺冠，由于人们对 新赛季的球队、球队的成员和团队磨合等不是很了解，即“冠军是 谁”这件事的“可知性”较低，因此只能以这些球队的历史成绩来考 察它们，此时人们更倾向于猜测上赛季的冠军，依旧会在本赛季夺冠，总结来说，人们会以“动量”的眼光来看待“球队夺冠”。
# 
# ## “可知性”与过度买卖
# 
# 然而当上述逻辑应用于股票时，却常常事与愿违，具体而言：
# 1. 当投资者将某只股票视为“球队”时，认为其将来会发生动量效 应，因此，如果该股票最近上涨，投资者认为它未来会继续上涨，就 会超买它，进而导致其未来股价出现回落；反之，如果该股票最近下 跌，投资者认为它未来会继续下跌，就会纷纷抛售超卖，导致其未来 补涨。因此那些被视为“球队”的股票，最终可能实际发生的是反转效应。
# 2. 当投资者将某只股票视为“硬币”时，认为其将来会发生反转效 应，因此，如果该股票最近上涨，投资者认为它未来会转为下跌，就 会超卖，进而导致其未来补涨；反之，如果该股票最近下跌，人们认 为它未来会转为上涨，就会超买，进而导致其股价未来回落。因此那 些被视为“硬币”的股票，最终可能实际发生的是动量效应。 因此判断一只股票将发生动量效应还是反转效应的核心，就变成了判 断一支股票是“硬币”还是“球队”，即判断一支股票走势的“可知性”。
#    
# 对于这一判断标准，在 Moskowitz（2021）的论文中，给出的指标是**依据公司是否发布了业绩预告，即认为发布了业绩预告的公司，其 “可知性”就会提高，投资者对于其未来走势就有了清晰的判断**。
# 
# **本文我们选择用交易类指标**作为划分的标准，对日间涨跌幅、日内涨跌 幅和隔夜涨跌幅进行改进，以期得到更为理想的选股效果。 具体而言，我们认为波动率和换手率的变化量可以代表一支股票表现 的“可知性”，即更像硬币还是更像球队。波动率低，表明股价走势相对稳定，投资者对其未来趋势做出判断也更加容易，而换手率降低，则表示投资者对股票的意见分歧逐渐减少，也是“可知性”提高 的表现。 
# 
# 总结来说，
# 
# **硬币型:**
# *波动率低的股票和换手率下降的股票，“可知性”更高，属于硬币类型的股票，未来发生动量效应的概率更大*；
# 
# **球队型:**
# *波动率高的股票和换手率增长的股票，“可知性”更低，属于球队类型的股票，未来发生反转效应的概率更大。*

# # 因子构建方法说明
# 
# ## 日间反转
# ### 日间反转-波动翻转因子(interday_volatility_reverse)
# 
# 1. 每天计算所有股票的日间收益率;
# 2. 每月月底计算*最近20天*的日间收益率的*均值*和*标准差*，作为当月的日间收益率和日间波动率;
# 3. 比较每只股票的日间波动率与市场截面均值的大小关系，将日间 波动率小于市场均值的股票，视为“硬币”型股票，由于未来其发生
# 动量效应的概率更大，因此我们将其当月日间收益率乘以-1；而日间波动率大于市场均值的股票，视为“球队”型股票，其未来将发生反转效应的概率更大，其因子值保持不变。我们将变换后的因子作为修正后的新反转因子，记为“日间反转-波动翻转”因子。
# 
# ### 日间反转-换手翻转因子(interday_turnover_rate_reverse)
# 
# 1. 计算每支股票t日换手率与t-1日换手率的差值，作为t日换手率的变化量;
# 2. 将每只股票的换手率变化量与当日全市场的换手率变化量的均值做比较，我们认为换手率变化量高于市场均值的股票为“球队”型股票，其未来将大概率发生反转效应；换手率变化量低于市场均值的，为“硬币”股票，未来将大概率发生动量效应;
# 3. 我们计算每只股票 t 日的日间收益率，将“硬币”型股票的日间收 益率乘以-1，而“球队”型股票的日间收益率保持不变。记变化后的日间收益率为“翻转收益率”;
# 4. 每月月底，计算最近20天的“翻转收益率”的均值，我们将变换后的因子作为经修正后的新反转因子，记为本月的“日间反转-换手翻转”因子。
# 
# ### 修正日间反转因子(revise_interday_reverse)
# 
# “日间反转-波动翻转”因子和“日间反转-换手翻 转”因子等权合成
# 
# ## 日内反转
# ### 日内反转-波动翻转因子(intraday_volatility_reverse)
# 1. 每天计算每只股票的日内收益率;
# 2. 每月月底计算最近 20 天的日内收益率的均值和标准差，作为当月的日内收益率和日内收益率的波动率;
# 3. 比较每只股票的日内收益率的波动率与市场截面均值的大小关 系，将日内收益率的波动率小于市场均值的股票，视为“硬币”型股 票，其未来发生动量效应的概率更大，因此我们将其当月日内收益率 乘以-1；而日内收益率的波动率大于市场均值的股票，视为“球队” 型股票，其未来将发生反转效应的概率更大，其当月日内收益率保持不变。
# 
# ### 日内反转-换手翻转因子(intraday_turnover_rate_reverse)
# 1. 计算每支股票 t 日换手率与 t-1 日换手率的差值，作为 t 日换手率 的变化量;
# 2. 将每只股票的换手率变化量与当日所有股票的换手率变化量的均 值做比较，我们认为换手率变化量高于市场均值的，为“球队”股 票，未来将发生反转；换手率变化量低于市场均值的，为“硬币”股票，未来将发生动量;
# 3. 我们计算每只股票 t 日的日内收益率，将“硬币”型股票的日内收 益率乘以-1，而“球队”型股票的日内收益率不变。记变化后的日内收益率为“翻转日内收益率”;
# 4. 每月月底，计算最近 20 天的“翻转日内收益率”的均值，我们将 变换后的因子作为修正后的新日内反转因子，记为本月的“日内反转-换手翻转”因子。
#    
# ### 修正日内反转因子(revise_intraday_reverse)
# “日内反转-波动翻转”因子和“日内反转-换手翻 转”因子等权合成
# 
# ## 隔夜距离
# 
# ### 隔夜距离的定义
# 1. 计算每只股票t日的隔夜收益率,即使用t日开盘价除以t-1日的收盘价再减1;
# 2. 每月月底,计算过去20个交易日的隔夜收益率的平均值,记为本月的传统隔夜涨跌因子;
# 
# 隔夜涨跌幅是一个“两边差，中间好”的因子，其逻辑通常可以解释为，开盘集合竞价里，不论方向，所有报价过于激进的交易者，都存在发生反应过度的风险。因此开盘时平静开盘是最好的。基于上述逻辑，我们对隔夜涨跌幅进行第一步改进——均值距离化。 即我们认为，隔夜涨跌幅的市场平均水平是最平静的，因此我们计算 每只个股的隔夜涨跌幅与市场平均水平的差值，然后取绝对值，表示这只个股与“最平静”之间的距离，并将其记为“隔夜距离”因子。
# 
# ### 隔夜反转-波动翻转因子(overnight_volatility_reverse)
# 1. 每天计算每只股票的“隔夜距离”;
# 2. 每月月底计算最近 20 天的隔夜距离的均值和标准差，作为当月的 “隔夜距离”和“隔夜距离波动率”;
# 3. 比较每只股票的“隔夜距离波动率”与市场截面均值的大小关 系，将“隔夜距离波动率”小于市场均值的股票，视为“硬币”型股 票，其未来发生动量效应的概率更大，因此我们将其当月“隔夜距离”取相反数；而“隔夜距离波动率”大于市场均值的股票，视为 “球队”型股票，其未来将发生反转效应的概率更大，因此其当月“隔夜距离”保持不变。
# 
# ### 隔夜反转-换手翻转因子(overnight_turnover_rate_reverse)
# 1. 计算每支股票 t-1 日换手率与 t-2 日换手率的差值，作为 t-1 日换手 率的变化量，然后将该变化量均值距离化，即减去市场均值后再取绝 对值，记为“换手距离”。这一步处理，与隔夜涨跌幅的逻辑类似， 我们认为，t 日开盘越平静越好，而从换手率维度来讲我们希望 t-1 日 的换手率变化量越平静越好，这样的股票 t 日开盘受额外因素影响相对较小，其开盘将会趋于平静;
# 2. 将每只股票的“换手距离”与当日所有股票的“换手距离”的均 值做比较，我们认为“换手距离”高于市场均值的，为“球队”股 票，未来将发生反转；“换手距离”低于市场均值的，为“硬币”股票，未来将发生动量;
# 3. 我们计算每只股票 t 日的“隔夜距离”，将“硬币”型股票的“隔 夜距离”乘以-1，而“球队”型股票的“隔夜距离”保持不变。记变化后的“隔夜距离”为“翻转隔夜距离”;
# 4. 每月月底，计算最近 20 天的“翻转隔夜距离”的均值，我们将变 换后的因子作为经修正后的新隔夜反转因子，记为本月的“隔夜反转-换手翻转”因子。
# 
# ### 修正隔夜反转(revise_overnight_reverse)
# “隔夜反转-波动翻转”因子和“隔夜反转-换手翻 转”因子等权合成
# 
# ## 球队硬币因子
# “修正日间反转”因子、“修正日内反转”因子和 “修正隔夜反转”因子等权合成，得到“球队硬币”因子
# 
# 这里我们还尝试将换手率还我自由流通换手率,用以测试因子效果

# In[11]:


from typing import List, Tuple

import empyrical as ep
import pandas as pd
import qlib
from FactorZoo import SportBettingsFactor, VolatilityMomentum
from src.build_factor import get_factor_data_and_forward_return
from src.factor_analyze import get_factor_describe, get_factor_group_returns
from src.plotting import plot_cumulativeline_from_dataframe


# In[12]:


qlib.init(provider_uri="data/qlib_data", region="cn")


# # 生成因子

# In[3]:


all_data: pd.DataFrame = get_factor_data_and_forward_return(
    SportBettingsFactor,
    window=20,
    periods=1,
    general_names=["interday", "intraday", "overnight"],
)


# In[4]:


all_data.head()


# In[5]:


# 储存数据
all_data.to_pickle('data/pkl/all_data.pkl')


# # 因子分析

# In[5]:


# 数据读取
all_data:pd.DataFrame = pd.read_pickle('data/pkl/all_data.pkl')


# In[13]:


clean_factor_res = get_factor_group_returns(all_data,quantiles=5)


# In[5]:


factor_names: List = [col for col in all_data.columns.tolist() if col != "next_ret"]


# In[6]:


all_data[factor_names].apply(get_factor_describe).T


# In[10]:


group_cum: pd.DataFrame = clean_factor_res.factor_return.groupby(
    level=0, axis=1, group_keys=False
).apply(ep.cum_returns)


# In[11]:


plot_cumulativeline_from_dataframe(group_cum)


# # 使用Qlib进行检验

# In[13]:


from qlib.data.dataset import DatasetH
from qlib.data.dataset.handler import DataHandlerLP
from src.plotting import model_performance_graph, report_graph
from src.qlib_workflow import QlibFlow
from src.utils import load2qlib


# In[14]:


TARIN_PERIODS: Tuple = ("2014-01-01", "2017-12-31")
VALID_PERIODS: Tuple = ("2018-01-01", "2019-12-31")
TEST_PERIODS: Tuple = ("2020-01-01", "2023-02-17")


# In[5]:


all_data:pd.DataFrame = pd.read_pickle('data/pkl/all_data.pkl')


# In[61]:


all_data.head()


# In[7]:


# 获取基础因子
sel_cols: List = [
    factor
    for factor in all_data.columns
    if (factor not in ["coin_team", "coin_team_f"]) and (factor.find("revise") == -1)
]

factor_base: pd.DataFrame = all_data[sel_cols].copy()


# In[8]:


# 将pd.DataFrame转为DatasetH
ds:DatasetH = load2qlib(factor_base,TARIN_PERIODS,VALID_PERIODS,TEST_PERIODS)


# In[9]:


# 储存ds数据
ds.config(dump_all=True, recursive=True)
ds.to_pickle(path="data/pkl/dataset.pkl", dump_all=True)


# In[8]:


# 储存dh_pr数据用于后续滚动训练
dh_pr: DataHandlerLP = load2qlib(
    factor_base, TARIN_PERIODS, VALID_PERIODS, TEST_PERIODS, output_type="DataHandlerLP"
)

dh_pr.to_pickle(path="data/pkl/data_dhpr.pkl", dump_all=True)


# ## 球队硬币(coin-team factor)因子(Baseline)
# 
# 以研报中的球队硬币因子为基线,时间范围选择2020年至2023-02-17,可以看到球队硬币因子有很好的单调性,低分组(因子值小)的收益最好

# In[10]:


cointeam_pred_df: pd.DataFrame = all_data.loc[
    TEST_PERIODS[0] : TEST_PERIODS[1], ["coin_team", "next_ret"]
].rename(columns={"coin_team": "score", "next_ret": "label"})


# In[11]:


performance_graph = model_performance_graph(cointeam_pred_df)


# In[24]:


# 使用
baseline_model = QlibFlow(
    dataset=ds, model="gbdt", start_time=TEST_PERIODS[0], end_time=TEST_PERIODS[1]
)


# 这里对球队硬币因子进行回测,虽然初始化了数据,但最终使用backtest方法时仅使用球队硬币因子值进行回测,回测默认使用**因子值最大**的topk只股票构建组合,所以这里我们将因子值乘-1反转因子值。

# In[28]:


coin_team:pd.DataFrame = all_data['coin_team_f'].to_frame('score')
baseline_model.backtest(pred_score=coin_team*-1,topk=50)


# In[29]:


coin_team_1day_df: pd.DataFrame = baseline_model.portfolio_metric_dict['1day'][0]


# In[30]:


coin_team_return_fig = report_graph(coin_team_1day_df)


# ## LGBMRanker模型

# In[31]:


lgbmrank_model = QlibFlow(
    dataset=ds,
    model="ranker",
    start_time=TEST_PERIODS[0],
    end_time=TEST_PERIODS[1],
    model_kw={"eval_at": [5]},
)


# In[32]:


lgbmrank_model.fit('rk_train') # 
lgbmrank_model.predict('rk_predict')
lgbmrank_model.backtest(topk=50)


# In[33]:


pred_label_df: pd.DataFrame = lgbmrank_model.get_pred(experiment_name="rk_predict",recorder_id='e7851ce3fd48483ca999d05162dbf72b')
pred_label_df.tail()


# In[34]:


performance_graph = model_performance_graph(pred_label_df)


# In[36]:


rk_fig = report_graph(lgbmrank_model.portfolio_metric_dict['1day'][0])


# ## LGBM模型复合因子

# In[37]:


gdbt_model = QlibFlow(
    dataset=ds, model="gbdt", start_time=TEST_PERIODS[0], end_time=TEST_PERIODS[1]
)


# In[38]:


gdbt_model.fit('train')
gdbt_model.predict('predict')
gdbt_model.backtest(topk=50)


# In[39]:


pred_label_df: pd.DataFrame = gdbt_model.get_pred(experiment_name="predict")
pred_label_df.tail()


# In[40]:


performance_graph = model_performance_graph(pred_label_df)


# In[41]:


fig = report_graph(gdbt_model.portfolio_metric_dict['1day'][0])


# ## 对比

# In[43]:


from typing import Dict


# In[44]:


ranker_ic_dict: Dict = lgbmrank_model.R.get_recorder(
    experiment_name="rk_v_predict", recorder_id="e7851ce3fd48483ca999d05162dbf72b"
).list_metrics()
gdbt_ic_dict: Dict = gdbt_model.R.get_recorder(
    experiment_name="predict", recorder_id="f2968244299e4bca8ff80c619979a63b"
).list_metrics()


# In[45]:


ic_df: pd.DataFrame = pd.concat(
    (pd.Series(ranker_ic_dict), pd.Series(gdbt_ic_dict)), axis=1
)
ic_df.columns = ["ranker", "gdbt"]


# In[46]:


ic_df


# # 日间/日内低波动率反转因子

# ## LGBMRanker模型

# In[33]:


volatility_momentum: pd.DataFrame = get_factor_data_and_forward_return(
    VolatilityMomentum,
    window=20,
    periods=1,
    factor_names=["interday_volatility_reverse", "intraday_volatility_reverse"],
)


# In[34]:


volatility_momentum.tail()


# In[35]:


# 储存数据
volatility_momentum.to_pickle('data/pkl/volatility_momentum.pkl')


# In[36]:


volatility_momentum: pd.DataFrame = pd.read_pickle("data/pkl/volatility_momentum.pkl")


# In[37]:


clean_factor_res = get_factor_group_returns(volatility_momentum,quantiles=5,max_loss=0.48)


# In[38]:


group_cum: pd.DataFrame = clean_factor_res.factor_return.groupby(
    level=0, axis=1, group_keys=False
).apply(ep.cum_returns)


# In[39]:


plot_cumulativeline_from_dataframe(group_cum,figsize=(18,4))


# In[40]:


# 将pd.DataFrame转为DatasetH
ds:DatasetH = load2qlib(volatility_momentum,TARIN_PERIODS,VALID_PERIODS,TEST_PERIODS)


# In[41]:


lgbmrank_v_model = QlibFlow(
    dataset=ds, model="ranker", start_time=TEST_PERIODS[0], end_time=TEST_PERIODS[1],model_kw={"eval_at":[3]}
)


# In[42]:


lgbmrank_v_model.fit('rk_v_train')
lgbmrank_v_model.predict('rk_v_predict')
lgbmrank_v_model.backtest()


# In[43]:


pred_label_df: pd.DataFrame = lgbmrank_v_model.get_pred(
    experiment_name="rk_v_predict",recorder_id="6eeae73a03b64abe90bb2c533cbac1b3"
)


# In[44]:


performance_graph = model_performance_graph(pred_label_df,duplicates='drop')


# In[45]:


rk_fig = report_graph(lgbmrank_v_model.portfolio_metric_dict['1day'][0])


# In[46]:


# 单独回测interday_lowvolatility_momentum因子
score_df: pd.DataFrame = volatility_momentum.loc[
    :, (slice("feature"), slice("interday_lowvolatility_momentum"))
].copy()
score_df.columns = ['score']


# In[47]:


lgbmrank_v_model.backtest(
    pred_score=score_df, start_time=TARIN_PERIODS[0], end_time=TEST_PERIODS[1]
)


# In[48]:


rk_fig = report_graph(lgbmrank_v_model.portfolio_metric_dict["1day"][0])


# # 滚动训练

# In[15]:


from qlib.workflow import R
from src.rolling import RollingBenchmark


# In[16]:


TRAIN_PERIODS: Tuple = ("2014-01-01", "2017-12-31")
VALID_PERIODS: Tuple = ("2018-01-01", "2019-12-31")
TEST_PERIODS: Tuple = ("2020-01-01", "2023-02-17")


# In[35]:


rolling_model = RollingBenchmark(
    TRAIN_PERIODS,
    VALID_PERIODS,
    TEST_PERIODS,
    factor_obj=SportBettingsFactor,
    window=20,
    step=20,
    horizon=1,
    exp_name="rolling_test",
    rolling_exp="test",
)
rolling_model.run()


# In[37]:


# pred_df: pd.DataFrame = R.get_recorder(
#     experiment_id="3", recorder_id="6210eef4630a4e33814a2c932d8be102"
# ).load_object("pred.pkl")
# label_df: pd.DataFrame = pd.read_pickle("data/pkl/all_data.pkl")[["next_ret"]].rename(
#     columns={"next_ret": "label"}
# )

# pred_label_df: pd.DataFrame = pd.concat((label_df, pred_df), axis=1, sort=True).reindex(
#     pred_df.index
# )

pred_label_df:pd.DataFrame = rolling_model.get_pred(experiment_id='3',recorder_id = '82b88a4264824dbebd747c7e3026cbf8')


# In[38]:


performance_graph = model_performance_graph(pred_label_df)

