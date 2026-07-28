"""构建全市场公告日财务和申万历史行业数据集。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quant_research.data.financial_statements import (  # noqa: E402
    EastmoneyFinancialStatementProvider,
    sync_financial_statement_partitions,
)
from quant_research.data.industry import import_shenwan_history  # noqa: E402
from quant_research.data.store import ResearchDataStore  # noqa: E402


DEFAULT_INDUSTRY_HISTORY = Path(
    "D:/code/_open-source/_data/quant-research/raw/"
    "swsresearch/industry-history/StockClassifyUse_stock.xls"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="构建全部历史 A 股的东方财富三表和申万历史行业"
    )
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--industry-history", type=Path, default=DEFAULT_INDUSTRY_HISTORY)
    parser.add_argument("--industry-names", type=Path)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--rebuild-normalized",
        action="store_true",
        help="使用既有不可变原始缓存重建全部财务分区，不重新请求数据源",
    )
    parser.add_argument("--skip-financials", action="store_true")
    parser.add_argument("--skip-industry", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    store = ResearchDataStore(args.data_root)
    master = store.read_parquet("security_master")
    summary = {"historical_stocks": int(master["asset_type"].eq("stock").sum())}
    if not args.skip_financials:
        statuses, manifest = sync_financial_statement_partitions(
            store,
            master,
            provider=EastmoneyFinancialStatementProvider(retries=args.retries),
            workers=args.workers,
            refresh=args.refresh,
            resume=not args.rebuild_normalized,
        )
        summary["financials"] = {
            "status_counts": statuses["status"].value_counts().sort_index().to_dict(),
            "coverage": manifest.coverage,
            "checks": manifest.checks,
        }
    if not args.skip_industry:
        names = None
        if args.industry_names:
            names = json.loads(args.industry_names.read_text(encoding="utf-8"))
        _, manifest = import_shenwan_history(
            store,
            args.industry_history,
            master,
            industry_names=names,
        )
        summary["industry"] = {
            "coverage": manifest.coverage,
            "checks": manifest.checks,
        }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
