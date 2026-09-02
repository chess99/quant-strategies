from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_shadow_signals.py"
INPUT_PATH = (
    STUDY_DIR
    / "results"
    / "2026-09-01__walk-forward-technical-families__tencent-yahoo-2020-2026-v1"
    / "raw"
    / "input-sh588000.csv"
)


def load_module():
    spec = importlib.util.spec_from_file_location("star50_shadow_signals_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_frozen_shadow_snapshot_matches_archived_observation():
    module = load_module()
    frame = module.engine.load_input_csv(INPUT_PATH)

    snapshot = module.compute_shadow_snapshot(frame)
    models = {row["config"]: row for row in snapshot["models"]}

    assert snapshot["status"] == "shadow_only"
    assert snapshot["observation_date"] == "2026-09-01"
    assert set(models) == set(module.FROZEN_CONFIG_NAMES)
    assert models["risk-friction__threshold-0p05"]["target_weight"] == pytest.approx(
        0.2482,
        abs=0.0001,
    )
    assert models["production-ensemble__threshold-0p1"]["target_weight"] == pytest.approx(
        0.1189,
        abs=0.0001,
    )


def test_shadow_snapshot_rejects_wrong_symbol():
    module = load_module()
    frame = module.engine.load_input_csv(INPUT_PATH)
    frame["symbol"] = "SH510300"

    with pytest.raises(ValueError, match="SH588000"):
        module.compute_shadow_snapshot(frame)
