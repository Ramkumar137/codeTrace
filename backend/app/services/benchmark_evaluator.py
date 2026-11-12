"""Synthetic benchmark runner for CodeTrace's source-only audit rules."""

import argparse
import json
from pathlib import Path
from typing import Any

from backend.app.services.audit_analyzer import analyze_findings
from backend.app.services.dataset_overlap import analyze_train_test_overlap
from backend.app.services.detection_engine import detect_findings
from backend.app.services.notebook_parser import parse_notebook
from backend.app.services.repair_engine import (
    AUTOMATICALLY_REPAIRABLE,
    RepairError,
    generate_corrected_notebook,
)
from backend.app.services.verification_engine import build_verification


FIXTURE_DIRECTORY = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "leakage_notebooks"
)


def _rule_ids(findings: list[dict[str, Any]]) -> set[str]:
    return {
        str(finding.get("rule_id", finding.get("id")))
        for finding in findings
        if finding.get("rule_id", finding.get("id"))
    }


def _metrics(
    cases: list[dict[str, Any]], expected_key: str, actual_key: str
) -> dict[str, Any]:
    labels = sorted(
        {
            rule
            for case in cases
            for rule in case[expected_key] | case[actual_key]
        }
    )
    true_positive = false_positive = false_negative = true_negative = 0
    for case in cases:
        expected = case[expected_key]
        actual = case[actual_key]
        for rule in labels:
            is_expected = rule in expected
            is_detected = rule in actual
            if is_expected and is_detected:
                true_positive += 1
            elif is_detected:
                false_positive += 1
            elif is_expected:
                false_negative += 1
            else:
                true_negative += 1

    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 0.0
    )
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "true_negative": true_negative,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_positive_rate": round(
            false_positive / (false_positive + true_negative)
            if false_positive + true_negative
            else 0.0,
            4,
        ),
        "false_negative_rate": round(
            false_negative / (false_negative + true_positive)
            if false_negative + true_positive
            else 0.0,
            4,
        ),
        "label_count": len(labels),
        "fixture_count": len(cases),
    }


def _legacy_baseline(analysis: dict[str, Any], cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    operations = analysis["all_operations"]
    return detect_findings(
        operations,
        cells,
        analysis["pipeline_graph"],
        analyze_findings(operations),
        analysis["selection_uses"],
    )


def _group_findings(
    directory: Path, case: dict[str, Any]
) -> list[dict[str, Any]]:
    if "train_csv" not in case:
        return []
    comparison = analyze_train_test_overlap(
        case["train_csv"],
        (directory / case["train_csv"]).read_bytes(),
        case["test_csv"],
        (directory / case["test_csv"]).read_bytes(),
        group_column=case["group_column"],
        evaluation_objective=case["evaluation_objective"],
    )
    return comparison["findings"]


def _evaluate_fixture(directory: Path, case: dict[str, Any]) -> dict[str, Any]:
    content = (directory / case["notebook"]).read_bytes()
    parsed = parse_notebook(
        case["notebook"], content, case.get("research_objective")
    )
    analysis = parsed["analysis"]
    groups = _group_findings(directory, case)
    baseline = _legacy_baseline(analysis, parsed["cells"])
    baseline.extend(groups)
    enhanced = [*analysis["findings"], *groups]
    return {
        "name": case["name"],
        "source_path": directory / case["notebook"],
        "research_objective": case.get("research_objective"),
        "expected": set(case["expected_findings"]),
        "baseline": _rule_ids(baseline),
        "enhanced": _rule_ids(enhanced),
        "content": content,
        "parsed": parsed,
        "groups": groups,
    }


def _evaluate_repairs(cases: list[dict[str, Any]]) -> dict[str, Any]:
    attempts = 0
    successes = 0
    failures: list[dict[str, str]] = []
    verification_attempts = 0
    verification_correct = 0

    for case in cases:
        parsed = case["parsed"]
        original_content = case["source_path"].read_bytes()
        original_notebook = dict(parsed)
        original_notebook["notebook_id"] = f"benchmark-original-{case['name']}"
        for repair in parsed["analysis"].get("repairs", []):
            if repair.get("repair_status") != AUTOMATICALLY_REPAIRABLE:
                continue
            attempts += 1
            finding = next(
                (
                    item
                    for item in parsed["analysis"]["findings"]
                    if item.get("id") == repair.get("finding_id")
                ),
                None,
            )
            if finding is None:
                failures.append(
                    {
                        "fixture": case["name"],
                        "repair_id": repair["repair_id"],
                        "reason": "The catalog repair has no matching finding.",
                    }
                )
                continue
            try:
                corrected_content, corrected_filename = generate_corrected_notebook(
                    case["content"],
                    parsed["filename"],
                    [repair["repair_id"]],
                    case["research_objective"],
                )
            except RepairError as error:
                failures.append(
                    {
                        "fixture": case["name"],
                        "repair_id": repair["repair_id"],
                        "reason": error.message,
                    }
                )
                continue

            corrected = parse_notebook(
                corrected_filename,
                corrected_content,
                case["research_objective"],
            )
            corrected["notebook_id"] = f"benchmark-corrected-{case['name']}"
            original_unchanged = case["source_path"].read_bytes() == original_content
            resolved = finding["rule_id"] not in _rule_ids(
                corrected["analysis"]["findings"]
            )
            if resolved and original_unchanged:
                successes += 1
            else:
                failures.append(
                    {
                        "fixture": case["name"],
                        "repair_id": repair["repair_id"],
                        "reason": (
                            "The original finding remained after the generated "
                            "repair or source immutability was not maintained."
                        ),
                    }
                )

            verification_attempts += 1
            unavailable_execution = {
                "execution_id": f"benchmark-unavailable-{case['name']}",
                "status": "unavailable",
                "notebook_id": original_notebook["notebook_id"],
                "notebook_type": "original",
            }
            corrected_unavailable_execution = {
                **unavailable_execution,
                "execution_id": f"benchmark-corrected-unavailable-{case['name']}",
                "notebook_id": corrected["notebook_id"],
                "notebook_type": "corrected",
            }
            verification = build_verification(
                original_notebook=original_notebook,
                corrected_notebook=corrected,
                approved_repairs=[
                    {"repair": repair, "finding": finding}
                ],
                original_execution=unavailable_execution,
                corrected_execution=corrected_unavailable_execution,
            )
            statuses = {
                result["verification_status"]
                for result in verification["findings"]
            }
            if statuses == {"inconclusive"}:
                verification_correct += 1

    return {
        "repair_attempts": attempts,
        "repair_successes": successes,
        "repair_success_rate": round(successes / attempts, 4) if attempts else 0.0,
        "repair_failures": failures,
        "verification_cases": verification_attempts,
        "verification_expected_status": "inconclusive_without_execution",
        "verification_accuracy": (
            round(verification_correct / verification_attempts, 4)
            if verification_attempts
            else 0.0
        ),
        "verification_correct": verification_correct,
        "verification_note": (
            "This is only the guardrail check that unavailable runtime evidence "
            "does not produce a verified result; it is not overall verification accuracy."
        ),
    }


def evaluate_benchmark(fixture_directory: Path = FIXTURE_DIRECTORY) -> dict[str, Any]:
    manifest = json.loads((fixture_directory / "manifest.json").read_text(encoding="utf-8"))
    evaluated = [
        _evaluate_fixture(fixture_directory, case)
        for case in manifest["cases"]
    ]
    metric_cases = [
        {
            "name": case["name"],
            "expected": case["expected"],
            "baseline": case["baseline"],
            "enhanced": case["enhanced"],
        }
        for case in evaluated
    ]
    return {
        "benchmark": "CodeTrace synthetic leakage fixtures",
        "synthetic_only": True,
        "fixture_count": len(evaluated),
        "metrics": {
            "rule_based_baseline": _metrics(
                metric_cases, "expected", "baseline"
            ),
            "enhanced_analyzer": _metrics(
                metric_cases, "expected", "enhanced"
            ),
        },
        "repairs_and_verification": _evaluate_repairs(evaluated),
        "fixtures": [
            {
                "name": case["name"],
                "expected_findings": sorted(case["expected"]),
                "baseline_findings": sorted(case["baseline"]),
                "enhanced_findings": sorted(case["enhanced"]),
            }
            for case in evaluated
        ],
        "methodology": [
            "Each expected finding label is one binary classification per fixture; all other observed labels are negatives.",
            "The baseline runs the existing rule-based detector and configured dataset-overlap check.",
            "The enhanced analyzer adds cross-cell lineage and objective-aware temporal findings.",
            "Repair success means the generated source repair removed the targeted static rule; no notebook code is executed.",
            "Verification accuracy only measures the expected inconclusive status when execution is unavailable.",
        ],
    }


def render_report(result: dict[str, Any]) -> str:
    metrics = result["metrics"]
    repairs = result["repairs_and_verification"]
    lines = [
        "# CodeTrace Synthetic Leakage Benchmark",
        "",
        f"Fixtures: {result['fixture_count']} (synthetic only)",
        "",
        "| Analyzer | Precision | Recall | F1 | False-positive rate | False-negative rate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, key in (
        ("Rule-based baseline", "rule_based_baseline"),
        ("Enhanced analyzer", "enhanced_analyzer"),
    ):
        item = metrics[key]
        lines.append(
            f"| {label} | {item['precision']:.4f} | {item['recall']:.4f} "
            f"| {item['f1']:.4f} | {item['false_positive_rate']:.4f} "
            f"| {item['false_negative_rate']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## Repair and verification",
            "",
            f"- Automatic repair success: {repairs['repair_successes']}/"
            f"{repairs['repair_attempts']} ({repairs['repair_success_rate']:.4f}).",
            f"- No-execution verification guardrail: {repairs['verification_correct']}/"
            f"{repairs['verification_cases']} ({repairs['verification_accuracy']:.4f}) "
            "returned the expected inconclusive status.",
            f"- {repairs['verification_note']}",
            "",
            "## Fixture findings",
            "",
            "| Fixture | Expected | Baseline | Enhanced |",
            "|---|---|---|---|",
        ]
    )
    for fixture in result["fixtures"]:
        lines.append(
            f"| {fixture['name']} | {', '.join(fixture['expected_findings']) or 'none'} "
            f"| {', '.join(fixture['baseline_findings']) or 'none'} "
            f"| {', '.join(fixture['enhanced_findings']) or 'none'} |"
        )
    lines.extend(
        [
            "",
            "All fixtures are hand-authored synthetic examples. These metrics measure "
            "rule behavior on this small fixture set, not real-world prevalence or "
            "generalization. Repair checks are source-only and do not execute notebooks.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmark-results"),
        help="Directory for benchmark_results.json and benchmark_report.md.",
    )
    arguments = parser.parse_args()
    result = evaluate_benchmark()
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    (arguments.output_dir / "benchmark_results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (arguments.output_dir / "benchmark_report.md").write_text(
        render_report(result), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
