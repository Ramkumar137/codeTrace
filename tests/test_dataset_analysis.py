"""Tests for explicitly uploaded CSV dataset analysis."""

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.main import app


client = TestClient(app)
ANALYZE_URL = "/api/datasets/analyze"


def upload(content, filename="sample.csv"):
    return client.post(
        ANALYZE_URL,
        files={"file": (filename, content, "text/csv")},
    )


def test_analyzes_column_types_missingness_and_numeric_summaries():
    response = upload(
        b"age,score,active,note,empty\n"
        b"20,1.5,true,hello,\n"
        b",2,false,,\n"
    )

    assert response.status_code == 200
    dataset = response.json()["dataset"]
    assert dataset["row_count"] == 2
    assert dataset["column_count"] == 5

    age, score, active, note, empty = dataset["columns"]
    assert age["inferred_type"] == "integer"
    assert age["missing_values"] == 1
    assert age["missing_percentage"] == 50
    assert age["numeric_summary"] == {
        "count": 1,
        "minimum": "20",
        "maximum": "20",
        "mean": "20",
    }
    assert score["inferred_type"] == "number"
    assert score["numeric_summary"] == {
        "count": 2,
        "minimum": "1.5",
        "maximum": "2",
        "mean": "1.75",
    }
    assert active["inferred_type"] == "boolean"
    assert active["numeric_summary"] is None
    assert note["inferred_type"] == "text"
    assert note["missing_values"] == 1
    assert empty["inferred_type"] == "empty"
    assert empty["missing_percentage"] == 100


def test_parses_utf8_bom_and_quoted_csv_fields_without_returning_row_values():
    response = upload(
        b"\xef\xbb\xbfname,description\n"
        b"Ada,\"researcher, mathematician\"\n"
    )

    assert response.status_code == 200
    dataset = response.json()["dataset"]
    assert dataset["filename"] == "sample.csv"
    assert dataset["row_count"] == 1
    assert [column["name"] for column in dataset["columns"]] == [
        "name",
        "description",
    ]
    assert "Ada" not in response.text
    assert "researcher" not in response.text


def test_skips_blank_records_and_handles_header_only_csv():
    response = upload(b"name,value\n\n")

    assert response.status_code == 200
    dataset = response.json()["dataset"]
    assert dataset["row_count"] == 0
    assert [column["inferred_type"] for column in dataset["columns"]] == [
        "empty",
        "empty",
    ]
    assert [column["missing_percentage"] for column in dataset["columns"]] == [
        0,
        0,
    ]


def test_rejects_missing_file():
    response = client.post(ANALYZE_URL)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "missing_file"


def test_rejects_non_csv_extension():
    response = upload(b"a,b\n1,2\n", filename="dataset.txt")

    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "unsupported_file_type"


def test_rejects_empty_file():
    response = upload(b"")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "empty_file"


def test_rejects_dataset_over_configured_limit(monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_SIZE_BYTES", 8)

    response = upload(b"column\n12345678\n")

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "file_too_large"


def test_rejects_non_utf8_csv():
    response = upload(b"name\n\xff\n")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_csv_encoding"


@pytest.mark.parametrize(
    "content",
    [
        b"\n",
        b"name,name\nAda,Lovelace\n",
        b"name,,value\nAda,1,2\n",
        b"name,value\nAda\n",
        b'name,value\n"Ada,1\n',
    ],
)
def test_rejects_invalid_csv_structures(content):
    response = upload(content)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_csv_structure"
