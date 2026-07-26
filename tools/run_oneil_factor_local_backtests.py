"""批量运行欧奈尔/CANSLIM 月频因子模型的本地回测。"""

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
    / "oneil-canslim-factor-a-share"
    / "local_backtest.py"
)
DEFAULT_QLIB_DIR = Path("D:/code/_open-source/_data/qlib/cn_data")
DEFAULT_FINANCIAL_DIR = Path("D:/code/_open-source/_data/oneil")


def load_engine():
    spec = importlib.util.spec_from_file_location("oneil_factor_local_cli", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError("无法加载本地回测器：{}".format(ENGINE_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_parser():
    parser = argparse.ArgumentParser(
        description="运行欧奈尔/CANSLIM 券商月频因子模型本地回测"
    )
    parser.add_argument("--qlib-dir", type=Path, default=DEFAULT_QLIB_DIR)
    parser.add_argument(
        "--financial-dir", type=Path, default=DEFAULT_FINANCIAL_DIR
    )
    parser.add_argument("--start-date", default="2019-01-01")
    parser.add_argument("--end-date", default="2025-12-31")
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument(
        "--models",
        default="all",
        help="all 或逗号分隔的模型名称",
    )
    parser.add_argument("--run-id", default="local-qlib-eastmoney-2019-2025-v1")
    parser.add_argument("--archived-at")
    parser.add_argument("--no-archive", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main():
    args = build_parser().parse_args()
    warnings.filterwarnings("ignore", category=FutureWarning)
    engine = load_engine()
    common = engine.load_common_engine()
    financial_module = engine.load_financial_engine()
    data = common.QlibBinDataPortal(args.qlib_dir)
    financials = financial_module.FinancialDataPortal(args.financial_dir)
    models = (
        list(engine.SUPPORTED_MODELS)
        if args.models.strip().lower() == "all"
        else [value.strip().lower() for value in args.models.split(",") if value.strip()]
    )
    unknown = sorted(set(models) - set(engine.SUPPORTED_MODELS))
    if unknown:
        raise ValueError("不支持的模型：{}".format(", ".join(unknown)))

    shared_frames = None
    shared_features = {}
    summaries = []
    for model in models:
        config = engine.BacktestConfig(
            start_date=args.start_date,
            end_date=args.end_date,
            model=model,
            initial_cash=args.initial_cash,
            verbose=args.verbose,
        )
        backtester = engine.LocalBacktester(
            data=data,
            financials=financials,
            config=config,
            common=common,
        )
        if shared_frames is not None:
            backtester.frames = shared_frames
        backtester.feature_cache = shared_features
        result = backtester.run()
        shared_frames = backtester.frames
        shared_features = backtester.feature_cache
        summary = {
            "model": model,
            **engine._json_safe(result.metrics),
        }
        summaries.append(summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if not args.no_archive:
            target = engine.archive_result(
                result,
                run_id=args.run_id,
                archived_at=args.archived_at,
            )
            print("归档完成：{}".format(target))

    print("COMPARISON_JSON")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
