"""Response models for explicit CSV dataset analysis."""

from typing import Literal

from pydantic import BaseModel


class DatasetNumericSummary(BaseModel):
    count: int
    minimum: str
    maximum: str
    mean: str


class DatasetColumnSummary(BaseModel):
    name: str
    inferred_type: Literal["boolean", "empty", "integer", "number", "text"]
    non_empty_values: int
    missing_values: int
    missing_percentage: float
    numeric_summary: DatasetNumericSummary | None


class DatasetSummary(BaseModel):
    filename: str
    row_count: int
    column_count: int
    columns: list[DatasetColumnSummary]


class DatasetAnalysisResponse(BaseModel):
    status: Literal["success"]
    dataset: DatasetSummary
