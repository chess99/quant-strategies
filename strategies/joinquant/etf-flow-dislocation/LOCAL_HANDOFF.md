# ETF Flow Dislocation 本地研究交接

## 当前状态

- 已完成：策略族骨架、聚宽 `baseline.py`、点时数据导出脚本、事件研究脚本、事前协议和单元测试。
- 已冻结：`protocols/2026-08-25-v1.json`；截至冻结时没有事件研究结果、参数搜索结果或组合回测结果。
- 未完成：真实 JQData 数据导出、事件研究、匹配对照、bootstrap、组合回测、聚宽官方黄金对照。
- 禁止：看到全样本结果后修改冻结 baseline 再宣称“事前参数”；任何后验实验必须新建协议/变体并明确标记。

## 第 0 步：拉取后验证

```bash
pytest -q strategies/joinquant/etf-flow-dislocation/tests/test_baseline.py
pytest -q
python tools/validate_repo.py
git diff --check
```

如果全仓基线不是绿色，先区分既有失败与本次新增失败，不要在失败基线上开始调参。

## 第 1 步：导出 JoinQuant/JQData 原始面板

在可访问 `jqdata` 的环境运行：

```bash
python strategies/joinquant/etf-flow-dislocation/joinquant_export.py
```

检查 `exports/etf-flow-dislocation-inputs/export_summary.csv`：

1. `historically_terminated_etfs` 必须大于 0；否则先修复历史 ETF master，停止后续研究。
2. `share_first_date/share_last_date` 应覆盖主要研究区间。
3. 按 ETF 检查 `FUND_SHARE_DAILY` 缺口；脚本最多只向前填充 10 个价格观察日，长缺口保留为空。
4. 抽查若干历史日期，确认 `traced_index_code/name` 只在 `max(pub_date, start_date)` 后生效，并尊重 `end_date`。
5. 记录所有原始导出文件 SHA-256；后续结果必须绑定这组输入。

## 第 2 步：先证伪事件 alpha

```bash
python strategies/joinquant/etf-flow-dislocation/research.py \
  exports/etf-flow-dislocation-inputs/panel.csv \
  exports/etf-flow-dislocation-study-v1
```

先读 `event_summary.csv`，不要先看参数冠军。冻结 baseline 的主判据是 20 个交易日前瞻收益相对无条件 ETF 周频样本的 `incremental_mean_return`。同一 ETF 28 个自然日内的连续信号只算一个冲击事件。

若冻结 baseline 连最基础的方向都不对，记录失败并停止；不要靠 216 组网格寻找一个能赚钱的故事。

## 第 3 步：协议要求的诊断

只有第 2 步方向成立才继续：

- 预先固定三个阶段：2015-2019、2020-2022、2023-2026；
- 宽基 vs 行业 ETF；
- 删除贡献最高的 5% 事件；
- 对 `ret20/drawdown60/vol20` 做匹配或分层控制，验证份额流是否有增量；
- 以 ETF / 跟踪指数为 cluster 做 block/bootstrap 置信区间；
- 看 216 组粗网格的邻域高原，不用全样本最优点替换 baseline。

这一步要产出机器可读 CSV/JSON，不能只留 Notebook 图。

## 第 4 步：组合化（仅在事件 alpha 通过后）

冻结 `baseline.py` 参数先跑，不调参。至少报告：

- 年化、最大回撤、Sharpe、换手、最长水下期；
- 单边 5/10/20/30bp 成本敏感性；
- 0.5% ADV 成交参与率和不同资金规模；
- 事件/ETF/年份贡献删除；
- expanding-window 样本外；
- 与简单的“20 日超跌 + 3 日止跌”无份额流版本做配对基准。

如果份额流版本不能稳定战胜简单价格反转，结论应是“没有证明机构流量带来独立 alpha”。

## 第 5 步：聚宽官方黄金对照与归档

本地结果通过后，把**同一个冻结源码**送入聚宽官方回测，重点对齐信号日期、成交、持仓和费用，不只对齐最终 CAGR。

新增不可变目录：

```text
backtests/YYYY-MM-DD__baseline__{run-id}/
  manifest.json
  report.md
  source.py
  raw/
  assets/
```

`report.md` 必须分开写事实、推断、限制、下一步实验。失败结果同样归档。

## 机制边界

ETF 份额收缩只是机械资金流/流动性压力代理。ETF 申赎可能使用实物交割和现金替代，因此不能把本策略结果表述成“基金被迫卖出底层股票”的直接证据。真正的主动基金 forced-selling / crowded-unwind 研究应另建 `fund-crowding-unwind`，使用基金规模、季度持仓、披露日和共同持仓网络。
