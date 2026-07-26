"""诊断指定股票在欧奈尔月频因子模型中的逐月门控。"""

import argparse
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = (
    ROOT
    / "strategies"
    / "joinquant"
    / "oneil-canslim-factor-a-share"
    / "local_backtest.py"
)
DEFAULT_SYMBOLS = (
    "SH688525",  # 佰维存储
    "SZ301308",  # 江波龙
    "SH603986",  # 兆易创新
    "SH688008",  # 澜起科技
    "SZ300857",  # 协创数据
    "SZ002371",  # 北方华创
    "SH688041",  # 海光信息
    "SH688256",  # 寒武纪
)


def load_engine():
    spec = importlib.util.spec_from_file_location("oneil_factor_gate_cli", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError("无法加载本地回测器：{}".format(ENGINE_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_parser():
    parser = argparse.ArgumentParser(description="诊断欧奈尔因子逐月门控")
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default="2025-12-31")
    parser.add_argument(
        "--symbols",
        default=",".join(DEFAULT_SYMBOLS),
        help="逗号分隔的 Qlib 股票代码",
    )
    parser.add_argument(
        "--qlib-dir",
        type=Path,
        default=Path("D:/code/_open-source/_data/qlib/cn_data"),
    )
    parser.add_argument(
        "--financial-dir",
        type=Path,
        default=Path("D:/code/_open-source/_data/oneil"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verbose", action="store_true")
    return parser


def _finite_ge(value, threshold):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(value) and value >= threshold)


def main():
    args = build_parser().parse_args()
    engine = load_engine()
    common = engine.load_common_engine()
    financial_module = engine.load_financial_engine()
    data = common.QlibBinDataPortal(args.qlib_dir)
    financials = financial_module.FinancialDataPortal(args.financial_dir)
    config = engine.BacktestConfig(
        start_date=args.start_date,
        end_date=args.end_date,
        verbose=args.verbose,
    )
    backtester = engine.LocalBacktester(
        data=data,
        financials=financials,
        config=config,
        common=common,
    )
    backtester._prepare_frames()
    symbols = [
        value.strip().upper() for value in args.symbols.split(",") if value.strip()
    ]
    trade_dates = data.trade_dates(args.start_date, args.end_date)
    rows = []
    for trade_date in sorted(engine.monthly_rebalance_dates(trade_dates)):
        observation_date = data.previous_trade_date(trade_date)
        members = set(backtester._members(observation_date))
        features = backtester._features(observation_date)
        for symbol in symbols:
            record = {
                "observation_date": observation_date,
                "trade_date": trade_date,
                "symbol": symbol,
                "name": financials.name(symbol),
                "industry": financials.industry(symbol),
                "in_universe": symbol in members,
            }
            if symbol not in features.index:
                record["feature_available"] = False
                rows.append(record)
                continue
            feature = features.loc[symbol].to_dict()
            record.update(feature)
            record["feature_available"] = True
            record["hc2019_c_eps"] = _finite_ge(record["eps_growth"], 0.18)
            record["hc2019_c_revenue"] = _finite_ge(
                record["revenue_growth"], 0.25
            )
            record["hc2019_a"] = bool(
                _finite_ge(record["annual_cagr"], 0.15)
                and record["annual_positive_path"]
            )
            record["hc2019_l"] = _finite_ge(record["rps"], 80.0)
            record["hc2019_new_high"] = _finite_ge(
                record["high_proximity"], 0.95
            )
            record["hc2019_pass"] = bool(
                record["hc2019_c_eps"]
                and record["hc2019_c_revenue"]
                and record["hc2019_a"]
                and record["hc2019_l"]
                and record["hc2019_new_high"]
                and record["liquid"]
            )
            record["hc2_growth_top20"] = _finite_ge(
                record["growth_percentile"], 80.0
            )
            record["hc2_momentum_top20"] = _finite_ge(
                record["momentum_percentile"], 80.0
            )
            record["hc2_pass"] = bool(
                record["hc2_growth_top20"]
                and record["hc2_momentum_top20"]
                and record["liquid"]
            )
            record["adaptive_pass"] = bool(
                (
                    _finite_ge(record["profit_growth"], 0.20)
                    or _finite_ge(record["eps_growth"], 0.20)
                )
                and _finite_ge(record["revenue_growth"], 0.15)
                and _finite_ge(record["momentum_percentile"], 70.0)
                and _finite_ge(record["high_proximity"], 0.85)
                and record["liquid"]
            )
            record["cycle_turnaround_top20"] = _finite_ge(
                record.get("turnaround_percentile"), 80.0
            )
            record["cycle_pass"] = bool(
                _finite_ge(record.get("profit_current"), 0.0)
                and float(record.get("profit_current", 0.0)) > 0.0
                and record["cycle_turnaround_top20"]
                and _finite_ge(record["revenue_growth"], 0.15)
                and _finite_ge(record["momentum_percentile"], 70.0)
                and _finite_ge(record["high_proximity"], 0.80)
                and record["liquid"]
            )
            rows.append(record)
    result = pd.DataFrame(rows)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(args.output, index=False, encoding="utf-8-sig")
        print("已写入：{}".format(args.output))
    summary_columns = [
        "symbol",
        "name",
        "in_universe",
        "feature_available",
        "hc2019_c_eps",
        "hc2019_c_revenue",
        "hc2019_a",
        "hc2019_l",
        "hc2019_new_high",
        "hc2019_pass",
        "hc2_growth_top20",
        "hc2_momentum_top20",
        "hc2_pass",
        "adaptive_pass",
        "cycle_turnaround_top20",
        "cycle_pass",
    ]
    available_columns = [
        column for column in summary_columns if column not in {"symbol", "name"}
        and column in result
    ]
    summary = result.groupby(["symbol", "name"], dropna=False)[
        available_columns
    ].agg(lambda values: int(values.astype(str).str.lower().eq("true").sum()))
    print(summary.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
