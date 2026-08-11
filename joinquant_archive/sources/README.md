# 聚宽策略来源快照

这里保存采集器输入资料中 593 份策略或研究代码的 UTF-8 `.py` 快照，按年度分类，便于搜索、比较和后续挑选。

这些文件来自历史帖子，尚未逐份验证：

- 只对 2020 年资料附带的非代码卖家前言做了注释化，其余代码逻辑保持不变；
- 硬编码邮箱和密码/token 会替换为 `<redacted-email>` 与 `<redacted-secret>`；
- `manifest.jsonl` 记录原文件和归档文件 SHA-256、编码转换以及 Python 3 AST 解析结果；
- AST 解析通过不等于策略符合当前聚宽 API、无未来数据或可复现；
- 需要正式维护的策略应另行迁入 `strategies/joinquant/<strategy-family>/`，补齐测试、说明和回测归档。

重新生成：

```powershell
python joinquant_archive/crawler.py `
  --source-root 'D:\BaiduNetdiskDownload\2020-2026聚宽600条源码'
```
