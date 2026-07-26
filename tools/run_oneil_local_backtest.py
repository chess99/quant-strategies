"""运行欧奈尔 CAN SLIM 基线的本地 Qlib + 东方财富回测。"""

import argparse
import importlib.util
import json
import warnings
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = (
    ROOT
    / "strategies"
    / "joinquant"
    / "oneil-canslim-a-share"
    / "local_backtest.py"
)
DEFAULT_QLIB_DIR = Path("D:/code/_open-source/_data/qlib/cn_data")
DEFAULT_FINANCIAL_DIR = Path("D:/code/_open-source/_data/oneil")


def load_engine():
    spec = importlib.util.spec_from_file_location("oneil_local_cli", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载本地回测器：{ENGINE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_parser():
    parser = argparse.ArgumentParser(
        description="使用本地 Qlib 与东方财富财务缓存回测欧奈尔 CAN SLIM 基线"
    )
    parser.add_argument("--qlib-dir", type=Path, default=DEFAULT_QLIB_DIR)
    parser.add_argument(
        "--financial-dir", type=Path, default=DEFAULT_FINANCIAL_DIR
    )
    parser.add_argument("--start-date", default="2019-01-01")
    parser.add_argument("--end-date", default="2025-12-31")
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument(
        "--run-id", default="local-qlib-eastmoney-2019-2025-v1"
    )
    parser.add_argument("--archived-at")
    parser.add_argument("--no-archive", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main():
    args = build_parser().parse_args()
    warnings.filterwarnings(
        "ignore",
        category=FutureWarning,
        message="The default fill_method='pad' in Series.pct_change.*",
    )
    engine = load_engine()
    common = engine.load_common_engine()
    config = engine.BacktestConfig(
        start_date=args.start_date,
        end_date=args.end_date,
        initial_cash=args.initial_cash,
        verbose=args.verbose,
    )
    backtester = engine.LocalBacktester(
        data=common.QlibBinDataPortal(args.qlib_dir),
        financials=engine.FinancialDataPortal(args.financial_dir),
        config=config,
        common=common,
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
