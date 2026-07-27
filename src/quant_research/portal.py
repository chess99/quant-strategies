"""本地日频研究统一数据入口。"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Iterable, Protocol

import pandas as pd

from .data.contracts import QualityGrade
from .data.store import ResearchDataStore, sha256_file


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
    last_provenance: dict | None = dataclass_field(default=None, init=False)

    def _build_provenance(self) -> dict:
        root = Path(self.provider_uri).resolve()
        source_files = []
        for relative in (Path("calendars/day.txt"), Path("instruments/all.txt")):
            path = root / relative
            if path.is_file():
                source_files.append(
                    {"path": str(path), "sha256": sha256_file(path)}
                )
        identities = "\n".join(
            f"{item['path']}={item['sha256']}" for item in source_files
        )
        return {
            "dataset": "qlib_daily_bars",
            "provider": "qlib-community-cn",
            "provider_uri": str(root),
            "quality_grade": self.quality_grade.value,
            "data_version": (
                hashlib.sha256(identities.encode("utf-8")).hexdigest()
                if identities
                else None
            ),
            "source_files": source_files,
        }

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

        result = pd.DatetimeIndex(
            D.calendar(start_date, end_date, freq="day")
        ).normalize()
        self.last_provenance = self._build_provenance()
        return result

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
        self.last_provenance = self._build_provenance()
        return frame[["symbol", "trade_date", *fields]].copy()


@dataclass
class PartitionedDailyBarSource:
    """读取按证券分区的规范化日线，例如 ``etf_daily``。"""

    store: ResearchDataStore
    dataset: str
    last_provenance: dict | None = dataclass_field(default=None, init=False)

    @property
    def quality_grade(self) -> QualityGrade:
        return QualityGrade(self.store.read_manifest(self.dataset)["quality_grade"])

    def calendar(self, start_date, end_date) -> pd.DatetimeIndex:
        manifest = self.store.read_manifest(self.dataset)
        manifest_path = self.store.manifest_path(self.dataset)
        self.last_provenance = {
            "dataset": self.dataset,
            "provider": manifest.get("provider"),
            "quality_grade": manifest.get("quality_grade"),
            "manifest_path": str(manifest_path),
            "manifest_sha256": sha256_file(manifest_path),
        }
        calendar = self.store.read_parquet("trading_calendar")
        dates = pd.to_datetime(calendar["trade_date"]).dt.normalize()
        return pd.DatetimeIndex(
            dates[dates.between(pd.Timestamp(start_date), pd.Timestamp(end_date))]
        )

    def load(self, symbols, start_date, end_date, fields, adjustment):
        if adjustment not in {"raw", "pre"}:
            raise CapabilityError(f"unsupported adjustment: {adjustment}")
        manifest = self.store.read_manifest(self.dataset)
        manifest_path = self.store.manifest_path(self.dataset)
        self.last_provenance = {
            "dataset": self.dataset,
            "provider": manifest.get("provider"),
            "quality_grade": manifest.get("quality_grade"),
            "manifest_path": str(manifest_path),
            "manifest_sha256": sha256_file(manifest_path),
        }
        requested = set(symbols)
        artifacts = [
            item
            for item in manifest.get("data_files", [])
            if (item.get("partition_values") or {}).get("symbol") in requested
        ]
        source_fields = {}
        for field in fields:
            if field == "money":
                source_fields[field] = "amount"
            elif adjustment == "pre" and field in {"open", "high", "low", "close"}:
                source_fields[field] = f"adjusted_{field}"
            else:
                source_fields[field] = field
        missing = set(source_fields.values()).difference(manifest.get("columns", []))
        if missing:
            raise CapabilityError(f"{self.dataset} fields are unavailable: {sorted(missing)}")
        frames = []
        columns = ["symbol", "trade_date", *dict.fromkeys(source_fields.values())]
        for artifact in artifacts:
            frames.append(
                pd.read_parquet(
                    self.store.root / artifact["path"],
                    columns=columns,
                    filters=[
                        ("trade_date", ">=", pd.Timestamp(start_date)),
                        ("trade_date", "<=", pd.Timestamp(end_date)),
                    ],
                )
            )
        if not frames:
            return pd.DataFrame(columns=["symbol", "trade_date", *fields])
        frame = pd.concat(frames, ignore_index=True)
        for target, source in source_fields.items():
            if target != source:
                frame[target] = frame[source]
        return frame[["symbol", "trade_date", *fields]].copy()


@dataclass
class CompositeDailyBarSource:
    """按证券类型把统一 ``bars`` 查询路由到不同事实源。"""

    store: ResearchDataStore
    default: DailyBarSource
    by_asset_type: dict[str, DailyBarSource]
    last_provenance: dict | None = dataclass_field(default=None, init=False)

    @property
    def quality_grade(self) -> QualityGrade:
        return QualityGrade.worst(
            [self.default.quality_grade, *[source.quality_grade for source in self.by_asset_type.values()]]
        )

    def calendar(self, start_date, end_date) -> pd.DatetimeIndex:
        result = self.default.calendar(start_date, end_date)
        source = getattr(self.default, "last_provenance", None) or {
            "dataset": "daily_bars",
            "provider": type(self.default).__name__,
            "quality_grade": self.default.quality_grade.value,
        }
        self.last_provenance = {
            "dataset": "composite_daily_bars",
            "provider": type(self).__name__,
            "quality_grade": self.quality_grade.value,
            "sources": [source],
        }
        return result

    def load(self, symbols, start_date, end_date, fields, adjustment):
        master = self.store.read_parquet("security_master").set_index("symbol")
        grouped: dict[int, tuple[DailyBarSource, list[str]]] = {}
        for symbol in symbols:
            asset_type = master.loc[symbol, "asset_type"] if symbol in master.index else None
            source = self.by_asset_type.get(str(asset_type), self.default)
            key = id(source)
            grouped.setdefault(key, (source, []))[1].append(symbol)
        frames = []
        sources = []
        for source, group_symbols in grouped.values():
            frames.append(source.load(group_symbols, start_date, end_date, fields, adjustment))
            sources.append(
                getattr(source, "last_provenance", None)
                or {
                    "dataset": "qlib_daily_bars",
                    "provider": type(source).__name__,
                    "quality_grade": source.quality_grade.value,
                }
            )
        self.last_provenance = {
            "dataset": "composite_daily_bars",
            "provider": type(self).__name__,
            "quality_grade": self.quality_grade.value,
            "sources": sources,
        }
        frames = [frame for frame in frames if not frame.empty]
        if not frames:
            return pd.DataFrame(columns=["symbol", "trade_date", *fields])
        return pd.concat(frames, ignore_index=True)


class LocalDataPortal:
    """显式观察日、显式质量门槛的本地统一数据接口。"""

    def __init__(self, store: ResearchDataStore, daily_bars: DailyBarSource):
        self.store = store
        self.daily_bars = daily_bars
        self.last_query_provenance: dict | None = None

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

    def _record_provenance(self, dataset: str, manifest: dict, result=None) -> dict:
        path = self.store.manifest_path(dataset)
        provenance = {
            "dataset": dataset,
            "provider": manifest.get("provider"),
            "quality_grade": manifest.get("quality_grade"),
            "created_at": manifest.get("created_at"),
            "date_range": manifest.get("date_range"),
            "manifest_path": str(path),
            "manifest_sha256": sha256_file(path),
        }
        self.last_query_provenance = provenance
        if isinstance(result, pd.DataFrame):
            result.attrs["quant_research_provenance"] = provenance.copy()
        return provenance

    def _bar_provenance(self, provenance: dict) -> dict:
        """绑定行情源版本，并附上最近一次全平台数据审计清单。"""

        result = copy.deepcopy(provenance)
        audit_path = self.store.manifest_path("platform_coverage")
        if audit_path.is_file():
            result["platform_audit"] = {
                "path": str(audit_path),
                "sha256": sha256_file(audit_path),
            }
        return result

    def _read_dataset(self, dataset: str, manifest: dict, symbols=None, filters=None):
        partitioning = manifest.get("partitioning") or {}
        if partitioning.get("columns") == ["symbol"] and symbols is not None:
            requested = set(symbols)
            frames = []
            for artifact in manifest.get("data_files", []):
                partition_values = artifact.get("partition_values") or {}
                if partition_values.get("symbol") not in requested:
                    continue
                frames.append(
                    pd.read_parquet(
                        self.store.root / artifact["path"],
                        filters=filters,
                    )
                )
            if not frames:
                return pd.DataFrame(columns=manifest.get("columns", []))
            return pd.concat(frames, ignore_index=True)
        return self.store.read_parquet(dataset)

    def calendar(self, start_date, end_date) -> pd.DatetimeIndex:
        start = self._date(start_date, "start_date")
        end = self._date(end_date, "end_date")
        if end < start:
            raise ValueError("end_date must not be earlier than start_date")
        result = self.daily_bars.calendar(start, end)
        source = getattr(self.daily_bars, "last_provenance", None) or {
            "dataset": "daily_bars",
            "provider": type(self.daily_bars).__name__,
            "quality_grade": self.daily_bars.quality_grade.value,
        }
        self.last_query_provenance = self._bar_provenance(source)
        return result

    def instruments(
        self,
        observation_date,
        asset_types: Iterable[str] | None = None,
        minimum_quality: QualityGrade | str = QualityGrade.B,
    ) -> pd.DataFrame:
        date = self._date(observation_date)
        manifest = self._require_dataset("security_master", minimum_quality)
        frame = self.store.read_parquet("security_master")
        mask = pd.to_datetime(frame["start_date"]).le(date) & pd.to_datetime(
            frame["end_date"]
        ).ge(date)
        if asset_types is not None:
            mask &= frame["asset_type"].isin(set(asset_types))
        result = frame.loc[mask].sort_values("symbol").reset_index(drop=True)
        self._record_provenance("security_master", manifest, result)
        return result

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
        result = frame.sort_values(["trade_date", "symbol"]).reset_index(drop=True)
        provenance = getattr(self.daily_bars, "last_provenance", None) or {
            "dataset": "daily_bars",
            "provider": type(self.daily_bars).__name__,
            "quality_grade": self.daily_bars.quality_grade.value,
            "adjustment": adjustment,
        }
        provenance = self._bar_provenance(provenance)
        self.last_query_provenance = provenance
        result.attrs["quant_research_provenance"] = copy.deepcopy(provenance)
        return result

    def index_members(
        self,
        index_symbol: str,
        observation_date,
        minimum_quality: QualityGrade | str = QualityGrade.B,
    ) -> list[str]:
        date = self._date(observation_date)
        manifest = self._require_dataset("index_membership", minimum_quality)
        frame = self.store.read_parquet("index_membership")
        mask = (
            frame["index_symbol"].eq(index_symbol.upper())
            & pd.to_datetime(frame["start_date"]).le(date)
            & pd.to_datetime(frame["end_date"]).ge(date)
        )
        result = sorted(frame.loc[mask, "symbol"].unique().tolist())
        self._record_provenance("index_membership", manifest)
        return result

    def market_snapshot(
        self,
        observation_date,
        symbols: str | Iterable[str] | None = None,
        minimum_quality: QualityGrade | str = QualityGrade.C,
    ) -> pd.DataFrame:
        date = self._date(observation_date)
        manifest = self._require_dataset("daily_market_state", minimum_quality)
        selected = (
            self._symbols(symbols)
            if symbols is not None
            else self.instruments(date, asset_types=["stock"])["symbol"].tolist()
        )
        frame = self._read_dataset(
            "daily_market_state",
            manifest,
            selected,
            filters=[("trade_date", "==", date)],
        )
        if not frame.empty:
            frame = frame[pd.to_datetime(frame["trade_date"]).eq(date)]
        result = frame.sort_values("symbol").reset_index(drop=True)
        self._record_provenance("daily_market_state", manifest, result)
        return result

    snapshot = market_snapshot

    def valuation(
        self,
        symbols: str | Iterable[str],
        observation_date,
        fields: Iterable[str] | None = None,
        maximum_age_days: int = 10,
        minimum_quality: QualityGrade | str = QualityGrade.B,
    ) -> pd.DataFrame:
        date = self._date(observation_date)
        manifest = self._require_dataset("daily_valuation", minimum_quality)
        selected_symbols = self._symbols(symbols)
        frame = self._read_dataset("daily_valuation", manifest, selected_symbols)
        frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.normalize()
        frame = frame[
            frame["symbol"].isin(selected_symbols) & frame["trade_date"].le(date)
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
        result = frame.sort_values("symbol").reset_index(drop=True)
        self._record_provenance("daily_valuation", manifest, result)
        return result

    def fundamentals(
        self,
        symbols: str | Iterable[str],
        observation_date,
        fields: Iterable[str] | None = None,
        minimum_quality: QualityGrade | str = QualityGrade.B,
    ) -> pd.DataFrame:
        date = self._date(observation_date)
        manifest = self._require_dataset("fundamentals_pit", minimum_quality)
        selected_symbols = self._symbols(symbols)
        frame = self._read_dataset("fundamentals_pit", manifest, selected_symbols)
        frame["notice_date"] = pd.to_datetime(frame["notice_date"]).dt.normalize()
        frame = frame[
            frame["symbol"].isin(selected_symbols) & frame["notice_date"].le(date)
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
        result = frame.sort_values("symbol").reset_index(drop=True)
        self._record_provenance("fundamentals_pit", manifest, result)
        return result

    def industry(
        self,
        symbols: str | Iterable[str],
        observation_date,
        minimum_quality: QualityGrade | str = QualityGrade.B,
    ) -> pd.DataFrame:
        date = self._date(observation_date)
        manifest = self._require_dataset("industry_membership", minimum_quality)
        selected_symbols = self._symbols(symbols)
        frame = self._read_dataset("industry_membership", manifest, selected_symbols)
        mask = (
            frame["symbol"].isin(selected_symbols)
            & pd.to_datetime(frame["start_date"]).le(date)
            & pd.to_datetime(frame["end_date"]).ge(date)
        )
        result = frame.loc[mask].sort_values(["symbol", "industry_code"]).reset_index(drop=True)
        self._record_provenance("industry_membership", manifest, result)
        return result
