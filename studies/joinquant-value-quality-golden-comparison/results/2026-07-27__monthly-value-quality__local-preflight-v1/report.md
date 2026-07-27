# 全市场价值质量本地预检

## 事实

- 区间：2019-01-02 至 2023-06-30；每月首个交易日开盘调仓，观察日为前一交易日。
- 股票池从 6,115 只历史 A 股按观察日生命周期展开；北交所因免费历史涨跌停为 C 级而剔除。
- 财务只使用 `notice_date <= observation_date` 的最新报告；估值最多向前 10 个自然日；
  行业使用申万官方历史一级行业有效区间。
- 先做行业内低 PE/PB/PS 与高 ROE/ROA/利润率、低杠杆综合排名，再设每行业最多
  3 只，等权持有 20 只。
- 共 54 次调仓；最少 995 只合格候选，
  最少选择 20 只。
- 本地累计收益 60.69%，年化 11.59%，
  最大回撤 30.55%，Sharpe 0.604，
  换手 35.61，平均现金 0.61%。
- 拒单 25 次；点时和数据质量检查：{'all_rebalances_have_20_targets': True, 'future_notice_rows_zero': True, 'fundamental_partition_failures_zero': True, 'industry_partition_failures_zero': True, 'future_industry_intervals_zero': True, 'selected_state_quality_at_least_b': False, 'trades_present': True}。

## 限制

- 东方财富可能把后来修订值回填到旧公告记录，因此财务和估值均为 B，不宣称严格 vintage A。
- 本归档完成本地全量预检，但在聚宽候选、持仓、成交和净值黄金对照通过前，迭代 6 仍未完成。
