"""可审计的 A 股与 ETF 日线撮合器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Literal

import numpy as np
import pandas as pd


ExecutionField = Literal["open", "close"]


@dataclass(frozen=True)
class CostModel:
    """股票与 ETF 的交易成本以及 A 股印花税历史。"""

    # 股票默认费率；保留原字段名以兼容已有研究脚本。
    buy_commission: float = 0.0003
    sell_commission: float = 0.0003
    minimum_commission: float = 5.0
    # ETF 可使用独立费率；None 表示沿用对应股票参数。
    etf_buy_commission: float | None = None
    etf_sell_commission: float | None = None
    etf_minimum_commission: float | None = None
    # 2000 年以后 A 股印花税的生效日与税率。2008-09-19 起改单边征收。
    stock_stamp_tax_schedule: tuple[tuple[str, float], ...] = (
        ("2000-01-01", 0.004),
        ("2001-11-16", 0.002),
        ("2005-01-24", 0.001),
        ("2007-05-30", 0.003),
        ("2008-04-24", 0.001),
        ("2023-08-28", 0.0005),
    )
    stock_stamp_tax_single_side_from: str = "2008-09-19"

    def stamp_tax_rate(self, asset_type: str, side: str, trade_date) -> float:
        if asset_type != "stock":
            return 0.0
        date = pd.Timestamp(trade_date).normalize()
        if side == "buy" and date >= pd.Timestamp(self.stock_stamp_tax_single_side_from):
            return 0.0
        rate = 0.0
        for effective_from, candidate in self.stock_stamp_tax_schedule:
            if date >= pd.Timestamp(effective_from):
                rate = candidate
            else:
                break
        return rate

    def fees(self, asset_type: str, side: str, gross: float, trade_date) -> tuple[float, float]:
        if asset_type == "etf":
            configured_rate = self.etf_buy_commission if side == "buy" else self.etf_sell_commission
            commission_rate = (
                configured_rate
                if configured_rate is not None
                else (self.buy_commission if side == "buy" else self.sell_commission)
            )
            minimum_commission = (
                self.etf_minimum_commission
                if self.etf_minimum_commission is not None
                else self.minimum_commission
            )
        else:
            commission_rate = self.buy_commission if side == "buy" else self.sell_commission
            minimum_commission = self.minimum_commission
        commission = max(minimum_commission, gross * commission_rate) if gross > 0 else 0.0
        tax = gross * self.stamp_tax_rate(asset_type, side, trade_date)
        return commission, tax


@dataclass
class Position:
    symbol: str
    shares: int
    average_cost: float
    last_price: float
    available_shares: int | None = None

    def __post_init__(self) -> None:
        if self.available_shares is None:
            self.available_shares = self.shares

    @property
    def market_value(self) -> float:
        return self.shares * self.last_price


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 1_000_000.0
    lot_size: int = 100
    maximum_volume_ratio: float = 0.10
    slippage_rate: float = 0.0
    allow_unknown_st: bool = False
    block_st_buys: bool = True
    t_plus_one_asset_types: tuple[str, ...] = ("stock",)
    participate_rights_issues: bool = False
    minimum_state_quality: Literal["A", "B", "C"] = "C"


def scheduled_dates(
    calendar: Iterable,
    frequency: Literal["daily", "weekly", "monthly"] = "daily",
    when: Literal["first", "last"] = "first",
) -> set[pd.Timestamp]:
    """返回日、周、月调度日期；周与月按实际交易日分组。"""

    dates = pd.DatetimeIndex(pd.to_datetime(list(calendar))).normalize().sort_values().unique()
    if frequency == "daily":
        return set(dates)
    if frequency not in {"weekly", "monthly"}:
        raise ValueError("frequency must be daily, weekly or monthly")
    if when not in {"first", "last"}:
        raise ValueError("when must be first or last")
    periods = dates.to_period("W-FRI" if frequency == "weekly" else "M")
    grouped = pd.Series(dates, index=periods).groupby(level=0)
    selected = grouped.first() if when == "first" else grouped.last()
    return set(pd.DatetimeIndex(selected.to_numpy()).normalize())


def build_delisting_actions(
    delisting_events: pd.DataFrame,
    security_master: pd.DataFrame,
    bars: pd.DataFrame,
) -> pd.DataFrame:
    """按证券最后交易日和一致口径收盘价生成强制结算公司行动。"""

    required_events = {"symbol", "effective_from"}
    required_master = {"symbol", "end_date"}
    required_bars = {"symbol", "trade_date", "close"}
    for name, frame, required in (
        ("delisting_events", delisting_events, required_events),
        ("security_master", security_master, required_master),
        ("bars", bars, required_bars),
    ):
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"{name} is missing columns: {sorted(missing)}")
    events = delisting_events[["symbol", "effective_from"]].copy()
    events["symbol"] = events["symbol"].str.upper()
    events["effective_from"] = pd.to_datetime(events["effective_from"]).dt.normalize()
    master = security_master[["symbol", "end_date"]].copy()
    master["symbol"] = master["symbol"].str.upper()
    master["end_date"] = pd.to_datetime(master["end_date"]).dt.normalize()
    terminal = events.merge(master, on="symbol", how="inner", validate="one_to_one")
    terminal = terminal[terminal["effective_from"].le(terminal["end_date"])]
    prices = bars[["symbol", "trade_date", "close"]].copy()
    prices["symbol"] = prices["symbol"].str.upper()
    prices["trade_date"] = pd.to_datetime(prices["trade_date"]).dt.normalize()
    actions = terminal.merge(
        prices,
        left_on=["symbol", "end_date"],
        right_on=["symbol", "trade_date"],
        how="inner",
        validate="one_to_one",
    )
    actions = actions[pd.to_numeric(actions["close"], errors="coerce").gt(0)]
    result = pd.DataFrame(
        {
            "action_date": actions["end_date"],
            "symbol": actions["symbol"],
            "action_type": "delisting",
            "cash_per_share": actions["close"].astype(float),
        }
    )
    return result.sort_values(["action_date", "symbol"]).reset_index(drop=True)


class DailyBacktester:
    """在开盘或收盘撮合日线订单，并导出完整审计账本。"""

    def __init__(
        self,
        bars: pd.DataFrame,
        market_state: pd.DataFrame,
        asset_types: dict[str, str] | None = None,
        config: BacktestConfig | None = None,
        costs: CostModel | None = None,
        corporate_actions: pd.DataFrame | None = None,
    ):
        self.config = config or BacktestConfig()
        if self.config.initial_cash < 0:
            raise ValueError("initial_cash must not be negative")
        if not 0 < self.config.maximum_volume_ratio <= 1:
            raise ValueError("maximum_volume_ratio must be in (0, 1]")
        self.costs = costs or CostModel()
        self.cash = float(self.config.initial_cash)
        self.positions: dict[str, Position] = {}
        self.asset_types = {key.upper(): value for key, value in (asset_types or {}).items()}
        self.bars = self._prepare_frame(bars, "bars")
        self.market_state = self._prepare_frame(market_state, "market_state")
        self.corporate_actions_frame = self._prepare_corporate_actions(corporate_actions)
        self.order_records: list[dict] = []
        self.trade_records: list[dict] = []
        self.equity_records: list[dict] = []
        self.position_records: list[dict] = []
        self.cash_records: list[dict] = [
            {
                "trade_date": pd.NaT,
                "event": "initial_cash",
                "symbol": None,
                "amount": self.cash,
                "cash_after": self.cash,
            }
        ]
        self.fee_records: list[dict] = []
        self.corporate_action_records: list[dict] = []
        self._current_session: pd.Timestamp | None = None
        self._session_volume_used: dict[str, int] = {}
        self._applied_action_rows: set[int] = set()
        self._next_order_id = 1

    @staticmethod
    def _prepare_frame(frame: pd.DataFrame, name: str) -> pd.DataFrame:
        required = {"symbol", "trade_date"}
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"{name} is missing columns: {sorted(missing)}")
        result = frame.copy()
        result["symbol"] = result["symbol"].str.upper()
        result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.normalize()
        if result.duplicated(["symbol", "trade_date"]).any():
            raise ValueError(f"{name} contains duplicate symbol/date rows")
        return result.set_index(["trade_date", "symbol"]).sort_index()

    @staticmethod
    def _prepare_corporate_actions(frame: pd.DataFrame | None) -> pd.DataFrame:
        columns = [
            "action_date",
            "symbol",
            "action_type",
            "cash_per_share",
            "share_multiplier",
            "rights_ratio",
            "subscription_price",
        ]
        if frame is None or frame.empty:
            return pd.DataFrame(columns=columns)
        required = {"action_date", "symbol", "action_type"}
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"corporate_actions is missing columns: {sorted(missing)}")
        result = frame.copy().reset_index(drop=True)
        result["action_date"] = pd.to_datetime(result["action_date"]).dt.normalize()
        result["symbol"] = result["symbol"].str.upper()
        allowed = {
            "cash_dividend",
            "bonus",
            "split",
            "consolidation",
            "rights_issue",
            "delisting",
        }
        unknown = sorted(set(result["action_type"]) - allowed)
        if unknown:
            raise ValueError(f"unsupported corporate action types: {unknown}")
        requirements = {
            "cash_dividend": (("cash_per_share", lambda value: value >= 0),),
            "delisting": (("cash_per_share", lambda value: value >= 0),),
            "bonus": (("share_multiplier", lambda value: value > 0),),
            "split": (("share_multiplier", lambda value: value > 0),),
            "consolidation": (("share_multiplier", lambda value: value > 0),),
            "rights_issue": (
                ("rights_ratio", lambda value: value > 0),
                ("subscription_price", lambda value: value > 0),
            ),
        }
        for row_index, action in result.iterrows():
            for field, predicate in requirements[action["action_type"]]:
                try:
                    value = float(action.get(field, np.nan))
                except (TypeError, ValueError):
                    value = np.nan
                if not np.isfinite(value) or not predicate(value):
                    raise ValueError(
                        "invalid corporate action "
                        f"{action['action_type']} field {field} at row {row_index}"
                    )
                result.at[row_index, field] = value
        return result

    @property
    def orders(self) -> pd.DataFrame:
        return pd.DataFrame(self.order_records)

    @property
    def trades(self) -> pd.DataFrame:
        return pd.DataFrame(self.trade_records)

    @property
    def equity(self) -> pd.DataFrame:
        return pd.DataFrame(self.equity_records)

    @property
    def holdings(self) -> pd.DataFrame:
        return pd.DataFrame(self.position_records)

    @property
    def cash_ledger(self) -> pd.DataFrame:
        return pd.DataFrame(self.cash_records)

    @property
    def fees_ledger(self) -> pd.DataFrame:
        return pd.DataFrame(self.fee_records)

    @property
    def rejections(self) -> pd.DataFrame:
        orders = self.orders
        if orders.empty:
            return orders
        return orders[orders["filled_shares"].eq(0)].reset_index(drop=True)

    @property
    def corporate_actions(self) -> pd.DataFrame:
        return pd.DataFrame(self.corporate_action_records)

    def _bar(self, trade_date, symbol: str) -> pd.Series | None:
        try:
            return self.bars.loc[(pd.Timestamp(trade_date).normalize(), symbol)]
        except KeyError:
            return None

    def _state(self, trade_date, symbol: str) -> pd.Series | None:
        try:
            return self.market_state.loc[(pd.Timestamp(trade_date).normalize(), symbol)]
        except KeyError:
            return None

    @staticmethod
    def _valid_price(value) -> bool:
        return not pd.isna(value) and np.isfinite(value) and value > 0

    def _asset_type(self, symbol: str) -> str:
        return self.asset_types.get(symbol, "stock")

    def _is_t_plus_one(self, symbol: str) -> bool:
        return self._asset_type(symbol) in self.config.t_plus_one_asset_types

    def _record_cash(self, trade_date, event: str, symbol: str | None, amount: float) -> None:
        self.cash += amount
        self.cash_records.append(
            {
                "trade_date": pd.Timestamp(trade_date).normalize(),
                "event": event,
                "symbol": symbol,
                "amount": amount,
                "cash_after": self.cash,
            }
        )

    def _start_session(self, trade_date) -> pd.Timestamp:
        date = pd.Timestamp(trade_date).normalize()
        if self._current_session is not None and date < self._current_session:
            raise ValueError("trade dates must be non-decreasing")
        if self._current_session != date:
            self._current_session = date
            self._session_volume_used = {}
            for position in self.positions.values():
                position.available_shares = position.shares
            self._apply_corporate_actions(date)
        return date

    def _apply_corporate_actions(self, trade_date: pd.Timestamp) -> None:
        if self.corporate_actions_frame.empty:
            return
        matches = self.corporate_actions_frame[
            self.corporate_actions_frame["action_date"].eq(trade_date)
        ]
        for row_index, action in matches.iterrows():
            if row_index in self._applied_action_rows:
                continue
            self._applied_action_rows.add(row_index)
            symbol = action["symbol"]
            position = self.positions.get(symbol)
            record = {
                "trade_date": trade_date,
                "symbol": symbol,
                "action_type": action["action_type"],
                "shares_before": 0 if position is None else position.shares,
                "shares_after": 0 if position is None else position.shares,
                "cash_change": 0.0,
                "status": "no_position" if position is None else "applied",
            }
            if position is None:
                self.corporate_action_records.append(record)
                continue
            action_type = action["action_type"]
            if action_type == "delisting":
                per_share = float(action.get("cash_per_share", 0.0))
                cash_change = position.shares * per_share
                if cash_change:
                    self._record_cash(trade_date, "delisting", symbol, cash_change)
                record.update(
                    {
                        "shares_after": 0,
                        "cash_change": cash_change,
                        "settlement_price": per_share,
                    }
                )
                del self.positions[symbol]
            elif action_type == "cash_dividend":
                per_share = float(action.get("cash_per_share", 0.0))
                cash_change = position.shares * per_share
                if cash_change:
                    self._record_cash(trade_date, "cash_dividend", symbol, cash_change)
                record["cash_change"] = cash_change
            elif action_type in {"bonus", "split", "consolidation"}:
                multiplier = float(action.get("share_multiplier", np.nan))
                if not np.isfinite(multiplier) or multiplier <= 0:
                    raise ValueError(
                        f"invalid share_multiplier for {symbol} on {trade_date.date()}"
                    )
                before = position.shares
                available_before = int(position.available_shares or 0)
                position.shares = int(np.floor(before * multiplier + 1e-9))
                position.available_shares = int(np.floor(available_before * multiplier + 1e-9))
                position.average_cost /= multiplier
                position.last_price /= multiplier
                record["shares_after"] = position.shares
                record["discarded_fractional_shares"] = before * multiplier - position.shares
            elif action_type == "rights_issue":
                ratio = float(action.get("rights_ratio", 0.0))
                price = float(action.get("subscription_price", np.nan))
                entitlement = int(np.floor(position.shares * ratio + 1e-9))
                if not self.config.participate_rights_issues:
                    record["status"] = "skipped_by_config"
                    record["entitled_shares"] = entitlement
                elif entitlement > 0 and self._valid_price(price):
                    subscribed = min(entitlement, int(self.cash / price))
                    cost = subscribed * price
                    if subscribed:
                        total_cost = position.average_cost * position.shares + cost
                        position.shares += subscribed
                        if not self._is_t_plus_one(symbol):
                            position.available_shares = (
                                int(position.available_shares or 0) + subscribed
                            )
                        position.average_cost = total_cost / position.shares
                        self._record_cash(trade_date, "rights_issue", symbol, -cost)
                    record.update(
                        {
                            "shares_after": position.shares,
                            "cash_change": -cost,
                            "entitled_shares": entitlement,
                            "subscribed_shares": subscribed,
                            "status": "applied" if subscribed == entitlement else "partial_cash",
                        }
                    )
                else:
                    record["status"] = "invalid_or_zero_entitlement"
            self.corporate_action_records.append(record)

    def _price_for_equity(self, trade_date, symbol: str, field: ExecutionField) -> float:
        bar = self._bar(trade_date, symbol)
        if bar is not None and field in bar and self._valid_price(bar[field]):
            return float(bar[field])
        return self.positions[symbol].last_price

    def total_value(self, trade_date, field: ExecutionField = "open") -> float:
        self._start_session(trade_date)
        holdings = sum(
            position.shares * self._price_for_equity(trade_date, symbol, field)
            for symbol, position in self.positions.items()
        )
        return self.cash + holdings

    def _new_order_id(self) -> int:
        value = self._next_order_id
        self._next_order_id += 1
        return value

    def _reject(
        self,
        order_id: int,
        trade_date,
        symbol: str,
        side: str,
        requested_shares: int,
        reason: str,
        execution: ExecutionField,
    ) -> None:
        self.order_records.append(
            {
                "order_id": order_id,
                "trade_date": pd.Timestamp(trade_date).normalize(),
                "symbol": symbol,
                "side": side,
                "execution": execution,
                "requested_shares": int(requested_shares),
                "filled_shares": 0,
                "unfilled_shares": int(requested_shares),
                "price": np.nan,
                "gross_value": 0.0,
                "commission": 0.0,
                "tax": 0.0,
                "reason": reason,
            }
        )

    def _tradability_reason(self, state: pd.Series | None, side: str) -> str | None:
        if state is None:
            return "missing_market_state"
        quality_rank = {"A": 0, "B": 1, "C": 2}
        minimum_rank = quality_rank[self.config.minimum_state_quality]
        for field in ("status_quality", "st_quality", "limit_quality"):
            if field not in state:
                if self.config.minimum_state_quality != "C":
                    return f"missing_{field}"
                continue
            actual = state.get(field)
            if pd.isna(actual) or quality_rank.get(str(actual), 99) > minimum_rank:
                return f"insufficient_{field}"
        paused = state.get("paused", pd.NA)
        if pd.isna(paused):
            return "unknown_paused"
        if bool(paused):
            return "paused"
        if side == "buy":
            is_st = state.get("is_st", pd.NA)
            if pd.isna(is_st) and not self.config.allow_unknown_st:
                return "unknown_st"
            if self.config.block_st_buys and not pd.isna(is_st) and bool(is_st):
                return "st_buy_blocked"
            buy_blocked = state.get("buy_blocked", pd.NA)
            if pd.isna(buy_blocked):
                return "unknown_buy_blocked"
            if bool(buy_blocked):
                return "up_limit"
        else:
            sell_blocked = state.get("sell_blocked", pd.NA)
            if pd.isna(sell_blocked):
                return "unknown_sell_blocked"
            if bool(sell_blocked):
                return "down_limit"
        return None

    def _maximum_fill(self, trade_date, symbol: str, bar: pd.Series, requested_shares: int) -> int:
        if "volume" not in bar or pd.isna(bar["volume"]):
            return requested_shares
        total_capacity = int(float(bar["volume"]) * self.config.maximum_volume_ratio)
        remaining = max(0, total_capacity - self._session_volume_used.get(symbol, 0))
        return min(requested_shares, remaining)

    def _round_request(self, symbol: str, side: str, requested: int) -> int:
        requested = max(0, int(requested))
        if side == "buy":
            return requested // self.config.lot_size * self.config.lot_size
        position = self.positions.get(symbol)
        if position is None:
            return 0
        # 全部卖出时允许清理送转或历史遗留的奇零股。
        if requested >= position.shares:
            return position.shares
        return requested // self.config.lot_size * self.config.lot_size

    def _execute(
        self,
        trade_date,
        symbol: str,
        side: str,
        requested_shares: int,
        execution: ExecutionField = "open",
    ) -> int:
        date = self._start_session(trade_date)
        symbol = symbol.upper()
        if execution not in {"open", "close"}:
            raise ValueError("execution must be open or close")
        order_id = self._new_order_id()
        original_requested = max(0, int(requested_shares))
        rounded = self._round_request(symbol, side, original_requested)
        if rounded <= 0:
            self._reject(order_id, date, symbol, side, original_requested, "below_lot", execution)
            return 0
        bar = self._bar(date, symbol)
        if bar is None or execution not in bar or not self._valid_price(bar[execution]):
            self._reject(
                order_id,
                date,
                symbol,
                side,
                original_requested,
                f"missing_{execution}",
                execution,
            )
            return 0
        reason = self._tradability_reason(self._state(date, symbol), side)
        if reason:
            self._reject(order_id, date, symbol, side, original_requested, reason, execution)
            return 0
        fill_shares = self._maximum_fill(date, symbol, bar, rounded)
        position = self.positions.get(symbol)
        if side == "sell":
            if position is None:
                self._reject(
                    order_id, date, symbol, side, original_requested, "no_position", execution
                )
                return 0
            available = (
                int(position.available_shares or 0)
                if self._is_t_plus_one(symbol)
                else position.shares
            )
            fill_shares = min(fill_shares, available)
            if fill_shares < position.shares:
                fill_shares = fill_shares // self.config.lot_size * self.config.lot_size
            if fill_shares <= 0:
                reason = "t_plus_one" if position.shares > 0 and available == 0 else "volume_limit"
                self._reject(order_id, date, symbol, side, original_requested, reason, execution)
                return 0
        elif fill_shares < rounded:
            fill_shares = fill_shares // self.config.lot_size * self.config.lot_size
        if fill_shares <= 0:
            self._reject(
                order_id, date, symbol, side, original_requested, "volume_limit", execution
            )
            return 0
        raw_price = float(bar[execution])
        direction = 1.0 if side == "buy" else -1.0
        price = raw_price * (1.0 + direction * self.config.slippage_rate)
        asset_type = self._asset_type(symbol)
        if side == "buy":
            while fill_shares > 0:
                gross = price * fill_shares
                commission, tax = self.costs.fees(asset_type, side, gross, date)
                if gross + commission + tax <= self.cash + 1e-8:
                    break
                fill_shares -= self.config.lot_size
            if fill_shares <= 0:
                self._reject(
                    order_id,
                    date,
                    symbol,
                    side,
                    original_requested,
                    "insufficient_cash",
                    execution,
                )
                return 0
        gross = price * fill_shares
        commission, tax = self.costs.fees(asset_type, side, gross, date)
        if side == "sell":
            assert position is not None
            self._record_cash(date, "sell", symbol, gross - commission - tax)
            position.shares -= fill_shares
            position.available_shares = max(0, int(position.available_shares or 0) - fill_shares)
            position.last_price = price
            if position.shares == 0:
                del self.positions[symbol]
        else:
            self._record_cash(date, "buy", symbol, -(gross + commission + tax))
            position = self.positions.get(symbol)
            if position is None:
                self.positions[symbol] = Position(
                    symbol=symbol,
                    shares=fill_shares,
                    average_cost=(gross + commission + tax) / fill_shares,
                    last_price=price,
                    available_shares=0 if self._is_t_plus_one(symbol) else fill_shares,
                )
            else:
                total_cost = position.average_cost * position.shares + gross + commission + tax
                position.shares += fill_shares
                if not self._is_t_plus_one(symbol):
                    position.available_shares = int(position.available_shares or 0) + fill_shares
                position.average_cost = total_cost / position.shares
                position.last_price = price
        self._session_volume_used[symbol] = self._session_volume_used.get(symbol, 0) + fill_shares
        fill_reason = "filled" if fill_shares == original_requested else "partial_volume_or_cash"
        record = {
            "order_id": order_id,
            "trade_date": date,
            "symbol": symbol,
            "side": side,
            "execution": execution,
            "requested_shares": original_requested,
            "filled_shares": int(fill_shares),
            "unfilled_shares": int(max(0, original_requested - fill_shares)),
            "price": price,
            "gross_value": gross,
            "commission": commission,
            "tax": tax,
            "reason": fill_reason,
        }
        self.order_records.append(record)
        self.trade_records.append(record.copy())
        self.fee_records.append(
            {
                "order_id": order_id,
                "trade_date": date,
                "symbol": symbol,
                "asset_type": asset_type,
                "commission": commission,
                "stamp_tax": tax,
                "total_fees": commission + tax,
            }
        )
        return int(fill_shares)

    def order_value(
        self,
        trade_date,
        symbol: str,
        value: float,
        execution: ExecutionField = "open",
    ) -> int:
        """按成交金额下单；正数买入，负数卖出。"""

        if value == 0:
            return 0
        symbol = symbol.upper()
        self._start_session(trade_date)
        bar = self._bar(trade_date, symbol)
        price = np.nan if bar is None or execution not in bar else bar[execution]
        if not self._valid_price(price):
            side = "buy" if value > 0 else "sell"
            return self._execute(trade_date, symbol, side, self.config.lot_size, execution)
        requested = int(abs(value) / float(price))
        return self._execute(
            trade_date,
            symbol,
            "buy" if value > 0 else "sell",
            requested,
            execution,
        )

    def order_target(
        self,
        trade_date,
        symbol: str,
        target_shares: int,
        execution: ExecutionField = "open",
    ) -> int:
        """把持仓调整到目标股数。"""

        if target_shares < 0:
            raise ValueError("long-only target_shares must not be negative")
        symbol = symbol.upper()
        current = self.positions.get(symbol, Position(symbol, 0, 0.0, 0.0)).shares
        difference = int(target_shares) - current
        if difference == 0:
            return 0
        return self._execute(
            trade_date,
            symbol,
            "buy" if difference > 0 else "sell",
            abs(difference),
            execution,
        )

    def order_target_value(
        self,
        trade_date,
        symbol: str,
        target_value: float,
        execution: ExecutionField = "open",
    ) -> int:
        """把单一证券市值调整到目标金额。"""

        if target_value < 0:
            raise ValueError("long-only target_value must not be negative")
        symbol = symbol.upper()
        bar = self._bar(trade_date, symbol)
        price = np.nan if bar is None or execution not in bar else bar[execution]
        if not self._valid_price(price):
            current = self.positions.get(symbol, Position(symbol, 0, 0.0, 0.0)).shares
            requested = current if target_value == 0 else self.config.lot_size
            return self._execute(
                trade_date,
                symbol,
                "sell" if target_value == 0 else "buy",
                requested,
                execution,
            )
        target_shares = int(target_value / float(price))
        if target_value > 0:
            target_shares = target_shares // self.config.lot_size * self.config.lot_size
        return self.order_target(trade_date, symbol, target_shares, execution)

    def order_target_percent(
        self,
        trade_date,
        symbol: str,
        target_percent: float,
        execution: ExecutionField = "open",
    ) -> int:
        if not 0 <= target_percent <= 1:
            raise ValueError("target_percent must be in [0, 1]")
        total = self.total_value(trade_date, execution)
        return self.order_target_value(trade_date, symbol, total * target_percent, execution)

    def order_target_weight(
        self,
        trade_date,
        symbol: str,
        target_weight: float,
        execution: ExecutionField = "open",
    ) -> int:
        return self.order_target_percent(trade_date, symbol, target_weight, execution)

    def rebalance_to_weights(
        self,
        trade_date,
        target_weights: dict[str, float],
        execution: ExecutionField = "open",
    ) -> None:
        """先卖后买，把组合调整到目标权重。"""

        date = self._start_session(trade_date)
        targets = {symbol.upper(): float(weight) for symbol, weight in target_weights.items()}
        if any(weight < 0 for weight in targets.values()):
            raise ValueError("long-only target weights must not be negative")
        if sum(targets.values()) > 1.000001:
            raise ValueError("target weights must sum to at most one")
        equity = self.total_value(date, field=execution)
        desired_shares: dict[str, int] = {}
        for symbol in set(self.positions).union(targets):
            bar = self._bar(date, symbol)
            if bar is None or execution not in bar or not self._valid_price(bar[execution]):
                desired_shares[symbol] = (
                    0
                    if targets.get(symbol, 0.0) == 0.0
                    else self.positions.get(symbol, Position(symbol, 0, 0.0, 0.0)).shares
                )
                continue
            target_value = equity * targets.get(symbol, 0.0)
            desired_shares[symbol] = (
                int(target_value / float(bar[execution])) // self.config.lot_size
            ) * self.config.lot_size
        for symbol in sorted(self.positions):
            current = self.positions[symbol].shares
            target = desired_shares.get(symbol, 0)
            if current > target:
                self.order_target(date, symbol, target, execution)
        buy_requests = []
        target_priority = {symbol: index for index, symbol in enumerate(targets)}
        for symbol, target in desired_shares.items():
            current = self.positions.get(symbol, Position(symbol, 0, 0.0, 0.0)).shares
            if target > current:
                buy_requests.append(
                    (
                        targets.get(symbol, 0.0),
                        target_priority.get(symbol, len(target_priority)),
                        symbol,
                        target,
                    )
                )
        for _, _, symbol, target in sorted(
            buy_requests,
            key=lambda item: (-item[0], item[1], item[2]),
        ):
            self.order_target(date, symbol, target, execution)

    def mark_close(self, trade_date) -> dict:
        date = self._start_session(trade_date)
        positions_value = 0.0
        for symbol, position in sorted(self.positions.items()):
            bar = self._bar(date, symbol)
            if bar is not None and "close" in bar and self._valid_price(bar["close"]):
                position.last_price = float(bar["close"])
            positions_value += position.market_value
            self.position_records.append(
                {
                    "trade_date": date,
                    "symbol": symbol,
                    "shares": position.shares,
                    "available_shares": position.available_shares,
                    "average_cost": position.average_cost,
                    "close": position.last_price,
                    "market_value": position.market_value,
                }
            )
        total = self.cash + positions_value
        previous_total = (
            self.equity_records[-1]["total_value"]
            if self.equity_records
            else self.config.initial_cash
        )
        record = {
            "trade_date": date,
            "cash": self.cash,
            "positions_value": positions_value,
            "total_value": total,
            "cash_ratio": self.cash / total if total > 0 else np.nan,
            "daily_return": total / previous_total - 1.0 if previous_total else np.nan,
        }
        self.equity_records.append(record)
        return record

    def run(
        self,
        calendar: Iterable,
        target_provider: Callable[[pd.Timestamp | None, pd.Timestamp], dict[str, float] | None],
        frequency: Literal["daily", "weekly", "monthly"] = "daily",
        when: Literal["first", "last"] = "first",
        execution: ExecutionField = "open",
    ) -> pd.DataFrame:
        dates = pd.DatetimeIndex(pd.to_datetime(list(calendar))).normalize()
        schedule = scheduled_dates(dates, frequency, when)
        previous_date = None
        for trade_date in dates:
            self._start_session(trade_date)
            if trade_date in schedule:
                targets = target_provider(previous_date, trade_date)
                if targets is not None:
                    self.rebalance_to_weights(trade_date, targets, execution)
            self.mark_close(trade_date)
            previous_date = trade_date
        return self.equity


def performance_metrics(
    equity: pd.DataFrame,
    trades: pd.DataFrame | None = None,
    trading_days: int = 252,
) -> dict:
    """计算组合收益、风险、换手与现金占用指标。"""

    if equity.empty:
        raise ValueError("equity curve is empty")
    values = pd.to_numeric(equity["total_value"], errors="raise")
    returns = pd.to_numeric(equity["daily_return"], errors="raise").fillna(0.0)
    initial_value = values.iloc[0] / (1.0 + returns.iloc[0])
    curve = pd.concat([pd.Series([initial_value]), values], ignore_index=True)
    years = max(len(values) / trading_days, 1.0 / trading_days)
    annualized = (values.iloc[-1] / initial_value) ** (1.0 / years) - 1.0
    volatility = returns.std(ddof=1) * np.sqrt(trading_days)
    sharpe = returns.mean() * trading_days / volatility if volatility > 0 else np.nan
    drawdown = curve / curve.cummax() - 1.0
    underwater = drawdown.lt(0)
    groups = underwater.ne(underwater.shift()).cumsum()
    longest_underwater = int(underwater.groupby(groups).sum().max())
    dates = pd.DatetimeIndex(pd.to_datetime(equity["trade_date"]))
    yearly = (
        pd.Series(returns.to_numpy(), index=dates)
        .groupby(dates.year)
        .agg(lambda series: (1.0 + series).prod() - 1.0)
    )
    gross_traded = 0.0
    if trades is not None and not trades.empty and "gross_value" in trades:
        gross_traded = float(pd.to_numeric(trades["gross_value"], errors="raise").sum())
    if "cash_ratio" in equity:
        cash_ratio = pd.to_numeric(equity["cash_ratio"], errors="coerce")
    elif "cash" in equity:
        cash_ratio = pd.to_numeric(equity["cash"], errors="coerce") / values
    else:
        cash_ratio = pd.Series(np.nan, index=equity.index)
    return {
        "total_return": float(values.iloc[-1] / initial_value - 1.0),
        "annualized_return": float(annualized),
        "maximum_drawdown": float(-drawdown.min()),
        "sharpe": float(sharpe),
        "annualized_volatility": float(volatility),
        "turnover": float(gross_traded / values.mean()) if values.mean() > 0 else np.nan,
        "average_cash_ratio": float(cash_ratio.mean()) if cash_ratio.notna().any() else np.nan,
        "maximum_cash_ratio": float(cash_ratio.max()) if cash_ratio.notna().any() else np.nan,
        "longest_underwater_trading_days": longest_underwater,
        "yearly_returns": {str(year): float(value) for year, value in yearly.items()},
    }
