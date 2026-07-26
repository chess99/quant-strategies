# 本地价值质量策略验收

这个研究不是寻找“最优因子”，而是验证公告日财务、历史估值、历史指数成分、统一接口
和日线撮合能够在 2019–2025 年完整运行，并用审计字段证明没有读取观察日之后的财务。

策略月初从历史中证800成分中选择 20 只低估值、高 ROE、增长未明显恶化的股票。
当前行业快照只有 C 级且从 2026-07-26 起有效，因此验收明确不使用行业数据。

```powershell
$env:PYTHONPATH='src'
D:\code\_open-source\_venvs\qlib\Scripts\python.exe `
  studies\local-value-quality-validation\run_backtest.py
```

结果目录不可覆盖；修订实验使用新的 `--run-id`。
