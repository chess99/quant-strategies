"""验证科创 50 ETF 冻结影子模型的订单、容量、账本与故障安全。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


SOURCE_PATH = Path(__file__).resolve()
STUDY_DIR = SOURCE_PATH.parent
RESULTS_DIR = STUDY_DIR / "results"
SIGNAL_PATH = STUDY_DIR / "run_shadow_signals.py"
OPERATIONS_PATH = STUDY_DIR / "run_shadow_operations.py"
PROTOCOL_PATH = STUDY_DIR / "OPERATIONS_PROTOCOL.md"
DEFAULT_INPUT = (
    RESULTS_DIR
    / "2026-09-01__walk-forward-technical-families__tencent-yahoo-2020-2026-v1"
    / "raw"
    / "input-sh588000.csv"
)
ARCHIVE_NAME = "2026-09-02__shadow-operations-o0-o4__tencent-yahoo-2020-2026-v1"
OOS_START = pd.Timestamp("2023-12-25")
CAPITAL_GRID = (
    10_000.0,
    50_000.0,
    100_000.0,
    500_000.0,
    1_000_000.0,
    5_000_000.0,
    10_000_000.0,
    50_000_000.0,
    100_000_000.0,
    500_000_000.0,
    1_000_000_000.0,
)
VOLUME_RATIOS = (0.001, 0.005, 0.01)
SLIPPAGES = (0.0002, 0.002)


def _load_local_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块：{path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


shadow = _load_local_module("star50_operational_shadow", SIGNAL_PATH)
operations = _load_local_module("star50_operational_core", OPERATIONS_PATH)
extension = shadow.extension
engine = shadow.engine


@dataclass(frozen=True)
class Scenario:
    model: str
    capital: float
    volume_ratio: float
    slippage: float

    @property
    def name(self) -> str:
        def slug(value) -> str:
            return f"{value:g}".replace("-", "m").replace(".", "p")

        return (
            f"{self.model}__capital-{slug(self.capital)}"
            f"__volume-{slug(self.volume_ratio)}__slippage-{slug(self.slippage)}"
        )


def build_scenarios() -> list[Scenario]:
    return [
        Scenario(model, capital, volume_ratio, slippage)
        for model in operations.FROZEN_CONFIG_NAMES
        for capital in CAPITAL_GRID
        for volume_ratio in VOLUME_RATIOS
        for slippage in SLIPPAGES
    ]


def _longest_true_run(values) -> int:
    longest = current = 0
    for value in values:
        current = current + 1 if bool(value) else 0
        longest = max(longest, current)
    return longest


def _market_quote(frame: pd.DataFrame, position: int) -> dict:
    date = frame.index[position]
    row = frame.iloc[position]
    previous_close = float(frame.iloc[position - 1]["close"])
    opening_gap = float(row["open"]) / previous_close - 1.0
    return {
        "symbol": engine.SYMBOL,
        "trade_date": pd.Timestamp(date).strftime("%Y-%m-%d"),
        "price": float(row["open"]),
        "volume": float(row["volume"]),
        "paused": bool(float(row["volume"]) <= 0.0),
        "buy_blocked": bool(opening_gap >= 0.195),
        "sell_blocked": bool(opening_gap <= -0.195),
    }


def replay_scenario(frame: pd.DataFrame, config, scenario: Scenario) -> dict:
    if scenario.model != config.name:
        raise ValueError("场景与冻结模型不一致")
    target = extension.generate_production_target(frame, config)
    account = operations.initial_account(config.name, scenario.capital)
    equity_rows = []
    order_rows = []
    events = []
    fee_ratios = []
    rounding_errors = []
    previous_total = scenario.capital
    index_lookup = {date: position for position, date in enumerate(frame.index)}
    calendar = frame.index[frame.index >= OOS_START]
    for trade_date in calendar:
        position = index_lookup[trade_date]
        if position <= 0:
            continue
        observation_date = frame.index[position - 1]
        target_weight = float(target.iloc[position - 1])
        quote = _market_quote(frame, position)
        open_price = float(quote["price"])
        value_before = float(account["cash"]) + int(account["shares"]) * open_price
        theoretical_shares = (
            int(value_before * target_weight / open_price)
            // operations.LOT_SIZE
            * operations.LOT_SIZE
        )
        theoretical_weight = (
            theoretical_shares * open_price / value_before if value_before > 0.0 else 0.0
        )
        rounding_errors.append(abs(theoretical_weight - target_weight))
        model = {
            "config": config.name,
            "objective": config.objective,
            "target_weight": target_weight,
        }
        order = operations.plan_order(
            model,
            account,
            quote,
            pd.Timestamp(observation_date).strftime("%Y-%m-%d"),
            maximum_volume_ratio=scenario.volume_ratio,
        )
        order_rows.append({"scenario": scenario.name, **order})
        if order["status"] == "planned":
            direction = 1.0 if order["side"] == "buy" else -1.0
            fill_price = open_price * (1.0 + direction * scenario.slippage)
            gross = fill_price * int(order["planned_shares"])
            fee = max(operations.MINIMUM_COMMISSION, gross * operations.COMMISSION_RATE)
            fill = {
                "fill_id": f"{scenario.name}__{pd.Timestamp(trade_date):%Y-%m-%d}",
                "order_id": order["order_id"],
                "trade_date": pd.Timestamp(trade_date).strftime("%Y-%m-%d"),
                "side": order["side"],
                "shares": int(order["planned_shares"]),
                "price": fill_price,
                "fee": fee,
            }
            account, event = operations.apply_fill(account, order, fill)
            events.append({"scenario": scenario.name, **event})
            fee_ratios.append(fee / gross if gross > 0.0 else 0.0)
        close_price = float(frame.loc[trade_date, "close"])
        total_value = float(account["cash"]) + int(account["shares"]) * close_price
        open_total_after = float(account["cash"]) + int(account["shares"]) * open_price
        actual_weight = (
            int(account["shares"]) * open_price / open_total_after
            if open_total_after > 0.0
            else 0.0
        )
        equity_rows.append(
            {
                "scenario": scenario.name,
                "trade_date": trade_date,
                "cash": float(account["cash"]),
                "shares": int(account["shares"]),
                "close": close_price,
                "total_value": total_value,
                "daily_return": total_value / previous_total - 1.0,
                "target_weight": target_weight,
                "actual_open_weight": actual_weight,
                "absolute_target_gap": abs(actual_weight - target_weight),
                "decision_required": not (
                    order["status"] == "no_order" and order["reason"] == "target_unchanged"
                ),
                "rebalance_incomplete": bool(account["rebalance_incomplete"]),
            }
        )
        previous_total = total_value
    equity = pd.DataFrame(equity_rows)
    orders = pd.DataFrame(order_rows)
    event_frame = pd.DataFrame(events)
    return_metrics = engine._metrics_from_returns(equity["daily_return"])
    participations = pd.to_numeric(orders["volume_participation"], errors="coerce").fillna(0.0)
    all_day_gaps = pd.to_numeric(equity["absolute_target_gap"], errors="raise")
    target_gaps = all_day_gaps.loc[equity["decision_required"].astype(bool)]
    if target_gaps.empty:
        target_gaps = pd.Series([0.0])
    fees = pd.to_numeric(event_frame.get("fee", pd.Series(dtype=float)), errors="coerce")
    metrics = {
        "scenario": scenario.name,
        "model": scenario.model,
        "capital": scenario.capital,
        "maximum_volume_ratio": scenario.volume_ratio,
        "slippage": scenario.slippage,
        "annualized_return": return_metrics["annualized_return"],
        "maximum_drawdown": return_metrics["maximum_drawdown"],
        "sharpe": return_metrics["sharpe"],
        "total_fees": float(fees.sum()) if not fees.empty else 0.0,
        "filled_order_count": int(len(event_frame)),
        "capacity_limited_order_count": int(orders["reason"].eq("capacity_limited").sum()),
        "blocked_order_count": int(orders["status"].eq("blocked").sum()),
        "maximum_volume_participation": float(participations.max()),
        "average_absolute_target_gap": float(target_gaps.mean()),
        "p95_absolute_target_gap": float(target_gaps.quantile(0.95)),
        "maximum_absolute_target_gap": float(target_gaps.max()),
        "p95_all_day_exposure_drift": float(all_day_gaps.quantile(0.95)),
        "longest_unfinished_rebalance_days": _longest_true_run(
            equity["rebalance_incomplete"]
        ),
        "average_rounding_error": float(np.mean(rounding_errors)),
        "maximum_rounding_error": float(np.max(rounding_errors)),
        "average_fee_to_trade_value": float(np.mean(fee_ratios)) if fee_ratios else 0.0,
        "maximum_fee_to_trade_value": float(np.max(fee_ratios)) if fee_ratios else 0.0,
        "minimum_cash": float(equity["cash"].min()),
        "minimum_shares": int(equity["shares"].min()),
        "event_chain_valid": bool(
            operations.verify_event_chain(
                [{key: value for key, value in event.items() if key != "scenario"} for event in events]
            )
        ),
    }
    metrics["engineering_capacity_gate"] = bool(
        metrics["minimum_cash"] >= -0.01
        and metrics["minimum_shares"] >= 0
        and metrics["event_chain_valid"]
        and metrics["p95_absolute_target_gap"] <= 0.02
        and metrics["longest_unfinished_rebalance_days"] <= 5
    )
    return {"metrics": metrics, "equity": equity, "orders": orders, "events": event_frame}


def causality_audit(
    frame: pd.DataFrame,
    configs,
    dates=None,
) -> pd.DataFrame:
    if dates is None:
        dates = list(frame.index[259:])
    rows = []
    for config in configs:
        full = extension.generate_production_target(frame, config)
        for date in dates:
            date = pd.Timestamp(date)
            prefix = frame.loc[:date]
            prefix_target = extension.generate_production_target(prefix, config)
            full_value = float(full.loc[date])
            prefix_value = float(prefix_target.iloc[-1])
            rows.append(
                {
                    "model": config.name,
                    "observation_date": date,
                    "full_target": full_value,
                    "prefix_target": prefix_value,
                    "absolute_difference": abs(full_value - prefix_value),
                    "matched": bool(math.isclose(full_value, prefix_value, abs_tol=1e-12)),
                }
            )
    return pd.DataFrame(rows)


def _expect_halt(name: str, function) -> dict:
    try:
        function()
    except operations.OperationHalt as exc:
        return {"case": name, "passed": True, "result": "halted", "reason": str(exc)}
    return {"case": name, "passed": False, "result": "not_halted", "reason": None}


def run_fault_injection() -> dict:
    name = operations.FROZEN_CONFIG_NAMES[0]
    model = {"config": name, "objective": "risk", "target_weight": 0.5}
    account = operations.initial_account(name, 100_000.0)
    quote = {
        "symbol": engine.SYMBOL,
        "trade_date": "2026-09-02",
        "price": 1.0,
        "volume": 1_000_000,
        "paused": False,
        "buy_blocked": False,
        "sell_blocked": False,
    }
    snapshot = {
        "schema_version": 1,
        "symbol": engine.SYMBOL,
        "status": "shadow_only",
        "observation_date": "2026-09-01",
        "data": {"maximum_ohlc_relative_error": 0.001},
        "models": [model],
    }
    cases = []
    cases.append(
        _expect_halt(
            "wrong-symbol",
            lambda: operations.plan_order(model, account, {**quote, "symbol": "SH510300"}, "2026-09-01"),
        )
    )
    cases.append(
        _expect_halt(
            "same-day-quote",
            lambda: operations.plan_order(
                model, account, {**quote, "trade_date": "2026-09-01"}, "2026-09-01"
            ),
        )
    )
    cases.append(
        _expect_halt(
            "nonfinite-price",
            lambda: operations.plan_order(model, account, {**quote, "price": np.nan}, "2026-09-01"),
        )
    )
    cases.append(
        _expect_halt(
            "zero-volume",
            lambda: operations.plan_order(model, account, {**quote, "volume": 0}, "2026-09-01"),
        )
    )
    cases.append(
        _expect_halt(
            "unknown-tradability",
            lambda: operations.plan_order(model, account, {**quote, "paused": None}, "2026-09-01"),
        )
    )
    pending = {**account, "pending_order_id": "old-order", "pending_shares": 100}
    cases.append(
        _expect_halt(
            "pending-order-conflict",
            lambda: operations.plan_order(model, pending, quote, "2026-09-01"),
        )
    )
    cases.append(
        _expect_halt(
            "target-above-limit",
            lambda: operations.plan_order({**model, "target_weight": 1.0}, account, quote, "2026-09-01"),
        )
    )
    cases.append(
        _expect_halt(
            "stale-snapshot",
            lambda: operations.validate_snapshot(snapshot, as_of_date="2026-09-08"),
        )
    )
    divergent = {**snapshot, "data": {"maximum_ohlc_relative_error": 0.02}}
    cases.append(
        _expect_halt(
            "cross-source-divergence",
            lambda: operations.validate_snapshot(divergent, as_of_date="2026-09-02"),
        )
    )
    cases.append(
        _expect_halt(
            "account-mismatch",
            lambda: operations.reconcile_account(account, {"cash": 99_000.0, "shares": 0}),
        )
    )
    order = operations.plan_order(model, account, quote, "2026-09-01")
    fill = {
        "fill_id": "fault-fill",
        "order_id": order["order_id"],
        "trade_date": "2026-09-02",
        "side": "buy",
        "shares": int(order["planned_shares"]),
        "price": 1.0002,
        "fee": 5.0,
    }
    updated, event = operations.apply_fill(account, order, fill)
    cases.append(
        _expect_halt(
            "duplicate-fill",
            lambda: operations.apply_fill(updated, order, fill),
        )
    )
    sell_account = operations.initial_account(name, 0.0, shares=10_000)
    sell_model = {**model, "target_weight": 0.0}
    sell_order = operations.plan_order(sell_model, sell_account, quote, "2026-09-01")
    empty_account = {**sell_account, "shares": 0}
    sell_fill = {
        "fill_id": "oversell-fill",
        "order_id": sell_order["order_id"],
        "trade_date": "2026-09-02",
        "side": "sell",
        "shares": int(sell_order["planned_shares"]),
        "price": 0.9998,
        "fee": 5.0,
    }
    cases.append(
        _expect_halt(
            "oversell",
            lambda: operations.apply_fill(empty_account, sell_order, sell_fill),
        )
    )
    tampered = dict(event)
    tampered["cash_after"] += 1.0
    cases.append(
        {
            "case": "hash-chain-tamper",
            "passed": not operations.verify_event_chain([tampered]),
            "result": "rejected" if not operations.verify_event_chain([tampered]) else "accepted",
            "reason": "event payload changed",
        }
    )
    network_halt = operations.halted_result("market_data_or_signal", OSError("source unavailable"))
    cases.append(
        {
            "case": "external-source-failure",
            "passed": network_halt["status"] == "halted" and network_halt["orders"] == [],
            "result": network_halt["status"],
            "reason": network_halt["reason"],
        }
    )
    return {"all_passed": all(row["passed"] for row in cases), "cases": cases}


def _capacity_summary(metrics: pd.DataFrame) -> pd.DataFrame:
    stressed = metrics[
        metrics["maximum_volume_ratio"].eq(0.01) & metrics["slippage"].eq(0.002)
    ]
    rows = []
    for model, group in stressed.groupby("model", sort=False):
        passed = group[group["engineering_capacity_gate"]]
        capacity = float(passed["capital"].max()) if not passed.empty else 0.0
        first_failed = group.loc[~group["engineering_capacity_gate"], "capital"]
        rows.append(
            {
                "model": model,
                "historical_engineering_capacity": capacity,
                "first_failed_capital": float(first_failed.min()) if not first_failed.empty else np.nan,
                "all_preregistered_capitals_passed": bool(len(passed) == len(group)),
            }
        )
    return pd.DataFrame(rows)


def _live_check(end_date: str) -> dict:
    try:
        live_frame = engine.fetch_market_data(end_date)
        snapshot = shadow.compute_shadow_snapshot(live_frame)
        operations.validate_snapshot(snapshot, as_of_date=end_date, require_cross_check=True)
        return snapshot
    except (KeyError, OSError, TimeoutError, ValueError, operations.OperationHalt) as exc:
        return operations.halted_result("live_cross_check", exc)


def run_operational_readiness(frame: pd.DataFrame, live_end_date: str | None = None) -> dict:
    configs = shadow.frozen_configs()
    scenario_rows = []
    baseline_equity = []
    baseline_orders = []
    baseline_events = []
    config_lookup = {config.name: config for config in configs}
    for scenario in build_scenarios():
        result = replay_scenario(frame, config_lookup[scenario.model], scenario)
        scenario_rows.append(result["metrics"])
        if (
            scenario.capital == 1_000_000.0
            and scenario.volume_ratio == 0.01
            and scenario.slippage == 0.002
        ):
            baseline_equity.append(result["equity"])
            baseline_orders.append(result["orders"])
            baseline_events.append(result["events"])
    metrics = pd.DataFrame(scenario_rows)
    causal = causality_audit(frame, configs)
    faults = run_fault_injection()
    return {
        "scenario_metrics": metrics,
        "capacity_summary": _capacity_summary(metrics),
        "causality_audit": causal,
        "fault_injection": faults,
        "baseline_equity": pd.concat(baseline_equity, ignore_index=True),
        "baseline_orders": pd.concat(baseline_orders, ignore_index=True),
        "baseline_events": pd.concat(baseline_events, ignore_index=True),
        "live_check": _live_check(live_end_date) if live_end_date else None,
    }


def _percent(value) -> str:
    return f"{float(value):.2%}"


def build_report(bundle: dict, frame: pd.DataFrame) -> str:
    metrics = bundle["scenario_metrics"]
    capacity = bundle["capacity_summary"]
    causal = bundle["causality_audit"]
    faults = bundle["fault_injection"]
    stressed = metrics[
        metrics["maximum_volume_ratio"].eq(0.01) & metrics["slippage"].eq(0.002)
    ]
    lines = [
        "# 科创 50 ETF O0-O4 影子执行与运营就绪研究",
        "",
        "## 结论",
        "",
        f"固定输入为 {frame.index.min():%Y-%m-%d} 至 {frame.index.max():%Y-%m-%d}，",
        f"共 {len(frame):,} 个交易日；订单回放区间从 {OOS_START:%Y-%m-%d} 开始。",
        f"本轮完整运行 {len(metrics)} 个预注册资金/容量/滑点场景，",
        f"逐点因果复算 {len(causal):,} 个模型日期，故障注入 {len(faults['cases'])} 项。",
        "本轮没有修改冻结信号，因此结论只涉及工程可执行性，不增加历史 Alpha 证据。",
        "",
        "## O0：因果与确定性",
        "",
        f"逐点前缀复算匹配 {int(causal['matched'].sum()):,}/{len(causal):,}；",
        "订单标识由模型、观察日、交易日、账户、目标和数量确定，同一输入重复运行完全一致。",
        "",
        "## O1-O2：资金规模与容量",
        "",
        "下表使用最严格预注册组合：20bp 滑点、单日成交量 1% 上限。容量是历史工程上限，",
        "没有建模未来冲击成本，不能直接当作真实可承载资金。",
        "",
        "| 模型 | 历史工程容量 | 首个失败资金 | 全部档位通过 |",
        "|---|---:|---:|---:|",
    ]
    for row in capacity.itertuples(index=False):
        failed = (
            "未出现" if pd.isna(row.first_failed_capital) else f"{row.first_failed_capital:,.0f}元"
        )
        lines.append(
            f"| `{row.model}` | {row.historical_engineering_capacity:,.0f}元 | "
            f"{failed} | {'是' if row.all_preregistered_capitals_passed else '否'} |"
        )
    lines.extend(
        [
            "",
            "### 100万元压力场景",
            "",
            "| 模型 | 年化 | 回撤 | Sharpe | 95%目标偏差 | 最长未完成 | 成交数 | 总费用 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in stressed[stressed["capital"].eq(1_000_000.0)].itertuples(index=False):
        lines.append(
            f"| `{row.model}` | {_percent(row.annualized_return)} | "
            f"{_percent(row.maximum_drawdown)} | {row.sharpe:.2f} | "
            f"{_percent(row.p95_absolute_target_gap)} | "
            f"{row.longest_unfinished_rebalance_days}日 | {row.filled_order_count} | "
            f"{row.total_fees:,.2f}元 |"
        )
    lines.extend(
        [
            "",
            "### 容量边界失败诊断",
            "",
            "| 模型 | 资金 | 95%决策日偏差 | 最长未完成 | 容量受限订单 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for capacity_row in capacity.itertuples(index=False):
        if pd.isna(capacity_row.first_failed_capital):
            continue
        failed_row = stressed[
            stressed["model"].eq(capacity_row.model)
            & stressed["capital"].eq(capacity_row.first_failed_capital)
        ].iloc[0]
        lines.append(
            f"| `{capacity_row.model}` | {capacity_row.first_failed_capital:,.0f}元 | "
            f"{_percent(failed_row['p95_absolute_target_gap'])} | "
            f"{int(failed_row['longest_unfinished_rebalance_days'])}日 | "
            f"{int(failed_row['capacity_limited_order_count'])} |"
        )
    lines.extend(
        [
            "",
            "## O3-O4：账本与故障安全",
            "",
            f"故障注入通过 {sum(case['passed'] for case in faults['cases'])}/{len(faults['cases'])}。",
            "覆盖错误标的、过期/分歧行情、未知交易状态、未决订单、重复成交、超额卖出、",
            "账户差异、哈希篡改和外部数据源失败。系统故障输出 `halted` 且不含订单；",
            "停牌或涨跌停输出 `blocked`，不会与系统故障混淆。",
            "",
            "## 运行日双源检查",
            "",
        ]
    )
    live_check = bundle["live_check"]
    if live_check is None:
        lines.append("本次未请求联网检查。")
    elif live_check.get("status") == "shadow_only":
        lines.extend(
            [
                f"双源检查成功，最新完整观察日为 {live_check['observation_date']}，",
                f"OHLC 最大相对差异为 "
                f"{_percent(live_check['data']['maximum_ohlc_relative_error'])}。",
            ]
        )
    else:
        lines.extend(
            [
                f"双源检查状态为 `halted`：{live_check.get('reason')}。",
                "该次运行没有退化为单源，也没有生成订单；这属于需要持续统计的数据源可用率事件。",
            ]
        )
    lines.extend(
        [
            "",
            "## 仍不能由历史解决的事项",
            "",
            "- 免费日线的证券状态仍只有 C 级，正式下单必须改用券商或交易所实时状态；",
            "- 容量实验只有成交量硬上限和固定滑点，没有盘口深度、冲击函数和排队位置；",
            "- 还没有真实券商回报、撤单、断线重连和交易所拒单记录；",
            "- 收益晋级仍必须等待冻结后的至少 8 个新季度，不能用本轮工程回放替代。",
            "",
            "因此当前最高状态仍是影子运行就绪，不是自动实盘就绪。下一步不再改历史规则，",
            "只积累真实模拟成交、数据源可用率、滑点、拒单、对账与未来季度结果。",
            "",
        ]
    )
    return "\n".join(lines)


def _json_safe(value):
    return engine._json_safe(value)


def _write_json(value, path: Path) -> None:
    path.write_text(
        json.dumps(_json_safe(value), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_result(bundle: dict, frame: pd.DataFrame, input_path: Path) -> Path:
    destination = RESULTS_DIR / ARCHIVE_NAME
    if destination.exists():
        raise FileExistsError(f"不可覆盖既有归档：{destination.name}")
    raw = destination / "raw"
    raw.mkdir(parents=True)
    bundle["scenario_metrics"].to_csv(raw / "scenario-metrics.csv", index=False)
    bundle["capacity_summary"].to_csv(raw / "capacity-summary.csv", index=False)
    bundle["causality_audit"].to_csv(raw / "causality-audit.csv", index=False)
    bundle["baseline_equity"].to_csv(raw / "baseline-equity.csv", index=False)
    bundle["baseline_orders"].to_csv(raw / "baseline-orders.csv", index=False)
    bundle["baseline_events"].to_csv(raw / "baseline-events.csv", index=False)
    _write_json(bundle["fault_injection"], raw / "fault-injection.json")
    _write_json(bundle["live_check"], raw / "live-cross-check.json")
    shutil.copy2(input_path, raw / "input-sh588000.csv")
    shutil.copy2(SOURCE_PATH, destination / "source.py")
    shutil.copy2(OPERATIONS_PATH, destination / "operations.py")
    shutil.copy2(SIGNAL_PATH, destination / "signals.py")
    shutil.copy2(extension.SOURCE_PATH, destination / "extension.py")
    shutil.copy2(engine.SOURCE_PATH, destination / "engine.py")
    report_path = destination / "report.md"
    report_path.write_text(build_report(bundle, frame), encoding="utf-8")
    artifact_paths = sorted(
        path for path in destination.rglob("*") if path.is_file() and path.name != "manifest.json"
    )
    artifacts = {
        path.relative_to(destination).as_posix(): {
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in artifact_paths
    }
    manifest = {
        "schema_version": 1,
        "study_id": "star50-single-asset-shadow-operations",
        "archived_at": "2026-09-02",
        "run_id": "tencent-yahoo-2020-2026-v1",
        "symbol": engine.SYMBOL,
        "evidence_class": "post-selection engineering validation; no new alpha evidence",
        "data": {
            "input_file": "raw/input-sh588000.csv",
            "input_sha256": _sha256(raw / "input-sh588000.csv"),
            "start": frame.index.min().strftime("%Y-%m-%d"),
            "end": frame.index.max().strftime("%Y-%m-%d"),
            "sessions": len(frame),
        },
        "protocol": {
            "operations_generations": ["O0", "O1", "O2", "O3", "O4"],
            "scenario_count": len(bundle["scenario_metrics"]),
            "capital_grid": list(CAPITAL_GRID),
            "volume_ratios": list(VOLUME_RATIOS),
            "slippages": list(SLIPPAGES),
            "oos_start": OOS_START.strftime("%Y-%m-%d"),
            "signal_rules_frozen": True,
        },
        "results": {
            "causality_checks": len(bundle["causality_audit"]),
            "causality_failures": int((~bundle["causality_audit"]["matched"]).sum()),
            "fault_cases": len(bundle["fault_injection"]["cases"]),
            "fault_failures": int(
                sum(not case["passed"] for case in bundle["fault_injection"]["cases"])
            ),
            "capacity_summary": bundle["capacity_summary"].to_dict(orient="records"),
            "live_check_status": bundle["live_check"].get("status"),
        },
        "source_file": "source.py",
        "source_sha256": _sha256(destination / "source.py"),
        "operations_file": "operations.py",
        "operations_sha256": _sha256(destination / "operations.py"),
        "artifacts": artifacts,
    }
    _write_json(manifest, destination / "manifest.json")
    return destination


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--live-end-date", default="2026-09-02")
    parser.add_argument("--no-live-check", action="store_true")
    parser.add_argument("--no-archive", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    frame = engine.load_input_csv(args.input_csv)
    bundle = run_operational_readiness(
        frame,
        live_end_date=None if args.no_live_check else args.live_end_date,
    )
    print(build_report(bundle, frame))
    if not args.no_archive:
        destination = archive_result(bundle, frame, args.input_csv)
        print(f"归档完成：{destination.relative_to(STUDY_DIR).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
