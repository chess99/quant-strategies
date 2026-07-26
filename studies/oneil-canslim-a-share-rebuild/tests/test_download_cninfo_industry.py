import importlib.util
import sys
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "download_cninfo_industry.py"
SPEC = importlib.util.spec_from_file_location("oneil_cninfo_industry", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_normalize_industry_rows_keeps_change_date_and_classification_standard():
    raw = pd.DataFrame(
        {
            "证券代码": ["600519"],
            "变更日期": [pd.Timestamp("2019-11-12").date()],
            "分类标准编码": ["008021"],
            "分类标准": ["证监会行业分类标准（2012）"],
            "行业编码": ["C15"],
            "行业门类": ["制造业"],
            "行业次类": [None],
            "行业大类": ["酒、饮料和精制茶制造业"],
            "行业中类": [None],
        }
    )

    result = MODULE.normalize_industry_rows(raw, "SH600519")

    assert result.loc[0, "symbol"] == "SH600519"
    assert result.loc[0, "change_date"] == pd.Timestamp("2019-11-12")
    assert result.loc[0, "classification_standard_code"] == "008021"
    assert result.loc[0, "industry_major"] == "酒、饮料和精制茶制造业"
