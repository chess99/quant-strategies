"""审计安全 EPO 正式源码、本地生产数据覆盖与 R3 外部证据缺口。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STUDY_DIR = Path(__file__).resolve().parent
ROOT = STUDY_DIR.parents[1]
if str(STUDY_DIR) not in sys.path:
    sys.path.insert(0, str(STUDY_DIR))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import run_epo_oos as parent  # noqa: E402


CANDIDATE_ID = "multi-asset-etf-momentum-epo-safe"
CANDIDATE_DIR = STUDY_DIR / "results" / CANDIDATE_ID
PROTOCOL_PATH = CANDIDATE_DIR / "platform-production-protocol.json"
FORMAL_SOURCE = (
    ROOT / "strategies/joinquant/multi-asset-etf-momentum-epo/baseline.py"
)
PARENT_TARGETS = (
    STUDY_DIR
    / "results/multi-asset-etf-momentum-epo/raw/causal-baseline-cost__targets.csv"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_formal_strategy():
    spec = importlib.util.spec_from_file_location("formal_multi_asset_epo", FORMAL_SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def to_local_symbol(symbol: str) -> str:
    code, exchange = symbol.split(".")
    return ("SH" if exchange == "XSHG" else "SZ") + code


def to_joinquant_symbol(symbol: str) -> str:
    prefix, code = symbol[:2], symbol[2:]
    if prefix == "SH":
        return code + ".XSHG"
    if prefix == "SZ":
        return code + ".XSHE"
    raise ValueError("unsupported local symbol: %s" % symbol)


def weight_l1(left: dict[str, float], right: dict[str, float]) -> float:
    symbols = set(left).union(right)
    return float(builtins_sum(abs(left.get(code, 0.0) - right.get(code, 0.0)) for code in symbols))


def builtins_sum(values):
    return sum(values)


def source_preflight(bars: pd.DataFrame, strategy) -> tuple[pd.DataFrame, dict[str, Any]]:
    close = bars.pivot(
        index="trade_date", columns="symbol", values="adjusted_close"
    ).sort_index()
    close = close.rename(columns=to_joinquant_symbol)
    expected_frame = pd.read_csv(PARENT_TARGETS)
    rows = []
    for expected in expected_frame.itertuples(index=False):
        observation = pd.Timestamp(expected.observation_date)
        expected_local = json.loads(expected.weights_json)
        expected_weights = {
            to_joinquant_symbol(symbol): float(weight)
            for symbol, weight in expected_local.items()
        }
        actual, diagnostics = strategy.build_target_weights(close, observation)
        rows.append(
            {
                "trade_date": expected.trade_date,
                "observation_date": expected.observation_date,
                "expected_selected": "|".join(sorted(expected_weights)),
                "actual_selected": "|".join(sorted(actual)),
                "targets_match_exactly": json.dumps(actual, sort_keys=True)
                == json.dumps(expected_weights, sort_keys=True),
                "target_weight_l1": weight_l1(actual, expected_weights),
                "fallback_used": bool(diagnostics.get("fallback_used", False)),
            }
        )
    frame = pd.DataFrame(rows)
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    thresholds = protocol["local_source_preflight_gates"]
    gates = {
        "target_count_gate": len(frame) == thresholds["frozen_oos_target_count"],
        "exact_target_gate": float(frame["targets_match_exactly"].mean())
        >= thresholds["exact_target_match_rate_min"],
        "target_weight_l1_gate": float(frame["target_weight_l1"].mean())
        <= thresholds["target_weight_l1_mean_max"],
        "fallback_gate": int(frame["fallback_used"].sum())
        <= thresholds["fallback_count_on_frozen_oos_max"],
        "self_contained_source_gate": "run_epo_" not in FORMAL_SOURCE.read_text(
            encoding="utf-8"
        ),
    }
    summary = {
        "status": "passed" if all(gates.values()) else "failed",
        "matched_observation_dates": len(frame),
        "exact_target_match_rate": float(frame["targets_match_exactly"].mean()),
        "mean_target_weight_l1": float(frame["target_weight_l1"].mean()),
        "maximum_target_weight_l1": float(frame["target_weight_l1"].max()),
        "fallback_count": int(frame["fallback_used"].sum()),
        "gates": gates,
        "evidence_scope": "local formal-source parity; not real JoinQuant evidence",
    }
    return frame, summary


def production_audit(
    store,
    bars: pd.DataFrame,
    strategy,
    protocol: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    master = store.read_parquet("etf_master")
    local_symbols = [to_local_symbol(symbol) for symbol in strategy.ETF_POOL]
    selected_master = master[master["symbol"].isin(local_symbols)].copy()
    selected_master = selected_master.set_index("symbol")
    grouped = bars.groupby("symbol", sort=True)
    rows = []
    for joinquant_symbol in strategy.ETF_POOL:
        local_symbol = to_local_symbol(joinquant_symbol)
        profile = selected_master.loc[local_symbol]
        history = grouped.get_group(local_symbol).sort_values("trade_date")
        amount = pd.to_numeric(history["amount"], errors="coerce").dropna()
        rows.append(
            {
                "joinquant_symbol": joinquant_symbol,
                "local_symbol": local_symbol,
                "display_name": profile["display_name"],
                "etf_category": profile["etf_category"],
                "listing_date": profile["listing_date"],
                "last_trade_date": profile["last_trade_date"],
                "lifecycle_status": profile["lifecycle_status"],
                "profile_quality_grade": profile["quality_grade"],
                "daily_bar_count": len(history),
                "first_bar_date": history["trade_date"].min(),
                "last_bar_date": history["trade_date"].max(),
                "median_daily_amount": float(amount.median()),
                "p05_daily_amount": float(amount.quantile(0.05)),
                "historical_ohlcv_amount_complete": bool(
                    history[["open", "high", "low", "close", "volume", "amount"]]
                    .notna()
                    .all()
                    .all()
                ),
                "is_qdii": joinquant_symbol
                in protocol["production_data_contract"]["qdii_assets"],
            }
        )
    assets = pd.DataFrame(rows)
    field_rows = [
        {
            "scope": "all-assets",
            "field": "listing_and_delisting_state",
            "status": "available-local-historical-C-not-live",
            "coverage": len(assets),
            "required": len(assets),
            "failure_policy": "block unknown lifecycle",
        },
        {
            "scope": "all-assets",
            "field": "daily_volume_and_amount",
            "status": "available-local-batch-B-not-live",
            "coverage": int(assets["historical_ohlcv_amount_complete"].sum()),
            "required": len(assets),
            "failure_policy": "block capacity estimate when missing",
        },
        {
            "scope": "all-assets",
            "field": "latest_quote_with_timestamp",
            "status": "joinquant-interface-declared-not-observed",
            "coverage": 0,
            "required": len(assets),
            "failure_policy": "no new order on stale quote",
        },
        {
            "scope": "all-assets",
            "field": "paused_state",
            "status": "joinquant-interface-declared-not-observed",
            "coverage": 0,
            "required": len(assets),
            "failure_policy": "cancel rebalance on blocked sell",
        },
        {
            "scope": "all-assets",
            "field": "upper_and_lower_price_limits",
            "status": "joinquant-interface-declared-not-observed",
            "coverage": 0,
            "required": len(assets),
            "failure_policy": "reject limit-locked side",
        },
        {
            "scope": "all-assets",
            "field": "data_quality_status",
            "status": "available-local-manifest-not-live-alerting",
            "coverage": len(assets),
            "required": len(assets),
            "failure_policy": "fail closed below required grade",
        },
    ]
    qdii_fields = protocol["production_data_contract"]["qdii_required_fields"]
    for field in qdii_fields:
        field_rows.append(
            {
                "scope": "qdii",
                "field": field,
                "status": "missing-no-production-feed",
                "coverage": 0,
                "required": len(protocol["production_data_contract"]["qdii_assets"]),
                "failure_policy": protocol["production_data_contract"]["failure_policy"],
            }
        )
    fields = pd.DataFrame(field_rows)
    summary = {
        "historical_asset_count": len(assets),
        "historical_ohlcv_amount_complete_count": int(
            assets["historical_ohlcv_amount_complete"].sum()
        ),
        "qdii_asset_count": int(assets["is_qdii"].sum()),
        "qdii_complete_asset_count": 0,
        "required_qdii_fields": qdii_fields,
        "status": "blocked-missing-live-and-qdii-feeds",
        "static_tracking_target_is_PIT": False,
        "failure_policy": protocol["production_data_contract"]["failure_policy"],
    }
    return assets, fields, summary


def run_audit(data_root: Path | None = None) -> dict[str, Any]:
    strategy = load_formal_strategy()
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    store = parent.ResearchDataStore(data_root)
    bars = parent.load_bars(store)
    preflight, preflight_summary = source_preflight(bars, strategy)
    assets, fields, production_summary = production_audit(
        store, bars, strategy, protocol
    )
    blockers = [
        "real JoinQuant target/order/trade/equity export is absent",
        "QDII premium-discount, subscription and cross-market feeds are absent",
        "frozen forward paper-trading evidence has not started",
    ]
    audit = {
        "schema_version": 1,
        "candidate_id": CANDIDATE_ID,
        "created_at": "2026-08-25",
        "formal_strategy_family": "multi-asset-etf-momentum-epo",
        "formal_source_sha256": sha256_file(FORMAL_SOURCE),
        "local_source_preflight": preflight_summary,
        "real_joinquant_golden": {
            "status": "not-run-no-export",
            "gates": protocol["real_joinquant_golden_gates"],
            "passed": False,
            "reason": "no candidate-specific platform export is present in the repository",
        },
        "production_data": production_summary,
        "candidate_status_after_audit": "R2",
        "eligible_for_R3": False,
        "blocking_gaps_for_R3": blockers,
    }
    CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
    preflight.to_csv(
        CANDIDATE_DIR / "platform-source-preflight.csv",
        index=False,
        encoding="utf-8-sig",
    )
    assets.to_csv(
        CANDIDATE_DIR / "production-asset-audit.csv",
        index=False,
        encoding="utf-8-sig",
    )
    fields.to_csv(
        CANDIDATE_DIR / "production-field-audit.csv",
        index=False,
        encoding="utf-8-sig",
    )
    (CANDIDATE_DIR / "platform-production-audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "candidate_id": CANDIDATE_ID,
        "run_id": "formal-source-and-production-preflight-v1",
        "created_at": "2026-08-25",
        "formal_source_sha256": sha256_file(FORMAL_SOURCE),
        "audit_engine_sha256": sha256_file(Path(__file__).resolve()),
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "parent_target_snapshot_sha256": sha256_file(PARENT_TARGETS),
        "data_manifests": {
            name: {
                "path": str(store.manifest_path(name)),
                "sha256": sha256_file(store.manifest_path(name)),
            }
            for name in ("etf_daily", "etf_master")
        },
        "artifacts": {
            "platform_source_preflight": "platform-source-preflight.csv",
            "production_asset_audit": "production-asset-audit.csv",
            "production_field_audit": "production-field-audit.csv",
            "audit": "platform-production-audit.json",
        },
    }
    (CANDIDATE_DIR / "platform-production-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    conclusion = """# ETF 动量 + EPO：平台与生产数据审计

## 事实

- 正式聚宽源码与冻结 R2 发布后窗口的 28 次目标逐次比较完成；本地预检状态见
  `platform-source-preflight.csv`。这只证明同一份本地行情输入下的源码等价，不是聚宽平台证据。
- 13 只 ETF 的历史 OHLCV、成交额和生命周期可用于本地研究；生命周期主表为 C 级，行情为 B 级。
- 两只 QDII ETF（`513100.XSHG`、`159740.XSHE`）没有带时间戳的 IOPV/NAV、折溢价、申赎状态、
  境外市场会话和汇率生产数据源。
- 仓库中不存在该候选自己的真实聚宽目标、订单、拒单、成交与净值导出。

## 推断

正式源码已经消除了“研究函数与待上传源码不是同一逻辑”的本地风险，但平台数据复权、历史行情返回
形状、订单状态和拒单原因仍未被真实运行验证。QDII 数据缺口意味着策略无法在溢价或申购额度异常时
可靠失败关闭。

## 决定

候选保持 **R2**。可以作为正式研究策略族保存，但不能晋级 R3、不能启动冻结模拟盘，也不能直接
用于实盘。补齐真实聚宽导出和生产数据合同后，必须按已预注册门槛重新审计，不得修改历史参数。
"""
    (CANDIDATE_DIR / "platform-production-conclusion.md").write_text(
        conclusion, encoding="utf-8"
    )
    return audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit = run_audit(args.data_root)
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
