"""Tests for explicitly uploaded train/test overlap checks."""

from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)
OVERLAP_URL = "/api/datasets/overlap"


def compare(
    train_csv,
    test_csv,
    *,
    identifier_column=None,
    group_column=None,
    evaluation_objective=None,
    train_filename="train.csv",
    test_filename="test.csv",
):
    data = {}
    if identifier_column is not None:
        data["identifier_column"] = identifier_column
    if group_column is not None:
        data["group_column"] = group_column
    if evaluation_objective is not None:
        data["evaluation_objective"] = evaluation_objective
    return client.post(
        OVERLAP_URL,
        files={
            "train_file": (train_filename, train_csv, "text/csv"),
            "test_file": (test_filename, test_csv, "text/csv"),
        },
        data=data,
    )


def test_finds_exact_duplicate_rows_without_returning_row_values():
    response = compare(
        b"id,feature\nprivate-1,alpha\nprivate-2,beta\n",
        b"id,feature\nprivate-2,beta\nprivate-3,gamma\n",
    )

    assert response.status_code == 200
    result = response.json()["overlap"]
    finding = result["findings"][0]
    assert finding["id"] == "exact_train_test_row_overlap"
    assert finding["evidence"][0]["overlap_count"] == 1
    assert "private-2" not in response.text


def test_configured_identifier_overlap_is_reported():
    response = compare(
        b"customer_id,feature\nc-1,alpha\nc-2,beta\n",
        b"customer_id,feature\nc-2,delta\nc-3,gamma\n",
        identifier_column="customer_id",
    )

    assert response.status_code == 200
    finding = response.json()["overlap"]["findings"][0]
    assert finding["id"] == "train_test_identifier_overlap"
    assert finding["evidence"][0]["overlap_count"] == 1
    assert finding["related_pipeline_node_ids"] == []


def test_configured_group_overlap_is_reported():
    response = compare(
        b"group,feature\nward-a,alpha\nward-b,beta\n",
        b"group,feature\nward-a,gamma\nward-c,delta\n",
        group_column="group",
    )

    finding = response.json()["overlap"]["findings"][0]
    visualization = response.json()["overlap"]["group_partition_visualization"]
    assert finding["id"] == "train_test_group_overlap"
    assert finding["severity"] == "high"
    assert visualization["execution_partition_assignments"] is False
    assert visualization["overlap_count"] == 1
    assert visualization["overlap_groups"] == ["Entity 001"]
    assert "ward-a" not in response.text


def test_unseen_group_objective_explains_group_overlap_conflict():
    response = compare(
        b"group,feature\nward-a,alpha\nward-b,beta\n",
        b"group,feature\nward-a,gamma\nward-c,delta\n",
        group_column="group",
        evaluation_objective="unseen_groups",
    )

    result = response.json()["overlap"]
    finding = next(
        item for item in result["findings"] if item["id"] == "train_test_group_overlap"
    )
    assert result["evaluation_objective"] == "unseen_groups"
    assert result["objective_review"]["status"] == "unseen_group_holdout"
    assert finding["severity"] == "high"
    assert "conflict" in finding["explanation"]
    assert "group-aware split" in finding["recommendation"]
    assert "ward-a" not in response.text


def test_future_known_group_objective_does_not_call_group_overlap_a_defect():
    response = compare(
        b"group,feature\nward-a,alpha\nward-b,beta\n",
        b"group,feature\nward-a,gamma\nward-c,delta\n",
        group_column="group",
        evaluation_objective="future_known_groups",
    )

    result = response.json()["overlap"]
    finding = next(
        item for item in result["findings"] if item["id"] == "train_test_group_overlap"
    )
    assert finding["severity"] == "informational"
    assert finding["classification"] == "informational_review"
    assert finding["status"] == "contextual"
    assert result["objective_review"]["status"] == "temporal_validation_required"
    assert "chronological ordering" in result["objective_review"]["message"]


def test_independent_rows_objective_flags_dependence_as_context():
    response = compare(
        b"group,feature\nward-a,alpha\nward-b,beta\n",
        b"group,feature\nward-a,gamma\nward-c,delta\n",
        group_column="group",
        evaluation_objective="independent_rows",
    )

    finding = next(
        item
        for item in response.json()["overlap"]["findings"]
        if item["id"] == "train_test_group_overlap"
    )
    assert finding["severity"] == "medium"
    assert "statistically dependent" in finding["recommendation"]


def test_unsupported_evaluation_objective_is_rejected():
    response = compare(
        b"group,feature\nward-a,alpha\n",
        b"group,feature\nward-b,beta\n",
        evaluation_objective="guess",
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_evaluation_objective"


def test_safe_disjoint_splits_return_no_findings():
    response = compare(
        b"id,feature\nid-1,alpha\nid-2,beta\n",
        b"id,feature\nid-3,gamma\nid-4,delta\n",
        identifier_column="id",
        group_column="id",
    )

    assert response.status_code == 200
    result = response.json()["overlap"]
    assert result["findings"] == []
    assert all(check["overlap_count"] == 0 for check in result["checks"])


def test_different_column_order_still_compares_exact_rows():
    response = compare(
        b"id,feature\nid-1,alpha\n",
        b"feature,id\nalpha,id-1\n",
    )

    assert response.status_code == 200
    assert response.json()["overlap"]["findings"][0]["id"] == (
        "exact_train_test_row_overlap"
    )


def test_different_schemas_skip_full_row_comparison_without_claiming_success():
    response = compare(
        b"id,feature\nid-1,alpha\n",
        b"id,other\nid-1,alpha\n",
    )

    result = response.json()["overlap"]
    assert result["findings"] == []
    assert result["checks"][0]["status"] == "skipped"
    assert "do not have the same column names" in result["checks"][0]["reason"]


def test_missing_identifier_column_is_explicit_error():
    response = compare(
        b"id,feature\nid-1,alpha\n",
        b"id,feature\nid-2,beta\n",
        identifier_column="patient_id",
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "identifier_column_not_found"


def test_overlap_endpoint_requires_both_csv_files():
    response = client.post(OVERLAP_URL)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "missing_training_file"
