"""Tests for source-evidence pipeline graph generation."""

from backend.app.services.notebook_analyzer import analyze_notebook
from backend.app.services.pipeline_trace import build_pipeline_trace


def graph_for(*sources):
    cells = [
        {
            "index": index,
            "cell_type": "code",
            "source": source,
            "execution_count": index + 3,
        }
        for index, source in enumerate(sources)
    ]
    analysis = analyze_notebook(cells)
    return build_pipeline_trace(analysis, cells), analysis


def node_by_name(graph, name):
    return next(node for node in graph["nodes"] if node["operation_name"] == name)


def test_simple_ml_workflow_uses_real_variable_dependencies_and_metadata():
    graph, _ = graph_for(
        'df = pd.read_csv("train.csv")',
        'X = df[["feature"]]\ny = df["label"]',
        "X_train, X_test, y_train, y_test = train_test_split(X, y)",
        "model = RandomForestClassifier()\nmodel.fit(X_train, y_train)",
        "predictions = model.predict(X_test)\naccuracy_score(y_test, predictions)",
    )

    assert {
        node["operation_type"] for node in graph["nodes"]
    } >= {
        "dataset_loading",
        "feature_engineering",
        "train_test_split",
        "model_initialization",
        "model_training",
        "prediction",
        "model_evaluation",
    }
    split = node_by_name(graph, "train_test_split")
    training = node_by_name(graph, "fit")
    assert split["cell_index"] == 2
    assert training["execution_count"] == 6
    assert {"X_train", "y_train"} <= set(training["input_variables"])
    assert any(
        edge["source"] == split["id"] and edge["target"] == training["id"]
        and {"X_train", "y_train"} <= set(edge["variables"])
        for edge in graph["edges"]
    )
    assert all(edge["id"] for edge in graph["edges"])
    assert all(edge["relationship"] == "direct_variable_reference" for edge in graph["edges"])


def test_pre_split_scaling_finding_is_only_attached_to_evidence_locations():
    graph, analysis = graph_for(
        "scaler = StandardScaler()",
        "X_scaled = scaler.fit_transform(X)",
        "X_train, X_test, y_train, y_test = train_test_split(X_scaled, y)",
    )

    finding = analysis["findings"][0]
    attached = [node for node in graph["nodes"] if finding["id"] in node["finding_ids"]]
    assert {node["operation_name"] for node in attached} == {
        "fit_transform",
        "train_test_split",
    }
    assert all(node["status"] == "amber" for node in attached)
    assert all(node["status"] != "amber" for node in graph["nodes"] if node not in attached)


def test_sklearn_pipeline_records_explicit_component_composition():
    graph, _ = graph_for(
        "pipeline = Pipeline(["
        "('scale', StandardScaler()), "
        "('model', LogisticRegression())"
        "])",
        "pipeline.fit(X_train, y_train)",
    )

    pipeline = node_by_name(graph, "Pipeline")
    components = [
        node for node in graph["nodes"]
        if node["operation_name"] in {"StandardScaler", "LogisticRegression"}
    ]
    composition_edges = [
        edge for edge in graph["edges"]
        if edge["relationship"] == "explicit_pipeline_composition"
    ]
    assert len(components) == 2
    assert {edge["source"] for edge in composition_edges} == {
        node["id"] for node in components
    }
    assert all(edge["target"] == pipeline["id"] for edge in composition_edges)


def test_multiple_models_branch_from_same_training_split():
    graph, _ = graph_for(
        "X_train, X_test, y_train, y_test = train_test_split(X, y)",
        "first = LogisticRegression()\nsecond = RandomForestClassifier()",
        "first.fit(X_train, y_train)\nsecond.fit(X_train, y_train)",
    )

    split = node_by_name(graph, "train_test_split")
    training_nodes = [node for node in graph["nodes"] if node["operation_type"] == "model_training"]
    assert len(training_nodes) == 2
    assert all(
        any(edge["source"] == split["id"] and edge["target"] == training["id"] for edge in graph["edges"])
        for training in training_nodes
    )


def test_parallel_scaling_branches_do_not_connect_to_each_other():
    graph, _ = graph_for(
        "X = make_features(raw)",
        "left_scaler = StandardScaler()\nright_scaler = MinMaxScaler()",
        "X_left = left_scaler.fit_transform(X)\n"
        "X_right = right_scaler.fit_transform(X)",
    )

    scaler_operations = {"StandardScaler", "MinMaxScaler"}
    left = node_by_name(graph, "fit_transform")
    assert sum(node["operation_type"] == "data_scaling" for node in graph["nodes"]) == 4
    assert all(
        not (
            graph_node["operation_type"] == "data_scaling"
            and graph_node["id"] != left["id"]
            and any(
                edge["source"] == left["id"] and edge["target"] == graph_node["id"]
                for edge in graph["edges"]
            )
        )
        for graph_node in graph["nodes"]
    )
    assert scaler_operations <= {
        node["operation_name"] for node in graph["nodes"]
    }


def test_multiple_datasets_remain_separate_until_code_joins_them():
    graph, _ = graph_for(
        'left = pd.read_csv("left.csv")\nright = pd.read_csv("right.csv")',
        "left_features = left[['a']]\nright_features = right[['b']]",
    )

    left_load = next(node for node in graph["nodes"] if node["source"].endswith('"left.csv")'))
    right_load = next(node for node in graph["nodes"] if node["source"].endswith('"right.csv")'))
    left_feature = next(node for node in graph["nodes"] if node["operation_name"] == "left_features")
    right_feature = next(node for node in graph["nodes"] if node["operation_name"] == "right_features")
    assert any(edge["source"] == left_load["id"] and edge["target"] == left_feature["id"] for edge in graph["edges"])
    assert any(edge["source"] == right_load["id"] and edge["target"] == right_feature["id"] for edge in graph["edges"])
    assert not any(
        edge["source"] == left_load["id"] and edge["target"] == right_feature["id"]
        for edge in graph["edges"]
    )


def test_unknown_inputs_are_not_guessed_and_node_status_is_grey():
    graph, _ = graph_for("model.fit(unknown_train, unknown_labels)")

    training = node_by_name(graph, "fit")
    assert training["status"] == "grey"
    assert not graph["edges"]
    assert {item["variable"] for item in graph["unresolved_references"]} >= {
        "model",
        "unknown_train",
        "unknown_labels",
    }


def test_non_ml_notebook_produces_an_honest_empty_graph():
    graph, _ = graph_for("message = 'hello'", "print(message)")

    assert graph["nodes"] == []
    assert graph["edges"] == []
    assert graph["metadata"]["node_count"] == 0


def test_syntax_fallback_is_grey_and_keeps_source_reference():
    graph, _ = graph_for("model.fit(X_train, y_train\n")

    assert len(graph["nodes"]) == 1
    assert graph["nodes"][0]["status"] == "grey"
    assert graph["nodes"][0]["evidence_status"] == "source_text_fallback"
    assert graph["nodes"][0]["source_ref"] == {"cell_index": 0, "line": 1}


def test_findings_use_amber_unless_explicitly_confirmed():
    graph, _ = graph_for("model.fit(X_test, y_test)")

    training = node_by_name(graph, "fit")
    assert training["finding_ids"] == ["test_data_used_for_fit"]
    assert training["status"] == "amber"
    assert not any(node["status"] == "red" for node in graph["nodes"])
