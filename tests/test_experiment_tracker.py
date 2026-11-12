import hashlib

from fastapi.testclient import TestClient

import backend.app.main as main
from backend.app.main import app
from backend.app.services.experiment_tracker import (
    analyze_experiment_history,
    fingerprint_datasets,
)
from backend.app.services.execution_store import ExecutionStore


client = TestClient(app)


def _record(
    experiment_id,
    *,
    dataset_fingerprint="dataset-a",
    decision="selected",
    test_ref="test",
    validation_ref=None,
):
    return {
        "experiment_id": experiment_id,
        "timestamp": f"2026-01-0{experiment_id[-1]}T00:00:00+00:00",
        "dataset_fingerprint": dataset_fingerprint,
        "model_name": "Classifier",
        "hyperparameters": {"depth": int(experiment_id[-1])},
        "training_data_reference": "train",
        "validation_data_reference": validation_ref,
        "test_data_reference": test_ref,
        "evaluation_metric": "accuracy",
        "metric_value": 0.8,
        "model_selection_decision": decision,
        "previous_experiment_id": None,
    }


def test_repeated_test_selection_is_reported_only_after_multiple_records():
    single = analyze_experiment_history([_record("experiment-1")])
    repeated = analyze_experiment_history(
        [_record("experiment-1"), _record("experiment-2")]
    )

    assert single["findings"] == []
    assert single["datasets"][0]["test_feedback_status"] == "single_test_evaluation"
    assert repeated["findings"][0]["rule_id"] == "repeated_test_set_model_selection"
    assert repeated["findings"][0]["experiment_ids"] == [
        "experiment-1",
        "experiment-2",
    ]


def test_validation_selection_and_single_final_evaluation_are_not_contamination():
    validation = _record(
        "experiment-1",
        decision="validation_selected",
        test_ref=None,
        validation_ref="validation",
    )
    final = _record("experiment-2", decision="final_evaluation")
    result = analyze_experiment_history([validation, final])

    assert result["findings"] == []
    assert result["datasets"][0]["validation_or_cv_selection_count"] == 1


def test_dataset_fingerprint_uses_content_hash_and_never_row_values():
    content = b"secret,rows\npatient-a,1\n"
    result = fingerprint_datasets(
        [{"dataset_id": "dataset-1", "content": content}]
    )

    assert result == hashlib.sha256(
        b"dataset-1\0" + hashlib.sha256(content).digest() + b"\0"
    ).hexdigest()
    assert "patient-a" not in result


def test_experiment_history_api_persists_and_flags_repeated_test_feedback(
    tmp_path, monkeypatch
):
    store = ExecutionStore(tmp_path)
    notebook_id, token = store.create_original_notebook("history.ipynb", b"{}")
    monkeypatch.setattr(main, "execution_store", store)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "dataset_version": "cohort-v1",
        "model_name": "Classifier",
        "hyperparameters": {"max_depth": 4},
        "training_data_reference": "train",
        "validation_data_reference": None,
        "test_data_reference": "test",
        "evaluation_metric": "accuracy",
        "metric_value": 0.82,
        "model_selection_decision": "selected",
    }

    first = client.post(
        f"/api/notebooks/{notebook_id}/experiment-history",
        headers=headers,
        json=payload,
    )
    second = client.post(
        f"/api/notebooks/{notebook_id}/experiment-history",
        headers=headers,
        json=payload,
    )

    assert first.status_code == 200
    assert first.json()["analysis"]["findings"] == []
    assert second.status_code == 200
    assert second.json()["experiment"]["previous_experiment_id"] == (
        first.json()["experiment"]["experiment_id"]
    )
    finding = second.json()["analysis"]["findings"][0]
    assert finding["rule_id"] == "repeated_test_set_model_selection"
    assert len(finding["experiment_ids"]) == 2
    assert "cohort-v1" not in finding["evidence"][0]["dataset_fingerprint"]

    history = client.get(
        f"/api/notebooks/{notebook_id}/experiment-history",
        headers=headers,
    )
    assert history.status_code == 200
    assert len(history.json()["experiments"]) == 2
    assert history.json()["analysis"]["findings"]


def test_experiment_history_requires_dataset_version_or_associated_data(
    tmp_path, monkeypatch
):
    store = ExecutionStore(tmp_path)
    notebook_id, token = store.create_original_notebook("history.ipynb", b"{}")
    monkeypatch.setattr(main, "execution_store", store)
    response = client.post(
        f"/api/notebooks/{notebook_id}/experiment-history",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model_name": "Classifier",
            "training_data_reference": "train",
            "evaluation_metric": "accuracy",
            "metric_value": 0.8,
            "model_selection_decision": "final_evaluation",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "dataset_version_required"
