"""统一 macOS 研究环境中的 OpenMP 运行库。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


def configure_macos_openmp(site_dir: Path, env_dir: Path) -> dict:
    """让 sklearn、PyTorch 和 Homebrew 模型库共享同一 libomp。"""
    if sys.platform != "darwin":
        return {}
    prefix = subprocess.check_output(["brew", "--prefix", "libomp"], text=True).strip()
    runtime = (Path(prefix) / "lib/libomp.dylib").resolve()
    if not runtime.is_file():
        raise RuntimeError("OpenMP runtime unavailable; run: brew install libomp")
    libraries = []
    for relative in ("sklearn/.dylibs/libomp.dylib", "torch/lib/libomp.dylib"):
        target = site_dir / relative
        backup = target.with_suffix(".dylib.bundled")
        if not target.exists():
            raise RuntimeError(f"Expected bundled OpenMP library is missing: {target}")
        if not target.is_symlink():
            if backup.exists():
                raise RuntimeError(f"Unexpected OpenMP backup already exists: {backup}")
            target.rename(backup)
        else:
            target.unlink()
        target.symlink_to(runtime)
        libraries.append(relative)
    report = {
        "runtime": str(runtime),
        "sha256": hashlib.sha256(runtime.read_bytes()).hexdigest(),
        "linked_libraries": libraries,
    }
    (env_dir / "research-native-runtime.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    return report
