"""初始化外部研究数据目录并导入 Qlib 证券主表。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_research.data.security_master import build_security_master  # noqa: E402
from quant_research.data.store import ResearchDataStore  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description="构建本地研究证券主表")
    parser.add_argument(
        "--qlib-all",
        type=Path,
        default=Path(
            "D:/code/_open-source/_data/qlib/cn_data/instruments/all.txt"
        ),
    )
    parser.add_argument("--data-root", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = ResearchDataStore(args.data_root)
    frame, manifest = build_security_master(args.qlib_all, store)
    summary = {
        "data_root": str(store.root),
        "rows": len(frame),
        "asset_types": frame["asset_type"].value_counts().to_dict(),
        "date_range": manifest.date_range,
        "manifest": str(store.manifest_path("security_master")),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
