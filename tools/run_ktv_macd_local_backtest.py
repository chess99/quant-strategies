"""运行 KTV + MACD 基线的本地 Qlib 日线回测并归档结果。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STRATEGY_DIR = ROOT / "strategies" / "joinquant" / "ktv-macd-resonance"
ENGINE_PATH = STRATEGY_DIR / "local_backtest.py"


def load_engine():
    spec = importlib.util.spec_from_file_location("ktv_local_backtest_cli", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载本地回测器：{ENGINE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args():
    parser = argparse.ArgumentParser(
        description="使用本地 Qlib 中国日线数据回测 KTV + MACD 基线"
    )
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("QLIB_CN_DATA_DIR"),
        help="Qlib cn_data 目录；也可设置 QLIB_CN_DATA_DIR",
    )
    parser.add_argument("--start", default="2019-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument(
        "--run-id",
        default="local-qlib-2019-2025-v1",
        help="稳定运行标识；归档目录已存在时不会覆盖",
    )
    parser.add_argument("--archived-at", default=None)
    parser.add_argument("--no-archive", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if not args.data_dir:
        parser.error("--data-dir 或 QLIB_CN_DATA_DIR 必须提供")
    return args


def main():
    args = parse_args()
    engine = load_engine()
    config = engine.BacktestConfig(
        start_date=args.start,
        end_date=args.end,
        initial_cash=args.initial_cash,
        verbose=args.verbose,
    )
    backtester = engine.LocalBacktester(
        data=engine.QlibBinDataPortal(args.data_dir),
        config=config,
    )
    result = backtester.run()
    print(
        json.dumps(
            engine._json_safe(result.metrics),
            ensure_ascii=False,
            indent=2,
        )
    )
    if not args.no_archive:
        target = engine.archive_result(
            result,
            run_id=args.run_id,
            archived_at=args.archived_at,
        )
        print(f"归档完成：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
