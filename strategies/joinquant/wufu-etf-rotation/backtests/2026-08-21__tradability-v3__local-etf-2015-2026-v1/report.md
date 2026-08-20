# 五福可交易化 v3 事前实验报告

## 结论

主模型 T3 的最终判定是：**未通过完整事前成功门槛**。16 项冻结门槛通过 9 项、未通过
7 项。本轮共运行 136 次直接回测，包含全部失败组合；没有用结构矩阵中的
历史冠军替换事前指定的 T3。

T3 在单边总成本 10bp 下年化 15.07%、Sharpe
0.72、最大回撤 34.36%、年化换手
70.5 倍。相对旧 A6 Top3 的年化换手
165.2 倍，降幅 57.33%。这回答了本轮最核心的
“能否把五福结构压到更可交易的频率”问题，但是否值得进入平台完整仿真必须服从下方全部门槛，而
不能只看换手下降。

## 事实：有序消融

| trial | annualized_return | sharpe | maximum_drawdown | annualized_turnover | worst_rolling_three_year_return |
| --- | --- | --- | --- | --- | --- |
| T0 | -0.1275 | -0.3802 | 0.8941 | 184.8024 | -0.7152 |
| T1 | 0.0170 | 0.1880 | 0.6226 | 203.4887 | -0.4639 |
| T2 | 0.0128 | 0.1691 | 0.6208 | 193.5466 | -0.4188 |
| T3_primary | 0.1507 | 0.7151 | 0.3436 | 70.5127 | -0.1454 |

T0—T3 的唯一顺序变化分别是：弱市换池、Top(K+2) 老持仓名次缓冲、五交易日调仓。直接弱市
投票只使用观察日及此前四指数收盘，不继承 A4 的 20 日迟滞；弱市时仍保留普通健康过滤，不放宽
过滤、不切换 23/25 日窗口，也不关闭缓冲。

## 事实：成本、容量与集中度

- 单边 20bp 时，T3 年化 7.46%、Sharpe
  0.42；
- 1000 万元、0.5% ADV 场景的平均风险暴露为
  43.65%；
- 删除事后贡献最高的 1/3/5 只 ETF 后，最低 CAGR 保留比例为
  32.90%；
- 正收益贡献 Top1/Top3/Top5 占比分别为
  7.40%/
  17.30%/
  25.79%。

容量压力只限制每个计划调仓日的成交量；非调仓日不会继续补单。删除贡献实验使用全样本事后排名，
只能检查收益是否单点崩塌，不能成为新的实时剔除规则。

## 事实：参数、相位与时间稳定性

- 96 组结构矩阵在 10bp 下正年化比例 84.38%，中位 Sharpe
  0.47；
- 五个周频相位中正年化比例 100.00%，年化范围
  7.24%—19.60%；
- CSCV/PBO 为 17.14%，T3 的 DSR 概率为
  34.89%；
- 2019 年起 expanding-window 年化
  11.87%，最差年度
  -24.96%；
- 最好年度为 2026 年 145.43%，最差年度为
  2021 年 -7.64%；最差滚动三年收益为
  -14.54%。

## 冻结成功门槛

| criterion | observed | operator | threshold | passed |
| --- | --- | --- | --- | --- |
| primary_annualized_turnover_reduction_vs_A6_top3 | 0.5733 | >= | 0.5000 | 通过 |
| primary_max_sharpe_loss_vs_A6_top3_at_2bp | 0.2507 | <= | 0.1000 | 未通过 |
| primary_10bp_min_cagr | 0.1507 | >= | 0.0000 | 通过 |
| primary_10bp_min_sharpe | 0.7151 | >= | 0.5000 | 通过 |
| primary_20bp_min_cagr | 0.0746 | >= | 0.0000 | 通过 |
| primary_max_drawdown | 0.3436 | <= | 0.3000 | 未通过 |
| primary_worst_rolling_three_year_min | -0.1454 | >= | 0.0000 | 未通过 |
| capacity_10m_0_5pct_adv_min_average_exposure | 0.4365 | >= | 0.7000 | 未通过 |
| exclusion_min_cagr_retention | 0.3290 | >= | 0.7000 | 未通过 |
| structural_grid_10bp_positive_ratio | 0.8438 | >= | 0.7000 | 通过 |
| structural_grid_10bp_median_sharpe | 0.4715 | >= | 0.4000 | 通过 |
| schedule_phase_positive_ratio | 1.0000 | >= | 0.8000 | 通过 |
| walk_forward_min_cagr | 0.1187 | >= | 0.0000 | 通过 |
| walk_forward_worst_year | -0.2496 | >= | -0.2000 | 未通过 |
| pbo_max | 0.1714 | <= | 0.2500 | 通过 |
| dsr_probability_min | 0.3489 | >= | 0.9500 | 未通过 |

## 推断

本轮可以把“降低换手”与“保持收益稳健”分开判断：前者由周频和名次缓冲的直接成交账本支持；
后者只有在成本、三年窗口、相位、容量、贡献删除、PBO 与 DSR 等门槛同时成立时才能宣布。任何单个
最好参数或最好周频相位都只是诊断结果，不构成替换 T3 的依据。

本结果仍使用研究者已经看过的 2015—2026 历史，因此 expanding-window 和 PBO 只能约束研究自由度，
不能创造真正独立样本。`original_like` 候选池的生命周期是点时的，但 ETF 类别、跟踪标的和简称仍是
当前静态字段；本地成交使用复权开盘价、100 份整数手和 ADV 参与率，未模拟停牌、涨跌停排队、
申赎冲击与溢价。

## 下一步

若完整门槛未通过，不把 T3 提升为新基线，也不回到 A7 补盘中特例。后续只应根据失败门槛决定是否
停止：如果主要失败来自成本与容量，说明结构仍不可交易；如果仅统计多重试验门槛失败，则等待新的
独立样本。只有准备实盘采用且本地完整门槛已经通过时，才值得新开平台分钟组合仿真。

## 审计与文件索引

- 协议：`protocol.json`；输入哈希校验：`raw/input-validation.json`；
- 主模型账本：`raw/primary-equity.csv`、`primary-trades.csv`、`primary-positions.csv`、
  `primary-decisions.csv`、`primary-contributions.csv`；
- 直接矩阵：`raw/ordered-ablation.csv`、`structural-grid.csv`、`schedule-phase.csv`、
  `lookback-stress.csv`、`universe-stress.csv`、`cost-stress.csv`、`capacity-stress.csv`、
  `contributor-exclusion.csv`；
- 时间与过拟合：`raw/yearly.csv`、`periods.csv`、`regimes.csv`、
  `rolling-three-year.csv`、`pbo-splits.csv`、`walk-forward.csv`；
- 精确本地执行引擎：`engine.py`；聚宽迁移工作包：`source.py`。

输入共 2911 个含预热交易日、1733 只 B 级 ETF。所有 v3 结果均在协议
`2026-08-21-wufu-tradability-v3` 冻结之后生成。
