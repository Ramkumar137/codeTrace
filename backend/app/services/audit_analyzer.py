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
    findings: list[dict[str, Any]] = []
    split_positions = [
        (operation["cell_index"], operation["line"])
        for operation in operations
        if operation["kind"] == "split"
    ]
    for operation in operations:
        kind = operation["kind"]
        name = operation["name"]
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
        elif (
            kind == "preprocessing"
            and name in {"fit", "fit_transform"}
            and any(value.lower() in {"x", "features", "df", "data", "dataset"} for value in inputs)
            and any(position > (operation["cell_index"], operation["line"]) for position in split_positions)
        ):
            finding = {
                "id": "preprocessing_fit_before_split",
                "title": "Preprocessing is fitted before a later split",
                "description": "A full-data-named input is passed to a preprocessing fit before a recognizable split call.",
                "severity": "medium",
                "confidence": "medium",
                "recommendation": "Split first, fit preprocessing on training data only, and apply the fitted transform to held-out data.",
                "caveat": "The analyzer cannot establish whether the input contains the later test partition or whether this ordering executes as written.",
                "explanation": "Source order shows a preprocessing fit on a common full-data identifier before a split call.",
            }

        if finding:
            source_ref = operation["source_ref"]
            refs = [source_ref]
            if finding["id"] == "preprocessing_fit_before_split":
                refs.extend(
                    other["source_ref"]
                    for other in operations
                    if other["kind"] == "split"
                    and (other["cell_index"], other["line"])
                    > (operation["cell_index"], operation["line"])
                )
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
