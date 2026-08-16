# -*- coding: utf-8 -*-
"""Paired JoinQuant Research PIT replay for frozen V2 and its 40/40/20 core."""

import builtins
import json
import os
import shutil
from pathlib import Path

import pandas as pd

import conditional_momentum_overlay_v2 as strategy
from research_runner import ResearchRunner, RunnerConfig


RUN_ID = "etf-core-v2-jq-research-open-2014-2026-v1"
DECISIONS = []


class _StrategyState(object):
    """Explicit state container for JoinQuant Research module imports."""


def configure_strategy():
    # Official backtests inject ``g`` at runtime, while a strategy imported as
    # a normal module in Research does not expose it.  Bind an explicit module
    # global so the exact same strategy functions can be replayed unchanged.
    strategy.g = _StrategyState()
    strategy.g.core_weights = {
        "510300.XSHG": 0.40,
        "511010.XSHG": 0.40,
        "518880.XSHG": 0.20,
    }
    strategy.g.active_sleeve = 0.30
    strategy.g.active_single_symbol_cap = 0.15
    strategy.g.lookbacks = (63, 126, 252)
    strategy.g.minimum_excess_horizons = 2
    strategy.g.minimum_dispersion_iqr = 0.10
    strategy.g.top_k = 3
    strategy.g.rank_buffer = 2
    strategy.g.corr_lookback = 60
    strategy.g.max_pair_corr = 0.90
    strategy.g.min_history_bars = 253
    strategy.g.min_listing_calendar_days = 300
    strategy.g.liquidity_lookback = 20
    strategy.g.min_adv20 = 20_000_000
    strategy.g.min_liquidity_observations = 15
    strategy.g.max_adv_participation = 0.005
    strategy.g.min_trade_value = 2000
    strategy.g.min_weight_change = 0.03
    strategy.g.gold_etf = "518880.XSHG"
    strategy.g.hurdle_bond = "511010.XSHG"
    strategy.g.cash_etf = "511880.XSHG"
    strategy.g.defensive_bond_etfs = ["511010.XSHG", "511260.XSHG"]
    strategy.g.exclude_keywords = [
        "货币", "现金", "短融", "国债", "政金债", "信用债", "债券", "转债",
        "同业存单", "城投债", "地方债", "公司债",
        "黄金", "白银", "原油", "豆粕", "商品",
        "纳指", "纳斯达克", "标普", "道琼斯", "日经", "德国", "法国", "沙特",
        "恒生", "港股", "香港", "中概", "H股", "海外", "中韩",
        "REIT", "Reit", "reit",
    ]
    strategy.g.last_selected = []
    strategy.g.last_universe = []
    strategy.g.last_adv20 = {}


def v2_target_weights(context):
    as_of = context.observation_date
    universe, adv20 = strategy.build_risk_universe(as_of)
    ranked = pd.DataFrame()
    selected = []
    diagnostics = {
        "dispersion_iqr": float("nan"),
        "dispersion_gate_open": False,
        "excess_pass_count": 0,
    }
    if universe:
        metrics, close_matrix = strategy.compute_risk_metrics(universe, as_of)
        if metrics is not None and not metrics.empty:
            ranked = strategy.rank_candidates(metrics)
            ranked, diagnostics = strategy.add_conditional_gates(ranked, as_of)
            if diagnostics["dispersion_gate_open"]:
                passed = ranked[ranked["excess_pass"]].copy()
                selected = strategy.select_assets_with_buffer(passed, close_matrix)
    active = strategy.build_active_weights(selected, ranked, context, adv20)
    targets = strategy.compose_core_and_active(active)
    strategy.g.last_selected = list(selected)
    DECISIONS.append(
        {
            "execution_date": context.current_date.isoformat(),
            "observation_date": as_of.isoformat(),
            "universe_count": len(universe),
            "ranked_count": len(ranked),
            "excess_pass_count": diagnostics["excess_pass_count"],
            "dispersion_iqr": diagnostics["dispersion_iqr"],
            "dispersion_gate_open": diagnostics["dispersion_gate_open"],
            "selected": ";".join(selected),
            "active_target_weight": builtins.sum(active.values()),
            "target_weights": json.dumps(targets, ensure_ascii=False, sort_keys=True),
        }
    )
    if len(DECISIONS) % 25 == 0:
        print("V2_REPLAY_PROGRESS {} {}".format(len(DECISIONS), context.current_date))
    return targets


def core_target_weights(context):
    return dict(strategy.g.core_weights)


def runner_config(run_id):
    return RunnerConfig(
        start_date="2014-01-02",
        end_date="2026-07-24",
        initial_cash=1000000,
        frequency="weekly",
        schedule_when="first",
        execution_price="open",
        price_adjustment="pre",
        lot_size=100,
        buy_commission=0.0003,
        sell_commission=0.0003,
        minimum_commission=5.0,
        stamp_tax=0.0,
        buy_slippage=0.001,
        sell_slippage=0.001,
        reject_st=True,
        reject_unknown_state=True,
        run_id=run_id,
    )


def run(output_root="exports"):
    del DECISIONS[:]
    configure_strategy()
    root = Path(output_root) / RUN_ID
    v2_config = runner_config(RUN_ID + "-v2")
    v2_result = ResearchRunner(v2_config, v2_target_weights).run()
    v2_manifest = v2_result.export(
        root / "v2",
        strategy_id="etf-core-rotation",
        variant="conditional-momentum-overlay-v2-research-open-proxy",
        source_path=Path(__file__),
        make_zip=False,
    )
    pd.DataFrame(DECISIONS).to_csv(
        str(root / "v2" / "raw" / "decisions.csv"),
        index=False,
        encoding="utf-8",
    )
    shutil.copy2(strategy.__file__, str(root / "v2" / "strategy.py"))

    core_config = runner_config(RUN_ID + "-core")
    core_result = ResearchRunner(core_config, core_target_weights).run()
    core_manifest = core_result.export(
        root / "core",
        strategy_id="etf-core-rotation",
        variant="strategic-core-40-40-20-research-open-proxy",
        source_path=Path(__file__),
        make_zip=False,
    )
    comparison = {
        "schema_version": 1,
        "v2": v2_manifest["metrics"],
        "core": core_manifest["metrics"],
        "annualized_excess": (
            v2_manifest["metrics"]["annualized_return"]
            - core_manifest["metrics"]["annualized_return"]
        ),
        "decision_count": len(DECISIONS),
    }
    (root / "comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    bundle = shutil.make_archive(str(root), "zip", root_dir=str(root))
    print(json.dumps(comparison, ensure_ascii=False, indent=2))
    print("BUNDLE {}".format(os.path.abspath(bundle)))
    return v2_result, core_result, comparison, Path(bundle)


if __name__ == "__main__":
    run()
