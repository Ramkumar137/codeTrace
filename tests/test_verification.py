"""Controlled fixtures for Phase 6 verification and comparison behavior."""

import nbformat
import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.main import app
from backend.app.services.execution_store import ExecutionStore
from backend.app.services.notebook_parser import parse_notebook
from backend.app.services.repair_engine import generate_corrected_notebook
from backend.app.services.verification_engine import (
    _category_verdict,
    build_verification,
    compare_experiments,
    extract_metrics,
)


client = TestClient(app)
DATASET_REFERENCE = [{"dataset_id": "fixture-dataset", "filename": "data.csv"}]


def _notebook_bytes(*sources):
    return nbformat.writes(
        nbformat.v4.new_notebook(
            cells=[nbformat.v4.new_code_cell(source) for source in sources]
        )
    ).encode("utf-8")


def _preprocessing_fixture():
    original_content = _notebook_bytes(
        "from sklearn.preprocessing import StandardScaler",
        "scaler = StandardScaler()\nX_scaled = scaler.fit_transform(X)",
        "X_train, X_test, y_train, y_test = train_test_split(X_scaled, y, random_state=42)",
        "from sklearn.linear_model import LogisticRegression\nmodel = LogisticRegression(random_state=7)\nmodel.fit(X_train, y_train)",
    )
    original_analysis = parse_notebook("original.ipynb", original_content)
    repair = next(
        item
        for item in original_analysis["analysis"]["repairs"]
        if item.get("repair_type") == "preprocessing_fit_before_split"
    )
    corrected_content, _ = generate_corrected_notebook(
        original_content, "original.ipynb", [repair["repair_id"]]
    )
    finding = next(
        item
        for item in original_analysis["analysis"]["findings"]
        if item["id"] == repair["finding_id"]
    )
    return (
        original_analysis,
        parse_notebook("corrected.ipynb", corrected_content),
        [{"repair": repair, "finding": finding}],
    )


def _execution(
    execution_id,
    notebook_id,
    notebook_type,
    *,
    status="completed",
    output="accuracy: 0.80",
    datasets=None,
):
    return {
        "execution_id": execution_id,
        "notebook_id": notebook_id,
        "notebook_type": notebook_type,
        "status": status,
        "duration_seconds": 1.25,
        "executed_cell_count": 4,
        "successful_cell_count": 4 if status == "completed" else 0,
        "failed_cell_number": None,
        "error_details": None,
        "outputs": (
            [{"cell_number": 4, "outputs": [{"text": output}]}] if output else []
        ),
        "dataset_references": DATASET_REFERENCE if datasets is None else datasets,
        "environment": {"image": "fixture-runner"},
        "python_version": "3.12.8",
        "package_versions": {
            "scikit-learn": "1.5.2",
            "numpy": "2.1.0",
            "pandas": "2.2.3",
        },
    }


def _build_pair(
    original_analysis,
    corrected_analysis,
    approved_repairs,
    *,
    corrected_status="completed",
    original_status="completed",
    corrected_output="accuracy: 0.82",
):
    original = {**original_analysis, "notebook_id": "original-id"}
    corrected = {**corrected_analysis, "notebook_id": "corrected-id"}
    result = build_verification(
        original_notebook=original,
        corrected_notebook=corrected,
        approved_repairs=approved_repairs,
        original_execution=_execution(
            "original-run", "original-id", "original",
            status=original_status,
        ),
        corrected_execution=_execution(
            "corrected-run", "corrected-id", "corrected",
            status=corrected_status,
            output=corrected_output,
        ),
    )
    return result


def test_preprocessing_repair_is_verified_and_metrics_remain_separate():
    original, corrected, repairs = _preprocessing_fixture()

    result = _build_pair(original, corrected, repairs)

    finding = result["findings"][0]
    assert finding["verification_status"] == "verified"
    assert finding["verification_status_normalized"] == "verified"
    assert finding["repair_id"] == repairs[0]["repair"]["repair_id"]
    assert finding["execution_ids"] == {
        "original": "original-run",
        "corrected": "corrected-run",
    }
    assert any(item["type"] == "execution_record" for item in finding["evidence"])
    assert result["comparison"]["comparable"] is True
    metric = result["comparison"]["metric_comparisons"][0]
    assert metric["name"] == "accuracy"
    assert metric["deltas"] == pytest.approx([0.02])
    assert metric["difference_percentage_points"] == pytest.approx([2.0])
    assert result["comparison"]["documented_changes"]
    assert result["comparison"]["original_metrics"][0][
        "evaluation_dataset_references"
    ] == DATASET_REFERENCE
    assert finding["verification_status"] == "verified"


def test_preprocessing_repair_that_leaves_full_dataset_fit_is_not_verified():
    original, corrected, repairs = _preprocessing_fixture()
    corrected["cells"][1]["source"] = (
        "scaler = StandardScaler()\nX_scaled = scaler.fit_transform(X)"
    )
    repairs[0]["repair"]["cell_changes"][0]["corrected_code"] = (
        corrected["cells"][1]["source"]
    )
    repairs[0]["repair"]["cell_changes"][1]["corrected_code"] = (
        corrected["cells"][2]["source"]
    )
    corrected = parse_notebook(
        "incorrect-correction.ipynb",
        _notebook_bytes(*(cell["source"] for cell in corrected["cells"])),
    )

    result = _build_pair(original, corrected, repairs)

    assert result["findings"][0]["verification_status"] == "not_verified"
    assert result["findings"][0]["verification_status_normalized"] == "failed"
    assert "remains" in " ".join(result["findings"][0]["remaining_risks"])


def test_partially_corrected_preprocessing_is_reported_as_partial():
    original, _, repairs = _preprocessing_fixture()
    corrected_sources = [
        "from sklearn.preprocessing import StandardScaler",
        "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
        "scaler = StandardScaler()\nX_train = scaler.fit_transform(X_train)",
    ]
    corrected = parse_notebook(
        "partial.ipynb", _notebook_bytes(*corrected_sources)
    )
    repairs[0]["repair"]["affected_cells"] = [1, 2]
    repairs[0]["repair"]["cell_changes"] = [
        {
            "cell_index": 1,
            "original_code": original["cells"][1]["source"],
            "corrected_code": corrected_sources[1],
        },
        {
            "cell_index": 2,
            "original_code": original["cells"][2]["source"],
            "corrected_code": corrected_sources[2],
        },
    ]

    result = _build_pair(original, corrected, repairs)

    assert result["findings"][0]["verification_status"] == "partially_verified"
    assert result["findings"][0]["remaining_risks"]


@pytest.mark.parametrize(
    ("original_status", "corrected_status", "expected"),
    [
        ("failed", "completed", "inconclusive"),
        ("completed", "failed", "execution_failed"),
        ("completed", "timed_out", "execution_failed"),
        ("completed", "unavailable", "inconclusive"),
    ],
)
def test_incomplete_execution_evidence_has_explicit_status(
    original_status, corrected_status, expected
):
    original, corrected, repairs = _preprocessing_fixture()

    result = _build_pair(
        original,
        corrected,
        repairs,
        original_status=original_status,
        corrected_status=corrected_status,
    )

    assert result["findings"][0]["verification_status"] == expected
    expected_normalized = (
        "failed" if expected == "execution_failed" else expected
    )
    assert (
        result["findings"][0]["verification_status_normalized"]
        == expected_normalized
    )
    if corrected_status == "unavailable":
        assert any(
            "was unavailable; runtime verification was not performed."
            in item
            for item in result["findings"][0]["limitations"]
        )


@pytest.mark.parametrize(
    ("finding_id", "source", "expected"),
    [
        (
            "train_test_group_overlap",
            "from sklearn.model_selection import GroupShuffleSplit\n"
            "splitter = GroupShuffleSplit(n_splits=1)\n"
            "splitter.split(X, y, groups=entity_id)",
            "partially_verified",
        ),
        (
            "train_test_identifier_overlap",
            "from sklearn.model_selection import GroupShuffleSplit\n"
            "splitter = GroupShuffleSplit(n_splits=1)\n"
            "splitter.split(X, y, groups=customer_id)",
            "partially_verified",
        ),
        (
            "train_test_group_overlap",
            "X_train, X_test = train_test_split(X)",
            "inconclusive",
        ),
        (
            "exact_train_test_row_overlap",
            "train = train.drop_duplicates()",
            "partially_verified",
        ),
        (
            "exact_train_test_row_overlap",
            "X_train, X_test = train_test_split(X)",
            "inconclusive",
        ),
    ],
)
def test_train_test_overlap_verification_requires_specific_evidence(
    finding_id, source, expected
):
    finding = {
        "id": finding_id,
        "rule_id": finding_id,
        "category": "train_test_overlap",
        "title": "Groups overlap",
        "source_refs": [],
    }
    repair = {
        "repair_id": "repair-overlap",
        "repair_type": "manual_review",
        "affected_cells": [0],
        "cell_changes": [],
        "limitations": [],
    }
    cells = [{"index": 0, "cell_type": "code", "source": source}]

    status, evidence, checks, risks, limitations = _category_verdict(
        finding["rule_id"], finding, repair, cells, cells
    )

    assert status == expected
    assert evidence
    assert checks
    assert risks
    assert limitations


def test_target_leakage_repair_checks_feature_column_and_target_reference():
    original_content = _notebook_bytes(
        'y = df["outcome"]\nX = df[["outcome", "age"]]',
        "X_train, X_test, y_train, y_test = train_test_split(X, y)",
    )
    original = parse_notebook("target.ipynb", original_content)
    repair = next(
        item
        for item in original["analysis"]["repairs"]
        if item.get("repair_type") == "target_column_in_features"
    )
    corrected_content, _ = generate_corrected_notebook(
        original_content, "target.ipynb", [repair["repair_id"]]
    )
    corrected = parse_notebook("target-corrected.ipynb", corrected_content)
    finding = next(
        item
        for item in original["analysis"]["findings"]
        if item["id"] == repair["finding_id"]
    )

    result = _build_pair(
        original, corrected, [{"repair": repair, "finding": finding}]
    )

    assert result["findings"][0]["verification_status"] == "verified"
    assert result["findings"][0]["remaining_risks"]


def test_multiple_findings_and_approved_repairs_keep_independent_verdicts():
    original_content = _notebook_bytes(
        "from sklearn.preprocessing import StandardScaler",
        "scaler = StandardScaler()\nX_scaled = scaler.fit_transform(X)",
        "X_train, X_test, y_train, y_test = train_test_split(X_scaled, y, random_state=42)",
        'y = df["outcome"]\nX = df[["outcome", "age"]]',
    )
    original = parse_notebook("multi.ipynb", original_content)
    repairs = [
        item
        for item in original["analysis"]["repairs"]
        if item["repair_status"] == "automatically_repairable"
    ]
    assert len(repairs) == 2
    corrected_content, _ = generate_corrected_notebook(
        original_content, "multi.ipynb", [item["repair_id"] for item in repairs]
    )
    corrected = parse_notebook("multi-corrected.ipynb", corrected_content)
    findings_by_id = {
        item["id"]: item for item in original["analysis"]["findings"]
    }
    manifest = [
        {"repair": repair, "finding": findings_by_id[repair["finding_id"]]}
        for repair in repairs
    ]

    result = _build_pair(original, corrected, manifest)

    assert {item["repair_id"] for item in result["findings"]} == {
        item["repair_id"] for item in repairs
    }
    assert [item["verification_status"] for item in result["findings"]] == [
        "verified",
        "verified",
    ]


def test_test_set_contamination_is_not_overstated_without_validation_evidence():
    finding = {"id": "test_metric_used_for_model_selection"}
    repair = {"affected_cells": [0]}
    cells = [
        {
            "index": 0,
            "cell_type": "code",
            "source": "score = model.score(X_test, y_test)\nif score > best: pass",
        }
    ]

    status, _, checks, risks, _ = _category_verdict(
        finding["id"], finding, repair, cells, cells
    )

    assert status == "inconclusive"
    assert checks[0]["passed"] is False
    assert risks


def test_test_set_contamination_correction_is_only_partially_verified():
    finding = {"id": "test_metric_used_for_model_selection"}
    repair = {"affected_cells": [0]}
    original = [
        {
            "index": 0,
            "cell_type": "code",
            "source": "score = model.score(X_test, y_test)\nif score > best: pass",
        }
    ]
    corrected = [
        {
            "index": 0,
            "cell_type": "code",
            "source": "score = model.score(X_test, y_test)\n"
            "validation_score = model.score(X_valid, y_valid)\n"
            "if validation_score > best: pass",
        }
    ]

    status, _, checks, risks, limitations = _category_verdict(
        finding["id"], finding, repair, original, corrected
    )

    assert status == "partially_verified"
    assert checks[0]["passed"] is True
    assert risks
    assert limitations


def test_equivalent_experiments_compare_only_labeled_metric_values():
    original = _execution(
        "original-run",
        "original-id",
        "original",
        output="accuracy: 0.80\nRMSE = 4.2",
    )
    corrected = _execution(
        "corrected-run",
        "corrected-id",
        "corrected",
        output="accuracy: 0.82\nRMSE = 4.0",
    )
    cells = parse_notebook(
        "metrics.ipynb",
        _notebook_bytes(
            "from sklearn.model_selection import train_test_split",
            "X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)",
            "from sklearn.linear_model import LogisticRegression\nmodel = LogisticRegression(random_state=7)",
        ),
    )["cells"]

    comparison = compare_experiments(original, corrected, cells, cells)

    assert comparison["comparable"] is True
    assert {item["name"] for item in comparison["metric_comparisons"]} == {
        "accuracy",
        "rmse",
    }
    assert next(
        item for item in comparison["metric_comparisons"] if item["name"] == "accuracy"
    )["deltas"] == pytest.approx([0.02])
    assert next(
        item for item in comparison["metric_comparisons"] if item["name"] == "accuracy"
    )["difference_percentage_points"] == pytest.approx([2.0])
    assert extract_metrics(original)[1]["name"] == "rmse"


def test_incomparable_datasets_withhold_metric_deltas():
    original = _execution("original-run", "original-id", "original")
    corrected = _execution(
        "corrected-run",
        "corrected-id",
        "corrected",
        datasets=[{"dataset_id": "other-data", "filename": "other.csv"}],
    )
    cells = parse_notebook(
        "metrics.ipynb",
        _notebook_bytes(
            "from sklearn.model_selection import train_test_split",
            "X_train, X_test, y_train, y_test = train_test_split(X, y, random_state=42)",
            "from sklearn.linear_model import LogisticRegression\nmodel = LogisticRegression(random_state=7)",
        ),
    )["cells"]

    comparison = compare_experiments(original, corrected, cells, cells)

    assert comparison["comparable"] is False
    assert comparison["metric_comparisons"][0]["deltas"] == []
    assert any(
        item["setting"] == "dataset_references"
        for item in comparison["setup_differences"]
    )


def test_missing_metrics_are_not_invented():
    execution = _execution(
        "empty-run",
        "notebook-id",
        "original",
        output="completed without a labeled metric",
    )

    assert extract_metrics(execution) == []


def test_unavailable_experiments_do_not_claim_metrics_from_completed_runs():
    original = _execution(
        "original-run", "original-id", "original", status="unavailable", output=""
    )
    corrected = _execution(
        "corrected-run", "corrected-id", "corrected", status="unavailable", output=""
    )
    cells = parse_notebook(
        "metrics.ipynb", _notebook_bytes("value = 1")
    )["cells"]

    comparison = compare_experiments(original, corrected, cells, cells)

    assert comparison["comparable"] is False
    assert comparison["metric_comparisons"] == []
    assert any(
        "No supported labeled metrics were captured" in reason
        for reason in comparison["comparability_reasons"]
    )


def test_metric_extractor_supports_only_labeled_metric_names():
    execution = _execution(
        "metric-run",
        "notebook-id",
        "original",
        output=(
            "accuracy: 0.9\nprecision_score=0.8\nrecall: 0.7\nF1-score: 0.75\n"
            "ROC-AUC: 0.88\nMAE: 1.2\nMSE: 2.4\nRMSE: 1.55\nR-squared: 0.6\n"
            "unlabeled result 42"
        ),
    )

    metrics = extract_metrics(execution)

    assert {item["name"] for item in metrics} == {
        "accuracy",
        "precision",
        "recall",
        "f1",
        "roc_auc",
        "mae",
        "mse",
        "rmse",
        "r2",
    }


def test_verification_api_checks_notebook_execution_associations_and_persists_audit(
    tmp_path, monkeypatch
):
    store = ExecutionStore(tmp_path)
    original_content = _notebook_bytes(
        "from sklearn.preprocessing import StandardScaler",
        "scaler = StandardScaler()\nX_scaled = scaler.fit_transform(X)",
        "X_train, X_test, y_train, y_test = train_test_split(X_scaled, y, random_state=42)",
        "from sklearn.linear_model import LogisticRegression\nmodel = LogisticRegression(random_state=7)\nmodel.fit(X_train, y_train)",
    )
    original_id, token = store.create_original_notebook(
        "original.ipynb", original_content
    )
    original_record = store.get_notebook(original_id, token)
    original_analysis = parse_notebook("original.ipynb", original_content)
    repair = next(
        item
        for item in original_analysis["analysis"]["repairs"]
        if item.get("repair_type") == "preprocessing_fit_before_split"
    )
    finding = next(
        item
        for item in original_analysis["analysis"]["findings"]
        if item["id"] == repair["finding_id"]
    )
    corrected_content, corrected_filename = generate_corrected_notebook(
        original_content, "original.ipynb", [repair["repair_id"]]
    )
    corrected_id = store.create_corrected_notebook(
        original_record,
        corrected_filename,
        corrected_content,
        [{"repair": repair, "finding": finding}],
    )
    original_execution_id = store.create_execution(
        original_id, DATASET_REFERENCE, {"image": "fixture"}
    )
    corrected_execution_id = store.create_execution(
        corrected_id, DATASET_REFERENCE, {"image": "fixture"}
    )
    store.update_execution(
        original_execution_id,
        status="completed",
        python_version="3.12.8",
        package_versions={},
        outputs=[{"cell_number": 1, "outputs": [{"text": "accuracy: 0.8"}]}],
        executed_cell_count=4,
        successful_cell_count=4,
    )
    store.update_execution(
        corrected_execution_id,
        status="completed",
        python_version="3.12.8",
        package_versions={},
        outputs=[{"cell_number": 1, "outputs": [{"text": "accuracy: 0.82"}]}],
        executed_cell_count=4,
        successful_cell_count=4,
    )
    monkeypatch.setattr(main, "execution_store", store)

    headers = {"Authorization": f"Bearer {token}"}
    response = client.post(
        f"/api/notebooks/{original_id}/verifications",
        headers=headers,
        json={
            "corrected_notebook_id": corrected_id,
            "original_execution_id": original_execution_id,
            "corrected_execution_id": corrected_execution_id,
        },
    )

    assert response.status_code == 200
    report = response.json()
    assert report["findings"][0]["verification_status"] == "verified"
    assert report["findings"][0]["repair_id"] == repair["repair_id"]
    assert store.get_verification(report["verification_id"], token) == report
    assert store.list_verifications(original_id, token) == [report]
    saved_runs = client.get(
        f"/api/notebooks/{original_id}/executions", headers=headers
    ).json()["executions"]
    assert {
        item["execution_id"] for item in saved_runs
    } == {original_execution_id, corrected_execution_id}
    assert client.get(
        f"/api/verifications/{report['verification_id']}/findings/{repair['finding_id']}",
        headers=headers,
    ).json()["verification_status"] == "verified"
    assert client.get(
        f"/api/verifications/{report['verification_id']}/comparison",
        headers=headers,
    ).json() == report["comparison"]

    unauthorized = client.get(
        f"/api/verifications/{report['verification_id']}",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert unauthorized.status_code == 404
    assert store.get_notebook(original_id, token)["content"] == original_content
    assert store.get_execution(original_execution_id, token)["status"] == "completed"


def test_verification_api_rejects_execution_from_wrong_notebook_version(
    tmp_path, monkeypatch
):
    store = ExecutionStore(tmp_path)
    original_content = _notebook_bytes(
        "from sklearn.preprocessing import StandardScaler",
        "scaler = StandardScaler()\nX_scaled = scaler.fit_transform(X)",
        "X_train, X_test, y_train, y_test = train_test_split(X_scaled, y)",
        "model.fit(X_train, y_train)",
    )
    original_id, token = store.create_original_notebook(
        "original.ipynb", original_content
    )
    original_record = store.get_notebook(original_id, token)
    analysis = parse_notebook("original.ipynb", original_content)
    repair = next(
        item
        for item in analysis["analysis"]["repairs"]
        if item.get("repair_type") == "preprocessing_fit_before_split"
    )
    finding = next(
        item for item in analysis["analysis"]["findings"]
        if item["id"] == repair["finding_id"]
    )
    corrected_content, corrected_filename = generate_corrected_notebook(
        original_content, "original.ipynb", [repair["repair_id"]]
    )
    corrected_id = store.create_corrected_notebook(
        original_record,
        corrected_filename,
        corrected_content,
        [{"repair": repair, "finding": finding}],
    )
    wrong_version_execution = store.create_execution(
        original_id, [], {"image": "fixture"}
    )
    corrected_execution = store.create_execution(
        corrected_id, [], {"image": "fixture"}
    )
    store.update_execution(wrong_version_execution, status="completed")
    store.update_execution(corrected_execution, status="completed")
    monkeypatch.setattr(main, "execution_store", store)

    response = client.post(
        f"/api/notebooks/{original_id}/verifications",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "corrected_notebook_id": corrected_id,
            "original_execution_id": corrected_execution,
            "corrected_execution_id": corrected_execution,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "execution_notebook_mismatch"
