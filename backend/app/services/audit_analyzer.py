"""Supported static audit rules for ML notebook source operations."""

from typing import Any


def _partition_name_matches(names: list[str], partition: str) -> bool:
    allowed_names = {
        partition,
        f"{partition}_data",
        f"{partition}_set",
        f"x_{partition}",
        f"y_{partition}",
        f"x_{partition}_data",
        f"y_{partition}_data",
        f"x_{partition}_set",
        f"y_{partition}_set",
    }
    return any(
        name.lower() in allowed_names
        for name in names
    )


def analyze_findings(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return findings only for explicitly supported source patterns."""
    findings: list[dict[str, Any]] = [    ]
    for operation in operations:
        kind = operation["kind"]
        inputs = operation["inputs"]
        finding = None

        if kind == "training" and _partition_name_matches(inputs, "test"):
            finding = {
                "id": "test_data_used_for_fit",
                "title": "Test data passed to model fitting",
                "description": "A recognizable fit call receives a test-named variable.",
                "severity": "high",
                "confidence": "high",
                "recommendation": "Fit model parameters using training data only; keep held-out test data for final evaluation.",
                "caveat": "Variable names are a static clue and do not prove the variable's contents.",
                "explanation": "The fit call's source arguments include an identifier named like a test partition.",
            }
        elif kind == "evaluation" and _partition_name_matches(inputs, "train"):
            finding = {
                "id": "evaluation_on_training_data",
                "title": "Evaluation appears to use training data",
                "description": "A recognizable metric or score call receives a train-named variable.",
                "severity": "medium",
                "confidence": "medium",
                "recommendation": "Report final metrics on a held-out test set or an appropriate cross-validation fold.",
                "caveat": "Identifier names do not establish the underlying data or the purpose of this metric.",
                "explanation": "The evaluation call's source arguments include an identifier named like a training partition.",
            }
        if finding:
            source_ref = operation["source_ref"]
            refs = [source_ref]
            finding.update(
                {
                    "source_refs": refs,
                    "cell_indices": sorted({ref["cell_index"] for ref in refs}),
                    "evidence": [
                        {
                            "cell_index": operation["cell_index"],
                            "line": operation["line"],
                            "snippet": operation["source"],
                        }
                    ],
                    "evidence_type": "static_code_pattern",
                    "limitations": [finding["caveat"]],
                }
            )
            findings.append(finding)
    return findings
