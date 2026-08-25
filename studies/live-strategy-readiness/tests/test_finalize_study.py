import importlib.util
import sys
from pathlib import Path

import pandas as pd


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "finalize_study.py"
SPEC = importlib.util.spec_from_file_location("finalize_live_readiness", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_unified_results_contains_every_completed_candidate_and_only_one_r2():
    results = MODULE.build_unified_results()

    assert len(results) == 15
    assert results["status"].value_counts().to_dict() == {
        "R1": 10,
        "R0": 4,
        "R2": 1,
    }
    assert results["candidate_id"].is_unique
    safe = results[results["candidate_id"].eq("multi-asset-etf-momentum-epo-safe")].iloc[0]
    assert safe["status"] == "R2"
    assert safe["formal_source_sha256"]
    assert safe["platform_status"] == "local-source-preflight-passed"
    assert safe["production_data_status"] == "blocked-missing-live-and-qdii-feeds"
    assert not results["status"].isin(["R3", "R4", "R5"]).any()


def test_platform_control_does_not_promote_candidate_platform_gates():
    audit = MODULE.platform_audit()

    control = audit[audit["candidate_status"].eq("control")].iloc[0]
    safe = audit[
        audit["candidate_id"].eq("multi-asset-etf-momentum-epo-safe")
    ].iloc[0]
    assert control["platform_status"] == "directionally-reconciled"
    assert safe["platform_status"] == "local-source-preflight-passed"
    assert safe["local_exact_target_match_ratio"] == 1.0
    assert safe["real_joinquant_export_present"] is False
    assert safe["eligible_for_R3"] is False


def test_committed_portfolio_analysis_keeps_single_r2_out_of_a_fake_portfolio():
    portfolio = pd.read_csv(STUDY_DIR / "portfolio-analysis.csv").iloc[0]

    assert portfolio["eligible_candidate_count"] == 1
    assert portfolio["status"] == "analyzed-single-r2-no-multi-strategy-portfolio"
    assert portfolio["eligible_candidates"] == "multi-asset-etf-momentum-epo-safe"
    assert -1.0 <= portfolio["simple_core_return_correlation"] <= 1.0
    assert portfolio["candidate_historical_sharpe"] > 0.0
    assert portfolio["candidate_plus_core_sharpe"] > 0.0
    assert not bool(portfolio["proposed_frozen_portfolio"])
