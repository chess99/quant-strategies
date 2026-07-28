# 聚宽核心资产 ETF 轮动本地复现

本研究用本地新浪 ETF 日线与 Qlib 沪深300指数，固定复现聚宽帖子
[`42673`](https://www.joinquant.com/post/42673) 的四资产轮动逻辑，不进行参数寻优。

策略每天用前一交易日及更早的 25 个收盘价，计算对数价格回归的年化斜率乘 R²，
持有得分最高的一只 ETF；下一交易日开盘执行。

资产池：

- `SH518880` 黄金 ETF
- `SH513100` 纳指 ETF
- `SZ159915` 创业板 ETF
- `SH510180` 上证180 ETF

本地数据为新浪原始行情，现金分红来自新浪累计分红表；常见份额拆分/合并倍率由
价格跳变识别并进入总收益调整因子，质量等级为 B。调整后单日绝对收益超过 30% 时
数据同步直接失败。

运行：

```powershell
D:\code\_open-source\_venvs\quant-research-py312\Scripts\python.exe `
  studies\joinquant-etf-rotation-replication\run_backtest.py `
  --data-root D:\code\_open-source\_data\quant-research `
  --run-id local-full-etf-universe-v4
```

归档目录存在时程序拒绝覆盖。

## 首次验收结果

完整归档见
[`results/2026-07-27__local-sina-qlib-v1/`](results/2026-07-27__local-sina-qlib-v1/)。

| 指标 | 聚宽 | 本地 |
|---|---:|---:|
| 年化收益 | 36.93% | 36.86% |
| 最大回撤 | 30.61% | 30.61% |
| Sharpe | 1.34 | 1.40 |
| 沪深300基准年化 | 5.58% | 5.61% |

年化差 `-0.07` 个百分点，最大回撤差小于 `0.01` 个百分点，ETF 数据和轮动逻辑
通过首次近似复现验收。固定资产池仍有事后选择风险，本结果不证明策略未来有效。

首次归档当时只记录了原策略路径和 SHA-256，没有保存 `source.py`。为遵守不可变归档规则，
原目录未被改写；同哈希源码已另存到
[`2026-07-29__local-sina-qlib-v1-source-addendum`](results/2026-07-29__local-sina-qlib-v1-source-addendum/)，
该附录不是一次新回测，也不产生新指标。

## 全量 ETF 数据验收

完整归档见
[`results/2026-07-27__local-full-etf-universe-v4/`](results/2026-07-27__local-full-etf-universe-v4/)。

本次使用 1,781 只候选、1,733 只有历史日线的全量数据底座；历史池含 125 只
已终止 ETF（上交所 79、深交所 46）。聚宽公开黄金回测接口
提供逐日四资产评分和订单总额，不需要重新运行聚宽：

- 逐日目标兼容匹配率 100%（2,297/2,297）；
- 唯一最高评分日期严格匹配率 100%（2,217/2,217）；
- 订单事件日期 Jaccard 98.55%；
- 年化和最大回撤与首次结果一致。

`local-full-etf-universe-v3` 是过滤巨潮公告假阳性之前生成的中间归档；它没有覆盖或
删除，但不作为最终数据底座证据。v4 已排除标题仅表示“流动性服务商终止”的
`SZ159892` 假阳性，并锁定最终 ETF 日线与统一证券主表 manifest 哈希。

ETF 全量覆盖、历史终止产品和质量限制见
[`docs/local-research/etf-data.md`](../../docs/local-research/etf-data.md)。
