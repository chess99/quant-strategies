"""同步真实涨跌停价并构建全市场日频交易状态。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.data.market_sync import (  # noqa: E402
    build_market_state_partitions,
    build_official_status_partitions,
    build_price_limit_partitions,
    collect_risk_warning_events,
    collect_szse_st_name_events,
    export_dolt_baostock_status,
    export_dolt_price_limits,
    print_market_sync_summary,
)
from quant_research.data.store import ResearchDataStore  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="同步全市场历史交易状态")
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument(
        "--stage",
        choices=["export", "reference", "events", "state", "all"],
        default="all",
    )
    parser.add_argument(
        "--dolt-exe",
        type=Path,
        default=Path(
            "D:/code/_open-source/_tools/dolt-v2.2.2/"
            "dolt-windows-amd64/bin/dolt.exe"
        ),
    )
    parser.add_argument(
        "--dolt-repository",
        type=Path,
        default=Path("D:/code/_open-source/_data/investment-data-dolt"),
    )
    parser.add_argument(
        "--qlib-root",
        type=Path,
        default=Path("D:/code/_open-source/_data/qlib/cn_data"),
    )
    parser.add_argument("--chunk-rows", type=int, default=250_000)
    parser.add_argument("--checkpoint-every", type=int, default=50)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--refresh-export", action="store_true")
    parser.add_argument("--refresh-notices", action="store_true")
    parser.add_argument("--notice-start", default="2021-11-15")
    parser.add_argument("--notice-workers", type=int, default=12)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument(
        "--reuse-existing-base",
        action="store_true",
        help="复用刚完成的全量状态分区，只重放新增事件并重算清单",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = ResearchDataStore(args.data_root)
    if args.stage in {"export", "reference", "all"}:
        raw_csv, commit = export_dolt_price_limits(
            store,
            dolt_exe=args.dolt_exe,
            repository=args.dolt_repository,
            refresh=args.refresh_export,
        )
        status_csv, status_commit = export_dolt_baostock_status(
            store,
            dolt_exe=args.dolt_exe,
            repository=args.dolt_repository,
            refresh=args.refresh_export,
        )
        if status_commit != commit:
            raise RuntimeError(
                f"Dolt snapshot changed during export: {commit} != {status_commit}"
            )
        if args.stage == "export":
            print_market_sync_summary(
                {
                    "stage": "export",
                    "dolt_commit": commit,
                    "path": str(raw_csv),
                    "bytes": raw_csv.stat().st_size,
                    "status_path": str(status_csv),
                    "status_bytes": status_csv.stat().st_size,
                }
            )
            return 0
    if args.stage in {"reference", "all"}:
        manifest = build_price_limit_partitions(
            store,
            raw_csv,
            commit=commit,
            chunk_rows=args.chunk_rows,
        )
        status_manifest = build_official_status_partitions(
            store,
            status_csv,
            commit=commit,
            chunk_rows=args.chunk_rows,
        )
        _, name_manifest = collect_szse_st_name_events(store)
    if args.stage in {"reference", "events", "all"}:
        calendar = pd.DatetimeIndex(
            pd.to_datetime(
                (args.qlib_root / "calendars" / "day.txt")
                .read_text(encoding="utf-8")
                .splitlines(),
                errors="raise",
            )
        ).normalize()
        _, risk_manifest = collect_risk_warning_events(
            store,
            calendar,
            start=args.notice_start,
            workers=args.notice_workers,
            refresh=args.refresh_notices,
        )
        if args.stage in {"reference", "events"}:
            payload = {
                "stage": args.stage,
                "risk_warning_event_rows": risk_manifest.row_count,
                "risk_warning_announcement_events": risk_manifest.coverage[
                    "announcement_events"
                ],
            }
            if args.stage == "reference":
                payload.update(
                    {
                        "rows": manifest.row_count,
                        "symbols": manifest.coverage["symbols"],
                        "known_st_ratio": manifest.coverage["known_st_ratio"],
                        "official_status_rows": status_manifest.row_count,
                        "official_status_end": status_manifest.date_range["end"],
                        "szse_name_event_rows": name_manifest.row_count,
                    }
                )
            print_market_sync_summary(
                payload
            )
            return 0
    statuses, manifest = build_market_state_partitions(
        store,
        qlib_root=args.qlib_root,
        resume=not args.no_resume,
        reuse_existing_base=args.reuse_existing_base,
        checkpoint_every=args.checkpoint_every,
        limit=args.limit,
    )
    print_market_sync_summary(
        {
            "stage": "state",
            "target_symbols": manifest.coverage["target_symbols"],
            "successful_symbols": manifest.coverage["successful_symbols"],
            "failed_symbols": manifest.coverage["failed_symbols"],
            "rows": manifest.row_count,
            "known_st_ratio": manifest.coverage["known_st_ratio"],
            "exact_limit_ratio": manifest.coverage["exact_limit_ratio"],
            "status_rows": len(statuses),
        }
    )
    return 0 if manifest.coverage["failed_symbols"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
