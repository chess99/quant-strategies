# 回测归档

这里尚无已完成回测。

聚宽回测完成后，新建：

```text
YYYY-MM-DD__{variant}__{run-id}/
  manifest.json
  report.md
  source.py
  raw/
  assets/
```

`source.py` 必须是平台实际运行的精确源码，而不是事后修改的 `baseline.py`。失败或不理想的实验也应归档，已有归档不得覆盖。
