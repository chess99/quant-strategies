"""同步东方财富历史日估值。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.data.store import ResearchDataStore  # noqa: E402
from quant_research.data.valuation import (  # noqa: E402
    densify_baidu_valuation_partitions,
    sync_valuation_partitions,
    verify_valuation_with_baidu,
)


def parse_args():
    parser = argparse.ArgumentParser(description="同步并核验全市场历史估值")
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument(
        "--symbols-from",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--stage",
        choices=["daily", "densify", "verify", "all"],
        default="all",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--verification-sample", type=int, default=20)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = ResearchDataStore(args.data_root)
    master = store.read_parquet("security_master")
    stocks = master[master["asset_type"] == "stock"].copy()
    active = set(
        stocks.loc[stocks["active_at_source_end"].astype(bool), "symbol"].astype(str)
    )
    if args.symbols_from is not None:
        symbols = sorted(
            pd.read_parquet(args.symbols_from)["symbol"].dropna().astype(str).unique()
        )
        active &= set(symbols)
    else:
        symbols = sorted(stocks["symbol"].astype(str).unique())
    if args.limit:
        symbols = symbols[: args.limit]
        active &= set(symbols)
    manifest = None
    statuses = None
    if args.stage == "densify":
        statuses, manifest, report = densify_baidu_valuation_partitions(
            store,
            symbols=symbols,
        )
        print(
            json.dumps(
                {
                    "stage": "densify",
                    "requested_symbols": report["requested_symbols"],
                    "successful_symbols": report["successful_symbols"],
                    "failed_symbols": report["failed_symbols"],
                    "before_rows": report["before_rows"],
                    "after_rows": report["after_rows"],
                    "total_rows": manifest.row_count,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.stage in {"daily", "all"}:
        statuses, manifest = sync_valuation_partitions(
            store,
            symbols,
            active_symbols=active,
            workers=args.workers,
            refresh=args.refresh,
            resume=not args.no_resume,
            checkpoint_every=args.checkpoint_every,
        )
        if args.stage == "daily":
            print(
                json.dumps(
                    {
                        "stage": "daily",
                        "requested_symbols": len(symbols),
                        "successful_symbols": manifest.coverage[
                            "successful_symbols"
                        ],
                        "failed_symbols": manifest.coverage["failed_symbols"],
                        "rows": manifest.row_count,
                        "date_range": manifest.date_range,
                        "current_coverage_ratio": manifest.coverage[
                            "current_coverage_ratio"
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0 if manifest.checks["current_coverage_passed"] else 2
    if statuses is None:
        statuses = store.read_parquet("valuation_sync_status")
    successful = statuses.loc[
        statuses["status"].eq("success") & statuses["symbol"].isin(active),
        "symbol",
    ].tolist()
    if not successful:
        raise RuntimeError("no successful valuation symbols are available")
    sample_size = min(args.verification_sample, len(successful))
    positions = (
        pd.Series(range(sample_size))
        .map(lambda index: round(index * (len(successful) - 1) / max(sample_size - 1, 1)))
        .astype(int)
    )
    sample = [successful[position] for position in positions]
    report = verify_valuation_with_baidu(store, sample)
    print(
        json.dumps(
            {
                "stage": "verify",
                "requested_symbols": report["requested_symbols"],
                "successful_symbols": report["successful_symbols"],
                "failed_symbols": report["failed_symbols"],
                "metrics": report["metrics"],
                "status": report["status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
