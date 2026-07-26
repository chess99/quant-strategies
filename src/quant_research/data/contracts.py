"""本地研究数据的稳定契约。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable


class QualityGrade(str, Enum):
    """点时与来源质量；A 最严格，C 仅允许代理研究。"""

    A = "A"
    B = "B"
    C = "C"

    @property
    def rank(self) -> int:
        return {QualityGrade.A: 3, QualityGrade.B: 2, QualityGrade.C: 1}[self]

    def meets(self, minimum: "QualityGrade | str") -> bool:
        minimum = QualityGrade(minimum)
        return self.rank >= minimum.rank

    @classmethod
    def worst(cls, grades: Iterable["QualityGrade | str"]) -> "QualityGrade":
        normalized = [QualityGrade(grade) for grade in grades]
        if not normalized:
            raise ValueError("at least one quality grade is required")
        return min(normalized, key=lambda grade: grade.rank)


class AssetType(str, Enum):
    STOCK = "stock"
    ETF = "etf"
    FUND = "fund"
    INDEX = "index"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DatasetManifest:
    schema_version: int
    dataset: str
    provider: str
    quality_grade: QualityGrade
    row_count: int
    columns: list[str]
    data_files: list[dict]
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    date_range: dict | None = None
    source_files: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["quality_grade"] = self.quality_grade.value
        return payload
