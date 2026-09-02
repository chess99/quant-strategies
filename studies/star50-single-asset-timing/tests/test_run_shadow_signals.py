from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

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


def test_network_failure_returns_structured_halt_without_orders(monkeypatch, capsys):
    module = load_module()

    def fail(_):
        raise OSError("verification source unavailable")

    monkeypatch.setattr(module.engine, "fetch_market_data", fail)
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: SimpleNamespace(input_csv=None, end_date="2026-09-02", output=None),
    )

    assert module.main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "halted"
    assert result["stage"] == "market_data_or_signal"
    assert result["models"] == []
    assert "verification source unavailable" in result["reason"]


def test_live_latest_session_without_second_source_halts(monkeypatch, capsys):
    module = load_module()
    frame = module.engine.load_input_csv(INPUT_PATH)
    frame.attrs["latest_session_cross_checked"] = False
    frame.attrs["latest_common_date"] = "2026-08-31"
    frame.attrs["verification_missing_sessions"] = 1

    monkeypatch.setattr(module.engine, "fetch_market_data", lambda _: frame)
    monkeypatch.setattr(
        module,
        "parse_args",
        lambda: SimpleNamespace(input_csv=None, end_date="2026-09-01", output=None),
    )

    assert module.main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "halted"
    assert "最新交易日尚未通过第二行情源" in result["reason"]
    assert result["models"] == []
