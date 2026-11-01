"""Tests for persisted Phase 7 evidence reports and authorized artifact downloads."""

import json

import nbformat
import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.main import app
from backend.app.services.execution_store import ExecutionStore
from backend.app.services.notebook_parser import parse_notebook
from backend.app.services.repair_engine import generate_corrected_notebook
from backend.app.services.report_service import (
    ReportGenerationError,
    build_report_data,
)
from backend.app.services.verification_engine import build_verification


client = TestClient(app)
RUNNER_ENVIRONMENT = {"image": "fixture-runner", "network": "none"}
PACKAGE_VERSIONS = {
    "numpy": "2.1.0",
    "pandas": "2.2.3",
    "scikit-learn": "1.5.2",
}


def _notebook_bytes(*sources, metadata=None):
    notebook = nbformat.v4.new_notebook(
        cells=[nbformat.v4.new_code_cell(source) for source in sources],
        metadata=metadata or {},
    )
    return nbformat.writes(notebook).encode("utf-8")


def _preprocessing_fixture():
    original_content = _notebook_bytes(
        "from sklearn.preprocessing import StandardScaler",
        "scaler = StandardScaler()\nX_scaled = scaler.fit_transform(X)",
        "X_train, X_test, y_train, y_test = train_test_split(X_scaled, y, random_state=42)",
        "from sklearn.linear_model import LogisticRegression\nmodel = LogisticRegression(random_state=7)\nmodel.fit(X_train, y_train)",
        'api_key = "sk-123456789012345678901234"',
        metadata={"custom": {"api_key": "do-not-export"}},
    )
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
    return (
        original_content,
        corrected_content,
        corrected_filename,
        original_analysis,
        parse_notebook(corrected_filename, corrected_content),
        [{"repair": repair, "finding": finding}],
    )


def _stored_run(
    store,
    notebook_id,
    dataset_references,
    *,
    output,
    artifact=None,
    status="completed",
):
    execution_id = store.create_execution(
        notebook_id,
        dataset_references,
        RUNNER_ENVIRONMENT,
    )
    store.update_execution(
        execution_id,
        status=status,
        started_at="2026-11-01T10:00:00+00:00",
        completed_at="2026-11-01T10:00:01+00:00",
        duration_seconds=1.0,
        executed_cell_count=4,
        successful_cell_count=4 if status == "completed" else 0,
        failed_cell_number=None if status == "completed" else 2,
        error_details=None if status == "completed" else {"message": "Runner unavailable."},
        python_version="3.12.8",
        package_versions=PACKAGE_VERSIONS,
        environment=RUNNER_ENVIRONMENT,
        outputs=(
            [{"cell_number": 4, "outputs": [{"text": output}]}]
            if output
            else []
        ),
        logs="",
        artifact=artifact,
    )
    return execution_id


def _create_complete_workflow(store):
    (
        original_content,
        corrected_content,
        corrected_filename,
        original_analysis,
        corrected_analysis,
        approved_repairs,
    ) = _preprocessing_fixture()
    original_id, token = store.create_original_notebook(
        "original.ipynb", original_content
    )
    original_record = store.get_notebook(original_id, token)
    corrected_id = store.create_corrected_notebook(
        original_record,
        corrected_filename,
        corrected_content,
        approved_repairs,
    )
    dataset_content = b"feature,target\n1,0\n2,1\n"
    dataset_id = store.add_dataset(original_id, "data.csv", dataset_content)
    dataset_references = [{"dataset_id": dataset_id, "filename": "data.csv"}]
    original_run_id = _stored_run(
        store,
        original_id,
        dataset_references,
        output="accuracy: 0.80",
        artifact=b"original executed notebook",
    )
    corrected_run_id = _stored_run(
        store,
        corrected_id,
        dataset_references,
        output="accuracy: 0.82",
        artifact=b"corrected executed notebook",
    )
    failed_run_id = _stored_run(
        store,
        corrected_id,
        dataset_references,
        output="",
        status="unavailable",
    )
    verification = build_verification(
        original_notebook={**original_analysis, "notebook_id": original_id},
        corrected_notebook={**corrected_analysis, "notebook_id": corrected_id},
        approved_repairs=approved_repairs,
        original_execution=store.get_execution(original_run_id, token),
        corrected_execution=store.get_execution(corrected_run_id, token),
    )
    store.create_verification(verification)
    return {
        "notebook_id": original_id,
        "corrected_notebook_id": corrected_id,
        "dataset_id": dataset_id,
        "dataset_content": dataset_content,
        "token": token,
        "original_content": original_content,
        "corrected_content": corrected_content,
        "original_run_id": original_run_id,
        "corrected_run_id": corrected_run_id,
        "failed_run_id": failed_run_id,
        "verification": verification,
        "repair_id": approved_repairs[0]["repair"]["repair_id"],
        "finding_id": approved_repairs[0]["finding"]["id"],
    }


def test_partial_report_marks_missing_phases_and_zero_findings(tmp_path, monkeypatch):
    store = ExecutionStore(tmp_path)
    notebook_id, token = store.create_original_notebook(
        "empty-analysis.ipynb",
        nbformat.writes(nbformat.v4.new_notebook()).encode("utf-8"),
    )
    monkeypatch.setattr(main, "execution_store", store)
    monkeypatch.setattr(main, "execution_manager", None)

    unauthorized = client.post(f"/api/notebooks/{notebook_id}/reports")
    response = client.post(
        f"/api/notebooks/{notebook_id}/reports",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "partially_available"
    assert result["overview"]["findings_count"] == 0
    assert result["overview"]["findings_by_severity"] == {}
    assert main.execution_manager is None
    saved = store.get_report(result["report_id"], token)
    assert saved is not None
    assert saved["report_data"]["sections"]["experiment_execution_results"] == {
        "status": "not_performed",
        "data": [],
        "reason": "No persisted experiment executions exist.",
    }
    assert (
        saved["report_data"]["sections"]["repair_verification"]["status"]
        == "not_performed"
    )


def test_report_includes_saved_repair_execution_verification_and_comparison(
    tmp_path,
):
    store = ExecutionStore(tmp_path)
    fixture = _create_complete_workflow(store)

    report = build_report_data(store, fixture["notebook_id"], fixture["token"])

    assert report["status"] == "completed"
    assert report["overview"]["findings_count"] == len(
        report["sections"]["findings"]["data"]
    )
    assert report["overview"]["execution_status_summary"]["unavailable"] == 1
    repair = next(
        item
        for item in report["sections"]["repair_summary"]["data"]
        if item["repair_id"] == fixture["repair_id"]
    )
    assert repair["approval_state"] == "approved_and_applied"
    assert repair["approval_records"][0]["corrected_notebook_id"] == fixture[
        "corrected_notebook_id"
    ]
    finding = next(
        item
        for item in report["sections"]["findings"]["data"]
        if item["id"] == fixture["finding_id"]
    )
    assert finding["evidence_classification"] == "static_analysis_inference"
    assert finding["pipeline_node_ids"]
    assert finding["code_snippets"]
    verifications = report["sections"]["repair_verification"]["data"]
    assert verifications[0]["verification_id"] == fixture["verification"][
        "verification_id"
    ]
    assert verifications[0]["findings"][0]["verification_status"] == "verified"
    comparisons = report["sections"]["experiment_comparison"]["data"]
    accuracy = comparisons[0]["comparison"]["metric_comparisons"][0]
    assert accuracy["name"] == "accuracy"
    assert accuracy["deltas"] == pytest.approx([0.02])
    assert fixture["original_run_id"] in json.dumps(report)
    assert fixture["corrected_run_id"] in json.dumps(report)
    assert fixture["failed_run_id"] in report["conclusion"]["failed_executions"]
    assert report["sections"]["pipeline_trace"]["data"]["graph_image"]["available"] is False
    assert any(
        item["artifact_type"] == "executed_notebook"
        for item in report["sections"]["available_artifacts"]["data"]
    )
    assert any(
        item["artifact_type"] == "associated_dataset"
        and item["dataset_id"] == fixture["dataset_id"]
        for item in report["sections"]["available_artifacts"]["data"]
    )


def test_reports_export_valid_html_pdf_and_json_and_list_saved_records(
    tmp_path, monkeypatch
):
    store = ExecutionStore(tmp_path)
    fixture = _create_complete_workflow(store)
    monkeypatch.setattr(main, "execution_store", store)
    headers = {"Authorization": f"Bearer {fixture['token']}"}

    created = client.post(
        f"/api/notebooks/{fixture['notebook_id']}/reports",
        headers=headers,
    )
    assert created.status_code == 200
    report_id = created.json()["report_id"]
    report_list = client.get(
        f"/api/notebooks/{fixture['notebook_id']}/reports",
        headers=headers,
    )
    assert report_list.status_code == 200
    assert report_list.json()["reports"][0]["report_id"] == report_id

    metadata = client.get(f"/api/reports/{report_id}", headers=headers)
    html_report = client.get(f"/api/reports/{report_id}/html", headers=headers)
    pdf_report = client.get(f"/api/reports/{report_id}/pdf", headers=headers)
    json_report = client.get(f"/api/reports/{report_id}/json", headers=headers)
    unauthorized_report = client.get(
        f"/api/reports/{report_id}/json",
        headers={"Authorization": "Bearer unrelated-token"},
    )

    assert metadata.status_code == 200
    assert metadata.json()["formats"] == ["html", "pdf", "json"]
    assert "Findings and Evidence" in html_report.text
    assert "Experiment Comparison" in html_report.text
    assert html_report.headers["content-security-policy"].startswith("default-src 'none'")
    assert pdf_report.status_code == 200
    assert pdf_report.content.startswith(b"%PDF-")
    assert pdf_report.content.rstrip().endswith(b"%%EOF")
    assert json_report.status_code == 200
    assert unauthorized_report.status_code == 404
    data = json_report.json()
    assert data["report_id"] == report_id
    assert data["sections"]["repair_verification"]["data"][0]["verification_id"] == (
        fixture["verification"]["verification_id"]
    )


def test_sensitive_values_are_redacted_from_all_report_exports(tmp_path, monkeypatch):
    store = ExecutionStore(tmp_path)
    fixture = _create_complete_workflow(store)
    monkeypatch.setattr(main, "execution_store", store)
    headers = {"Authorization": f"Bearer {fixture['token']}"}
    created = client.post(
        f"/api/notebooks/{fixture['notebook_id']}/reports",
        headers=headers,
    )
    report_id = created.json()["report_id"]

    report_json = client.get(
        f"/api/reports/{report_id}/json", headers=headers
    ).text
    report_html = client.get(
        f"/api/reports/{report_id}/html", headers=headers
    ).text

    assert fixture["token"] not in report_json
    assert "sk-123456789012345678901234" not in report_json
    assert "do-not-export" not in report_json
    assert "sk-123456789012345678901234" not in report_html
    assert "do-not-export" not in report_html
    assert '"api_key": "[REDACTED]"' in report_json


def test_artifact_downloads_require_token_and_match_notebook_association(
    tmp_path, monkeypatch
):
    store = ExecutionStore(tmp_path)
    fixture = _create_complete_workflow(store)
    unrelated_id, unrelated_token = store.create_original_notebook(
        "unrelated.ipynb", _notebook_bytes("value = 1")
    )
    monkeypatch.setattr(main, "execution_store", store)

    notebook_artifact = client.get(
        f"/api/notebooks/{fixture['notebook_id']}/artifacts/notebooks/"
        f"{fixture['corrected_notebook_id']}",
        headers={"Authorization": f"Bearer {fixture['token']}"},
    )
    executed_artifact = client.get(
        f"/api/notebooks/{fixture['notebook_id']}/artifacts/executions/"
        f"{fixture['corrected_run_id']}",
        headers={"Authorization": f"Bearer {fixture['token']}"},
    )
    unauthorized = client.get(
        f"/api/notebooks/{fixture['notebook_id']}/artifacts/notebooks/"
        f"{fixture['corrected_notebook_id']}"
    )
    artifact_catalog = client.get(
        f"/api/notebooks/{fixture['notebook_id']}/artifacts",
        headers={"Authorization": f"Bearer {fixture['token']}"},
    )
    cross_notebook = client.get(
        f"/api/notebooks/{unrelated_id}/artifacts/notebooks/"
        f"{fixture['corrected_notebook_id']}",
        headers={"Authorization": f"Bearer {unrelated_token}"},
    )
    dataset_artifact = client.get(
        f"/api/notebooks/{fixture['notebook_id']}/artifacts/datasets/"
        f"{fixture['dataset_id']}",
        headers={"Authorization": f"Bearer {fixture['token']}"},
    )

    assert notebook_artifact.status_code == 200
    assert notebook_artifact.content == fixture["corrected_content"]
    assert executed_artifact.status_code == 200
    assert executed_artifact.content == b"corrected executed notebook"
    assert dataset_artifact.status_code == 200
    assert dataset_artifact.content == fixture["dataset_content"]
    assert unauthorized.status_code == 401
    assert cross_notebook.status_code == 404
    assert artifact_catalog.status_code == 200
    assert {
        item["notebook_id"] for item in artifact_catalog.json()["notebooks"]
    } == {fixture["notebook_id"], fixture["corrected_notebook_id"]}
    assert artifact_catalog.json()["datasets"][0]["dataset_id"] == fixture["dataset_id"]
    assert {
        item["execution_id"]
        for item in artifact_catalog.json()["executed_notebooks"]
    } == {fixture["original_run_id"], fixture["corrected_run_id"]}


def test_unapproved_repair_decision_is_not_fabricated(tmp_path):
    store = ExecutionStore(tmp_path)
    original_content, _, _, _, _, _ = _preprocessing_fixture()
    notebook_id, token = store.create_original_notebook(
        "original.ipynb", original_content
    )

    report = build_report_data(store, notebook_id, token)

    assert report["status"] == "partially_available"
    assert report["overview"]["repair_proposals_count"] > 0
    assert report["overview"]["approved_repair_count"] == 0
    assert all(
        repair["approval_state"] == "decision_not_persisted"
        for repair in report["sections"]["repair_summary"]["data"]
    )


def test_report_preserves_multiple_findings_and_repair_proposals(tmp_path):
    store = ExecutionStore(tmp_path)
    content = _notebook_bytes(
        "model.fit(X_test, y_test)",
        "score = model.score(X_train, y_train)",
    )
    notebook_id, token = store.create_original_notebook("multi.ipynb", content)

    report = build_report_data(store, notebook_id, token)

    findings = report["sections"]["findings"]["data"]
    repairs = report["sections"]["repair_summary"]["data"]
    assert {finding["id"] for finding in findings} == {
        "test_data_used_for_fit",
        "evaluation_on_training_data",
    }
    assert len(repairs) == 2
    assert {repair["finding_id"] for repair in repairs} == {
        finding["id"] for finding in findings
    }
    assert all(
        repair["approval_state"] == "decision_not_persisted" for repair in repairs
    )


def test_report_rejects_verification_with_mismatched_execution_records(tmp_path):
    store = ExecutionStore(tmp_path)
    fixture = _create_complete_workflow(store)
    invalid = dict(fixture["verification"])
    invalid["verification_id"] = "mismatched-report-verification"
    invalid["corrected_execution_id"] = fixture["original_run_id"]
    store.create_verification(invalid)

    with pytest.raises(ReportGenerationError, match="inconsistent"):
        build_report_data(store, fixture["notebook_id"], fixture["token"])
