import json
import os
from pathlib import Path

import pytest

from quant_research import paths
from quant_research.data.store import ResearchDataStore
from quant_research.portal import QlibDailyBarSource


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(paths, "LOCAL_CONFIG", tmp_path / "research.local.json")
    for name in (
        "QUANT_DATA_HOME",
        "DOLT_EXECUTABLE",
        *(x[0] for x in paths.DATA_LOCATIONS.values()),
    ):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_defaults_are_independent_of_working_directory(isolated_paths, monkeypatch):
    monkeypatch.chdir(isolated_paths.parent)
    assert paths.data_path("quant-research") == isolated_paths / "data/quant-research"
    assert ResearchDataStore().root == paths.data_path("quant-research")
    assert Path(QlibDailyBarSource().provider_uri) == paths.data_path("qlib/cn_data")


def test_local_config_and_environment_precedence(isolated_paths, monkeypatch):
    paths.LOCAL_CONFIG.write_text(
        json.dumps(
            {
                "data_home": "legacy-data",
                "qlib_cn_data_dir": "separate/qlib",
            }
        )
    )
    assert (
        paths.data_path("oneil/financials.parquet")
        == isolated_paths / "legacy-data/oneil/financials.parquet"
    )
    assert (
        paths.data_path("qlib/cn_data/calendars/day.txt")
        == isolated_paths / "separate/qlib/calendars/day.txt"
    )
    monkeypatch.setenv("QUANT_DATA_HOME", "external-data")
    monkeypatch.setenv("QLIB_CN_DATA_DIR", "env-qlib")
    monkeypatch.setenv("QUANT_RESEARCH_DATA_DIR", "env-research")
    assert paths.data_path("oneil") == isolated_paths / "external-data/oneil"
    assert paths.data_path("qlib/cn_data") == isolated_paths / "env-qlib"
    assert ResearchDataStore().root == isolated_paths / "env-research"
    explicit = isolated_paths / "explicit"
    assert ResearchDataStore(explicit).root == explicit


def test_invalid_configuration_and_foreign_paths_fail_clearly(isolated_paths):
    paths.LOCAL_CONFIG.write_text('{"data_hmoe": "typo"}')
    with pytest.raises(ValueError, match="Invalid keys"):
        paths.data_home()
    paths.LOCAL_CONFIG.write_text('{"data_home": 42}')
    with pytest.raises(ValueError, match="non-empty strings"):
        paths.data_home()
    if os.name != "nt":
        with pytest.raises(ValueError, match="Windows path"):
            paths.resolve_local_path("D:/old-data")
        with pytest.raises(ValueError, match="Windows path"):
            ResearchDataStore(r"D:\old-data")
    with pytest.raises(ValueError, match="relative data path"):
        paths.data_path("../outside")


def test_dolt_uses_path_or_local_override(isolated_paths, monkeypatch):
    assert paths.dolt_executable() == "dolt"
    monkeypatch.setenv("DOLT_EXECUTABLE", "tools/dolt")
    assert paths.dolt_executable() == str(isolated_paths / "tools/dolt")


def test_active_research_code_has_no_machine_specific_windows_defaults():
    root = Path(__file__).resolve().parents[2]
    for folder in ("src", "tools", "studies", "strategies"):
        for source in (root / folder).rglob("*.py"):
            if {"backtests", "results", "__pycache__"}.intersection(source.parts):
                continue
            assert "D:/code/_open-source" not in source.read_text(encoding="utf-8"), source
