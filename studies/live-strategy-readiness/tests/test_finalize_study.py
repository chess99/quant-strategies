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


def test_unified_results_contains_all_candidates_without_r2_overpromotion():
    results = MODULE.build_unified_results()

    assert len(results) == 6
    assert set(results["status"]) == {"R0", "R1"}
    assert not results["status"].isin(["R2", "R3"]).any()
    assert results["candidate_id"].is_unique


def test_platform_control_does_not_promote_candidate_platform_gates():
    audit = MODULE.platform_audit()

    control = audit[audit["candidate_status"].eq("control")].iloc[0]
    candidates = audit[~audit["candidate_status"].eq("control")]
    assert control["platform_status"] == "directionally-reconciled"
    assert not candidates["platform_status"].eq("directionally-reconciled").any()


def test_committed_portfolio_analysis_refuses_an_ineligible_set():
    portfolio = pd.read_csv(STUDY_DIR / "portfolio-analysis.csv").iloc[0]

    assert portfolio["eligible_candidate_count"] == 0
    assert portfolio["status"] == "not-run-no-eligible-candidates"
