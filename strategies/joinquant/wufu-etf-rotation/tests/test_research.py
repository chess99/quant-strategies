import ast
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest


FAMILY = Path(__file__).resolve().parents[1]
ROOT = FAMILY.parents[2]
REFERENCE = ROOT / "joinquant_archive" / "sources" / "ETF轮动策略" / "五福7.5.py"
PROTOCOL = FAMILY / "protocols" / "2026-08-16-wufu-direct-decomposition-v1.json"


def load_research():
    path = FAMILY / "research.py"
    spec = importlib.util.spec_from_file_location("wufu_research", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_a7_import():
    path = FAMILY / "a7_import.py"
    spec = importlib.util.spec_from_file_location("wufu_a7_import", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_protocol_freezes_reference_hash_before_results():
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    digest = hashlib.sha256(REFERENCE.read_bytes()).hexdigest()
    assert protocol["frozen_before_results"] is True
    assert digest == protocol["reference"]["source_sha256"]
    assert [stage["id"] for stage in protocol["stages"]] == [
        "A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7"
    ]


def test_weighted_trend_score_distinguishes_slope_and_quality():
    research = load_research()
    smooth = np.exp(np.linspace(0.0, 0.12, 26))
    noisy = smooth.copy()
    noisy[::2] *= 1.03
    smooth_result = research.weighted_trend_metrics(smooth, 25)
    noisy_result = research.weighted_trend_metrics(noisy, 25)
    assert smooth_result[0] > 0
    assert smooth_result[1] > noisy_result[1]
    assert np.isclose(smooth_result[2], smooth_result[0] * smooth_result[1])


def test_three_of_four_regime_vote_uses_only_supplied_history():
    research = load_research()
    closes = np.array(
        [
            [10.0] * 10 + [9.0],
            [20.0] * 10 + [19.0],
            [30.0] * 10 + [29.0],
            [40.0] * 10 + [41.0],
        ]
    ).T
    assert research.is_a_share_weak(closes, 10) is True
    assert research.is_a_share_weak(closes[:, [0, 1, 3]], 10) is False


def test_incumbent_buffer_retains_only_close_followers():
    research = load_research()
    ranked = [("A", 2.0), ("B", 1.85), ("C", 1.5)]
    assert research.select_with_buffer(ranked, ["B"], 1, 0.9) == ["B"]
    assert research.select_with_buffer(ranked, ["C"], 1, 0.9) == ["A"]
    assert research.select_with_buffer(ranked, ["B", "C"], 3, 0.9) == ["A", "B", "C"]


def test_mainline_rule_is_exact_dense_conjunction():
    research = load_research()
    passing = {
        "scores": [5.1, 6.0, 7.0, 8.5, 10.5],
        "r2": [0.91, 0.92, 0.93, 0.94, 0.95],
        "volume_ratio": [1.8, 1.9, 2.0, 2.1, 2.2],
        "laplace_slope": [0.01] * 5,
    }
    assert research.evaluate_mainline_history(passing)
    failing = dict(passing)
    failing["volume_ratio"] = [1.7] * 5
    assert not research.evaluate_mainline_history(failing)


def test_platform_baseline_is_parseable_and_causal():
    source = (FAMILY / "baseline.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert 'set_option("avoid_future_data", True)' in source
    assert "context.previous_date" in source
    assert "from __future__ import annotations" not in source


def test_a7_platform_calibration_is_parseable_and_keeps_targets_fixed():
    source = (FAMILY / "platform" / "a7_minute_calibration.py").read_text(
        encoding="utf-8"
    )
    ast.parse(source)
    assert "a7-switch-events.csv" in source
    assert 'baseline_time": "13:10"' in source
    assert "target and 13:10 exit frozen" in source
    assert "from __future__ import annotations" not in source
    assert ".tail(30).to_numpy(" not in source


def test_a7_frozen_platform_summaries_aggregate_exactly():
    a7_import = load_a7_import()
    payload = a7_import.load_platform_run()
    summary = a7_import.aggregate_segments(payload, base_trading_days=2808)
    assert summary["requested_events"] == 891
    assert summary["valid_events"] == 891
    assert sum(summary["confirmation_counts"].values()) == 891
    assert summary["confirmation_counts"] == {
        "13:10": 262,
        "13:40": 142,
        "14:10": 120,
        "14:40": 94,
        "14:55": 273,
    }
    assert summary["forced_1455_ratio"] == pytest.approx(0.3063973063973064)
    assert summary["mean_entry_edge_bp"] == pytest.approx(5.058175414477158)
    assert summary["positive_entry_edge_ratio"] == pytest.approx(
        0.2716049382716049
    )
    assert summary["paired_trade_return_delta"] == pytest.approx(
        0.00044193058356293256
    )
    assert summary["relative_wealth_from_entry_only"] == pytest.approx(
        0.5286204020507015
    )
    assert summary["relative_annualized_from_entry_only"] == pytest.approx(
        0.038818588712748126
    )


def test_a7_platform_hash_validation_rejects_tampering(tmp_path):
    a7_import = load_a7_import()
    payload = json.loads(a7_import.DEFAULT_RUN_FILE.read_text(encoding="utf-8"))
    payload["input"]["repository_compatible_script_sha256"] = "0" * 64
    tampered = tmp_path / "tampered-a7-platform-run.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="script hash mismatch"):
        a7_import.load_platform_run(tampered)
