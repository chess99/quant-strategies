from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


STUDY_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = STUDY_DIR / "run_study.py"


def load_module():
    spec = importlib.util.spec_from_file_location("star50_technical_study", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def synthetic_bars(periods=360):
    dates = pd.bdate_range("2023-01-02", periods=periods)
    phase = np.linspace(0.0, 18.0, periods)
    close = 100.0 + np.linspace(0.0, 25.0, periods) + 8.0 * np.sin(phase)
    return pd.DataFrame(
        {
            "symbol": "SH588000",
            "trade_date": dates,
            "open": close * (1.0 + 0.001 * np.cos(phase)),
            "high": close * 1.015,
            "low": close * 0.985,
            "close": close,
            "volume": 10_000_000 + np.arange(periods) * 1000,
            "amount": close * (10_000_000 + np.arange(periods) * 1000),
        }
    ).set_index("trade_date")


def test_config_registry_has_twenty_families_and_one_canonical_each():
    module = load_module()
    configs = module.build_configs()
    families = {config.family for config in configs}

    assert len(families) == 20
    assert len(configs) == 122
    assert len({config.name for config in configs}) == len(configs)
    for family in families:
        assert sum(config.canonical for config in configs if config.family == family) == 1


def test_all_targets_are_causal_when_future_bar_changes():
    module = load_module()
    original = synthetic_bars()
    changed = original.copy()
    changed.iloc[-1, changed.columns.get_loc("close")] *= 1.8
    changed.iloc[-1, changed.columns.get_loc("high")] *= 1.8
    changed.iloc[-1, changed.columns.get_loc("low")] *= 1.4
    changed.iloc[-1, changed.columns.get_loc("volume")] *= 5

    for config in module.build_configs():
        first = module.generate_target(original, config)
        second = module.generate_target(changed, config)
        pd.testing.assert_series_equal(first.iloc[:-1], second.iloc[:-1])
        assert first.between(0.0, module.TARGET_WEIGHT).all()


def test_execution_target_is_lagged_one_session():
    module = load_module()
    observation = pd.Series(
        [0.0, 0.99, 0.99, 0.0],
        index=pd.bdate_range("2025-01-02", periods=4),
    )

    assert module.execution_target(observation, 1).tolist() == [0.0, 0.0, 0.99, 0.99]


def test_indicator_implementations_return_finite_values_after_warmup():
    module = load_module()
    frame = synthetic_bars()

    rsi = module.wilder_rsi(frame["close"], 14)
    adx, positive_di, negative_di = module.dmi_adx(frame, 14)
    mfi = module.money_flow_index(frame, 14)
    aroon_up, aroon_down = module.aroon(frame, 25)

    for values in (rsi, adx, positive_di, negative_di, mfi, aroon_up, aroon_down):
        assert np.isfinite(values.iloc[-50:]).all()
    assert rsi.iloc[-1] > 50.0
    assert mfi.iloc[-1] >= 0.0
    assert 0.0 <= aroon_up.iloc[-1] <= 100.0


def test_cross_source_normalization_rejects_material_price_mismatch():
    module = load_module()
    dates = pd.bdate_range("2025-01-02", periods=260)
    base = np.linspace(1.0, 1.5, len(dates))
    eastmoney = pd.DataFrame(
        {
            "date": dates,
            "open": base,
            "high": base * 1.01,
            "low": base * 0.99,
            "close": base,
            "volume": np.arange(len(dates)) + 100,
        }
    )
    sina = eastmoney.copy()
    sina["volume"] *= 100
    sina.loc[259, "close"] = 1.8

    with pytest.raises(ValueError, match="OHLC 交叉核验差异过大"):
        module.normalize_cross_checked_data(eastmoney, sina)


def test_cross_source_normalization_keeps_primary_only_session():
    module = load_module()
    dates = pd.bdate_range("2025-01-02", periods=260)
    primary = pd.DataFrame(
        {
            "date": dates,
            "open": 1.0,
            "high": 1.01,
            "low": 0.99,
            "close": 1.0,
            "volume": 100,
        }
    )
    verification = primary.iloc[:-1].copy()
    verification["volume"] *= 100

    normalized = module.normalize_cross_checked_data(primary, verification)

    assert len(normalized) == 260
    assert normalized.index.max() == dates[-1]
    assert normalized.attrs["cross_checked_common_sessions"] == 259
    assert normalized.attrs["verification_missing_sessions"] == 1


def test_walk_forward_selection_uses_only_prior_sessions():
    module = load_module()
    dates = pd.bdate_range("2020-01-02", periods=700)
    returns = pd.DataFrame(
        {
            "a": np.r_[np.full(504, 0.001), np.full(196, -0.01)],
            "b": np.r_[np.full(504, -0.001), np.full(196, 0.02)],
        },
        index=dates,
    )
    targets = pd.DataFrame({"a": 0.99, "b": 0.0}, index=dates)

    selections, combined = module.select_walk_forward_targets(
        returns,
        targets,
        initial_train_sessions=504,
        test_sessions=63,
        rolling_train_sessions=None,
    )

    assert selections.iloc[0]["selected_config"] == "a"
    assert (selections["train_end"] < selections["test_start"]).all()
    assert combined.loc[selections.iloc[0]["selection_date"]] == pytest.approx(0.99)


def test_pbo_has_all_seventy_half_splits():
    module = load_module()
    dates = pd.bdate_range("2022-01-03", periods=320)
    matrix = np.vstack(
        [
            np.sin(np.arange(320) / 10.0) / 100.0,
            np.cos(np.arange(320) / 13.0) / 100.0,
            np.full(320, 0.0002),
        ]
    )

    rows, summary = module.compute_pbo(matrix, dates, ["a", "b", "c"], partitions=8)

    assert len(rows) == 70
    assert summary["split_count"] == 70
    assert 0.0 <= summary["pbo"] <= 1.0


def test_white_reality_check_is_deterministic():
    module = load_module()
    dates = pd.bdate_range("2022-01-03", periods=240)
    excess = pd.DataFrame(
        {
            "a": np.sin(np.arange(240) / 9.0) / 100.0 + 0.0002,
            "b": np.cos(np.arange(240) / 11.0) / 100.0,
        },
        index=dates,
    )

    first = module.white_reality_check(excess, 20, 200, 7)
    second = module.white_reality_check(excess, 20, 200, 7)

    assert first == second
    assert 0.0 <= first["p_value"] <= 1.0


def test_study_files_contain_no_machine_absolute_paths():
    windows_absolute = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")
    for path in (STUDY_DIR / "README.md", STUDY_DIR / "run_study.py"):
        text = path.read_text(encoding="utf-8")
        assert not windows_absolute.search(text)
