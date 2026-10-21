"""从平台锁文件创建隔离研究环境并运行验收。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


from research_native_runtime import configure_macos_openmp


ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = "3.12.9"
LINUX_TORCH = "torch-2.6.0+cpu-cp312-cp312-linux_x86_64.whl"
LINUX_TORCH_SHA256 = "59e78aa0c690f70734e42670036d6b541930b8eabbaa18d94e090abf14cc4d91"


def platform_profile() -> str:
    machine = platform.machine().lower()
    if sys.platform == "darwin" and machine == "arm64":
        return "research-macos-arm64-py312"
    if sys.platform == "win32" and machine in {"amd64", "x86_64"}:
        return "research-win-py312"
    if sys.platform == "linux" and machine in {"amd64", "x86_64"}:
        return "research-linux-py312"
    raise RuntimeError(f"Unsupported research platform: {sys.platform}/{machine}")


def run(*command: str, env: dict | None = None) -> None:
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-dir", type=Path, default=ROOT / ".venv")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    profile = platform_profile()
    uv = shutil.which("uv")
    if uv is None:
        parser.error("Install uv first: https://docs.astral.sh/uv/getting-started/installation/")
    env_dir = args.env_dir.expanduser().resolve()
    if env_dir.exists():
        parser.error(f"Environment already exists; choose a new directory: {env_dir}")
    if sys.platform == "darwin":
        brew = shutil.which("brew")
        if brew is None:
            parser.error("Install Homebrew and run: brew install libomp")
        prefix = subprocess.check_output([brew, "--prefix", "libomp"], text=True).strip()
        if not (Path(prefix) / "lib/libomp.dylib").is_file():
            parser.error("Missing OpenMP runtime; run: brew install libomp")
    cache_dir = (args.cache_dir or ROOT / "data/.cache").expanduser().resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    process_env = dict(os.environ)
    if args.cache_dir is not None:
        process_env["UV_CACHE_DIR"] = str(cache_dir / "uv")
    links = []
    if sys.platform == "linux":
        wheel = cache_dir / LINUX_TORCH
        if not wheel.is_file():
            temporary = wheel.with_suffix(".part")
            urllib.request.urlretrieve(
                "https://download.pytorch.org/whl/cpu/" + LINUX_TORCH.replace("+", "%2B"),
                temporary,
            )
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != LINUX_TORCH_SHA256:
                raise RuntimeError("PyTorch CPU wheel checksum mismatch")
            temporary.replace(wheel)
        if hashlib.sha256(wheel.read_bytes()).hexdigest() != LINUX_TORCH_SHA256:
            raise RuntimeError("PyTorch CPU wheel checksum mismatch")
        links = ["--find-links", str(cache_dir)]
    run(uv, "python", "install", PYTHON_VERSION, env=process_env)
    run(uv, "venv", "--python", PYTHON_VERSION, str(env_dir), env=process_env)
    python = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    lock = ROOT / "requirements" / f"{profile}.lock"
    expected = ROOT / "requirements" / f"{profile}.expected.json"
    run(uv, "pip", "sync", "--python", str(python), *links, str(lock), env=process_env)
    site_dir = Path(
        subprocess.check_output(
            [str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            text=True,
        ).strip()
    )
    configure_macos_openmp(site_dir, env_dir)
    # 让命令行和 Jupyter 使用当前仓库源码，同时保持已安装 distribution 与锁文件完全一致。
    (site_dir / "quant_research_source.pth").write_text(str(ROOT / "src") + "\n", encoding="utf-8")
    if args.output is None:
        output = subprocess.check_output(
            [
                str(python),
                "-c",
                "from quant_research.paths import data_path; print(data_path('quant-research/environment/verification.json'))",
            ],
            cwd=ROOT,
            text=True,
        ).strip()
    else:
        output = str(args.output.expanduser().resolve())
    run(
        str(python),
        "tools/verify_research_environment.py",
        "--expected",
        str(expected),
        "--lock",
        str(lock),
        "--output",
        output,
    )
    run(uv, "pip", "check", "--python", str(python), env=process_env)
    run(str(python), "-m", "pytest", "-q")
    run(str(python), "tools/validate_repo.py")
    run(str(python), "-m", "ruff", "check", "src", "tools", "tests", "studies")
    run(str(python), "tools/check_research_data.py")
    print(json.dumps({"status": "passed", "environment": str(env_dir), "report": output}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
