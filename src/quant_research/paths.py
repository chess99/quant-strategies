"""跨平台本地数据路径；相对配置始终以仓库根目录为基准。"""

from __future__ import annotations

import json
import os
from pathlib import Path, PureWindowsPath


REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_CONFIG = REPO_ROOT / "research.local.json"
DATA_LOCATIONS = {
    "quant-research": ("QUANT_RESEARCH_DATA_DIR", "research_data_dir"),
    "qlib/cn_data": ("QLIB_CN_DATA_DIR", "qlib_cn_data_dir"),
    "oneil": ("QUANT_ONEIL_DATA_DIR", "oneil_data_dir"),
}


def local_config() -> dict[str, str]:
    if not LOCAL_CONFIG.is_file():
        return {}
    config = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8"))
    allowed = {"data_home", "dolt_executable"} | {key for _, key in DATA_LOCATIONS.values()}
    if not isinstance(config, dict) or set(config).difference(allowed):
        raise ValueError(f"Invalid keys in {LOCAL_CONFIG}; allowed: {sorted(allowed)}")
    if any(not isinstance(value, str) or not value.strip() for value in config.values()):
        raise ValueError(f"Paths in {LOCAL_CONFIG} must be non-empty strings")
    return config


def resolve_local_path(value: str | Path, *, base: Path | None = None) -> Path:
    text = str(value)
    if os.name != "nt" and (PureWindowsPath(text).drive or text.startswith("\\\\")):
        raise ValueError(f"Windows path cannot be used on this system: {text}")
    if os.name == "nt" and text.startswith("/") and not text.startswith("//"):
        raise ValueError(f"POSIX absolute path cannot be used on Windows: {text}")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base if base is not None else Path.cwd()) / path
    return path.resolve()


def data_home() -> Path:
    value = os.environ.get("QUANT_DATA_HOME") or local_config().get("data_home") or "data"
    return resolve_local_path(value, base=REPO_ROOT)


def data_path(relative: str = "") -> Path:
    """获取数据路径，支持数据集级环境变量和本地配置覆盖。"""
    relative = relative.replace("\\", "/")
    if relative.startswith("/"):
        raise ValueError(f"Expected a relative data path: {relative}")
    relative = relative.rstrip("/")
    if ".." in Path(relative).parts or PureWindowsPath(relative).drive:
        raise ValueError(f"Expected a relative data path: {relative}")
    for prefix, (env_name, config_key) in DATA_LOCATIONS.items():
        if relative == prefix or relative.startswith(prefix + "/"):
            value = os.environ.get(env_name) or local_config().get(config_key)
            root = resolve_local_path(value, base=REPO_ROOT) if value else data_home() / prefix
            suffix = relative[len(prefix) :].lstrip("/")
            return root / suffix if suffix else root
    return data_home() / relative


def dolt_executable() -> str:
    """默认在 PATH 查找 Dolt；可显式指定本机可执行文件。"""
    value = os.environ.get("DOLT_EXECUTABLE") or local_config().get("dolt_executable")
    return str(resolve_local_path(value, base=REPO_ROOT)) if value else "dolt"
