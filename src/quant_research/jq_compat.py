"""常用聚宽研究 API 的薄兼容层。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import pandas as pd

from .data.contracts import QualityGrade
from .portal import CapabilityError, LocalDataPortal, PointInTimeError


TYPE_MAP = {
    "stock": "stock",
    "fund": "fund",
    "etf": "etf",
    "index": "index",
}


@dataclass(frozen=True)
class CurrentSecurityData:
    paused: bool
    is_st: bool | None
    high_limit: float | None
    low_limit: float | None
    last_price: float | None
    name: str | None = None


class LazyCurrentData(Mapping):
    """按证券代码触发加载，避免一次读入整个市场。"""

    def __init__(self, portal: LocalDataPortal, observation_date, minimum_quality):
        self.portal = portal
        self.observation_date = pd.Timestamp(observation_date).normalize()
        self.minimum_quality = minimum_quality
        self._cache: dict[str, CurrentSecurityData] = {}

    def __getitem__(self, symbol: str) -> CurrentSecurityData:
        symbol = symbol.upper()
        if symbol not in self._cache:
            frame = self.portal.market_snapshot(
                self.observation_date,
                [symbol],
                minimum_quality=self.minimum_quality,
            )
            if frame.empty:
                raise KeyError(symbol)
            row = frame.iloc[0]
            st_value = row["is_st"]
            self._cache[symbol] = CurrentSecurityData(
                paused=bool(row["paused"]),
                is_st=None if pd.isna(st_value) else bool(st_value),
                high_limit=None if pd.isna(row["high_limit"]) else float(row["high_limit"]),
                low_limit=None if pd.isna(row["low_limit"]) else float(row["low_limit"]),
                last_price=None if pd.isna(row["raw_close"]) else float(row["raw_close"]),
            )
        return self._cache[symbol]

    def __iter__(self):
        return iter(self._cache)

    def __len__(self):
        return len(self._cache)

    def get(self, key, default=None):
        raise TypeError("current_data is lazy; use current_data[code] instead of .get()")


class JoinQuantCompat:
    """以固定观察日运行的常用 JoinQuant 查询接口。"""

    def __init__(
        self,
        portal: LocalDataPortal,
        observation_date=None,
        minimum_quality: QualityGrade | str = QualityGrade.B,
        market_state_quality: QualityGrade | str = QualityGrade.C,
    ):
        self.portal = portal
        self.minimum_quality = QualityGrade(minimum_quality)
        self.market_state_quality = QualityGrade(market_state_quality)
        self.observation_date = None
        if observation_date is not None:
            self.set_observation_date(observation_date)

    def set_observation_date(self, observation_date) -> None:
        self.observation_date = pd.Timestamp(observation_date).normalize()

    def _observation_date(self, date=None) -> pd.Timestamp:
        if date is not None:
            return pd.Timestamp(date).normalize()
        if self.observation_date is None:
            raise PointInTimeError("set_observation_date() or an explicit date is required")
        return self.observation_date

    @staticmethod
    def _symbols(security) -> tuple[list[str], bool]:
        if isinstance(security, str):
            return [security.upper()], True
        return [str(symbol).upper() for symbol in security], False

    def get_price(
        self,
        security,
        start_date=None,
        end_date=None,
        frequency="daily",
        fields=None,
        skip_paused=False,
        fq="pre",
    ) -> pd.DataFrame:
        if frequency not in {"daily", "1d"}:
            raise CapabilityError("the local platform currently supports daily frequency only")
        end = self._observation_date(end_date)
        if start_date is None:
            start_date = end
        symbols, single = self._symbols(security)
        adjustment = "raw" if fq in {None, "none"} else fq
        frame = self.portal.bars(
            symbols,
            start_date,
            end,
            fields=fields or ("open", "high", "low", "close", "volume", "money"),
            adjustment=adjustment,
            skip_paused=skip_paused,
            minimum_quality=self.minimum_quality,
        )
        if single:
            return frame.drop(columns="symbol").set_index("trade_date")
        return frame.set_index(["trade_date", "symbol"])

    def attribute_history(
        self,
        security,
        count,
        unit="1d",
        fields=("close",),
        skip_paused=True,
        fq="pre",
    ) -> pd.DataFrame:
        if unit not in {"1d", "daily"}:
            raise CapabilityError("the local platform currently supports daily frequency only")
        end = self._observation_date()
        calendar = self.portal.calendar(end - pd.Timedelta(days=max(30, count * 4)), end)
        if len(calendar) < count:
            raise ValueError(f"only {len(calendar)} trading days are available, requested {count}")
        frame = self.get_price(
            security,
            start_date=calendar[0],
            end_date=end,
            fields=fields,
            skip_paused=skip_paused,
            fq=fq,
        )
        return frame.tail(count)

    def get_all_securities(self, types=("stock",), date=None) -> pd.DataFrame:
        observation_date = self._observation_date(date)
        asset_types = []
        for item in types:
            if item not in TYPE_MAP:
                raise CapabilityError(f"unsupported security type: {item}")
            asset_types.append(TYPE_MAP[item])
        frame = self.portal.instruments(
            observation_date,
            asset_types=asset_types,
            minimum_quality=self.minimum_quality,
        )
        return frame.set_index("symbol")

    def get_index_stocks(self, index_symbol, date=None) -> list[str]:
        return self.portal.index_members(
            index_symbol,
            self._observation_date(date),
            minimum_quality=self.minimum_quality,
        )

    def get_current_data(self) -> LazyCurrentData:
        return LazyCurrentData(
            self.portal,
            self._observation_date(),
            self.market_state_quality,
        )

    def get_fundamentals(
        self,
        symbols: str | Iterable[str],
        fields: Iterable[str] | None = None,
        date=None,
    ) -> pd.DataFrame:
        return self.portal.fundamentals(
            symbols,
            self._observation_date(date),
            fields=fields,
            minimum_quality=self.minimum_quality,
        )

    def get_industry(self, symbols: str | Iterable[str], date=None) -> dict:
        if isinstance(symbols, str):
            symbols = [symbols]
        frame = self.portal.industry(
            symbols,
            self._observation_date(date),
            minimum_quality=self.minimum_quality,
        )
        return {
            symbol: group.drop(columns="symbol").to_dict(orient="records")
            for symbol, group in frame.groupby("symbol")
        }
