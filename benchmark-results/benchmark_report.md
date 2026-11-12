# CodeTrace Synthetic Leakage Benchmark

Fixtures: 8 (synthetic only)

| Analyzer | Precision | Recall | F1 | False-positive rate | False-negative rate |
|---|---:|---:|---:|---:|---:|
| Rule-based baseline | 1.0000 | 0.7500 | 0.8571 | 0.0000 | 0.2500 |
| Enhanced analyzer | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 |

## Repair and verification

- Automatic repair success: 2/2 (1.0000).
- No-execution verification guardrail: 2/2 (1.0000) returned the expected inconclusive status.
- This is only the guardrail check that unavailable runtime evidence does not produce a verified result; it is not overall verification accuracy.

## Fixture findings

| Fixture | Expected | Baseline | Enhanced |
|---|---|---|---|
| preprocessing-leakage | preprocessing_fit_before_split | preprocessing_fit_before_split | preprocessing_fit_before_split |
| target-leakage | target_column_in_features | target_column_in_features | target_column_in_features |
| entity-group-overlap | train_test_group_overlap | train_test_group_overlap | train_test_group_overlap |
| temporal-leakage | random_split_for_forecasting, temporal_ordering_missing_before_split | none | random_split_for_forecasting, temporal_ordering_missing_before_split |
| test-set-contamination | test_metric_used_for_model_selection | test_metric_used_for_model_selection | test_metric_used_for_model_selection |
| clean-pipeline | none | none | none |
| multiple-leakage | preprocessing_fit_before_split, target_column_in_features | preprocessing_fit_before_split, target_column_in_features | preprocessing_fit_before_split, target_column_in_features |
| date-column-false-positive | none | none | none |

All fixtures are hand-authored synthetic examples. These metrics measure rule behavior on this small fixture set, not real-world prevalence or generalization. Repair checks are source-only and do not execute notebooks.
