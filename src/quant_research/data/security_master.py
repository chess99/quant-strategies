"""从 Qlib 历史证券区间构建本地证券主表。"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .contracts import AssetType, DatasetManifest, QualityGrade
from .security_lifecycle import (
    SecurityLifecycleSnapshot,
    enrich_security_lifecycle,
)
from .store import ResearchDataStore, sha256_file


KNOWN_INDEXES = {"SH000300", "SH000905", "SZ399300"}
INTERNAL_SYMBOL = re.compile(r"^(SH|SZ|BJ)\d{6}$")
JOINQUANT_SUFFIXES = {
    "XSHG": "SH",
    "XSHE": "SZ",
    "XBSE": "BJ",
}
SECURITY_MASTER_COLUMNS = [
    "symbol",
    "exchange",
    "asset_type",
    "board",
    "start_date",
    "end_date",
    "listing_date",
    "delisting_date",
    "active_at_source_end",
    "canonical_symbol",
    "lifecycle_status",
    "lifecycle_quality",
    "lifecycle_source",
    "display_name",
    "quality_grade",
    "source",
]


def normalize_symbol(symbol: str) -> str:
    text = str(symbol).strip().upper()
    if INTERNAL_SYMBOL.fullmatch(text):
        return text
    if "." in text:
        code, suffix = text.split(".", maxsplit=1)
        prefix = JOINQUANT_SUFFIXES.get(suffix)
        if prefix and code.isdigit() and len(code) == 6:
            return f"{prefix}{code}"
    raise ValueError(f"unsupported security symbol: {symbol!r}")


def to_joinquant_symbol(symbol: str) -> str:
    normalized = normalize_symbol(symbol)
    exchange = exchange_for(normalized)
    return f"{normalized[2:]}.{exchange}"


def exchange_for(symbol: str) -> str:
    prefix = symbol[:2].upper()
    return {"SH": "XSHG", "SZ": "XSHE", "BJ": "XBSE"}.get(prefix, "UNKNOWN")


def board_for(symbol: str, asset_type: AssetType) -> str:
    code = symbol[2:]
    if asset_type is not AssetType.STOCK:
        return asset_type.value
    if symbol.startswith("BJ"):
        return "beijing"
    if code.startswith("688"):
        return "star"
    if code.startswith(("300", "301")):
        return "chinext"
    return "main"


def infer_asset_type(symbol: str) -> AssetType:
    if (
        symbol.upper() in KNOWN_INDEXES
        or symbol.startswith("SH000")
        or symbol.startswith("SZ399")
    ):
        return AssetType.INDEX
    return AssetType.STOCK


def read_qlib_instruments(path: Path | str) -> pd.DataFrame:
    path = Path(path).resolve()
    frame = pd.read_csv(
        path,
        sep="\t",
        names=["symbol", "start_date", "end_date"],
        dtype={"symbol": "string"},
    )
    frame["symbol"] = frame["symbol"].str.upper()
    frame["start_date"] = pd.to_datetime(frame["start_date"]).dt.normalize()
    frame["end_date"] = pd.to_datetime(frame["end_date"]).dt.normalize()
    source_end = frame["end_date"].max()
    records = []
    for row in frame.itertuples(index=False):
        asset_type = infer_asset_type(row.symbol)
        records.append(
            {
                "symbol": row.symbol,
                "exchange": exchange_for(row.symbol),
                "asset_type": asset_type.value,
                "board": board_for(row.symbol, asset_type),
                "start_date": row.start_date,
                "end_date": row.end_date,
                "listing_date": row.start_date,
                "delisting_date": (
                    pd.NaT
                    if asset_type is AssetType.INDEX or row.end_date == source_end
                    else row.end_date
                ),
                "active_at_source_end": bool(
                    asset_type is AssetType.INDEX or row.end_date == source_end
                ),
                "canonical_symbol": row.symbol,
                "lifecycle_status": (
                    "active"
                    if asset_type is AssetType.INDEX or row.end_date == source_end
                    else "qlib_interval_ended"
                ),
                "lifecycle_quality": (
                    QualityGrade.B.value
                    if asset_type is AssetType.INDEX
                    else QualityGrade.C.value
                ),
                "lifecycle_source": "qlib-community-cn/all.txt",
                "display_name": None,
                "quality_grade": QualityGrade.B.value,
                "source": "qlib-community-cn/all.txt",
            }
        )
    result = pd.DataFrame(records, columns=SECURITY_MASTER_COLUMNS)
    validate_security_master(result)
    return result.sort_values("symbol").reset_index(drop=True)


def validate_security_master(frame: pd.DataFrame) -> None:
    missing = set(SECURITY_MASTER_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"security master is missing columns: {sorted(missing)}")
    if frame["symbol"].isna().any() or frame["symbol"].duplicated().any():
        raise ValueError("security master symbols must be present and unique")
    invalid_symbols = [
        symbol
        for symbol in frame["symbol"].astype(str)
        if not INTERNAL_SYMBOL.fullmatch(symbol)
    ]
    if invalid_symbols:
        raise ValueError(
            f"security master contains invalid symbols: {invalid_symbols[:10]}"
        )
    invalid_canonical = [
        symbol
        for symbol in frame["canonical_symbol"].astype(str)
        if not INTERNAL_SYMBOL.fullmatch(symbol)
    ]
    if invalid_canonical:
        raise ValueError(
            "security master contains invalid canonical symbols: "
            f"{invalid_canonical[:10]}"
        )
    if (pd.to_datetime(frame["start_date"]) > pd.to_datetime(frame["end_date"])).any():
        raise ValueError("security master contains start_date later than end_date")
    if (
        pd.to_datetime(frame["listing_date"], errors="coerce")
        > pd.to_datetime(frame["end_date"])
    ).any():
        raise ValueError("security master listing_date cannot be later than end_date")
    active = frame["active_at_source_end"].fillna(False).astype(bool)
    if pd.to_datetime(frame.loc[active, "delisting_date"]).notna().any():
        raise ValueError("active securities cannot have delisting_date")
    inactive_delisting = pd.to_datetime(
        frame.loc[~active, "delisting_date"], errors="coerce"
    )
    if inactive_delisting.isna().any():
        raise ValueError("inactive securities must have delisting_date")
    invalid_types = set(frame["asset_type"]).difference(item.value for item in AssetType)
    if invalid_types:
        raise ValueError(f"security master contains invalid asset types: {invalid_types}")
    invalid_grades = set(frame["quality_grade"]).difference(item.value for item in QualityGrade)
    if invalid_grades:
        raise ValueError(f"security master contains invalid quality grades: {invalid_grades}")
    invalid_lifecycle_grades = set(frame["lifecycle_quality"]).difference(
        item.value for item in QualityGrade
    )
    if invalid_lifecycle_grades:
        raise ValueError(
            "security master contains invalid lifecycle quality grades: "
            f"{invalid_lifecycle_grades}"
        )


def build_security_master(
    qlib_all_path: Path | str,
    store: ResearchDataStore,
    supplemental: pd.DataFrame | None = None,
    supplemental_sources: list[dict] | None = None,
    lifecycle_snapshot: SecurityLifecycleSnapshot | None = None,
) -> tuple[pd.DataFrame, DatasetManifest]:
    qlib_all_path = Path(qlib_all_path).resolve()
    frame = read_qlib_instruments(qlib_all_path)
    if lifecycle_snapshot is not None:
        frame = enrich_security_lifecycle(frame, lifecycle_snapshot)
        supplemental_sources = list(supplemental_sources or [])
        supplemental_sources.extend(lifecycle_snapshot.source_files)
    if supplemental is not None and not supplemental.empty:
        supplemental = supplemental.copy()
        if "listing_date" not in supplemental:
            supplemental["listing_date"] = supplemental["start_date"]
        if "active_at_source_end" not in supplemental:
            supplemental_end = pd.to_datetime(supplemental["end_date"]).max()
            supplemental["active_at_source_end"] = (
                pd.to_datetime(supplemental["end_date"]) == supplemental_end
            )
        if "delisting_date" not in supplemental:
            supplemental["delisting_date"] = pd.to_datetime(
                supplemental["end_date"]
            ).where(~supplemental["active_at_source_end"], pd.NaT)
        if "canonical_symbol" not in supplemental:
            supplemental["canonical_symbol"] = supplemental["symbol"]
        if "lifecycle_status" not in supplemental:
            supplemental["lifecycle_status"] = "active"
        if "lifecycle_quality" not in supplemental:
            supplemental["lifecycle_quality"] = QualityGrade.B.value
        if "lifecycle_source" not in supplemental:
            supplemental["lifecycle_source"] = supplemental["source"]
        supplemental = supplemental[SECURITY_MASTER_COLUMNS].copy()
        supplemental["symbol"] = supplemental["symbol"].map(normalize_symbol)
        supplemental = supplemental[~supplemental["symbol"].isin(frame["symbol"])]
        frame = pd.concat([frame, supplemental], ignore_index=True)
        frame = frame.sort_values("symbol").reset_index(drop=True)
        validate_security_master(frame)
    data_file = store.write_parquet("security_master", frame)
    counts = {
        str(key): int(value)
        for key, value in frame["asset_type"].value_counts().sort_index().items()
    }
    overall_quality = QualityGrade.worst(frame["quality_grade"])
    lifecycle_counts = {
        str(key): int(value)
        for key, value in frame["lifecycle_status"].value_counts().sort_index().items()
    }
    manifest = DatasetManifest(
        schema_version=2,
        dataset="security_master",
        provider=(
            "qlib-community-cn"
            + (" + akshare/exchange-lists" if lifecycle_snapshot is not None else "")
            + (
                " + supplemental point-in-time masters"
                if supplemental is not None and not supplemental.empty
                else ""
            )
        ),
        quality_grade=overall_quality,
        row_count=len(frame),
        columns=list(frame.columns),
        data_files=[data_file],
        date_range={
            "start": frame["start_date"].min().strftime("%Y-%m-%d"),
            "end": frame["end_date"].max().strftime("%Y-%m-%d"),
        },
        source_files=[
            {
                "path": str(qlib_all_path),
                "bytes": qlib_all_path.stat().st_size,
                "sha256": sha256_file(qlib_all_path),
            }
        ]
        + list(supplemental_sources or []),
        primary_key=["symbol"],
        date_fields={
            "start_date": "证券有效区间起点（闭区间）",
            "end_date": "来源快照内最后覆盖日期（闭区间）",
            "listing_date": "上市日期",
            "delisting_date": "退市日期；来源期末仍有效时为空",
        },
        coverage={
            "asset_type_counts": counts,
            "qlib_instrument_count": int(
                frame["source"].astype(str).str.contains("qlib", case=False).sum()
            ),
            "active_at_source_end": int(frame["active_at_source_end"].sum()),
            "ended_before_source_end": int((~frame["active_at_source_end"]).sum()),
            "lifecycle_status_counts": lifecycle_counts,
            "lifecycle_quality_counts": {
                str(key): int(value)
                for key, value in frame["lifecycle_quality"]
                .value_counts()
                .sort_index()
                .items()
            },
            "lifecycle_snapshot_as_of": (
                lifecycle_snapshot.as_of if lifecycle_snapshot is not None else None
            ),
        },
        checks={
            "duplicate_symbols": int(frame["symbol"].duplicated().sum()),
            "time_inversions": int(
                (
                    pd.to_datetime(frame["start_date"])
                    > pd.to_datetime(frame["end_date"])
                ).sum()
            ),
            "unknown_exchanges": int((frame["exchange"] == "UNKNOWN").sum()),
            "invalid_symbols": 0,
            "unverified_lifecycle_rows": int(
                (frame["lifecycle_quality"] == QualityGrade.C.value).sum()
            ),
        },
        notes=[
            "证券有效区间来自 Qlib 社区中国日线包。",
            "证券类型和板块由代码规则推导，因此整体质量为 B。",
            "ETF 与基金补充记录必须来自各自点时主表或日线事实，不从当前列表回填历史。",
        ],
    )
    store.write_manifest(manifest)
    return frame, manifest
