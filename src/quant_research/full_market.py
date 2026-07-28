"""流式读取全市场证券分区，构建点时横截面。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd

from .data.store import ResearchDataStore


@dataclass(frozen=True)
class CrossSectionBuildResult:
    frame: pd.DataFrame
    audit: dict


def _dates(values: Iterable) -> pd.DatetimeIndex:
    result = pd.DatetimeIndex(pd.to_datetime(list(values))).normalize().sort_values().unique()
    if result.empty:
        raise ValueError("at least one observation date is required")
    return result


def _symbol_artifacts(store: ResearchDataStore, dataset: str, symbols=None):
    manifest = store.read_manifest(dataset)
    if (manifest.get("partitioning") or {}).get("columns") != ["symbol"]:
        raise ValueError(f"{dataset} must be partitioned by symbol")
    selected = None if symbols is None else {str(symbol).upper() for symbol in symbols}
    artifacts = []
    for artifact in manifest.get("data_files", []):
        symbol = (artifact.get("partition_values") or {}).get("symbol")
        if symbol is not None and (selected is None or symbol in selected):
            artifacts.append((symbol, artifact))
    return manifest, artifacts


def build_asof_cross_sections(
    store: ResearchDataStore,
    dataset: str,
    observation_dates: Iterable,
    fields: Iterable[str],
    *,
    maximum_age_days: int = 10,
    symbols: Iterable[str] | None = None,
) -> CrossSectionBuildResult:
    """逐证券读取最近可见记录，不把全市场几十年数据一次装入内存。"""

    dates = _dates(observation_dates)
    requested_fields = list(dict.fromkeys(fields))
    manifest, artifacts = _symbol_artifacts(store, dataset, symbols)
    required = {"symbol", "trade_date", *requested_fields}
    missing_fields = required.difference(manifest.get("columns", []))
    if missing_fields:
        raise ValueError(f"{dataset} fields are unavailable: {sorted(missing_fields)}")
    earliest = dates.min() - pd.Timedelta(days=maximum_age_days)
    latest = dates.max()
    targets = pd.DataFrame({"observation_date": dates})
    frames = []
    failures = []
    empty_symbols = []
    for symbol, artifact in artifacts:
        path = store.root / artifact["path"]
        try:
            source = pd.read_parquet(
                path,
                columns=["symbol", "trade_date", *requested_fields],
                filters=[("trade_date", ">=", earliest), ("trade_date", "<=", latest)],
            )
            if source.empty:
                empty_symbols.append(symbol)
                continue
            source["trade_date"] = pd.to_datetime(source["trade_date"]).dt.normalize()
            source = source.sort_values("trade_date").drop_duplicates("trade_date", keep="last")
            matched = pd.merge_asof(
                targets,
                source,
                left_on="observation_date",
                right_on="trade_date",
                direction="backward",
                tolerance=pd.Timedelta(days=maximum_age_days),
            )
            matched = matched.dropna(subset=["trade_date"])
            if not matched.empty:
                matched["symbol"] = symbol
                matched["age_days"] = (
                    matched["observation_date"] - matched["trade_date"]
                ).dt.days
                frames.append(matched)
            else:
                empty_symbols.append(symbol)
        except Exception as exc:  # pragma: no cover - real-data failure evidence
            failures.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})
    result = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(
            columns=["observation_date", "symbol", "trade_date", *requested_fields, "age_days"]
        )
    )
    expected = len(artifacts) * len(dates)
    audit = {
        "dataset": dataset,
        "mode": "asof",
        "quality_grade": manifest.get("quality_grade"),
        "observation_date_count": len(dates),
        "target_symbols": len(artifacts),
        "successful_symbols": int(result["symbol"].nunique()) if not result.empty else 0,
        "empty_symbols": empty_symbols,
        "failed_symbols": failures,
        "expected_symbol_dates": expected,
        "matched_symbol_dates": len(result),
        "coverage_ratio": len(result) / expected if expected else 0.0,
        "maximum_age_days": maximum_age_days,
    }
    return CrossSectionBuildResult(result, audit)


def build_exact_cross_sections(
    store: ResearchDataStore,
    dataset: str,
    observation_dates: Iterable,
    fields: Iterable[str],
    *,
    symbols: Iterable[str] | None = None,
) -> CrossSectionBuildResult:
    """逐证券读取指定日期的精确记录。"""

    dates = _dates(observation_dates)
    requested_fields = list(dict.fromkeys(fields))
    manifest, artifacts = _symbol_artifacts(store, dataset, symbols)
    required = {"symbol", "trade_date", *requested_fields}
    missing_fields = required.difference(manifest.get("columns", []))
    if missing_fields:
        raise ValueError(f"{dataset} fields are unavailable: {sorted(missing_fields)}")
    frames = []
    failures = []
    empty_symbols = []
    for symbol, artifact in artifacts:
        path = store.root / artifact["path"]
        try:
            source = pd.read_parquet(
                path,
                columns=["symbol", "trade_date", *requested_fields],
                filters=[("trade_date", ">=", dates.min()), ("trade_date", "<=", dates.max())],
            )
            source["trade_date"] = pd.to_datetime(source["trade_date"]).dt.normalize()
            source = source[source["trade_date"].isin(dates)]
            if source.empty:
                empty_symbols.append(symbol)
                continue
            source = source.drop_duplicates(["symbol", "trade_date"], keep="last")
            source.rename(columns={"trade_date": "observation_date"}, inplace=True)
            frames.append(source)
        except Exception as exc:  # pragma: no cover - real-data failure evidence
            failures.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})
    result = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=["observation_date", "symbol", *requested_fields])
    )
    expected = len(artifacts) * len(dates)
    audit = {
        "dataset": dataset,
        "mode": "exact",
        "quality_grade": manifest.get("quality_grade"),
        "observation_date_count": len(dates),
        "target_symbols": len(artifacts),
        "successful_symbols": int(result["symbol"].nunique()) if not result.empty else 0,
        "empty_symbols": empty_symbols,
        "failed_symbols": failures,
        "expected_symbol_dates": expected,
        "matched_symbol_dates": len(result),
        "coverage_ratio": len(result) / expected if expected else 0.0,
    }
    return CrossSectionBuildResult(result, audit)


def build_event_cross_sections(
    store: ResearchDataStore,
    dataset: str,
    observation_dates: Iterable,
    fields: Iterable[str],
    *,
    event_date_field: str = "effective_from",
    symbols: Iterable[str] | None = None,
) -> CrossSectionBuildResult:
    """回放离散生效事件，逐证券选择观察日以前的最后一条记录。"""

    dates = _dates(observation_dates)
    requested_fields = list(dict.fromkeys(fields))
    manifest = store.read_manifest(dataset)
    required = {"symbol", event_date_field, *requested_fields}
    missing_fields = required.difference(manifest.get("columns", []))
    if missing_fields:
        raise ValueError(f"{dataset} fields are unavailable: {sorted(missing_fields)}")
    selected = None if symbols is None else {str(symbol).upper() for symbol in symbols}
    frames = []
    for artifact in manifest.get("data_files", []):
        source = pd.read_parquet(
            store.root / artifact["path"],
            columns=["symbol", event_date_field, *requested_fields],
        )
        if selected is not None:
            source = source[source["symbol"].astype(str).str.upper().isin(selected)]
        if not source.empty:
            frames.append(source)
    source = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=["symbol", event_date_field, *requested_fields])
    )
    source[event_date_field] = pd.to_datetime(
        source[event_date_field], errors="coerce"
    ).dt.normalize()
    source = source.dropna(subset=["symbol", event_date_field])
    source = source[source[event_date_field].le(dates.max())]
    targets = pd.DataFrame({"observation_date": dates})
    matched_frames = []
    for symbol, group in source.groupby("symbol", sort=True):
        events = (
            group.sort_values(event_date_field)
            .drop_duplicates(event_date_field, keep="last")
        )
        matched = pd.merge_asof(
            targets,
            events,
            left_on="observation_date",
            right_on=event_date_field,
            direction="backward",
        ).dropna(subset=[event_date_field])
        if not matched.empty:
            matched["symbol"] = symbol
            matched_frames.append(matched)
    result = (
        pd.concat(matched_frames, ignore_index=True)
        if matched_frames
        else pd.DataFrame(
            columns=["observation_date", "symbol", event_date_field, *requested_fields]
        )
    )
    result = result[
        ["observation_date", "symbol", event_date_field, *requested_fields]
    ].sort_values(["observation_date", "symbol"])
    target_symbols = int(source["symbol"].nunique()) if not source.empty else 0
    expected = target_symbols * len(dates)
    audit = {
        "dataset": dataset,
        "mode": "event_asof",
        "quality_grade": manifest.get("quality_grade"),
        "event_date_field": event_date_field,
        "observation_date_count": len(dates),
        "target_symbols": target_symbols,
        "successful_symbols": int(result["symbol"].nunique()) if not result.empty else 0,
        "expected_symbol_dates": expected,
        "matched_symbol_dates": len(result),
        "coverage_ratio": len(result) / expected if expected else 0.0,
        "future_event_rows": int(
            result[event_date_field].gt(result["observation_date"]).sum()
        ),
    }
    return CrossSectionBuildResult(result.reset_index(drop=True), audit)


def build_fundamental_cross_sections(
    store: ResearchDataStore,
    dataset: str,
    observation_dates: Iterable,
    fields: Iterable[str],
    *,
    symbols: Iterable[str] | None = None,
    annual_only: bool = False,
) -> CrossSectionBuildResult:
    """逐证券选择观察日已公告的最新报告期，晚到的旧报告修订不会覆盖新报告。"""

    dates = _dates(observation_dates)
    requested_fields = list(dict.fromkeys(fields))
    manifest, artifacts = _symbol_artifacts(store, dataset, symbols)
    required = {"symbol", "report_date", "notice_date", *requested_fields}
    if annual_only:
        required.add("is_annual")
    missing_fields = required.difference(manifest.get("columns", []))
    if missing_fields:
        raise ValueError(f"{dataset} fields are unavailable: {sorted(missing_fields)}")
    frames = []
    failures = []
    empty_symbols = []
    for symbol, artifact in artifacts:
        try:
            read_columns = ["symbol", "report_date", "notice_date", *requested_fields]
            if annual_only and "is_annual" not in read_columns:
                read_columns.append("is_annual")
            source = pd.read_parquet(
                store.root / artifact["path"],
                columns=read_columns,
                filters=[("notice_date", "<=", dates.max())],
            )
            if annual_only:
                source = source[source["is_annual"].astype(bool)]
            source["report_date"] = pd.to_datetime(source["report_date"]).dt.normalize()
            source["notice_date"] = pd.to_datetime(source["notice_date"]).dt.normalize()
            matched = []
            records = source.sort_values(["notice_date", "report_date"]).to_dict("records")
            position = 0
            latest = None
            for observation_date in dates:
                while position < len(records) and records[position]["notice_date"] <= observation_date:
                    candidate = records[position]
                    if latest is None or (
                        candidate["report_date"], candidate["notice_date"]
                    ) >= (latest["report_date"], latest["notice_date"]):
                        latest = candidate
                    position += 1
                if latest is not None:
                    row = dict(latest)
                    row["observation_date"] = observation_date
                    matched.append(row)
            if matched:
                frames.append(pd.DataFrame(matched))
            else:
                empty_symbols.append(symbol)
        except Exception as exc:  # pragma: no cover - real-data failure evidence
            failures.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})
    result = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(
            columns=[
                "observation_date",
                "symbol",
                "report_date",
                "notice_date",
                *requested_fields,
            ]
        )
    )
    result = result[
        [
            "observation_date",
            "symbol",
            "report_date",
            "notice_date",
            *requested_fields,
        ]
    ].sort_values(["observation_date", "symbol"])
    expected = len(artifacts) * len(dates)
    audit = {
        "dataset": dataset,
        "mode": "fundamental_pit",
        "quality_grade": manifest.get("quality_grade"),
        "observation_date_count": len(dates),
        "target_symbols": len(artifacts),
        "successful_symbols": int(result["symbol"].nunique()) if not result.empty else 0,
        "empty_symbols": empty_symbols,
        "failed_symbols": failures,
        "expected_symbol_dates": expected,
        "matched_symbol_dates": len(result),
        "coverage_ratio": len(result) / expected if expected else 0.0,
        "future_notice_rows": int(
            result["notice_date"].gt(result["observation_date"]).sum()
        ),
        "annual_only": annual_only,
    }
    return CrossSectionBuildResult(result.reset_index(drop=True), audit)


def build_interval_cross_sections(
    store: ResearchDataStore,
    dataset: str,
    observation_dates: Iterable,
    fields: Iterable[str],
    *,
    symbols: Iterable[str] | None = None,
) -> CrossSectionBuildResult:
    """按闭区间展开历史分类、名称或成分事实，不用当前状态回填过去。"""

    dates = _dates(observation_dates)
    requested_fields = list(dict.fromkeys(fields))
    manifest, artifacts = _symbol_artifacts(store, dataset, symbols)
    required = {"symbol", "start_date", "end_date", *requested_fields}
    missing_fields = required.difference(manifest.get("columns", []))
    if missing_fields:
        raise ValueError(f"{dataset} fields are unavailable: {sorted(missing_fields)}")
    frames = []
    failures = []
    empty_symbols = []
    for symbol, artifact in artifacts:
        try:
            source = pd.read_parquet(
                store.root / artifact["path"],
                columns=["symbol", "start_date", "end_date", *requested_fields],
                filters=[
                    ("start_date", "<=", dates.max()),
                    ("end_date", ">=", dates.min()),
                ],
            )
            source["start_date"] = pd.to_datetime(source["start_date"]).dt.normalize()
            source["end_date"] = pd.to_datetime(source["end_date"]).dt.normalize()
            matched = []
            records = source.to_dict("records")
            for observation_date in dates:
                visible = [
                    {**row, "observation_date": observation_date}
                    for row in records
                    if row["start_date"] <= observation_date <= row["end_date"]
                ]
                if visible:
                    matched.append(pd.DataFrame(visible))
            if matched:
                frames.append(pd.concat(matched, ignore_index=True))
            else:
                empty_symbols.append(symbol)
        except Exception as exc:  # pragma: no cover - real-data failure evidence
            failures.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})
    result = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(
            columns=[
                "observation_date",
                "symbol",
                "start_date",
                "end_date",
                *requested_fields,
            ]
        )
    )
    result = result[
        [
            "observation_date",
            "symbol",
            "start_date",
            "end_date",
            *requested_fields,
        ]
    ].sort_values(["observation_date", "symbol"])
    audit = {
        "dataset": dataset,
        "mode": "effective_interval",
        "quality_grade": manifest.get("quality_grade"),
        "observation_date_count": len(dates),
        "target_symbols": len(artifacts),
        "successful_symbols": int(result["symbol"].nunique()) if not result.empty else 0,
        "empty_symbols": empty_symbols,
        "failed_symbols": failures,
        "matched_rows": len(result),
        "future_interval_rows": int(
            (
                result["start_date"].gt(result["observation_date"])
                | result["end_date"].lt(result["observation_date"])
            ).sum()
        ),
    }
    return CrossSectionBuildResult(result.reset_index(drop=True), audit)
