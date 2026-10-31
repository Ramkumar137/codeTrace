"""Build a source-evidence pipeline graph from extracted notebook operations."""

import hashlib
from typing import Any


OPERATION_LABELS = {
    "dataset_loading": "Dataset loading",
    "data_cleaning": "Data cleaning",
    "missing_value_handling": "Missing-value handling",
    "data_encoding": "Data encoding",
    "data_scaling": "Data scaling",
    "feature_engineering": "Feature engineering",
    "feature_selection": "Feature selection",
    "train_test_split": "Train-test split",
    "model_initialization": "Model initialization",
    "model_training": "Model training",
    "prediction": "Prediction",
    "model_evaluation": "Model evaluation",
    "preprocessing": "Preprocessing",
    "unknown": "Unclassified operation",
}

MISSING_VALUE_NAMES = {
    "dropna", "fillna", "interpolate", "simpleimputer", "impute"
}
ENCODING_NAMES = {
    "onehotencoder", "labelencoder", "ordinalencoder", "get_dummies", "encode"
}
SCALING_NAMES = {"standardscaler", "minmaxscaler", "robustscaler"}
FEATURE_SELECTION_NAMES = {
    "selectkbest", "selectfrommodel", "rfe", "variancethreshold"
}
COMPOSITION_NAMES = {
    "Pipeline", "make_pipeline", "make_union", "ColumnTransformer"
}
FINDING_STATUSES = {"red", "amber", "green", "grey"}


def _operation_type(operation: dict[str, Any]) -> str:
    kind = operation.get("kind")
    name = str(operation.get("name", ""))
    lower_name = name.lower()
    lower_source = str(operation.get("source", "")).lower()

    if kind == "data_source":
        return "dataset_loading"
    if kind == "split":
        return "train_test_split"
    if kind == "training":
        return "model_training"
    if kind == "prediction":
        return "prediction"
    if kind == "evaluation":
        return "model_evaluation"
    if kind == "cleaning":
        return "data_cleaning"
    if kind == "missing_value_handling":
        return "missing_value_handling"
    if kind == "feature_engineering":
        return "feature_engineering"
    if kind == "model":
        return "model_initialization"
    if kind == "preprocessing":
        if lower_name in MISSING_VALUE_NAMES or "imputer" in lower_source:
            return "missing_value_handling"
        if lower_name in ENCODING_NAMES or "encoder" in lower_source:
            return "data_encoding"
        if lower_name in SCALING_NAMES or "scaler" in lower_source:
            return "data_scaling"
        if lower_name in FEATURE_SELECTION_NAMES or "select" in lower_source:
            return "feature_selection"
        if name in COMPOSITION_NAMES:
            return "preprocessing"
        return "preprocessing"
    return "unknown"


def _edge_id(source: str, target: str, relation: str, variables: list[str]) -> str:
    identity = "\0".join((source, target, relation, *variables))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"edge-{digest}"


def _finding_status(finding: dict[str, Any]) -> str:
    if finding.get("status") == "confirmed" or finding.get("evidence_status") == "confirmed":
        return "red"
    return "amber"


def build_pipeline_trace(
    analysis: dict[str, Any], cells: list[dict[str, Any]]
) -> dict[str, Any]:
    """Create stable graph nodes and only source-supported dependency edges."""
    operations = analysis.get("all_operations")
    if not isinstance(operations, list):
        operations = []
    findings = analysis.get("findings")
    if not isinstance(findings, list):
        findings = []

    cell_by_index = {
        cell["index"]: cell for cell in cells if isinstance(cell.get("index"), int)
    }
    findings_by_reference: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        finding_status = _finding_status(finding)
        for reference in finding.get("source_refs", []):
            if not isinstance(reference, dict):
                continue
            cell_index = reference.get("cell_index")
            line = reference.get("line")
            if isinstance(cell_index, int) and isinstance(line, int):
                findings_by_reference.setdefault((cell_index, line), []).append(
                    {**finding, "_graph_status": finding_status}
                )

    nodes: list[dict[str, Any]] = []
    operation_by_id: dict[str, dict[str, Any]] = {}
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        operation_id = operation.get("id")
        if not isinstance(operation_id, str) or not operation_id:
            continue
        source_ref = operation.get("source_ref")
        if not isinstance(source_ref, dict):
            source_ref = {
                "cell_index": operation.get("cell_index"),
                "line": operation.get("line"),
            }
        cell_index = source_ref.get("cell_index")
        line = source_ref.get("line")
        location_findings = (
            findings_by_reference.get((cell_index, line), [])
            if isinstance(cell_index, int) and isinstance(line, int)
            else []
        )
        evidence = operation.get("evidence", "static_ast")
        status = (
            "grey"
            if evidence != "static_ast"
            else next(
                (
                    finding["_graph_status"]
                    for finding in location_findings
                    if finding["_graph_status"] == "red"
                ),
                "amber" if location_findings else "green",
            )
        )
        cell = cell_by_index.get(cell_index)
        operation_type = _operation_type(operation)
        node = {
            "id": operation_id,
            "operation_type": operation_type,
            "display_label": OPERATION_LABELS[operation_type],
            "operation_name": operation.get("name", OPERATION_LABELS[operation_type]),
            "cell_index": cell_index,
            "line": line,
            "source_ref": source_ref,
            "source": operation.get("source", ""),
            "input_variables": operation.get("inputs", []),
            "output_variables": operation.get("outputs", []),
            "execution_count": cell.get("execution_count") if cell else None,
            "finding_ids": sorted(
                {
                    finding["id"]
                    for finding in location_findings
                    if isinstance(finding.get("id"), str)
                }
            ),
            "status": status,
            "evidence_status": evidence,
        }
        nodes.append(node)
        operation_by_id[operation_id] = operation

    nodes_by_id = {node["id"]: node for node in nodes}
    edges_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    latest_producer: dict[str, str] = {}
    unresolved_references: list[dict[str, Any]] = []
    imported_names = {
        imported["name"]
        for imported in analysis.get("imports", [])
        if isinstance(imported, dict) and isinstance(imported.get("name"), str)
    }

    for node in nodes:
        operation = operation_by_id[node["id"]]
        for variable in node["input_variables"]:
            producer_id = latest_producer.get(variable)
            if producer_id and producer_id != node["id"]:
                key = (producer_id, node["id"], "direct_variable_reference")
                edge = edges_by_key.get(key)
                if edge is None:
                    edge = {
                        "source": producer_id,
                        "target": node["id"],
                        "relationship": "direct_variable_reference",
                        "variables": [],
                        "dependency_confidence": "explicit_source_reference",
                        "evidence_status": "static_ast",
                        "explanation": (
                            f"The source references variable '{variable}', which an earlier "
                            "recognized operation assigns. This is static source evidence, "
                            "not a confirmed runtime transfer."
                        ),
                        "source_refs": [node["source_ref"]],
                    }
                    edges_by_key[key] = edge
                if variable not in edge["variables"]:
                    edge["variables"].append(variable)
            elif not producer_id and variable not in imported_names:
                unresolved_references.append(
                    {
                        "node_id": node["id"],
                        "variable": variable,
                        "reason": (
                            "No earlier recognized operation assigns this input variable; "
                            "no dependency edge was inferred."
                        ),
                        "source_ref": node["source_ref"],
                    }
                )

        parent_id = operation.get("composition_parent_id")
        if isinstance(parent_id, str) and parent_id in nodes_by_id:
            key = (node["id"], parent_id, "explicit_pipeline_composition")
            if key not in edges_by_key:
                edges_by_key[key] = {
                    "source": node["id"],
                    "target": parent_id,
                    "relationship": "explicit_pipeline_composition",
                    "variables": [],
                    "dependency_confidence": "explicit_ast_composition",
                    "evidence_status": "static_ast",
                    "explanation": (
                        "The operation is syntactically nested inside a recognized "
                        "scikit-learn pipeline or transformer composition."
                    ),
                    "source_refs": [
                        node["source_ref"],
                        nodes_by_id[parent_id]["source_ref"],
                    ],
                }

        for variable in node["output_variables"]:
            latest_producer[variable] = node["id"]

    edges = []
    for (source, target, relationship), edge in edges_by_key.items():
        edge["id"] = _edge_id(source, target, relationship, sorted(edge["variables"]))
        edges.append(edge)

    nodes_with_unresolved_inputs = {
        reference["node_id"] for reference in unresolved_references
    }
    for node in nodes:
        if node["id"] in nodes_with_unresolved_inputs and node["status"] == "green":
            node["status"] = "grey"

    findings_output = [
        {
            "id": finding["id"],
            "title": finding.get("title", finding["id"]),
            "status": _finding_status(finding),
            "source_refs": finding.get("source_refs", []),
        }
        for finding in findings
        if isinstance(finding, dict) and isinstance(finding.get("id"), str)
    ]
    return {
        "metadata": {
            "trace_type": "static_source_dependency_graph",
            "node_count": len(nodes),
            "edge_count": len(edges),
            "runtime_verified": False,
            "limitations": [
                "Edges represent explicit source references or explicit estimator composition, not observed runtime data transfer.",
                "Notebook source order and saved execution counts do not establish execution order.",
                "Aliases, control flow, repeated execution, and dynamic data flow are not resolved.",
            ],
        },
        "nodes": nodes,
        "edges": edges,
        "findings": findings_output,
        "unresolved_references": unresolved_references,
    }
