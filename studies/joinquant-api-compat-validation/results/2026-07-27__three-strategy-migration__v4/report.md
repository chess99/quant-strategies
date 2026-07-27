# 聚宽日频兼容层三策略验收

观察日：2026-07-23。

同一 `JoinQuantCompat` 实例依次执行指数60日均线择时、四ETF动量轮动、四股票公告日基本面质量排序；未为三类逻辑各写一套数据读取代码。

机器检查：`{"index_60_sessions": true, "etf_four_ranked": true, "fundamental_four_visible": true, "notice_dates_point_in_time": true, "all_three_have_provenance": true, "all_three_have_versioned_provenance": true}`。

本轮只验收接口迁移与点时语义；策略收益黄金对照不在此报告中冒充完成。
