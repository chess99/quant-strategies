"""可审计的 A 股/ETF 日线撮合器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CostModel:
    buy_commission: float = 0.0003
    sell_commission: float = 0.0003
    minimum_commission: float = 5.0
    stock_stamp_tax_before_2023_08_28: float = 0.001
    stock_stamp_tax_from_2023_08_28: float = 0.0005

    def fees(self, asset_type: str, side: str, gross: float, trade_date) -> tuple[float, float]:
        commission_rate = self.buy_commission if side == "buy" else self.sell_commission
        commission = max(self.minimum_commission, gross * commission_rate)
        tax = 0.0
        if asset_type == "stock" and side == "sell":
            cutoff = pd.Timestamp("2023-08-28")
            rate = (
                self.stock_stamp_tax_before_2023_08_28
                if pd.Timestamp(trade_date) < cutoff
                else self.stock_stamp_tax_from_2023_08_28
            )
            tax = gross * rate
        return commission, tax


@dataclass
class Position:
    symbol: str
    shares: int
    average_cost: float
    last_price: float

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


class DailyBacktester:
    """按开盘撮合目标权重，并在收盘记录组合净值。"""

    def __init__(
        self,
        bars: pd.DataFrame,
        market_state: pd.DataFrame,
        asset_types: dict[str, str] | None = None,
        config: BacktestConfig | None = None,
        costs: CostModel | None = None,
    ):
        self.config = config or BacktestConfig()
        self.costs = costs or CostModel()
        self.cash = float(self.config.initial_cash)
        self.positions: dict[str, Position] = {}
        self.asset_types = {key.upper(): value for key, value in (asset_types or {}).items()}
        self.bars = self._prepare_frame(bars, "bars")
        self.market_state = self._prepare_frame(market_state, "market_state")
        self.order_records: list[dict] = []
        self.trade_records: list[dict] = []
        self.equity_records: list[dict] = []
        self.position_records: list[dict] = []

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

    def _price_for_equity(self, trade_date, symbol: str, field: str) -> float:
        bar = self._bar(trade_date, symbol)
        if bar is not None and field in bar and self._valid_price(bar[field]):
            return float(bar[field])
        return self.positions[symbol].last_price

    def total_value(self, trade_date, field="open") -> float:
        holdings = sum(
            position.shares * self._price_for_equity(trade_date, symbol, field)
            for symbol, position in self.positions.items()
        )
        return self.cash + holdings

    def _reject(self, trade_date, symbol, side, requested_shares, reason) -> None:
        self.order_records.append(
            {
                "trade_date": pd.Timestamp(trade_date).normalize(),
                "symbol": symbol,
                "side": side,
                "requested_shares": int(requested_shares),
                "filled_shares": 0,
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
        if bool(state.get("paused", False)):
            return "paused"
        if side == "buy":
            is_st = state.get("is_st", pd.NA)
            if pd.isna(is_st) and not self.config.allow_unknown_st:
                return "unknown_st"
            if self.config.block_st_buys and not pd.isna(is_st) and bool(is_st):
                return "st_buy_blocked"
            if bool(state.get("buy_blocked", False)):
                return "price_limit"
        elif bool(state.get("sell_blocked", False)):
            return "price_limit"
        return None

    def _maximum_fill(self, bar: pd.Series, requested_shares: int) -> int:
        if "volume" not in bar or pd.isna(bar["volume"]):
            return requested_shares
        capacity = int(float(bar["volume"]) * self.config.maximum_volume_ratio)
        capacity = capacity // self.config.lot_size * self.config.lot_size
        return min(requested_shares, max(0, capacity))

    def _execute(self, trade_date, symbol: str, side: str, requested_shares: int) -> int:
        if requested_shares <= 0:
            return 0
        bar = self._bar(trade_date, symbol)
        if bar is None or "open" not in bar or not self._valid_price(bar["open"]):
            self._reject(trade_date, symbol, side, requested_shares, "missing_open")
            return 0
        state = self._state(trade_date, symbol)
        reason = self._tradability_reason(state, side)
        if reason:
            self._reject(trade_date, symbol, side, requested_shares, reason)
            return 0
        fill_shares = self._maximum_fill(bar, requested_shares)
        if side == "sell":
            fill_shares = min(fill_shares, self.positions.get(symbol, Position(symbol, 0, 0, 0)).shares)
        if fill_shares <= 0:
            self._reject(trade_date, symbol, side, requested_shares, "volume_limit")
            return 0
        raw_price = float(bar["open"])
        direction = 1.0 if side == "buy" else -1.0
        price = raw_price * (1.0 + direction * self.config.slippage_rate)
        asset_type = self.asset_types.get(symbol, "stock")
        if side == "buy":
            while fill_shares > 0:
                gross = price * fill_shares
                commission, tax = self.costs.fees(asset_type, side, gross, trade_date)
                if gross + commission + tax <= self.cash + 1e-8:
                    break
                fill_shares -= self.config.lot_size
            if fill_shares <= 0:
                self._reject(trade_date, symbol, side, requested_shares, "insufficient_cash")
                return 0
        gross = price * fill_shares
        commission, tax = self.costs.fees(asset_type, side, gross, trade_date)
        if side == "sell":
            self.cash += gross - commission - tax
            position = self.positions[symbol]
            position.shares -= fill_shares
            position.last_price = price
            if position.shares == 0:
                del self.positions[symbol]
        else:
            self.cash -= gross + commission + tax
            position = self.positions.get(symbol)
            if position is None:
                self.positions[symbol] = Position(
                    symbol=symbol,
                    shares=fill_shares,
                    average_cost=(gross + commission + tax) / fill_shares,
                    last_price=price,
                )
            else:
                total_cost = position.average_cost * position.shares + gross + commission + tax
                position.shares += fill_shares
                position.average_cost = total_cost / position.shares
                position.last_price = price
        fill_reason = "filled" if fill_shares == requested_shares else "partial_volume_or_cash"
        record = {
            "trade_date": pd.Timestamp(trade_date).normalize(),
            "symbol": symbol,
            "side": side,
            "requested_shares": int(requested_shares),
            "filled_shares": int(fill_shares),
            "price": price,
            "gross_value": gross,
            "commission": commission,
            "tax": tax,
            "reason": fill_reason,
        }
        self.order_records.append(record)
        self.trade_records.append(record.copy())
        return fill_shares

    def rebalance_to_weights(self, trade_date, target_weights: dict[str, float]) -> None:
        date = pd.Timestamp(trade_date).normalize()
        targets = {symbol.upper(): float(weight) for symbol, weight in target_weights.items()}
        if any(weight < 0 for weight in targets.values()):
            raise ValueError("long-only target weights must not be negative")
        if sum(targets.values()) > 1.000001:
            raise ValueError("target weights must sum to at most one")
        equity = self.total_value(date, field="open")
        desired_shares: dict[str, int] = {}
        for symbol in set(self.positions).union(targets):
            bar = self._bar(date, symbol)
            if bar is None or "open" not in bar or not self._valid_price(bar["open"]):
                desired_shares[symbol] = self.positions.get(
                    symbol, Position(symbol, 0, 0.0, 0.0)
                ).shares
                if targets.get(symbol, 0.0) == 0.0 and symbol in self.positions:
                    self._reject(date, symbol, "sell", desired_shares[symbol], "missing_open")
                continue
            target_value = equity * targets.get(symbol, 0.0)
            desired_shares[symbol] = (
                int(target_value / float(bar["open"])) // self.config.lot_size
            ) * self.config.lot_size
        for symbol in sorted(self.positions):
            current = self.positions[symbol].shares
            requested = current - desired_shares.get(symbol, 0)
            if requested > 0:
                self._execute(date, symbol, "sell", requested)
        buy_requests = []
        for symbol, target in desired_shares.items():
            current = self.positions.get(symbol, Position(symbol, 0, 0.0, 0.0)).shares
            if target > current:
                buy_requests.append((targets.get(symbol, 0.0), symbol, target - current))
        for _, symbol, requested in sorted(buy_requests, key=lambda item: (-item[0], item[1])):
            self._execute(date, symbol, "buy", requested)

    def mark_close(self, trade_date) -> dict:
        date = pd.Timestamp(trade_date).normalize()
        positions_value = 0.0
        for symbol, position in self.positions.items():
            bar = self._bar(date, symbol)
            if bar is not None and "close" in bar and self._valid_price(bar["close"]):
                position.last_price = float(bar["close"])
            positions_value += position.market_value
            self.position_records.append(
                {
                    "trade_date": date,
                    "symbol": symbol,
                    "shares": position.shares,
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
            "daily_return": total / previous_total - 1.0,
        }
        self.equity_records.append(record)
        return record

    def run(
        self,
        calendar: Iterable,
        target_provider: Callable[[pd.Timestamp | None, pd.Timestamp], dict[str, float] | None],
    ) -> pd.DataFrame:
        previous_date = None
        for value in calendar:
            trade_date = pd.Timestamp(value).normalize()
            targets = target_provider(previous_date, trade_date)
            if targets is not None:
                self.rebalance_to_weights(trade_date, targets)
            self.mark_close(trade_date)
            previous_date = trade_date
        return self.equity


def performance_metrics(equity: pd.DataFrame, trading_days: int = 252) -> dict:
    if equity.empty:
        raise ValueError("equity curve is empty")
    values = pd.to_numeric(equity["total_value"], errors="raise")
    returns = pd.to_numeric(equity["daily_return"], errors="raise")
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
    yearly = pd.Series(returns.to_numpy(), index=dates).groupby(dates.year).agg(
        lambda series: (1.0 + series).prod() - 1.0
    )
    return {
        "total_return": float(values.iloc[-1] / initial_value - 1.0),
        "annualized_return": float(annualized),
        "maximum_drawdown": float(-drawdown.min()),
        "sharpe": float(sharpe),
        "annualized_volatility": float(volatility),
        "longest_underwater_trading_days": longest_underwater,
        "yearly_returns": {str(year): float(value) for year, value in yearly.items()},
    }
