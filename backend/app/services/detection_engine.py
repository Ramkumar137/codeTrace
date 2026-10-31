"""Evidence-based, source-only leakage and evaluation checks."""

import re
from typing import Any


POSITIONAL_FULL_DATA_NAMES = {"x", "features", "df", "data", "dataset"}
LEARNED_PREPROCESSORS = {
    "columntransformer",
    "kbinsdiscretizer",
    "kbest",
    "labelencoder",
    "minmaxscaler",
    "onehotencoder",
    "ordinalencoder",
    "rfe",
    "robustscaler",
    "selectfrommodel",
    "selectkbest",
    "selectpercentile",
    "simpleimputer",
    "standardscaler",
    "variancethreshold",
    "pca",
    "truncatedsvd",
    "pipeline",
    "make_pipeline",
}
CLASSIFIER_NAMES = {
    "logisticregression",
    "svc",
    "linear_svc",
    "sgdclassifier",
    "perceptron",
}
TARGET_VARIABLE_NAMES = {"y", "target", "targets", "label", "labels", "outcome"}
FUTURE_FEATURE_PATTERN = re.compile(
    r"(?:post[_ ]?outcome|after[_ ]?(?:event|outcome)|future[_ ]?(?:result|outcome)|target[_ ]?(?:derived|encoded))",
    re.IGNORECASE,
)


def _position(operation: dict[str, Any]) -> tuple[int, int]:
    return operation.get("cell_index", -1), operation.get("line", -1)


def _partition_name_matches(names: list[str], partition: str) -> bool:
    return any(
        re.search(rf"(?:^|_){partition}(?:_|$)", name.casefold())
        for name in names
    )


def _operation_at(
    operations: list[dict[str, Any]], source_ref: dict[str, int]
) -> dict[str, Any] | None:
    return next(
        (
            operation
            for operation in operations
            if operation.get("cell_index") == source_ref.get("cell_index")
            and operation.get("line") == source_ref.get("line")
        ),
        None,
    )


def _source_line(
    cells_by_index: dict[int, dict[str, Any]], cell_index: int, line: int
) -> str:
    cell = cells_by_index.get(cell_index)
    if not cell:
        return ""
    lines = cell.get("source", "").splitlines()
    if 1 <= line <= len(lines):
        return lines[line - 1].strip()
    return ""


def _make_finding(
    *,
    rule_id: str,
    category: str,
    title: str,
    description: str,
    severity: str,
    confidence: str,
    classification: str,
    recommendation: str,
    explanation: str,
    limitations: list[str],
    related_operations: list[dict[str, Any]],
    cells_by_index: dict[int, dict[str, Any]],
    extra_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    related_operations = list(
        {
            operation["id"]: operation
            for operation in related_operations
            if isinstance(operation.get("id"), str)
        }.values()
    )
    source_refs = []
    evidence = []
    variables: set[str] = set()
    for operation in related_operations:
        source_ref = operation.get("source_ref") or {
            "cell_index": operation.get("cell_index"),
            "line": operation.get("line"),
        }
        if source_ref not in source_refs:
            source_refs.append(source_ref)
        variables.update(operation.get("inputs", []))
        variables.update(operation.get("outputs", []))
        snippet = operation.get("source") or _source_line(
            cells_by_index, source_ref.get("cell_index", -1), source_ref.get("line", -1)
        )
        evidence.append(
            {
                "cell_index": source_ref.get("cell_index"),
                "line": source_ref.get("line"),
                "snippet": snippet,
            }
        )
    for item in extra_evidence or []:
        if item not in evidence:
            evidence.append(item)
        ref = {
            "cell_index": item.get("cell_index"),
            "line": item.get("line"),
        }
        if ref not in source_refs:
            source_refs.append(ref)

    return {
        "id": rule_id,
        "rule_id": rule_id,
        "category": category,
        "title": title,
        "description": description,
        "severity": severity,
        "confidence": confidence,
        "classification": classification,
        "status": "potential",
        "recommendation": recommendation,
        "explanation": explanation,
        "risk_explanation": explanation,
        "caveat": limitations[0] if limitations else "Static analysis cannot establish runtime behavior.",
        "limitations": limitations,
        "source_refs": source_refs,
        "cell_indices": sorted(
            {
                ref["cell_index"]
                for ref in source_refs
                if isinstance(ref.get("cell_index"), int)
            }
        ),
        "evidence": evidence,
        "source_code_evidence": evidence,
        "related_variables": sorted(variables),
        "related_pipeline_node_ids": [
            operation["id"] for operation in related_operations
        ],
        "evidence_type": "static_code_pattern",
    }


def _edge_adjacency(graph: dict[str, Any]) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {}
    for edge in graph.get("edges", []):
        source = edge.get("source")
        target = edge.get("target")
        if isinstance(source, str) and isinstance(target, str):
            adjacency.setdefault(source, set()).add(target)
    return adjacency


def _is_reachable(adjacency: dict[str, set[str]], start: str, end: str) -> bool:
    visited = set()
    queue = [start]
    while queue:
        current = queue.pop()
        if current == end:
            return True
        if current in visited:
            continue
        visited.add(current)
        queue.extend(adjacency.get(current, set()) - visited)
    return False


def _find_preprocessing_leakage(
    operations: list[dict[str, Any]],
    graph: dict[str, Any],
    cells_by_index: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    constructor_variables: dict[str, str] = {}
    for operation in operations:
        if operation.get("kind") == "preprocessing":
            name = operation.get("name", "").casefold()
            for variable in operation.get("outputs", []):
                constructor_variables[variable] = name

    adjacency = _edge_adjacency(graph)
    findings = []
    for operation in operations:
        if (
            operation.get("kind") != "preprocessing"
            or operation.get("name") not in {"fit", "fit_transform"}
        ):
            continue
        if operation.get("evidence") == "source_text_fallback":
            continue
        receiver = operation.get("receiver")
        receiver_type = constructor_variables.get(receiver, "")
        if (
            receiver_type not in LEARNED_PREPROCESSORS
            and (receiver or "").casefold() not in LEARNED_PREPROCESSORS
        ):
            continue

        input_variables = set().union(
            *(set(variables) for variables in operation.get("argument_variables", []))
        )
        if not input_variables:
            input_variables = set(operation.get("inputs", [])) - {receiver}
        if not input_variables or _partition_name_matches(
            list(input_variables), "train"
        ):
            continue

        later_splits = []
        for split in operations:
            if split.get("kind") != "split" or _position(split) <= _position(operation):
                continue
            split_variables = set(split.get("inputs", []))
            reaches_split = _is_reachable(
                adjacency, operation.get("id", ""), split.get("id", "")
            )
            direct_data_dependency = bool(input_variables & split_variables)
            if reaches_split or direct_data_dependency:
                later_splits.append(split)

        if not later_splits:
            continue
        finding = _make_finding(
            rule_id="preprocessing_fit_before_split",
            category="preprocessing_leakage",
            title="Learned preprocessing precedes the train-test split",
            description=(
                "A recognized learned transformer is fitted on data that flows into "
                "a later split, so held-out examples may have influenced its parameters."
            ),
            severity="medium",
            confidence="medium",
            classification="potential_risk",
            recommendation=(
                "Split the raw features first, fit the transformer using training "
                "features only, and place preprocessing inside a Pipeline when possible."
            ),
            explanation=(
                "The operation is a fit/fit_transform call on a recognized learned "
                "preprocessor, and its source dependency reaches a later train-test split."
            ),
            limitations=[
                "The analyzer cannot establish that the held-out rows were included at runtime from static variable dependencies and notebook source order alone.",
                "Aliases, dynamic execution, and mutations may change the actual data flow.",
            ],
            related_operations=[operation, *later_splits],
            cells_by_index=cells_by_index,
        )
        findings.append(finding)
    return findings


def _find_target_leakage(
    operations: list[dict[str, Any]],
    cells_by_index: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    target_variables: set[str] = set()
    split_targets: set[str] = set()
    for operation in operations:
        if operation.get("kind") == "split":
            arguments = operation.get("argument_variables", [])
            if len(arguments) > 1:
                split_targets.update(arguments[1])
        target_variables.update(
            name
            for name in operation.get("outputs", [])
            if name.casefold() in TARGET_VARIABLE_NAMES
        )
    target_variables.update(split_targets)

    target_column_sources: dict[str, dict[str, Any]] = {}
    for operation in operations:
        if target_variables.intersection(operation.get("outputs", [])):
            for column in operation.get("selected_columns", []):
                target_column_sources[column.casefold()] = operation

    findings = []
    for feature in operations:
        if feature.get("kind") not in {"feature_engineering", "cleaning"}:
            continue
        if target_variables.intersection(feature.get("outputs", [])):
            continue
        feature_sources = [feature]
        matched_columns = [
            column.casefold()
            for column in feature.get("selected_columns", [])
            if column.casefold() in target_column_sources
        ]
        if matched_columns:
            feature_sources.extend(
                target_column_sources[column] for column in matched_columns
            )
            findings.append(
                _make_finding(
                    rule_id="target_column_in_features",
                    category="target_leakage",
                    title="Target column is selected as a model feature",
                    description=(
                        "A column selected for a feature variable matches the column "
                        "used to construct the target variable."
                    ),
                    severity="high",
                    confidence="high",
                    classification="source_evidence",
                    recommendation=(
                        "Exclude the target column from feature construction and verify "
                        "that no target-derived values remain in the feature matrix."
                    ),
                    explanation=(
                        "Notebook assignments show the same literal dataframe column "
                        "used for both the target variable and a non-target feature variable."
                    ),
                    limitations=[
                        "The detector compares literal column names and assignment dependencies; it cannot establish the runtime dataframe contents.",
                    ],
                    related_operations=feature_sources,
                    cells_by_index=cells_by_index,
                )
            )
            continue

        used_targets = target_variables.intersection(feature.get("inputs", []))
        if used_targets:
            findings.append(
                _make_finding(
                    rule_id="target_variable_in_features",
                    category="target_leakage",
                    title="Target variable contributes to feature construction",
                    description=(
                        "A feature-construction assignment directly references a variable "
                        "used as the split target."
                    ),
                    severity="high",
                    confidence="medium",
                    classification="potential_risk",
                    recommendation=(
                        "Keep target values separate from feature construction and review "
                        "the derived feature expression."
                    ),
                    explanation=(
                        "The source dependency graph shows the target variable as an input "
                        "to a non-target feature assignment."
                    ),
                    limitations=[
                        "Variable names and static assignment dependencies do not prove that the feature contains target information at runtime.",
                    ],
                    related_operations=[feature],
                    cells_by_index=cells_by_index,
                )
            )
            continue

        suspicious_columns = [
            column
            for column in feature.get("selected_columns", [])
            if FUTURE_FEATURE_PATTERN.search(column)
        ]
        if suspicious_columns:
            findings.append(
                _make_finding(
                    rule_id="suspicious_outcome_feature",
                    category="target_leakage",
                    title="Feature name suggests post-outcome information",
                    description=(
                        "A selected feature name resembles a future or post-outcome "
                        "field and may encode information unavailable at prediction time."
                    ),
                    severity="low",
                    confidence="low",
                    classification="heuristic_suspicion",
                    recommendation=(
                        "Confirm when each field becomes available and remove features "
                        "that are recorded only after the outcome."
                    ),
                    explanation=(
                        "The warning is based only on the literal selected-column name; "
                        "the name may be benign in this domain."
                    ),
                    limitations=[
                        "Column-name heuristics do not establish feature timing or target dependence.",
                    ],
                    related_operations=[feature],
                    cells_by_index=cells_by_index,
                )
            )
    return findings


def _find_test_selection_feedback(
    operations: list[dict[str, Any]],
    selection_uses: list[dict[str, Any]],
    cells_by_index: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    findings = []
    for evaluation in operations:
        if evaluation.get("kind") != "evaluation":
            continue
        if not _partition_name_matches(evaluation.get("inputs", []), "test"):
            continue

        evaluation_position = _position(evaluation)
        output_names = set(evaluation.get("outputs", []))
        feedback_uses = [
            use
            for use in selection_uses
            if (
                use.get("variable") in output_names
                and (use.get("cell_index", -1), use.get("line", -1))
                > evaluation_position
            )
            or (
                use.get("cell_index") == evaluation_position[0]
                and use.get("line") == evaluation_position[1]
                and set(evaluation.get("inputs", [])).intersection(
                    {use.get("variable")}
                )
            )
        ]
        if not feedback_uses:
            continue

        extra_evidence = [
            {
                "cell_index": use["cell_index"],
                "line": use["line"],
                "snippet": use.get("source", ""),
            }
            for use in feedback_uses
        ]
        findings.append(
            _make_finding(
                rule_id="test_metric_used_for_model_selection",
                category="test_set_contamination",
                title="Test-set metric feeds a model-selection condition",
                description=(
                    "A metric evaluated on test-named data is reused in a later "
                    "conditional expression, potentially tuning decisions to the test set."
                ),
                severity="high",
                confidence="medium",
                classification="potential_risk",
                recommendation=(
                    "Use training-only cross-validation or a validation set for model "
                    "selection, then evaluate the locked model on the test set once."
                ),
                explanation=(
                    "Static source evidence links a test-data evaluation result to an "
                    "if/while condition."
                ),
                limitations=[
                    "Conditional use may be exploratory or unrelated to model selection; notebook intent and runtime values are not known.",
                ],
                related_operations=[evaluation],
                cells_by_index=cells_by_index,
                extra_evidence=extra_evidence,
            )
        )
    return findings


def _find_unstratified_classification_splits(
    operations: list[dict[str, Any]],
    graph: dict[str, Any],
    cells_by_index: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    classifiers = [
        operation
        for operation in operations
        if operation.get("kind") == "model"
        and (
            "classifier" in operation.get("name", "").casefold()
            or operation.get("name", "").casefold() in CLASSIFIER_NAMES
        )
    ]
    if not classifiers:
        return []

    adjacency = _edge_adjacency(graph)
    findings = []
    for split in operations:
        if (
            split.get("kind") != "split"
            or "stratify" in split.get("keyword_names", [])
            or len(split.get("argument_variables", [])) < 2
        ):
            continue
        related = [
            split,
            *(
                classifier
                for classifier in classifiers
                if any(
                    _is_reachable(adjacency, split.get("id", ""), training.get("id", ""))
                    and _is_reachable(adjacency, classifier.get("id", ""), training.get("id", ""))
                    for training in operations
                    if training.get("kind") == "training"
                )
            ),
        ]
        if len(related) == 1:
            continue
        findings.append(
            _make_finding(
                rule_id="classification_split_without_stratify_review",
                category="evaluation_flaw",
                title="Review class balance in the train-test split",
                description=(
                    "A split feeds a recognized classifier but does not specify "
                    "stratification. This is a review prompt, not proof of an invalid split."
                ),
                severity="informational",
                confidence="low",
                classification="informational_review",
                recommendation=(
                    "Inspect class counts in each partition; use stratify=y when "
                    "preserving class proportions is appropriate."
                ),
                explanation=(
                    "The source connects a two-argument data/target split to classifier "
                    "training, but no class distribution is available to this check."
                ),
                limitations=[
                    "No dataset class balance or split output is inspected; stratification is not always necessary or appropriate.",
                ],
                related_operations=related,
                cells_by_index=cells_by_index,
            )
        )
    return findings


def detect_findings(
    operations: list[dict[str, Any]],
    cells: list[dict[str, Any]],
    pipeline_graph: dict[str, Any],
    base_findings: list[dict[str, Any]],
    selection_uses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Combine the existing source-pattern audit with independent evidence rules."""
    cells_by_index = {
        cell["index"]: cell
        for cell in cells
        if isinstance(cell.get("index"), int)
    }
    findings = []
    category_by_rule = {
        "test_data_used_for_fit": "test_set_contamination",
        "evaluation_on_training_data": "evaluation_flaw",
    }
    for existing in base_findings:
        source_refs = existing.get("source_refs", [])
        related = [
            operation
            for ref in source_refs
            if (operation := _operation_at(operations, ref)) is not None
        ]
        findings.append(
            _make_finding(
                rule_id=existing["id"],
                category=category_by_rule.get(existing["id"], "evaluation_flaw"),
                title=existing["title"],
                description=existing["description"],
                severity=existing["severity"],
                confidence=existing["confidence"],
                classification="potential_risk",
                recommendation=existing["recommendation"],
                explanation=existing["explanation"],
                limitations=existing.get("limitations", [existing.get("caveat", "")]),
                related_operations=related,
                cells_by_index=cells_by_index,
            )
        )

    findings.extend(
        _find_preprocessing_leakage(
            operations, pipeline_graph, cells_by_index
        )
    )
    findings.extend(_find_target_leakage(operations, cells_by_index))
    findings.extend(
        _find_test_selection_feedback(
            operations, selection_uses, cells_by_index
        )
    )
    findings.extend(
        _find_unstratified_classification_splits(
            operations, pipeline_graph, cells_by_index
        )
    )

    counts: dict[str, int] = {}
    for finding in findings:
        rule_id = finding["rule_id"]
        counts[rule_id] = counts.get(rule_id, 0) + 1
        if counts[rule_id] > 1:
            reference = finding["source_refs"][0] if finding["source_refs"] else {}
            finding["id"] = (
                f"{rule_id}-cell{reference.get('cell_index', 'na')}"
                f"-line{reference.get('line', 'na')}-{counts[rule_id]}"
            )
        finding["rule_id"] = rule_id
    return findings
