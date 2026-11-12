"""Conservative source-only variable lineage for notebook cells."""

import ast
from typing import Any


_SPLITTERS = {"train_test_split"}
_FITTING = {"fit", "fit_transform", "partial_fit"}
_TRANSFORMS = {
    "transform",
    "copy",
    "drop",
    "rename",
    "assign",
    "fillna",
    "dropna",
    "astype",
    "shift",
    "rolling",
    "resample",
    "sort_values",
    "reset_index",
    "merge",
    "join",
    "concat",
    "where",
    "concatenate",
    "array",
    "asarray",
}
_SELECTORS = {"loc", "iloc", "select_dtypes"}
_PREDICTORS = {"predict", "predict_proba", "decision_function"}
_EVALUATORS = {
    "score",
    "evaluate",
    "accuracy_score",
    "f1_score",
    "roc_auc_score",
    "mean_squared_error",
    "mean_absolute_error",
    "classification_report",
    "confusion_matrix",
}
_PREPROCESSOR_NAMES = {
    "standardscaler",
    "minmaxscaler",
    "robustscaler",
    "onehotencoder",
    "ordinalencoder",
    "simpleimputer",
    "columntransformer",
    "pipeline",
    "selectkbest",
    "pca",
    "truncatedsvd",
}


def _assigned_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for item in target.elts for name in _assigned_names(item)]
    return []


def _variables(node: ast.AST) -> list[str]:
    return sorted({item.id for item in ast.walk(node) if isinstance(item, ast.Name)})


def _call_name(node: ast.Call) -> str:
    function = node.func
    if isinstance(function, ast.Attribute):
        return function.attr
    if isinstance(function, ast.Name):
        return function.id
    return ""


def _operation_type(value: ast.AST) -> str:
    if isinstance(value, ast.Call):
        name = _call_name(value)
        lowered = name.casefold()
        if lowered in _SPLITTERS:
            return "split"
        if lowered in _FITTING:
            return "preprocessing_fit" if lowered != "fit" else "fit"
        if lowered in _PREDICTORS:
            return "prediction"
        if lowered in _EVALUATORS or lowered.endswith("_score"):
            return "evaluation"
        if lowered in _TRANSFORMS:
            return "feature_engineering" if lowered in {"shift", "rolling", "resample"} else "transform"
        if lowered in _SELECTORS:
            return "selection"
        if lowered.startswith("read_") or lowered in {"load", "array", "asarray"}:
            return "data_source"
        if lowered in _PREPROCESSOR_NAMES:
            return "preprocessor_constructor"
        if lowered.endswith(("classifier", "regressor", "estimator")):
            return "model_constructor"
        return "call"
    if isinstance(value, ast.Subscript):
        return "selection"
    if isinstance(value, ast.Name):
        return "alias"
    return "assignment"


def _partition_for_name(name: str) -> str | None:
    """Use a variable suffix only as a low-confidence fallback, not as proof."""
    lowered = name.casefold()
    for partition in ("train", "validation", "val", "test"):
        if lowered.endswith(f"_{partition}") or lowered.endswith(f"_{partition}_data"):
            return "validation" if partition == "val" else partition
    return None


def analyze_variable_lineage(cells: list[dict[str, Any]]) -> dict[str, Any]:
    """Track assignment versions and explicit AST dependencies in notebook order."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    current: dict[str, str] = {}
    versions: dict[str, int] = {}
    operation_nodes: list[dict[str, Any]] = []
    limitations = [
        "Lineage follows top-level assignments in notebook cell order, not runtime execution order.",
        "Control flow, mutation through aliases, dynamic code, and implicit library semantics are not modeled.",
        "Partition labels from train_test_split follow its documented output ordering; name-derived labels are low-confidence hints.",
    ]

    def add_node(
        name: str,
        operation_type: str,
        cell_index: int,
        line: int,
        source: str,
        parent_names: list[str],
        *,
        parent_ids: list[str] | None = None,
        partition: str | None = None,
        role: str | None = None,
        confidence: str = "medium",
        uncertainties: list[str] | None = None,
    ) -> dict[str, Any]:
        version = versions.get(name, 0) + 1
        versions[name] = version
        resolved_parents = list(parent_ids or [])
        if parent_ids is None:
            resolved_parents = [current[parent] for parent in parent_names if parent in current]
        if partition is None and operation_type not in {"split", "data_source"}:
            inherited = {
                node_by_id[parent]["dataset_partition"]
                for parent in resolved_parents
                if parent in node_by_id and node_by_id[parent]["dataset_partition"]
            }
            if len(inherited) == 1:
                partition = inherited.pop()
        if partition is None:
            name_partition = _partition_for_name(name)
            if name_partition:
                partition = name_partition
                confidence = "low"
                (uncertainties := list(uncertainties or [])).append(
                    "Partition was inferred from the variable name, not a split operation."
                )
        node_id = f"lineage-{cell_index}-{line}-{name}-v{version}"
        node = {
            "id": node_id,
            "variable": name,
            "version": version,
            "parent_variables": list(dict.fromkeys(parent_names)),
            "parents": resolved_parents,
            "operation_type": operation_type,
            "cell_index": cell_index,
            "line": line,
            "source": source,
            "dataset_partition": partition,
            "data_role": role,
            "fits": operation_type in {"fit", "preprocessing_fit"},
            "transforms": operation_type in {"transform", "feature_engineering"},
            "selects": operation_type == "selection",
            "evaluates": operation_type == "evaluation",
            "confidence": confidence,
            "uncertainties": list(uncertainties or []),
        }
        nodes.append(node)
        node_by_id[node_id] = node
        current[name] = node_id
        for parent_id in resolved_parents:
            edges.append(
                {
                    "source": parent_id,
                    "target": node_id,
                    "relationship": "ast_variable_dependency",
                    "source_ref": {"cell_index": cell_index, "line": line},
                }
            )
        if operation_type in {
            "split",
            "fit",
            "preprocessing_fit",
            "prediction",
            "evaluation",
        }:
            operation_nodes.append(node)
        return node

    node_by_id: dict[str, dict[str, Any]] = {}
    for cell in sorted(cells, key=lambda item: item.get("index", -1)):
        if cell.get("cell_type") != "code":
            continue
        try:
            tree = ast.parse(cell.get("source", ""))
        except SyntaxError:
            continue
        for statement in tree.body:
            value: ast.AST | None = None
            targets: list[str] = []
            if isinstance(statement, ast.Assign):
                value = statement.value
                targets = [
                    name
                    for target in statement.targets
                    for name in _assigned_names(target)
                ]
            elif isinstance(statement, ast.AnnAssign):
                value = statement.value
                targets = _assigned_names(statement.target)
            elif isinstance(statement, ast.AugAssign):
                value = statement.value
                targets = _assigned_names(statement.target)

            if value is not None and targets:
                operation = _operation_type(value)
                source = ast.get_source_segment(cell.get("source", ""), statement) or ""
                line = getattr(statement, "lineno", 1)
                parent_names = _variables(value)
                call = value if isinstance(value, ast.Call) else None
                call_args = (
                    [argument for argument in call.args if isinstance(argument, ast.Name)]
                    if call and operation == "split"
                    else []
                )
                if operation == "split" and call_args:
                    input_names = [argument.id for argument in call_args]
                    for output_index, name in enumerate(targets):
                        input_index = output_index // 2
                        source_name = (
                            input_names[input_index]
                            if input_index < len(input_names)
                            else None
                        )
                        parents = [source_name] if source_name else parent_names
                        role = (
                            "feature"
                            if input_index == 0
                            else "target"
                            if input_index == 1
                            else None
                        )
                        add_node(
                            name,
                            "split",
                            cell["index"],
                            line,
                            source,
                            parents,
                            partition="train" if output_index % 2 == 0 else "test",
                            role=role,
                            confidence="high",
                        )
                else:
                    for name in targets:
                        if operation == "preprocessor_constructor":
                            confidence = "high"
                        elif operation == "alias":
                            confidence = "high"
                        else:
                            confidence = "medium"
                        add_node(
                            name,
                            operation,
                            cell["index"],
                            line,
                            source,
                            parent_names,
                            confidence=confidence,
                        )
            elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                call = statement.value
                call_name = _call_name(call).casefold()
                if call_name not in (_FITTING | _PREDICTORS | _EVALUATORS):
                    continue
                receiver = (
                    statement.value.func.value.id
                    if isinstance(statement.value.func, ast.Attribute)
                    and isinstance(statement.value.func.value, ast.Name)
                    else None
                )
                if not receiver:
                    continue
                operation = _operation_type(call)
                input_names = _variables(call)
                add_node(
                    receiver,
                    operation,
                    cell["index"],
                    getattr(statement, "lineno", 1),
                    ast.get_source_segment(cell.get("source", ""), statement) or "",
                    input_names,
                    confidence="medium",
                )

    return {
        "nodes": nodes,
        "edges": edges,
        "operations": operation_nodes,
        "limitations": limitations,
        "trace_type": "static_ast_assignment_lineage",
    }


def pre_split_preprocessing(lineage: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Return unpartitioned fitting nodes that flow into a later split node."""
    nodes = lineage.get("nodes", [])
    by_id = {node["id"]: node for node in nodes}
    ancestors: dict[str, set[str]] = {}

    def collect(node_id: str) -> set[str]:
        if node_id not in ancestors:
            parents = by_id.get(node_id, {}).get("parents", [])
            result = set(parents)
            for parent_id in parents:
                result.update(collect(parent_id))
            ancestors[node_id] = result
        return ancestors[node_id]

    findings = []
    for split in (node for node in nodes if node.get("operation_type") == "split"):
        split_position = (split["cell_index"], split["line"])
        for node_id in collect(split["id"]):
            fitted = by_id.get(node_id)
            if not fitted or not fitted.get("fits"):
                continue
            if fitted.get("dataset_partition") in {"train", "validation", "test"}:
                continue
            if (fitted["cell_index"], fitted["line"]) < split_position:
                findings.append((fitted, split))
    return findings
