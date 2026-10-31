"""Deterministic, source-only repair proposals for supported notebook findings."""

import ast
import copy
import hashlib
import json
import re
from typing import Any

import nbformat

from backend.app.services.notebook_analyzer import analyze_notebook


AUTOMATICALLY_REPAIRABLE = "automatically_repairable"
REQUIRES_MANUAL_INTERVENTION = "requires_manual_intervention"
NOT_REPAIRABLE = "not_repairable_with_available_evidence"

_TARGET_NAMES = {"y", "target", "targets", "label", "labels", "outcome"}
_MANUAL_REVIEW_RULES = {
    "preprocessing_fit_before_split",
    "target_column_in_features",
    "target_variable_in_features",
    "suspicious_outcome_feature",
    "test_metric_used_for_model_selection",
    "test_data_used_for_fit",
    "evaluation_on_training_data",
    "training_data_used_for_evaluation",
    "classification_split_without_stratify_review",
    "exact_train_test_row_overlap",
    "train_test_identifier_overlap",
    "train_test_group_overlap",
}
_SPLIT_TARGET_PATTERNS = (
    re.compile(r"^x_train$", re.IGNORECASE),
    re.compile(r"^x_test$", re.IGNORECASE),
)


class RepairError(ValueError):
    """A user-correctable error while generating an approved repair."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def build_repair_catalog(
    cells: list[dict[str, Any]], findings: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Classify every finding and attach validated repair proposals where supported."""
    catalog = []
    for finding in findings:
        rule_id = finding.get("rule_id", finding.get("id", ""))
        proposal = None
        limitation = ""

        if rule_id == "preprocessing_fit_before_split":
            proposal = _preprocessing_repair(cells, finding)
            limitation = (
                "Only a single top-level fit_transform assignment feeding a simple "
                "train_test_split pattern is rewritten."
            )
        elif rule_id == "target_column_in_features":
            proposal = _target_column_repair(cells, finding)
            limitation = (
                "Only an exact literal target column selected from the same dataframe "
                "as y can be removed."
            )
        elif rule_id in {
            "target_variable_in_features",
            "suspicious_outcome_feature",
            "test_metric_used_for_model_selection",
            "test_data_used_for_fit",
            "training_data_used_for_evaluation",
            "classification_split_without_stratify_review",
        }:
            limitation = (
                "The finding requires notebook-specific judgment that cannot be "
                "safely inferred from the available source evidence."
            )
        else:
            if not limitation:
                limitation = "No deterministic repair template supports this finding."

        if proposal:
            proposal.update(
                {
                    "repair_status": AUTOMATICALLY_REPAIRABLE,
                    "validation_status": "passed",
                    "validation": {
                        "python_syntax": "passed",
                        "required_imports": "no new imports required",
                        "variable_references": "passed",
                        "finding_pattern": "no longer detected by the static rule",
                        "unrelated_cells": "unchanged",
                        "notebook_structure": "passed",
                        "experiment_verification": "not_performed",
                    },
                    "limitations": [limitation],
                }
            )
        else:
            status = (
                REQUIRES_MANUAL_INTERVENTION
                if rule_id in _MANUAL_REVIEW_RULES
                else NOT_REPAIRABLE
            )
            proposal = {
                "repair_id": _repair_id(finding, "manual"),
                "finding_id": finding.get("id"),
                "finding_category": finding.get("category", "unknown"),
                "finding_title": finding.get("title", "Finding"),
                "repair_status": status,
                "affected_cells": finding.get("cell_indices", []),
                "original_code": _finding_code(cells, finding),
                "corrected_code": "",
                "cell_changes": [],
                "explanation": limitation,
                "reason": "A safe, deterministic correction could not be established.",
                "variables_affected": finding.get("related_variables", []),
                "dependencies_affected": [],
                "validation_status": "not_applicable",
                "validation": {
                    "python_syntax": "not_run",
                    "required_imports": "not_run",
                    "variable_references": "not_run",
                    "finding_pattern": "not_addressed",
                    "unrelated_cells": "not_applicable",
                    "notebook_structure": "not_run",
                    "experiment_verification": "not_performed",
                },
                "limitations": [limitation],
            }

        catalog.append(proposal)

    _mark_conflicts(catalog)
    return catalog


def generate_corrected_notebook(
    content: bytes,
    filename: str,
    approved_repair_ids: list[str],
) -> tuple[bytes, str]:
    """Apply only selected, non-conflicting proposals to a separate notebook document."""
    if len(approved_repair_ids) != len(set(approved_repair_ids)):
        raise RepairError("invalid_repair_ids", "Repair IDs must be distinct.")
    try:
        notebook_text = content.decode("utf-8-sig")
        raw_notebook = json.loads(notebook_text)
        if (
            not isinstance(raw_notebook, dict)
            or isinstance(raw_notebook.get("nbformat"), bool)
            or raw_notebook.get("nbformat") != 4
        ):
            raise RepairError(
                "invalid_notebook_structure",
                "Only nbformat v4 notebooks can be repaired.",
            )
        original_notebook = nbformat.reads(notebook_text, as_version=nbformat.NO_CONVERT)
        nbformat.validate(original_notebook)
    except RepairError:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        nbformat.NBFormatError,
        TypeError,
        ValueError,
    ) as error:
        raise RepairError(
            "invalid_notebook_structure",
            "The uploaded notebook is not valid UTF-8 nbformat v4 JSON.",
        ) from error

    parsed_cells = _source_cells(raw_notebook)
    analysis = analyze_notebook(parsed_cells)
    catalog = build_repair_catalog(parsed_cells, analysis.get("findings", []))
    selected_ids = set(approved_repair_ids)
    if not selected_ids:
        raise RepairError("no_approved_repairs", "Approve at least one repair before downloading.")

    by_id = {repair["repair_id"]: repair for repair in catalog}
    unknown_ids = selected_ids - by_id.keys()
    if unknown_ids:
        raise RepairError(
            "unknown_repair_id",
            "One or more selected repairs do not belong to this notebook.",
        )
    selected = [by_id[repair_id] for repair_id in approved_repair_ids]
    unavailable = [
        repair
        for repair in selected
        if repair["repair_status"] != AUTOMATICALLY_REPAIRABLE
        or repair["validation_status"] != "passed"
    ]
    if unavailable:
        raise RepairError(
            "repair_not_approved",
            "Only validated, automatically repairable proposals can be applied.",
        )
    _ensure_no_conflicts(selected)

    corrected = copy.deepcopy(raw_notebook)
    changes_by_cell: dict[int, dict[str, str]] = {}
    for repair in selected:
        for change in repair["cell_changes"]:
            cell_index = change["cell_index"]
            if cell_index in changes_by_cell:
                raise RepairError(
                    "repair_conflict",
                    "Selected repairs modify the same cell; review them separately.",
                )
            changes_by_cell[cell_index] = change

    for cell_index, change in changes_by_cell.items():
        cell = corrected["cells"][cell_index]
        cell["source"] = change["corrected_code"]
        cell["execution_count"] = None
        cell["outputs"] = []

    try:
        validated = nbformat.reads(
            json.dumps(corrected, ensure_ascii=False), as_version=nbformat.NO_CONVERT
        )
        nbformat.validate(validated)
    except (nbformat.NBFormatError, TypeError, ValueError) as error:
        raise RepairError(
            "invalid_corrected_notebook",
            "The corrected notebook did not pass nbformat validation.",
        ) from error

    corrected_bytes = json.dumps(corrected, ensure_ascii=False, indent=1).encode("utf-8")
    return corrected_bytes, _corrected_filename(filename)


def _preprocessing_repair(
    cells: list[dict[str, Any]], finding: dict[str, Any]
) -> dict[str, Any] | None:
    parsed = _parse_code_cells(cells)
    if parsed is None:
        return None

    transforms = []
    splits = []
    constructors: dict[str, str] = {}
    for cell_index, tree in parsed.items():
        for statement in tree.body:
            if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
                continue
            target = statement.targets[0]
            value = statement.value
            if isinstance(target, ast.Name) and isinstance(value, ast.Call):
                constructor = _imported_scaler_name(parsed, _call_name(value.func))
                if constructor:
                    constructors[target.id] = constructor
            call = _find_relevant_call(value)
            if call and _call_name(call.func) == "fit_transform":
                if not isinstance(target, ast.Name) or not isinstance(call.func, ast.Attribute):
                    continue
                receiver = call.func.value
                if (
                    not isinstance(receiver, ast.Name)
                    or receiver.id not in constructors
                    or len(call.args) != 1
                    or not isinstance(call.args[0], ast.Name)
                ):
                    continue
                transforms.append(
                    (cell_index, statement, target.id, receiver.id, call.args[0].id)
                )
            for node in ast.walk(value):
                if isinstance(node, ast.Call) and _call_name(node.func) == "train_test_split":
                    splits.append((cell_index, statement, node))

    if len(transforms) != 1 or len(splits) != 1:
        return None
    transform_cell, transform_statement, scaled_name, transformer, raw_name = transforms[0]
    split_cell, split_statement, split_call = splits[0]
    if (transform_cell, transform_statement.lineno) >= (split_cell, split_statement.lineno):
        return None
    if not isinstance(split_statement, ast.Assign) or len(split_statement.targets) != 1:
        return None
    targets = split_statement.targets[0]
    if not isinstance(targets, (ast.Tuple, ast.List)) or len(targets.elts) < 2:
        return None
    first_two = targets.elts[:2]
    if not all(isinstance(item, ast.Name) for item in first_two):
        return None
    train_name, test_name = (item.id for item in first_two)
    if not all(
        pattern.fullmatch(name)
        for pattern, name in zip(_SPLIT_TARGET_PATTERNS, (train_name, test_name))
    ):
        return None
    if not split_call.args or not isinstance(split_call.args[0], ast.Name):
        return None
    if split_call.args[0].id != scaled_name or not _is_simple_statement(
        parsed[transform_cell], transform_statement
    ) or not _is_simple_statement(parsed[split_cell], split_statement):
        return None
    if _has_unrelated_load(parsed, scaled_name, transform_cell, transform_statement, split_cell, split_call):
        return None

    source_by_index = {
        cell["index"]: cell["source"]
        for cell in cells
        if cell.get("cell_type") == "code"
    }
    original_changes = {
        transform_cell: source_by_index[transform_cell],
        split_cell: source_by_index[split_cell],
    }
    edits: dict[int, list[tuple[int, int, str]]] = {
        transform_cell: [],
        split_cell: [],
    }
    edits[transform_cell].append(
        _statement_edit(source_by_index[transform_cell], transform_statement, "")
    )
    split_source = source_by_index[split_cell]
    edits[split_cell].append(
        _node_edit(split_source, split_call.args[0], raw_name)
    )
    newline = "\r\n" if "\r\n" in split_source else "\n"
    insertion = (
        f"{train_name} = {transformer}.fit_transform({train_name}){newline}"
        f"{test_name} = {transformer}.transform({test_name}){newline}"
    )
    insertion_offset = _line_end_offset(split_source, split_statement.end_lineno)
    if insertion_offset == len(split_source) and not split_source.endswith(("\n", "\r")):
        insertion = newline + insertion
    edits[split_cell].append((insertion_offset, insertion_offset, insertion))
    corrected_changes = {
        transform_cell: _apply_edits(original_changes[transform_cell], edits[transform_cell]),
        split_cell: _apply_edits(original_changes[split_cell], edits[split_cell]),
    }

    if not _validate_candidate(cells, original_changes, corrected_changes, finding):
        return None
    return _proposal(
        finding,
        "preprocessing_fit_before_split",
        [transform_cell, split_cell],
        original_changes,
        corrected_changes,
        f"Split raw feature data before fitting {transformer}; fit it only on "
        f"{train_name}, then transform {test_name} with the training-fitted parameters.",
        [transformer, raw_name, scaled_name, train_name, test_name],
        [f"{raw_name} -> {train_name}", f"{raw_name} -> {test_name}"],
    )


def _target_column_repair(
    cells: list[dict[str, Any]], finding: dict[str, Any]
) -> dict[str, Any] | None:
    parsed = _parse_code_cells(cells)
    if parsed is None:
        return None
    targets: list[tuple[int, int, int, str, str]] = []
    features: list[tuple[int, ast.Assign, ast.Subscript, ast.List, str, list[ast.expr]]] = []

    for cell_index, tree in parsed.items():
        for statement in tree.body:
            if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                continue
            assigned_names = _assigned_names(statement)
            value = statement.value
            if not isinstance(value, ast.Subscript) or not isinstance(value.value, ast.Name):
                continue
            if isinstance(value.slice, ast.Constant) and isinstance(value.slice.value, str):
                if assigned_names & _TARGET_NAMES:
                    targets.append(
                        (
                            cell_index,
                            statement.lineno,
                            statement.col_offset,
                            value.value.id,
                            value.slice.value,
                        )
                    )
            if (
                len(assigned_names) == 1
                and isinstance(value.slice, ast.List)
                and all(
                    isinstance(item, ast.Constant) and isinstance(item.value, str)
                    for item in value.slice.elts
                )
            ):
                variable = next(iter(assigned_names))
                features.append(
                    (
                        cell_index,
                        statement,
                        value,
                        value.slice,
                        variable,
                        list(value.slice.elts),
                    )
                )

    matches = []
    for feature in features:
        feature_cell, feature_statement = feature[:2]
        for target_cell, target_line, target_column_offset, target_base, target_column in targets:
            if (
                feature[2].value.id == target_base
                and any(item.value == target_column for item in feature[5])
                and (target_cell, target_line, target_column_offset)
                < (
                    feature_cell,
                    feature_statement.lineno,
                    feature_statement.col_offset,
                )
            ):
                matches.append((feature, target_column))
    if len(matches) != 1:
        return None

    (cell_index, statement, _, column_list, feature_name, elements), target_column = matches[0]
    kept = [item for item in elements if item.value != target_column]
    if not kept:
        return None
    source = next(
        cell["source"]
        for cell in cells
        if cell.get("index") == cell_index and cell.get("cell_type") == "code"
    )
    list_source = ast.get_source_segment(source, column_list)
    if not list_source or "#" in list_source or "\n" in list_source or "\r" in list_source:
        return None
    list_text = "[" + ", ".join(ast.get_source_segment(source, item) or "" for item in kept) + "]"
    corrected = _replace_node(source, column_list, list_text)
    original_changes = {cell_index: source}
    corrected_changes = {cell_index: corrected}
    if not _validate_candidate(cells, original_changes, corrected_changes, finding):
        return None
    return _proposal(
        finding,
        "target_column_in_features",
        [cell_index],
        original_changes,
        corrected_changes,
        f"Remove the exact target column {target_column!r} from {feature_name}; the "
        "notebook assigns that same dataframe column to the target variable.",
        [feature_name, target_column],
        [f"{target_column} removed from {feature_name}"],
    )


def _proposal(
    finding: dict[str, Any],
    repair_type: str,
    affected_cells: list[int],
    original_changes: dict[int, str],
    corrected_changes: dict[int, str],
    explanation: str,
    variables: list[str],
    dependencies: list[str],
) -> dict[str, Any]:
    changes = [
        {
            "cell_index": cell_index,
            "original_code": original_changes[cell_index],
            "corrected_code": corrected_changes[cell_index],
        }
        for cell_index in affected_cells
    ]
    return {
        "repair_id": _repair_id(finding, repair_type),
        "finding_id": finding.get("id"),
        "finding_category": finding.get("category", "unknown"),
        "finding_title": finding.get("title", "Finding"),
        "repair_type": repair_type,
        "repair_status": AUTOMATICALLY_REPAIRABLE,
        "affected_cells": affected_cells,
        "original_code": "\n\n".join(change["original_code"] for change in changes),
        "corrected_code": "\n\n".join(change["corrected_code"] for change in changes),
        "cell_changes": changes,
        "explanation": explanation,
        "reason": "The deterministic rewrite removes the evidenced source pattern while preserving other cells.",
        "variables_affected": sorted(set(variables)),
        "dependencies_affected": dependencies,
        "validation_status": "passed",
        "validation": {},
        "limitations": [],
    }


def _validate_candidate(
    cells: list[dict[str, Any]],
    original_changes: dict[int, str],
    corrected_changes: dict[int, str],
    finding: dict[str, Any],
) -> bool:
    try:
        for source in corrected_changes.values():
            compile(source, "<repair-candidate>", "exec")
    except SyntaxError:
        return False

    original_names: set[str] = set()
    introduced_names: set[str] = set()
    for cell in cells:
        if cell.get("cell_type") != "code":
            continue
        try:
            tree = ast.parse(cell.get("source", ""))
        except SyntaxError:
            return False
        original_names.update(
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        )
    for source in corrected_changes.values():
        tree = ast.parse(source)
        introduced_names.update(
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        )
    if not introduced_names <= original_names:
        return False

    candidate_cells = copy.deepcopy(cells)
    for cell in candidate_cells:
        if cell.get("index") in corrected_changes:
            cell["source"] = corrected_changes[cell["index"]]
    remaining = {
        item.get("rule_id", item.get("id"))
        for item in analyze_notebook(candidate_cells).get("findings", [])
    }
    finding_rule = finding.get("rule_id", finding.get("id"))
    if finding_rule in remaining:
        return False

    return all(
        original_changes[index] != corrected_changes[index]
        for index in corrected_changes
    )


def _mark_conflicts(catalog: list[dict[str, Any]]) -> None:
    repairable = [
        repair
        for repair in catalog
        if repair["repair_status"] == AUTOMATICALLY_REPAIRABLE
    ]
    for index, first in enumerate(repairable):
        for second in repairable[index + 1 :]:
            if set(first["affected_cells"]) & set(second["affected_cells"]):
                for repair in (first, second):
                    repair["repair_status"] = REQUIRES_MANUAL_INTERVENTION
                    repair["validation_status"] = "conflict"
                    repair["explanation"] += (
                        " This proposal conflicts with another repair affecting the same cell; "
                        "review and resolve it manually."
                    )
                    repair["limitations"].append(
                        "Only one proposal affecting a given cell can be approved in this phase."
                    )


def _ensure_no_conflicts(selected: list[dict[str, Any]]) -> None:
    seen_cells: set[int] = set()
    for repair in selected:
        cells = set(repair["affected_cells"])
        if cells & seen_cells:
            raise RepairError(
                "repair_conflict",
                "Selected repairs modify the same cell; review them separately.",
            )
        seen_cells.update(cells)


def _parse_code_cells(cells: list[dict[str, Any]]) -> dict[int, ast.Module] | None:
    parsed = {}
    try:
        for cell in cells:
            if cell.get("cell_type") == "code":
                parsed[cell["index"]] = ast.parse(cell.get("source", ""))
    except (SyntaxError, KeyError):
        return None
    return parsed


def _source_cells(notebook: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(notebook, dict) or not isinstance(notebook.get("cells"), list):
        raise RepairError("invalid_notebook_structure", "Notebook cells are missing.")
    cells = []
    for index, cell in enumerate(notebook["cells"]):
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(source)
        if not isinstance(source, str):
            raise RepairError("invalid_notebook_structure", "A notebook cell has invalid source.")
        cells.append(
            {"index": index, "cell_type": cell.get("cell_type"), "source": source}
        )
    return cells


def _finding_code(cells: list[dict[str, Any]], finding: dict[str, Any]) -> str:
    indices = set(finding.get("cell_indices", []))
    return "\n\n".join(
        cell.get("source", "")
        for cell in cells
        if cell.get("index") in indices and cell.get("cell_type") == "code"
    )


def _repair_id(finding: dict[str, Any], repair_type: str) -> str:
    value = f"{finding.get('id', '')}:{repair_type}".encode("utf-8")
    return "repair-" + hashlib.sha256(value).hexdigest()[:16]


def _call_name(function: ast.expr) -> str:
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return ""


def _imported_scaler_name(parsed: dict[int, ast.Module], local_name: str) -> str:
    allowed_modules = {
        "sklearn.preprocessing": {"standardscaler", "minmaxscaler", "robustscaler", "maxabsscaler"},
        "sklearn.impute": {"simpleimputer", "knnimputer"},
        "sklearn.decomposition": {"pca"},
    }
    for tree in parsed.values():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module not in allowed_modules:
                continue
            for alias in node.names:
                if (alias.asname or alias.name) == local_name and alias.name.casefold() in allowed_modules[node.module]:
                    return alias.name.casefold()
    return ""


def _find_relevant_call(value: ast.expr) -> ast.Call | None:
    if isinstance(value, ast.Call):
        return value
    return None


def _assigned_names(statement: ast.Assign | ast.AnnAssign) -> set[str]:
    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
    return {
        node.id
        for target in targets
        for node in ast.walk(target)
        if isinstance(node, ast.Name)
    }


def _is_simple_statement(tree: ast.Module, statement: ast.stmt) -> bool:
    same_line = [
        item
        for item in tree.body
        if item is not statement
        and item.lineno <= statement.end_lineno
        and item.end_lineno >= statement.lineno
    ]
    return not same_line


def _has_unrelated_load(
    parsed: dict[int, ast.Module],
    scaled_name: str,
    transform_cell: int,
    transform_statement: ast.stmt,
    split_cell: int,
    split_call: ast.Call,
) -> bool:
    allowed = {
        (transform_cell, transform_statement.lineno, transform_statement.end_lineno),
        (split_cell, split_call.lineno, split_call.end_lineno),
    }
    for cell_index, tree in parsed.items():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id == scaled_name
                and not any(
                    cell_index == allowed_cell
                    and allowed_start <= node.lineno <= allowed_end
                    for allowed_cell, allowed_start, allowed_end in allowed
                )
            ):
                return True
    return False


def _node_edit(source: str, node: ast.AST, replacement: str) -> tuple[int, int, str]:
    start, end = _node_offsets(source, node)
    return start, end, replacement


def _replace_node(source: str, node: ast.AST, replacement: str) -> str:
    start, end = _node_offsets(source, node)
    return source[:start] + replacement + source[end:]


def _node_offsets(source: str, node: ast.AST) -> tuple[int, int]:
    lines = source.splitlines(keepends=True)
    start_line = node.lineno - 1
    end_line = node.end_lineno - 1
    start_prefix = lines[start_line].encode("utf-8")[: node.col_offset].decode("utf-8")
    end_prefix = lines[end_line].encode("utf-8")[: node.end_col_offset].decode("utf-8")
    start = sum(len(line) for line in lines[:start_line]) + len(start_prefix)
    end = sum(len(line) for line in lines[:end_line]) + len(end_prefix)
    return start, end


def _statement_edit(
    source: str, statement: ast.stmt, replacement: str
) -> tuple[int, int, str]:
    lines = source.splitlines(keepends=True)
    start = sum(len(line) for line in lines[: statement.lineno - 1])
    end = sum(len(line) for line in lines[: statement.end_lineno])
    return start, end, replacement


def _line_end_offset(source: str, line_number: int) -> int:
    return sum(len(line) for line in source.splitlines(keepends=True)[:line_number])


def _apply_edits(source: str, edits: list[tuple[int, int, str]]) -> str:
    result = source
    previous_start = len(source) + 1
    for start, end, replacement in sorted(edits, key=lambda edit: edit[0], reverse=True):
        if end > previous_start:
            raise RepairError("repair_conflict", "Source edits overlap.")
        result = result[:start] + replacement + result[end:]
        previous_start = start
    return result


def _corrected_filename(filename: str) -> str:
    from pathlib import Path

    return f"{Path(filename).stem}-repaired.ipynb"
