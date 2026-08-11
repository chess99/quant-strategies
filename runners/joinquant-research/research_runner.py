"""Self-contained research-grade daily backtester for JoinQuant Research.

Upload this file to JoinQuant Research and import it from a strategy module or
notebook.  The strategy callback receives a point-in-time context and returns
target weights.  Signals always observe the previous trading day; orders are
matched on the current trading day's open or close.

This is intentionally not an emulation of JoinQuant's complete strategy
runtime.  It provides a small, auditable contract for daily and lower-frequency
research and exports repository-compatible evidence files.
"""

import builtins
import hashlib
import json
import math
import shutil
from collections import OrderedDict
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from jqdata import get_all_trade_days, get_extras, get_price


ENGINE_VERSION = "1.0.0"
MANIFEST_SCHEMA_VERSION = 1
TRADING_DAYS_PER_YEAR = 250


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return datetime.strptime(value, "%Y-%m-%d").date()
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime().date()
    return pd.Timestamp(value).date()


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return OrderedDict((str(key), _json_value(item)) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _finite_number(value, field):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("{} must be numeric".format(field))
    if not math.isfinite(number):
        raise ValueError("{} must be finite".format(field))
    return number


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def scheduled_trade_days(days, frequency, when="first"):
    """Return actual trading days selected by a daily/weekly/monthly schedule."""
    normalized = [_as_date(day) for day in days]
    if frequency == "daily":
        return set(normalized)
    if frequency not in ("weekly", "monthly"):
        raise ValueError("frequency must be daily, weekly, or monthly")
    if when not in ("first", "last"):
        raise ValueError("schedule_when must be first or last")

    grouped = OrderedDict()
    for day in normalized:
        if frequency == "weekly":
            iso = day.isocalendar()
            key = (iso[0], iso[1])
        else:
            key = (day.year, day.month)
        grouped.setdefault(key, []).append(day)
    index = 0 if when == "first" else -1
    return set(values[index] for values in grouped.values())


class RunnerConfig:
    """Configuration for a point-in-time JoinQuant Research run."""

    def __init__(
        self,
        start_date,
        end_date,
        initial_cash=10_000_000,
        frequency="monthly",
        schedule_when="first",
        execution_price="open",
        price_adjustment="pre",
        lot_size=100,
        buy_commission=0.0003,
        sell_commission=0.0003,
        minimum_commission=5.0,
        stamp_tax=0.0005,
        buy_slippage=0.0,
        sell_slippage=0.0,
        reject_st=True,
        reject_unknown_state=True,
        run_id=None,
    ):
        self.start_date = _as_date(start_date)
        self.end_date = _as_date(end_date)
        self.initial_cash = _finite_number(initial_cash, "initial_cash")
        self.frequency = frequency
        self.schedule_when = schedule_when
        self.execution_price = execution_price
        self.price_adjustment = price_adjustment
        self.lot_size = int(lot_size)
        self.buy_commission = _finite_number(buy_commission, "buy_commission")
        self.sell_commission = _finite_number(sell_commission, "sell_commission")
        self.minimum_commission = _finite_number(
            minimum_commission, "minimum_commission"
        )
        self.stamp_tax = _finite_number(stamp_tax, "stamp_tax")
        self.buy_slippage = _finite_number(buy_slippage, "buy_slippage")
        self.sell_slippage = _finite_number(sell_slippage, "sell_slippage")
        self.reject_st = bool(reject_st)
        self.reject_unknown_state = bool(reject_unknown_state)
        self.run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
        self._validate()

    def _validate(self):
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if self.frequency not in ("daily", "weekly", "monthly"):
            raise ValueError("frequency must be daily, weekly, or monthly")
        if self.schedule_when not in ("first", "last"):
            raise ValueError("schedule_when must be first or last")
        if self.execution_price not in ("open", "close"):
            raise ValueError("execution_price must be open or close")
        if self.price_adjustment not in ("pre", "post", None):
            raise ValueError("price_adjustment must be pre, post, or None")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")
        rates = [
            self.buy_commission,
            self.sell_commission,
            self.minimum_commission,
            self.stamp_tax,
            self.buy_slippage,
            self.sell_slippage,
        ]
        if builtins.any(value < 0 for value in rates):
            raise ValueError("cost and slippage values must not be negative")

    def to_dict(self):
        return OrderedDict(
            [
                ("start_date", self.start_date.isoformat()),
                ("end_date", self.end_date.isoformat()),
                ("initial_cash", self.initial_cash),
                ("frequency", self.frequency),
                ("schedule_when", self.schedule_when),
                ("execution_price", self.execution_price),
                ("price_adjustment", self.price_adjustment),
                ("lot_size", self.lot_size),
                ("buy_commission", self.buy_commission),
                ("sell_commission", self.sell_commission),
                ("minimum_commission", self.minimum_commission),
                ("stamp_tax", self.stamp_tax),
                ("buy_slippage", self.buy_slippage),
                ("sell_slippage", self.sell_slippage),
                ("reject_st", self.reject_st),
                ("reject_unknown_state", self.reject_unknown_state),
                ("run_id", self.run_id),
            ]
        )


class PositionView:
    def __init__(self, code, values):
        self.security = code
        self.total_amount = int(values["amount"])
        self.closeable_amount = int(values["amount"])
        self.avg_cost = float(values["avg_cost"])
        self.price = float(values.get("last_price", self.avg_cost))
        self.value = self.total_amount * self.price


class PortfolioView:
    def __init__(self, cash, total_value, positions):
        self.available_cash = float(cash)
        self.cash = float(cash)
        self.total_value = float(total_value)
        self.positions = OrderedDict(
            (code, PositionView(code, values)) for code, values in positions.items()
        )


class ResearchContext:
    """Read-only strategy context passed to the target-weight callback."""

    def __init__(self, current_date, observation_date, portfolio, run_id):
        self.current_date = current_date
        self.observation_date = observation_date
        self.previous_date = observation_date
        self.current_dt = datetime.combine(current_date, datetime.min.time())
        self.portfolio = portfolio
        self.run_id = run_id


class ResearchResult:
    def __init__(self, config, equity, orders, positions, warnings):
        self.config = config
        self.equity = equity
        self.orders = orders
        self.positions = positions
        self.warnings = warnings
        self.metrics = performance_metrics(equity, orders, config.initial_cash)

    def export(self, output_dir, strategy_id, variant, source_path, make_zip=True):
        """Export an immutable repository-compatible result payload."""
        output = Path(output_dir)
        if output.exists() and list(output.iterdir()):
            raise RuntimeError("output directory is not empty: {}".format(output))
        bundle = Path(str(output) + ".zip")
        if make_zip and bundle.exists():
            raise RuntimeError("output bundle already exists: {}".format(bundle))
        output.mkdir(parents=True, exist_ok=True)
        raw = output / "raw"
        raw.mkdir(parents=True, exist_ok=True)

        source = Path(source_path)
        if not source.is_file():
            raise RuntimeError("strategy source does not exist: {}".format(source))
        shutil.copyfile(str(source), str(output / "source.py"))
        engine_path = Path(__file__)
        if not engine_path.is_file():
            raise RuntimeError("runner source is unavailable: {}".format(engine_path))
        shutil.copyfile(str(engine_path), str(output / "engine.py"))

        equity_frame = pd.DataFrame(self.equity)
        equity_frame.to_csv(str(raw / "equity.csv"), index=False, encoding="utf-8")
        orders_frame = pd.DataFrame(self.orders)
        order_columns = [
            "date",
            "code",
            "side",
            "requested_amount",
            "amount",
            "price",
            "value",
            "fees",
            "status",
            "reason",
        ]
        if orders_frame.empty:
            orders_frame = pd.DataFrame(columns=order_columns)
        orders_frame.to_csv(str(raw / "orders.csv"), index=False, encoding="utf-8")
        if orders_frame.empty:
            trades_frame = pd.DataFrame(columns=order_columns)
        else:
            trades_frame = orders_frame[
                orders_frame["status"].isin(["filled", "partial"])
            ].copy()
        trades_frame.to_csv(str(raw / "trades.csv"), index=False, encoding="utf-8")

        position_rows = []
        for snapshot in self.positions:
            for code, values in snapshot["positions"].items():
                position_rows.append(
                    {
                        "date": snapshot["date"],
                        "code": code,
                        "amount": values["amount"],
                        "avg_cost": values["avg_cost"],
                        "last_price": values["last_price"],
                        "market_value": values["amount"] * values["last_price"],
                    }
                )
        pd.DataFrame(
            position_rows,
            columns=["date", "code", "amount", "avg_cost", "last_price", "market_value"],
        ).to_csv(str(raw / "positions.csv"), index=False, encoding="utf-8")

        if self.warnings:
            (raw / "log.txt").write_text(
                "\n".join(self.warnings) + "\n", encoding="utf-8"
            )

        report = self._report(strategy_id, variant)
        (output / "report.md").write_text(report, encoding="utf-8")

        artifact_paths = [
            output / "source.py",
            output / "engine.py",
            output / "report.md",
            raw / "equity.csv",
            raw / "orders.csv",
            raw / "trades.csv",
            raw / "positions.csv",
        ]
        if (raw / "log.txt").exists():
            artifact_paths.append(raw / "log.txt")
        artifacts = OrderedDict()
        for path in artifact_paths:
            relative = str(path.relative_to(output)).replace("\\", "/")
            item = OrderedDict([("sha256", _sha256(path)), ("bytes", path.stat().st_size)])
            if path.suffix == ".csv":
                item["rows"] = max(len(path.read_text(encoding="utf-8").splitlines()) - 1, 0)
            artifacts[relative] = item

        manifest = OrderedDict(
            [
                ("schema_version", MANIFEST_SCHEMA_VERSION),
                ("platform", "joinquant-research"),
                ("strategy_family", strategy_id),
                ("variant", variant),
                ("run_id", self.config.run_id),
                ("engine_version", ENGINE_VERSION),
                ("engine_sha256", _sha256(output / "engine.py")),
                ("source_sha256", _sha256(output / "source.py")),
                ("config", self.config.to_dict()),
                ("metrics", _json_value(self.metrics)),
                ("warnings", list(self.warnings)),
                ("artifacts", artifacts),
            ]
        )
        (output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if make_zip:
            shutil.make_archive(str(output), "zip", root_dir=str(output))
        return manifest

    def _report(self, strategy_id, variant):
        metrics = self.metrics
        lines = [
            "# 聚宽 Research 回测报告",
            "",
            "## 事实",
            "",
            "- 策略族：`{}`".format(strategy_id),
            "- 变体：`{}`".format(variant),
            "- 运行标识：`{}`".format(self.config.run_id),
            "- 区间：{} 至 {}".format(
                self.config.start_date.isoformat(), self.config.end_date.isoformat()
            ),
            "- 累计收益：{:.4%}".format(metrics["cumulative_return"]),
            "- 年化收益：{:.4%}".format(metrics["annualized_return"]),
            "- 最大回撤：{:.4%}".format(metrics["max_drawdown"]),
            "- Sharpe：{:.4f}".format(metrics["sharpe"]),
            "- 换手：{:.4f}".format(metrics["turnover"]),
            "- 最长水下期：{} 天".format(metrics["longest_underwater_days"]),
            "",
            "## 推断",
            "",
            "- 本报告只证明该策略在自包含 Research Runner 撮合语义下的表现。",
            "- 与聚宽官方回测的一致性必须通过同源码、同区间黄金对照确认。",
            "",
            "## 已知限制",
            "",
            "- 日频撮合，不模拟分钟、Tick、集合竞价或涨跌停排队。",
            "- 默认使用连续前复权价格；公司行为后的名义股数和最低佣金可能与逐事件模拟不同。",
            "- ST、停牌和涨跌停依赖聚宽研究接口返回值；未知状态默认拒绝买入。",
            "- 策略回调必须只使用 `context.observation_date` 或更早数据。",
            "",
            "## 下一步实验",
            "",
            "- 使用相同源码在聚宽官方回测运行短窗口黄金对照。",
            "- 比较目标、成交、持仓、年化收益和最大回撤差异。",
            "",
        ]
        return "\n".join(lines)


class ResearchRunner:
    """Run target-weight strategies inside JoinQuant Research."""

    def __init__(self, config, target_weights):
        if not isinstance(config, RunnerConfig):
            raise TypeError("config must be RunnerConfig")
        if not callable(target_weights):
            raise TypeError("target_weights must be callable")
        self.config = config
        self.target_weights = target_weights
        self.cash = config.initial_cash
        self._positions = OrderedDict()
        self._orders = []
        self._equity = []
        self._position_snapshots = []
        self._warnings = []
        self._bar_cache = {}
        self._st_cache = {}

    def run(self):
        calendar = [_as_date(day) for day in get_all_trade_days()]
        run_days = [
            day
            for day in calendar
            if self.config.start_date <= day <= self.config.end_date
        ]
        if not run_days:
            raise RuntimeError("no trading days in configured interval")
        first_index = calendar.index(run_days[0])
        if first_index == 0:
            raise RuntimeError("a previous trading day is required")

        observation_by_day = {}
        for day in run_days:
            observation_by_day[day] = calendar[calendar.index(day) - 1]
        scheduled = scheduled_trade_days(
            run_days, self.config.frequency, self.config.schedule_when
        )

        for day in run_days:
            if day in scheduled:
                self._run_rebalance(day, observation_by_day[day])
            self._mark_to_market(day)
        return ResearchResult(
            self.config,
            list(self._equity),
            list(self._orders),
            list(self._position_snapshots),
            list(self._warnings),
        )

    def _run_rebalance(self, day, observation_date):
        execution_value = self._portfolio_value(day, self.config.execution_price)
        context = ResearchContext(
            day,
            observation_date,
            PortfolioView(self.cash, execution_value, self._positions),
            self.config.run_id,
        )
        requested = self.target_weights(context)
        targets = self._normalize_targets(requested)
        codes = list(self._positions.keys())
        for code in targets:
            if code not in codes:
                codes.append(code)

        desired = OrderedDict()
        for code in codes:
            weight = targets.get(code, 0.0)
            bar = self._read_bar(code, day)
            if bar is None:
                desired[code] = self._positions.get(code, {}).get("amount", 0)
                self._record_rejection(day, code, "buy", 0, "missing_price")
                continue
            raw_price = bar[self.config.execution_price]
            price = self._trade_price(raw_price, "buy")
            desired[code] = self._round_lot(execution_value * weight / price)

        for code in list(self._positions.keys()):
            current = self._positions[code]["amount"]
            target = desired.get(code, 0)
            if target < current:
                self._sell(day, code, current - target)

        for code in targets:
            current = self._positions.get(code, {}).get("amount", 0)
            target = desired.get(code, current)
            if target > current:
                self._buy(day, code, target - current)

    def _normalize_targets(self, requested):
        if requested is None:
            requested = {}
        if not hasattr(requested, "items"):
            raise TypeError("target_weights must return a mapping")
        targets = OrderedDict()
        for code, value in requested.items():
            weight = _finite_number(value, "target weight")
            if weight < 0:
                raise ValueError("target weights must not be negative")
            if weight > 0:
                targets[str(code)] = weight
        total = builtins.sum(targets.values())
        if total > 1.0 + 1e-9:
            raise ValueError("target weights must sum to at most 1")
        return targets

    def _buy(self, day, code, requested_amount):
        bar = self._read_bar(code, day)
        if bar is None:
            self._record_rejection(day, code, "buy", requested_amount, "missing_price")
            return
        state_reason = self._buy_state_reason(code, day, bar)
        if state_reason:
            self._record_rejection(day, code, "buy", requested_amount, state_reason)
            return
        price = self._trade_price(bar[self.config.execution_price], "buy")
        amount = self._round_lot(requested_amount)
        while amount >= self.config.lot_size:
            value = amount * price
            fees = self._buy_fees(value)
            if value + fees <= self.cash + 1e-9:
                break
            amount -= self.config.lot_size
        if amount < self.config.lot_size:
            self._record_rejection(day, code, "buy", requested_amount, "insufficient_cash")
            return

        value = amount * price
        fees = self._buy_fees(value)
        old = self._positions.get(code)
        if old is None:
            position = {
                "amount": amount,
                "avg_cost": (value + fees) / amount,
                "last_price": price,
            }
            self._positions[code] = position
        else:
            old_cost = old["avg_cost"] * old["amount"]
            new_amount = old["amount"] + amount
            old["amount"] = new_amount
            old["avg_cost"] = (old_cost + value + fees) / new_amount
            old["last_price"] = price
        self.cash -= value + fees
        status = "filled" if amount == requested_amount else "partial"
        reason = "" if status == "filled" else "cash_limited"
        self._orders.append(
            self._order(day, code, "buy", requested_amount, amount, price, fees, status, reason)
        )

    def _sell(self, day, code, requested_amount):
        position = self._positions.get(code)
        if position is None:
            self._record_rejection(day, code, "sell", requested_amount, "not_held")
            return
        bar = self._read_bar(code, day)
        if bar is None:
            self._record_rejection(day, code, "sell", requested_amount, "missing_price")
            return
        if bool(bar.get("paused", False)):
            self._record_rejection(day, code, "sell", requested_amount, "paused")
            return
        raw_price = _finite_number(bar[self.config.execution_price], "execution price")
        low_limit = bar.get("low_limit")
        if low_limit is not None and math.isfinite(float(low_limit)):
            if raw_price <= float(low_limit) + 1e-12:
                self._record_rejection(day, code, "sell", requested_amount, "low_limit")
                return

        amount = min(int(requested_amount), int(position["amount"]))
        if amount != position["amount"]:
            amount = self._round_lot(amount)
        if amount <= 0:
            self._record_rejection(day, code, "sell", requested_amount, "below_lot")
            return
        price = self._trade_price(raw_price, "sell")
        value = amount * price
        fees = self._sell_fees(value)
        self.cash += value - fees
        position["amount"] -= amount
        position["last_price"] = price
        if position["amount"] == 0:
            del self._positions[code]
        status = "filled" if amount == requested_amount else "partial"
        reason = "" if status == "filled" else "position_limited"
        self._orders.append(
            self._order(day, code, "sell", requested_amount, amount, price, fees, status, reason)
        )

    def _buy_state_reason(self, code, day, bar):
        if bool(bar.get("paused", False)):
            return "paused"
        st_value = self._read_st(code, day)
        if self.config.reject_st and st_value is True:
            return "st"
        if self.config.reject_unknown_state and st_value is None:
            return "unknown_st"
        raw_price = _finite_number(bar[self.config.execution_price], "execution price")
        high_limit = bar.get("high_limit")
        if high_limit is None or not math.isfinite(float(high_limit)):
            if self.config.reject_unknown_state:
                return "unknown_high_limit"
        elif raw_price >= float(high_limit) - 1e-12:
            return "high_limit"
        return None

    def _read_bar(self, code, day):
        key = (code, day)
        if key in self._bar_cache:
            return self._bar_cache[key]
        frame = get_price(
            code,
            count=1,
            end_date=day,
            frequency="daily",
            fields=["open", "close", "high_limit", "low_limit", "paused", "volume"],
            skip_paused=False,
            panel=False,
            fq=self.config.price_adjustment,
        )
        if frame is None or frame.empty:
            self._bar_cache[key] = None
            return None
        row = frame.iloc[-1]
        result = {}
        for field in ("open", "close", "high_limit", "low_limit", "paused", "volume"):
            result[field] = row[field] if field in row.index else None
        self._bar_cache[key] = result
        return result

    def _read_st(self, code, day):
        key = (code, day)
        if key in self._st_cache:
            return self._st_cache[key]
        try:
            frame = get_extras(
                "is_st", [code], start_date=day, end_date=day, df=True
            )
            if frame is None or frame.empty:
                value = None
            elif code in frame.columns:
                value = bool(frame[code].iloc[-1])
            else:
                value = bool(frame.iloc[-1, 0])
        except Exception as error:
            value = None
            self._warnings.append(
                "{} {} ST state unavailable: {}".format(day.isoformat(), code, error)
            )
        self._st_cache[key] = value
        return value

    def _portfolio_value(self, day, field):
        market_value = 0.0
        for code, position in self._positions.items():
            bar = self._read_bar(code, day)
            if bar is not None and bar.get(field) is not None:
                price = float(bar[field])
                if math.isfinite(price):
                    position["last_price"] = price
            market_value += position["amount"] * position["last_price"]
        return self.cash + market_value

    def _mark_to_market(self, day):
        total = self._portfolio_value(day, "close")
        market_value = total - self.cash
        previous = self._equity[-1]["total_value"] if self._equity else self.config.initial_cash
        daily_return = total / previous - 1.0 if previous else 0.0
        self._equity.append(
            {
                "date": day.isoformat(),
                "cash": self.cash,
                "market_value": market_value,
                "total_value": total,
                "daily_return": daily_return,
            }
        )
        snapshot = OrderedDict()
        for code, values in self._positions.items():
            snapshot[code] = {
                "amount": int(values["amount"]),
                "avg_cost": float(values["avg_cost"]),
                "last_price": float(values["last_price"]),
            }
        self._position_snapshots.append(
            {"date": day.isoformat(), "positions": snapshot}
        )

    def _trade_price(self, raw_price, side):
        price = _finite_number(raw_price, "execution price")
        if price <= 0:
            raise ValueError("execution price must be positive")
        if side == "buy":
            return price * (1.0 + self.config.buy_slippage)
        return price * (1.0 - self.config.sell_slippage)

    def _round_lot(self, amount):
        return int(float(amount) // self.config.lot_size) * self.config.lot_size

    def _buy_fees(self, value):
        if value <= 0:
            return 0.0
        return max(self.config.minimum_commission, value * self.config.buy_commission)

    def _sell_fees(self, value):
        if value <= 0:
            return 0.0
        commission = max(
            self.config.minimum_commission, value * self.config.sell_commission
        )
        return commission + value * self.config.stamp_tax

    def _record_rejection(self, day, code, side, requested_amount, reason):
        self._orders.append(
            self._order(day, code, side, requested_amount, 0, None, 0, "rejected", reason)
        )

    @staticmethod
    def _order(day, code, side, requested, amount, price, fees, status, reason):
        value = amount * price if price is not None else 0.0
        return {
            "date": day.isoformat(),
            "code": code,
            "side": side,
            "requested_amount": int(requested),
            "amount": int(amount),
            "price": price,
            "value": value,
            "fees": fees,
            "status": status,
            "reason": reason,
        }


def performance_metrics(equity, orders, initial_cash):
    """Calculate auditable daily-return metrics from exported ledgers."""
    if not equity:
        raise ValueError("equity ledger must not be empty")
    values = np.asarray([float(row["total_value"]) for row in equity], dtype=float)
    dates = [_as_date(row["date"]) for row in equity]
    returns = np.asarray([float(row["daily_return"]) for row in equity], dtype=float)
    cumulative = values[-1] / float(initial_cash) - 1.0
    annualized = (values[-1] / float(initial_cash)) ** (
        TRADING_DAYS_PER_YEAR / float(len(values))
    ) - 1.0

    peak = float(initial_cash)
    peak_date = dates[0]
    max_drawdown = 0.0
    drawdown_start = dates[0]
    drawdown_end = dates[0]
    underwater_start = None
    longest_underwater = 0
    for index, value in enumerate(values):
        day = dates[index]
        if value >= peak:
            peak = value
            peak_date = day
            if underwater_start is not None:
                longest_underwater = max(longest_underwater, (day - underwater_start).days)
                underwater_start = None
        else:
            if underwater_start is None:
                underwater_start = peak_date
            drawdown = 1.0 - value / peak
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                drawdown_start = peak_date
                drawdown_end = day
    if underwater_start is not None:
        longest_underwater = max(longest_underwater, (dates[-1] - underwater_start).days)

    if len(returns) > 1 and float(np.std(returns, ddof=1)) > 0:
        sharpe = float(np.mean(returns) / np.std(returns, ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR))
    else:
        sharpe = 0.0
    traded = builtins.sum(
        float(order["value"])
        for order in orders
        if order["status"] in ("filled", "partial")
    )
    average_equity = float(np.mean(values))
    turnover = traded / average_equity if average_equity > 0 else 0.0

    yearly = OrderedDict()
    base = float(initial_cash)
    years = OrderedDict()
    for day, value in zip(dates, values):
        years[day.year] = value
    for year, value in years.items():
        yearly[str(year)] = value / base - 1.0
        base = value

    return OrderedDict(
        [
            ("cumulative_return", cumulative),
            ("annualized_return", annualized),
            ("max_drawdown", max_drawdown),
            ("max_drawdown_start", drawdown_start.isoformat()),
            ("max_drawdown_end", drawdown_end.isoformat()),
            ("sharpe", sharpe),
            ("turnover", turnover),
            ("longest_underwater_days", int(longest_underwater)),
            ("ending_value", float(values[-1])),
            ("trading_days", len(values)),
            ("yearly_returns", yearly),
        ]
    )
