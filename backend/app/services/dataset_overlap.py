"""Compare explicitly supplied train/test CSV files without retaining values."""

import csv
import io
from typing import Any

from backend.app.services.dataset_analyzer import DatasetAnalysisError


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
        "title": title,
        "description": description,
        "severity": severity,
        "confidence": confidence,
        "classification": "dataset_evidence",
        "status": "potential",
        "recommendation": recommendation,
        "explanation": explanation,
        "risk_explanation": explanation,
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
) -> dict[str, Any]:
    """Compare exact records and caller-selected IDs; never return row values."""
    train_columns, train_rows = _read_rows(train_content, "training")
    test_columns, test_rows = _read_rows(test_content, "test")
    train_records = [dict(zip(train_columns, row)) for row in train_rows]
    test_records = [dict(zip(test_columns, row)) for row in test_rows]

    findings = []
    checks = []
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
        checks.append(
            {
                "check": check_name,
                "column": column,
                "status": "completed",
                "overlap_count": len(shared_values),
            }
        )
        if shared_values:
            is_group = check_name == "group_overlap"
            findings.append(
                _finding(
                    finding_id=finding_id,
                    category="train_test_overlap",
                    title=title,
                    description=(
                        f"{len(shared_values)} distinct non-empty value(s) in the "
                        f"configured {('group' if is_group else 'identifier')} column "
                        "appear in both splits."
                    ),
                    severity="high" if is_group else "medium",
                    confidence="high",
                    recommendation=(
                        "Use a group-aware split so every configured group is assigned "
                        "to only one partition."
                        if is_group
                        else "Verify these are stable entity identifiers and keep each entity in one partition."
                    ),
                    explanation=(
                        "The explicitly selected column values were compared across the "
                        "two uploaded partitions."
                    ),
                    evidence={
                        "train_filename": train_filename,
                        "test_filename": test_filename,
                        "column": column,
                        "overlap_count": len(shared_values),
                        "overlapping_values_returned": False,
                    },
                    limitation=(
                        "Identifier semantics are supplied by the user; matching values do not establish the intended split policy."
                    ),
                )
            )

    return {
        "train_filename": train_filename,
        "test_filename": test_filename,
        "train_row_count": len(train_rows),
        "test_row_count": len(test_rows),
        "checks": checks,
        "findings": findings,
        "limitations": [
            "Only the two explicitly uploaded CSV files are compared; notebook paths are never opened.",
            "Exact row equality is not treated as proof that rows represent the same individual.",
            "Identifier and group semantics are configured by the user; raw values are not returned or retained.",
        ],
    }
