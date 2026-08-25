import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_epo_safe_research.py"
SPEC = importlib.util.spec_from_file_location("live_readiness_epo_safe", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_safe_builder_is_identical_when_original_epo_is_valid():
    dates = pd.date_range("2023-01-02", periods=100, freq="B")
    close = pd.DataFrame(
        {
            "A": np.exp(np.arange(100) * 0.004),
            "B": np.exp(np.arange(100) * 0.003 + np.sin(np.arange(100)) * 0.002),
            "C": np.exp(np.arange(100) * 0.002 + np.cos(np.arange(100)) * 0.002),
        },
        index=dates,
    )

    expected, _ = MODULE.original_build_target_weights(
        close,
        dates[-1],
        method="epo",
        momentum_days=34,
        stock_num=3,
        epo_w=0.2,
        price_history_days=1200,
    )
    actual, diagnostics = MODULE.safe_build_target_weights(
        close,
        dates[-1],
        method="epo",
        momentum_days=34,
        stock_num=3,
        epo_w=0.2,
        price_history_days=1200,
    )

    assert actual == pytest.approx(expected)
    assert diagnostics["fallback_used"] is False


def test_safe_builder_equal_weights_only_selected_assets_on_invalid_epo(monkeypatch):
    dates = pd.date_range("2023-01-02", periods=80, freq="B")
    close = pd.DataFrame(
        {
            "A": np.exp(np.arange(80) * 0.004),
            "B": np.exp(np.arange(80) * 0.003),
            "C": np.exp(np.arange(80) * 0.002),
            "D": np.exp(np.arange(80) * -0.001),
        },
        index=dates,
    )

    def fail(*args, **kwargs):
        raise ValueError("EPO produced no positive weights")

    monkeypatch.setattr(MODULE, "original_build_target_weights", fail)
    weights, diagnostics = MODULE.safe_build_target_weights(
        close,
        dates[-1],
        method="epo",
        momentum_days=34,
        stock_num=3,
        epo_w=0.2,
        price_history_days=1200,
    )

    assert weights == pytest.approx({"A": 1 / 3, "B": 1 / 3, "C": 1 / 3})
    assert diagnostics["selected"] == ["A", "B", "C"]
    assert diagnostics["fallback_used"] is True


def test_safe_builder_does_not_swallow_unrelated_errors(monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("insufficient common returns")

    monkeypatch.setattr(MODULE, "original_build_target_weights", fail)
    with pytest.raises(ValueError, match="insufficient common returns"):
        MODULE.safe_build_target_weights(
            pd.DataFrame(),
            pd.Timestamp("2024-01-01"),
            method="epo",
            momentum_days=34,
            stock_num=3,
            epo_w=0.2,
            price_history_days=1200,
        )


def test_protocol_forbids_changed_oos_path():
    protocol = json.loads(MODULE.PROTOCOL_PATH.read_text(encoding="utf-8"))

    assert protocol["change_class"] == "risk_execution_engineering"
    assert protocol["evidence_reuse_rule"]["targets_must_match_exactly"] is True
    assert protocol["evidence_reuse_rule"]["fallback_count_must_equal"] == 0
    assert protocol["R2_gates"]["parameter_completion_rate_min"] == 1.0
    assert protocol["R2_gates"]["fallback_rebalance_share_max"] == 0.2


def test_committed_safe_epo_results_pass_preregistered_r2_gates():
    candidate = STUDY_DIR / "results" / "multi-asset-etf-momentum-epo-safe"
    scorecard = json.loads(
        (candidate / "live-readiness-scorecard.json").read_text(encoding="utf-8")
    )
    robustness = pd.read_csv(candidate / "robustness.csv")

    assert scorecard["status"] == "R2"
    assert all(scorecard["gates"].values())
    assert scorecard["parent_oos_equivalence"] == {
        "equity_max_absolute_difference": pytest.approx(0.0, abs=1e-10),
        "target_count": 28,
        "exact_target_match_count": 28,
        "targets_match_exactly": True,
        "simulation_fallback_count": 0,
        "target_check_fallback_count": 0,
    }
    assert scorecard["parameter_neighborhood_trials"] == 27
    assert scorecard["parameter_completion_rate"] == 1.0
    assert scorecard["parameter_positive_return_rate"] == 1.0
    assert scorecard["parameter_sharpe_ge_0_5_rate"] == 1.0

    neighborhood = robustness[
        robustness["experiment"] == "parameter-neighborhood"
    ]
    assert len(neighborhood) == 27
    assert (neighborhood["status"] == "ok").all()
    assert (neighborhood["annualized_return"] > 0.0).all()
    assert (neighborhood["sharpe"] >= 0.5).all()


def test_committed_safe_epo_manifest_binds_all_research_inputs():
    candidate = STUDY_DIR / "results" / "multi-asset-etf-momentum-epo-safe"
    manifest = json.loads(
        (candidate / "safe-run-manifest.json").read_text(encoding="utf-8")
    )
    protocol_path = candidate / "protocol.json"

    assert manifest["candidate_id"] == "multi-asset-etf-momentum-epo-safe"
    assert manifest["source_sha256"] == MODULE.sha256_file(MODULE.base.SOURCE_PATH)
    assert manifest["engine_sha256"] == MODULE.sha256_file(MODULE_PATH)
    assert manifest["protocol_sha256"] == MODULE.sha256_file(protocol_path)
    assert manifest["parameter_selection_used_parent_oos"] is False
    assert set(manifest["data_manifests"]) == {"etf_daily", "etf_master"}
    for item in manifest["data_manifests"].values():
        path = Path(item["path"])
        assert path.is_file()
        assert item["sha256"] == MODULE.sha256_file(path)


def test_committed_safe_epo_oos_summary_uses_oos_period_metrics():
    candidate = STUDY_DIR / "results" / "multi-asset-etf-momentum-epo-safe"
    summary = pd.read_csv(candidate / "oos.csv").iloc[0]
    equity = pd.read_csv(candidate / "raw" / "safe__oos-equity.csv")
    returns = pd.to_numeric(equity["daily_return"], errors="raise").fillna(0.0)
    values = pd.to_numeric(equity["total_value"], errors="raise")
    initial_value = values.iloc[0] / (1.0 + returns.iloc[0])
    expected = (values.iloc[-1] / initial_value) ** (250.0 / len(values)) - 1.0

    assert summary["annualized_return"] == pytest.approx(expected)
