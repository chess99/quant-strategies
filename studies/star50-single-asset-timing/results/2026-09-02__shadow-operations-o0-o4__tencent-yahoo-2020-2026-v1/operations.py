"""为科创 50 ETF 冻结影子模型生成可审计订单并维护模拟账本。"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path


SYMBOL = "SH588000"
FROZEN_CONFIG_NAMES = (
    "risk-friction__threshold-0p05",
    "production-ensemble__threshold-0p1",
)
LOT_SIZE = 100
MAX_TARGET_WEIGHT = 0.99
DEFAULT_CASH_BUFFER = 0.005
DEFAULT_VOLUME_RATIO = 0.01
COMMISSION_RATE = 0.0003
MINIMUM_COMMISSION = 5.0
SLIPPAGE_GUARD = 0.002
MAX_STALENESS_DAYS = 4
ZERO_HASH = "0" * 64


class OperationHalt(RuntimeError):
    """表示数据、账户或审计状态不安全，必须停止产生新订单。"""


def _finite_number(value, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise OperationHalt(f"{field} 不是有效数值") from exc
    if not math.isfinite(result):
        raise OperationHalt(f"{field} 不是有限值")
    return result


def _date(value, field: str):
    try:
        from datetime import date

        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise OperationHalt(f"{field} 不是有效日期") from exc


def _canonical_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(value: dict) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _commission(gross_value: float) -> float:
    if gross_value <= 0.0:
        return 0.0
    return max(MINIMUM_COMMISSION, gross_value * COMMISSION_RATE)


def initial_account(model_name: str, cash: float, shares: int = 0) -> dict:
    if model_name not in FROZEN_CONFIG_NAMES:
        raise OperationHalt("账户模型不在冻结名单")
    cash_value = _finite_number(cash, "cash")
    shares_value = int(shares)
    if cash_value < 0.0 or shares_value < 0 or shares_value % LOT_SIZE:
        raise OperationHalt("初始账户现金或份额不合法")
    return {
        "schema_version": 1,
        "symbol": SYMBOL,
        "model": model_name,
        "cash": cash_value,
        "shares": shares_value,
        "pending_order_id": None,
        "pending_shares": 0,
        "active_target_weight": 0.0 if shares_value == 0 else None,
        "rebalance_incomplete": False,
        "applied_fill_ids": [],
        "last_event_hash": ZERO_HASH,
    }


def _validate_account(account: dict, expected_model: str | None = None) -> None:
    if account.get("symbol") != SYMBOL:
        raise OperationHalt("账户标的不是 SH588000")
    if account.get("model") not in FROZEN_CONFIG_NAMES:
        raise OperationHalt("账户模型不在冻结名单")
    if expected_model is not None and account.get("model") != expected_model:
        raise OperationHalt("信号与账户模型不一致")
    cash = _finite_number(account.get("cash"), "cash")
    try:
        shares = int(account.get("shares"))
    except (TypeError, ValueError) as exc:
        raise OperationHalt("账户份额不合法") from exc
    if cash < -0.01 or shares < 0 or shares % LOT_SIZE:
        raise OperationHalt("账户出现负现金、负持仓或非整手持仓")
    fill_ids = account.get("applied_fill_ids")
    if not isinstance(fill_ids, list) or len(fill_ids) != len(set(fill_ids)):
        raise OperationHalt("账户成交标识异常")
    event_hash = account.get("last_event_hash")
    if not isinstance(event_hash, str) or len(event_hash) != 64:
        raise OperationHalt("账户事件哈希异常")
    active_target = account.get("active_target_weight")
    if active_target is not None:
        active_target = _finite_number(active_target, "active_target_weight")
        if not 0.0 <= active_target <= MAX_TARGET_WEIGHT:
            raise OperationHalt("账户活动目标仓位异常")
    if not isinstance(account.get("rebalance_incomplete"), bool):
        raise OperationHalt("账户调仓完成状态异常")


def validate_snapshot(
    snapshot: dict,
    as_of_date=None,
    require_cross_check: bool = False,
) -> None:
    if snapshot.get("schema_version") != 1 or snapshot.get("status") != "shadow_only":
        raise OperationHalt("影子信号版本或状态异常")
    if snapshot.get("symbol") != SYMBOL:
        raise OperationHalt("影子信号标的不是 SH588000")
    observation = _date(snapshot.get("observation_date"), "observation_date")
    if as_of_date is not None:
        current = _date(as_of_date, "as_of_date")
        age = (current - observation).days
        if age < 0:
            raise OperationHalt("影子信号日期晚于运行日期")
        if age > MAX_STALENESS_DAYS:
            raise OperationHalt(f"影子信号已过期：{age} 天")
    data = snapshot.get("data")
    if not isinstance(data, dict):
        raise OperationHalt("影子信号缺少数据质量信息")
    ohlc_error = data.get("maximum_ohlc_relative_error")
    if ohlc_error is None:
        if require_cross_check:
            raise OperationHalt("实时影子信号缺少双源 OHLC 核验")
    elif _finite_number(ohlc_error, "OHLC 差异") > 0.01:
        raise OperationHalt("双源 OHLC 差异超过 1%")
    models = snapshot.get("models")
    if not isinstance(models, list) or not models:
        raise OperationHalt("影子信号缺少模型")
    names = []
    for model in models:
        name = model.get("config")
        target = _finite_number(model.get("target_weight"), "target_weight")
        if name not in FROZEN_CONFIG_NAMES:
            raise OperationHalt("影子信号包含未冻结模型")
        if not 0.0 <= target <= MAX_TARGET_WEIGHT:
            raise OperationHalt("目标仓位超出 0%-99%")
        names.append(name)
    if len(names) != len(set(names)):
        raise OperationHalt("影子信号模型重复")


def _validate_quote(quote: dict, observation_date) -> tuple[float, float]:
    if quote.get("symbol") != SYMBOL:
        raise OperationHalt("行情标的不是 SH588000")
    trade_date = _date(quote.get("trade_date"), "trade_date")
    observation = _date(observation_date, "observation_date")
    if trade_date <= observation:
        raise OperationHalt("交易行情必须晚于信号观察日")
    price = _finite_number(quote.get("price"), "price")
    volume = _finite_number(quote.get("volume"), "volume")
    if price <= 0.0 or volume <= 0.0:
        raise OperationHalt("价格或成交量必须为正")
    for field in ("paused", "buy_blocked", "sell_blocked"):
        if not isinstance(quote.get(field), bool):
            raise OperationHalt("交易状态未知，停止生成订单")
    return price, volume


def _base_order_result(model: dict, quote: dict, target_weight: float) -> dict:
    return {
        "schema_version": 1,
        "symbol": SYMBOL,
        "model": model["config"],
        "objective": model.get("objective"),
        "observation_date": None,
        "trade_date": quote.get("trade_date"),
        "target_weight": target_weight,
        "status": None,
        "reason": None,
        "side": None,
        "planned_shares": 0,
        "unplanned_shares": 0,
        "volume_participation": 0.0,
        "estimated_price": None,
        "estimated_fee": 0.0,
        "order_id": None,
    }


def plan_order(
    model: dict,
    account: dict,
    quote: dict,
    observation_date,
    cash_buffer: float = DEFAULT_CASH_BUFFER,
    maximum_volume_ratio: float = DEFAULT_VOLUME_RATIO,
) -> dict:
    name = model.get("config")
    if name not in FROZEN_CONFIG_NAMES:
        raise OperationHalt("订单模型不在冻结名单")
    _validate_account(account, expected_model=name)
    if account.get("pending_order_id"):
        raise OperationHalt("账户存在未决订单，禁止重复规划")
    target_weight = _finite_number(model.get("target_weight"), "target_weight")
    if not 0.0 <= target_weight <= MAX_TARGET_WEIGHT:
        raise OperationHalt("目标仓位超出 0%-99%")
    cash_buffer_value = _finite_number(cash_buffer, "cash_buffer")
    volume_ratio = _finite_number(maximum_volume_ratio, "maximum_volume_ratio")
    if not 0.0 <= cash_buffer_value < 1.0:
        raise OperationHalt("现金缓冲比例不合法")
    if not 0.0 < volume_ratio <= 1.0:
        raise OperationHalt("成交量上限比例不合法")
    price, volume = _validate_quote(quote, observation_date)
    result = _base_order_result(model, quote, target_weight)
    result["observation_date"] = str(observation_date)
    total_value = float(account["cash"]) + int(account["shares"]) * price
    active_target = account.get("active_target_weight")
    if (
        active_target is not None
        and math.isclose(target_weight, float(active_target), abs_tol=1e-12)
        and not account["rebalance_incomplete"]
    ):
        result.update(
            status="no_order",
            reason="target_unchanged",
            account_value=total_value,
            current_shares=int(account["shares"]),
            target_shares=int(account["shares"]),
        )
        return result
    target_shares = int(total_value * target_weight / price) // LOT_SIZE * LOT_SIZE
    desired_delta = target_shares - int(account["shares"])
    result["account_value"] = total_value
    result["current_shares"] = int(account["shares"])
    result["target_shares"] = target_shares
    if desired_delta == 0:
        result.update(status="no_order", reason="already_at_target")
        return result
    side = "buy" if desired_delta > 0 else "sell"
    blocked_field = "buy_blocked" if side == "buy" else "sell_blocked"
    if quote["paused"] or quote[blocked_field]:
        reason = "paused" if quote["paused"] else blocked_field
        result.update(status="blocked", reason=reason, side=side)
        return result
    capacity = int(volume * volume_ratio) // LOT_SIZE * LOT_SIZE
    requested = abs(desired_delta)
    planned = min(requested, capacity)
    planned = planned // LOT_SIZE * LOT_SIZE
    if side == "sell":
        planned = min(planned, int(account["shares"]))
    estimated_price = price * (1.0 + SLIPPAGE_GUARD if side == "buy" else 1.0 - SLIPPAGE_GUARD)
    if side == "buy":
        cash_floor = total_value * cash_buffer_value
        while planned > 0:
            gross = planned * estimated_price
            if gross + _commission(gross) <= float(account["cash"]) - cash_floor + 1e-8:
                break
            planned -= LOT_SIZE
    if planned <= 0:
        reason = "volume_limit" if capacity <= 0 else "insufficient_cash_or_buffer"
        result.update(status="blocked", reason=reason, side=side)
        return result
    gross = planned * estimated_price
    fee = _commission(gross)
    order_seed = {
        "account_cash": round(float(account["cash"]), 8),
        "account_shares": int(account["shares"]),
        "model": name,
        "observation_date": str(observation_date),
        "planned_shares": planned,
        "side": side,
        "target_weight": round(target_weight, 12),
        "trade_date": str(quote["trade_date"]),
    }
    result.update(
        status="planned",
        reason="capacity_limited" if planned < requested else "target_rebalance",
        side=side,
        planned_shares=planned,
        unplanned_shares=requested - planned,
        volume_participation=planned / volume,
        estimated_price=estimated_price,
        estimated_fee=fee,
        order_id=f"shadow-{_payload_hash(order_seed)[:24]}",
    )
    return result


def apply_fill(account: dict, order: dict, fill: dict) -> tuple[dict, dict]:
    _validate_account(account, expected_model=order.get("model"))
    if order.get("status") != "planned" or not order.get("order_id"):
        raise OperationHalt("只能对已规划订单登记成交")
    fill_id = str(fill.get("fill_id") or "")
    if not fill_id:
        raise OperationHalt("成交缺少 fill_id")
    if fill_id in account["applied_fill_ids"]:
        raise OperationHalt("重复成交被拒绝")
    if fill.get("order_id") != order["order_id"]:
        raise OperationHalt("成交与订单标识不一致")
    side = fill.get("side")
    if side != order.get("side") or side not in {"buy", "sell"}:
        raise OperationHalt("成交方向与订单不一致")
    try:
        shares = int(fill.get("shares"))
    except (TypeError, ValueError) as exc:
        raise OperationHalt("成交份额不合法") from exc
    if shares <= 0 or shares % LOT_SIZE or shares > int(order["planned_shares"]):
        raise OperationHalt("成交份额超出订单或不是整数手")
    price = _finite_number(fill.get("price"), "fill price")
    fee = _finite_number(fill.get("fee"), "fill fee")
    if price <= 0.0 or fee < 0.0:
        raise OperationHalt("成交价格或费用不合法")
    updated = copy.deepcopy(account)
    cash_before = float(updated["cash"])
    shares_before = int(updated["shares"])
    gross = price * shares
    if side == "buy":
        cash_after = cash_before - gross - fee
        shares_after = shares_before + shares
        if cash_after < -0.01:
            raise OperationHalt("成交导致现金不足")
    else:
        if shares > shares_before:
            raise OperationHalt("成交导致超额卖出")
        cash_after = cash_before + gross - fee
        shares_after = shares_before - shares
    remaining = int(order["planned_shares"]) - shares
    event = {
        "schema_version": 1,
        "previous_hash": updated["last_event_hash"],
        "event_type": "fill",
        "fill_id": fill_id,
        "order_id": order["order_id"],
        "trade_date": str(fill.get("trade_date")),
        "side": side,
        "shares": shares,
        "price": price,
        "fee": fee,
        "cash_before": cash_before,
        "cash_after": cash_after,
        "shares_before": shares_before,
        "shares_after": shares_after,
    }
    event["event_hash"] = _payload_hash(event)
    updated["cash"] = cash_after
    updated["shares"] = shares_after
    updated["applied_fill_ids"].append(fill_id)
    updated["last_event_hash"] = event["event_hash"]
    updated["pending_order_id"] = order["order_id"] if remaining else None
    updated["pending_shares"] = remaining
    updated["active_target_weight"] = float(order["target_weight"])
    updated["rebalance_incomplete"] = bool(remaining or int(order["unplanned_shares"]) > 0)
    _validate_account(updated)
    return updated, event


def verify_event_chain(events: list[dict], initial_hash: str = ZERO_HASH) -> bool:
    previous = initial_hash
    for event in events:
        if event.get("previous_hash") != previous:
            return False
        expected = _payload_hash({key: value for key, value in event.items() if key != "event_hash"})
        if event.get("event_hash") != expected:
            return False
        previous = expected
    return True


def reconcile_account(
    account: dict,
    actual: dict,
    cash_tolerance: float = 0.01,
) -> dict:
    _validate_account(account)
    actual_cash = _finite_number(actual.get("cash"), "actual cash")
    try:
        actual_shares = int(actual.get("shares"))
    except (TypeError, ValueError) as exc:
        raise OperationHalt("实际账户份额不合法") from exc
    cash_difference = actual_cash - float(account["cash"])
    shares_difference = actual_shares - int(account["shares"])
    if abs(cash_difference) > cash_tolerance or shares_difference != 0:
        raise OperationHalt(
            f"账户对账失败：现金差 {cash_difference:.2f}，份额差 {shares_difference}"
        )
    return {
        "status": "reconciled",
        "cash_difference": cash_difference,
        "shares_difference": shares_difference,
    }


def halted_result(stage: str, error: Exception) -> dict:
    return {
        "schema_version": 1,
        "status": "halted",
        "stage": stage,
        "error_type": type(error).__name__,
        "reason": str(error),
        "orders": [],
    }


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_result(value: dict, output: Path | None) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if output is not None:
        output.write_text(text, encoding="utf-8")
    print(text, end="")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    initial = subparsers.add_parser("initial", help="创建两个冻结模型的空白影子账户")
    initial.add_argument("--cash", type=float, required=True)
    initial.add_argument("--output", type=Path)
    plan = subparsers.add_parser("plan", help="根据冻结信号、账户和次日行情规划订单")
    plan.add_argument("--snapshot", type=Path, required=True)
    plan.add_argument("--accounts", type=Path, required=True)
    plan.add_argument("--quote", type=Path, required=True)
    plan.add_argument("--as-of-date", required=True)
    plan.add_argument("--allow-archived-input", action="store_true")
    plan.add_argument("--output", type=Path)
    verify = subparsers.add_parser("verify-ledger", help="验证追加式成交事件哈希链")
    verify.add_argument("--events", type=Path, required=True)
    verify.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "initial":
            result = {
                "schema_version": 1,
                "status": "initialized",
                "accounts": {
                    name: initial_account(name, args.cash) for name in FROZEN_CONFIG_NAMES
                },
            }
        elif args.command == "plan":
            snapshot = _read_json(args.snapshot)
            accounts = _read_json(args.accounts)
            quote = _read_json(args.quote)
            validate_snapshot(
                snapshot,
                as_of_date=args.as_of_date,
                require_cross_check=not args.allow_archived_input,
            )
            account_map = accounts.get("accounts", accounts)
            orders = [
                plan_order(
                    model,
                    account_map[model["config"]],
                    quote,
                    snapshot["observation_date"],
                )
                for model in snapshot["models"]
            ]
            result = {"schema_version": 1, "status": "planned", "orders": orders}
        else:
            events = _read_json(args.events)
            if not verify_event_chain(events):
                raise OperationHalt("事件哈希链校验失败")
            result = {"schema_version": 1, "status": "verified", "events": len(events)}
    except (KeyError, OSError, ValueError, json.JSONDecodeError, OperationHalt) as exc:
        result = halted_result(args.command, exc)
        _write_result(result, getattr(args, "output", None))
        return 2
    _write_result(result, getattr(args, "output", None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
