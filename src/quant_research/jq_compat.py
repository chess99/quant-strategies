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
JQ_EXCHANGE_TO_PREFIX = {"XSHG": "SH", "XSHE": "SZ", "XBSE": "BJ"}
PREFIX_TO_JQ_EXCHANGE = {value: key for key, value in JQ_EXCHANGE_TO_PREFIX.items()}


def to_local_symbol(symbol: str) -> str:
    text = str(symbol).upper()
    if "." in text:
        code, exchange = text.split(".", maxsplit=1)
        if exchange not in JQ_EXCHANGE_TO_PREFIX:
            raise CapabilityError(f"unsupported JoinQuant exchange: {exchange}")
        return f"{JQ_EXCHANGE_TO_PREFIX[exchange]}{code.zfill(6)}"
    if text[:2] in PREFIX_TO_JQ_EXCHANGE:
        return text
    raise CapabilityError(f"unsupported security code: {symbol}")


def to_joinquant_symbol(symbol: str) -> str:
    local = to_local_symbol(symbol)
    return f"{local[2:]}.{PREFIX_TO_JQ_EXCHANGE[local[:2]]}"


@dataclass(frozen=True)
class CurrentSecurityData:
    paused: bool
    is_st: bool | None
    high_limit: float | None
    low_limit: float | None
    last_price: float | None
    name: str | None = None
    status_quality: str | None = None
    st_quality: str | None = None
    limit_quality: str | None = None


class LazyCurrentData(Mapping):
    """按证券代码触发加载，避免一次读入整个市场。"""

    def __init__(self, portal: LocalDataPortal, observation_date, minimum_quality):
        self.portal = portal
        self.observation_date = pd.Timestamp(observation_date).normalize()
        self.minimum_quality = minimum_quality
        self._cache: dict[str, CurrentSecurityData] = {}

    def __getitem__(self, symbol: str) -> CurrentSecurityData:
        requested = str(symbol).upper()
        local_symbol = to_local_symbol(requested)
        if requested not in self._cache:
            frame = self.portal.market_snapshot(
                self.observation_date,
                [local_symbol],
                minimum_quality=self.minimum_quality,
            )
            if frame.empty:
                raise KeyError(requested)
            row = frame.iloc[0]
            st_value = row["is_st"]
            master = self.portal.store.read_parquet("security_master")
            names = master.loc[master["symbol"].eq(local_symbol), "display_name"]
            self._cache[requested] = CurrentSecurityData(
                paused=bool(row["paused"]),
                is_st=None if pd.isna(st_value) else bool(st_value),
                high_limit=None if pd.isna(row["high_limit"]) else float(row["high_limit"]),
                low_limit=None if pd.isna(row["low_limit"]) else float(row["low_limit"]),
                last_price=None if pd.isna(row["raw_close"]) else float(row["raw_close"]),
                name=None if names.empty or pd.isna(names.iloc[0]) else str(names.iloc[0]),
                status_quality=row.get("status_quality"),
                st_quality=row.get("st_quality"),
                limit_quality=row.get("limit_quality"),
            )
        return self._cache[requested]

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
            return [to_local_symbol(security)], True
        return [to_local_symbol(symbol) for symbol in security], False

    @property
    def last_query_provenance(self) -> dict | None:
        return self.portal.last_query_provenance

    def get_price(
        self,
        security,
        start_date=None,
        end_date=None,
        frequency="daily",
        fields=None,
        skip_paused=False,
        fq="pre",
        count=None,
        panel=False,
        fill_paused=True,
    ) -> pd.DataFrame:
        if frequency not in {"daily", "1d"}:
            raise CapabilityError("the local platform currently supports daily frequency only")
        end = self._observation_date(end_date)
        if panel not in {False, None}:
            raise CapabilityError("pandas Panel is not supported; pass panel=False")
        if count is not None:
            if start_date is not None:
                raise ValueError("count and start_date cannot be used together")
            calendar = self.portal.calendar(
                end - pd.Timedelta(days=max(30, int(count) * 4)), end
            )
            if len(calendar) < int(count):
                raise ValueError(f"only {len(calendar)} sessions, requested {count}")
            start_date = calendar[-int(count)]
        elif start_date is None:
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
        if fill_paused and not frame.empty:
            fill_fields = [
                field
                for field in (fields or ("open", "high", "low", "close"))
                if field in frame.columns and field != "volume" and field != "money"
            ]
            frame[fill_fields] = frame.groupby("symbol")[fill_fields].ffill()
        frame["symbol"] = frame["symbol"].map(to_joinquant_symbol)
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
        df=True,
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
        result = frame.tail(count)
        return result if df else result.to_dict(orient="list")

    def history(
        self,
        count,
        unit="1d",
        field="close",
        security_list=None,
        df=True,
        skip_paused=False,
        fq="pre",
    ):
        if security_list is None:
            raise ValueError("security_list is required")
        if isinstance(security_list, str):
            security_list = [security_list]
        frame = self.get_price(
            security_list,
            end_date=self._observation_date(),
            count=count,
            frequency=unit,
            fields=[field],
            skip_paused=skip_paused,
            fq=fq,
            panel=False,
        ).reset_index()
        result = frame.pivot(index="trade_date", columns="symbol", values=field)
        result = result.reindex(columns=[to_joinquant_symbol(x) for x in security_list])
        return result if df else result.to_dict(orient="list")

    def get_all_securities(self, types=("stock",), date=None) -> pd.DataFrame:
        observation_date = self._observation_date(date)
        asset_types = []
        for item in types:
            if item not in TYPE_MAP:
                raise CapabilityError(f"unsupported security type: {item}")
            asset_types.append(TYPE_MAP[item])
            if item == "fund":
                asset_types.append("etf")
        frame = self.portal.instruments(
            observation_date,
            asset_types=asset_types,
            minimum_quality=self.minimum_quality,
        )
        frame["symbol"] = frame["symbol"].map(to_joinquant_symbol)
        return frame.set_index("symbol")

    def get_index_stocks(self, index_symbol, date=None) -> list[str]:
        members = self.portal.index_members(
            to_local_symbol(index_symbol),
            self._observation_date(date),
            minimum_quality=self.minimum_quality,
        )
        return [to_joinquant_symbol(symbol) for symbol in members]

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
        statDate=None,
    ) -> pd.DataFrame:
        if statDate is not None:
            raise CapabilityError(
                "statDate query is not supported; pass an observation date and use "
                "LocalDataPortal.fundamentals() for explicit report-period filtering"
            )
        if not isinstance(symbols, (str, list, tuple, set)):
            raise CapabilityError(
                "JoinQuant query DSL is not supported; migrate the query to "
                "get_fundamentals(symbols, fields=[...], date=observation_date)"
            )
        return self.portal.fundamentals(
            [to_local_symbol(symbol) for symbol in ([symbols] if isinstance(symbols, str) else symbols)],
            self._observation_date(date),
            fields=fields,
            minimum_quality=self.minimum_quality,
        )

    def get_industry(self, symbols: str | Iterable[str], date=None) -> dict:
        if isinstance(symbols, str):
            symbols = [symbols]
        frame = self.portal.industry(
            [to_local_symbol(symbol) for symbol in symbols],
            self._observation_date(date),
            minimum_quality=self.minimum_quality,
        )
        return {
            to_joinquant_symbol(symbol): group.drop(columns="symbol").to_dict(orient="records")
            for symbol, group in frame.groupby("symbol")
        }
