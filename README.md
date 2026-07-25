# Quant Strategies

这是一个专门保存、测试和复盘量化策略的研究仓库。

仓库以“策略族”为管理单位：一个核心投资逻辑对应一个目录；同一逻辑的小变体放在该目录的 `variants/` 下；每次回测都在 `backtests/` 下生成不可变归档，并保存当时的精确源码快照。

## 目录概览

```text
quant-strategies/
  AGENTS.md
  docs/
    architecture/
    data-sources/
    platforms/joinquant/
  strategies/
    {platform}/{strategy-family}/
      README.md
      strategy.toml
      baseline.py
      variants/
      tests/
      backtests/
  templates/
    strategy-family/
  tools/
  .agents/skills/
```

当前策略族：

- `strategies/joinquant/bill-miller-a-share/`：比尔·米勒风格的 A 股纯量化选股策略。
- `strategies/joinquant/ktv-macd-resonance/`：KTV（Stochastic RSI 透明代理）与 MACD 共振策略。
- `strategies/joinquant/oneil-canslim-a-share/`：欧奈尔 CAN SLIM 风格的 A 股成长突破策略。
- `strategies/joinquant/social-security-shareholders/`：基于全国社保基金前十大流通股东披露的 A 股策略。

## 常用命令

```bash
python tools/validate_repo.py
pytest -q
```

开始工作前先阅读 [AGENTS.md](AGENTS.md)。新增策略、变体或回测归档时，还应按仓库内的 `manage-joinquant-strategy` skill 执行。

本地数据源验收记录见 [docs/data-sources/qlib-community-cn-audit-2026-07-23.md](docs/data-sources/qlib-community-cn-audit-2026-07-23.md)。
