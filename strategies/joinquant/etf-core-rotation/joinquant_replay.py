# -*- coding: utf-8 -*-
"""Full weekly JoinQuant Research replay for ETF Core Rotation v1."""

import json
import os
import shutil
from pathlib import Path

import pandas as pd

import baseline as strategy
import joinquant_probe
from research_runner import ResearchRunner, RunnerConfig


RUN_ID = "etf-core-jq-research-open-2014-2026-v1"
DECISIONS = []


def target_weights(context):
    as_of = context.observation_date
    universe, adv20 = strategy.build_risk_universe(as_of)
    if not universe:
        targets = strategy.build_defensive_only_weights(as_of)
        DECISIONS.append(
            {
                "execution_date": context.current_date.isoformat(),
                "observation_date": as_of.isoformat(),
                "universe_count": 0,
                "ranked_count": 0,
                "absolute_momentum_pass_count": 0,
                "selected": "",
                "target_weights": json.dumps(targets, ensure_ascii=False, sort_keys=True),
            }
        )
        return targets
    metrics, close_matrix = strategy.compute_risk_metrics(universe, as_of)
    if metrics is None or metrics.empty:
        targets = strategy.build_defensive_only_weights(as_of)
        selected = []
        ranked = pd.DataFrame()
        passed = pd.DataFrame()
    else:
        ranked = strategy.rank_candidates(metrics)
        passed = ranked[ranked["abs_pass"]].copy()
        selected = strategy.select_assets_with_buffer(context, passed, close_matrix)
        risk_weights = strategy.build_risk_weights(
            selected, ranked, close_matrix, context, adv20
        )
        targets = strategy.add_defensive_sleeve(risk_weights, as_of)
    DECISIONS.append(
        {
            "execution_date": context.current_date.isoformat(),
            "observation_date": as_of.isoformat(),
            "universe_count": len(universe),
            "ranked_count": len(ranked),
            "absolute_momentum_pass_count": len(passed),
            "selected": ";".join(selected),
            "target_weights": json.dumps(targets, ensure_ascii=False, sort_keys=True),
        }
    )
    if len(DECISIONS) % 25 == 0:
        print(
            "REPLAY_PROGRESS {} {}".format(
                len(DECISIONS), context.current_date.isoformat()
            )
        )
    return targets


def run(output_root="exports"):
    del DECISIONS[:]
    joinquant_probe._configure_strategy()
    config = RunnerConfig(
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
        run_id=RUN_ID,
    )
    result = ResearchRunner(config, target_weights).run()
    output = Path(output_root) / config.run_id
    manifest = result.export(
        output,
        strategy_id="etf-core-rotation",
        variant="baseline-research-open-proxy",
        source_path=Path(__file__),
        make_zip=False,
    )
    pd.DataFrame(DECISIONS).to_csv(
        str(output / "raw" / "decisions.csv"), index=False, encoding="utf-8"
    )
    shutil.copy2(strategy.__file__, str(output / "baseline.py"))
    shutil.copy2(joinquant_probe.__file__, str(output / "probe_dependency.py"))
    bundle = shutil.make_archive(str(output), "zip", root_dir=str(output))
    print(json.dumps(manifest["metrics"], ensure_ascii=False, indent=2))
    print("DECISIONS {}".format(len(DECISIONS)))
    print("BUNDLE {}".format(os.path.abspath(bundle)))
    return result, manifest, Path(bundle)


if __name__ == "__main__":
    run()
