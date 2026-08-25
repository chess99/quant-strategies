import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_epo_supplemental_robustness.py"
SPEC = importlib.util.spec_from_file_location("live_readiness_epo_supplemental", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_placebo_plan_is_deterministic_and_uses_prior_session_observations():
    calendar = pd.date_range("2024-01-02", "2024-06-28", freq="B")

    first = MODULE.randomized_monthly_plan(calendar, seed=20260825)
    second = MODULE.randomized_monthly_plan(calendar, seed=20260825)

    assert first == second
    assert len(first) == 6
    for item in first:
        assert item["observation_date"] < item["execution_date"]
        assert (
            calendar.get_loc(item["execution_date"]) - calendar.get_loc(item["observation_date"])
            == 1
        )


def test_committed_walk_forward_uses_only_prior_years_for_selection():
    candidate = STUDY_DIR / "results" / "multi-asset-etf-momentum-epo-safe"
    walk = pd.read_csv(candidate / "supplemental-walk-forward.csv")

    assert set(walk["test_year"]) == {2023, 2024, 2025, 2026}
    assert len(walk) == 4
    assert (pd.to_datetime(walk["train_end"]).dt.year < walk["test_year"]).all()
    assert (~walk["selected_variant"].isna()).all()


def test_committed_regime_and_placebo_artifacts_cover_preregistered_scope():
    candidate = STUDY_DIR / "results" / "multi-asset-etf-momentum-epo-safe"
    regime = pd.read_csv(candidate / "supplemental-regime-attribution.csv")
    placebo = pd.read_csv(candidate / "supplemental-placebo.csv")
    score = json.loads(
        (candidate / "supplemental-robustness-scorecard.json").read_text(encoding="utf-8")
    )

    assert {"bull", "bear", "sideways"}.issubset(set(regime["segment"]))
    assert {"liquidity-contraction", "extreme-market-day"}.issubset(set(regime["segment"]))
    assert len(placebo) == 24
    assert (placebo["status"] == "ok").all()
    assert score["status_after_supplement"] == ("R2" if all(score["gates"].values()) else "R1")
    assert score["historical_parameters_changed"] is False


def test_supplemental_manifest_binds_engine_protocol_and_inputs():
    candidate = STUDY_DIR / "results" / "multi-asset-etf-momentum-epo-safe"
    manifest = json.loads(
        (candidate / "supplemental-robustness-manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["candidate_id"] == "multi-asset-etf-momentum-epo-safe"
    assert manifest["engine_sha256"] == MODULE.sha256_file(MODULE_PATH)
    assert manifest["protocol_sha256"] == MODULE.sha256_file(MODULE.PROTOCOL_PATH)
    assert manifest["parameter_returns_sha256"] == MODULE.sha256_file(MODULE.PARAMETER_RETURNS_PATH)
    assert manifest["baseline_equity_sha256"] == MODULE.sha256_file(MODULE.BASELINE_EQUITY_PATH)
    assert set(manifest["data_manifests"]) == {"etf_daily", "etf_master"}
