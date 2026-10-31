# CodeTrace

> **Evidence-Grounded Detection of Data Leakage and Evaluation Flaws in Machine Learning Notebooks**

CodeTrace helps investigate whether machine-learning notebook workflows support trustworthy evaluation. It validates `.ipynb` uploads, extracts source and saved cell metadata, and performs bounded static inspection of recognizable ML operations. Its pipeline links and audit findings are potential source-based signals, not runtime facts or proof of leakage.

---

## Problem Statement

Data leakage and flawed ML evaluation practices can make reported model performance misleading. In notebooks, the cause may be distributed across cells—for example, preprocessing fitted before a train/test split or evaluation performed against training data—making manual review difficult. CodeTrace provides source-linked static signals to help inspect such patterns; it does not prove them.

## Motivation

Notebook workflows can accidentally reuse test data for fitting or selection, fit preprocessing using examples later treated as held out, or evaluate on training examples. These mistakes can make metrics look better than performance on new data. The relevant code and variables may span multiple cells, so a useful review needs cell-level evidence and clear uncertainty rather than a context-free warning.

---

## Objectives

The current implementation validates and parses notebooks, identifies a defined set of imports, data references and common ML operations, links recognized operations through explicit shared variable references, and flags a few supported evaluation-risk patterns. The UI presents source-linked operations, audit caveats, cell contents, and a downloadable report. It does not provide comprehensive static analysis or benchmark detection quality.

---

## Feature Status

| Feature | Status |
|---|---|
| FastAPI root endpoint (`GET /`) | Implemented |
| FastAPI health endpoint (`GET /api/health`) | Implemented |
| Automatic API health indicator in brand symbol | Implemented |
| Notebook upload and nbformat v4 validation | Implemented |
| Cell metadata, source, and AST-based operation extraction | Implemented |
| Explicit CSV dataset profiling (shape, inferred types, missingness, numeric summaries) | Implemented; bounded and aggregate-only |
| Source-linked operation graph with inferred variable links | Implemented; partial static-analysis coverage |
| Interactive pipeline dependency map with node/edge inspection and filters | Implemented; static evidence only |
| Evidence-linked checks for preprocessing, target, test-set, and evaluation risks | Implemented; bounded static rules |
| Explicit train/test CSV overlap checks | Implemented; caller supplies both splits and optional identifier/group columns |
| Cell Explorer and downloadable JSON evidence report | Implemented |
| Comprehensive or runtime-verified leakage/data-flow detection | Not implemented |
| Dataset-aware notebook linkage, runtime tracing, and benchmark evaluation | Not implemented |

---

## Technology Stack

| Layer | Technology |
|---|---|
| Frontend | HTML 5, Vanilla CSS, Vanilla JavaScript |
| Backend | Python 3.11+, FastAPI, Uvicorn, nbformat |
| Upload handling | python-multipart |
| Testing | pytest, httpx, pytest-asyncio |
| Environment | Python `venv` |

## Architecture

The application has a static frontend and a FastAPI backend:

- **Frontend:** vanilla HTML, CSS, and JavaScript provide Inspect/About navigation, an automatic health indicator, notebook upload, Overview, Pipeline Trace, Leakage & Evaluation Audit, Cell Explorer, and evidence-report download.
- **API and validation:** `backend/app/main.py` exposes root and health endpoints plus `POST /api/notebooks/upload`. Uploads are bounded to 10 MiB by default, validated, processed in memory, and not saved.
- **Dataset analysis:** `POST /api/datasets/analyze` accepts a separately selected UTF-8 CSV (using the same upload-size limit) and returns aggregate row/column counts, inferred column types, missing-value counts, and numeric summaries. `POST /api/datasets/overlap` accepts explicitly selected training and test CSVs, compares exact rows and optional caller-selected identifier/group columns in memory, and never returns raw values.
- **Notebook parser:** `backend/app/services/notebook_parser.py` checks JSON and nbformat v4 structure and extracts ordered cell source, type, saved execution count, and output presence.
- **Static analyzer:** `backend/app/services/notebook_analyzer.py` uses Python AST without executing source. It extracts recognizable imports, data-read paths, feature transformations, splits, model construction, fitting, prediction, and evaluation operations.
- **Pipeline trace:** `backend/app/services/pipeline_trace.py` converts those extracted operations and audit findings into a stable, source-referenced graph in `notebook.analysis.pipeline_trace`; it does not re-parse or execute notebook code.
- **Detection engine:** `backend/app/services/audit_analyzer.py` retains the initial fit/evaluation source checks; `backend/app/services/detection_engine.py` adds context/dependency-based preprocessing, target, test-selection, and classification-split review rules. Findings carry categories, source evidence, variable and graph references, confidence, severity, recommendations, and limitations.
- **Dataset overlap:** `backend/app/services/dataset_overlap.py` compares two CSV uploads, reports exact duplicated rows and configured identifier/group overlap counts, and does not expose values or persist records.
- **Response models:** `backend/app/models/notebook.py` documents the parsed notebook and nested analysis response.
- **Tests:** pytest tests exercise upload validation, AST extraction, graph links, findings, fallback behavior, and non-execution of untrusted source.

There is no database, permanent file storage, or notebook execution.

## End-to-End Workflow

**Available workflow:** start the API and serve the static frontend. The About page is the default landing page when opened without a route; choose Inspect Notebook when ready to upload. The top navigation stays visible while the rest of the page scrolls. The header symbol checks `/api/health` on load and every 15 seconds. Choose and upload a notebook; after successful validation, the upload form is replaced by a notebook summary and separate navigation buttons for Overview, Pipeline Trace, Leakage & Evaluation Audit, Cell Explorer, and Evidence Report. Each button opens its own focused view rather than appending every section to one long page. Overview shows imported library names, individual imports, notebook dataset path references, recognized operations, and every notebook cell's source in notebook order. It also lets you separately upload a CSV for aggregate dataset profiling; notebook-referenced paths are never opened. Pipeline Trace displays an interactive dependency graph generated from the notebook analysis response. Zoom, pan, fit/reset, operation-type and finding-status filters, node/edge selection, upstream/downstream highlighting, and finding-path highlighting are available. Use Notebook summary to return to the summary, or Choose another notebook to start a fresh upload. The feature pages also show potential audit findings and their evidence, notebook source cells, or a downloadable JSON report.

### Static analysis coverage

The analyzer scans Python code cells independently with `ast.parse`. It recognizes common imports; data readers such as `read_csv` and `read_parquet`; common preprocessing constructors and transforms; common train/test split calls; estimator names ending in `Classifier`, `Regressor`, `Model`, or `Estimator` plus selected common names; `fit`, prediction, and common metric calls. It reports source locations and simple assignment-to-operation relationships where variable identifiers are visible. Markdown is parsed as content, not Python. A syntax-error cell receives limited regex fallback for split, fit, predict, and score calls and is marked as a limitation.

The notebook upload analysis applies the following bounded rules:

| Rule ID | Trigger | Severity / confidence | Classification and limitation |
|---|---|---|---|
| `test_data_used_for_fit` | A recognizable fit operation receives a test-named variable | High / high | Potential risk; names do not prove the variable's contents or intent. |
| `evaluation_on_training_data` | A metric/score operation receives a train-named variable | Medium / medium | Training-set scoring can be intentional; source does not establish purpose. |
| `preprocessing_fit_before_split` | A recognized learned transform's fitted output or input is source-linked to a later split | Medium / medium | Potential risk; source order and variable links do not prove runtime rows. Stateless transforms and constructors alone are not flagged. |
| `target_column_in_features` | A literal feature-column selection matches the literal column used to construct the split target | High / high | Direct source evidence, not proof of actual dataframe contents or modeling intent. |
| `target_variable_in_features` | A feature assignment directly depends on the target argument supplied to a recognized split | High / medium | Static dependency may not mean target values are present at runtime. |
| `suspicious_outcome_feature` | A selected feature name matches a narrow post-outcome/future-name pattern | Low / low | Heuristic suspicion only; domain meaning is unknown. |
| `test_metric_used_for_model_selection` | A metric on test-named input is reused in a later `if`/`while` condition | High / medium | Potential contamination; intent and runtime branch behavior are unknown. Repeated final metrics alone are not flagged. |
| `classification_split_without_stratify_review` | A source-linked split feeds a recognized classifier and omits `stratify=` | Informational / low | Review prompt only; the engine does not know class balance or whether stratification is appropriate. |

### Explicit CSV dataset analysis

The Overview page can separately submit a `.csv` file to `POST /api/datasets/analyze`. The API decodes UTF-8 (including a BOM), parses comma-delimited records for the request, ignores blank records, and returns row/column counts plus one profile per column: inferred `boolean`, `integer`, `number`, `text`, or `empty` type; non-empty and missing-value counts; missing-value percentage; and, for numeric columns, count/minimum/maximum/mean. Numeric summary values are strings to preserve decimal representation. The response does not include dataset rows or sample values, and uploaded data is not retained in application storage. Non-empty rows must match the header width and header names must be non-empty and unique. CSV uploads use the same configurable 10 MiB limit as notebooks. The implementation uses Python's standard-library CSV parser and adds no dependency.

This is bounded, descriptive profiling rather than a full data-quality or ML-target analysis. Inferred types are heuristic; no categorical distributions, relationships, labels, or leakage conclusions are derived from dataset values. Dataset paths in notebook code remain informational and are never opened.

### Explicit train/test overlap checks

The Leakage & Evaluation Audit page can submit two separately selected CSV files to `POST /api/datasets/overlap`. The endpoint accepts multipart fields `train_file`, `test_file`, and optional `identifier_column` and `group_column`. It checks exact full-row matches when both files have the same column names (column order may differ), and compares only configured non-empty identifier/group values across the files. A missing configured column is an explicit validation error. If schemas differ, full-row comparison is marked skipped rather than reported as a successful check; configured identifiers can still be checked when present in both files.

The response contains overlap counts, filenames, check status, caveats, and findings, but never overlapping values. Exact duplicate feature rows are not treated as proof of same-person leakage. Identifier/group findings depend on the caller's column semantics. Both files are bounded by the existing per-file upload limit, processed in memory, and discarded after the request. This check is not automatically joined to notebook graph nodes because the dataset files are supplied separately and notebooks are not persisted.

### Finding evidence and interpretation

Notebook findings are generated from the already parsed cell AST, extracted operation arguments, and Phase 2 dependency graph; detection does not execute code or load referenced paths. Each finding includes a unique `id`, stable `rule_id`, category, severity, confidence, classification, source references/snippets, related variables, related pipeline node IDs, explanation, recommendation, and detection limitations. Dataset overlap findings use dataset evidence and intentionally have no notebook cell or graph node.

`source_evidence` means the source directly shows a suspicious construction; `potential_risk` means data semantics or intent remain uncertain; `heuristic_suspicion` means a name-based signal requiring manual review; `informational_review` is not a defect finding. High/medium/low confidence describes evidence support rather than probability. Informational severity is a review prompt. No current rule claims a runtime-confirmed defect, so graph findings remain amber rather than red.

### Graph contract and interpretation

`notebook.analysis.pipeline_graph` contains:

- `nodes`: stable node ID, operation kind/label, cell index, line, source snippet, static evidence label, and source reference.
- `edges`: source and target node IDs, shared variable, `inferred_from_variable_reference` relationship, static-AST evidence, and source references.
- `unresolved_references`: input identifiers without an earlier recognized producer and an explicit reason/source reference.
- `limitations` and `trace_type: "static_inference_not_runtime_trace"`.

Edges indicate only that recognized source operations reference a variable produced by an earlier recognized operation. They are inferences, not observed runtime transfers. Nodes without links remain disconnected. Notebook order, saved execution counts, and output presence are not runtime tracing.

The analyzer also retains the earlier `pipeline_graph` field for compatibility. The current Pipeline Trace interface is generated from `notebook.analysis.pipeline_trace` as described below; neither graph is a runtime trace.

### Interactive pipeline dependency map

The upload response also includes `notebook.analysis.pipeline_trace`, generated from the existing `all_operations` and `findings` by `backend/app/services/pipeline_trace.py`. The graph is built independently of rendering and is consumed by the Pipeline Trace workspace; no notebook-ID endpoint is needed because uploaded notebooks are not persisted.

Each node has a stable operation ID, operation type and label, operation name, cell/line source reference and source snippet, input/output variables, saved execution count when available, finding IDs, and evidence/status fields. Recognized types include dataset loading, data cleaning, missing-value handling, encoding, scaling, feature engineering/selection, train-test split, model initialization/training, prediction, and evaluation. Generic preprocessing and unclassified operations are retained when the analyzer recognized them, rather than inventing a more specific type.

Directed edges are created only where an input variable matches an earlier recognized output, or where the AST explicitly nests an estimator in a recognized `Pipeline`, `make_pipeline`, `make_union`, or `ColumnTransformer`. Each edge carries stable identity, connecting variables (when applicable), an explanation, evidence reference, relationship kind, and dependency confidence. Source order is only used to identify an earlier assignment; it is not proof of runtime execution or data transfer. Unknown inputs are listed as unresolved instead of being connected by guesswork. This supports branches, multiple models, shared preprocessing, and multiple datasets when the extracted variable references establish those relationships.

The SVG UI supports zoom, pan, fit/reset, node-type and finding-presence filters, node/edge selection, connected upstream/downstream highlighting, and finding-path highlighting. Node details show source code, variables, neighboring operations, execution metadata, evidence status, and associated findings. Edge details show endpoints, connecting variables, relationship support, and the dependency explanation. Status colors are scoped to evidence at the referenced operation: green means no supported issue was detected there, amber means a potential finding is associated, red is reserved for explicit confirmation, and grey indicates fallback or insufficient evidence. Existing audit rules produce potential findings, so they do not currently produce red nodes. Findings attach only to cited source locations, not automatically to downstream nodes. A green node is not a safety guarantee.

Graph generation remains bounded by the static analyzer: dynamic aliases, control flow, runtime ordering, repeated assignments/execution, generated code, and library-specific semantics may be missed. Nodes and edges are limited to operations and dependencies that the analyzer actually extracts. An empty graph means no supported operation was detected, not that the notebook has no ML workflow.

### Response and safety boundaries

Success retains the existing `status` and `notebook` fields and adds `notebook.analysis` containing `imports`, `libraries`, `dataset_references`, grouped `operations`, `all_operations`, `pipeline_graph`, `findings`, confidence/severity definitions, a summary, and limitations. Dataset references are extracted strings only. No referenced path or URL is accessed.

Example analysis fragment:

```json
{
  "analysis": {
    "libraries": ["pandas", "sklearn"],
    "dataset_references": [
      {"path": "data.csv", "cell_index": 0, "line": 2, "operation": "read_csv", "inferred": true}
    ],
    "pipeline_graph": {
      "nodes": [],
      "edges": [],
      "unresolved_references": [],
      "limitations": [
        "Results are static-source inferences, not runtime observations.",
        "Notebook order and saved execution counts do not establish execution order.",
        "Variable aliases, dynamic dispatch, generated code, and complex data flow may not be resolved.",
        "Control-flow branches and repeated variable assignments are not modeled.",
        "Dataset paths and URLs are reported as source references; no data is loaded or contacted.",
        "Potential findings require human review and do not prove leakage or invalid evaluation.",
        "Target leakage checks cover only literal target-column/variable dependencies and a narrow suspicious-name heuristic.",
        "No explicit variable-reference dependencies between recognized operations were established."
      ],
      "trace_type": "static_inference_not_runtime_trace"
    },
    "pipeline_trace": {
      "metadata": {
        "trace_type": "static_source_dependency_graph",
        "node_count": 0,
        "edge_count": 0,
        "runtime_verified": false
      },
      "nodes": [],
      "edges": [],
      "findings": [],
      "unresolved_references": []
    },
    "findings": []
  }
}
```

The actual response returns the complete parsed notebook and the analysis metadata, both graph representations, findings, confidence/severity definitions, and limitations.

Notebook code is never executed, imported, or evaluated. Binary outputs are omitted. The frontend inserts notebook-controlled strings as text, not HTML, and does not persist notebook contents in browser storage. Findings are source-grounded signals for human review, not runtime-confirmed defects. Static analysis cannot establish runtime execution, actual data values, target-derived feature leakage generally, dynamic aliases/control flow, indirect test-set reuse, generated code, or all library-specific behavior. False negatives are possible; no detection benchmark is provided.

---

## Project Structure

```text
CodeTrace/
├── frontend/
│   ├── index.html          # Inspect/About navigation and notebook workspace
│   ├── css/
│   │   └── style.css       # Responsive light theme
│   └── js/
│       └── app.js          # Health, upload, workspace, and report UI
├── backend/
│   └── app/
│       ├── main.py         # FastAPI health, notebook, and dataset endpoints
│       ├── services/
│       │   ├── notebook_parser.py # nbformat validation and extraction
│   │   ├── notebook_analyzer.py # AST metadata and pipeline operations
│   │   ├── pipeline_trace.py # Source-evidence dependency graph builder
│       │   ├── detection_engine.py # Notebook leakage/evaluation rules
│       │   ├── dataset_overlap.py # Explicit train/test CSV comparison
│       │   ├── audit_analyzer.py # Initial source-pattern audit rules
│       │   └── dataset_analyzer.py # Explicit CSV profiling
│       ├── api/            # Package scaffold
│       ├── analyzers/      # Package scaffold
│       └── models/
│           ├── notebook.py # Notebook upload response models
│           └── dataset.py  # CSV analysis response models
├── tests/
│   ├── test_main.py        # Health endpoint tests
│   ├── test_notebook_upload.py # Upload validation tests
│   ├── test_notebook_analyzer.py # Static analysis tests
│   ├── test_detection_engine.py # Leakage/evaluation rule tests
│   ├── test_pipeline_trace.py # Pipeline graph shape/dependency tests
│   ├── test_dataset_analysis.py # CSV profile tests
│   └── test_dataset_overlap.py # Train/test overlap tests
├── testing/
│   ├── clean_ml_workflow.ipynb
│   ├── mixed_cells_syntax_fallback.ipynb
│   ├── preprocessing_before_split.ipynb
│   ├── sample_dataset.csv
│   ├── sample_notebook.ipynb
│   ├── test_data_fit_risk.ipynb
│   ├── test_split_overlap.csv
│   ├── train_split_overlap.csv
│   └── training_data_evaluation_risk.ipynb
├── .gitignore
├── requirements.txt
├── README.md
└── completion.md
```

---

## Prerequisites

- Python 3.11 or later (project target; the current test environment uses Python 3.13.14) — <https://www.python.org/downloads/>
- Git — <https://git-scm.com/>
- A modern browser (Chrome, Firefox, Edge)
- (Optional) VS Code with the Live Server extension for serving the frontend

---

## Setup

### 1. Clone the repository

```bash
git clone <repository-url>
cd CodeTrace
```

### 2. Use the project virtual environment

**Windows PowerShell:**

```powershell
.\venv\Scripts\Activate.ps1
```

The project already uses a virtual environment named `venv`; do not recreate it. For a fresh checkout only, create it first with `python -m venv venv`.

> If PowerShell blocks the activation script, run this once in your user account:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

**macOS / Linux:**

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

## Running the Application

### Start the backend (Terminal 1)

```powershell
.\venv\Scripts\Activate.ps1
uvicorn backend.app.main:app --reload
```

The API will be available at `http://127.0.0.1:8000`. From the project root, `.\venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload` uses the existing Windows virtual environment without requiring activation.

| Method and path | Description | Response |
|---|---|---|
| `GET /` | Confirms the API is running | `{"status":"ok","message":"CodeTrace API is running."}` |
| `GET /api/health` | Health check consumed by the frontend | `{"status":"healthy","service":"CodeTrace API"}` |
| `POST /api/notebooks/upload` | Validates and statically inspects one notebook | Notebook summary, source-only cell metadata, analysis, graph, and potential findings |
| `POST /api/datasets/analyze` | Profiles one explicitly uploaded CSV for the request | Dataset dimensions and aggregate per-column profile; no row values |
| `POST /api/datasets/overlap` | Compares explicitly uploaded train/test CSVs | Exact-row and configured identifier/group overlap counts; no row values |

The upload endpoints do not authenticate callers and do not retain uploaded files. FastAPI's interactive documentation is available at `http://127.0.0.1:8000/docs` while the local server is running.

**Expected response from `GET /api/health`:**

```json
{
  "status": "healthy",
  "service": "CodeTrace API"
}
```

### Uploading a notebook

Send one multipart form field named `file` containing a `.ipynb` file. The browser frontend uses `FormData` and leaves the multipart content type to the browser so it can include the boundary.

The maximum size defaults to 10 MiB (10 × 1024 × 1024 bytes). Configure it in bytes with `CODETRACE_MAX_UPLOAD_SIZE_BYTES`; for example:

```powershell
$env:CODETRACE_MAX_UPLOAD_SIZE_BYTES = "20971520"
.\venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

The endpoint rejects missing files and filenames (400), empty files (400), invalid JSON or text (400), unsupported extensions (415), files over the configured size (413), invalid notebook structures (422), and notebook format versions other than 4 (422). Errors include a structured `detail` object with a stable `code` and readable `message`:

```json
{
  "detail": {
    "code": "unsupported_file_type",
    "message": "Only files with the .ipynb extension are accepted."
  }
}
```

On success, `format_version` is the integer in the notebook's `nbformat` field (the major format version). Counts are computed from all cells. Each cell includes its zero-based notebook index, type, source, execution count for code cells when available, and a `has_outputs` boolean. Notebook order is not a claim about runtime order; saved execution counts are metadata only. Output payloads, including embedded images, are never returned.

Example success response:

```json
{
  "status": "success",
  "notebook": {
    "filename": "example.ipynb",
    "format_version": 4,
    "total_cells": 2,
    "code_cells": 1,
    "markdown_cells": 1,
    "raw_cells": 0,
    "cells": [
      {
        "index": 0,
        "cell_type": "markdown",
        "source": "# Notes",
        "execution_count": null,
        "has_outputs": false
      },
      {
        "index": 1,
        "cell_type": "code",
        "source": "value = 1",
        "execution_count": 1,
        "has_outputs": false
      }
    ],
    "analysis": {
      "imports": [],
      "libraries": [],
      "dataset_references": [],
      "operations": {
        "data_source": [],
        "feature_engineering": [],
        "preprocessing": [],
        "split": [],
        "model": [],
        "training": [],
        "prediction": [],
        "evaluation": []
      },
      "all_operations": [],
      "pipeline_graph": {
        "nodes": [],
        "edges": [],
        "unresolved_references": [],
        "limitations": ["Results are static-source inferences, not runtime observations."],
        "trace_type": "static_inference_not_runtime_trace"
      },
      "findings": [],
      "confidence_definitions": {
        "high": "The source directly contains the flagged call and a recognizable risky argument.",
        "medium": "The source contains a recognizable pattern, but its data semantics are uncertain.",
        "low": "A source-text fallback suggests a pattern that could not be confirmed by Python AST parsing."
      },
      "severity_definitions": {
        "high": "A direct source-pattern concern that should be reviewed promptly; it is not proof of a runtime defect.",
        "medium": "A recognizable pattern with important uncertainty about data contents or execution context.",
        "low": "A weak or fallback-only signal; review manually before drawing conclusions."
      },
      "analysis_summary": "Static inspection identified 0 recognizable operation(s) and 0 potential audit finding(s). Results are source-based inferences.",
      "limitations": [
        "Results are static-source inferences, not runtime observations.",
        "Notebook order and saved execution counts do not establish execution order.",
        "Variable aliases, dynamic dispatch, generated code, and complex data flow may not be resolved.",
        "Control-flow branches and repeated variable assignments are not modeled.",
        "Dataset paths and URLs are reported as source references; no data is loaded or contacted.",
        "Potential findings require human review and do not prove leakage or invalid evaluation.",
        "Target-derived feature leakage and context-dependent test-set reuse are not automatically classified.",
        "No explicit variable-reference dependencies between recognized operations were established."
      ]
    }
  }
}
```

The parser uses `nbformat.reads(..., as_version=nbformat.NO_CONVERT)` and `nbformat.validate`. It supports Jupyter Notebook format v4 and does not execute, evaluate, import, or otherwise run cell source. On successful responses, the backward-compatible notebook fields are extended with `analysis`: extracted imports/libraries and data references; grouped and ordered operations with cell/line/source references; a static-inference graph; supported potential-risk findings; and confidence, severity, and limitation definitions.

CSV analysis is a separate explicit upload. It does not follow or open paths extracted from a notebook, and it does not persist the CSV or return individual values.

### Serve the frontend (Terminal 2)

**Option A – VS Code Live Server (recommended):**

1. Open the project in VS Code.
2. Right-click `frontend/index.html` → **Open with Live Server**.
3. The page opens at `http://127.0.0.1:5500`.

**Option B – Python's built-in HTTP server:**

```powershell
cd frontend
..\venv\Scripts\python.exe -m http.server 5500
```

Then open `http://127.0.0.1:5500` in your browser.

> Opening `index.html` directly as a `file://` URL also works because `"null"` is included in the CORS allowed-origins list.

---

## Running Tests

```powershell
.\venv\Scripts\python.exe -m pytest tests\ -v
```

The tests cover the root and health endpoints, notebook and CSV upload validation, CSV schema/type/missingness/numeric summaries, source-only overlap comparison, AST extraction, graph links, leakage/evaluation rules, clean and flawed examples, parse fallback, and non-execution of suspicious notebook source. Run the suite to see current results.

---

## Manual Verification

1. Start the backend with `uvicorn backend.app.main:app --reload`.
2. Open `http://127.0.0.1:8000/api/health` in a browser — you should see the JSON health response.
3. Open the frontend page in a browser.
4. Wait for the `</>` symbol in the header to turn green after the health check succeeds.
5. Upload `testing/sample_notebook.ipynb` or another valid notebook.
6. In Overview, optionally upload `testing/sample_dataset.csv` to review its measured row count, column types, missing values, and numeric summaries.
7. In Leakage & Evaluation Audit, optionally upload separate training/test CSV files and configure identifier/group columns for overlap checks.
8. Review Pipeline Trace, Leakage & Evaluation Audit, and Cell Explorer. Confirm graph links are labeled as inferred and source is shown as text.
9. Download the evidence report and inspect its notebook details, notebook and dataset findings, graph, definitions, and limitations.
10. Stop the backend — within the next health check, the symbol should turn red. An upload attempt should show a connection error.

---

## Limitations

- Only nbformat v4 JSON notebooks up to the configured size limit can be uploaded. Files are held in request memory and are not persisted.
- AST analysis covers common Python syntax and selected patterns. Syntax-error cells receive a limited source-text fallback or remain unresolved.
- Variable-name matches do not prove value relationships. Control flow, branches, dynamic aliases, reassignment semantics, and target-derived feature leakage are not comprehensively analyzed.
- Audit results require human review. Exact row duplicates are not proof of same-entity overlap; identifier semantics depend on user configuration. No labeled benchmark or measured precision/recall is available.
- Notebook-referenced datasets are not loaded. CSV profiling is aggregate-only; overlap analysis compares only separately uploaded split files and does not infer notebook-to-file correspondence. Saved notebook output payloads are omitted and notebook code is never executed.
- The frontend API base URL is configured in `frontend/js/app.js`.
- CORS origins are intended for local development, including the `null` origin for locally opened files; this configuration is not a production security policy.
- No database, authentication, deployment configuration, or production hardening is provided.

## Research Evaluation

No benchmark dataset, annotation protocol, baseline comparison, or measured detection result has been produced yet. A future evaluation should use a documented, labeled set of notebooks, define annotation criteria for each target pattern, and report precision, recall, and F1 with error analysis. Any results should be compared with a stated baseline and should distinguish syntactic matches from cases requiring contextual interpretation. This is an evaluation recommendation, not a completed or implemented capability.

---

## License

To be decided at a later stage.
