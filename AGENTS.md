# Quant Strategies Agent Guide

本仓库用于保存可直接运行的量化策略、同一逻辑的小变体、自动化测试和不可变回测归档。

## 事实源与边界

- `strategies/{platform}/{strategy-family}/` 是单个策略族的事实源。
- 一个投资逻辑只建一个策略族；参数微调、小型信号替换和风险覆盖层变体放在该策略族的 `variants/` 下。
- 只有投资假设、目标市场或核心数据模型发生根本变化时，才新建策略族。
- 平台可执行源码必须自包含。聚宽策略不得依赖本仓库中的运行时模块导入。
- `baseline.py` 表示当前基线，不代表永远不变；历史可复现性由每次回测目录中的 `source.py` 保证。
- 已归档的回测目录不可覆盖或改写。发现错误时新增一次回测，并在新报告中引用旧结果。

## 标准策略族目录

```text
strategies/{platform}/{strategy-family}/
  README.md
  strategy.toml
  baseline.py
  variants/
    README.md
    {variant}.py
  tests/
    test_baseline.py
  backtests/
    YYYY-MM-DD__{variant}__{run-id}/
      manifest.json
      report.md
      source.py
      raw/          # 可选：净值、成交、持仓、日志
      assets/       # 可选：截图和图表
```

## 命名规范

- 目录和变体名使用小写 kebab-case，例如 `bill-miller-a-share`、`catalyst-filter`。
- Python 文件使用 snake_case；基线固定为 `baseline.py`。
- 回测目录名包含归档日期、变体名和稳定运行标识，不使用 `latest`。
- `strategy.toml` 中的 `id` 必须与策略族目录名一致。

## 开发流程

处理新增策略、修改策略、创建变体或归档聚宽回测时，必须先完整阅读：

1. `.agents/skills/manage-joinquant-strategy/SKILL.md`
2. `docs/architecture/repository-layout.md`
3. 涉及聚宽时读取 `docs/platforms/joinquant/pitfalls.md`

然后：

1. 明确本次修改属于基线、变体还是独立策略族。
2. 先补测试，再修改可执行源码。
3. 聚宽文件保持单文件、自包含和旧运行环境兼容。
4. 运行相关测试与 `python tools/validate_repo.py`。
5. 回测后新增不可变归档，保存精确 `source.py` 和 SHA-256。
6. 更新策略族 `README.md` 中的结果索引和已知限制。

## 回测归档规则

- 每次归档至少包含 `manifest.json`、`report.md`、`source.py`。
- `manifest.json` 必须记录平台、策略族、变体、回测区间、基准、成本参数、关键指标、来源链接或运行 ID、源码 SHA-256。
- 报告必须区分事实、推断和下一步实验，不只记录累计收益。
- 至少报告年化收益、最大回撤、Sharpe、换手、最长水下期和分阶段表现。
- 能导出的净值、成交和日志放入 `raw/`；超过 25 MB 的单文件先压缩，仍过大时只保存摘要和外部来源。
- 不根据同一全样本反复调参后只保存最好结果；失败实验同样归档。

## 聚宽硬规则

- 不使用 `from __future__ import annotations`。
- `from jqdata import *` 后，`sum`、`all`、`any` 必须通过 `builtins` 调用。
- `get_current_data()` 返回惰性映射，必须用 `current_data[code]` 触发加载，不以 `.get()` 判断不存在。
- 初始化时启用真实价格和避免未来数据；所有财务与行业查询显式使用观察日期。
- 调仓观察日默认是当前交易日的前一交易日。
- 回测策略不得依赖当前成分股、当前行业或当前财务数据去解释历史日期。
- 下单前处理停牌、ST、涨跌停、A 股 100 股整数手和卖出失败。
- 详细兼容性与 API 模式见 `docs/platforms/joinquant/pitfalls.md`。

## 提交规则

- 默认直接在当前分支工作，除非用户要求切分支。
- 每个完整迭代结束后主动提交。
- 只暂存本次自己创建或修改的文件；提交前检查 `git diff --staged`。
- 不提交临时下载、浏览器缓存、密钥、Cookie 或个人环境文件。
