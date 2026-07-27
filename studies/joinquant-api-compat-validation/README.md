# 聚宽日频兼容层验收

本研究用同一 `JoinQuantCompat` 运行指数择时、ETF 轮动和基本面质量筛选三类逻辑，验证
代码格式转换、`count`/`history`、分区读取、公告日门禁及来源溯源。它不替代各业务迭代
要求的收益黄金对照。

运行：

```powershell
D:\code\_open-source\_venvs\quant-research-py312\Scripts\python.exe `
  studies\joinquant-api-compat-validation\run_validation.py
```
