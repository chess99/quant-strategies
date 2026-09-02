from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pandas as pd


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "audit_execution_prices.py"


def load_module():
    spec = importlib.util.spec_from_file_location("star50_execution_price_audit_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_price_comparison_reports_exact_and_material_differences():
    module = load_module()
    dates = pd.to_datetime(["2026-09-01", "2026-09-02"])
    qfq = pd.DataFrame(
        {
            "date": dates,
            "open": [1.0, 1.1],
            "high": [1.1, 1.2],
            "low": [0.9, 1.0],
            "close": [1.05, 1.15],
            "volume": [100.0, 200.0],
        }
    )
    raw = qfq.copy()
    raw.loc[1, ["open", "high", "low", "close"]] *= 1.01

    comparison, summary = module.compare_prices(qfq, raw)

    assert len(comparison) == 2
    assert summary["common_sessions"] == 2
    assert summary["exact_match_sessions"] == 1
    assert 0.009 < summary["maximum_ohlc_relative_error"] < 0.011
    assert "不能视为完全一致" in module.build_report(summary)


def test_execution_price_audit_source_has_no_machine_absolute_path():
    text = MODULE_PATH.read_text(encoding="utf-8")
    assert not re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", text)
