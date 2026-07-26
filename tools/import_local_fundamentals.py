"""导入公告日财务缓存和当前行业代理。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.data.fundamentals import import_fundamentals  # noqa: E402
from quant_research.data.industry import import_current_industry  # noqa: E402
from quant_research.data.store import ResearchDataStore  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description="导入本地公告日财务与行业快照")
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("D:/code/_open-source/_data/oneil"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = ResearchDataStore(args.data_root)
    fundamentals, quarantine, fundamental_manifest = import_fundamentals(
        store,
        args.source_dir / "financials.parquet",
        args.source_dir / "metadata.json",
    )
    industry, industry_manifest = import_current_industry(
        store,
        args.source_dir / "industries.csv",
        args.source_dir / "metadata.json",
    )
    print(
        json.dumps(
            {
                "fundamental_rows": len(fundamentals),
                "fundamental_symbols": int(fundamentals["symbol"].nunique()),
                "quarantined_rows": len(quarantine),
                "fundamental_quality": fundamental_manifest.quality_grade.value,
                "industry_rows": len(industry),
                "industry_quality": industry_manifest.quality_grade.value,
                "industry_observed_date": industry_manifest.date_range["start"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
