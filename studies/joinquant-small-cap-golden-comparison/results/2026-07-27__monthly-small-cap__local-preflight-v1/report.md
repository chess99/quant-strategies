# 全市场小市值本地预检

## 事实

- 回测区间：2019-01-02 至 2025-12-31；每月首个交易日开盘调仓，观察日为前一交易日。
- 股票池从 6,115 只历史 A 股主表按观察日生命周期展开，不使用当前股票池回填。
- 点时总市值为 B 级；历史 ST/停牌/涨跌停为 A/B 级；价格为 Qlib B 级。
- 共 84 次调仓；每次最少 3235 只合格候选；
  每次均选 10 只。
- 本地累计收益 2827.99%，年化 65.02%，
  最大回撤 41.12%，Sharpe 1.374，
  换手 35.88，平均现金比例 0.70%。
- 拒单 103 次；点时、覆盖和归档检查：{'full_master_is_6115': True, 'all_rebalances_have_ten_targets': True, 'no_valuation_future_data': True, 'no_partition_read_failures': True, 'known_st_for_archived_candidates': True, 'nonnegative_cash': True, 'orders_and_ledgers_present': True}。

## 限制

- 本地用连续复权价格表示分红送转影响；撮合器同时支持原始价加显式公司行为账本，
  但免费数据尚无全市场公司行为事件表。
- 本归档是聚宽运行前的本地审计，不包含聚宽黄金结果，不能单独完成迭代 5。
- 聚宽侧仅在本地规则、数据覆盖和未来数据检查通过后运行一次，并输出逐月候选、订单和持仓。
