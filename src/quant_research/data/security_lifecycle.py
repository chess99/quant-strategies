"""公开交易所证券生命周期快照与 Qlib 主表校正。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from .contracts import QualityGrade
from .store import ResearchDataStore, sha256_file


SNAPSHOT_NAMES = (
    "current_a",
    "sh_main",
    "sh_star",
    "sz_a",
    "bj_a",
    "sh_delisted",
    "sz_delisted",
)
KNOWN_CODE_MIGRATIONS = {
    "SH601313": {
        "canonical_symbol": "SH601360",
        "display_name": "江南嘉捷",
        "listing_date": "2012-01-16",
    },
    "SZ000022": {
        "canonical_symbol": "SZ001872",
        "display_name": "深赤湾A",
        "listing_date": "1993-05-05",
    },
    "SZ000043": {
        "canonical_symbol": "SZ001914",
        "display_name": "中航善达",
        "listing_date": "1994-09-28",
    },
    "SZ300114": {
        "canonical_symbol": "SZ302132",
        "display_name": "中航电测",
        "listing_date": "2010-08-27",
    },
}
KNOWN_TERMINATIONS = {
    "BJ920680": {
        "display_name": "广道退",
        "delisting_date": "2026-01-05",
        "source": "北证发[2025]67号；退市整理期于2025-12-31结束",
    }
}


def clip_to_security_lifecycle(
    frame: pd.DataFrame,
    security,
    *,
    date_column: str,
) -> pd.DataFrame:
    """移除供应商在上市前或退市后返回的代码历史。"""

    if frame.empty:
        return frame.copy()
    dates = pd.to_datetime(frame[date_column], errors="coerce").dt.normalize()
    listing_date = pd.Timestamp(security["listing_date"]).normalize()
    mask = dates.ge(listing_date)
    delisting_date = security.get("delisting_date")
    if pd.notna(delisting_date):
        mask &= dates.le(pd.Timestamp(delisting_date).normalize())
    return frame.loc[mask].reset_index(drop=True)


@dataclass(frozen=True)
class SecurityLifecycleSnapshot:
    as_of: str
    tables: dict[str, pd.DataFrame]
    source_files: list[dict]


class AkshareSecurityLifecycleProvider:
    def fetch(self) -> dict[str, pd.DataFrame]:
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("akshare is required for lifecycle snapshots") from exc
        return {
            "current_a": ak.stock_info_a_code_name(),
            "sh_main": ak.stock_info_sh_name_code(symbol="主板A股"),
            "sh_star": ak.stock_info_sh_name_code(symbol="科创板"),
            "sz_a": ak.stock_info_sz_name_code(symbol="A股列表"),
            "bj_a": ak.stock_info_bj_name_code(),
            "sh_delisted": ak.stock_info_sh_delist(),
            "sz_delisted": ak.stock_info_sz_delist(),
        }


def _snapshot_filename(as_of: str, name: str) -> str:
    return f"{as_of}__{name}.csv"


def sync_security_lifecycle_snapshot(
    store: ResearchDataStore,
    provider: AkshareSecurityLifecycleProvider | None = None,
    as_of: date | str | None = None,
) -> SecurityLifecycleSnapshot:
    provider = provider or AkshareSecurityLifecycleProvider()
    as_of_text = pd.Timestamp(as_of or date.today()).strftime("%Y-%m-%d")
    tables = provider.fetch()
    source_files = []
    for name in SNAPSHOT_NAMES:
        source_files.append(
            store.write_raw_csv(
                "akshare",
                "security_lifecycle",
                _snapshot_filename(as_of_text, name),
                tables[name],
            )
        )
    return SecurityLifecycleSnapshot(as_of_text, tables, source_files)


def load_latest_security_lifecycle_snapshot(
    store: ResearchDataStore,
) -> SecurityLifecycleSnapshot:
    directory = store.raw_dir / "akshare" / "security_lifecycle"
    candidates = sorted(directory.glob("*__current_a.csv"))
    if not candidates:
        raise FileNotFoundError(
            "security lifecycle snapshot is missing; rerun with --refresh-lifecycle"
        )
    as_of = candidates[-1].name.split("__", maxsplit=1)[0]
    tables = {}
    source_files = []
    for name in SNAPSHOT_NAMES:
        path = directory / _snapshot_filename(as_of, name)
        if not path.is_file():
            raise FileNotFoundError(f"incomplete lifecycle snapshot: {path}")
        tables[name] = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
        source_files.append(
            {
                "path": path.relative_to(store.root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return SecurityLifecycleSnapshot(as_of, tables, source_files)


def _symbol_for_code(code) -> str:
    code = str(code).strip().split(".", maxsplit=1)[0].zfill(6)
    if code.startswith("6"):
        return f"SH{code}"
    if code.startswith(("0", "1", "2", "3")):
        return f"SZ{code}"
    return f"BJ{code}"


def _active_records(snapshot: SecurityLifecycleSnapshot) -> dict[str, dict]:
    records = {}
    specs = {
        "sh_main": (0, 1, 5),
        "sh_star": (0, 1, 5),
        "sz_a": (1, 2, 3),
        "bj_a": (0, 1, 4),
    }
    for name, (code_position, name_position, date_position) in specs.items():
        frame = snapshot.tables[name]
        for row in frame.itertuples(index=False, name=None):
            symbol = _symbol_for_code(row[code_position])
            records[symbol] = {
                "display_name": row[name_position],
                "listing_date": pd.to_datetime(
                    row[date_position], errors="coerce"
                ),
                "delisting_date": pd.NaT,
                "active_at_source_end": True,
                "canonical_symbol": symbol,
                "lifecycle_status": "active",
                "lifecycle_quality": QualityGrade.A.value,
                "lifecycle_source": f"akshare/{name}@{snapshot.as_of}",
            }
    return records


def _delisted_records(snapshot: SecurityLifecycleSnapshot) -> dict[str, dict]:
    records = {}
    specs = {
        "sh_delisted": (0, 1, 2, 3, QualityGrade.B),
        "sz_delisted": (0, 1, 2, 3, QualityGrade.A),
    }
    for name, (
        code_position,
        name_position,
        listing_position,
        delisting_position,
        grade,
    ) in specs.items():
        frame = snapshot.tables[name]
        for row in frame.itertuples(index=False, name=None):
            symbol = _symbol_for_code(row[code_position])
            records[symbol] = {
                "display_name": row[name_position],
                "listing_date": pd.to_datetime(
                    row[listing_position], errors="coerce"
                ),
                "delisting_date": pd.to_datetime(
                    row[delisting_position], errors="coerce"
                ),
                "active_at_source_end": False,
                "canonical_symbol": symbol,
                "lifecycle_status": "delisted",
                "lifecycle_quality": grade.value,
                "lifecycle_source": f"akshare/{name}@{snapshot.as_of}",
            }
    return records


def enrich_security_lifecycle(
    frame: pd.DataFrame,
    snapshot: SecurityLifecycleSnapshot,
) -> pd.DataFrame:
    """以交易所当前/退市清单校正上市、退市和换码；不覆盖指数与基金。"""

    result = frame.copy()
    active = _active_records(snapshot)
    delisted = _delisted_records(snapshot)
    for index, row in result[result["asset_type"] == "stock"].iterrows():
        symbol = row["symbol"]
        record = active.get(symbol) or delisted.get(symbol)
        if record is None and symbol.startswith("BJ") and not symbol.startswith("BJ920"):
            migrated_symbol = f"BJ920{symbol[-3:]}"
            if migrated_symbol in active or migrated_symbol in KNOWN_TERMINATIONS:
                record = {
                    "display_name": (
                        active.get(migrated_symbol, {}).get("display_name")
                        or KNOWN_TERMINATIONS.get(migrated_symbol, {}).get(
                            "display_name"
                        )
                    ),
                    "listing_date": row["start_date"],
                    "delisting_date": row["end_date"],
                    "active_at_source_end": False,
                    "canonical_symbol": migrated_symbol,
                    "lifecycle_status": "code_migrated",
                    "lifecycle_quality": QualityGrade.B.value,
                    "lifecycle_source": "北交所920代码切换；Qlib有效区间",
                }
        if record is None and symbol in KNOWN_CODE_MIGRATIONS:
            migration = KNOWN_CODE_MIGRATIONS[symbol]
            record = {
                "display_name": migration["display_name"],
                "listing_date": pd.Timestamp(migration["listing_date"]),
                "delisting_date": row["end_date"],
                "active_at_source_end": False,
                "canonical_symbol": migration["canonical_symbol"],
                "lifecycle_status": "code_migrated",
                "lifecycle_quality": QualityGrade.B.value,
                "lifecycle_source": "交易所换码事件注册表；Qlib有效区间",
            }
        if record is None and symbol in KNOWN_TERMINATIONS:
            termination = KNOWN_TERMINATIONS[symbol]
            record = {
                "display_name": termination["display_name"],
                "listing_date": row["start_date"],
                "delisting_date": pd.Timestamp(termination["delisting_date"]),
                "active_at_source_end": False,
                "canonical_symbol": symbol,
                "lifecycle_status": "delisted",
                "lifecycle_quality": QualityGrade.B.value,
                "lifecycle_source": termination["source"],
            }
        if record is None:
            continue
        for column, value in record.items():
            result.at[index, column] = value

    lifecycle_grade = result["lifecycle_quality"].map(QualityGrade)
    result["quality_grade"] = [
        QualityGrade.worst([base, lifecycle]).value
        for base, lifecycle in zip(result["quality_grade"], lifecycle_grade)
    ]
    return result
