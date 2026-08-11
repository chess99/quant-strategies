# 聚宽 Research Runner

这是仓库正式维护的聚宽 Research 执行后端。它使用聚宽研究环境中的 `jqdata` 获取点时行情，
自行完成日频调度、撮合、账本和结果导出，不调用聚宽官方策略回测任务。

它适合数据依赖型研究、参数预检和短周期黄金对照，不冒充聚宽完整回测引擎。

## 文件

```text
runners/joinquant-research/
  README.md
  research_runner.py
  examples/
    monthly_etf_momentum.py
tests/joinquant_research/
  test_runner.py
```

- `research_runner.py`：直接上传聚宽的单文件、自包含运行模块。
- `monthly_etf_momentum.py`：只演示策略回调和导出流程。
- `test_runner.py`：使用伪造的 `jqdata` 做本地确定性验证。

## 策略契约

策略提供一个函数，接收 `ResearchContext`，返回证券到目标权重的映射：

```python
def target_weights(context):
    observation_date = context.observation_date
    # 所有信号查询必须使用 observation_date 或更早日期。
    return {
        "510300.XSHG": 0.5,
        "510500.XSHG": 0.5,
    }
```

权重必须非负、有限且总和不超过 1；未使用的部分保留现金。回调还能读取：

- `context.current_date`：执行日；
- `context.observation_date` / `previous_date`：前一交易日；
- `context.portfolio`：执行前现金、总资产和持仓只读快照；
- `context.run_id`：运行标识。

Runner 固定在执行日前生成观察上下文，随后计算目标股数，先卖后买。卖出失败不会释放现金。
同一执行日不会在买入后再次卖出，因此日频目标权重接口天然不产生当日回转交易。

## 聚宽内运行

1. 将 `research_runner.py` 和策略文件上传到聚宽 Research 文件根目录。
2. 在 Notebook 中导入并运行：

```python
from monthly_etf_momentum import run

result, manifest, bundle = run()
manifest["metrics"]
```

3. 从文件列表下载返回的 ZIP。
4. 解压到对应策略族的新回测目录，核对 `manifest.json`、`source.py`、`engine.py` 和原始账本。
5. 更新策略族 README 的结果索引；已有回测目录不得覆盖。

不要把账号、Cookie、密码或 token 写入仓库。后续自动化只操作已经登录的浏览器页面，不读取
或持久化浏览器凭据，也不依赖聚宽未公开的内部接口。

## 输出契约

`ResearchResult.export()` 拒绝覆盖非空目录，并生成：

```text
{output}/
  manifest.json
  report.md
  source.py
  engine.py
  raw/
    equity.csv
    orders.csv
    trades.csv
    positions.csv
    log.txt          # 有警告时
{output}.zip
```

manifest 记录运行参数、费用、指标、策略源码 SHA-256、引擎 SHA-256 和每个工件的 SHA-256。
报告明确区分事实、推断、限制和下一步实验。

## 已实现语义

- 日、周、月频；周/月按实际首个或最后一个交易日调度；
- 前一交易日观察，执行日开盘或收盘成交；
- A 股整数手、现金约束、先卖后买；
- 停牌、ST、涨停买入和跌停卖出拒单；未知 ST/涨停状态默认拒绝买入；
- 买卖佣金、最低佣金、印花税和双向滑点；
- 现金、净值、订单、成交、持仓和警告账本；
- 累计/年化收益、最大回撤、Sharpe、换手、最长水下期和年度收益。

## 明确限制

- 不兼容聚宽 `initialize`、`run_daily`、`order_target_value` 等完整策略运行时；现有正式策略需
  抽取或包装为目标权重回调。
- 不模拟分钟、Tick、集合竞价、涨跌停排队、成交量冲击或部分成交。
- 默认使用连续前复权价格；公司行为后的名义股数、整数手和最低佣金不等同于逐事件模拟。
- 聚宽 Research 的环境、配额和可用内存由平台控制，不适合无限制并行参数搜索。
- 正式结论必须再与聚宽官方回测做同源码、同区间黄金对照。

第一批黄金对照建议依次使用 ETF 轮动、月度小市值、月度财务选股；只有目标、成交、持仓和
关键指标均达到各策略预设阈值后，才将这个后端作为该策略的默认 Research 执行方式。
