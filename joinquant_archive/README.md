# 聚宽原帖与回测信息采集器

这个目录独立于仓库中的策略族，用于把本地聚宽源码文件映射回原帖，并采集原帖元数据和回测框中的公开信息。

采集器只扫描源根目录下各分类子目录中的 `.txt` 和 `.py` 文件，不把根层的卖家说明、交流群素材等附带文件当作策略。输入目录中的 `2024年度精选策略1` 会统一归档为 `2024年度精选策略`。

## 输出设计

默认输出到 `joinquant_archive/data/`：

- `data/<原目录>/<原文件名>.json`：每个本地策略文件一个 JSON。
- `../sources/<年度分类>/<策略名>.py`：统一为 UTF-8 的来源代码快照。
- `../sources/manifest.jsonl`：来源文件哈希、转码方式和 Python 3 AST 解析状态。
- `summary.csv`：适合 Excel/WPS 直接查看，使用 UTF-8 BOM。
- `summary.jsonl`：每行一个策略，适合脚本、DuckDB、Polars 等工具读取。
- `issues.jsonl`：没有链接、没有回测框或请求失败的条目。
- `run-summary.json`：本次结果数量和状态统计。

单策略 JSON 包含：

- 本地文件路径、编码、SHA-256、全部聚宽链接和主链接选择依据；
- 原帖标题、正文、作者、标签、发布时间、阅读/回复/收藏/克隆等信息；
- 回测起止日期、初始资金、频率、Python 版本；
- 聚宽指标接口返回的全部原始指标；
- 常用指标的百分数展示值；
- 主贴没有回测框时，从楼主回复中找到的回测；
- 实际访问过的公开接口地址，便于审计和重跑。

不会保存接口返回的邮箱、EUID、客户端 IP 等与策略整理无关的字段。

## 运行

```powershell
python joinquant_archive/crawler.py `
  --source-root 'D:\BaiduNetdiskDownload\2020-2026聚宽600条源码'
```

默认 4 个工作线程，全局约每秒 5 个请求，并带重试、原子写入和断点复用。再次运行时，已有成功 JSON 会直接复用；需要重新抓取时加 `--refresh`。

源码快照默认同步到 `joinquant_archive/sources/`。采集器只将旧资料中的非代码卖家前言改成 Python 注释、统一转为 UTF-8，并脱敏硬编码邮箱和密码/token；不会自动修复旧式语法、缩进或策略逻辑。每个文件的转换和脱敏数量记录在 manifest 中。它们是可检索的来源归档，不代表已经满足仓库正式策略族的兼容性和回测要求。

常用选项：

```text
--output PATH             指定输出目录
--source-archive PATH     指定 UTF-8 .py 来源快照目录
--skip-source-archive     不更新来源快照
--workers 4               并发线程数
--min-interval 0.20       全局相邻请求最小间隔（秒）
--max-reply-pages 20      主贴无回测框时最多检查的回复页数
--include-series          额外保存完整逐点策略/基准收益曲线
--refresh                 忽略已有成功结果
--limit N                 只处理前 N 个本地文件，便于试跑
```

完整收益曲线默认不保存，因为数百个策略会产生大量重复日期点；回测总收益、基准收益、年化、波动率、回撤、Sharpe、Sortino、Information Ratio、胜率、盈亏比、换手率等指标默认都会保存。确有逐日曲线分析需求时使用 `--include-series`。
如果已有结果不含曲线，带 `--include-series` 再次运行时会自动重新抓取相应帖子。

## 测试

```powershell
python -m pytest joinquant_archive/tests -q
```

采集器只使用 Python 标准库，不需要额外安装运行依赖。
