"""Conservative, source-only inspection of common Python ML notebook patterns."""

import ast
import re
from typing import Any

from backend.app.services.audit_analyzer import analyze_findings
from backend.app.services.detection_engine import detect_findings


ANALYSIS_LIMITATIONS = [
    "Results are static-source inferences, not runtime observations.",
    "Notebook order and saved execution counts do not establish execution order.",
    "Variable aliases, dynamic dispatch, generated code, and complex data flow may not be resolved.",
    "Control-flow branches and repeated variable assignments are not modeled.",
    "Dataset paths and URLs are reported as source references; no data is loaded or contacted.",
    "Potential findings require human review and do not prove leakage or invalid evaluation.",
]
CONFIDENCE_DEFINITIONS = {
    "high": "The source directly supports the reported relationship or configured dataset comparison; runtime semantics may still be unknown.",
    "medium": "The source contains a recognizable pattern, but data semantics or intent remain uncertain.",
    "low": "A weak, name-based, or context-dependent signal requiring manual review.",
}
SEVERITY_DEFINITIONS = {
    "high": "A direct source-pattern concern that should be reviewed promptly; it is not proof of a runtime defect.",
    "medium": "A recognizable pattern with important uncertainty about data contents or execution context.",
    "low": "A weak or fallback-only signal; review manually before drawing conclusions.",
    "informational": "A context prompt for human review, not a finding that a defect occurred.",
}

DATASET_READERS = {
    "read_csv", "read_table", "read_parquet", "read_excel", "read_json",
    "read_pickle", "read_feather", "read_sql", "load",
}
PREPROCESSOR_TYPES = {
    "StandardScaler", "MinMaxScaler", "RobustScaler", "OneHotEncoder",
    "LabelEncoder", "OrdinalEncoder", "SimpleImputer", "ColumnTransformer",
    "Pipeline", "SelectKBest", "SelectFromModel", "RFE", "VarianceThreshold",
    "PCA", "TruncatedSVD", "KBinsDiscretizer", "SelectPercentile",
    "make_pipeline", "make_union",
}
DATA_CLEANERS = {"drop_duplicates", "drop", "replace", "rename"}
MISSING_VALUE_HANDLERS = {"dropna", "fillna", "interpolate"}
SPLITTERS = {"train_test_split", "StratifiedShuffleSplit", "KFold", "StratifiedKFold"}
PREDICTORS = {"predict", "predict_proba", "decision_function"}
EVALUATORS = {
    "score", "evaluate", "accuracy_score", "balanced_accuracy_score",
    "precision_score", "recall_score", "f1_score", "roc_auc_score",
    "mean_squared_error", "mean_absolute_error", "classification_report",
    "confusion_matrix",
}
MODEL_SUFFIXES = ("Classifier", "Regressor", "Model", "Estimator")


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Call):
        return _name(node.func)
    return ""


def _call_name(node: ast.Call) -> str:
    return _name(node.func).split(".")[-1]


def _targets(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return set().union(*(_targets(item) for item in node.elts))
    return set()


def _variables(node: ast.AST) -> set[str]:
    return {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}


def _literal_strings(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return set().union(*(_literal_strings(item) for item in node.elts))
    return set()


def _selected_columns(node: ast.AST) -> set[str]:
    return set().union(
        *(
            _literal_strings(item.slice)
            for item in ast.walk(node)
            if isinstance(item, ast.Subscript)
        )
    )


def _source_segment(source: str, node: ast.AST) -> str:
    return ast.get_source_segment(source, node) or ""


def _operation_kind(call: ast.Call) -> str | None:
    method = _call_name(call)
    lower = method.lower()
    if method in DATASET_READERS:
        return "data_source"
    if method in SPLITTERS:
        return "split"
    if method in DATA_CLEANERS:
        return "cleaning"
    if method in MISSING_VALUE_HANDLERS:
        return "missing_value_handling"
    if lower in {
        "fit_transform", "transform", "impute", "normalize",
        "standardize", "scale", "encode", "get_dummies",
    }:
        return "preprocessing"
    if method == "fit" and isinstance(call.func, ast.Attribute):
        receiver = _name(call.func.value).lower()
        if any(
            part in receiver
            for part in (
                "scal", "imput", "encod", "vector", "transform", "prep",
                "pca", "svd", "select", "discret",
            )
        ):
            return "preprocessing"
    if method in PREDICTORS:
        return "prediction"
    if method in EVALUATORS or lower.endswith("_score"):
        return "evaluation"
    if method == "fit" and isinstance(call.func, ast.Attribute):
        return "training"
    if method in {"array", "asarray", "DataFrame", "Series"}:
        return "data_source"
    if method in PREPROCESSOR_TYPES:
        return "preprocessing"
    if method.endswith(MODEL_SUFFIXES) or (
        method.startswith(("LogisticRegression", "LinearRegression", "SVC", "SVR", "KMeans"))
    ):
        return "model"
    return None


def analyze_notebook(cells: list[dict[str, Any]]) -> dict[str, Any]:
    imports: list[dict[str, Any]] = []
    libraries: set[str] = set()
    operations: list[dict[str, Any]] = []
    graph_nodes: list[dict[str, Any]] = []
    graph_edges: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    limitations = list(ANALYSIS_LIMITATIONS)
    limitations.append(
        "Target-derived feature leakage and context-dependent test-set reuse are not automatically classified."
    )
    parse_fallback_cells: list[int] = []
    dataset_refs: list[dict[str, Any]] = []
    selection_uses: list[dict[str, Any]] = []
    node_counter = 0
    previous_nodes_by_variable: dict[str, list[str]] = {}
    seen_edges: set[tuple[str, str, str]] = set()
    unresolved_references: list[dict[str, Any]] = []

    def add_operation(
        kind: str, node: ast.Call, tree: ast.AST, cell: dict[str, Any], source: str
    ) -> dict[str, Any]:
        nonlocal node_counter
        call_name = _call_name(node)
        line = getattr(node, "lineno", 1)
        segment = _source_segment(source, node)
        node_id = f"cell-{cell['index']}-op-{node_counter}"
        node_counter += 1
        assigned_vars: set[str] = set()
        for parent in ast.walk(tree):
            if isinstance(parent, ast.Assign) and parent.value is node:
                for target in parent.targets:
                    assigned_vars.update(_targets(target))
            elif isinstance(parent, (ast.AnnAssign, ast.NamedExpr)) and parent.value is node:
                assigned_vars.update(_targets(parent.target))
            elif isinstance(parent, ast.Call) and parent is node and kind == "split":
                for ancestor in ast.walk(tree):
                    if isinstance(ancestor, ast.Assign) and ancestor.value is node:
                        for target in ancestor.targets:
                            assigned_vars.update(_targets(target))

        used_vars = set()
        for argument in [*node.args, *(keyword.value for keyword in node.keywords)]:
            used_vars.update(_variables(argument))
        if isinstance(node.func, ast.Attribute):
            used_vars.update(_variables(node.func.value))

        operation = {
            "id": node_id,
            "kind": kind,
            "name": call_name,
            "cell_index": cell["index"],
            "line": line,
            "source": segment,
            "receiver": (
                _name(node.func.value)
                if isinstance(node.func, ast.Attribute)
                else None
            ),
            "argument_variables": [
                sorted(_variables(argument)) for argument in node.args
            ],
            "keyword_names": [
                keyword.arg for keyword in node.keywords if keyword.arg
            ],
            "inputs": sorted(
                (used_vars - assigned_vars)
                | (
                    _variables(node.func.value)
                    if isinstance(node.func, ast.Attribute)
                    else set()
                )
            ),
            "outputs": sorted(assigned_vars),
            "source_ref": {"cell_index": cell["index"], "line": line},
        }
        operations.append(operation)
        graph_nodes.append(
            {
                "id": node_id,
                "kind": kind,
                "label": f"{call_name} · cell {cell['index']}",
                "cell_index": cell["index"],
                "line": line,
                "source": segment,
                "evidence": "static_ast",
                "source_ref": operation["source_ref"],
            }
        )
        for variable in operation["inputs"]:
            producer_ids = previous_nodes_by_variable.get(variable, [])
            if not producer_ids:
                unresolved_references.append(
                    {
                        "node_id": node_id,
                        "variable": variable,
                        "reason": "No earlier recognized producer was identified in source.",
                        "source_ref": operation["source_ref"],
                    }
                )
            for parent_id in producer_ids:
                edge_key = (parent_id, node_id, variable)
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    graph_edges.append(
                        {
                            "source": parent_id,
                            "target": node_id,
                            "variable": variable,
                            "relationship": "inferred_from_variable_reference",
                            "evidence": "static_ast",
                            "source_refs": [operation["source_ref"]],
                        }
                    )
        for variable in operation["outputs"]:
            previous_nodes_by_variable[variable] = [node_id]
        return operation

    for cell in cells:
        source = cell["source"]
        if cell["cell_type"] == "markdown":
            continue
        if cell["cell_type"] != "code":
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            parse_fallback_cells.append(cell["index"])
            fallback_patterns = (
                ("train_test_split", "split"),
                ("\\.fit\\s*\\(", "training"),
                ("\\.predict(?:_proba)?\\s*\\(", "prediction"),
                ("\\.score\\s*\\(", "evaluation"),
            )
            for pattern, kind in fallback_patterns:
                match = re.search(pattern, source)
                if match:
                    line = source.count("\n", 0, match.start()) + 1
                    source_ref = {"cell_index": cell["index"], "line": line}
                    operation = {
                        "id": f"cell-{cell['index']}-fallback-{kind}",
                        "kind": kind,
                        "name": match.group(0).split("(")[0].lstrip("."),
                        "cell_index": cell["index"],
                        "line": line,
                        "source": source.splitlines()[line - 1].strip(),
                        "inputs": [],
                        "outputs": [],
                        "source_ref": source_ref,
                        "evidence": "source_text_fallback",
                    }
                    operations.append(operation)
                    graph_nodes.append(
                        {
                            "id": operation["id"],
                            "kind": kind,
                            "label": f"{operation['name']} · cell {cell['index']}",
                            "cell_index": cell["index"],
                            "line": line,
                            "source": operation["source"],
                            "evidence": "source_text_fallback",
                            "source_ref": source_ref,
                        }
                    )
            continue

        ordered_nodes = sorted(
            ast.walk(tree),
            key=lambda item: (
                getattr(item, "lineno", 0),
                getattr(item, "col_offset", 0),
                0 if isinstance(item, ast.Assign) else 1,
            ),
        )
        parent_by_node = {
            id(child): parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        operation_by_call: dict[int, dict[str, Any]] = {}
        for item in ordered_nodes:
            if isinstance(item, (ast.If, ast.While)):
                selection_uses.extend(
                    {
                        "variable": variable,
                        "cell_index": cell["index"],
                        "line": item.lineno,
                        "source": _source_segment(source, item.test),
                    }
                    for variable in sorted(_variables(item.test))
                )
            elif isinstance(item, ast.Import):
                for alias in item.names:
                    module = alias.name
                    imports.append(
                        {
                            "module": module,
                            "name": alias.asname or module.split(".")[0],
                            "cell_index": cell["index"],
                            "line": item.lineno,
                        }
                    )
                    libraries.add(module.split(".")[0])
            elif isinstance(item, ast.ImportFrom):
                module = item.module or ""
                if module:
                    libraries.add(module.split(".")[0])
                for alias in item.names:
                    imports.append(
                        {
                            "module": module,
                            "name": alias.asname or alias.name,
                            "cell_index": cell["index"],
                            "line": item.lineno,
                        }
                    )
            elif isinstance(item, ast.Call):
                kind = _operation_kind(item)
                if not kind:
                    continue
                operation_by_call[id(item)] = add_operation(
                    kind, item, tree, cell, source
                )
                if kind == "data_source":
                    argument = item.args[0] if item.args else next(
                        (keyword.value for keyword in item.keywords if keyword.arg in {"filepath_or_buffer", "path"}),
                        None,
                    )
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                        dataset_refs.append(
                            {
                                "path": argument.value,
                                "cell_index": cell["index"],
                                "line": item.lineno,
                                "operation": _call_name(item),
                                "inferred": True,
                            }
                        )
            elif isinstance(item, (ast.Assign, ast.AnnAssign)):
                value = item.value
                targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                if value is not None:
                    call_operations = [
                        candidate
                        for candidate in ast.walk(value)
                        if isinstance(candidate, ast.Call) and _operation_kind(candidate)
                    ]
                    output_names = set().union(*(_targets(target) for target in targets))
                    input_names = _variables(value) - output_names
                    if not call_operations and output_names and input_names:
                        line = getattr(item, "lineno", 1)
                        segment = _source_segment(source, item)
                        node_id = f"cell-{cell['index']}-assign-{node_counter}"
                        node_counter += 1
                        source_ref = {"cell_index": cell["index"], "line": line}
                        operation = {
                            "id": node_id,
                            "kind": "feature_engineering",
                            "name": ", ".join(sorted(output_names)),
                            "cell_index": cell["index"],
                            "line": line,
                            "source": segment,
                            "inputs": sorted(input_names),
                            "outputs": sorted(output_names),
                            "selected_columns": sorted(_selected_columns(value)),
                            "source_ref": source_ref,
                        }
                        operations.append(operation)
                        graph_nodes.append(
                            {
                                "id": node_id,
                                "kind": "feature_engineering",
                                "label": f"{operation['name']} · cell {cell['index']}",
                                "cell_index": cell["index"],
                                "line": line,
                                "source": segment,
                                "evidence": "static_ast",
                                "source_ref": source_ref,
                            }
                        )
                        for variable in operation["inputs"]:
                            producer_ids = previous_nodes_by_variable.get(variable, [])
                            if not producer_ids:
                                unresolved_references.append(
                                    {
                                        "node_id": node_id,
                                        "variable": variable,
                                        "reason": "No earlier recognized producer was identified in source.",
                                        "source_ref": source_ref,
                                    }
                                )
                            for parent_id in producer_ids:
                                edge_key = (parent_id, node_id, variable)
                                if edge_key not in seen_edges:
                                    seen_edges.add(edge_key)
                                    graph_edges.append(
                                        {
                                            "source": parent_id,
                                            "target": node_id,
                                            "variable": variable,
                                            "relationship": "inferred_from_variable_reference",
                                            "evidence": "static_ast",
                                            "source_refs": [source_ref],
                                        }
                                    )
                        for variable in operation["outputs"]:
                            previous_nodes_by_variable[variable] = [node_id]

        for item in ordered_nodes:
            operation = operation_by_call.get(id(item))
            if operation is None:
                continue
            parent = parent_by_node.get(id(item))
            while parent is not None and id(parent) not in operation_by_call:
                parent = parent_by_node.get(id(parent))
            if parent is not None:
                parent_operation = operation_by_call[id(parent)]
                if parent_operation["name"] in {
                    "Pipeline", "make_pipeline", "make_union", "ColumnTransformer"
                }:
                    operation["composition_parent_id"] = parent_operation["id"]

    pipeline_graph = {
        "nodes": graph_nodes,
        "edges": graph_edges,
        "unresolved_references": unresolved_references,
        "limitations": list(dict.fromkeys(limitations)),
        "trace_type": "static_inference_not_runtime_trace",
    }
    findings = detect_findings(
        operations,
        cells,
        pipeline_graph,
        analyze_findings(operations),
        selection_uses,
    )
    if parse_fallback_cells:
        limitations.append(
            "Python AST parsing failed for code cell(s) "
            + ", ".join(map(str, sorted(set(parse_fallback_cells))))
            + "; limited source-text fallback was used."
        )
    if not graph_edges:
        limitations.append(
            "No explicit variable-reference dependencies between recognized operations were established."
        )

    grouped = {
        key: [operation for operation in operations if operation["kind"] == key]
        for key in (
            "data_source", "feature_engineering", "preprocessing", "split", "model",
            "training", "prediction", "evaluation", "cleaning",
            "missing_value_handling",
        )
    }
    return {
        "imports": imports,
        "libraries": sorted(libraries),
        "dataset_references": dataset_refs,
        "operations": grouped,
        "all_operations": operations,
        "pipeline_graph": pipeline_graph,
        "findings": findings,
        "selection_uses": selection_uses,
        "confidence_definitions": CONFIDENCE_DEFINITIONS,
        "severity_definitions": SEVERITY_DEFINITIONS,
        "analysis_summary": (
            f"Static inspection identified {len(operations)} recognizable operation(s) "
            f"and {len(findings)} potential audit finding(s). Results are source-based inferences."
        ),
        "limitations": list(dict.fromkeys(limitations)),
    }
