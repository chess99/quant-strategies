import importlib.util
from pathlib import Path

import pandas as pd


PATH = (
    Path(__file__).resolve().parents[2]
    / "studies"
    / "joinquant-api-compat-validation"
    / "run_validation.py"
)
SPEC = importlib.util.spec_from_file_location("api_compat_validation", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeAPI:
    def get_price(self, *args, **kwargs):
        return pd.DataFrame({"close": range(1, 61)})

    def history(self, *args, **kwargs):
        return pd.DataFrame(
            {
                "510300.XSHG": [1.0, 1.1],
                "510500.XSHG": [1.0, 1.2],
                "513100.XSHG": [1.0, 0.9],
                "518880.XSHG": [1.0, 1.05],
            }
        )


def test_price_and_etf_logic_only_depend_on_compat_api():
    timing = MODULE.index_timing_logic(FakeAPI())
    ranking = MODULE.etf_rotation_logic(FakeAPI())

    assert timing["observations"] == 60
    assert timing["risk_on"]
    assert ranking.loc[0, "symbol"] == "510500.XSHG"
