from backend.app.services.notebook_analyzer import analyze_notebook
from backend.app.services.pipeline_trace import build_pipeline_trace
from backend.app.services.variable_lineage import analyze_variable_lineage


def cells(*sources):
    return [
        {"index": index, "cell_type": "code", "source": source}
        for index, source in enumerate(sources)
    ]


def test_aliases_and_cross_cell_reassignments_have_versions_and_parent_links():
    lineage = analyze_variable_lineage(
        cells(
            "df = pd.read_csv('data.csv')\ndata = df",
            "X = data.copy()",
            "X = X.drop(columns=['target'])",
        )
    )

    x_versions = [
        node for node in lineage["nodes"] if node["variable"] == "X"
    ]
    assert [node["version"] for node in x_versions] == [1, 2]
    assert x_versions[0]["parents"]
    assert x_versions[1]["parents"] == [x_versions[0]["id"]]
    assert x_versions[1]["cell_index"] == 2
    assert x_versions[1]["line"] == 1


def test_partition_lineage_uses_split_output_order_not_output_names():
    lineage = analyze_variable_lineage(
        cells("features, test_features, labels, test_labels = train_test_split(X, y)")
    )

    partitions = {
        node["variable"]: node["dataset_partition"]
        for node in lineage["nodes"]
    }
    assert partitions == {
        "features": "train",
        "test_features": "test",
        "labels": "train",
        "test_labels": "test",
    }
    assert next(node for node in lineage["nodes"] if node["variable"] == "labels")[
        "data_role"
    ] == "target"


def test_pre_split_fit_through_alias_is_detected():
    result = analyze_notebook(
        cells(
            "df = pd.read_csv('data.csv')\ndata = df\nX = data[['feature']]",
            "scaler = StandardScaler()\nscaled = scaler.fit_transform(X)",
            "X_train, X_test, y_train, y_test = train_test_split(scaled, y)",
        )
    )

    finding = next(
        item
        for item in result["findings"]
        if item["rule_id"] == "preprocessing_fit_before_split"
    )
    assert finding["evidence_type"] == "static_ast_lineage"
    assert finding["cell_indices"] == [1, 2]
    assert finding["human_confirmation_required"] is True
    assert result["analysis_summary"].startswith("Static inspection")
    assert result["variable_lineage"]["trace_type"] == "static_ast_assignment_lineage"
    trace = build_pipeline_trace(
        result,
        cells(
            "df = pd.read_csv('data.csv')\ndata = df\nX = data[['feature']]",
            "scaler = StandardScaler()\nscaled = scaler.fit_transform(X)",
            "X_train, X_test, y_train, y_test = train_test_split(scaled, y)",
        ),
    )
    assert trace["lineage_nodes"]
