"""Tests for deterministic notebook repair proposals and generation."""

import json

import nbformat
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.notebook_analyzer import analyze_notebook
from backend.app.services.repair_engine import (
    AUTOMATICALLY_REPAIRABLE,
    NOT_REPAIRABLE,
    REQUIRES_MANUAL_INTERVENTION,
    _validate_candidate,
    build_repair_catalog,
    generate_corrected_notebook,
)


client = TestClient(app)
REPAIR_URL = "/api/notebooks/repairs/generate"


def cells_from_sources(*sources):
    return [
        {"index": index, "cell_type": "code", "source": source}
        for index, source in enumerate(sources)
    ]


def repairs_for(cells):
    findings = analyze_notebook(cells)["findings"]
    return build_repair_catalog(cells, findings)


def notebook_bytes(cells):
    notebook = nbformat.v4.new_notebook(cells=cells)
    return nbformat.writes(notebook).encode("utf-8")


def leakage_cells(*, imports=True):
    sources = []
    if imports:
        sources.append("from sklearn.preprocessing import StandardScaler")
    sources.extend(
        [
            "scaler = StandardScaler()\nX_scaled = scaler.fit_transform(X)",
            "X_train, X_test, y_train, y_test = train_test_split(X_scaled, y)",
            "model.fit(X_train, y_train)",
        ]
    )
    return cells_from_sources(*sources)


def test_pre_split_scaler_has_a_validated_training_only_repair():
    cells = leakage_cells()
    repair = next(item for item in repairs_for(cells) if item["repair_type"] == "preprocessing_fit_before_split")

    assert repair["repair_status"] == AUTOMATICALLY_REPAIRABLE
    assert repair["validation_status"] == "passed"
    assert "train_test_split(X, y)" in repair["corrected_code"]
    assert "X_train = scaler.fit_transform(X_train)" in repair["corrected_code"]
    assert "X_test = scaler.transform(X_test)" in repair["corrected_code"]
    assert repair["validation"]["experiment_verification"] == "not_performed"


def test_safe_train_only_preprocessing_is_not_modified():
    cells = cells_from_sources(
        "from sklearn.preprocessing import StandardScaler",
        "X_train, X_test = train_test_split(X)",
        "scaler = StandardScaler()\nX_train_scaled = scaler.fit_transform(X_train)",
    )

    assert repairs_for(cells) == []


def test_repair_preserves_related_cells_and_does_not_change_model_code():
    cells = leakage_cells()
    repair = next(item for item in repairs_for(cells) if item.get("repair_type"))

    assert repair["affected_cells"] == [1, 2]
    assert "model.fit(X_train, y_train)" not in repair["corrected_code"]
    assert "X_scaled = scaler.fit_transform(X)" not in repair["corrected_code"]


def test_missing_train_test_variables_leaves_preprocessing_for_manual_review():
    cells = cells_from_sources(
        "scaler = StandardScaler()\nX_scaled = scaler.fit_transform(X)",
        "result = train_test_split(X_scaled, y)",
    )

    repair = next(item for item in repairs_for(cells) if item["finding_id"] == "preprocessing_fit_before_split")

    assert repair["repair_status"] == REQUIRES_MANUAL_INTERVENTION
    assert not repair["cell_changes"]


def test_missing_transformer_import_does_not_generate_automated_repair():
    cells = leakage_cells(imports=False)
    repair = next(item for item in repairs_for(cells) if item["finding_id"] == "preprocessing_fit_before_split")

    assert repair["repair_status"] == REQUIRES_MANUAL_INTERVENTION
    assert repair["validation_status"] == "not_applicable"


def test_direct_target_column_is_removed_only_from_literal_feature_list():
    cells = cells_from_sources(
        'y = df["outcome"]\nX = df[["outcome", "age"]]',
        "X_train, X_test, y_train, y_test = train_test_split(X, y)",
    )
    repair = next(item for item in repairs_for(cells) if item["finding_id"] == "target_column_in_features")

    assert repair["repair_status"] == AUTOMATICALLY_REPAIRABLE
    assert 'X = df[["age"]]' in repair["corrected_code"]
    assert 'y = df["outcome"]' in repair["corrected_code"]


def test_target_feature_is_not_removed_when_no_other_feature_remains():
    cells = cells_from_sources(
        'y = df["outcome"]\nX = df[["outcome"]]',
        "X_train, X_test, y_train, y_test = train_test_split(X, y)",
    )
    repair = next(item for item in repairs_for(cells) if item["finding_id"] == "target_column_in_features")

    assert repair["repair_status"] == REQUIRES_MANUAL_INTERVENTION
    assert not repair["cell_changes"]


def test_target_column_selection_with_comments_is_left_for_manual_review():
    cells = cells_from_sources(
        'y = df["outcome"]\nX = df[["outcome",  # target\n         "age"]]',
        "X_train, X_test, y_train, y_test = train_test_split(X, y)",
    )
    repair = next(item for item in repairs_for(cells) if item["finding_id"] == "target_column_in_features")

    assert repair["repair_status"] == REQUIRES_MANUAL_INTERVENTION
    assert not repair["cell_changes"]


def test_target_variable_derivation_requires_manual_intervention():
    cells = cells_from_sources(
        "X = pd.concat([feature_frame, y], axis=1)",
        "X_train, X_test, y_train, y_test = train_test_split(features, y)",
    )
    repair = next(item for item in repairs_for(cells) if item["finding_id"] == "target_variable_in_features")

    assert repair["repair_status"] == REQUIRES_MANUAL_INTERVENTION


def test_target_assignment_after_feature_selection_is_not_automatically_repaired():
    cells = cells_from_sources(
        'X = df[["outcome", "age"]]\ny = df["outcome"]',
        "X_train, X_test, y_train, y_test = train_test_split(X, y)",
    )
    repair = next(item for item in repairs_for(cells) if item["finding_id"] == "target_column_in_features")

    assert repair["repair_status"] == REQUIRES_MANUAL_INTERVENTION
    assert not repair["cell_changes"]


def test_group_overlap_has_a_manual_recommendation_not_a_guessed_split():
    finding = {
        "id": "train_test_group_overlap",
        "rule_id": "train_test_group_overlap",
        "category": "train_test_overlap",
        "title": "Groups overlap",
        "recommendation": "Review group-aware splitting.",
        "cell_indices": [],
    }

    repair = build_repair_catalog([], [finding])[0]

    assert repair["repair_status"] == REQUIRES_MANUAL_INTERVENTION
    assert not repair["cell_changes"]


def test_test_metric_selection_is_not_rewritten_speculatively():
    cells = cells_from_sources(
        "score = model.score(X_test, y_test)",
        "if score > best_score:\n    best_score = score",
    )
    repair = next(item for item in repairs_for(cells) if item["finding_id"] == "test_metric_used_for_model_selection")

    assert repair["repair_status"] == REQUIRES_MANUAL_INTERVENTION
    assert not repair["cell_changes"]


def test_training_set_evaluation_finding_requires_manual_intervention():
    cells = cells_from_sources("model.score(X_train, y_train)")
    repair = next(item for item in repairs_for(cells) if item["finding_id"] == "evaluation_on_training_data")

    assert repair["repair_status"] == REQUIRES_MANUAL_INTERVENTION


def test_invalid_candidate_python_syntax_fails_validation():
    cells = cells_from_sources("value = 1")
    finding = {"id": "unsupported", "rule_id": "unsupported"}

    assert not _validate_candidate(
        cells,
        {0: "value = 1"},
        {0: "value = ("},
        finding,
    )


def test_conflicting_repairs_on_the_same_cells_are_not_approvable():
    cells = cells_from_sources(
        "from sklearn.preprocessing import StandardScaler\n"
        'y = df["outcome"]\nX = df[["outcome", "age"]]\n'
        "scaler = StandardScaler()\nX_scaled = scaler.fit_transform(X)",
        "X_train, X_test, y_train, y_test = train_test_split(X_scaled, y)",
    )
    repairs = repairs_for(cells)

    assert len(repairs) >= 2
    assert all(item["repair_status"] == REQUIRES_MANUAL_INTERVENTION for item in repairs)
    assert all(item["validation_status"] == "conflict" for item in repairs)


def test_unknown_finding_is_not_repairable_with_available_evidence():
    repair = build_repair_catalog(
        [],
        [{"id": "unknown_rule", "rule_id": "unknown_rule", "cell_indices": []}],
    )[0]

    assert repair["repair_status"] == NOT_REPAIRABLE


def test_generated_notebook_preserves_metadata_and_original_file():
    notebook = nbformat.v4.new_notebook(
        cells=[
            nbformat.v4.new_code_cell(
                "from sklearn.preprocessing import StandardScaler",
                execution_count=1,
                outputs=[nbformat.v4.new_output("stream", name="stdout", text="old\n")],
            ),
            nbformat.v4.new_code_cell(
                "scaler = StandardScaler()\nX_scaled = scaler.fit_transform(X)",
                execution_count=2,
                outputs=[nbformat.v4.new_output("stream", name="stdout", text="stale\n")],
            ),
            nbformat.v4.new_code_cell(
                "X_train, X_test, y_train, y_test = train_test_split(X_scaled, y)",
                execution_count=3,
                outputs=[],
            ),
            nbformat.v4.new_markdown_cell("Keep this note."),
        ]
    )
    notebook.metadata["custom_metadata"] = {"owner": "CodeTrace"}
    notebook.cells[3].metadata["tag"] = "untouched"
    original = nbformat.writes(notebook).encode("utf-8")
    analysis_cells = [
        {"index": index, "cell_type": cell.cell_type, "source": cell.source}
        for index, cell in enumerate(notebook.cells)
    ]
    proposal = next(item for item in repairs_for(analysis_cells) if item.get("repair_type"))

    corrected_bytes, corrected_filename = generate_corrected_notebook(
        original, "source.ipynb", [proposal["repair_id"]]
    )
    corrected = nbformat.reads(corrected_bytes.decode("utf-8"), as_version=nbformat.NO_CONVERT)
    nbformat.validate(corrected)

    assert corrected_filename == "source-repaired.ipynb"
    assert original == nbformat.writes(notebook).encode("utf-8")
    assert corrected.metadata["custom_metadata"] == {"owner": "CodeTrace"}
    assert corrected.cells[3].source == "Keep this note."
    assert corrected.cells[3].metadata["tag"] == "untouched"
    assert corrected.cells[1].execution_count is None
    assert corrected.cells[1].outputs == []
    assert corrected.cells[2].execution_count is None


def test_generation_rejects_empty_or_unknown_approval_selection():
    content = notebook_bytes([nbformat.v4.new_code_cell("value = 1")])

    try:
        generate_corrected_notebook(content, "sample.ipynb", [])
    except ValueError as error:
        assert "Approve at least one repair" in str(error)
    else:
        raise AssertionError("Expected empty selection to be rejected.")

    try:
        generate_corrected_notebook(content, "sample.ipynb", ["not-a-repair"])
    except ValueError as error:
        assert "do not belong to this notebook" in str(error)
    else:
        raise AssertionError("Expected unknown repair ID to be rejected.")


def test_repair_generation_endpoint_applies_only_approved_repair():
    content = notebook_bytes(
        [
            nbformat.v4.new_code_cell(
                "from sklearn.preprocessing import StandardScaler"
            ),
            nbformat.v4.new_code_cell(
                "scaler = StandardScaler()\nX_scaled = scaler.fit_transform(X)"
            ),
            nbformat.v4.new_code_cell(
                "X_train, X_test, y_train, y_test = train_test_split(X_scaled, y)"
            ),
        ]
    )
    cells = [
        {"index": index, "cell_type": "code", "source": cell.source}
        for index, cell in enumerate(nbformat.reads(content.decode(), as_version=nbformat.NO_CONVERT).cells)
    ]
    repair = next(item for item in repairs_for(cells) if item.get("repair_type"))

    response = client.post(
        REPAIR_URL,
        files={"file": ("sample.ipynb", content, "application/octet-stream")},
        data={"repair_ids": json.dumps([repair["repair_id"]])},
    )

    assert response.status_code == 200
    assert "sample-repaired.ipynb" in response.headers["content-disposition"]
    corrected = nbformat.reads(response.content.decode("utf-8"), as_version=nbformat.NO_CONVERT)
    nbformat.validate(corrected)
    assert "train_test_split(X, y)" in corrected.cells[2].source


def test_repair_generation_endpoint_rejects_rejected_or_unknown_repairs():
    content = notebook_bytes([nbformat.v4.new_code_cell("value = 1")])

    response = client.post(
        REPAIR_URL,
        files={"file": ("sample.ipynb", content, "application/octet-stream")},
        data={"repair_ids": json.dumps(["not-approved"])},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unknown_repair_id"
