from backend.app.services.benchmark_evaluator import (
    evaluate_benchmark,
    render_report,
)


def test_synthetic_benchmark_reports_metrics_and_fixture_cases():
    result = evaluate_benchmark()

    assert result["synthetic_only"] is True
    assert result["fixture_count"] == 8
    assert result["metrics"]["enhanced_analyzer"]["recall"] >= result["metrics"][
        "rule_based_baseline"
    ]["recall"]
    assert result["repairs_and_verification"]["repair_attempts"] > 0
    assert result["repairs_and_verification"]["verification_cases"] > 0
    assert (
        result["repairs_and_verification"]["verification_accuracy"] == 1.0
    )


def test_benchmark_report_discloses_limits_of_verification_metric():
    report = render_report(evaluate_benchmark())

    assert "synthetic" in report
    assert "not overall verification accuracy" in report
    assert "do not execute notebooks" in report
