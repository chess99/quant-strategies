import importlib.util
import sys
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "run_backtest.py"
SPEC = importlib.util.spec_from_file_location("joinquant_csi300_reversal_study", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_rebalance_dates_preserve_original_six_day_week_counter():
    calendar = pd.date_range("2024-01-01", periods=361, freq="B")

    dates = sorted(MODULE.rebalance_dates(calendar))

    assert dates == [calendar[0], calendar[179], calendar[359]]


def test_reversal_score_uses_only_observation_date_history():
    dates = pd.date_range("2023-01-01", periods=151, freq="B")
    close = pd.DataFrame(
        {
            "AAA": range(1, 152),
            "BBB": list(range(151, 0, -1)),
        },
        index=dates,
    )

    scores = MODULE.reversal_scores(close, ["AAA", "BBB"], dates[-2])

    assert scores.index.tolist() == ["BBB", "AAA"]
    expected_aaa = close.loc[dates[-7], "AAA"] / close.loc[dates[-146], "AAA"] - 1.0
    assert scores["AAA"] == expected_aaa
