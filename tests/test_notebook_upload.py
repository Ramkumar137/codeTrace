"""Tests for notebook upload validation and source-only parsing."""

from pathlib import Path

import nbformat
import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.main import app


client = TestClient(app)
UPLOAD_URL = "/api/notebooks/upload"


def notebook_bytes(cells):
    notebook = nbformat.v4.new_notebook(cells=cells)
    return nbformat.writes(notebook).encode("utf-8")


def upload(content, filename="sample.ipynb"):
    return client.post(
        UPLOAD_URL,
        files={"file": (filename, content, "application/octet-stream")},
    )


def test_upload_parses_markdown_and_code_cells():
    content = notebook_bytes(
        [
            nbformat.v4.new_markdown_cell("# Notebook title"),
            nbformat.v4.new_code_cell(
                "value = 3",
                execution_count=1,
                outputs=[nbformat.v4.new_output("stream", name="stdout", text="3\n")],
            ),
        ]
    )

    response = upload(content)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert {
        key: data["notebook"][key]
        for key in (
            "filename", "format_version", "total_cells", "code_cells",
            "markdown_cells", "raw_cells", "cells",
        )
    } == {
        "filename": "sample.ipynb",
        "format_version": 4,
        "total_cells": 2,
        "code_cells": 1,
        "markdown_cells": 1,
        "raw_cells": 0,
        "cells": [
            {
                "index": 0,
                "cell_type": "markdown",
                "source": "# Notebook title",
                "execution_count": None,
                "has_outputs": False,
            },
            {
                "index": 1,
                "cell_type": "code",
                "source": "value = 3",
                "execution_count": 1,
                "has_outputs": True,
            },
        ],
    }
    assert data["notebook"]["analysis"]["pipeline_graph"]["trace_type"] == (
        "static_inference_not_runtime_trace"
    )
    trace = data["notebook"]["analysis"]["pipeline_trace"]
    assert trace["metadata"]["trace_type"] == "static_source_dependency_graph"
    assert trace["metadata"]["node_count"] == 0
    assert trace["nodes"] == []
    assert trace["edges"] == []


def test_upload_includes_pipeline_trace_built_from_notebook_source():
    content = notebook_bytes(
        [
            nbformat.v4.new_code_cell('data = pd.read_csv("train.csv")'),
            nbformat.v4.new_code_cell('X = data[["feature"]]\ny = data["label"]'),
            nbformat.v4.new_code_cell(
                "X_train, X_test, y_train, y_test = train_test_split(X, y)"
            ),
            nbformat.v4.new_code_cell(
                "model = LogisticRegression()\nmodel.fit(X_train, y_train)"
            ),
        ]
    )

    response = upload(content)

    assert response.status_code == 200
    trace = response.json()["notebook"]["analysis"]["pipeline_trace"]
    node_types = {node["operation_type"] for node in trace["nodes"]}
    assert {
        "dataset_loading",
        "feature_engineering",
        "train_test_split",
        "model_training",
    } <= node_types
    split = next(
        node for node in trace["nodes"] if node["operation_type"] == "train_test_split"
    )
    training = next(
        node for node in trace["nodes"] if node["operation_type"] == "model_training"
    )
    assert any(
        edge["source"] == split["id"]
        and edge["target"] == training["id"]
        and {"X_train", "y_train"} <= set(edge["variables"])
        for edge in trace["edges"]
    )


def test_upload_connects_detection_findings_to_supported_pipeline_nodes():
    content = notebook_bytes(
        [
            nbformat.v4.new_code_cell(
                'y = df["outcome"]\nX = df[["outcome", "age"]]'
            ),
            nbformat.v4.new_code_cell(
                "X_train, X_test, y_train, y_test = train_test_split(X, y)"
            ),
        ]
    )

    response = upload(content)

    assert response.status_code == 200
    notebook = response.json()["notebook"]
    finding = next(
        item
        for item in notebook["analysis"]["findings"]
        if item["rule_id"] == "target_column_in_features"
    )
    trace = notebook["analysis"]["pipeline_trace"]
    assert finding["related_pipeline_node_ids"]
    assert any(
        finding["id"] in node["finding_ids"]
        for node in trace["nodes"]
        if node["id"] in finding["related_pipeline_node_ids"]
    )


def test_upload_counts_all_supported_cell_types():
    content = notebook_bytes(
        [
            nbformat.v4.new_raw_cell("raw source"),
            nbformat.v4.new_code_cell("pass"),
            nbformat.v4.new_markdown_cell("notes"),
            nbformat.v4.new_raw_cell("more raw source"),
        ]
    )

    response = upload(content)

    assert response.status_code == 200
    notebook = response.json()["notebook"]
    assert notebook["total_cells"] == 4
    assert notebook["code_cells"] == 1
    assert notebook["markdown_cells"] == 1
    assert notebook["raw_cells"] == 2
    assert [cell["index"] for cell in notebook["cells"]] == [0, 1, 2, 3]


def test_upload_rejects_malformed_json():
    response = upload(b'{"nbformat":')

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_notebook_json"


def test_upload_rejects_invalid_notebook_structure():
    response = upload(b'{"nbformat": 4, "nbformat_minor": 5, "cells": "not-a-list"}')

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_notebook_structure"


def test_upload_rejects_unsupported_notebook_version():
    response = upload(b'{"nbformat": 5, "nbformat_minor": 0, "cells": []}')

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsupported_notebook_version"


def test_upload_rejects_wrong_file_extension():
    response = upload(b"{}", filename="sample.json")

    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "unsupported_file_type"


def test_upload_rejects_empty_file():
    response = upload(b"")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "empty_file"


def test_upload_rejects_file_over_configured_limit(monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_SIZE_BYTES", 32)

    response = upload(b"x" * 33)

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "file_too_large"


def test_upload_rejects_missing_file():
    response = client.post(UPLOAD_URL)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "missing_file"


def test_upload_accepts_missing_execution_count_and_outputs():
    content = notebook_bytes([nbformat.v4.new_code_cell("result = 1")])

    response = upload(content)

    assert response.status_code == 200
    cell = response.json()["notebook"]["cells"][0]
    assert cell["execution_count"] is None
    assert cell["has_outputs"] is False


def test_upload_parses_suspicious_code_without_executing_it(tmp_path: Path):
    marker = tmp_path / "executed.txt"
    source = f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')"

    response = upload(notebook_bytes([nbformat.v4.new_code_cell(source)]))

    assert response.status_code == 200
    assert response.json()["notebook"]["cells"][0]["source"] == source
    assert not marker.exists()


def test_upload_rejects_blank_filename():
    response = upload(b"{}", filename="")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "missing_filename"
