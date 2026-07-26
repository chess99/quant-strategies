"""本地日频研究统一数据入口。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

import pandas as pd

from .data.contracts import QualityGrade
from .data.store import ResearchDataStore


class CapabilityError(RuntimeError):
    """请求的数据集或语义尚未实现。"""


class DataQualityError(RuntimeError):
    """可用数据低于策略声明的最低质量。"""


class PointInTimeError(ValueError):
    """查询缺少观察日，可能引入未来数据。"""


BAR_FIELDS = ("open", "high", "low", "close", "volume", "money")


class DailyBarSource(Protocol):
    quality_grade: QualityGrade

    def calendar(self, start_date, end_date) -> pd.DatetimeIndex: ...

    def load(
        self,
        symbols: list[str],
        start_date,
        end_date,
        fields: list[str],
        adjustment: str,
    ) -> pd.DataFrame: ...


@dataclass
class FrameDailyBarSource:
    """测试和小型研究使用的内存日线源；输入价格必须是原始价。"""

    frame: pd.DataFrame
    quality_grade: QualityGrade = QualityGrade.B

    def __post_init__(self):
        self.frame = self.frame.copy()
        self.frame["symbol"] = self.frame["symbol"].str.upper()
        self.frame["trade_date"] = pd.to_datetime(self.frame["trade_date"]).dt.normalize()

    def calendar(self, start_date, end_date) -> pd.DatetimeIndex:
        dates = self.frame["trade_date"].drop_duplicates().sort_values()
        return pd.DatetimeIndex(dates[(dates >= pd.Timestamp(start_date)) & (dates <= pd.Timestamp(end_date))])

    def load(self, symbols, start_date, end_date, fields, adjustment):
        if adjustment not in {"raw", "pre"}:
            raise CapabilityError(f"unsupported adjustment: {adjustment}")
        mask = (
            self.frame["symbol"].isin(symbols)
            & self.frame["trade_date"].between(pd.Timestamp(start_date), pd.Timestamp(end_date))
        )
        available = [field for field in fields if field in self.frame.columns]
        missing = set(fields).difference(available)
        if missing:
            raise CapabilityError(f"daily bar fields are unavailable: {sorted(missing)}")
        return self.frame.loc[mask, ["symbol", "trade_date", *available]].copy()


@dataclass
class QlibDailyBarSource:
    """Qlib 社区中国日线适配器。"""

    provider_uri: Path | str = Path("D:/code/_open-source/_data/qlib/cn_data")
    quality_grade: QualityGrade = QualityGrade.B
    _initialized: bool = False

    def _initialize(self):
        if self._initialized:
            return
        try:
            import qlib
        except ImportError as exc:
            raise CapabilityError("pyqlib is required for the Qlib daily source") from exc
        qlib.init(provider_uri=str(self.provider_uri), region="cn")
        self._initialized = True

    def calendar(self, start_date, end_date) -> pd.DatetimeIndex:
        self._initialize()
        from qlib.data import D

        return pd.DatetimeIndex(D.calendar(start_date, end_date, freq="day")).normalize()

    def load(self, symbols, start_date, end_date, fields, adjustment):
        if adjustment not in {"raw", "pre"}:
            raise CapabilityError(f"unsupported adjustment: {adjustment}")
        unknown = set(fields).difference(BAR_FIELDS)
        if unknown:
            raise CapabilityError(f"daily bar fields are unavailable: {sorted(unknown)}")
        self._initialize()
        from qlib.data import D

        qlib_names = {"money": "amount"}
        requested = [qlib_names.get(field, field) for field in fields]
        raw_fields = [f"${field}" for field in sorted(set(requested + ["factor"]))]
        frame = D.features(
            symbols,
            raw_fields,
            start_time=start_date,
            end_time=end_date,
            freq="day",
        ).reset_index()
        frame.columns = [column.removeprefix("$") for column in frame.columns]
        frame.rename(columns={"instrument": "symbol", "datetime": "trade_date"}, inplace=True)
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.normalize()
        factor = pd.to_numeric(frame["factor"], errors="coerce")
        price_fields = set(fields).intersection({"open", "high", "low", "close"})
        if adjustment == "raw":
            for field in price_fields:
                frame[field] = pd.to_numeric(frame[field], errors="coerce") / factor
        else:
            last_factor = frame.groupby("symbol")["factor"].transform("last")
            for field in price_fields:
                frame[field] = pd.to_numeric(frame[field], errors="coerce") / last_factor
        if "volume" in fields:
            # Qlib 社区中国包以手记录成交量；本地统一成股。
            frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce") * 100.0
        if "money" in fields:
            frame.rename(columns={"amount": "money"}, inplace=True)
        return frame[["symbol", "trade_date", *fields]].copy()


class LocalDataPortal:
    """显式观察日、显式质量门槛的本地统一数据接口。"""

    def __init__(self, store: ResearchDataStore, daily_bars: DailyBarSource):
        self.store = store
        self.daily_bars = daily_bars

    @staticmethod
    def _date(value, name="observation_date") -> pd.Timestamp:
        if value is None:
            raise PointInTimeError(f"{name} is required")
        return pd.Timestamp(value).normalize()

    @staticmethod
    def _symbols(symbols: str | Iterable[str]) -> list[str]:
        if isinstance(symbols, str):
            symbols = [symbols]
        return sorted({str(symbol).upper() for symbol in symbols})

    def _require_dataset(self, dataset: str, minimum_quality: QualityGrade | str) -> dict:
        try:
            manifest = self.store.read_manifest(dataset)
        except FileNotFoundError as exc:
            raise CapabilityError(f"dataset is unavailable: {dataset}") from exc
        actual = QualityGrade(manifest["quality_grade"])
        minimum = QualityGrade(minimum_quality)
        if not actual.meets(minimum):
            raise DataQualityError(
                f"dataset {dataset} quality {actual.value} is below required {minimum.value}"
            )
        return manifest

    def calendar(self, start_date, end_date) -> pd.DatetimeIndex:
        start = self._date(start_date, "start_date")
        end = self._date(end_date, "end_date")
        if end < start:
            raise ValueError("end_date must not be earlier than start_date")
        return self.daily_bars.calendar(start, end)

    def instruments(
        self,
        observation_date,
        asset_types: Iterable[str] | None = None,
        minimum_quality: QualityGrade | str = QualityGrade.B,
    ) -> pd.DataFrame:
        date = self._date(observation_date)
        self._require_dataset("security_master", minimum_quality)
        frame = self.store.read_parquet("security_master")
        mask = pd.to_datetime(frame["start_date"]).le(date) & pd.to_datetime(
            frame["end_date"]
        ).ge(date)
        if asset_types is not None:
            mask &= frame["asset_type"].isin(set(asset_types))
        return frame.loc[mask].sort_values("symbol").reset_index(drop=True)

    def bars(
        self,
        symbols: str | Iterable[str],
        start_date,
        end_date,
        fields: Iterable[str] = ("open", "high", "low", "close", "volume"),
        adjustment: str = "pre",
        skip_paused: bool = False,
        minimum_quality: QualityGrade | str = QualityGrade.B,
    ) -> pd.DataFrame:
        start = self._date(start_date, "start_date")
        end = self._date(end_date, "end_date")
        minimum = QualityGrade(minimum_quality)
        if not self.daily_bars.quality_grade.meets(minimum):
            raise DataQualityError(
                f"daily bars quality {self.daily_bars.quality_grade.value} "
                f"is below required {minimum.value}"
            )
        requested_fields = list(dict.fromkeys(fields))
        frame = self.daily_bars.load(
            self._symbols(symbols), start, end, requested_fields, adjustment
        )
        if skip_paused and not frame.empty:
            price_fields = [field for field in ("open", "close") if field in frame.columns]
            frame = frame.dropna(subset=price_fields)
            if "volume" in frame.columns:
                frame = frame[frame["volume"].fillna(0).gt(0)]
        return frame.sort_values(["trade_date", "symbol"]).reset_index(drop=True)

    def index_members(
        self,
        index_symbol: str,
        observation_date,
        minimum_quality: QualityGrade | str = QualityGrade.B,
    ) -> list[str]:
        date = self._date(observation_date)
        self._require_dataset("index_membership", minimum_quality)
        frame = self.store.read_parquet("index_membership")
        mask = (
            frame["index_symbol"].eq(index_symbol.upper())
            & pd.to_datetime(frame["start_date"]).le(date)
            & pd.to_datetime(frame["end_date"]).ge(date)
        )
        return sorted(frame.loc[mask, "symbol"].unique().tolist())

    def market_snapshot(
        self,
        observation_date,
        symbols: str | Iterable[str] | None = None,
        minimum_quality: QualityGrade | str = QualityGrade.C,
    ) -> pd.DataFrame:
        date = self._date(observation_date)
        self._require_dataset("daily_market_state", minimum_quality)
        frame = self.store.read_parquet("daily_market_state")
        frame = frame[pd.to_datetime(frame["trade_date"]).eq(date)]
        if symbols is not None:
            frame = frame[frame["symbol"].isin(self._symbols(symbols))]
        return frame.sort_values("symbol").reset_index(drop=True)

    def valuation(
        self,
        symbols: str | Iterable[str],
        observation_date,
        fields: Iterable[str] | None = None,
        maximum_age_days: int = 10,
        minimum_quality: QualityGrade | str = QualityGrade.B,
    ) -> pd.DataFrame:
        date = self._date(observation_date)
        self._require_dataset("daily_valuation", minimum_quality)
        frame = self.store.read_parquet("daily_valuation")
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.normalize()
        frame = frame[
            frame["symbol"].isin(self._symbols(symbols)) & frame["trade_date"].le(date)
        ]
        frame = frame.sort_values("trade_date").groupby("symbol", as_index=False).tail(1)
        age = (date - frame["trade_date"]).dt.days
        frame = frame[age.le(maximum_age_days)]
        if fields is not None:
            selected = list(dict.fromkeys(fields))
            missing = set(selected).difference(frame.columns)
            if missing:
                raise CapabilityError(f"valuation fields are unavailable: {sorted(missing)}")
            frame = frame[["symbol", "trade_date", *selected]]
        return frame.sort_values("symbol").reset_index(drop=True)

    def fundamentals(
        self,
        symbols: str | Iterable[str],
        observation_date,
        fields: Iterable[str] | None = None,
        minimum_quality: QualityGrade | str = QualityGrade.B,
    ) -> pd.DataFrame:
        date = self._date(observation_date)
        self._require_dataset("fundamentals_pit", minimum_quality)
        frame = self.store.read_parquet("fundamentals_pit")
        frame["notice_date"] = pd.to_datetime(frame["notice_date"]).dt.normalize()
        frame = frame[
            frame["symbol"].isin(self._symbols(symbols)) & frame["notice_date"].le(date)
        ]
        frame = frame.sort_values(["report_date", "notice_date"]).groupby(
            "symbol", as_index=False
        ).tail(1)
        if fields is not None:
            selected = list(dict.fromkeys(fields))
            missing = set(selected).difference(frame.columns)
            if missing:
                raise CapabilityError(f"fundamental fields are unavailable: {sorted(missing)}")
            frame = frame[["symbol", "report_date", "notice_date", *selected]]
        return frame.sort_values("symbol").reset_index(drop=True)

    def industry(
        self,
        symbols: str | Iterable[str],
        observation_date,
        minimum_quality: QualityGrade | str = QualityGrade.B,
    ) -> pd.DataFrame:
        date = self._date(observation_date)
        self._require_dataset("industry_membership", minimum_quality)
        frame = self.store.read_parquet("industry_membership")
        mask = (
            frame["symbol"].isin(self._symbols(symbols))
            & pd.to_datetime(frame["start_date"]).le(date)
            & pd.to_datetime(frame["end_date"]).ge(date)
        )
        return frame.loc[mask].sort_values(["symbol", "industry_code"]).reset_index(drop=True)
