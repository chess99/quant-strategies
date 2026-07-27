"""构建完整场内 ETF 候选池、逐只日线、档案和覆盖率报告。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.data.etf_sync import (  # noqa: E402
    collect_etf_source_snapshot,
    finalize_etf_master,
    print_sync_summary,
    sync_etf_daily,
    write_etf_candidates,
)
from quant_research.data.store import ResearchDataStore  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="同步全市场 ETF 历史主表与分区日线"
    )
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument(
        "--stage",
        choices=["sources", "daily", "finalize", "all"],
        default="all",
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--history-start", default="2013-01-01")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def _source_end(store: ResearchDataStore):
    import pandas as pd

    payload = store.read_manifest("etf_candidates")
    return pd.Timestamp(payload["date_range"]["end"])


def main() -> int:
    args = parse_args()
    store = ResearchDataStore(args.data_root)
    candidate_manifest = None
    if args.stage in {"sources", "all"}:
        calendar = store.read_parquet("trading_calendar")["trade_date"]
        snapshot = collect_etf_source_snapshot(
            store,
            calendar,
            history_start=args.history_start,
            attempts=args.attempts,
        )
        candidates, candidate_manifest = write_etf_candidates(store, snapshot)
        if args.stage == "sources":
            print_sync_summary(
                {
                    "stage": "sources",
                    "candidate_count": len(candidates),
                    "expected_active": int(candidates["expected_active"].sum()),
                    "source_end": snapshot.source_end.strftime("%Y-%m-%d"),
                }
            )
            return 0
    else:
        candidates = store.read_parquet("etf_candidates")

    if args.stage in {"daily", "all"}:
        statuses, profiles, daily_manifest = sync_etf_daily(
            store,
            candidates,
            workers=args.workers,
            attempts=args.attempts,
            resume=not args.no_resume,
            checkpoint_every=args.checkpoint_every,
        )
        if args.stage == "daily":
            print_sync_summary(
                {
                    "stage": "daily",
                    "candidate_count": len(candidates),
                    "attempted_count": len(statuses),
                    "successful_symbols": daily_manifest.coverage[
                        "successful_symbols"
                    ],
                    "empty_symbols": daily_manifest.coverage["empty_symbols"],
                    "failed_symbols": daily_manifest.coverage["failed_symbols"],
                }
            )
            return 0
    else:
        statuses = store.read_parquet("etf_sync_status")
        profiles = store.read_parquet("etf_profiles")

    if candidate_manifest is None:
        candidate_manifest = store.read_manifest("etf_candidates")
    master, manifest, report_path = finalize_etf_master(
        store,
        candidates,
        statuses,
        profiles,
        source_end=_source_end(store),
        candidate_manifest=candidate_manifest,
    )
    print_sync_summary(
        {
            "stage": "finalize",
            "candidate_count": len(master),
            "current_expected": manifest.coverage["current_expected"],
            "current_with_daily_history": manifest.coverage[
                "current_with_daily_history"
            ],
            "current_coverage_ratio": manifest.coverage[
                "current_coverage_ratio"
            ],
            "coverage_target_passed": manifest.checks[
                "current_coverage_passed"
            ],
            "report": str(report_path),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
