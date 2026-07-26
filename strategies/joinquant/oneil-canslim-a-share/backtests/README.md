# 回测归档

当前包含一次本地研究级回测：

- `2026-07-26__baseline__local-qlib-eastmoney-2019-2025-v1/`

它使用历史沪深300和中证500成分、Qlib 日线、东方财富带公告日财务，以及沪深300
市场状态代理。它不是聚宽官方回测。后续每次运行仍应新增
`YYYY-MM-DD__{variant}__{run-id}/`，至少保存 `manifest.json`、`report.md`
和实际运行的 `source.py`，禁止覆盖已有目录。
