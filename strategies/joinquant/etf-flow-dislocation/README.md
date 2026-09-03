# ETF 资金流错位反转

## 投资假设

机构和产品约束可能制造“必须交易”而非“愿意交易”的订单流。第一版只研究其中最容易获得
日频点时数据的一类：**场内 ETF 大额份额收缩伴随的机械资金流/流动性错位**。

基线不把“下跌”本身当 alpha。只有同时出现：

1. ETF 20 个份额观察点累计赎回至少 5%；
2. ETF 20 日价格收益不高于 -8%；
3. 相对近 60 日高点回撤不高于 -12%；
4. 近 3 日已经停止继续下跌，且收盘重新站上 5 日均线；

才视为“卖压可能耗尽”的候选。候选按赎回极端程度、20 日跌幅和 60 日回撤的横截面百分位
排序，最多持有 3 只，风险预算最多 75%，余下资金进入货币 ETF。

这不是对“基金赎回必然导致反弹”的结论，而是一个可被数据直接否证的 research baseline。

## 为什么先做 ETF，而不是主动基金拥挤

主动基金的委托代理/追热门赛道问题更接近原始想法，但需要季度基金持仓、公告日、基金规模、
行业映射和披露口径统一，研究数据更慢且更容易产生前视偏差。ETF 的每日份额
`FUND_SHARE_DAILY` 能先把“机械资金流代理 → 价格冲击 → 后续反转”这个最基础命题测清楚。ETF 申赎可能包含实物交割和现金替代，所以份额下降不是主动基金 forced selling 的等价物。

如果第一层都不存在稳定增量，就没有必要把主动基金持仓模型复杂化。

## 基线

`baseline.py` 是聚宽可直接运行的研究基线，使用：

- `get_all_securities(..., date=as_of)` 重建观察日 ETF 生命周期；
- `FUND_INVEST_TARGET.pub_date/start_date/end_date` 做跟踪指数点时映射；
- `FUND_SHARE_DAILY` 计算 ETF 份额变化；
- 观察日固定为 `context.previous_date`；
- 周一 10:30 调仓；
- 同一跟踪指数只保留 ADV20 最大的 ETF；
- 逆波动率分配风险预算，单 ETF 上限 30%，目标持仓容量上限 0.5% ADV20；
- 最短持有 10 个自然日，最长 60 日；15% 止盈、12% 止损仅作为基线风险边界。

这些阈值是**事前粗参数**，不是全样本搜索后的赢家。

## 研究协议

第一阶段先做事件研究，不先优化组合收益。冻结协议：
`protocols/2026-08-25-v1.json`。

优先回答：

1. 极端赎回 + 急跌 + 止跌之后，未来 5/10/20/40 日收益是否显著高于无条件基准；
2. 收益是否集中在 2015、2020、2024 等少数冲击年份；
3. 宽基与行业 ETF 是否同方向；
4. 去掉最极端 5% 事件后是否仍成立；
5. 信号是否只是在复刻普通短期反转/高波动因子；
6. 参数是否形成高原，而不是只有某个阈值有效。

只有事件研究通过后，才进入完整组合回测、容量、成本和样本外研究。

## 本地 / 聚宽 Research 交接

执行状态、硬门槛和归档步骤另见 `LOCAL_HANDOFF.md`；该文件是下一次本地研究的起点。

### 1. 导出数据

在聚宽 Research 或本地已登录 JQData 的环境中运行：

```bash
python strategies/joinquant/etf-flow-dislocation/joinquant_export.py
```

默认导出 2015-01-01 至 2026-07-31，生成：

```text
exports/etf-flow-dislocation-inputs/
  etf_master.csv
  fund_invest_target.csv
  etf_daily.csv
  fund_share_daily.csv
  panel.csv
  export_summary.csv
```

`panel.csv` 包含 `date, code, open, close, money, shares`，同时保留 ETF `start_date/end_date` 生命周期，并附带按公告日/生效日重建的 `traced_index_code`、`traced_index_name`、`domestic_equity` 点时字段。

### 2. 事件研究和参数屏

```bash
python strategies/joinquant/etf-flow-dislocation/research.py \
  exports/etf-flow-dislocation-inputs/panel.csv \
  exports/etf-flow-dislocation-study-v1
```

输出：

- `events.csv`：冻结基线的独立冲击事件；同一 ETF 28 个自然日内连续触发只保留第一次，避免把一次赎回潮重复计数；
- `event_summary.csv`：5/10/20/40 日前瞻收益摘要；
- `parameter_grid.csv`：216 组粗网格，只用于观察参数高原，不允许从同一全样本挑冠军直接升级 baseline。

### 3. 后续本地研究顺序

如果事件研究支持假设，再做：

- 2015-2019 / 2020-2022 / 2023-2026 分阶段；
- expanding-window 样本外；
- 事件按 ETF / 跟踪指数聚类后的 bootstrap；
- 与普通 20 日反转、60 日回撤、波动率单因子做匹配对照；
- 加入交易成本和 0.5% ADV 成交参与率；
- 再把完全相同的冻结候选送入聚宽官方回测黄金对照。

## 变体

| 变体 | 假设差异 | 状态 |
|---|---|---|
| baseline | ETF 极端赎回 + 急跌 + 短期止跌后的均值回归 | research |

“主动基金拥挤解除 / 追热门赛道”暂不放进这个策略族。它的数据频率、持仓口径和退出逻辑不同，
如果后续研究会单独创建 `fund-crowding-unwind` 策略族，避免把两个机制混成一个历史拟合模型。

## 成功标准

第一阶段不是看 CAGR，而是看 alpha 是否存在：

- 冻结 baseline 的 20 日事件收益相对无条件 ETF 周频样本有正增量；
- 至少三个市场阶段方向一致；
- 宽基和行业 ETF 不依赖单一类别；
- 去掉贡献最高的 5% 事件后仍为正；
- 粗参数网格中多数相邻配置方向一致；
- 与普通价格反转匹配后仍保留增量。

第二阶段组合研究才看年化、最大回撤、Sharpe、换手、最长水下期、成本、容量和样本外。

## 回测索引

尚无回测结果。当前只完成策略实现、事前协议和研究交接，不把未运行的代码当作业绩证据。
