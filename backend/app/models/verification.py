"""Request models for evidence-based repair verification."""

from pydantic import BaseModel, Field


class VerificationRequest(BaseModel):
    corrected_notebook_id: str
    original_execution_id: str
    corrected_execution_id: str
    repair_ids: list[str] | None = Field(default=None, max_length=50)
