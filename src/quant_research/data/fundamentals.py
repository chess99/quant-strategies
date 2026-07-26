"""公告日约束的东方财富财务缓存导入。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .contracts import DatasetManifest, QualityGrade
from .store import ResearchDataStore, sha256_file


SOURCE_COLUMNS = [
    "symbol",
    "report_date",
    "notice_date",
    "report_type",
    "basic_eps",
    "adjusted_profit",
    "parent_net_profit",
    "revenue",
    "roe",
    "quarter_basic_eps",
    "quarter_adjusted_profit",
    "quarter_parent_net_profit",
    "quarter_revenue",
    "annual_basic_eps",
    "annual_roe",
]

FUNDAMENTAL_COLUMNS = SOURCE_COLUMNS + [
    "fiscal_year",
    "fiscal_quarter",
    "is_annual",
    "source",
    "quality_grade",
]

REPORT_QUARTERS = {"一季报": 1, "中报": 2, "三季报": 3, "年报": 4}


def normalize_financial_cache(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    missing = set(SOURCE_COLUMNS).difference(raw.columns)
    if missing:
        raise ValueError(f"financial cache is missing columns: {sorted(missing)}")
    frame = raw[SOURCE_COLUMNS].copy()
    frame["symbol"] = frame["symbol"].astype("string").str.upper()
    frame["report_date"] = pd.to_datetime(frame["report_date"], errors="coerce").dt.normalize()
    frame["notice_date"] = pd.to_datetime(frame["notice_date"], errors="coerce").dt.normalize()
    invalid_mask = (
        frame[["symbol", "report_date", "notice_date", "report_type"]].isna().any(axis=1)
        | frame["notice_date"].lt(frame["report_date"])
        | ~frame["report_type"].isin(REPORT_QUARTERS)
    )
    quarantine = frame.loc[invalid_mask].copy()
    quarantine["quarantine_reason"] = "missing_or_invalid_key_or_notice_before_report"
    frame = frame.loc[~invalid_mask].copy()
    for column in set(SOURCE_COLUMNS).difference(
        {"symbol", "report_date", "notice_date", "report_type"}
    ):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["fiscal_year"] = frame["report_date"].dt.year.astype("int16")
    frame["fiscal_quarter"] = frame["report_type"].map(REPORT_QUARTERS).astype("int8")
    frame["is_annual"] = frame["report_type"].eq("年报")
    frame["source"] = "eastmoney/datacenter-financial-cache"
    frame["quality_grade"] = QualityGrade.B.value
    frame = frame[FUNDAMENTAL_COLUMNS].sort_values(
        ["symbol", "report_date", "notice_date"]
    )
    validate_fundamentals(frame)
    return frame.reset_index(drop=True), quarantine.reset_index(drop=True)


def validate_fundamentals(frame: pd.DataFrame) -> None:
    missing = set(FUNDAMENTAL_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"fundamentals are missing columns: {sorted(missing)}")
    if frame.duplicated(["symbol", "report_date", "notice_date"]).any():
        raise ValueError("fundamentals contain duplicate point-in-time rows")
    if frame["notice_date"].lt(frame["report_date"]).any():
        raise ValueError("fundamentals contain notice dates before report dates")


def latest_fundamentals_asof(
    frame: pd.DataFrame,
    observation_date,
    symbols: list[str] | None = None,
    annual_only: bool = False,
) -> pd.DataFrame:
    date = pd.Timestamp(observation_date).normalize()
    visible = frame[pd.to_datetime(frame["notice_date"]).le(date)].copy()
    if symbols is not None:
        visible = visible[visible["symbol"].isin({symbol.upper() for symbol in symbols})]
    if annual_only:
        visible = visible[visible["is_annual"]]
    return (
        visible.sort_values(["symbol", "report_date", "notice_date"])
        .groupby("symbol", as_index=False)
        .tail(1)
        .sort_values("symbol")
        .reset_index(drop=True)
    )


def import_fundamentals(
    store: ResearchDataStore,
    financial_path: Path | str,
    metadata_path: Path | str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, DatasetManifest]:
    financial_path = Path(financial_path).resolve()
    raw = pd.read_parquet(financial_path)
    data, quarantine = normalize_financial_cache(raw)
    data_file = store.write_parquet("fundamentals_pit", data)
    quarantine_file = store.write_quarantine_parquet("fundamentals_pit", quarantine)
    source_files = [
        {
            "path": str(financial_path),
            "bytes": financial_path.stat().st_size,
            "sha256": sha256_file(financial_path),
        }
    ]
    notes = [
        "以 notice_date 控制点时可见性，不以报告期替代公告日。",
        "历史修订值可能被数据商回填，故质量为 B 而不是 A。",
        f"隔离公告日早于报告期或关键字段异常的记录 {len(quarantine)} 条。",
        f"隔离文件：{quarantine_file['path']}。",
    ]
    if metadata_path is not None:
        metadata_path = Path(metadata_path).resolve()
        source_files.append(
            {
                "path": str(metadata_path),
                "bytes": metadata_path.stat().st_size,
                "sha256": sha256_file(metadata_path),
            }
        )
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        notes.append(f"上游元数据来源：{metadata.get('source', 'unknown')}。")
    manifest = DatasetManifest(
        schema_version=1,
        dataset="fundamentals_pit",
        provider="eastmoney/datacenter-financial-cache",
        quality_grade=QualityGrade.B,
        row_count=len(data),
        columns=list(data.columns),
        data_files=[data_file],
        date_range={
            "start": data["notice_date"].min().strftime("%Y-%m-%d"),
            "end": data["notice_date"].max().strftime("%Y-%m-%d"),
        },
        source_files=source_files,
        notes=notes,
    )
    store.write_manifest(manifest)
    return data, quarantine, manifest
