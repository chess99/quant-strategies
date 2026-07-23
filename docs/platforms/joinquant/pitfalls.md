# 聚宽策略兼容性与 API 踩坑

本文记录已经验证过的聚宽写法。修改聚宽策略前必须阅读。

## 运行时语法

### 不使用 future annotations

部分聚宽运行环境不支持：

```python
from __future__ import annotations
```

更不能把 Markdown 强调符号复制成：

```python
from **future** import annotations
```

平台交付文件只包含合法 Python 源码。

### 避免依赖较新的 Python 或 pandas 参数

平台版本可能落后于本地环境。交付文件中避免：

- `zip(..., strict=True)`
- 只有新版本 pandas 才支持的 `groupby(..., dropna=...)`
- 仅用于类型标注便利、但运行时并不必要的新语法

本地测试应对平台文件做 AST 解析和禁止特性检查。

## `jqdata import *` 的名称覆盖

`from jqdata import *` 可能覆盖 Python 内建的 `sum`、`all`、`any`。正确模式：

```python
import builtins
from jqdata import *

total = builtins.sum(values)
valid = builtins.all(flags)
matched = builtins.any(flags)
```

测试应扫描 AST，禁止平台文件直接调用未限定的这三个名称。

## `get_current_data()` 是惰性映射

聚宽的 `current_data` 不是普通字典。用 `.get(code)` 可能不会触发标的快照加载，导致策略误判标的不存在并产生零交易。

正确模式：

```python
current_data = get_current_data()
snapshot = current_data[code]
```

本地测试使用实现 `__missing__` 的惰性映射模拟这一行为。

## 时间与未来数据

初始化至少设置：

```python
set_option("use_real_price", True)
set_option("avoid_future_data", True)
```

调仓日计算信号时默认使用前一交易日作为观察日。财务、估值、行业和价格查询都显式传入该日期：

```python
observation_date = previous_trade_day(context.current_dt.date())
get_fundamentals(query_object, date=observation_date)
get_industry(codes, date=observation_date)
```

不要使用今天能看到的股票池、行业分类或财务数据解释历史日期。

## 股票池与退市证券

历史回测应使用观察日的证券集合：

```python
get_all_securities(types=["stock"], date=observation_date)
```

随后按当日状态过滤上市天数、停牌、ST 和退市标识。不要从当前仍上市股票倒推历史股票池，否则会引入幸存者偏差。

## 批量查询

全 A 股财务和价格查询需要分批，避免单次查询过大或平台超时。推荐模式：

```python
for batch in chunked(codes, 300):
    ...
```

价格接口使用 `panel=False`，并对不同聚宽返回形状做统一归一化。缺少某个批次时应记录警告并继续，不应静默把全仓清空。

## 财务口径

- 年报、季度或最新报告必须明确区分，避免把单季度现金流与全年现金流直接比较。
- 金融企业的负债率、经营现金流与普通制造企业含义不同，应使用独立模型。
- 所有除法先处理零、负数和缺失值。
- 因子排序前做截尾；样本过小时不要输出貌似精确的百分位。

## 行业接口

`get_industry` 返回值可能同时含 `sw_l1`、`sw_l2`、`jq_l1`，字段也可能缺失。读取时逐层防御，并给无法识别的行业显式标签。

行业上限不能简单削减后留下随机现金。削减出的权重应重新分配给仍有容量的标的，或者由明确的总仓位规则决定保留现金。

## 下单

下单前分别判断：

- 买入：非停牌、非 ST、未涨停、目标金额至少能买 100 股。
- 卖出：非停牌、未跌停。
- A 股新开仓数量按 100 股整数手。

目标权重调整时先卖后买。卖出失败的持仓不能假定已经释放现金。

## 回测诊断

不能只看累计收益。至少检查：

- 分年度和分市场阶段收益
- 最大回撤、峰值到谷底和恢复时间
- 滚动三年最差收益
- 换手与交易成本敏感性
- 平均现金和现金来源
- 行业、规模、价值、质量、动量暴露
- 收益是否集中在极少数年份

聚宽页面只展示部分成交或持仓明细时，优先保存导出文件和日志；平台统计值与本地计算值要注明口径差异。
