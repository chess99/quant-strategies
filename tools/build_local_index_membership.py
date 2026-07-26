"""导入 Qlib 历史指数成分区间。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.data.index_membership import build_index_membership  # noqa: E402
from quant_research.data.store import ResearchDataStore  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description="构建本地历史指数成分数据")
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument(
        "--qlib-instruments-dir",
        type=Path,
        default=Path("D:/code/_open-source/_data/qlib/cn_data/instruments"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = ResearchDataStore(args.data_root)
    data, manifest = build_index_membership(args.qlib_instruments_dir, store)
    print(
        json.dumps(
            {
                "rows": len(data),
                "indexes": data["index_symbol"].value_counts().to_dict(),
                "date_range": manifest.date_range,
                "quality_grade": manifest.quality_grade.value,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
