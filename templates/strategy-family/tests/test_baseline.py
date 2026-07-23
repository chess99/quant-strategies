import ast
from pathlib import Path


STRATEGY = Path(__file__).resolve().parents[1] / "baseline.py"


def test_platform_file_is_valid_python():
    source = STRATEGY.read_text(encoding="utf-8")
    ast.parse(source)
    assert "from __future__ import annotations" not in source
