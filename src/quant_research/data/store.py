"""Parquet + JSON 的本地研究数据存储。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable

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

    def write_partitioned_parquet(
        self,
        dataset: str,
        frame: pd.DataFrame,
        partition_columns: Iterable[str],
        filename: str = "part-00000.parquet",
    ) -> list[dict]:
        """按 Hive 风格分区写入；调用方可逐批传入，避免全市场一次驻留内存。"""

        columns = list(partition_columns)
        if not columns:
            raise ValueError("at least one partition column is required")
        missing = set(columns).difference(frame.columns)
        if missing:
            raise ValueError(f"partition columns are missing: {sorted(missing)}")
        files = []
        grouped = frame.groupby(columns, sort=True, dropna=False)
        for values, partition in grouped:
            if not isinstance(values, tuple):
                values = (values,)
            partition_values = {
                column: value.item() if hasattr(value, "item") else value
                for column, value in zip(columns, values)
            }
            segments = []
            for column, value in partition_values.items():
                text = str(value)
                if text in {"", ".", ".."} or any(char in text for char in r"\/:"):
                    raise ValueError(f"unsafe partition value for {column}: {value!r}")
                segments.append(f"{column}={text}")
            relative_name = "/".join([*segments, filename])
            artifact = self.write_parquet(
                dataset,
                partition.reset_index(drop=True),
                filename=relative_name,
            )
            artifact["partition_values"] = partition_values
            files.append(artifact)
        return files

    def read_parquet(self, dataset: str, filename: str = "data.parquet") -> pd.DataFrame:
        path = self.normalized_path(dataset, filename)
        if not path.is_file():
            raise FileNotFoundError(f"dataset file does not exist: {path}")
        return pd.read_parquet(path)

    def read_symbol_partitions(
        self,
        dataset: str,
        symbols: Iterable[str],
    ) -> pd.DataFrame:
        """只读取指定证券的 Hive 分区，避免把全市场历史一次装入内存。"""

        frames = []
        missing = []
        for symbol in dict.fromkeys(str(item) for item in symbols):
            path = self.normalized_path(
                dataset,
                f"symbol={symbol}/data.parquet",
            )
            if not path.is_file():
                missing.append(symbol)
                continue
            frames.append(pd.read_parquet(path))
        if missing:
            raise FileNotFoundError(
                f"{dataset} symbol partitions do not exist: {missing}"
            )
        if not frames:
            raise ValueError("at least one symbol is required")
        return pd.concat(frames, ignore_index=True)

    def write_quarantine_parquet(
        self,
        dataset: str,
        frame: pd.DataFrame,
        filename: str = "data.parquet",
    ) -> dict:
        self.initialize()
        target = self.quarantine_dir / dataset / filename
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

    def write_json_report(self, name: str, payload: dict) -> Path:
        self.initialize()
        target = self.manifest_dir / f"{name}.json"
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            text=True,
        )
        os.close(handle)
        temporary = Path(temporary_name)
        try:
            temporary.write_text(text, encoding="utf-8")
            temporary.replace(target)
        finally:
            if temporary.exists():
                temporary.unlink()
        return target
