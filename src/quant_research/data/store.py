"""Parquet + JSON 的本地研究数据存储。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

import pandas as pd

from .contracts import DatasetManifest


DEFAULT_DATA_ROOT = Path("D:/code/_open-source/_data/quant-research")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ResearchDataStore:
    def __init__(self, root: Path | str | None = None):
        configured = root or os.environ.get("QUANT_RESEARCH_DATA_DIR")
        self.root = Path(configured or DEFAULT_DATA_ROOT).expanduser().resolve()
        self.raw_dir = self.root / "raw"
        self.normalized_dir = self.root / "normalized"
        self.manifest_dir = self.root / "manifests"
        self.snapshot_dir = self.root / "snapshots"
        self.quarantine_dir = self.root / "quarantine"

    def initialize(self) -> None:
        for directory in (
            self.raw_dir,
            self.normalized_dir,
            self.manifest_dir,
            self.snapshot_dir,
            self.quarantine_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def normalized_path(self, dataset: str, filename: str = "data.parquet") -> Path:
        return self.normalized_dir / dataset / filename

    def manifest_path(self, dataset: str) -> Path:
        return self.manifest_dir / f"{dataset}.json"

    def write_parquet(
        self,
        dataset: str,
        frame: pd.DataFrame,
        filename: str = "data.parquet",
    ) -> dict:
        self.initialize()
        target = self.normalized_path(dataset, filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        os.close(handle)
        temporary = Path(temporary_name)
        try:
            frame.to_parquet(temporary, index=False)
            temporary.replace(target)
        finally:
            if temporary.exists():
                temporary.unlink()
        return {
            "path": target.relative_to(self.root).as_posix(),
            "bytes": target.stat().st_size,
            "sha256": sha256_file(target),
        }

    def read_parquet(self, dataset: str, filename: str = "data.parquet") -> pd.DataFrame:
        path = self.normalized_path(dataset, filename)
        if not path.is_file():
            raise FileNotFoundError(f"dataset file does not exist: {path}")
        return pd.read_parquet(path)

    def write_raw_csv(
        self,
        provider: str,
        dataset: str,
        filename: str,
        frame: pd.DataFrame,
    ) -> dict:
        """不可变保存原始表；同名内容不同则拒绝覆盖。"""
        self.initialize()
        target = self.raw_dir / provider / dataset / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = frame.to_csv(index=False).encode("utf-8-sig")
        expected_hash = hashlib.sha256(payload).hexdigest()
        if target.exists():
            if sha256_file(target) != expected_hash:
                raise FileExistsError(f"raw artifact already exists with other data: {target}")
        else:
            target.write_bytes(payload)
        return {
            "path": target.relative_to(self.root).as_posix(),
            "bytes": target.stat().st_size,
            "sha256": sha256_file(target),
        }

    def write_manifest(self, manifest: DatasetManifest) -> Path:
        self.initialize()
        target = self.manifest_path(manifest.dataset)
        payload = json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n"
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            text=True,
        )
        os.close(handle)
        temporary = Path(temporary_name)
        try:
            temporary.write_text(payload, encoding="utf-8")
            temporary.replace(target)
        finally:
            if temporary.exists():
                temporary.unlink()
        return target

    def read_manifest(self, dataset: str) -> dict:
        path = self.manifest_path(dataset)
        if not path.is_file():
            raise FileNotFoundError(f"manifest does not exist: {path}")
        return json.loads(path.read_text(encoding="utf-8"))
