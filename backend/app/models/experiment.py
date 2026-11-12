"""Request model for auditable experiment-history entries."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ExperimentHistoryRequest(BaseModel):
    dataset_ids: list[str] = Field(default_factory=list, max_length=20)
    dataset_version: str | None = Field(default=None, max_length=200)
    model_name: str = Field(min_length=1, max_length=200)
    hyperparameters: dict[str, Any] = Field(default_factory=dict)
    training_data_reference: str = Field(min_length=1, max_length=300)
    validation_data_reference: str | None = Field(default=None, max_length=300)
    test_data_reference: str | None = Field(default=None, max_length=300)
    evaluation_metric: str = Field(min_length=1, max_length=100)
    metric_value: float
    model_selection_decision: Literal[
        "selected",
        "rejected",
        "final_evaluation",
        "candidate",
        "not_used_for_selection",
        "validation_selected",
        "cv_selected",
    ]
