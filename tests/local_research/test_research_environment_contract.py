import json
from pathlib import Path


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
