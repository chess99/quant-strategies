"""聚宽自包含策略模板。"""

import builtins

try:
    from jqdata import *  # noqa: F403
except ImportError:
    pass


def initialize(context):
    set_benchmark("000300.XSHG")
    set_option("use_real_price", True)
    set_option("avoid_future_data", True)
    run_monthly(rebalance, 1, time="10:00")


def rebalance(context):
    current_data = get_current_data()
    # 使用 current_data[code] 触发惰性加载。
    _ = current_data
    _ = builtins.sum([])
