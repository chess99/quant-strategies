"""校验并执行首次指数择时复现归档中的不可变引擎源码。"""

from __future__ import annotations

import hashlib
import runpy
from pathlib import Path


EXPECTED_ENGINE_SHA256 = (
    "58c3c219ad1b0ac9078aa947a563cbcc4e9b01df0d02ed4995d8559e1ac2a4fc"
)
ENGINE_PATH = (
    Path(__file__).resolve().parent
    / ".."
    / "2026-07-27__local-qlib-comparison-v1"
    / "engine.py"
).resolve()


def main() -> None:
    actual = hashlib.sha256(ENGINE_PATH.read_bytes()).hexdigest()
    if actual != EXPECTED_ENGINE_SHA256:
        raise RuntimeError(
            f"archived engine hash mismatch: expected {EXPECTED_ENGINE_SHA256}, "
            f"got {actual}"
        )
    runpy.run_path(str(ENGINE_PATH), run_name="__main__")


if __name__ == "__main__":
    main()
