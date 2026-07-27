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

SHENWAN_COLUMN_ALIASES = {
    "股票代码": "stock_code",
    "计入日期": "included_date",
    "行业代码": "industry_code",
    "更新日期": "updated_at",
    "symbol": "stock_code",
    "start_date": "included_date",
    "update_time": "updated_at",
}


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
    ordered = frame.sort_values(["symbol", "classification", "start_date"])
    prior_end = ordered.groupby(["symbol", "classification"])["end_date"].shift()
    if prior_end.notna().any() and (
        ordered.loc[prior_end.notna(), "start_date"]
        <= prior_end.loc[prior_end.notna()]
    ).any():
        raise ValueError("industry membership contains overlapping intervals")


def _coalesce_industry_intervals(frame: pd.DataFrame) -> pd.DataFrame:
    records = []
    for _, group in frame.groupby(["symbol", "classification"], sort=True):
        previous = None
        for row in group.sort_values("start_date").to_dict("records"):
            if previous is not None and previous["industry_code"] == row["industry_code"]:
                previous["end_date"] = row["end_date"]
                previous["observed_date"] = max(
                    previous["observed_date"], row["observed_date"]
                )
                continue
            if previous is not None:
                records.append(previous)
            previous = row
        if previous is not None:
            records.append(previous)
    return pd.DataFrame(records, columns=INDUSTRY_COLUMNS)


def normalize_shenwan_history(
    raw: pd.DataFrame,
    security_master: pd.DataFrame,
    *,
    industry_names: dict[str, str] | None = None,
) -> pd.DataFrame:
    """把申万官方三级变更记录规范化为一级、二级点时有效区间。"""

    frame = raw.rename(columns=SHENWAN_COLUMN_ALIASES).copy()
    required = {"stock_code", "included_date", "industry_code", "updated_at"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Shenwan history is missing columns: {sorted(missing)}")
    master_required = {"symbol", "listing_date", "delisting_date"}
    master_missing = master_required.difference(security_master.columns)
    if master_missing:
        raise ValueError(f"security master is missing columns: {sorted(master_missing)}")
    industry_names = industry_names or {}
    frame["stock_code"] = (
        frame["stock_code"].astype("string").str.extract(r"(\d{6})", expand=False)
    )
    frame["industry_code"] = (
        frame["industry_code"].astype("string").str.extract(r"(\d{6})", expand=False)
    )
    frame["included_date"] = pd.to_datetime(
        frame["included_date"], errors="coerce"
    ).dt.normalize()
    frame["updated_at"] = pd.to_datetime(frame["updated_at"], errors="coerce").dt.normalize()
    frame = frame.dropna(subset=list(required))
    master = security_master.copy()
    if "asset_type" in master.columns:
        master = master[master["asset_type"].eq("stock")].copy()
    master["symbol"] = master["symbol"].astype("string").str.upper()
    master["stock_code"] = master["symbol"].str[-6:]
    master["listing_date"] = pd.to_datetime(master["listing_date"], errors="coerce").dt.normalize()
    master["delisting_date"] = pd.to_datetime(
        master["delisting_date"], errors="coerce"
    ).dt.normalize()
    matched = frame.merge(
        master[["symbol", "stock_code", "listing_date", "delisting_date"]],
        on="stock_code",
        how="inner",
    )
    matched = matched[
        matched["delisting_date"].isna()
        | matched["included_date"].le(matched["delisting_date"])
    ]
    records = []
    for classification, digits in (("sw_l1", 2), ("sw_l2", 4)):
        expanded = matched.copy()
        expanded["industry_code"] = (
            expanded["industry_code"].str[:digits] + "0" * (6 - digits)
        )
        expanded["classification"] = classification
        expanded = expanded.sort_values(["symbol", "included_date", "industry_code"])
        expanded = expanded.drop_duplicates(
            ["symbol", "included_date", "classification"], keep="last"
        )
        expanded["next_date"] = expanded.groupby(["symbol", "classification"])[
            "included_date"
        ].shift(-1)
        expanded["start_date"] = expanded[["included_date", "listing_date"]].max(axis=1)
        expanded["end_date"] = expanded["next_date"].sub(pd.Timedelta(days=1))
        expanded["end_date"] = expanded["end_date"].fillna(pd.Timestamp("2099-12-31"))
        has_delisting = expanded["delisting_date"].notna()
        expanded.loc[has_delisting, "end_date"] = expanded.loc[
            has_delisting, ["end_date", "delisting_date"]
        ].min(axis=1)
        expanded = expanded[expanded["start_date"].le(expanded["end_date"])]
        expanded["industry_name"] = expanded["industry_code"].map(
            lambda code: industry_names.get(str(code), str(code))
        )
        expanded["observed_date"] = expanded["updated_at"]
        expanded["source"] = "swsresearch/StockClassifyUse_stock.xls"
        expanded["quality_grade"] = QualityGrade.B.value
        records.append(expanded[INDUSTRY_COLUMNS])
    result = pd.concat(records, ignore_index=True)
    result = _coalesce_industry_intervals(result)
    result = result.sort_values(["symbol", "classification", "start_date"])
    validate_industry(result)
    return result.reset_index(drop=True)


def import_shenwan_history(
    store: ResearchDataStore,
    history_path: Path | str,
    security_master: pd.DataFrame,
    *,
    industry_names: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, DatasetManifest]:
    history_path = Path(history_path).resolve()
    raw = pd.read_excel(history_path, dtype=str)
    data = normalize_shenwan_history(
        raw,
        security_master,
        industry_names=industry_names,
    )
    stock_master = security_master[security_master.get("asset_type", "stock").eq("stock")].copy()
    expected = set(stock_master["symbol"].astype(str))
    covered = set(data["symbol"].astype(str))
    unexpected_symbols = sorted(covered - expected)
    if unexpected_symbols:
        raise ValueError(
            "industry membership contains non-stock symbols: "
            f"{unexpected_symbols[:10]}"
        )
    artifacts = store.write_partitioned_parquet(
        "industry_membership",
        data,
        ["symbol"],
        filename="data.parquet",
    )
    active = set(
        stock_master.loc[
            stock_master.get("active_at_source_end", False).astype(bool), "symbol"
        ].astype(str)
    )
    active_covered = len(active & covered)
    missing_symbols = sorted(expected - covered)
    manifest = DatasetManifest(
        schema_version=2,
        dataset="industry_membership",
        provider="swsresearch/official-industry-history",
        quality_grade=QualityGrade.B,
        row_count=len(data),
        columns=INDUSTRY_COLUMNS,
        data_files=artifacts,
        date_range={
            "start": data["start_date"].min().strftime("%Y-%m-%d"),
            "end": data["end_date"].max().strftime("%Y-%m-%d"),
        },
        source_files=[
            {
                "path": str(history_path),
                "bytes": history_path.stat().st_size,
                "sha256": sha256_file(history_path),
            }
        ],
        primary_key=["symbol", "classification", "start_date"],
        date_fields={
            "start_date": "行业归属生效日（闭区间）",
            "end_date": "行业归属失效日（闭区间）",
            "observed_date": "申万源文件记录的更新日",
        },
        partitioning={"style": "hive", "columns": ["symbol"]},
        coverage={
            "historical_stock_universe": len(expected),
            "covered_symbols": len(covered),
            "missing_symbols": len(missing_symbols),
            "current_expected": len(active),
            "current_covered": active_covered,
            "current_coverage_ratio": active_covered / len(active) if active else 0.0,
            "sw_l1_rows": int(data["classification"].eq("sw_l1").sum()),
            "sw_l2_rows": int(data["classification"].eq("sw_l2").sum()),
        },
        failures=[
            {"symbol": symbol, "status": "no_official_history", "error": None}
            for symbol in missing_symbols
        ],
        limitations=[
            "官方源给出历史行业代码和生效日，但可能随后修订，故质量为 B。",
            "没有官方名称字典的旧版行业代码以代码本身作为名称，不影响历史分组。",
        ],
        checks={
            "overlapping_intervals": 0,
            "non_stock_symbols": 0,
            "duplicate_primary_keys": int(
                data.duplicated(["symbol", "classification", "start_date"]).sum()
            ),
            "current_coverage_target": 0.95,
            "current_coverage_passed": active_covered / len(active) >= 0.95 if active else False,
        },
    )
    store.write_manifest(manifest)
    store.write_json_report(
        "shenwan-industry-history-coverage",
        {
            "schema_version": 1,
            "dataset": "industry_membership",
            "manifest": manifest.to_dict(),
            "missing_symbols": missing_symbols,
        },
    )
    return data, manifest


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
