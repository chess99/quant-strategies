# 沪深300中期反转策略复现

本研究用于验收统一数据入口和日线撮合器。原策略来自聚宽帖子
[30350](https://www.joinquant.com/post/30350)，实际启用的是沪深300成分内中期跌幅最低
25 只的反转分支，而不是源码中被注释掉的动量分支。

本地实现保留原策略异常的“6 个交易日计一周、30 周调仓”计数逻辑，并使用历史指数
成分、上一交易日信号、下一交易日开盘成交。结果差异应结合归档报告中的数据源和
`5d` 聚合近似限制解释。

运行：

```powershell
$env:PYTHONPATH='src'
D:\code\_open-source\_venvs\qlib\Scripts\python.exe `
  studies\joinquant-csi300-reversal-replication\run_backtest.py
```

归档目录不可覆盖；重复实验必须使用新的 `--run-id`。
