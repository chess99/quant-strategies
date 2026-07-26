"""从 Qlib 历史证券区间构建本地证券主表。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .contracts import AssetType, DatasetManifest, QualityGrade
from .store import ResearchDataStore, sha256_file


KNOWN_INDEXES = {"SH000300", "SH000905", "SZ399300"}
SECURITY_MASTER_COLUMNS = [
    "symbol",
    "exchange",
    "asset_type",
    "board",
    "start_date",
    "end_date",
    "display_name",
    "quality_grade",
    "source",
]


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
    if symbol.upper() in KNOWN_INDEXES or symbol[2:].startswith("399"):
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
    if (pd.to_datetime(frame["start_date"]) > pd.to_datetime(frame["end_date"])).any():
        raise ValueError("security master contains start_date later than end_date")
    invalid_types = set(frame["asset_type"]).difference(item.value for item in AssetType)
    if invalid_types:
        raise ValueError(f"security master contains invalid asset types: {invalid_types}")
    invalid_grades = set(frame["quality_grade"]).difference(item.value for item in QualityGrade)
    if invalid_grades:
        raise ValueError(f"security master contains invalid quality grades: {invalid_grades}")


def build_security_master(
    qlib_all_path: Path | str,
    store: ResearchDataStore,
) -> tuple[pd.DataFrame, DatasetManifest]:
    qlib_all_path = Path(qlib_all_path).resolve()
    frame = read_qlib_instruments(qlib_all_path)
    data_file = store.write_parquet("security_master", frame)
    manifest = DatasetManifest(
        schema_version=1,
        dataset="security_master",
        provider="qlib-community-cn",
        quality_grade=QualityGrade.B,
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
        ],
        notes=[
            "证券有效区间来自 Qlib 社区中国日线包。",
            "证券类型和板块由代码规则推导，因此整体质量为 B。",
            "ETF 将在独立数据接入迭代中合并。",
        ],
    )
    store.write_manifest(manifest)
    return frame, manifest
