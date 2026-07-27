# 聚宽日频兼容层验收

本研究用同一 `JoinQuantCompat` 运行指数择时、ETF 轮动和基本面质量筛选三类逻辑，验证
代码格式转换、`count`/`history`、分区读取、公告日门禁及来源溯源。它不替代各业务迭代
要求的收益黄金对照。

运行：

```powershell
D:\code\_open-source\_venvs\quant-research-py312\Scripts\python.exe `
  studies\joinquant-api-compat-validation\run_validation.py
```

最终归档是 `results/2026-07-27__three-strategy-migration__v4/`。v1 保留归档器异常，
v2 保留失败验收，v3 保留只有来源/质量而缺少 Qlib 数据版本的审计前结果，均未覆盖。
