"""Response models for notebook uploads."""

from typing import Any, Literal

from pydantic import BaseModel


class NotebookCell(BaseModel):
    index: int
    cell_type: Literal["code", "markdown", "raw"]
    source: str
    execution_count: int | None
    has_outputs: bool


class NotebookSummary(BaseModel):
    filename: str
    format_version: int
    total_cells: int
    code_cells: int
    markdown_cells: int
    raw_cells: int
    cells: list[NotebookCell]
    analysis: dict[str, Any]


class NotebookUploadResponse(BaseModel):
    status: Literal["success"]
    notebook: NotebookSummary
