# 科创 50 ETF 冻结影子运行手册

## 状态与边界

本手册只覆盖 2026-09-02 G0-G3 归档机械选出的两个工程候选。它们使用的历史已经被研究者
看过，当前状态是**影子运行**，不是正式实盘策略，也不允许因后续短期收益修改规则。

两个模型都只持有 `588000` 或现金，收盘后观察，目标最早在下一交易日执行。

## S1：风险核心低换手版

冻结名称：`risk-friction__threshold-0p05`

1. 计算 200 日收盘均线；收盘价不高于均线时原始目标为 0。
2. 计算 60 日收盘收益年化波动率。
3. 趋势开启时，原始目标为 `min(99%, 15% / 实现波动率)`。
4. 当前目标为 0 或原始目标为 0 时立即接受变化；其他情况下，只有目标变化达到 5 个
   百分点才更新。
5. 基础回测假设为下一交易日开盘、单边 2bp 滑点、ETF 双边万三佣金、最低 5 元。

截至归档观察日 2026-09-01，冻结目标为 24.82%。该数值只用于校验实现，不能在更晚日期
继续当作当前信号。

## S2：固定三机制低换手组合

冻结名称：`production-ensemble__threshold-0p1`

1. 风险核心与 S1 相同，但先保留未经 5%阈值过滤的连续目标。
2. MACD 覆盖：使用 `(12, 26, 9)`；开启时保留全部核心目标，关闭时保留 25%。
3. Keltner 覆盖：20 日 EMA 与 2 倍 ATR 通道；开启时保留全部核心目标，关闭时保留 25%。
4. 三个目标固定等权平均，不根据近期收益更换权重或挑选赢家。
5. 当前目标为 0 或组合原始目标为 0 时立即接受变化；其他情况下，目标变化达到 10 个
   百分点才更新。

截至归档观察日 2026-09-01，冻结目标为 11.89%。同样只用于实现校验。

## 每日影子流程

1. 收盘后分别获取腾讯前复权日线和 Yahoo 调整日线；OHLC 最大相对差异超过 1%时不更新。
2. 保留腾讯主源全部交易日，在共同日期核验价格和成交量；核验源漏日只报警，不删除主源日。
3. 运行 `run_shadow_signals.py`，保存观察日期、数据质量、冻结版本、当前目标、前一目标和最近变化日；
   数据源异常时必须得到 `halted` 且模型列表为空。
4. 下一交易日取得开盘行情和明确的停牌、买卖限制状态后，运行 `run_shadow_operations.py plan`；
   相同状态生成相同订单标识，冻结目标未变化且上次调仓完成时不因价格漂移重复下单。
5. 记录真实开盘、5分钟成交均价、滑点、费用和券商成交标识；部分成交保持未决，收到取消、
   过期或拒绝回报后才能释放并重新规划。
6. 把每笔成交登记到账户，事件按上一事件哈希形成追加式链；每日核对理论与实际份额、现金、
   未决订单和模型净值，不以当日盈亏改变规则。

## 工具流程

首次建立两个独立影子账户：

```powershell
python studies/star50-single-asset-timing/run_shadow_operations.py initial `
  --cash 1000000 --output accounts.json
```

收盘后生成冻结目标。联网失败或双源差异超限时返回非零状态和结构化 `halted`，不会退化为
单源信号：

```powershell
python studies/star50-single-asset-timing/run_shadow_signals.py `
  --output snapshot.json
```

成功取得冻结日之后的新完整交易日时，使用独立命令保存输入、信号、源码和哈希；已存在的
同日目录会拒绝覆盖：

```powershell
python studies/star50-single-asset-timing/archive_shadow_observation.py `
  --end-date YYYY-MM-DD
```

下一交易日的 `quote.json` 必须来自可核验行情与证券状态，最少包含：

```json
{
  "symbol": "SH588000",
  "trade_date": "2026-09-02",
  "price": 1.0,
  "volume": 100000000,
  "paused": false,
  "buy_blocked": false,
  "sell_blocked": false
}
```

规划理论订单：

```powershell
python studies/star50-single-asset-timing/run_shadow_operations.py plan `
  --snapshot snapshot.json --accounts accounts.json --quote quote.json `
  --as-of-date 2026-09-02 --output plan.json
```

把券商或模拟成交保存为 `fill.json` 后登记到账户；输出中的 `accounts` 是下一次运行的新状态，
`event` 必须追加到只增不改的事件文件：

```powershell
python studies/star50-single-asset-timing/run_shadow_operations.py apply-fill `
  --accounts accounts.json --plan plan.json --fill fill.json `
  --output accounts-after-fill.json
```

部分成交的剩余订单在确认取消、过期或拒绝后释放；没有明确回报时保持停机：

```powershell
python studies/star50-single-asset-timing/run_shadow_operations.py release-order `
  --accounts accounts-after-fill.json --model risk-friction__threshold-0p05 `
  --order-id <order-id> --reason cancelled --output accounts-released.json
```

使用 `reconcile` 对比理论账户与外部账户，使用 `verify-ledger` 检查事件数组的完整哈希链。
这些命令只管理影子状态，不调用券商接口。

## 停机条件

任一条件发生时停止产生新的加仓建议，并保留原始日志：

- 双源 OHLC 差异超过 1%；
- 最新行情日期不一致或输入日期重复、倒序；
- 当前持仓、理论持仓或订单状态无法对账；
- 目标超出 0%—99%；
- 实际滑点连续 5 次高于 20bp 压力假设；
- 代码、参数、数据源或费用模型的哈希与冻结版本不一致。

## 监控与晋级

每日记录数据差异、目标仓位、理论成交、实际可成交价格和拒单；每月汇总换手、滑点、仓位
偏差和净值偏差。前三个月只评估运行正确性。冻结后至少积累 8 个新季度，才重新评估收益、
回撤、Sharpe、多重检验和目标门槛；未到该条件不得称为正式策略。
