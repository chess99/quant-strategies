from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_shadow_operations.py"


def load_module():
    spec = importlib.util.spec_from_file_location("star50_shadow_operations_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def model(target=0.50):
    return {
        "config": "risk-friction__threshold-0p05",
        "objective": "risk",
        "target_weight": target,
    }


def quote(**overrides):
    value = {
        "symbol": "SH588000",
        "trade_date": "2026-09-02",
        "price": 1.0,
        "volume": 1_000_000,
        "paused": False,
        "buy_blocked": False,
        "sell_blocked": False,
    }
    value.update(overrides)
    return value


def test_buy_plan_is_deterministic_lot_rounded_and_capacity_limited():
    module = load_module()
    account = module.initial_account(model()["config"], 100_000.0)

    first = module.plan_order(model(), account, quote(), "2026-09-01")
    second = module.plan_order(model(), account, quote(), "2026-09-01")

    assert first == second
    assert first["status"] == "planned"
    assert first["side"] == "buy"
    assert first["planned_shares"] == 10_000
    assert first["planned_shares"] % 100 == 0
    assert first["volume_participation"] == pytest.approx(0.01)


def test_market_block_is_distinct_from_system_halt():
    module = load_module()
    account = module.initial_account(model()["config"], 0.0, shares=10_000)

    result = module.plan_order(
        model(0.0),
        account,
        quote(sell_blocked=True),
        "2026-09-01",
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "sell_blocked"
    assert result["planned_shares"] == 0


def test_snapshot_quality_and_staleness_fail_closed():
    module = load_module()
    snapshot = {
        "schema_version": 1,
        "symbol": "SH588000",
        "status": "shadow_only",
        "observation_date": "2026-09-01",
        "data": {"maximum_ohlc_relative_error": 0.02},
        "models": [model()],
    }

    with pytest.raises(module.OperationHalt, match="OHLC"):
        module.validate_snapshot(snapshot, as_of_date="2026-09-02")

    snapshot["data"]["maximum_ohlc_relative_error"] = 0.001
    with pytest.raises(module.OperationHalt, match="过期"):
        module.validate_snapshot(snapshot, as_of_date="2026-09-08")

    snapshot["data"]["latest_session_cross_checked"] = False
    with pytest.raises(module.OperationHalt, match="最新交易日"):
        module.validate_snapshot(
            snapshot,
            as_of_date="2026-09-02",
            require_cross_check=True,
        )


def test_fill_updates_cash_and_shares_once_and_builds_hash_chain():
    module = load_module()
    account = module.initial_account(model()["config"], 100_000.0)
    order = module.plan_order(model(), account, quote(), "2026-09-01")
    fill = {
        "fill_id": "fill-1",
        "order_id": order["order_id"],
        "trade_date": "2026-09-02",
        "side": "buy",
        "shares": 10_000,
        "price": 1.0002,
        "fee": 5.0,
    }

    updated, event = module.apply_fill(account, order, fill)

    assert updated["shares"] == 10_000
    assert updated["cash"] == pytest.approx(89_993.0)
    assert updated["last_event_hash"] == event["event_hash"]
    assert module.verify_event_chain([event])
    with pytest.raises(module.OperationHalt, match="重复成交"):
        module.apply_fill(updated, order, fill)


def test_completed_target_does_not_rebalance_daily_price_drift():
    module = load_module()
    account = module.initial_account(model()["config"], 100_000.0)
    order = module.plan_order(model(), account, quote(volume=10_000_000), "2026-09-01")
    updated, _ = module.apply_fill(
        account,
        order,
        {
            "fill_id": "fill-drift",
            "order_id": order["order_id"],
            "trade_date": "2026-09-02",
            "side": "buy",
            "shares": order["planned_shares"],
            "price": 1.0002,
            "fee": 15.0,
        },
    )

    next_day = module.plan_order(
        model(),
        updated,
        quote(trade_date="2026-09-03", price=1.05, volume=10_000_000),
        "2026-09-02",
    )

    assert next_day["status"] == "no_order"
    assert next_day["reason"] == "target_unchanged"


def test_partial_fill_must_be_closed_before_replanning_and_keeps_chain():
    module = load_module()
    account = module.initial_account(model()["config"], 100_000.0)
    order = module.plan_order(model(), account, quote(), "2026-09-01")
    partially_filled, fill_event = module.apply_fill(
        account,
        order,
        {
            "fill_id": "partial-fill",
            "order_id": order["order_id"],
            "trade_date": "2026-09-02",
            "side": "buy",
            "shares": 5_000,
            "price": 1.0002,
            "fee": 5.0,
        },
    )

    with pytest.raises(module.OperationHalt, match="未决订单"):
        module.plan_order(
            model(),
            partially_filled,
            quote(trade_date="2026-09-03"),
            "2026-09-02",
        )

    released, release_event = module.release_pending_order(
        partially_filled,
        order["order_id"],
        "cancelled",
    )
    assert released["pending_order_id"] is None
    assert released["rebalance_incomplete"]
    assert module.verify_event_chain([fill_event, release_event])


def test_reconciliation_and_tamper_detection_fail_closed():
    module = load_module()
    account = module.initial_account(model()["config"], 100_000.0)

    with pytest.raises(module.OperationHalt, match="对账失败"):
        module.reconcile_account(account, {"cash": 99_000.0, "shares": 0})

    order = module.plan_order(model(), account, quote(), "2026-09-01")
    updated, event = module.apply_fill(
        account,
        order,
        {
            "fill_id": "fill-2",
            "order_id": order["order_id"],
            "trade_date": "2026-09-02",
            "side": "buy",
            "shares": 10_000,
            "price": 1.0002,
            "fee": 5.0,
        },
    )
    assert updated["shares"] == 10_000
    event["cash_after"] += 1.0
    assert not module.verify_event_chain([event])


def test_unknown_tradability_and_pending_order_fail_closed():
    module = load_module()
    account = module.initial_account(model()["config"], 100_000.0)

    with pytest.raises(module.OperationHalt, match="交易状态未知"):
        module.plan_order(model(), account, quote(paused=None), "2026-09-01")

    account["pending_order_id"] = "old-order"
    with pytest.raises(module.OperationHalt, match="未决订单"):
        module.plan_order(model(), account, quote(), "2026-09-01")


def test_protocol_freezes_signal_and_operations_search_space():
    text = (STUDY_DIR / "OPERATIONS_PROTOCOL.md").read_text(encoding="utf-8")

    assert "不新增指标" in text
    assert "1万、5万、10万" in text
    assert "O0-O4 全部完成后" in text
