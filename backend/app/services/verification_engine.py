"""Evidence-based repair verification and conservative experiment comparison."""

import ast
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.app.services.notebook_analyzer import analyze_notebook


_METRIC_PATTERNS = (
    ("accuracy", r"accuracy(?:_score)?"),
    ("precision", r"precision(?:_score)?"),
    ("recall", r"recall(?:_score)?"),
    ("f1", r"f1(?:[_ -]?score)?"),
    ("roc_auc", r"roc(?:[_ -]?auc)(?:_score)?"),
    ("mae", r"mean[_ -]?absolute[_ -]?error|mae"),
    ("mse", r"(?<!root )mean[_ -]?squared[_ -]?error|mse"),
    ("rmse", r"root[_ -]?mean[_ -]?squared[_ -]?error|rmse"),
    ("r2", r"r2(?:_score)?|r[_ -]?squared"),
)
_NUMBER = r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
_TRAIN_NAME = re.compile(r"(?:^|_)train(?:_|$)", re.IGNORECASE)
_TEST_NAME = re.compile(r"(?:^|_)test(?:_|$)", re.IGNORECASE)
_TARGET_NAMES = {"y", "target", "targets", "label", "labels", "outcome"}


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _execution_context(cells: list[dict[str, Any]]) -> dict[str, Any]:
    analysis = analyze_notebook(cells)
    operations = analysis.get("operations", {})
    all_operations = [
        operation
        for operation_group in operations.values()
        if isinstance(operation_group, list)
        for operation in operation_group
        if isinstance(operation, dict)
    ]
    models: list[dict[str, Any]] = [
        {
            "type": item.get("name", ""),
            "configuration": item.get("source", ""),
        }
        for item in all_operations
        if item.get("kind") == "model"
        or (
            item.get("kind") == "preprocessing"
            and item.get("name") in {"Pipeline", "make_pipeline"}
        )
    ]
    splits: list[dict[str, Any]] = []
    seeds: list[str] = []
    for cell in cells:
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", "")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            if name == "train_test_split":
                options = {
                    item.arg: ast.unparse(item.value)
                    for item in node.keywords
                    if item.arg
                }
                target_names: list[str] = []
                for statement in ast.walk(tree):
                    if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                        value = statement.value
                        if any(child is node for child in ast.walk(value)):
                            targets = (
                                statement.targets
                                if isinstance(statement, ast.Assign)
                                else [statement.target]
                            )
                            target_names = sorted(
                                {
                                    target.id
                                    for target in targets
                                    for target in ast.walk(target)
                                    if isinstance(target, ast.Name)
                                }
                            )
                            break
                splits.append(
                    {
                        "method": name,
                        "options": options,
                        "feature_reference": (
                            ast.unparse(node.args[0]) if node.args else None
                        ),
                        "target_reference": (
                            ast.unparse(node.args[1]) if len(node.args) > 1 else None
                        ),
                        "output_variables": target_names,
                    }
                )
            elif name in {
                "GridSearchCV",
                "RandomizedSearchCV",
                "cross_val_score",
                "cross_validate",
                "GroupKFold",
                "GroupShuffleSplit",
            } or name.endswith(("Classifier", "Regressor", "Estimator", "Model")):
                models.append(
                    {
                        "type": name,
                        "configuration": ast.unparse(node),
                    }
                )
            for keyword in node.keywords:
                if keyword.arg == "random_state":
                    seeds.append(ast.unparse(keyword.value))
    return {
        "models": sorted(models, key=lambda item: (item["type"], item["configuration"])),
        "splits": sorted(
            splits,
            key=lambda item: (
                item["method"],
                str(item["options"]),
                str(item["target_reference"]),
                str(item["output_variables"]),
            ),
        ),
        "random_seeds": sorted(seeds),
    }


def extract_metrics(execution: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract only explicitly labeled numeric metrics from captured cell outputs."""
    if execution.get("status") != "completed":
        return []
    patterns = [
        (
            name,
            re.compile(
                rf"\b(?P<label>{label})\b\s*[:=]\s*{_NUMBER}(?P<percent>\s*%)?",
                re.IGNORECASE,
            ),
        )
        for name, label in _METRIC_PATTERNS
    ]
    metrics = []
    for cell in execution.get("outputs", []):
        cell_number = cell.get("cell_number")
        for output in cell.get("outputs", []):
            text = output.get("text", "")
            if not isinstance(text, str):
                continue
            for metric_name, pattern in patterns:
                for match in pattern.finditer(text):
                    metrics.append(
                        {
                            "name": metric_name,
                            "label": match.group("label"),
                            "value": float(match.group(2)),
                            "unit": "percent" if match.group("percent") else "value",
                            "cell_number": cell_number,
                            "execution_id": execution.get("execution_id"),
                        }
                    )
    return metrics


def compare_experiments(
    original_execution: dict[str, Any],
    corrected_execution: dict[str, Any],
    original_cells: list[dict[str, Any]],
    corrected_cells: list[dict[str, Any]],
) -> dict[str, Any]:
    original_context = _execution_context(original_cells)
    corrected_context = _execution_context(corrected_cells)
    original_datasets = original_execution.get("dataset_references", [])
    corrected_datasets = corrected_execution.get("dataset_references", [])
    original_dataset_set = sorted(
        original_datasets,
        key=lambda item: (item.get("dataset_id", ""), item.get("filename", "")),
    )
    corrected_dataset_set = sorted(
        corrected_datasets,
        key=lambda item: (item.get("dataset_id", ""), item.get("filename", "")),
    )
    differences: list[dict[str, Any]] = []
    limitations: list[str] = []

    def compare_setting(name: str, original: Any, corrected: Any, *, required: bool):
        if original != corrected:
            differences.append(
                {"setting": name, "original": original, "corrected": corrected}
            )
            limitations.append(f"{name} differs between the two runs.")
        elif required and not original:
            limitations.append(f"{name} could not be established from the records.")

    compare_setting(
        "dataset_references",
        original_dataset_set,
        corrected_dataset_set,
        required=True,
    )
    compare_setting(
        "model_configuration",
        original_context["models"],
        corrected_context["models"],
        required=True,
    )
    original_split_protocol = [
        {
            key: split.get(key)
            for key in ("method", "options", "target_reference", "output_variables")
        }
        for split in original_context["splits"]
    ]
    corrected_split_protocol = [
        {
            key: split.get(key)
            for key in ("method", "options", "target_reference", "output_variables")
        }
        for split in corrected_context["splits"]
    ]
    compare_setting(
        "train_test_split_configuration",
        original_split_protocol,
        corrected_split_protocol,
        required=True,
    )
    compare_setting(
        "random_seeds",
        original_context["random_seeds"],
        corrected_context["random_seeds"],
        required=True,
    )
    intentional_changes = []
    original_features = [
        split.get("feature_reference") for split in original_context["splits"]
    ]
    corrected_features = [
        split.get("feature_reference") for split in corrected_context["splits"]
    ]
    if original_features != corrected_features:
        differences.append(
            {
                "setting": "feature_input_expression",
                "original": original_features,
                "corrected": corrected_features,
            }
        )
        intentional_changes.append(
            "The feature expression passed to the split changed. This may be required by the approved preprocessing repair; interpret any metric difference alongside that change."
        )
    compare_setting(
        "python_version",
        original_execution.get("python_version"),
        corrected_execution.get("python_version"),
        required=True,
    )
    compare_setting(
        "execution_environment",
        original_execution.get("environment"),
        corrected_execution.get("environment"),
        required=True,
    )
    source_text = "\n".join(
        cell.get("source", "")
        for cell in [*original_cells, *corrected_cells]
        if cell.get("cell_type") == "code"
    )
    relevant_packages = []
    for package, pattern in (
        ("scikit-learn", r"\bsklearn\b"),
        ("numpy", r"\b(?:numpy|np\.)"),
        ("pandas", r"\b(?:pandas|pd\.)"),
        ("scipy", r"\bscipy\b"),
    ):
        if re.search(pattern, source_text):
            relevant_packages.append(package)
    for package in relevant_packages:
        original_version = _package_version(original_execution, package)
        corrected_version = _package_version(corrected_execution, package)
        if package in relevant_packages and (
            original_version is None or corrected_version is None
        ):
            limitations.append(
                f"The {package} package version is missing from one or both execution records."
            )
        if original_version != corrected_version and (
            original_version is not None or corrected_version is not None
        ):
            differences.append(
                {
                    "setting": f"package:{package}",
                    "original": original_version,
                    "corrected": corrected_version,
                }
            )
            limitations.append(f"The {package} package version differs.")

    same_nonempty_datasets = bool(original_dataset_set) and (
        original_dataset_set == corrected_dataset_set
    )
    executions_completed = (
        original_execution.get("status") == "completed"
        and corrected_execution.get("status") == "completed"
    )
    if not executions_completed:
        limitations.append(
            "Both executions must complete successfully before metric comparison is available."
        )
    comparable = same_nonempty_datasets and executions_completed and not limitations
    original_metrics = extract_metrics(original_execution)
    corrected_metrics = extract_metrics(corrected_execution)
    for metric in original_metrics:
        metric["evaluation_dataset_references"] = original_dataset_set
        metric["evaluation_split_configuration"] = original_context["splits"]
        metric["model_configuration"] = original_context["models"]
        metric["random_seeds"] = original_context["random_seeds"]
    for metric in corrected_metrics:
        metric["evaluation_dataset_references"] = corrected_dataset_set
        metric["evaluation_split_configuration"] = corrected_context["splits"]
        metric["model_configuration"] = corrected_context["models"]
        metric["random_seeds"] = corrected_context["random_seeds"]
    metric_comparisons = _compare_metric_values(
        original_metrics, corrected_metrics, comparable
    )
    if not original_metrics or not corrected_metrics:
        limitations.append(
            "No supported labeled metrics were captured in one or both execution records."
        )
    if not comparable and original_metrics and corrected_metrics:
        limitations.append(
            "Metric deltas are withheld because experiment comparability was not established."
        )

    return {
        "comparable": comparable,
        "comparability_reasons": list(dict.fromkeys(limitations)),
        "setup_differences": differences,
        "documented_changes": intentional_changes,
        "original_setup": original_context,
        "corrected_setup": corrected_context,
        "original_execution": _execution_summary(original_execution),
        "corrected_execution": _execution_summary(corrected_execution),
        "original_metrics": original_metrics,
        "corrected_metrics": corrected_metrics,
        "metric_comparisons": metric_comparisons,
    }


def build_verification(
    *,
    original_notebook: dict[str, Any],
    corrected_notebook: dict[str, Any],
    approved_repairs: list[dict[str, Any]],
    original_execution: dict[str, Any],
    corrected_execution: dict[str, Any],
    selected_repair_ids: list[str] | None = None,
) -> dict[str, Any]:
    original_analysis = original_notebook["analysis"]
    corrected_analysis = corrected_notebook["analysis"]
    manifest_by_id = {
        item["repair"]["repair_id"]: item for item in approved_repairs
    }
    repair_ids = (
        list(manifest_by_id)
        if selected_repair_ids is None
        else selected_repair_ids
    )
    if not repair_ids:
        raise ValueError("No approved repairs are associated with this notebook.")
    if len(repair_ids) != len(set(repair_ids)) or any(
        repair_id not in manifest_by_id for repair_id in repair_ids
    ):
        raise ValueError("One or more repair IDs are not approved for this notebook.")

    verification_results = [
        _verify_repair(
            manifest_by_id[repair_id],
            original_notebook["cells"],
            corrected_notebook["cells"],
            original_analysis.get("findings", []),
            corrected_analysis.get("findings", []),
            original_execution,
            corrected_execution,
        )
        for repair_id in repair_ids
    ]
    comparison = compare_experiments(
        original_execution,
        corrected_execution,
        original_notebook["cells"],
        corrected_notebook["cells"],
    )
    return {
        "verification_id": str(uuid.uuid4()),
        "original_notebook_id": original_notebook["notebook_id"],
        "corrected_notebook_id": corrected_notebook["notebook_id"],
        "original_execution_id": original_execution["execution_id"],
        "corrected_execution_id": corrected_execution["execution_id"],
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "original_execution_status": original_execution["status"],
        "corrected_execution_status": corrected_execution["status"],
        "findings": verification_results,
        "comparison": comparison,
        "limitations": [
            "Verification addresses only the specific stored finding and repair; it is not a proof of overall notebook correctness.",
            "Static evidence does not establish hidden data semantics, untracked data sources, or all runtime paths.",
            "Model performance comparison is separate from repair verification.",
        ],
    }


def _verify_repair(
    manifest: dict[str, Any],
    original_cells: list[dict[str, Any]],
    corrected_cells: list[dict[str, Any]],
    original_findings: list[dict[str, Any]],
    corrected_findings: list[dict[str, Any]],
    original_execution: dict[str, Any],
    corrected_execution: dict[str, Any],
) -> dict[str, Any]:
    repair = manifest["repair"]
    finding = manifest["finding"]
    rule_id = finding.get("rule_id", finding.get("id"))
    original_source = _cell_source_map(original_cells)
    corrected_source = _cell_source_map(corrected_cells)
    original_refs = finding.get("source_refs", [])
    if not original_refs:
        original_refs = [
            {"cell_index": index, "line": None}
            for index in finding.get("cell_indices", [])
        ]
    corrected_refs = [
        {"cell_index": index, "line": None}
        for index in repair.get("affected_cells", [])
    ]
    evidence: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    risks: list[str] = []
    limitations = list(repair.get("limitations", []))
    evidence.append(
        {
            "type": "original_finding_evidence",
            "items": finding.get("evidence", []),
        }
    )
    for change in repair.get("cell_changes", []):
        evidence.append(
            {
                "type": "approved_code_change",
                "cell_index": change["cell_index"],
                "original_code": change["original_code"],
                "corrected_code": change["corrected_code"],
            }
        )
    status = "inconclusive"
    original_finding_present = any(
        item.get("rule_id", item.get("id")) == rule_id for item in original_findings
    )
    checks.append(
        {
            "check": "finding_reproduced_in_stored_original",
            "passed": original_finding_present,
        }
    )
    if not original_finding_present:
        limitations.append(
            "The stored source no longer reproduces the original finding rule."
        )
        status = "inconclusive"
    elif corrected_execution.get("status") != "completed":
        status = (
            "execution_failed"
            if corrected_execution.get("status")
            in {"failed", "timed_out", "cancelled"}
            else "inconclusive"
        )
        if corrected_execution.get("status") == "unavailable":
            limitations.append(
                "Corrected notebook execution was unavailable; runtime verification was not performed."
            )
        else:
            limitations.append(
                "Corrected notebook execution did not complete successfully; runtime verification is incomplete."
            )
    elif original_execution.get("status") != "completed":
        limitations.append(
            "The original notebook execution did not complete successfully, so the two-run evidence is incomplete."
        )
    else:
        expected_changes = repair.get("cell_changes", [])
        source_changes_match = bool(expected_changes) and all(
            original_source.get(change["cell_index"]) == change["original_code"]
            and corrected_source.get(change["cell_index"]) == change["corrected_code"]
            for change in expected_changes
        )
        checks.append(
            {
                "check": "stored_approved_source_changes_match_notebook_versions",
                "passed": source_changes_match,
            }
        )
        if not source_changes_match:
            status = "not_verified"
            risks.append(
                "The approved source changes do not match the stored original/corrected notebook cells."
            )
        else:
            still_present = any(
                item.get("rule_id", item.get("id")) == rule_id
                for item in corrected_findings
            )
            checks.append(
                {
                    "check": "original_static_finding_absent_from_corrected_notebook",
                    "passed": not still_present,
                }
            )
            if still_present:
                status = "not_verified"
                risks.append("The original static finding remains in corrected source.")
            else:
                status, category_evidence, category_checks, category_risks, category_limits = (
                    _category_verdict(
                        rule_id,
                        finding,
                        repair,
                        original_cells,
                        corrected_cells,
                    )
                )
                evidence.extend(category_evidence)
                checks.extend(category_checks)
                risks.extend(category_risks)
                limitations.extend(category_limits)

    evidence.extend(
        _execution_evidence(original_execution, corrected_execution)
    )
    return {
        "finding_id": finding.get("id"),
        "finding_category": finding.get("category", "unknown"),
        "finding_title": finding.get("title", "Finding"),
        "repair_id": repair["repair_id"],
        "verification_status": status,
        "original_cell_references": original_refs,
        "corrected_cell_references": corrected_refs,
        "execution_ids": {
            "original": original_execution["execution_id"],
            "corrected": corrected_execution["execution_id"],
        },
        "checks_performed": checks,
        "evidence": evidence,
        "reasons": _status_reason(status, checks, risks),
        "remaining_risks": list(dict.fromkeys(risks)),
        "limitations": list(dict.fromkeys(limitations)),
    }


def _category_verdict(
    rule_id: str,
    finding: dict[str, Any],
    repair: dict[str, Any],
    original_cells: list[dict[str, Any]],
    corrected_cells: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
    corrected_sources = [
        cell.get("source", "")
        for cell in corrected_cells
        if cell.get("cell_type") == "code"
    ]
    all_corrected = "\n".join(corrected_sources)
    checks: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = [
        {
            "type": "original_finding_record",
            "finding_id": finding.get("id"),
            "source_references": finding.get("source_refs", []),
        }
    ]
    risks: list[str] = []
    limitations: list[str] = []
    if rule_id == "preprocessing_fit_before_split":
        transformed = _preprocessing_evidence(corrected_sources)
        checks.append(
            {
                "check": "preprocessing_fit_uses_training_partition_and_test_uses_transform",
                "passed": transformed["verified"],
                "details": transformed,
            }
        )
        evidence.append(
            {
                "type": "corrected_source_pattern",
                "details": transformed,
            }
        )
        if transformed["verified"]:
            risks.append(
                "Other learned preprocessing or data-dependent feature selection may still occur outside the checked pattern."
            )
            return "verified", evidence, checks, risks, [
                "The check verifies the recognized train-only fit and test transform pattern, not all preprocessing semantics."
            ]
        if transformed["training_fit_found"]:
            risks.append(
                "The corrected workflow does not show both a training-only fit and held-out transform."
            )
            return "partially_verified", evidence, checks, risks, [
                "The specific transformer pattern is only partially observable in static source."
            ]
        risks.append("No qualifying train-only preprocessing fit was identified.")
        return "not_verified", evidence, checks, risks, limitations

    if rule_id == "target_column_in_features":
        target_result = _target_feature_check(original_cells, corrected_cells)
        checks.append(
            {
                "check": "identified_target_column_removed_from_feature_selection",
                "passed": target_result["verified"],
                "details": target_result,
            }
        )
        evidence.append({"type": "target_column_source_check", **target_result})
        if target_result["verified"]:
            risks.append(
                "Other target-derived fields, aliases, or post-outcome features are not ruled out."
            )
            return "verified", evidence, checks, risks, [
                "The check covers only the exact literal target column identified by the original detector."
            ]
        if target_result["target_columns"]:
            risks.append("The identified target column remains in a feature selection.")
            return "not_verified", evidence, checks, risks, limitations
        return "inconclusive", evidence, checks, risks, [
            "Could not reliably identify the original target/feature column relationship in stored source."
        ]

    if rule_id in {
        "test_metric_used_for_model_selection",
        "test_data_used_for_fit",
        "evaluation_on_training_data",
        "training_data_used_for_evaluation",
    }:
        uses_validation = bool(
            re.search(
                r"\b(?:validation|valid)[A-Za-z0-9_]*\b|\b(?:cross_val_score|cross_validate|GridSearchCV|RandomizedSearchCV)\b",
                all_corrected,
                re.IGNORECASE,
            )
        )
        checks.append(
            {
                "check": "validation_or_cross_validation_evidence_present",
                "passed": uses_validation,
            }
        )
        evidence.append(
            {
                "type": "corrected_evaluation_source",
                "cell_references": repair.get("affected_cells", []),
                "validation_or_cross_validation_present": uses_validation,
            }
        )
        if uses_validation:
            return "partially_verified", evidence, checks, [
                "The recognized validation pattern is present, but test-set isolation and runtime data flow are not established."
            ], [
                "Static variable names and API usage do not prove which records were used at runtime."
            ]
        return "inconclusive", evidence, checks, [
            "No recognizable validation or cross-validation pattern supports the intended correction."
        ], [
            "This evaluation issue requires notebook-specific judgment beyond the available static evidence."
        ]

    if rule_id in {
        "exact_train_test_row_overlap",
        "train_test_identifier_overlap",
        "train_test_group_overlap",
    }:
        if rule_id == "exact_train_test_row_overlap":
            deduplicated = bool(
                re.search(r"\.drop_duplicates\s*\(", all_corrected)
            )
            checks.append(
                {
                    "check": "duplicate_row_removal_pattern_present",
                    "passed": deduplicated,
                }
            )
            evidence.append(
                {
                    "type": "duplicate_row_source_check",
                    "drop_duplicates_present": deduplicated,
                }
            )
            risks.append(
                "No post-correction row-overlap check was run against the associated datasets."
            )
            return (
                "partially_verified" if deduplicated else "inconclusive",
                evidence,
                checks,
                risks,
                [
                    "drop_duplicates source usage does not establish that the specific overlap was removed or that duplicate rows represent the same entity."
                ],
            )
        has_group_split = bool(
            re.search(
                r"\b(?:GroupKFold|GroupShuffleSplit|GroupStratifiedKFold)\b",
                all_corrected,
            )
        )
        has_groups_argument = bool(
            re.search(r"\bgroups\s*=", all_corrected)
        )
        checks.append(
            {
                "check": "group_aware_split_uses_explicit_groups",
                "passed": has_group_split and has_groups_argument,
            }
        )
        evidence.append(
            {
                "type": "group_split_source_check",
                "group_split_present": has_group_split,
                "groups_argument_present": has_groups_argument,
            }
        )
        risks.append(
            "The verification cannot establish that the group variable represents the same real-world entity as the original overlap identifier."
        )
        if has_group_split and has_groups_argument:
            return "partially_verified", evidence, checks, risks, [
                "Dataset membership was not re-compared after correction; source use of a group-aware splitter is supporting evidence only."
            ]
        return "inconclusive", evidence, checks, risks, [
            "No persisted post-correction overlap analysis or reliable identifier association is available."
        ]

    if rule_id == "classification_split_without_stratify_review":
        stratified = bool(
            re.search(
                r"\b(?:stratify\s*=\s*y|Stratified(?:ShuffleSplit|KFold))\b",
                all_corrected,
            )
        )
        checks.append({"check": "stratified_split_pattern_present", "passed": stratified})
        evidence.append(
            {"type": "corrected_split_source", "stratified_pattern_present": stratified}
        )
        return (
            "partially_verified" if stratified else "inconclusive",
            evidence,
            checks,
            ["Class balance in the resulting partitions was not computed."],
            ["Stratification appropriateness depends on dataset and task semantics."],
        )

    return (
        "not_applicable",
        evidence,
        checks,
        risks,
        ["No category-specific verification rule supports this finding."],
    )


def _preprocessing_evidence(sources: list[str]) -> dict[str, Any]:
    training_fit_found = False
    test_transform_found = False
    invalid_fit_found = False
    fitting_receivers: set[str] = set()
    transforms: set[str] = set()
    for source in sources:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            receiver = node.func.value.id if isinstance(node.func.value, ast.Name) else ""
            argument = (
                node.args[0].id
                if node.args and isinstance(node.args[0], ast.Name)
                else ""
            )
            if node.func.attr in {"fit_transform", "fit"}:
                if _TRAIN_NAME.search(argument):
                    training_fit_found = True
                    fitting_receivers.add(receiver)
                elif argument:
                    invalid_fit_found = True
            elif node.func.attr == "transform" and _TEST_NAME.search(argument):
                transforms.add(receiver)
    test_transform_found = bool(fitting_receivers & transforms)
    return {
        "verified": training_fit_found and test_transform_found and not invalid_fit_found,
        "training_fit_found": training_fit_found,
        "test_transform_found": test_transform_found,
        "non_partition_fit_found": invalid_fit_found,
        "fitting_receivers": sorted(fitting_receivers),
        "test_transform_receivers": sorted(transforms),
    }


def _target_feature_check(
    original_cells: list[dict[str, Any]], corrected_cells: list[dict[str, Any]]
) -> dict[str, Any]:
    targets: dict[str, set[str]] = {}
    for cell in original_cells:
        if cell.get("cell_type") != "code":
            continue
        try:
            tree = ast.parse(cell.get("source", ""))
        except SyntaxError:
            continue
        for statement in tree.body:
            if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                continue
            assigned = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
            )
            assigned_names = {
                item.id
                for target in assigned
                for item in ast.walk(target)
                if isinstance(item, ast.Name)
            }
            value = statement.value
            if (
                assigned_names & _TARGET_NAMES
                and isinstance(value, ast.Subscript)
                and isinstance(value.value, ast.Name)
                and isinstance(value.slice, ast.Constant)
                and isinstance(value.slice.value, str)
            ):
                targets.setdefault(value.value.id, set()).add(value.slice.value)

    target_columns = sorted(set().union(*targets.values()) if targets else set())
    remaining = set()
    target_preserved = False
    for cell in corrected_cells:
        if cell.get("cell_type") != "code":
            continue
        try:
            tree = ast.parse(cell.get("source", ""))
        except SyntaxError:
            continue
        for statement in tree.body:
            if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                continue
            assigned = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
            )
            names = {
                item.id
                for target in assigned
                for item in ast.walk(target)
                if isinstance(item, ast.Name)
            }
            value = statement.value
            if (
                names & _TARGET_NAMES
                and isinstance(value, ast.Subscript)
                and isinstance(value.value, ast.Name)
                and isinstance(value.slice, ast.Constant)
                and value.slice.value in target_columns
            ):
                target_preserved = True
            if (
                isinstance(value, ast.Subscript)
                and isinstance(value.value, ast.Name)
                and isinstance(value.slice, ast.List)
            ):
                feature_columns = {
                    item.value
                    for item in value.slice.elts
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                }
                remaining.update(feature_columns & set(target_columns))
    return {
        "verified": bool(target_columns) and not remaining and target_preserved,
        "target_columns": target_columns,
        "remaining_target_feature_columns": sorted(remaining),
        "target_assignment_preserved": target_preserved,
    }


def _cell_source_map(cells: list[dict[str, Any]]) -> dict[int, str]:
    return {
        cell["index"]: cell.get("source", "")
        for cell in cells
        if isinstance(cell.get("index"), int)
    }


def _execution_evidence(
    original_execution: dict[str, Any], corrected_execution: dict[str, Any]
) -> list[dict[str, Any]]:
    return [
        {
            "type": "execution_record",
            "execution_id": execution["execution_id"],
            "notebook_id": execution["notebook_id"],
            "notebook_type": execution.get("notebook_type"),
            "status": execution["status"],
            "executed_cell_count": execution.get("executed_cell_count", 0),
            "successful_cell_count": execution.get("successful_cell_count", 0),
            "failed_cell_number": execution.get("failed_cell_number"),
        }
        for execution in (original_execution, corrected_execution)
    ]


def _execution_summary(execution: dict[str, Any]) -> dict[str, Any]:
    return {
        "execution_id": execution.get("execution_id"),
        "notebook_id": execution.get("notebook_id"),
        "notebook_type": execution.get("notebook_type"),
        "status": execution.get("status"),
        "duration_seconds": execution.get("duration_seconds"),
        "executed_cell_count": execution.get("executed_cell_count", 0),
        "successful_cell_count": execution.get("successful_cell_count", 0),
        "failed_cell_number": execution.get("failed_cell_number"),
        "dataset_references": execution.get("dataset_references", []),
        "environment": execution.get("environment", {}),
        "python_version": execution.get("python_version"),
        "package_versions": execution.get("package_versions", {}),
    }


def _compare_metric_values(
    original: list[dict[str, Any]],
    corrected: list[dict[str, Any]],
    comparable: bool,
) -> list[dict[str, Any]]:
    names = list(dict.fromkeys(item["name"] for item in [*original, *corrected]))
    comparisons = []
    for name in names:
        original_values = [item for item in original if item["name"] == name]
        corrected_values = [item for item in corrected if item["name"] == name]
        values_match = (
            len(original_values) == len(corrected_values)
            and all(
                left["unit"] == right["unit"]
                for left, right in zip(original_values, corrected_values)
            )
        )
        deltas = []
        if comparable and values_match:
            deltas = [
                right["value"] - left["value"]
                for left, right in zip(original_values, corrected_values)
            ]
        percentage_point_deltas = []
        is_rate_metric = name in {
            "accuracy",
            "precision",
            "recall",
            "f1",
            "roc_auc",
        }
        if deltas and is_rate_metric:
            percentage_point_deltas = [
                delta * 100
                if left["unit"] == "value"
                and abs(left["value"]) <= 1
                and abs(right["value"]) <= 1
                else delta
                for left, right, delta in zip(
                    original_values, corrected_values, deltas
                )
            ]
        comparisons.append(
            {
                "name": name,
                "original_values": [item["value"] for item in original_values],
                "corrected_values": [item["value"] for item in corrected_values],
                "unit": (
                    original_values[0]["unit"]
                    if original_values
                    and corrected_values
                    and original_values[0]["unit"] == corrected_values[0]["unit"]
                    else None
                ),
                "deltas": deltas,
                "difference_percentage_points": percentage_point_deltas,
                "comparison_available": bool(comparable and values_match),
                "reason": (
                    None
                    if comparable and values_match
                    else "Metric observations or experimental setup are not comparable."
                ),
            }
        )
    return comparisons


def _package_version(execution: dict[str, Any], wanted: str) -> str | None:
    versions = execution.get("package_versions", {})
    return next(
        (
            value
            for name, value in versions.items()
            if name.casefold().replace("_", "-") == wanted
        ),
        None,
    )


def _status_reason(status: str, checks: list[dict[str, Any]], risks: list[str]) -> list[str]:
    labels = {
        "verified": "Available source and completed execution evidence supports that this specific issue was addressed.",
        "partially_verified": "Some supporting evidence is present, but the available checks do not establish the full correction.",
        "not_verified": "Available evidence indicates that the correction was not applied as approved or the finding remains.",
        "inconclusive": "The stored evidence is insufficient to determine whether the issue was addressed.",
        "execution_failed": "The corrected notebook execution did not complete, preventing the required runtime verification.",
        "not_applicable": "No supported category-specific verification rule applies to this repair.",
    }
    failed_checks = [
        f"Check not satisfied: {item['check']}."
        for item in checks
        if item.get("passed") is False
    ]
    return [labels[status], *failed_checks, *risks]
