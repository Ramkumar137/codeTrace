"""Compare explicitly supplied train/test CSV files without retaining values."""

import csv
import io
from decimal import Decimal, InvalidOperation
from typing import Any

from backend.app.services.dataset_analyzer import DatasetAnalysisError


EVALUATION_OBJECTIVES = {
    "unspecified",
    "unseen_groups",
    "future_known_groups",
    "independent_rows",
}


def _read_rows(content: bytes, dataset_label: str) -> tuple[list[str], list[list[str]]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise DatasetAnalysisError(
            "invalid_csv_encoding",
            f"The {dataset_label} CSV must use UTF-8 text encoding.",
            400,
        ) from error

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        headers = next(reader, None)
    except csv.Error as error:
        raise DatasetAnalysisError(
            "invalid_csv_structure",
            f"The {dataset_label} CSV does not contain a valid header.",
            422,
        ) from error

    if not headers or not any(header.strip() for header in headers):
        raise DatasetAnalysisError(
            "invalid_csv_structure",
            f"The {dataset_label} CSV must contain a header row.",
            422,
        )
    names = [header.strip() for header in headers]
    if any(not name for name in names) or len(set(names)) != len(names):
        raise DatasetAnalysisError(
            "invalid_csv_structure",
            f"The {dataset_label} CSV must have unique, non-empty column names.",
            422,
        )

    rows = []
    try:
        for record_number, row in enumerate(reader, start=2):
            if not row or (len(row) == 1 and not row[0].strip()):
                continue
            if len(row) != len(names):
                raise DatasetAnalysisError(
                    "invalid_csv_structure",
                    f"{dataset_label} CSV record {record_number} has {len(row)} "
                    f"fields; the header has {len(names)}.",
                    422,
                )
            rows.append([value.strip() for value in row])
    except csv.Error as error:
        raise DatasetAnalysisError(
            "invalid_csv_structure",
            f"The {dataset_label} CSV contains malformed data.",
            422,
        ) from error
    return names, rows


def _finding(
    *,
    finding_id: str,
    category: str,
    title: str,
    description: str,
    severity: str,
    confidence: str,
    recommendation: str,
    explanation: str,
    evidence: dict[str, Any],
    limitation: str,
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "rule_id": finding_id,
        "category": category,
        "issue_category": category,
        "title": title,
        "description": description,
        "severity": severity,
        "confidence": confidence,
        "confidence_score": {"high": 0.9, "medium": 0.7, "low": 0.4}[confidence],
        "classification": "dataset_evidence",
        "status": "potential",
        "recommendation": recommendation,
        "suggested_correction": recommendation,
        "source_line_numbers": [],
        "notebook_cell_indices": [],
        "explanation": explanation,
        "risk_explanation": explanation,
        "potential_impact": explanation,
        "human_confirmation_required": True,
        "caveat": limitation,
        "limitations": [limitation],
        "source_refs": [],
        "cell_indices": [],
        "evidence": [evidence],
        "source_code_evidence": [evidence],
        "related_variables": [],
        "related_pipeline_node_ids": [],
        "evidence_type": "explicit_dataset_comparison",
    }


def analyze_train_test_overlap(
    train_filename: str,
    train_content: bytes,
    test_filename: str,
    test_content: bytes,
    identifier_column: str | None = None,
    group_column: str | None = None,
    evaluation_objective: str = "unspecified",
) -> dict[str, Any]:
    """Compare exact records and caller-selected IDs; never return row values."""
    if evaluation_objective not in EVALUATION_OBJECTIVES:
        raise DatasetAnalysisError(
            "invalid_evaluation_objective",
            "Select a supported evaluation objective.",
            422,
        )

    train_columns, train_rows = _read_rows(train_content, "training")
    test_columns, test_rows = _read_rows(test_content, "test")
    train_records = [dict(zip(train_columns, row)) for row in train_rows]
    test_records = [dict(zip(test_columns, row)) for row in test_rows]
    entity_column_candidates = _entity_column_candidates(
        train_columns, train_records
    )

    findings = []
    checks = []
    group_partition_visualization = None
    if set(train_columns) == set(test_columns):
        ordered_columns = sorted(train_columns)
        train_row_set = {
            tuple(record[column] for column in ordered_columns)
            for record in train_records
        }
        test_row_set = {
            tuple(record[column] for column in ordered_columns)
            for record in test_records
        }
        shared_rows = train_row_set & test_row_set
        checks.append(
            {
                "check": "exact_row_overlap",
                "status": "completed",
                "overlap_count": len(shared_rows),
            }
        )
        if shared_rows:
            findings.append(
                _finding(
                    finding_id="exact_train_test_row_overlap",
                    category="train_test_overlap",
                    title="Exact rows occur in both uploaded splits",
                    description=(
                        f"{len(shared_rows)} distinct complete row(s) match exactly "
                        "between the training and test CSV files."
                    ),
                    severity="medium",
                    confidence="high",
                    recommendation=(
                        "Review how the split was created and remove accidental "
                        "cross-partition duplicates when they represent repeated examples."
                    ),
                    explanation=(
                        "A literal comparison of all shared columns found identical "
                        "row values in both uploaded files."
                    ),
                    evidence={
                        "train_filename": train_filename,
                        "test_filename": test_filename,
                        "shared_column_count": len(ordered_columns),
                        "overlap_count": len(shared_rows),
                        "row_values_returned": False,
                    },
                    limitation=(
                        "Identical feature rows do not prove that the rows represent the same individual or that the split is invalid."
                    ),
                )
            )
    else:
        checks.append(
            {
                "check": "exact_row_overlap",
                "status": "skipped",
                "reason": "The uploaded CSV files do not have the same column names.",
            }
        )

    for column, check_name, finding_id, title in (
        (
            identifier_column,
            "identifier_overlap",
            "train_test_identifier_overlap",
            "Configured identifiers occur in both splits",
        ),
        (
            group_column,
            "group_overlap",
            "train_test_group_overlap",
            "Configured groups occur in both splits",
        ),
    ):
        if not column:
            continue
        if column not in train_columns or column not in test_columns:
            raise DatasetAnalysisError(
                "identifier_column_not_found",
                f"Configured column '{column}' must exist in both uploaded CSV files.",
                422,
            )
        train_values = {
            record[column] for record in train_records if record[column]
        }
        test_values = {
            record[column] for record in test_records if record[column]
        }
        shared_values = train_values & test_values
        is_group = check_name == "group_overlap"
        if is_group:
            group_partition_visualization = _group_partition_visualization(
                train_values, test_values
            )
        checks.append(
            {
                "check": check_name,
                "column": column,
                "status": "completed",
                "overlap_count": len(shared_values),
            }
        )
        if shared_values:
            if is_group:
                (
                    severity,
                    recommendation,
                    explanation,
                    objective_assessment,
                ) = _group_overlap_guidance(evaluation_objective)
            else:
                severity = "medium"
                recommendation = (
                    "Verify these are stable entity identifiers and keep each entity in one partition."
                )
                explanation = (
                    "The explicitly selected column values were compared across the "
                    "two uploaded partitions."
                )
                objective_assessment = None
            finding = _finding(
                finding_id=finding_id,
                category="train_test_overlap",
                title=title,
                description=(
                    f"{len(shared_values)} distinct non-empty value(s) in the "
                    f"configured {('group' if is_group else 'identifier')} column "
                    "appear in both splits."
                ),
                severity=severity,
                confidence="high",
                recommendation=recommendation,
                explanation=explanation,
                evidence={
                    "train_filename": train_filename,
                    "test_filename": test_filename,
                    "column": column,
                    "overlap_count": len(shared_values),
                    "overlapping_values_returned": False,
                    "evaluation_objective": evaluation_objective,
                },
                limitation=(
                    objective_assessment
                    or "Identifier semantics are supplied by the user; matching values do not establish the intended split policy."
                ),
            )
            finding["related_variables"] = [column]
            finding["lineage_association"] = (
                "user_configured_column_name_only; dataset-to-notebook semantics were not inferred"
            )
            if not is_group:
                finding["evidence"][0]["overlapping_identifiers"] = [
                    f"Identifier {index:03d}"
                    for index, _ in enumerate(sorted(shared_values)[:30], start=1)
                ]
                finding["evidence"][0]["identifiers_truncated"] = (
                    len(shared_values) > 30
                )
            if is_group and evaluation_objective == "future_known_groups":
                finding["classification"] = "informational_review"
                finding["status"] = "contextual"
            findings.append(finding)

    objective_review = _objective_review(evaluation_objective, bool(group_column))
    return {
        "train_filename": train_filename,
        "test_filename": test_filename,
        "evaluation_objective": evaluation_objective,
        "objective_review": objective_review,
        "train_row_count": len(train_rows),
        "test_row_count": len(test_rows),
        "checks": checks,
        "group_partition_visualization": group_partition_visualization,
        "entity_column_candidates": entity_column_candidates,
        "findings": findings,
        "limitations": [
            "Only the two explicitly uploaded CSV files are compared; notebook paths are never opened.",
            "Exact row equality is not treated as proof that rows represent the same individual.",
            "Identifier and group semantics are configured by the user; raw values are not returned or retained.",
        ],
    }


def _entity_column_candidates(
    columns: list[str], records: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """Suggest likely entity columns by name; never assign group semantics."""
    hints = (
        "student",
        "patient",
        "customer",
        "device",
        "user",
        "entity",
        "subject",
        "account",
        "household",
        "member",
        "person",
        "uuid",
    )
    candidates = []
    for column in columns:
        normalized = column.casefold().replace("-", "_")
        if not (
            normalized == "id"
            or normalized.endswith("_id")
            or any(hint in normalized for hint in hints)
        ):
            continue
        values = [record[column] for record in records if record[column]]
        numeric = bool(values)
        for value in values:
            try:
                Decimal(value)
            except (InvalidOperation, ValueError):
                numeric = False
                break
        candidates.append(
            {
                "column": column,
                "value_shape": "numeric" if numeric else "text_or_mixed",
                "reason": "The column name resembles an identifier or entity field.",
                "requires_user_confirmation": True,
            }
        )
    return candidates


def _group_partition_visualization(
    train_values: set[str], test_values: set[str]
) -> dict[str, Any]:
    aliases = {
        value: f"Entity {index:03d}"
        for index, value in enumerate(sorted(train_values | test_values)[:1000], 1)
    }

    def labels(values: set[str]) -> list[str]:
        return [aliases[value] for value in sorted(values)[:30] if value in aliases]

    return {
        "source": "explicitly_uploaded_train_test_csvs",
        "execution_partition_assignments": False,
        "train_group_count": len(train_values),
        "test_group_count": len(test_values),
        "overlap_count": len(train_values & test_values),
        "train_groups": labels(train_values),
        "test_groups": labels(test_values),
        "overlap_groups": labels(train_values & test_values),
        "truncated": len(train_values | test_values) > 30,
        "identifiers_anonymized": True,
    }


def _group_overlap_guidance(
    evaluation_objective: str,
) -> tuple[str, str, str, str]:
    if evaluation_objective == "unseen_groups":
        return (
            "high",
            "Use a group-aware split: GroupShuffleSplit for a holdout or GroupKFold for cross-validation, keeping every configured group within one partition.",
            "Shared groups conflict with the declared goal of evaluating generalization to entirely unseen groups.",
            "Group overlap conflicts with the declared unseen-group evaluation objective.",
        )
    if evaluation_objective == "future_known_groups":
        return (
            "informational",
            "Group overlap is compatible with prediction for known entities; verify that training observations precede test observations and that features contain no post-cutoff information.",
            "The declared objective allows entities to occur in both partitions. This check does not inspect timestamps or establish chronological separation.",
            "Group overlap alone is not a defect for the declared known-entity future-prediction objective; temporal validity remains unchecked.",
        )
    if evaluation_objective == "independent_rows":
        return (
            "medium",
            "Determine whether rows from one group are statistically dependent. If so, choose a split that matches the intended generalization target.",
            "Shared group values may be acceptable for independent-row evaluation, but dependence within groups can make a row-wise split optimistic.",
            "The effect of group overlap depends on within-group dependence and the intended deployment population.",
        )
    return (
        "high",
        "Specify whether evaluation targets unseen groups or future observations for known groups. Use a group-aware split when testing generalization to unseen groups.",
        "Shared group values were observed, but the appropriate split policy depends on the research objective.",
        "The evaluation objective was not supplied, so group overlap cannot be classified as an evaluation defect.",
    )


def _objective_review(evaluation_objective: str, has_group_column: bool) -> dict[str, str]:
    if not has_group_column:
        return {
            "objective": evaluation_objective,
            "status": "not_applicable",
            "message": "Select a group column to assess whether entity overlap matches the evaluation objective.",
        }
    if evaluation_objective == "unseen_groups":
        return {
            "objective": evaluation_objective,
            "status": "unseen_group_holdout",
            "message": "For generalization to unseen entities, each group should appear in only one split.",
        }
    if evaluation_objective == "future_known_groups":
        return {
            "objective": evaluation_objective,
            "status": "temporal_validation_required",
            "message": "Entity overlap can be expected, but this checker cannot confirm chronological ordering or detect post-cutoff features.",
        }
    if evaluation_objective == "independent_rows":
        return {
            "objective": evaluation_objective,
            "status": "dependence_review_required",
            "message": "Decide whether within-entity dependence is relevant to the intended deployment population.",
        }
    return {
        "objective": evaluation_objective,
        "status": "objective_required",
        "message": "Choose the intended evaluation objective before interpreting entity overlap.",
    }
