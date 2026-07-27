import json
from pathlib import Path

import pytest

from tools.verify_research_environment import read_exact_lock, verify_lock


ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = ROOT / "requirements"
DIST_NAMES = {"qlib": "pyqlib"}


def _pins(path):
    result = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        assert "==" in line
        name, version = line.split("==", maxsplit=1)
        result[name.lower()] = version
    return result


def test_expected_versions_are_exactly_pinned_in_input_and_lock():
    expected = json.loads(
        (REQUIREMENTS / "research-win-py312.expected.json").read_text(
            encoding="utf-8"
        )
    )
    direct = _pins(REQUIREMENTS / "research-win-py312.in")
    locked = _pins(REQUIREMENTS / "research-win-py312.lock")

    for public_name, version in expected["packages"].items():
        distribution = DIST_NAMES.get(public_name, public_name).lower()
        assert direct[distribution] == version
        assert locked[distribution] == version


def test_lock_contains_only_portable_exact_pins():
    lock_path = REQUIREMENTS / "research-win-py312.lock"
    text = lock_path.read_text(encoding="utf-8")
    assert "file://" not in text
    assert " @ " not in text
    assert "-e " not in text
    assert len(_pins(lock_path)) >= 200


def test_runtime_lock_verification_rejects_missing_extra_and_drift(tmp_path):
    lock = tmp_path / "research.lock"
    lock.write_text("Alpha_Pkg==1.0\nbeta-pkg==2.0\n", encoding="utf-8")

    report = verify_lock(lock, {"alpha-pkg": "1.0", "beta_pkg": "2.0"})

    assert report["exact_pin_count"] == 2
    assert report["installed_distribution_count"] == 2
    assert report["matches_installed_environment"] is True
    with pytest.raises(RuntimeError, match="missing=.*beta-pkg"):
        verify_lock(lock, {"alpha-pkg": "1.0"})
    with pytest.raises(RuntimeError, match="extra=.*gamma"):
        verify_lock(
            lock,
            {"alpha-pkg": "1.0", "beta-pkg": "2.0", "gamma": "3.0"},
        )
    with pytest.raises(RuntimeError, match="mismatches"):
        verify_lock(lock, {"alpha-pkg": "1.1", "beta-pkg": "2.0"})


def test_lock_parser_rejects_non_exact_requirements(tmp_path):
    lock = tmp_path / "research.lock"
    lock.write_text("alpha>=1.0\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="non-exact"):
        read_exact_lock(lock)
