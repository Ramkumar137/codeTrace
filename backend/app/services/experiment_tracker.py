"""Evidence-based summaries of persisted experiment history."""

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any


_TEST_SELECTION_DECISIONS = {"selected", "rejected"}


def fingerprint_dataset_version(version: str) -> str:
    """Create a stable fingerprint for a caller-supplied dataset version label."""
    return hashlib.sha256(version.strip().encode("utf-8")).hexdigest()


def fingerprint_datasets(datasets: list[dict[str, Any]]) -> str:
    """Fingerprint explicitly associated dataset bytes without retaining their rows."""
    digest = hashlib.sha256()
    for dataset in sorted(datasets, key=lambda item: item["dataset_id"]):
        digest.update(dataset["dataset_id"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(bytes(dataset["content"])).digest())
        digest.update(b"\0")
    return digest.hexdigest()


def make_experiment_record(
    request: dict[str, Any],
    dataset_fingerprint: str,
    previous_experiment_id: str | None,
) -> dict[str, Any]:
    return {
        "experiment_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset_fingerprint": dataset_fingerprint,
        "dataset_version": request.get("dataset_version"),
        "model_name": request["model_name"].strip(),
        "hyperparameters": request.get("hyperparameters", {}),
        "training_data_reference": request["training_data_reference"].strip(),
        "validation_data_reference": request.get("validation_data_reference"),
        "test_data_reference": request.get("test_data_reference"),
        "evaluation_metric": request["evaluation_metric"].strip(),
        "metric_value": request["metric_value"],
        "model_selection_decision": request["model_selection_decision"],
        "previous_experiment_id": previous_experiment_id,
    }


def analyze_experiment_history(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Detect repeated selection based on persisted test-set evaluations only."""
    by_dataset: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_dataset.setdefault(record["dataset_fingerprint"], []).append(record)

    findings = []
    dataset_summaries = []
    for fingerprint, experiments in by_dataset.items():
        ordered = sorted(experiments, key=lambda item: item["timestamp"])
        test_selection = [
            item
            for item in ordered
            if item.get("test_data_reference")
            and item.get("model_selection_decision") in _TEST_SELECTION_DECISIONS
        ]
        validation_selection = [
            item
            for item in ordered
            if (
                item.get("validation_data_reference")
                or item.get("model_selection_decision")
                in {"validation_selected", "cv_selected"}
            )
            and not item.get("test_data_reference")
        ]
        if len(test_selection) >= 2:
            ids = [item["experiment_id"] for item in test_selection]
            findings.append(
                {
                    "id": "repeated_test_set_model_selection",
                    "rule_id": "repeated_test_set_model_selection",
                    "category": "test_set_contamination",
                    "title": "Test-set results were used in repeated model selection",
                    "severity": "high",
                    "confidence": "high",
                    "confidence_score": 0.9,
                    "classification": "persisted_history_evidence",
                    "status": "potential",
                    "explanation": (
                        f"{len(test_selection)} recorded experiments with the same "
                        "dataset fingerprint used test-set metrics to select or reject models."
                    ),
                    "potential_impact": (
                        "Repeated decisions based on the test score can make that set no longer an independent final evaluation."
                    ),
                    "recommendation": (
                        "Use a validation set or cross-validation for model selection, "
                        "then evaluate the locked model on a fresh untouched test set."
                    ),
                    "suggested_correction": (
                        "Use a validation set or cross-validation for model selection, "
                        "then evaluate the locked model on a fresh untouched test set."
                    ),
                    "human_confirmation_required": True,
                    "evidence": [
                        {
                            "experiment_id": item["experiment_id"],
                            "timestamp": item["timestamp"],
                            "model_name": item["model_name"],
                            "metric": item["evaluation_metric"],
                            "metric_value": item["metric_value"],
                            "decision": item["model_selection_decision"],
                            "dataset_fingerprint": fingerprint,
                        }
                        for item in test_selection
                    ],
                    "source_refs": [],
                    "cell_indices": [],
                    "notebook_cell_indices": [],
                    "source_line_numbers": [],
                    "related_variables": [],
                    "related_pipeline_node_ids": [],
                    "experiment_ids": ids,
                    "evidence_type": "persisted_experiment_history",
                    "limitations": [
                        "History only includes experiments recorded in CodeTrace; external tuning decisions are not visible.",
                        "Repeated selection signals test feedback but does not quantify the resulting optimism.",
                    ],
                }
            )

        dataset_summaries.append(
            {
                "dataset_fingerprint": fingerprint,
                "experiment_count": len(ordered),
                "test_evaluation_count": sum(
                    bool(item.get("test_data_reference")) for item in ordered
                ),
                "test_selection_count": len(test_selection),
                "validation_or_cv_selection_count": len(validation_selection),
                "test_feedback_status": (
                    "repeated_test_selection"
                    if len(test_selection) >= 2
                    else "single_test_evaluation"
                    if any(item.get("test_data_reference") for item in ordered)
                    else "no_test_evaluation_recorded"
                ),
            }
        )

    return {
        "findings": findings,
        "datasets": dataset_summaries,
        "limitations": [
            "Repeated test-set contamination is reported only when at least two recorded test evaluations were used for selection.",
            "A single notebook snapshot or a single final test evaluation cannot establish repeated tuning.",
            "Experiments performed outside the persisted CodeTrace history are not considered.",
        ],
    }
