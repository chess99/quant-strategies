"""重建证券主表、交易日历并运行全平台覆盖率审计。"""

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

from quant_research.data.audit import build_platform_coverage_report  # noqa: E402
from quant_research.data.calendar import build_trading_calendar  # noqa: E402
from quant_research.data.etf_universe import etf_security_supplemental  # noqa: E402
from quant_research.data.security_master import build_security_master  # noqa: E402
from quant_research.data.security_lifecycle import (  # noqa: E402
    load_latest_security_lifecycle_snapshot,
    sync_security_lifecycle_snapshot,
)
from quant_research.data.store import ResearchDataStore, sha256_file  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--qlib-root",
        type=Path,
        default=Path("D:/code/_open-source/_data/qlib/cn_data"),
    )
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument(
        "--refresh-lifecycle",
        action="store_true",
        help="从公开交易所接口抓取新的证券生命周期快照",
    )
    return parser.parse_args()


def _existing_supplemental_master(store: ResearchDataStore):
    master_path = store.normalized_path("security_master")
    if not master_path.is_file():
        return None, []
    current = store.read_parquet("security_master")
    supplemental = current[current["asset_type"].isin(["etf", "fund"])].copy()
    sources = []
    etf_master_path = store.normalized_path("etf_master")
    if etf_master_path.is_file():
        etf_manifest = store.read_manifest("etf_master")
        etf_master = store.read_parquet("etf_master")
        etf = etf_security_supplemental(
            etf_master,
            source_end=etf_manifest["date_range"]["end"],
        )
        funds = supplemental[supplemental["asset_type"] == "fund"].copy()
        supplemental = pd.concat([funds, etf], ignore_index=True)
        path = store.manifest_path("etf_master")
        sources.append(
            {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    for dataset in ("etf_daily", "fund_daily"):
        path = store.manifest_path(dataset)
        if path.is_file():
            sources.append(
                {
                    "path": str(path),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    return supplemental, sources


def main() -> int:
    args = parse_args()
    qlib_root = args.qlib_root.resolve()
    store = ResearchDataStore(args.data_root)
    lifecycle_snapshot = (
        sync_security_lifecycle_snapshot(store)
        if args.refresh_lifecycle
        else load_latest_security_lifecycle_snapshot(store)
    )
    supplemental, supplemental_sources = _existing_supplemental_master(store)
    master, master_manifest = build_security_master(
        qlib_root / "instruments" / "all.txt",
        store,
        supplemental=supplemental,
        supplemental_sources=supplemental_sources,
        lifecycle_snapshot=lifecycle_snapshot,
    )
    calendar, calendar_manifest = build_trading_calendar(
        qlib_root / "calendars" / "day.txt",
        store,
    )
    report = build_platform_coverage_report(store, qlib_root)
    summary = {
        "data_root": str(store.root),
        "security_master": {
            "rows": len(master),
            "asset_type_counts": master_manifest.coverage["asset_type_counts"],
            "manifest": str(store.manifest_path("security_master")),
        },
        "trading_calendar": {
            "sessions": len(calendar),
            "date_range": calendar_manifest.date_range,
            "manifest": str(store.manifest_path("trading_calendar")),
        },
        "platform_coverage": {
            "status": report["status"],
            "qlib_expected_instruments": report["qlib_daily_features"][
                "expected_instruments"
            ],
            "qlib_successful_instruments": report["qlib_daily_features"][
                "successful_instruments"
            ],
            "report": str(store.manifest_path("platform_coverage")),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if report["status"] != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
