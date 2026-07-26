"""当前行业分类代理导入；禁止回填历史。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from .contracts import DatasetManifest, QualityGrade
from .store import ResearchDataStore, sha256_file


INDUSTRY_COLUMNS = [
    "symbol",
    "industry_code",
    "industry_name",
    "classification",
    "start_date",
    "end_date",
    "observed_date",
    "source",
    "quality_grade",
]


def _stable_industry_code(name: str) -> str:
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]
    return f"eastmoney-current-{digest}"


def normalize_current_industry(raw: pd.DataFrame, observed_date) -> pd.DataFrame:
    required = {"symbol", "industry"}
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"industry snapshot is missing columns: {sorted(missing)}")
    date = pd.Timestamp(observed_date).normalize()
    frame = raw.copy()
    frame["symbol"] = frame["symbol"].astype("string").str.upper()
    frame["industry_name"] = frame["industry"].astype("string").str.strip()
    frame = frame.dropna(subset=["symbol", "industry_name"])
    frame = frame[frame["industry_name"].ne("")]
    frame["industry_code"] = frame["industry_name"].map(_stable_industry_code)
    frame["classification"] = "eastmoney-current-proxy"
    frame["start_date"] = date
    frame["end_date"] = pd.Timestamp("2099-12-31")
    frame["observed_date"] = date
    frame["source"] = "eastmoney/current-industry-cache"
    frame["quality_grade"] = QualityGrade.C.value
    result = frame[INDUSTRY_COLUMNS].sort_values(["symbol", "industry_code"])
    validate_industry(result)
    return result.reset_index(drop=True)


def validate_industry(frame: pd.DataFrame) -> None:
    missing = set(INDUSTRY_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"industry membership is missing columns: {sorted(missing)}")
    if frame.duplicated(["symbol", "industry_code", "start_date"]).any():
        raise ValueError("industry membership contains duplicate snapshot rows")
    if (frame["start_date"] > frame["end_date"]).any():
        raise ValueError("industry membership contains inverted intervals")


def import_current_industry(
    store: ResearchDataStore,
    industry_path: Path | str,
    metadata_path: Path | str,
) -> tuple[pd.DataFrame, DatasetManifest]:
    industry_path = Path(industry_path).resolve()
    metadata_path = Path(metadata_path).resolve()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    observed_date = pd.Timestamp(metadata["created_at"]).tz_convert("Asia/Shanghai").normalize().tz_localize(None)
    raw = pd.read_csv(industry_path)
    data = normalize_current_industry(raw, observed_date)
    data_file = store.write_parquet("industry_membership", data)
    manifest = DatasetManifest(
        schema_version=1,
        dataset="industry_membership",
        provider="eastmoney/current-industry-cache",
        quality_grade=QualityGrade.C,
        row_count=len(data),
        columns=list(data.columns),
        data_files=[data_file],
        date_range={"start": observed_date.strftime("%Y-%m-%d"), "end": None},
        source_files=[
            {
                "path": str(industry_path),
                "bytes": industry_path.stat().st_size,
                "sha256": sha256_file(industry_path),
            },
            {
                "path": str(metadata_path),
                "bytes": metadata_path.stat().st_size,
                "sha256": sha256_file(metadata_path),
            },
        ],
        notes=[
            "仅为抓取日可见的当前行业分类代理，质量 C。",
            "有效区间从 observed_date 开始，绝不回填到历史观察日。",
            "要求 B 级历史行业的策略必须拒绝运行。",
        ],
    )
    store.write_manifest(manifest)
    return data, manifest
