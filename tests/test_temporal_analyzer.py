from backend.app.services.notebook_analyzer import analyze_notebook
from backend.app.services.temporal_analyzer import analyze_temporal


def cells(*sources):
    return [
        {"index": index, "cell_type": "code", "source": source}
        for index, source in enumerate(sources)
    ]


def test_random_split_is_flagged_for_explicit_forecasting_objective():
    result = analyze_temporal(
        cells("X_train, X_test, y_train, y_test = train_test_split(X, y)"),
        "forecasting",
    )

    rule_ids = {item["rule_id"] for item in result["findings"]}
    assert "random_split_for_forecasting" in rule_ids
    assert "temporal_ordering_missing_before_split" in rule_ids
    assert all(item["human_confirmation_required"] for item in result["findings"])


def test_date_column_alone_does_not_trigger_temporal_finding():
    result = analyze_temporal(
        cells(
            'df["date"] = pd.to_datetime(df["date"])',
            "X_train, X_test, y_train, y_test = train_test_split(X, y)",
        )
    )

    assert result["findings"] == []


def test_markdown_forecasting_context_flags_default_shuffle():
    result = analyze_notebook(
        [
            {"index": 0, "cell_type": "markdown", "source": "Forecasting next-month demand"},
            {"index": 1, "cell_type": "code", "source": "train_test_split(X, y)"},
        ]
    )

    finding = next(
        item
        for item in result["findings"]
        if item["rule_id"] == "random_split_for_forecasting"
    )
    assert finding["confidence"] == "medium"
    assert finding["source_refs"] == [{"cell_index": 1, "line": 1}]


def test_past_only_chronological_split_does_not_emit_random_split_warning():
    result = analyze_temporal(
        cells(
            'df = df.sort_values("date")',
            "X_train, X_test, y_train, y_test = train_test_split(X, y, shuffle=False)",
        ),
        "forecasting",
    )

    assert not any(
        item["rule_id"] in {
            "random_split_for_forecasting",
            "temporal_ordering_missing_before_split",
        }
        for item in result["findings"]
    )


def test_future_shift_centered_rolling_and_kfold_are_reviewed_for_forecasting():
    result = analyze_temporal(
        cells(
            "future_feature = series.shift(-1)",
            "centered = series.rolling(5, center=True).mean()",
            "cv = KFold(n_splits=5, shuffle=True)",
        ),
        "forecasting",
    )

    rule_ids = {item["rule_id"] for item in result["findings"]}
    assert {
        "future_shift_feature",
        "centered_rolling_feature",
        "non_temporal_cross_validation",
    } <= rule_ids
