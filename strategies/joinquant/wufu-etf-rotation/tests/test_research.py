import ast
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np


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
