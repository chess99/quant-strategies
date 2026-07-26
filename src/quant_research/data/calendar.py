"""交易日历数据集。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .contracts import DatasetManifest, QualityGrade
from .store import ResearchDataStore, sha256_file


TRADING_CALENDAR_COLUMNS = [
    "trade_date",
    "session_index",
    "source",
    "quality_grade",
]


def read_qlib_calendar(path: Path | str) -> pd.DataFrame:
    path = Path(path).resolve()
    dates = pd.to_datetime(
        pd.Series(path.read_text(encoding="utf-8").splitlines()),
        errors="coerce",
    ).dt.normalize()
    if dates.isna().any():
        raise ValueError("trading calendar contains invalid dates")
    if dates.duplicated().any():
        raise ValueError("trading calendar dates must be unique")
    if not dates.is_monotonic_increasing:
        raise ValueError("trading calendar dates must be strictly increasing")
    return pd.DataFrame(
        {
            "trade_date": dates,
            "session_index": range(len(dates)),
            "source": "qlib-community-cn/calendars/day.txt",
            "quality_grade": QualityGrade.A.value,
        },
        columns=TRADING_CALENDAR_COLUMNS,
    )


def build_trading_calendar(
    qlib_calendar_path: Path | str,
    store: ResearchDataStore,
) -> tuple[pd.DataFrame, DatasetManifest]:
    qlib_calendar_path = Path(qlib_calendar_path).resolve()
    frame = read_qlib_calendar(qlib_calendar_path)
    data_file = store.write_parquet("trading_calendar", frame)
    manifest = DatasetManifest(
        schema_version=2,
        dataset="trading_calendar",
        provider="qlib-community-cn",
        quality_grade=QualityGrade.A,
        row_count=len(frame),
        columns=list(frame.columns),
        data_files=[data_file],
        date_range={
            "start": frame["trade_date"].min().strftime("%Y-%m-%d"),
            "end": frame["trade_date"].max().strftime("%Y-%m-%d"),
        },
        source_files=[
            {
                "path": str(qlib_calendar_path),
                "bytes": qlib_calendar_path.stat().st_size,
                "sha256": sha256_file(qlib_calendar_path),
            }
        ],
        primary_key=["trade_date"],
        date_fields={"trade_date": "交易所开放日"},
        coverage={"session_count": len(frame)},
        checks={
            "duplicate_dates": 0,
            "strictly_increasing": True,
            "invalid_dates": 0,
        },
        notes=["仅保存开放交易日；周末和休市日不生成伪记录。"],
    )
    store.write_manifest(manifest)
    return frame, manifest
