"""为 KTV + MACD 本地回测生成逐持仓 MFE/MAE 路径诊断。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
STRATEGY_DIR = ROOT / "strategies" / "joinquant" / "ktv-macd-resonance"
ENGINE_PATH = STRATEGY_DIR / "local_backtest.py"
DIAGNOSTICS_PATH = STRATEGY_DIR / "trade_diagnostics.py"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args():
    parser = argparse.ArgumentParser(
        description="生成 KTV + MACD 逐持仓 MFE/MAE 与退出后路径"
    )
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("QLIB_CN_DATA_DIR"),
        help="Qlib cn_data 目录；也可设置 QLIB_CN_DATA_DIR",
    )
    parser.add_argument("--archive-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--forward-days", type=int, default=10)
    args = parser.parse_args()
    if not args.data_dir:
        parser.error("--data-dir 或 QLIB_CN_DATA_DIR 必须提供")
    return args


def main():
    args = parse_args()
    archive = Path(args.archive_dir).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    manifest = json.loads(
        (archive / "manifest.json").read_text(encoding="utf-8")
    )
    engine = load_module("ktv_path_engine", ENGINE_PATH)
    diagnostics = load_module("ktv_trade_diagnostics_cli", DIAGNOSTICS_PATH)
    logic = engine.load_baseline_logic(archive / manifest["source_file"])
    round_trips = pd.read_csv(
        archive / manifest["artifacts"]["round_trips"],
        parse_dates=["entry_date", "exit_date"],
    )
    trades = pd.read_csv(
        archive / manifest["artifacts"]["trades"],
        parse_dates=["date", "observation_date"],
    )
    result = diagnostics.analyze_trade_paths(
        engine.QlibBinDataPortal(args.data_dir),
        logic,
        round_trips,
        trades,
        end_date=manifest["period"]["end"],
        forward_days=args.forward_days,
    )
    if output.exists():
        raise FileExistsError(f"输出文件已存在：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False, encoding="utf-8")
    closed = result.loc[result["status"].eq("closed")]
    summary = {
        "source_archive": str(archive),
        "output": str(output),
        "rows": int(len(result)),
        "closed_rows": int(len(closed)),
        "median_mfe": float(closed["mfe"].median()),
        "median_mae": float(closed["mae"].median()),
        "median_post_exit_close_return_10": float(
            closed["post_exit_close_return_10"].median()
        ),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
