"""API models for explicitly started notebook experiments."""

from typing import Any

from pydantic import BaseModel, Field


class ExecutionRequest(BaseModel):
    dataset_ids: list[str] = Field(default_factory=list, max_length=20)


class PairedExecutionRequest(BaseModel):
    corrected_notebook_id: str
    dataset_ids: list[str] = Field(min_length=1, max_length=20)


class ExecutionStatusResponse(BaseModel):
    execution_id: str
    notebook_id: str
    notebook_type: str
    status: str
    started_at: str | None
    completed_at: str | None
    duration_seconds: float | None
    executed_cell_count: int
    successful_cell_count: int
    failed_cell_number: int | None
    error_details: dict[str, Any] | None
    python_version: str | None
    package_versions: dict[str, str]
    environment: dict[str, Any]
    dataset_references: list[dict[str, str]]
    outputs: list[dict[str, Any]]
    logs: str
    artifact_available: bool
