"""Tests for source-evidence leakage and evaluation detection."""

from backend.app.services.notebook_analyzer import analyze_notebook


def analyze(*sources):
    cells = [
        {"index": index, "cell_type": "code", "source": source}
        for index, source in enumerate(sources)
    ]
    return analyze_notebook(cells)


def rule_findings(result, rule_id):
    return [finding for finding in result["findings"] if finding["rule_id"] == rule_id]


def test_pre_split_learned_scaler_is_reported_with_graph_nodes_and_evidence():
    result = analyze(
        "scaler = StandardScaler()\nX_scaled = scaler.fit_transform(X)",
        "X_train, X_test, y_train, y_test = train_test_split(X_scaled, y)",
    )

    finding = rule_findings(result, "preprocessing_fit_before_split")[0]
    assert finding["category"] == "preprocessing_leakage"
    assert finding["classification"] == "potential_risk"
    assert finding["cell_indices"] == [0, 1]
    assert finding["related_pipeline_node_ids"]
    assert any("fit_transform" in evidence["snippet"] for evidence in finding["evidence"])


def test_pipeline_fitted_only_on_training_data_is_not_preprocessing_leakage():
    result = analyze(
        "X_train, X_test, y_train, y_test = train_test_split(X, y)",
        "pipeline = Pipeline([('scale', StandardScaler()), ('model', LogisticRegression())])",
        "pipeline.fit(X_train, y_train)",
    )

    assert not rule_findings(result, "preprocessing_fit_before_split")


def test_transformer_fitted_only_on_training_data_is_not_flagged():
    result = analyze(
        "X_train, X_test = train_test_split(X)",
        "scaler = StandardScaler()\nX_train_scaled = scaler.fit_transform(X_train)",
    )

    assert not rule_findings(result, "preprocessing_fit_before_split")


def test_stateless_transform_before_split_is_not_flagged():
    result = analyze(
        "X_clean = X.fillna(0)",
        "X_train, X_test = train_test_split(X_clean)",
    )

    assert not rule_findings(result, "preprocessing_fit_before_split")


def test_direct_target_column_selection_is_reported():
    result = analyze(
        'y = df["outcome"]\nX = df[["outcome", "age"]]',
        "X_train, X_test, y_train, y_test = train_test_split(X, y)",
    )

    finding = rule_findings(result, "target_column_in_features")[0]
    assert finding["category"] == "target_leakage"
    assert finding["classification"] == "source_evidence"
    assert finding["related_variables"]
    assert len(finding["source_code_evidence"]) == 2


def test_target_variable_used_to_derive_features_is_reported():
    result = analyze(
        "X = pd.concat([feature_frame, y], axis=1)",
        "X_train, X_test, y_train, y_test = train_test_split(features, y)",
    )

    finding = rule_findings(result, "target_variable_in_features")[0]
    assert finding["category"] == "target_leakage"
    assert finding["confidence"] == "medium"


def test_excluding_target_column_is_not_reported_as_direct_inclusion():
    result = analyze(
        'y = df["outcome"]\nX = df.drop(columns=["outcome"])',
        "X_train, X_test, y_train, y_test = train_test_split(X, y)",
    )

    assert not rule_findings(result, "target_column_in_features")


def test_post_outcome_feature_name_is_only_a_low_confidence_suspicion():
    result = analyze("X = df[['age', 'after_outcome_value']]")

    finding = rule_findings(result, "suspicious_outcome_feature")[0]
    assert finding["classification"] == "heuristic_suspicion"
    assert finding["severity"] == "low"
    assert finding["confidence"] == "low"


def test_test_metric_used_for_selection_is_reported():
    result = analyze(
        "score = model.score(X_test, y_test)",
        "if score > best_score:\n    best_score = score",
    )

    finding = rule_findings(result, "test_metric_used_for_model_selection")[0]
    assert finding["category"] == "test_set_contamination"
    assert finding["cell_indices"] == [0, 1]
    assert any("score > best_score" in evidence["snippet"] for evidence in finding["evidence"])


def test_single_final_test_evaluation_is_not_reported_as_selection():
    result = analyze("accuracy = accuracy_score(y_test, model.predict(X_test))")

    assert not rule_findings(result, "test_metric_used_for_model_selection")


def test_classifier_split_without_stratify_is_an_informational_review():
    result = analyze(
        "X_train, X_test, y_train, y_test = train_test_split(X, y)",
        "model = LogisticRegression()\nmodel.fit(X_train, y_train)",
    )

    finding = rule_findings(result, "classification_split_without_stratify_review")[0]
    assert finding["severity"] == "informational"
    assert finding["classification"] == "informational_review"


def test_stratified_classifier_split_does_not_emit_stratification_review():
    result = analyze(
        "X_train, X_test, y_train, y_test = train_test_split(X, y, stratify=y)",
        "model = LogisticRegression()\nmodel.fit(X_train, y_train)",
    )

    assert not rule_findings(result, "classification_split_without_stratify_review")


def test_training_data_evaluation_is_categorized_as_evaluation_flaw():
    result = analyze("model.score(X_train, y_train)")

    finding = rule_findings(result, "evaluation_on_training_data")[0]
    assert finding["category"] == "evaluation_flaw"
    assert finding["related_pipeline_node_ids"]
    assert finding["source_code_evidence"][0]["snippet"] == "model.score(X_train, y_train)"


def test_test_data_model_fit_is_categorized_as_test_contamination():
    result = analyze("model.fit(X_test, y_test)")

    finding = rule_findings(result, "test_data_used_for_fit")[0]
    assert finding["category"] == "test_set_contamination"
    assert finding["source_code_evidence"][0]["snippet"] == "model.fit(X_test, y_test)"


def test_multiple_same_rule_findings_have_unique_ids():
    result = analyze(
        "first.fit(X_test, y_test)\nsecond.fit(X_test, y_test)"
    )

    findings = rule_findings(result, "test_data_used_for_fit")
    assert len(findings) == 2
    assert len({finding["id"] for finding in findings}) == 2


def test_non_ml_notebook_and_ambiguous_source_do_not_fabricate_findings():
    result = analyze("message = 'hello'", "unknown.fit(data, labels)")

    assert result["findings"] == []
