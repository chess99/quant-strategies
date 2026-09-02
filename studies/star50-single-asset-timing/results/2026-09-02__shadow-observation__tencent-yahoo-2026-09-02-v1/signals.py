"""计算科创 50 ETF 两个冻结影子模型的下一交易日目标。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd


SOURCE_PATH = Path(__file__).resolve()
EXTENSION_PATH = SOURCE_PATH.with_name("run_live_extension.py")
FROZEN_CONFIG_NAMES = (
    "risk-friction__threshold-0p05",
    "production-ensemble__threshold-0p1",
)


def _load_extension():
    spec = importlib.util.spec_from_file_location("star50_live_extension_shadow", EXTENSION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载科创 50 实盘扩展模块")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


extension = _load_extension()
engine = extension.engine


def frozen_configs():
    registry = {config.name: config for config in extension.build_production_configs()}
    missing = set(FROZEN_CONFIG_NAMES).difference(registry)
    if missing:
        raise RuntimeError(f"冻结影子配置缺失：{sorted(missing)}")
    return [registry[name] for name in FROZEN_CONFIG_NAMES]


def compute_shadow_snapshot(frame: pd.DataFrame) -> dict:
    if len(frame) < 260:
        raise ValueError("行情长度不足以计算冻结影子信号")
    if frame.index.duplicated().any() or not frame.index.is_monotonic_increasing:
        raise ValueError("行情日期必须唯一且递增")
    if set(frame["symbol"].astype(str)) != {engine.SYMBOL}:
        raise ValueError("输入只能包含 SH588000")
    models = []
    for config in frozen_configs():
        target = extension.generate_production_target(frame, config)
        changes = target.ne(target.shift(1))
        current = float(target.iloc[-1])
        previous = float(target.iloc[-2])
        if current > previous + 1e-12:
            action = "increase"
        elif current < previous - 1e-12:
            action = "decrease"
        else:
            action = "hold"
        models.append(
            {
                "config": config.name,
                "objective": config.objective,
                "params": config.params,
                "target_weight": current,
                "previous_target_weight": previous,
                "action": action,
                "last_target_change": target.index[changes].max().strftime("%Y-%m-%d"),
            }
        )
    return {
        "schema_version": 1,
        "symbol": engine.SYMBOL,
        "status": "shadow_only",
        "evidence_class": "post_selection_historical_development",
        "observation_date": pd.Timestamp(frame.index.max()).strftime("%Y-%m-%d"),
        "data": {
            "sessions": len(frame),
            "source": frame.attrs.get("source", "archived_input"),
            "maximum_ohlc_relative_error": frame.attrs.get("maximum_ohlc_relative_error"),
            "median_volume_relative_error": frame.attrs.get("median_volume_relative_error"),
        },
        "models": models,
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", type=Path, default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        frame = (
            engine.load_input_csv(args.input_csv)
            if args.input_csv is not None
            else engine.fetch_market_data(args.end_date)
        )
        snapshot = compute_shadow_snapshot(frame)
    except (KeyError, OSError, TimeoutError, ValueError) as exc:
        snapshot = {
            "schema_version": 1,
            "symbol": engine.SYMBOL,
            "status": "halted",
            "stage": "market_data_or_signal",
            "requested_end_date": args.end_date,
            "error_type": type(exc).__name__,
            "reason": str(exc),
            "models": [],
        }
        text = json.dumps(engine._json_safe(snapshot), ensure_ascii=False, indent=2) + "\n"
        if args.output is not None:
            args.output.write_text(text, encoding="utf-8")
        print(text, end="")
        return 2
    text = json.dumps(engine._json_safe(snapshot), ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
