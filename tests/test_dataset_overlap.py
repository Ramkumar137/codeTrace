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
    train_filename="train.csv",
    test_filename="test.csv",
):
    data = {}
    if identifier_column is not None:
        data["identifier_column"] = identifier_column
    if group_column is not None:
        data["group_column"] = group_column
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
    assert finding["id"] == "train_test_group_overlap"
    assert finding["severity"] == "high"


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
