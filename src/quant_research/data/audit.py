"""全平台数据覆盖率与点时安全审计。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .store import ResearchDataStore, sha256_file


DEFAULT_PRIMARY_KEYS = {
    "security_master": ["symbol"],
    "trading_calendar": ["trade_date"],
    "etf_daily": ["symbol", "trade_date"],
    "daily_market_state": ["symbol", "trade_date"],
    "daily_valuation": ["symbol", "trade_date"],
    "fundamentals_pit": ["symbol", "report_date", "notice_date", "report_type"],
    "index_membership": ["index_symbol", "symbol", "start_date", "end_date"],
    "industry_membership": [
        "symbol",
        "classification",
        "start_date",
        "end_date",
    ],
}
DATE_COLUMNS = {
    "trade_date",
    "start_date",
    "end_date",
    "report_date",
    "notice_date",
    "observed_date",
    "effective_from",
    "effective_to",
}
QLIB_REQUIRED_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "factor",
    "change",
    "volume",
    "amount",
)


def _json_scalar(value):
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, np.generic):
        return value.item()
    return value


def _read_qlib_feature(path: Path) -> tuple[int, np.ndarray]:
    payload = np.fromfile(path, dtype="<f4")
    if payload.size < 1 or not np.isfinite(payload[0]):
        raise ValueError(f"invalid Qlib feature header: {path}")
    start_index = int(payload[0])
    if not np.isclose(payload[0], start_index):
        raise ValueError(f"non-integral Qlib feature start index: {path}")
    return start_index, payload[1:]


def _master_lookup(master: pd.DataFrame) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    lookup = {}
    columns = ["symbol", "start_date", "end_date"]
    if "active_at_source_end" in master:
        columns.append("active_at_source_end")
    for row in master[columns].itertuples(index=False):
        active = bool(getattr(row, "active_at_source_end", False))
        lookup[str(row.symbol).upper()] = (
            pd.Timestamp(row.start_date).normalize(),
            (
                pd.Timestamp("2262-04-11")
                if active
                else pd.Timestamp(row.end_date).normalize()
            ),
        )
    return lookup


def audit_qlib_daily_features(
    qlib_root: Path | str,
    security_master: pd.DataFrame,
    abnormal_return_threshold: float = 0.30,
) -> dict:
    """逐证券读取 Qlib 二进制，内存峰值与单只证券历史长度相关。"""

    qlib_root = Path(qlib_root).resolve()
    feature_root = qlib_root / "features"
    calendar_path = qlib_root / "calendars" / "day.txt"
    calendar = pd.DatetimeIndex(
        pd.to_datetime(
            calendar_path.read_text(encoding="utf-8").splitlines(),
            errors="raise",
        )
    ).normalize()
    master = security_master.copy()
    if "source" in master:
        master = master[
            master["source"].astype(str).str.contains("qlib", case=False, na=False)
        ]
    if "asset_type" in master:
        master = master[master["asset_type"].isin(["stock", "index"])]
    active_intervals = _master_lookup(master)
    expected_symbols = set(active_intervals)
    feature_symbols = {
        path.name.upper()
        for path in feature_root.iterdir()
        if path.is_dir()
    }

    statuses = []
    abnormal_samples = []
    total_observations = 0
    ohlc_violations = 0
    nonpositive_factors = 0
    out_of_active_interval = 0
    return_counts = {
        f"absolute_return_gt_{int(abnormal_return_threshold * 100)}pct": 0,
        "absolute_return_gt_50pct": 0,
        "absolute_return_gt_100pct": 0,
    }
    successful = 0

    for symbol in sorted(expected_symbols):
        directory = feature_root / symbol.lower()
        failures = []
        arrays = {}
        start_indexes = {}
        for field in QLIB_REQUIRED_FIELDS:
            path = directory / f"{field}.day.bin"
            if not path.is_file():
                failures.append({"code": "missing_field", "field": field})
                continue
            try:
                start_index, values = _read_qlib_feature(path)
            except (OSError, ValueError) as exc:
                failures.append(
                    {"code": "invalid_feature", "field": field, "detail": str(exc)}
                )
                continue
            start_indexes[field] = start_index
            arrays[field] = values

        lengths = {field: len(values) for field, values in arrays.items()}
        if arrays and (
            len(set(start_indexes.values())) != 1 or len(set(lengths.values())) != 1
        ):
            failures.append(
                {
                    "code": "misaligned_fields",
                    "start_indexes": start_indexes,
                    "lengths": lengths,
                }
            )
        if failures:
            statuses.append({"symbol": symbol, "status": "failed", "failures": failures})
            continue

        start_index = next(iter(start_indexes.values()))
        length = next(iter(lengths.values()))
        end_index = start_index + length
        if start_index < 0 or end_index > len(calendar):
            statuses.append(
                {
                    "symbol": symbol,
                    "status": "failed",
                    "failures": [
                        {
                            "code": "calendar_bounds",
                            "start_index": start_index,
                            "length": length,
                            "calendar_sessions": len(calendar),
                        }
                    ],
                }
            )
            continue

        close = arrays["close"]
        finite_close = np.isfinite(close)
        finite_count = int(finite_close.sum())
        total_observations += finite_count
        dates = calendar[start_index:end_index]
        first_date = None
        last_date = None
        if finite_count:
            finite_positions = np.flatnonzero(finite_close)
            first_date = dates[finite_positions[0]]
            last_date = dates[finite_positions[-1]]
            active_start, active_end = active_intervals[symbol]
            outside = (dates[finite_positions] < active_start) | (
                dates[finite_positions] > active_end
            )
            out_of_active_interval += int(outside.sum())

        comparable = (
            np.isfinite(arrays["open"])
            & np.isfinite(arrays["high"])
            & np.isfinite(arrays["low"])
            & finite_close
        )
        row_max = np.maximum.reduce(
            [arrays["open"], arrays["low"], arrays["close"]]
        )
        row_min = np.minimum.reduce(
            [arrays["open"], arrays["high"], arrays["close"]]
        )
        ohlc_violations += int(
            (
                comparable
                & (
                    (arrays["high"] + 1e-5 < row_max)
                    | (arrays["low"] - 1e-5 > row_min)
                )
            ).sum()
        )
        nonpositive_factors += int(
            (np.isfinite(arrays["factor"]) & (arrays["factor"] <= 0.0)).sum()
        )

        changes = arrays["change"]
        finite_changes = np.isfinite(changes)
        absolute_changes = np.abs(changes[finite_changes])
        return_counts[
            f"absolute_return_gt_{int(abnormal_return_threshold * 100)}pct"
        ] += int((absolute_changes > abnormal_return_threshold).sum())
        return_counts["absolute_return_gt_50pct"] += int(
            (absolute_changes > 0.50).sum()
        )
        return_counts["absolute_return_gt_100pct"] += int(
            (absolute_changes > 1.00).sum()
        )
        if absolute_changes.size:
            finite_indexes = np.flatnonzero(finite_changes)
            local_order = np.argsort(absolute_changes)[-3:]
            for local_index in local_order:
                change_index = finite_indexes[local_index]
                if absolute_changes[local_index] <= abnormal_return_threshold:
                    continue
                abnormal_samples.append(
                    {
                        "symbol": symbol,
                        "trade_date": dates[change_index].strftime("%Y-%m-%d"),
                        "change": float(changes[change_index]),
                    }
                )

        successful += 1
        statuses.append(
            {
                "symbol": symbol,
                "status": "success",
                "finite_close_observations": finite_count,
                "first_finite_date": _json_scalar(first_date),
                "last_finite_date": _json_scalar(last_date),
            }
        )

    abnormal_samples = sorted(
        abnormal_samples,
        key=lambda item: abs(item["change"]),
        reverse=True,
    )[:100]
    failed = len(expected_symbols) - successful
    return {
        "provider": "qlib-community-cn",
        "calendar": {
            "sessions": len(calendar),
            "start": calendar.min().strftime("%Y-%m-%d"),
            "end": calendar.max().strftime("%Y-%m-%d"),
            "source_path": str(calendar_path),
            "source_sha256": sha256_file(calendar_path),
        },
        "expected_instruments": len(expected_symbols),
        "feature_directories": len(feature_symbols),
        "successful_instruments": successful,
        "failed_instruments": failed,
        "unknown_feature_symbols": sorted(feature_symbols - expected_symbols),
        "missing_feature_symbols": sorted(expected_symbols - feature_symbols),
        "total_finite_close_observations": total_observations,
        "checks": {
            "ohlc_violation_count": ohlc_violations,
            "nonpositive_factor_count": nonpositive_factors,
            "finite_observations_outside_security_interval": out_of_active_interval,
            **return_counts,
            "largest_abnormal_return_samples": abnormal_samples,
        },
        "instrument_status": statuses,
        "status": "passed"
        if failed == 0
        and not (feature_symbols - expected_symbols)
        and ohlc_violations == 0
        and nonpositive_factors == 0
        and out_of_active_interval == 0
        else "failed",
    }


@dataclass
class _FileAuditState:
    rows: int = 0
    duplicate_keys: int = 0
    sorted_keys: bool = True
    last_key: tuple | None = None
    time_inversions: int = 0
    notice_before_report: int = 0
    rows_outside_active_interval: int = 0


def _normalized_key(frame: pd.DataFrame, columns: list[str]) -> list[tuple]:
    normalized = frame[columns].copy()
    for column in columns:
        if column in DATE_COLUMNS:
            normalized[column] = pd.to_datetime(
                normalized[column], errors="coerce"
            )
    return list(normalized.itertuples(index=False, name=None))


def audit_normalized_dataset(
    store: ResearchDataStore,
    dataset: str,
    security_master: pd.DataFrame,
    batch_size: int = 65_536,
) -> dict:
    manifest = store.read_manifest(dataset)
    primary_key = manifest.get("primary_key") or DEFAULT_PRIMARY_KEYS.get(dataset, [])
    master_intervals = _master_lookup(security_master)
    known_symbols = set(master_intervals)
    state = _FileAuditState()
    unknown_symbols = set()
    observed_symbols = set()
    missing_files = []
    hash_mismatches = []
    file_rows = 0

    for artifact in manifest.get("data_files", []):
        path = store.root / artifact["path"]
        if not path.is_file():
            missing_files.append(artifact["path"])
            continue
        actual_hash = sha256_file(path)
        if actual_hash != artifact.get("sha256"):
            hash_mismatches.append(
                {
                    "path": artifact["path"],
                    "expected": artifact.get("sha256"),
                    "actual": actual_hash,
                }
            )
        parquet = pq.ParquetFile(path)
        file_rows += parquet.metadata.num_rows
        available = set(parquet.schema_arrow.names)
        scan_columns = set(primary_key).intersection(available)
        scan_columns.update(
            column
            for column in (
                "symbol",
                "index_symbol",
                "trade_date",
                "start_date",
                "end_date",
                "effective_from",
                "effective_to",
                "report_date",
                "notice_date",
            )
            if column in available
        )
        file_last_key = None
        file_first_key = None
        for batch in parquet.iter_batches(
            batch_size=batch_size,
            columns=sorted(scan_columns),
        ):
            frame = batch.to_pandas()
            state.rows += len(frame)
            if "symbol" in frame:
                symbols = frame["symbol"].dropna().astype(str).str.upper()
                observed_symbols.update(symbols)
                unknown_symbols.update(set(symbols) - known_symbols)

            if primary_key and set(primary_key).issubset(frame.columns):
                keys = _normalized_key(frame, primary_key)
                for key in keys:
                    if file_first_key is None:
                        file_first_key = key
                    if file_last_key is not None:
                        if key < file_last_key:
                            state.sorted_keys = False
                        if key == file_last_key:
                            state.duplicate_keys += 1
                    file_last_key = key

            interval_pairs = [
                ("start_date", "end_date"),
                ("effective_from", "effective_to"),
            ]
            for start_column, end_column in interval_pairs:
                if {start_column, end_column}.issubset(frame.columns):
                    start = pd.to_datetime(frame[start_column], errors="coerce")
                    end = pd.to_datetime(frame[end_column], errors="coerce")
                    state.time_inversions += int((start > end).sum())
            if {"report_date", "notice_date"}.issubset(frame.columns):
                report_date = pd.to_datetime(frame["report_date"], errors="coerce")
                notice_date = pd.to_datetime(frame["notice_date"], errors="coerce")
                state.notice_before_report += int((notice_date < report_date).sum())

            if {"symbol", "trade_date"}.issubset(frame.columns):
                dates = pd.to_datetime(frame["trade_date"], errors="coerce")
                for symbol, positions in frame.groupby("symbol", sort=False).groups.items():
                    interval = master_intervals.get(str(symbol).upper())
                    if interval is None:
                        continue
                    symbol_dates = dates.loc[positions]
                    state.rows_outside_active_interval += int(
                        ((symbol_dates < interval[0]) | (symbol_dates > interval[1])).sum()
                    )
        if primary_key and state.last_key is not None and file_first_key is not None:
            if file_first_key < state.last_key:
                state.sorted_keys = False
            if file_first_key == state.last_key:
                state.duplicate_keys += 1
        if file_last_key is not None:
            state.last_key = file_last_key

    expected_rows = int(manifest.get("row_count", 0))
    failures = []
    if missing_files:
        failures.append({"code": "missing_files", "paths": missing_files})
    if hash_mismatches:
        failures.append({"code": "hash_mismatch", "files": hash_mismatches})
    if file_rows != expected_rows or state.rows != expected_rows:
        failures.append(
            {
                "code": "row_count_mismatch",
                "manifest": expected_rows,
                "parquet_metadata": file_rows,
                "scanned": state.rows,
            }
        )
    if state.duplicate_keys:
        failures.append(
            {"code": "duplicate_primary_keys", "count": state.duplicate_keys}
        )
    if primary_key and not state.sorted_keys:
        failures.append({"code": "primary_key_not_sorted"})
    if unknown_symbols:
        failures.append(
            {"code": "unknown_symbols", "count": len(unknown_symbols)}
        )
    if state.time_inversions:
        failures.append(
            {"code": "time_inversions", "count": state.time_inversions}
        )
    if state.notice_before_report:
        failures.append(
            {
                "code": "notice_before_report_date",
                "count": state.notice_before_report,
            }
        )
    if state.rows_outside_active_interval:
        failures.append(
            {
                "code": "rows_outside_security_interval",
                "count": state.rows_outside_active_interval,
            }
        )
    partitioning = manifest.get("partitioning")
    is_large = expected_rows >= 1_000_000
    target_asset_type = {
        "etf_daily": "etf",
        "daily_market_state": "stock",
        "daily_valuation": "stock",
        "fundamentals_pit": "stock",
        "index_membership": "stock",
        "industry_membership": "stock",
    }.get(dataset)
    symbol_coverage = None
    if "symbol" in manifest.get("columns", []):
        if target_asset_type and "asset_type" in security_master:
            target_symbols = set(
                security_master.loc[
                    security_master["asset_type"] == target_asset_type,
                    "symbol",
                ].astype(str)
            )
        else:
            target_symbols = known_symbols
        covered_symbols = observed_symbols & target_symbols
        symbol_coverage = {
            "target_asset_type": target_asset_type or "all",
            "target_symbols": len(target_symbols),
            "covered_symbols": len(covered_symbols),
            "coverage_ratio": (
                len(covered_symbols) / len(target_symbols) if target_symbols else None
            ),
            "missing_symbols": sorted(target_symbols - observed_symbols),
        }
    return {
        "dataset": dataset,
        "quality_grade": manifest.get("quality_grade"),
        "row_count": {
            "manifest": expected_rows,
            "parquet_metadata": file_rows,
            "actual": state.rows,
        },
        "data_file_count": len(manifest.get("data_files", [])),
        "primary_key": primary_key,
        "primary_key_sorted": state.sorted_keys if primary_key else None,
        "duplicate_primary_keys": state.duplicate_keys,
        "unknown_symbols": sorted(unknown_symbols),
        "time_inversions": state.time_inversions,
        "notice_before_report_date": state.notice_before_report,
        "rows_outside_security_interval": state.rows_outside_active_interval,
        "hash_mismatches": hash_mismatches,
        "partitioning": partitioning,
        "partitioning_compliant": not is_large or bool(partitioning),
        "symbol_coverage": symbol_coverage,
        "failures": failures,
        "status": "passed" if not failures else "failed",
    }


def build_platform_coverage_report(
    store: ResearchDataStore,
    qlib_root: Path | str,
) -> dict:
    master = store.read_parquet("security_master")
    calendar = store.read_parquet("trading_calendar")
    qlib_report = audit_qlib_daily_features(qlib_root, master)
    datasets = []
    for manifest_path in sorted(store.manifest_dir.glob("*.json")):
        if manifest_path.stem in {"platform_coverage"}:
            continue
        datasets.append(
            audit_normalized_dataset(store, manifest_path.stem, master)
        )
    asset_counts = {
        str(key): int(value)
        for key, value in master["asset_type"].value_counts().sort_index().items()
    }
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "日频A股、ETF、基金和指数本地研究平台",
        "security_master": {
            "rows": len(master),
            "asset_type_counts": asset_counts,
            "data_start": pd.to_datetime(master["start_date"]).min().strftime("%Y-%m-%d"),
            "data_end": pd.to_datetime(master["end_date"]).max().strftime("%Y-%m-%d"),
            "earliest_listing_date": pd.to_datetime(
                master["listing_date"]
            ).min().strftime("%Y-%m-%d"),
            "latest_delisting_date": pd.to_datetime(
                master["delisting_date"]
            ).max().strftime("%Y-%m-%d"),
            "lifecycle_status_counts": {
                str(key): int(value)
                for key, value in master["lifecycle_status"]
                .value_counts()
                .sort_index()
                .items()
            },
            "lifecycle_quality_counts": {
                str(key): int(value)
                for key, value in master["lifecycle_quality"]
                .value_counts()
                .sort_index()
                .items()
            },
            "duplicate_symbols": int(master["symbol"].duplicated().sum()),
            "time_inversions": int(
                (
                    pd.to_datetime(master["start_date"])
                    > pd.to_datetime(master["end_date"])
                ).sum()
            ),
        },
        "trading_calendar": {
            "sessions": len(calendar),
            "start": pd.to_datetime(calendar["trade_date"]).min().strftime("%Y-%m-%d"),
            "end": pd.to_datetime(calendar["trade_date"]).max().strftime("%Y-%m-%d"),
        },
        "qlib_daily_features": qlib_report,
        "normalized_datasets": datasets,
        "known_limitations": [
            "异常收益只报告、不自动删除；注册制新股首日可能合法超过30%。",
            "尚未重建的百万行旧数据集会被标记为分区不合规，并在对应业务迭代迁移。",
            "质量报告验证公告日不早于报告期末；策略查询的观察日门禁由接口测试单独验证。",
        ],
    }
    foundation_failed = (
        report["security_master"]["duplicate_symbols"] > 0
        or report["security_master"]["time_inversions"] > 0
        or qlib_report["status"] != "passed"
    )
    report["status"] = "failed" if foundation_failed else "passed_with_findings"
    store.write_json_report("platform_coverage", report)
    return report
