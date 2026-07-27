"""迭代 5 本地撮合器与预检归档的机器验收。"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pandas as pd

from .backtest import DailyBacktester, performance_metrics, scheduled_dates
from .data.store import sha256_file


REQUIRED_ORDER_APIS = (
    "order_value",
    "order_target",
    "order_target_value",
    "order_target_percent",
    "order_target_weight",
    "rebalance_to_weights",
)
REQUIRED_LEDGERS = (
    "equity.csv",
    "orders.csv",
    "trades.csv",
    "holdings-daily.csv",
    "holdings-monthly.csv",
    "cash-ledger.csv",
    "fees-ledger.csv",
    "rejections.csv",
    "corporate-actions.csv",
)
REQUIRED_METRICS = (
    "annualized_return",
    "maximum_drawdown",
    "sharpe",
    "turnover",
    "longest_underwater_trading_days",
    "yearly_returns",
    "average_cash_ratio",
)


def verify_daily_backtester(root: Path, result_dir: Path) -> dict:
    manifest_path = result_dir / "manifest.json"
    coverage_path = result_dir / "coverage.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    raw_dir = result_dir / "raw"
    raw_hash_checks = {
        filename: (raw_dir / filename).is_file()
        and sha256_file(raw_dir / filename) == expected
        for filename, expected in manifest.get("raw_sha256", {}).items()
    }
    order_api_checks = {
        name: callable(getattr(DailyBacktester, name, None)) for name in REQUIRED_ORDER_APIS
    }
    ledger_checks = {filename: (raw_dir / filename).is_file() for filename in REQUIRED_LEDGERS}
    metric_checks = {name: name in manifest.get("metrics", {}) for name in REQUIRED_METRICS}
    candidates = pd.read_csv(raw_dir / "candidates-top50.csv")
    coverage_table = pd.read_csv(raw_dir / "rebalance-coverage.csv")
    trades = pd.read_csv(raw_dir / "trades.csv")
    checks = {
        "local_preflight_status_passed": manifest.get("status") == "local_preflight_passed",
        "full_history_master_used": coverage.get("checks", {}).get("full_master_is_6115") is True,
        "all_rebalances_have_ten_targets": coverage_table["selected_count"].eq(10).all(),
        "all_future_data_checks_passed": coverage.get("pit_violations") == 0,
        "all_filled_orders_use_a_or_b_state": manifest.get("checks", {}).get(
            "all_filled_orders_use_a_or_b_state"
        )
        is True,
        "source_sha256_valid": sha256_file(result_dir / "source.py")
        == manifest.get("source_sha256"),
        "engine_sha256_valid": sha256_file(result_dir / "engine.py")
        == manifest.get("engine_sha256"),
        "joinquant_source_sha256_valid": sha256_file(result_dir / "joinquant_strategy.py")
        == manifest.get("joinquant_strategy_sha256"),
        "coverage_sha256_valid": sha256_file(coverage_path)
        == manifest.get("coverage_sha256"),
        "all_raw_sha256_valid": bool(raw_hash_checks) and all(raw_hash_checks.values()),
        "all_order_apis_present": all(order_api_checks.values()),
        "all_ledgers_present": all(ledger_checks.values()),
        "all_required_metrics_present": all(metric_checks.values()),
        "open_and_close_execution_supported": 'execution not in {"open", "close"}'
        in inspect.getsource(DailyBacktester),
        "daily_weekly_monthly_scheduler_present": callable(scheduled_dates),
        "performance_metrics_callable": callable(performance_metrics),
        "candidate_archive_has_54_dates": candidates["execution_date"].nunique() == 54,
        "real_trades_present": not trades.empty,
    }
    checks = {key: bool(value) for key, value in checks.items()}
    return {
        "schema_version": 1,
        "iteration": 5,
        "iteration_status": "in_progress",
        "local_preflight_status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "details": {
            "order_apis": order_api_checks,
            "ledgers": ledger_checks,
            "metrics": metric_checks,
            "raw_hashes": raw_hash_checks,
            "period": manifest["period"],
            "rebalance_dates": int(coverage_table.shape[0]),
            "selected_unique_symbols": coverage.get("selected_unique_symbols"),
            "local_metrics": manifest["metrics"],
            "data_quality": manifest["quality"],
            "result_manifest_sha256": sha256_file(manifest_path),
        },
        "remaining": [
            "run the prepared JoinQuant strategy exactly once",
            "import all 54 candidate/holding logs and aggregate stats",
            "pass >=80% candidate and holding overlap",
            "pass <=3 percentage-point annualized and drawdown differences",
        ],
        "root": str(root),
    }
