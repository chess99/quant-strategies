from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pandas as pd
import pytest


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "archive_shadow_observation.py"
INPUT_PATH = (
    STUDY_DIR
    / "results"
    / "2026-09-01__walk-forward-technical-families__tencent-yahoo-2020-2026-v1"
    / "raw"
    / "input-sh588000.csv"
)


def load_module():
    spec = importlib.util.spec_from_file_location("star50_shadow_observation_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def future_frame(module):
    frame = module.engine.load_input_csv(INPUT_PATH)
    last = frame.iloc[-1].copy()
    last[["open", "high", "low", "close"]] = [1.714, 1.728, 1.698, 1.708]
    last["volume"] = 2_933_644_600.0
    last["amount"] = last["close"] * last["volume"]
    frame.loc[pd.Timestamp("2026-09-02")] = last
    frame.attrs["source"] = "test cross-checked data"
    frame.attrs["maximum_ohlc_relative_error"] = 0.0069
    frame.attrs["median_volume_relative_error"] = 0.000001
    frame.attrs["latest_session_cross_checked"] = True
    frame.attrs["latest_common_date"] = "2026-09-02"
    frame.attrs["verification_missing_sessions"] = 0
    return frame


def test_future_observation_archive_is_immutable_and_hash_complete(tmp_path):
    module = load_module()
    frame = future_frame(module)
    snapshot = module.shadow.compute_shadow_snapshot(frame)

    destination = module.archive_observation(frame, snapshot, tmp_path)

    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["evidence_class"] == "frozen future shadow observation"
    assert manifest["observation_date"] == "2026-09-02"
    assert manifest["new_sessions_since_freeze"] == 1
    for relative, record in manifest["artifacts"].items():
        digest = hashlib.sha256((destination / relative).read_bytes()).hexdigest()
        assert digest == record["sha256"]
    with pytest.raises(FileExistsError):
        module.archive_observation(frame, snapshot, tmp_path)

    corrected = module.archive_observation(
        frame,
        snapshot,
        tmp_path,
        version=2,
        supersedes="results/2026-09-02__shadow-observation__tencent-yahoo-2026-09-02-v1",
        correction_note="补充最新双源日期证明。",
    )
    corrected_manifest = json.loads(
        (corrected / "manifest.json").read_text(encoding="utf-8")
    )
    assert corrected.name.endswith("-v2")
    assert corrected_manifest["supersedes"].endswith("-v1")
    assert corrected_manifest["correction_note"] == "补充最新双源日期证明。"


def test_observation_must_be_strictly_after_freeze(tmp_path):
    module = load_module()
    frame = module.engine.load_input_csv(INPUT_PATH)
    snapshot = module.shadow.compute_shadow_snapshot(frame)

    with pytest.raises(ValueError, match="冻结日之后"):
        module.archive_observation(frame, snapshot, tmp_path)


def test_latest_session_must_be_cross_checked_before_archive(tmp_path):
    module = load_module()
    frame = future_frame(module)
    frame.attrs["latest_session_cross_checked"] = False
    frame.attrs["latest_common_date"] = "2026-09-01"
    snapshot = module.shadow.compute_shadow_snapshot(frame)

    with pytest.raises(ValueError, match="第二行情源"):
        module.archive_observation(frame, snapshot, tmp_path)


def test_shadow_observation_source_has_no_machine_absolute_path():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert not re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", text)
