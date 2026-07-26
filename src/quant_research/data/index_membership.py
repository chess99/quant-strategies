"""从 Qlib 历史成分区间构建指数成分数据集。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .contracts import DatasetManifest, QualityGrade
from .store import ResearchDataStore, sha256_file


DEFAULT_INDEX_FILES = {
    "SH000300": "csi300.txt",
    "SH000905": "csi500.txt",
    "SH000852": "csi1000.txt",
    "SH000906": "csi800.txt",
    "SH000985": "csiall.txt",
}

INDEX_MEMBERSHIP_COLUMNS = [
    "index_symbol",
    "symbol",
    "start_date",
    "end_date",
    "source",
    "quality_grade",
]


def read_qlib_index_membership(index_symbol: str, path: Path | str) -> pd.DataFrame:
    path = Path(path).resolve()
    frame = pd.read_csv(
        path,
        sep="\t",
        names=["symbol", "start_date", "end_date"],
        dtype={"symbol": "string"},
    )
    frame["index_symbol"] = index_symbol.upper()
    frame["symbol"] = frame["symbol"].str.upper()
    frame["start_date"] = pd.to_datetime(frame["start_date"]).dt.normalize()
    frame["end_date"] = pd.to_datetime(frame["end_date"]).dt.normalize()
    frame["source"] = f"qlib-community-cn/{path.name}"
    frame["quality_grade"] = QualityGrade.B.value
    result = frame[INDEX_MEMBERSHIP_COLUMNS].sort_values(
        ["index_symbol", "symbol", "start_date"]
    )
    validate_index_membership(result)
    return result.reset_index(drop=True)


def validate_index_membership(frame: pd.DataFrame) -> None:
    missing = set(INDEX_MEMBERSHIP_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"index membership is missing columns: {sorted(missing)}")
    if frame.duplicated(["index_symbol", "symbol", "start_date", "end_date"]).any():
        raise ValueError("index membership contains duplicate intervals")
    if (frame["start_date"] > frame["end_date"]).any():
        raise ValueError("index membership contains inverted intervals")


def build_index_membership(
    qlib_instruments_dir: Path | str,
    store: ResearchDataStore,
    index_files: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, DatasetManifest]:
    directory = Path(qlib_instruments_dir).resolve()
    index_files = index_files or DEFAULT_INDEX_FILES
    frames = []
    source_files = []
    for index_symbol, filename in index_files.items():
        path = directory / filename
        frames.append(read_qlib_index_membership(index_symbol, path))
        source_files.append(
            {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    data = pd.concat(frames, ignore_index=True).sort_values(
        ["index_symbol", "symbol", "start_date"]
    )
    data_file = store.write_parquet("index_membership", data)
    manifest = DatasetManifest(
        schema_version=1,
        dataset="index_membership",
        provider="qlib-community-cn",
        quality_grade=QualityGrade.B,
        row_count=len(data),
        columns=list(data.columns),
        data_files=[data_file],
        date_range={
            "start": data["start_date"].min().strftime("%Y-%m-%d"),
            "end": data["end_date"].max().strftime("%Y-%m-%d"),
        },
        source_files=source_files,
        notes=[
            "成分区间直接来自 Qlib 社区中国日线包，不使用当前成分回填历史。",
            "免费数据未与指数公司逐次公告交叉核验，质量等级为 B。",
        ],
    )
    store.write_manifest(manifest)
    return data.reset_index(drop=True), manifest
