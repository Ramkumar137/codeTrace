# CodeTrace

CodeTrace is an evidence-grounded notebook auditing system for machine-learning workflows. It validates uploaded Jupyter notebooks, extracts structural and source-level signals, reconstructs the ML pipeline from static code patterns, flags supported leakage and evaluation risks, and supports reviewable repair proposals and evidence reporting.

This project is intentionally conservative: it does not execute untrusted notebook code during parsing or analysis, and it treats findings as source-linked evidence rather than absolute proof of runtime defects.

## Why this matters

Data leakage and flawed evaluation are among the most common reasons that ML notebook results look better than they really are. The pattern may be spread across multiple cells, several variable names, and different preprocessing or model-training steps. In practice, reviewers often need help identifying where the issue starts, which operations are connected, and which findings are supported by source evidence versus still uncertain.

CodeTrace helps by giving a structured review workflow around these questions:

- What operations are present in the notebook?
- How are they connected by variable flow?
- Which cells or operations are implicated by a potential issue?
- Is the issue strongly supported or still only a risk signal?
- Can a deterministic repair be proposed without overwriting the original notebook?
- What evidence remains after an approved corrected version is generated and compared?

## Who benefits

CodeTrace is designed for several audiences:

- Data scientists and ML engineers reviewing notebook workflows before reporting results.
- Research teams validating whether preprocessing, splitting, and feature selection are appropriately separated.
- ML reviewers who need source-level evidence without executing untrusted code.
- Students and educators learning to reason about leakage and evaluation design.
- Audit and compliance teams that want a traceable, explainable notebook evidence trail.

## What makes CodeTrace different and novel

CodeTrace is not just a notebook linter or a notebook viewer. Its novelty is the combination of:

- static source-grounded notebook analysis rather than blind execution
- source-linked pipeline reconstruction across ML operations
- graph-based dependency tracing from recognized variable relations
- audit findings that include severity, confidence, evidence, and limitations
- repair proposals that are narrowed to safe, supported patterns only
- separate corrected-notebook generation that preserves the original upload
- isolated execution and verification as explicit follow-on steps rather than implicit trust

This approach is different from generic ML notebook tooling because it emphasizes evidence, traceability, and reviewability rather than generating a broad but untrustworthy warning list.

## Comparison with existing approaches

Common existing approaches in this space often focus on one of the following:

- notebook visualization only
- static linting with generic code-quality checks
- package-specific model checks without explaining notebook workflow context
- runtime execution that executes untrusted code automatically
- report generation without a rigorous source evidence trail

CodeTrace differs by combining these elements in a bounded, review-first workflow:

- It parses notebooks safely and stays static during review.
- It reconstructs an ML pipeline as a graph of operations and dependencies.
- It associates suspected issues with actual source references and variables.
- It avoids claiming a runtime defect when only static source evidence is available.
- It keeps repair generation limited to patterns that can be validated conservatively.
- It separates original, corrected, and execution artifacts so the evidence remains inspectable.

## Architecture overview

```mermaid
flowchart LR
    A[Notebook upload / validation] --> B[Static source analysis]
    B --> C[Operation extraction]
    C --> D[Pipeline graph reconstruction]
    D --> E[Leakage & evaluation audit]
    E --> F[Evidence-backed findings]
    F --> G[Repair classification]
    G --> H[Approved corrected notebook]
    B --> I[Dataset analysis / overlap checks]
    H --> J[Explicit isolated execution]
    J --> K[Verification and comparison]
    K --> L[Evidence report + downloads]

    M[Frontend UI] --> A
    M --> E
    M --> G
    M --> J
    M --> L
```

The frontend remains lightweight and static, while the FastAPI backend handles notebook validation, source analysis, graph assembly, detection, repair generation, execution requests, verification, and report artifacts.

## End-to-end workflow

```mermaid
flowchart TD
    A[Upload notebook] --> B[Validate notebook structure]
    B --> C[Analyze source code]
    C --> D[Extract ML operations and variables]
    D --> E[Build pipeline dependency graph]
    E --> F[Detect leakage and evaluation risks]
    F --> G[Review findings and source evidence]
    G --> H{Repair proposal available?}
    H -->|Yes| I[Review and approve or reject repair]
    I --> J[Generate separate corrected notebook]
    H -->|No| K[Continue with original notebook]
    J --> L[Optionally run isolated experiment]
    K --> L
    L --> M[Verify and compare available evidence]
    M --> N[Generate evidence report and downloads]
    C -. Optional separate CSV upload .-> O[Profile dataset or check train/test overlap]
```

## Current implementation

The repository currently includes:

- notebook upload and validation for Jupyter Notebook v4 files
- source-only static analysis of imports, dataset references, and ML operations
- cross-cell variable lineage for assignments, aliases, versions, and recognized partition/preprocessing flows
- pipeline graph generation from recognized operations and variable dependencies
- supported leakage and evaluation audit rules for notebook source patterns
- objective-aware temporal risk checks and CSV train/test row, identifier, and group overlap checks
- SQLite-backed experiment-history records and repeated test-selection analysis
- narrow deterministic repair proposals where the pattern is safe and supported
- corrected notebook generation that preserves the original upload
- isolated execution support and verification/comparison logic
- evidence report generation in HTML, PDF, and JSON formats
- a synthetic leakage benchmark with JSON results and a readable report

## Project architecture

### Frontend
The frontend is a static HTML, CSS, and JavaScript application. It keeps the existing light CodeTrace theme and exposes notebook upload, overview, pipeline trace, audit review, repair center, experiments, verification, and report views.

### Backend
The backend is a FastAPI application in `backend/app/main.py` and it exposes notebook, dataset, repair, execution, verification, and report endpoints.

### Core services 
### ``backend/app/services/``
- `notebook_parser.py` — validates notebook structure and extracts cell metadata
- `notebook_analyzer.py` — extracts imports, dataset references, operations, and findings
- `variable_lineage.py` — tracks top-level variable versions, aliases, parent variables, and source references across cells
- `temporal_analyzer.py` — flags temporal workflow patterns when the objective or notebook context supports review
- `pipeline_trace.py` — builds the static dependency graph
- `detection_engine.py` — supports source-based evaluation and leakage checks
- `repair_engine.py` — generates narrow deterministic repair proposals
- `dataset_analyzer.py` — profiles CSV inputs without exposing row values
- `dataset_overlap.py` — compares explicitly uploaded train/test datasets and configured entity/group columns
- `experiment_tracker.py` — fingerprints dataset versions and analyzes explicitly recorded experiment history
- `benchmark_evaluator.py` — measures the existing rule-based detector against the enhanced analyzer on synthetic fixtures
- `execution_manager.py` and `backend/app/services/docker_runner.py` — isolate notebook execution
- `verification_engine.py` — compares original and corrected execution artifacts
- `report_service.py` — builds evidence snapshots and exports

## Research features, APIs, and limitations

Notebook findings include rule ID, category, severity, confidence, explanation, source references, affected variables, impact, a suggested correction, and a human-review indicator. Confidence is separate from severity. Findings remain static-source evidence and are not proof that runtime data actually followed the inferred path.

The current analysis supports:

- **Variable lineage:** source-order tracking for recognized top-level assignments, aliases, reassignment versions, and selected preprocessing/split relationships. Branches, dynamic code, mutation through shared references, and runtime execution order are not modeled.
- **Temporal review:** random splitting and ordering, selected shift/rolling and cross-validation patterns are flagged when forecasting is explicit or source context is suggestive. A date column alone is not enough. Timestamp meaning, chronology, and the prediction horizon need human confirmation.
- **Entity/group overlap:** exact-row checks and explicit identifier/group column comparisons are available for two uploaded CSVs. Candidate ID-like columns are suggestions only; group semantics must be confirmed. Reports avoid returning raw overlapping identifiers.
- **Experiment history:** records are persisted with a dataset fingerprint and model/metric/selection metadata. A repeated test-selection warning requires at least two recorded test-data decisions for the same fingerprint. A notebook snapshot or a single final evaluation cannot establish repeated tuning.
- **Repair verification:** the original finding, approved source edits, corrected analysis, and execution evidence are checked independently. `verification_status_normalized` uses `verified`, `partially_verified`, `inconclusive`, or `failed`; the legacy `verification_status` field remains for compatibility. Successful execution alone is not evidence that leakage is absent.

The experiment-history routes require the notebook's access token in the `Authorization` header:

- `POST /api/notebooks/{notebook_id}/experiment-history` records one experiment. Supply `dataset_ids` for associated uploaded datasets or a `dataset_version` label, along with model name, hyperparameters, training/validation/test references, metric, value, and selection decision. The response includes the record, current history, and findings.
- `GET /api/notebooks/{notebook_id}/experiment-history` returns the notebook's records and history analysis.

## Synthetic benchmark

Fixtures in `tests/fixtures/leakage_notebooks/` are synthetic. Run the evaluator from the repository root:

```powershell
python -m backend.app.services.benchmark_evaluator --output-dir benchmark-results
```

This writes `benchmark_results.json` and `benchmark_report.md`. The reported precision/recall/F1 and error rates are fixture-set metrics, not estimates of real-world performance. Repair success measures removal of a targeted static rule and does not execute notebooks. The verification metric is deliberately limited to checking that missing runtime evidence yields an inconclusive result; it is not overall verification accuracy.

## Docker execution security and packages

Execution is explicit and uses the versioned `codetrace-notebook-runner:1.0.0` image by default. The runner disables networking, uses a non-root account, a read-only container filesystem with a bounded writable temporary area, drops Linux capabilities, and applies CPU, memory, process, output, and timeout limits. The application stores a SHA-256 checksum for collected notebook artifacts.

The runner does not install arbitrary per-notebook packages or enable network access. To add packages, build a reviewed custom runner image from `backend/execution/Dockerfile`, pin every package to an exact version (and preferably pin the base image by digest in controlled deployments), rebuild and scan the image, then configure `CODETRACE_EXECUTION_IMAGE` to that fixed tag or digest. Do not mount package caches or enable network access to make installs work at notebook runtime.

## Key workflow principles

- Static analysis first; no notebook execution during upload or parser review.
- Source-linked evidence instead of silent assumptions.
- Separate original and corrected artifacts.
- Reviewable repair proposals rather than automatic rewrite of notebook code.
- Explicit verification after execution, not inference from a passing run alone.

## Safety and limitations

The project is intentionally conservative. It does not claim to be a complete runtime leakage detector, and it does not treat a green graph or a passing repair as proof of safety.

Current limitations include:

- source-only inference, not full runtime tracing
- deterministic repair proposals only for narrowly supported patterns
- ambiguous or context-dependent findings require manual review
- execution verification is only as strong as the captured evidence and comparable conditions


## Summary

CodeTrace is designed as an evidence-first review environment for ML notebooks. Its value is not in pretending to know everything about a notebook from a single static pass, but in providing a transparent, source-linked, reviewable workflow that gives teams structured evidence and safe, bounded actions to take next.
