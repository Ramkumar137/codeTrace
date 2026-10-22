"""Tests for source-only notebook analysis."""

from backend.app.services.notebook_analyzer import analyze_notebook


def cells(*sources):
    return [
        {"index": index, "cell_type": "code", "source": source}
        for index, source in enumerate(sources)
    ]


def test_extracts_imports_data_paths_and_ml_operations():
    result = analyze_notebook(
        cells(
            "import pandas as pd\nfrom sklearn.model_selection import train_test_split",
            "df = pd.read_csv('data/train.csv')\nX = df[['feature']]\ny = df['label']",
            "X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)",
            "model = RandomForestClassifier()\nmodel.fit(X_train, y_train)",
            "predictions = model.predict(X_test)\naccuracy_score(y_test, predictions)",
        )
    )

    analysis = result
    assert "pandas" in analysis["libraries"]
    assert "sklearn" in analysis["libraries"]
    assert analysis["dataset_references"][0]["path"] == "data/train.csv"
    assert analysis["operations"]["split"][0]["cell_index"] == 2
    assert analysis["operations"]["model"][0]["cell_index"] == 3
    assert analysis["operations"]["training"][0]["cell_index"] == 3
    assert analysis["operations"]["prediction"][0]["cell_index"] == 4
    assert analysis["operations"]["evaluation"][0]["cell_index"] == 4
    assert analysis["pipeline_graph"]["nodes"]
    assert analysis["pipeline_graph"]["edges"]
    edge = analysis["pipeline_graph"]["edges"][0]
    assert edge["source"] and edge["target"]
    assert edge["relationship"] == "inferred_from_variable_reference"
    assert edge["source_refs"]


def test_flags_explicit_test_set_model_fit_with_source_evidence():
    result = analyze_notebook(cells("model.fit(X_test, y_test)"))

    finding = result["findings"][0]
    assert finding["id"] == "test_data_used_for_fit"
    assert finding["severity"] == "high"
    assert finding["cell_indices"] == [0]
    assert finding["evidence"][0]["snippet"] == "model.fit(X_test, y_test)"
    assert finding["caveat"]
    assert finding["recommendation"]
    assert finding["source_refs"] == [{"cell_index": 0, "line": 1}]


def test_flags_full_data_preprocessing_before_later_split_as_potential_risk():
    result = analyze_notebook(
        cells(
            "scaler = StandardScaler()\nX_scaled = scaler.fit_transform(X)",
            "X_train, X_test, y_train, y_test = train_test_split(X_scaled, y)",
        )
    )

    finding = result["findings"][0]
    assert finding["id"] == "preprocessing_fit_before_split"
    assert finding["severity"] == "medium"
    assert finding["cell_indices"] == [0, 1]
    assert "cannot establish" in finding["caveat"]


def test_does_not_flag_preprocessor_construction_without_fitting():
    result = analyze_notebook(
        cells("scaler = StandardScaler()", "X_train, X_test = train_test_split(X)")
    )

    assert result["findings"] == []


def test_flags_training_partition_used_as_evaluation_input():
    result = analyze_notebook(cells("model.score(X_train, y_train)"))

    assert result["findings"][0]["id"] == "evaluation_on_training_data"


def test_does_not_treat_test_size_parameter_as_test_data():
    result = analyze_notebook(cells("model.fit(X_train, y_train, test_size=0.2)"))

    assert not any(finding["id"] == "test_data_used_for_fit" for finding in result["findings"])


def test_malformed_python_uses_fallback_and_discloses_limitations():
    result = analyze_notebook(cells("model.fit(X_train, y_train\n"))

    assert result["all_operations"][0]["evidence"] == "source_text_fallback"
    assert result["pipeline_graph"]["nodes"][0]["evidence"] == "source_text_fallback"
    assert any("AST parsing failed" in item for item in result["limitations"])


def test_empty_notebook_returns_honest_empty_graph_and_audit():
    result = analyze_notebook([])

    assert result["pipeline_graph"]["nodes"] == []
    assert result["pipeline_graph"]["edges"] == []
    assert result["findings"] == []
    assert result["pipeline_graph"]["limitations"]


def test_unresolved_inputs_are_explicit_not_linked_to_guessed_producers():
    result = analyze_notebook(cells("model.fit(unknown_train, unknown_labels)"))

    graph = result["pipeline_graph"]
    assert graph["edges"] == []
    unresolved_names = {item["variable"] for item in graph["unresolved_references"]}
    assert {"unknown_train", "unknown_labels"} <= unresolved_names
