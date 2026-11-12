"""Objective-aware, source-only temporal leakage checks."""

import ast
import re
from typing import Any


_TEMPORAL_OBJECTIVES = {
    "forecasting",
    "time_series_forecasting",
    "temporal_prediction",
    "future_prediction",
    "predicting_future_events",
}
_OBJECTIVE_CUES = re.compile(
    r"\b(forecast(?:ing)?|time[\s_-]?series|predict(?:ing)?\s+(?:the\s+)?future|"
    r"future\s+(?:event|value|observation)|next\s+(?:day|week|month|period))\b",
    re.IGNORECASE,
)
_TIME_CUES = re.compile(
    r"\b(date|datetime|timestamp|time_index|time_series|lag|rolling|resample)\b",
    re.IGNORECASE,
)
_DATE_SORT_CUES = re.compile(r"(date|time|timestamp|period)", re.IGNORECASE)


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return ""


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((item.value for item in call.keywords if item.arg == name), None)


def _literal_bool(node: ast.expr | None) -> bool | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, bool) else None


def _finding(
    rule_id: str,
    title: str,
    description: str,
    severity: str,
    confidence: str,
    explanation: str,
    recommendation: str,
    cell_index: int,
    line: int,
    snippet: str,
    *,
    impact: str,
    additional_information: str,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    confidence_score = {"high": 0.9, "medium": 0.7, "low": 0.4}[confidence]
    return {
        "id": rule_id,
        "rule_id": rule_id,
        "category": "temporal_leakage",
        "issue_category": "temporal_leakage",
        "title": title,
        "description": description,
        "severity": severity,
        "confidence": confidence,
        "confidence_score": confidence_score,
        "classification": "potential_risk",
        "status": "potential",
        "explanation": explanation,
        "risk_explanation": explanation,
        "potential_impact": impact,
        "recommendation": recommendation,
        "suggested_correction": recommendation,
        "human_confirmation_required": True,
        "additional_information_needed": additional_information,
        "source_line_numbers": [line],
        "notebook_cell_indices": [cell_index],
        "source_refs": [{"cell_index": cell_index, "line": line}],
        "cell_indices": [cell_index],
        "related_variables": [],
        "evidence": [{"cell_index": cell_index, "line": line, "snippet": snippet}],
        "source_code_evidence": [{"cell_index": cell_index, "line": line, "snippet": snippet}],
        "evidence_type": "static_code_pattern",
        "limitations": limitations or [
            "Static analysis cannot determine timestamp values, runtime row order, or the intended forecasting protocol."
        ],
    }


def analyze_temporal(
    cells: list[dict[str, Any]], research_objective: str | None = None
) -> dict[str, Any]:
    """Report temporal risks only when objective or source context warrants review."""
    objective = (research_objective or "").strip().casefold().replace("-", "_").replace(" ", "_")
    markdown = "\n".join(
        str(cell.get("source", ""))
        for cell in cells
        if cell.get("cell_type") == "markdown"
    )
    objective_confirmed = objective in _TEMPORAL_OBJECTIVES or bool(_OBJECTIVE_CUES.search(markdown))

    calls: list[dict[str, Any]] = []
    time_context = objective_confirmed
    for cell in cells:
        if cell.get("cell_type") != "code":
            continue
        source = str(cell.get("source", ""))
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for call in (
            node for node in ast.walk(tree) if isinstance(node, ast.Call)
        ):
            name = _call_name(call)
            line = getattr(call, "lineno", 1)
            snippet = ast.get_source_segment(source, call) or source.splitlines()[line - 1].strip()
            calls.append(
                {
                    "name": name,
                    "cell_index": cell["index"],
                    "line": line,
                    "snippet": snippet,
                    "call": call,
                    "source": source,
                }
            )
            if name in {"shift", "rolling", "resample"} or (
                name == "sort_values" and _DATE_SORT_CUES.search(snippet)
            ):
                time_context = True

    splits = [item for item in calls if item["name"] == "train_test_split"]
    findings: list[dict[str, Any]] = []
    ordered_calls = sorted(calls, key=lambda item: (item["cell_index"], item["line"]))
    for split in splits:
        call = split["call"]
        shuffle = _literal_bool(_keyword(call, "shuffle"))
        random_split = shuffle is not False
        if not objective_confirmed and not time_context:
            continue
        confidence = "medium" if objective_confirmed else "low"
        if random_split:
            findings.append(
                _finding(
                    "random_split_for_forecasting",
                    "Random split may violate temporal evaluation",
                    "A randomized train/test split appears in a time-dependent workflow.",
                    "high" if objective_confirmed else "medium",
                    confidence,
                    (
                        "The research objective or notebook context indicates temporal prediction, "
                        "while train_test_split shuffles rows by default."
                        if objective_confirmed
                        else "Temporal feature engineering or ordering cues occur near a randomized split, but the research objective is not explicit."
                    ),
                    "For forecasting, order observations by the confirmed time column and use a chronological holdout or TimeSeriesSplit.",
                    split["cell_index"],
                    split["line"],
                    split["snippet"],
                    impact="Future observations may influence training while earlier observations are held out, overstating future performance.",
                    additional_information=(
                        "Confirm the prediction horizon, timestamp column, and whether the intended evaluation is on future observations."
                    ),
                )
            )
        earlier_sort = any(
            item["name"] in {"sort_values", "sort_index"}
            and (item["cell_index"], item["line"])
            < (split["cell_index"], split["line"])
            and (
                item["name"] == "sort_index"
                or _DATE_SORT_CUES.search(item["snippet"])
            )
            for item in ordered_calls
        )
        if random_split and not earlier_sort:
            findings.append(
                _finding(
                    "temporal_ordering_missing_before_split",
                    "Chronological ordering is not evident before the split",
                    "No source-visible chronological sort precedes the randomized split.",
                    "medium",
                    confidence,
                    "A time-dependent objective should preserve temporal order before a chronological holdout.",
                    "Sort by the confirmed timestamp and split by time; do not choose a date field automatically.",
                    split["cell_index"],
                    split["line"],
                    split["snippet"],
                    impact="The evaluation partitions may not represent the intended past-to-future prediction task.",
                    additional_information="Identify the authoritative time column and confirm the intended holdout boundary.",
                )
            )

    for item in calls:
        call = item["call"]
        if item["name"] == "shift" and call.args:
            amount = call.args[0]
            if isinstance(amount, ast.UnaryOp) and isinstance(amount.op, ast.USub):
                findings.append(
                    _finding(
                        "future_shift_feature",
                        "Feature shift appears to reference future rows",
                        "A negative pandas shift is a forward-looking row reference.",
                        "high" if objective_confirmed else "medium",
                        "medium" if objective_confirmed else "low",
                        "A negative shift can make a feature depend on observations after the current timestamp.",
                        "Confirm the feature's alignment and prediction horizon; use past-only lags and construct targets separately.",
                        item["cell_index"],
                        item["line"],
                        item["snippet"],
                        impact="Future information may enter model features and produce optimistic evaluation.",
                        additional_information="Confirm whether the shifted values are intended as labels or predictors.",
                    )
                )
        elif item["name"] == "rolling":
            center = _literal_bool(_keyword(call, "center"))
            if center is True:
                findings.append(
                    _finding(
                        "centered_rolling_feature",
                        "Centered rolling window may use future observations",
                        "A centered rolling window includes observations on both sides of the current row.",
                        "high" if objective_confirmed else "medium",
                        "medium" if objective_confirmed else "low",
                        "Centered windows can include values later than the prediction timestamp.",
                        "Use a trailing window and verify that feature construction only uses information available at prediction time.",
                        item["cell_index"],
                        item["line"],
                        item["snippet"],
                        impact="Future observations may leak into training features.",
                        additional_information="Confirm feature availability at the forecast origin.",
                    )
                )
            elif any(
                (split["cell_index"], split["line"])
                > (item["cell_index"], item["line"])
                for split in splits
            ) and (objective_confirmed or time_context):
                findings.append(
                    _finding(
                        "rolling_window_before_partition",
                        "Rolling feature is constructed before partitioning",
                        "A rolling transformation appears before a later split in a temporal workflow.",
                        "medium",
                        "low" if not objective_confirmed else "medium",
                        "The source order may allow rolling windows to span the eventual split boundary; runtime observations are not available.",
                        "Review window alignment at the split boundary and construct features using only information available at each prediction time.",
                        item["cell_index"],
                        item["line"],
                        item["snippet"],
                        impact="Features near the partition boundary may incorporate observations unavailable at the prediction time.",
                        additional_information="Confirm whether test-period features may use prior training-period history and whether any window is centered.",
                    )
                )

    if objective_confirmed:
        temporal_cv = [
            item for item in calls
            if item["name"] in {"KFold", "GroupKFold"}
            or (
                item["name"] in {"cross_val_score", "cross_validate", "GridSearchCV", "RandomizedSearchCV"}
                and "KFold" in item["snippet"]
            )
        ]
        for item in temporal_cv:
            findings.append(
                _finding(
                    "non_temporal_cross_validation",
                    "Cross-validation may not preserve temporal order",
                    "KFold-style validation is used in a time-dependent prediction task.",
                    "medium",
                    "medium",
                    "KFold and group-based folds do not inherently train only on earlier observations than the validation fold.",
                    "Use TimeSeriesSplit or a task-appropriate rolling-origin evaluation.",
                    item["cell_index"],
                    item["line"],
                    item["snippet"],
                    impact="Validation results may not estimate performance on future observations.",
                    additional_information="Confirm whether the prediction setting permits training on observations later than a validation fold.",
                )
            )

    unique_findings = []
    seen = set()
    for finding in findings:
        reference = finding["source_refs"][0]
        key = (finding["rule_id"], reference["cell_index"], reference["line"])
        if key not in seen:
            unique_findings.append(finding)
            seen.add(key)
    return {
        "objective": research_objective or ("temporal_prediction" if objective_confirmed else "unspecified"),
        "objective_status": "confirmed" if objective_confirmed else "unclear",
        "findings": unique_findings,
        "limitations": [
            "Temporal direction cannot be established without inspecting timestamp values and execution-time row order.",
            "Notebook source cannot prove which observations fell into each partition.",
            "A TimeSeriesSplit or chronological split is a recommendation, not an automatically generated repair.",
        ],
    }
