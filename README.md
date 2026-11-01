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
| Notebook upload, nbformat v4 validation, and safe kernel/language metadata display | Implemented; arbitrary notebook metadata is not exposed |
| Cell metadata, source, and AST-based operation extraction | Implemented |
| Explicit CSV dataset profiling (shape, inferred types, missingness, numeric summaries) | Implemented; bounded and aggregate-only |
| Source-linked operation graph with inferred variable links | Implemented; partial static-analysis coverage |
| Interactive pipeline dependency map with node/edge inspection and filters | Implemented; static evidence only |
| Evidence-linked checks for preprocessing, target, test-set, and evaluation risks | Implemented; bounded static rules |
| Explicit train/test CSV overlap checks | Implemented; caller supplies both splits, optional identifier/group columns, and the evaluation objective |
| Deterministic repair proposals and separately generated corrected notebooks | Implemented for narrow, validated preprocessing and literal target-column patterns |
| Static analysis of approved corrected notebook versions | Implemented; corrected graph is source-derived and separate from original findings |
| User approval/rejection before repair generation | Implemented in the Repair Center; decisions remain in the current browser session |
| Explicit original/corrected notebook experiments | Implemented; each run has a separate execution ID and Docker container |
| Explicit paired run using the same attached dataset IDs | Implemented after a corrected notebook is generated from approved repair evidence |
| Offline, resource-limited notebook execution | Implemented with Docker-only isolation; unavailable when Docker or the runner image is unavailable |
| Persisted execution status, cell outputs/errors, package metadata, and executed notebook artifact | Implemented in SQLite; capability-token authorized |
| Persisted paired experiment metadata and side-by-side results | Implemented; reports both execution states, captured metrics, logs, setup, and verification evidence |
| Repair verification using stored approved repairs and original/corrected execution records | Implemented with per-finding evidence, statuses, and limitations; does not infer success from execution alone |
| Original/corrected metric comparison | Implemented for explicitly labeled output metrics when datasets and recorded model, split protocol, seed, runtime, and relevant package settings match; repair-related feature-expression changes are documented |
| Cell Explorer and persisted HTML, PDF, and JSON evidence reports | Implemented from stored CodeTrace records; partial workflows are labeled |
| Objective-aware group-overlap visualization | Implemented for explicitly uploaded split CSVs with temporary anonymized entity labels; does not claim notebook execution assignments or rewrite notebook split code |
| Comprehensive or runtime-verified leakage/data-flow detection | Not implemented |

---

## Technology Stack

| Layer | Technology |
|---|---|
| Frontend | HTML 5, Vanilla CSS, Vanilla JavaScript |
| Backend | Python 3.11+, FastAPI, Uvicorn, nbformat, SQLite |
| Report exports | ReportLab 4.4.4 for PDF; generated HTML and JSON use the Python standard library |
| Isolated execution | Docker, Python 3.12 runner image, nbclient, ipykernel |
| Upload handling | python-multipart |
| Testing | pytest, httpx, pytest-asyncio |
| Environment | Python `venv` |

## Architecture

The application has a static frontend and a FastAPI backend:

- **Frontend:** vanilla HTML, CSS, and JavaScript provide Inspect/About navigation, an automatic health indicator, notebook upload, Overview, Pipeline Trace, Leakage & Evaluation Audit, Repair Center, Experiments, Verification, Cell Explorer, and Reports.
- **API and validation:** `backend/app/main.py` exposes root and health endpoints plus notebook, dataset, repair, and execution APIs. Notebook and explicitly associated dataset bytes are persisted for experiments; the separate CSV profile and overlap APIs remain request-scoped.
- **Dataset analysis:** `POST /api/datasets/analyze` accepts a separately selected UTF-8 CSV (using the same upload-size limit) and returns aggregate row/column counts, inferred column types, missing-value counts, and numeric summaries. `POST /api/datasets/overlap` accepts explicitly selected training and test CSVs, compares exact rows and optional caller-selected identifier/group columns in memory, and never returns raw values.
- **Notebook parser:** `backend/app/services/notebook_parser.py` checks JSON and nbformat v4 structure and extracts ordered cell source, type, saved execution count, and output presence. The Overview displays only whitelisted kernel and language fields from standard notebook metadata, not arbitrary metadata.
- **Static analyzer:** `backend/app/services/notebook_analyzer.py` uses Python AST without executing source. It extracts recognizable imports, data-read paths, feature transformations, splits, model construction, fitting, prediction, and evaluation operations.
- **Pipeline trace:** `backend/app/services/pipeline_trace.py` converts those extracted operations and audit findings into a stable, source-referenced graph in `notebook.analysis.pipeline_trace`; it does not re-parse or execute notebook code.
- **Corrected-version trace:** `GET /api/notebooks/{notebook_id}/versions/{version_id}/analysis` re-runs static analysis over an authorized stored notebook version. The UI can switch between the original and approved corrected graph; original findings and repair evidence stay anchored to the uploaded notebook.
- **Detection engine:** `backend/app/services/audit_analyzer.py` retains the initial fit/evaluation source checks; `backend/app/services/detection_engine.py` adds context/dependency-based preprocessing, target, test-selection, and classification-split review rules. Findings carry categories, source evidence, variable and graph references, confidence, severity, recommendations, and limitations.
- **Repair engine:** `backend/app/services/repair_engine.py` classifies each notebook finding and creates deterministic proposals only for a narrowly recognized train/test preprocessing rewrite or direct literal target-column selection. The Repair Center shows original/proposed code, changes, evidence-based limitations, and validation; users must approve each proposal before a separate corrected notebook can be downloaded.
- **Execution persistence and orchestration:** `backend/app/services/execution_store.py` stores notebook versions, explicitly associated CSVs, experiment status, bounded cell outputs, metadata, logs, and executed-notebook artifacts in SQLite under `CODETRACE_DATA_DIR` (default: `~/.codetrace`). Upload responses issue a random per-notebook bearer capability; only its hash is stored. The token stays in browser memory and is required for dataset association, corrected notebook creation, execution, status, cancellation, and artifact download.
- **Paired experiments:** the paired-run API stores one pair record linking an original run and an approved corrected run. Both execute independently through the same Docker manager with the same selected associated dataset IDs. After both executions become terminal, fetching the pair finalizes and persists verification with the existing evidence engine. Neither a score change nor successful execution alone marks a repair verified.
- **Repair verification and comparison:** `backend/app/services/verification_engine.py` evaluates only the approved repair manifest persisted with a corrected notebook and the selected original/corrected execution records. It re-analyzes both stored notebook versions, checks approved cell changes and category-specific source patterns, persists immutable verification records, and extracts only explicitly labeled numeric metrics from completed captured outputs. Metric deltas are available only when explicit datasets and extractable model/split/random-seed, Python, and relevant package settings match; otherwise values are shown without deltas and the reasons are recorded.
- **Evidence reports:** `backend/app/services/report_service.py` rebuilds source analysis from the authorized persisted original notebook, associates only its stored corrected versions, repair manifests, executions, and verification records, and creates immutable versioned report snapshots. It renders escaped HTML and PDF and stores JSON evidence without running notebook code. Common credential fields and token patterns are redacted; report sections preserve unavailable/inconclusive states. The existing graph nodes/edges are included as source-linked graph data; no artificial graph or graph image is generated.
- **Docker runner:** `backend/app/services/execution_manager.py` runs background tasks with a two-container concurrency limit and a bounded in-process queue. `backend/app/services/docker_runner.py` invokes the configured image (`CODETRACE_EXECUTION_IMAGE`, default `codetrace-notebook-runner:latest`) with network disabled, a non-root UID, read-only root filesystem, dropped capabilities, no-new-privileges, CPU/memory/PID/time limits, a read-only bind mount containing only the selected notebook and associated datasets, and bounded tmpfs writable areas. The runner keeps the container alive briefly after execution so the host can read the result and notebook from tmpfs through bounded `docker exec` streams before stopping it; no host output directory or Docker socket is mounted. A per-run temporary directory and container are cleaned up after success, failure, timeout, or cancellation. Docker/image failures return `unavailable`; notebook code is never executed on the API host.
- **Container execution entry point:** `backend/execution/Dockerfile` builds the pre-installed Python runtime; `backend/execution/runner.py` validates and executes notebooks using `nbclient`, captures cell outputs/errors and actual runtime/package metadata, and caps persisted output. Runtime execution does not install notebook packages or access the network.
- **Dataset overlap:** `backend/app/services/dataset_overlap.py` compares two CSV uploads, reports exact duplicated rows and configured identifier/group overlap counts, and does not expose values or persist records.
- **Response models:** `backend/app/models/notebook.py`, `backend/app/models/dataset.py`, and `backend/app/models/execution.py` document upload, dataset, and execution responses.
- **Tests:** pytest tests exercise upload validation, AST extraction, graph links, findings, fallback behavior, and non-execution of untrusted source.

Execution orchestration currently runs in one FastAPI process; use one Uvicorn worker. SQLite records survive process restarts, but the in-process task queue is not a durable distributed job queue. The API has no account/login system; random notebook bearer tokens act as local capability authorization. Protect the local API and data directory accordingly.

## End-to-End Workflow

**Available workflow:** start the API and serve the static frontend. The About page is the default landing page when opened without a route; choose Inspect Notebook when ready to upload. The top navigation stays visible while the rest of the page scrolls. The header symbol checks `/api/health` on load and every 15 seconds. Choose and upload a notebook; after successful validation, the upload form is replaced by a notebook summary and separate navigation buttons for Overview, Pipeline Trace, Leakage & Evaluation Audit, Repair Center, Experiments, Verification, Cell Explorer, and Reports. Each button opens its own focused view rather than appending every section to one long page. Overview shows the standard kernel/language metadata when present, imported library names, individual imports, notebook dataset path references, recognized operations, and every notebook cell's source in notebook order. It also lets you separately upload a CSV for aggregate dataset profiling; notebook-referenced paths are never opened. Pipeline Trace displays an interactive dependency graph generated from the notebook analysis response. Zoom, pan, fit/reset, operation-type and finding-status filters, node/edge selection, upstream/downstream highlighting, and finding-path highlighting are available. In Repair Center, inspect the original and proposed code, diff, explanation, and validation; approve or reject proposals individually. Only explicitly approved, validated notebook repairs can be submitted to generate a separate corrected file. Dataset overlap findings remain manual because they are not linked to notebook split source. In Experiments, explicitly associate datasets, select the original or approved corrected notebook, and start each execution separately; monitor status and cell outputs/errors and download the executed artifact. In Reports, explicitly generate an immutable snapshot, preview its HTML, download HTML/PDF/JSON, and download available persisted notebook artifacts. Dataset analysis by itself does not associate a CSV with a notebook. Use Notebook summary to return to the summary, or Choose another notebook to start a fresh upload.

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

The Leakage & Evaluation Audit page can submit two separately selected CSV files to `POST /api/datasets/overlap`. The endpoint accepts multipart fields `train_file`, `test_file`, optional `identifier_column` and `group_column`, and an `evaluation_objective`: `unseen_groups`, `future_known_groups`, `independent_rows`, or `unspecified` (the default). It checks exact full-row matches when both files have the same column names (column order may differ), and compares only configured non-empty identifier/group values across the files. A missing configured column or unsupported objective is an explicit validation error. If schemas differ, full-row comparison is marked skipped rather than reported as a successful check; configured identifiers can still be checked when present in both files.

The response contains overlap counts, filenames, check status, objective-specific interpretation, caveats, and findings, but never overlapping values. For `unseen_groups`, shared groups are flagged as conflicting with the stated holdout goal. For `future_known_groups`, group overlap is informational rather than treated as a defect; chronology and post-cutoff feature leakage still require separate review. For `independent_rows`, the user is prompted to assess within-group dependence. If the objective is unspecified, the result remains a caution rather than assuming a split policy. Exact duplicate feature rows are not treated as proof of same-person leakage. Identifier/group semantics are supplied by the caller. Both files are bounded by the existing per-file upload limit, processed in memory, and discarded after the request. This check is not automatically joined to notebook graph nodes or used to rewrite a notebook split because the uploaded CSVs are not tied to the notebook's split statement.

### Finding evidence and interpretation

Notebook findings are generated from the already parsed cell AST, extracted operation arguments, and Phase 2 dependency graph; detection does not execute code or load referenced paths. Each finding includes a unique `id`, stable `rule_id`, category, severity, confidence, classification, source references/snippets, related variables, related pipeline node IDs, explanation, recommendation, and detection limitations. Dataset overlap findings use dataset evidence and intentionally have no notebook cell or graph node.

`source_evidence` means the source directly shows a suspicious construction; `potential_risk` means data semantics or intent remain uncertain; `heuristic_suspicion` means a name-based signal requiring manual review; `informational_review` is not a defect finding. High/medium/low confidence describes evidence support rather than probability. Informational severity is a review prompt. No current rule claims a runtime-confirmed defect, so graph findings remain amber rather than red.

### Automated repair proposals

The parser adds `notebook.analysis.repairs`, a repair classification corresponding to each notebook finding. The separate `backend/app/services/repair_engine.py` consumes the source cells and Phase 3 findings; it does not duplicate detection or execute notebook code. Repair IDs are stable for the finding and template. Supported deterministic proposals are deliberately narrow:

- **Preprocessing leakage:** move a single recognized scaler/imputer/PCA `fit_transform` result out of a simple `train_test_split` input, split the raw feature variable instead, fit the existing transformer on `X_train`, and transform `X_test`. The transformer must have a recognized scikit-learn import, the split must expose the expected `X_train`/`X_test` outputs, and the transformed value must not have unrelated uses.
- **Direct target-column leakage:** remove an exact string column from a simple, single-line literal feature-column list only when a preceding assignment selects that same dataframe column for a conventional target variable and another feature remains. Commented or multi-line lists remain manual.

Each proposal includes its finding ID/category, affected zero-based cells, original and corrected source, a human-readable change explanation, affected variables/dependencies, validation results, and limitations. Other recognized Phase 3 findings—including target-derived feature construction, suspicious feature names, test-set selection/contamination, and insufficiently specified group overlap—are classified for manual intervention. Unknown rules are marked not repairable with current evidence. Dataset overlap findings are included in the frontend Repair Center as manual-only because the separately uploaded CSVs are not tied to notebook split statements.

Before a supported proposal is offered, the engine parses modified Python cells, checks that the rewrite introduces no new identifiers, re-runs the relevant static finding rule, and rejects ambiguous or overlapping edits. The notebook parser has already validated the uploaded nbformat v4 document. At generation, only explicitly approved repair IDs are re-derived from the uploaded original and applied; selected repairs that affect the same cell are rejected. The output is validated with `nbformat`, preserves notebook/cell metadata and order, clears outputs and execution counts only for modified code cells, and is named `<original>-repaired.ipynb`. The uploaded original is never changed. For Phase 5, notebook bytes and approved corrected versions are persisted so a user can explicitly start separate experiments; repair generation itself does not start execution.

Validation does **not** establish semantic correctness or successful experiment behavior. Repair generation does not install missing dependencies, infer group identifiers, change test-driven model selection, construct validation workflows, remove duplicates, or automatically repair ambiguous target leakage. Repair generation does not execute the notebook; Phase 5 execution is separate and explicit, and the repair proposal itself is not evidence of successful verification.

### Graph contract and interpretation

`notebook.analysis.pipeline_graph` contains:

- `nodes`: stable node ID, operation kind/label, cell index, line, source snippet, static evidence label, and source reference.
- `edges`: source and target node IDs, shared variable, `inferred_from_variable_reference` relationship, static-AST evidence, and source references.
- `unresolved_references`: input identifiers without an earlier recognized producer and an explicit reason/source reference.
- `limitations` and `trace_type: "static_inference_not_runtime_trace"`.

Edges indicate only that recognized source operations reference a variable produced by an earlier recognized operation. They are inferences, not observed runtime transfers. Nodes without links remain disconnected. Notebook order, saved execution counts, and output presence are not runtime tracing.

The analyzer also retains the earlier `pipeline_graph` field for compatibility. The current Pipeline Trace interface is generated from `notebook.analysis.pipeline_trace` as described below; neither graph is a runtime trace.

### Interactive pipeline dependency map

The upload response also includes `notebook.analysis.pipeline_trace`, generated from the existing `all_operations` and `findings` by `backend/app/services/pipeline_trace.py`. The graph is built independently of rendering and is consumed by the Pipeline Trace workspace. Upload now returns a persistent notebook ID and a random access token for explicit experiment operations.

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

Notebook upload, parsing, and static analysis never execute, import, or evaluate notebook code. Saved binary outputs are omitted from the analysis response. Explicit experiments, when requested, execute notebook code only inside the restricted Docker runner. The frontend inserts notebook-controlled strings as text, not HTML, and does not persist notebook contents or bearer tokens in browser storage. Findings are source-grounded signals for human review, not runtime-confirmed defects. Static analysis cannot establish actual data values, target-derived feature leakage generally, dynamic aliases/control flow, indirect test-set reuse, generated code, or all library-specific behavior. False negatives are possible; no detection benchmark is provided.

---

## Project Structure

```text
CodeTrace/
├── frontend/
│   ├── index.html          # Inspect/About navigation and notebook workspace
│   ├── css/
│   │   └── style.css       # Responsive light theme
│   └── js/
│       └── app.js          # Health, upload, workspace, repair, and report UI
├── backend/
│   ├── app/
│   │   ├── main.py         # FastAPI notebook, experiment, verification, report, and artifact APIs
│   │   ├── services/
│   │   │   ├── notebook_parser.py # nbformat validation and extraction
│   │   │   ├── notebook_analyzer.py # AST metadata and pipeline operations
│   │   │   ├── pipeline_trace.py # Source-evidence dependency graph builder
│   │   │   ├── detection_engine.py # Notebook leakage/evaluation rules
│   │   │   ├── dataset_overlap.py # Explicit train/test CSV comparison
│   │   │   ├── repair_engine.py # Finding classification, source transforms, validation
│   │   │   ├── audit_analyzer.py # Initial source-pattern audit rules
│   │   │   ├── dataset_analyzer.py # Explicit CSV profiling
│   │   │   ├── execution_store.py # SQLite notebook, dataset, and run persistence
│   │   │   ├── verification_engine.py # Finding verification and metric comparison
│   │   │   ├── report_service.py # Persisted evidence aggregation and HTML/PDF export
│   │   │   ├── execution_manager.py # Background run lifecycle
│   │   │   └── docker_runner.py # Docker-only isolated execution
│   │   ├── api/            # Package scaffold
│   │   ├── analyzers/      # Package scaffold
│   │   └── models/
│   │       ├── notebook.py # Notebook upload response models
│   │       ├── dataset.py  # CSV analysis response models
│   │       ├── execution.py # Experiment request/result models
│   │       └── verification.py # Verification request model
│   └── execution/
│       ├── Dockerfile      # Prebuilt, non-root Python notebook runtime
│       └── runner.py       # Container-side nbclient execution and output limits
├── tests/
│   ├── test_main.py        # Health endpoint tests
│   ├── test_notebook_upload.py # Upload validation tests
│   ├── test_notebook_analyzer.py # Static analysis tests
│   ├── test_detection_engine.py # Leakage/evaluation rule tests
│   ├── test_pipeline_trace.py # Pipeline graph shape/dependency tests
│   ├── test_dataset_analysis.py # CSV profile tests
│   ├── test_dataset_overlap.py # Train/test overlap tests
│   ├── test_repair_engine.py # Repair proposals, validation, conflicts, generation
│   ├── test_execution.py   # Mocked isolated execution, auth, persistence, limits, cleanup
│   ├── test_verification.py # Repair evidence, statuses, metrics, and auth
│   └── test_reports.py     # Report snapshots, exports, redaction, and artifact access
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

- Python 3.11 or later for the API — <https://www.python.org/downloads/>
- Docker Desktop or Docker Engine for isolated experiments
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
| `POST /api/notebooks/upload` | Validates, analyzes, and stores an original notebook | Notebook summary, `notebook_id`, and one-time `access_token` |
| `POST /api/notebooks/repairs/generate` | Accepts the original, its ID, bearer token, and approved repair IDs | Separate `.ipynb` attachment and `X-CodeTrace-Notebook-ID` for the approved corrected version |
| `POST /api/datasets/analyze` | Profiles one explicitly uploaded CSV for the request | Dataset dimensions and aggregate per-column profile; no row values |
| `POST /api/datasets/overlap` | Compares explicitly uploaded train/test CSVs | Exact-row and configured identifier/group overlap; group visualization uses temporary aliases, never raw IDs |
| `GET /api/notebooks/{notebook_id}/versions/{version_id}/analysis` | Re-analyzes an authorized stored notebook version without execution | Source-based notebook and pipeline analysis |
| `POST /api/notebooks/{notebook_id}/datasets` | Explicitly associates one CSV with a notebook | Dataset ID and filename |
| `GET /api/notebooks/{notebook_id}/datasets` | Lists associated CSVs | Dataset IDs, filenames, and timestamps |
| `POST /api/notebooks/{notebook_id}/executions` | Explicitly starts a run with JSON `{"dataset_ids":[]}` | HTTP 202 queued/running result; HTTP 503 with a persisted `unavailable` result if Docker/image is missing |
| `POST /api/notebooks/{notebook_id}/paired-experiments` | Explicitly starts the original and an approved corrected notebook with the same non-empty `dataset_ids` | Pair ID, two separate execution IDs, and both initial statuses |
| `GET /api/notebooks/{notebook_id}/paired-experiments` | Lists saved pair records for an authorized original notebook | Pair IDs, notebook IDs, execution IDs, and any saved verification |
| `GET /api/notebooks/{notebook_id}/paired-experiments/{pair_id}` | Retrieves both run records and finalizes verification once both runs are terminal | Actual outputs, logs, verification, and comparison; no metrics are invented |
| `GET /api/notebooks/{notebook_id}/executions` | Lists saved runs for the original and its corrected versions | Authorized execution records; does not start runs |
| `GET /api/executions/{execution_id}` | Retrieves status, cell outputs/errors, logs, metadata, and associated datasets | Persisted execution result |
| `GET /api/executions/{execution_id}/notebook` | Downloads the executed artifact when one exists | Executed `.ipynb` attachment |
| `POST /api/executions/{execution_id}/cancel` | Stops an active container | Cancelled result or HTTP 409 if no longer active |
| `POST /api/notebooks/{notebook_id}/verifications` | Verifies supplied original/corrected execution IDs and optional approved `repair_ids` | Per-finding verification plus separate comparison, persisted without executing notebooks |
| `GET /api/notebooks/{notebook_id}/verifications` | Lists saved verification audit records | Immutable history for the authorized notebook |
| `GET /api/verifications/{verification_id}` | Retrieves a verification audit record | Findings, evidence, execution IDs, checks, limitations, and comparison |
| `GET /api/verifications/{verification_id}/findings/{finding_id}` | Retrieves one finding's verification details | Individual status and evidence |
| `GET /api/verifications/{verification_id}/comparison` | Retrieves only the original/corrected experiment comparison | Execution setup, captured metrics, and comparability reasons |
| `POST /api/notebooks/{notebook_id}/reports` | Generates and persists a report snapshot from saved records | Report ID, timestamp, status, overview, and available formats |
| `GET /api/notebooks/{notebook_id}/reports` | Lists report snapshots for an authorized notebook | Report metadata; does not execute notebooks |
| `GET /api/reports/{report_id}` | Retrieves report metadata | Notebook association, generation time, and formats |
| `GET /api/reports/{report_id}/html` | Previews the stored HTML export | Escaped HTML with a restrictive content security policy |
| `GET /api/reports/{report_id}/pdf` | Downloads the stored PDF export | PDF attachment |
| `GET /api/reports/{report_id}/json` | Downloads the machine-readable evidence export | JSON attachment with schema version and traceable records |
| `GET /api/notebooks/{notebook_id}/artifacts` | Lists associated notebooks, CSV datasets, and executed notebook artifacts | Only artifacts that actually exist |
| `GET /api/notebooks/{notebook_id}/artifacts/notebooks/{artifact_notebook_id}` | Downloads an associated original or corrected notebook | Capability-authorized `.ipynb` attachment |
| `GET /api/notebooks/{notebook_id}/artifacts/datasets/{dataset_id}` | Downloads a dataset explicitly associated with the notebook | Capability-authorized original CSV bytes |
| `GET /api/notebooks/{notebook_id}/artifacts/executions/{execution_id}` | Downloads an associated executed notebook artifact | Capability-authorized attachment only when stored |

Notebook execution-related APIs require the `Authorization: Bearer <access_token>` header, using the capability token returned by the notebook upload response. The random token is a capability for that notebook and its approved corrected version; it is returned only at upload and retained in frontend memory. It is not a user-account system. `POST /api/notebooks/repairs/generate` accepts multipart `file`, `repair_ids` (a JSON array of repair IDs from the analysis response), and `notebook_id`; the frontend also sends the bearer token. Existing callers that omit `notebook_id` retain the legacy download-only behavior. FastAPI's interactive documentation is available at `http://127.0.0.1:8000/docs` while the local server is running.

### Phase 5 isolated execution

Install/start Docker Desktop (Windows) or Docker Engine (Linux/macOS), then build the runner image from the repository root:

```powershell
docker build -f backend\execution\Dockerfile -t codetrace-notebook-runner:latest backend\execution
```

The runner image pins `nbclient`, `ipykernel`, and `nbformat`. Additional Python libraries must be deliberately baked into a locally built runner image; CodeTrace never installs packages declared by a notebook and execution has no network access. To use a differently named image, set `CODETRACE_EXECUTION_IMAGE` before starting the API. Docker and the image must already be available; otherwise execution is marked `unavailable`, with no host-execution fallback.

Each explicit execution creates a fresh container. The API mounts the selected notebook and only the explicitly associated datasets read-only; results are written to a size-limited container tmpfs and streamed back with bounded `docker exec` reads before the container is stopped (tmpfs contents do not survive container exit). The runner waits up to 30 seconds for artifact collection if the host becomes unresponsive. The container runs as UID 10001, with `--network none`, a read-only root filesystem, dropped Linux capabilities, no-new-privileges, a 1 CPU limit, 1 GiB memory, 64 processes, a 300-second timeout, and bounded tmpfs storage/output. It receives no host environment variables, credentials, API keys, Docker socket, or host output directory. Container and per-run temporary files are removed after the run. Each container uses its own working directory and is not given files associated with another notebook/run.

Every execution version has its own ID and container. Generating/approving a corrected notebook does not start it. The single-run control still starts one selected version; the separate **Start original + corrected runs** action starts a paired experiment only after an approved correction exists and at least one associated dataset is selected. Both runs receive the identical selected dataset IDs and run in separate fresh containers. The pair is persisted with both execution IDs. An execution stores actual start/completion times, duration, status, cell counts and outputs, failure details, container Python/package versions, environment limits, dataset references, bounded logs, and an executed notebook artifact when available. Statuses are `queued`, `running`, `completed`, `failed`, `timed_out`, `cancelled`, and `unavailable`.

The execution API is designed for one FastAPI process/worker because the background task queue is in-process; SQLite status/artifact records persist, but queued work is not a distributed durable job queue. The API has no login or multi-user account model. Treat notebook execution tokens as secrets and protect the SQLite data directory. CORS is restricted to the configured local development origins, so serve the frontend through Live Server (`http://127.0.0.1:5500`) or the documented local HTTP server; opening it as `file://` is intentionally unsupported. Docker isolation reduces risk but is not a proof against container runtime/kernel vulnerabilities or resource exhaustion outside configured limits. Do not treat this local development setup as a hardened multi-tenant service.

### Phase 6 repair verification and experiment comparison

The **Experiments** workflow can explicitly start a pair, display original and corrected cards, captured metrics and execution logs, and poll both statuses. When both runs are terminal, loading the pair invokes the same stored-source and execution verification used by the manual verification API, then saves that result once with the pair. The **Verification** workspace also supports selecting saved runs manually; verification never starts or repeats an experiment. A corrected notebook generated before approved repair manifests were persisted cannot be verified through this API and must be generated again from the current Repair Center.

Each immutable SQLite verification record traces the original finding and cell references to the approved repair, corrected source cells, both execution IDs, checks performed, evidence, remaining risks, limitations, and timestamp. Supported statuses are `verified`, `partially_verified`, `not_verified`, `inconclusive`, `execution_failed`, and `not_applicable`. A corrected failed, timed-out, or cancelled run is reported as `execution_failed`; an unavailable run is `inconclusive` because no execution took place. Incomplete original evidence is also inconclusive. Successful execution alone never marks a repair verified.

Category checks are deliberately narrow:

- **Preprocessing leakage:** checks the specific corrected pattern for training-partition fitting and a test-partition transform using the same transformer, and confirms the original static rule is absent. It does not prove that every preprocessing operation or data path is safe.
- **Direct target-column leakage:** checks that the exact literal target column originally identified is absent from corrected literal feature lists while the target assignment remains. Other target-derived fields, aliases, and post-outcome variables remain outside this check.
- **Test-set contamination and evaluation flaws:** checks whether the specific static finding remains and looks for recognizable validation/cross-validation evidence where relevant. These source signals are partial and do not establish runtime partition membership.
- **Train/test overlap:** recognizes explicit group-aware splitting with a `groups` argument as partial supporting evidence only. Dataset membership is not recomputed after repair; absent reliable identifier/group evidence remains inconclusive.
- Unsupported category patterns are explicitly inconclusive or not applicable rather than being treated as repaired.

Metric extraction recognizes explicitly labeled `accuracy`, `precision`, `recall`, `F1`, `ROC-AUC`, `MAE`, `MSE`, `RMSE`, and `R-squared` values in captured text outputs. Each extracted observation is tied to its execution, cell, associated dataset references, detected split/model configuration, and random seeds. It does not infer metrics from code, unlabeled output, plots, or unrelated values. Deltas are shown only when both executions completed, use identical non-empty dataset references and execution environments, and the analyzer can establish matching model configuration, split protocol/target/output variables, random seeds, Python version, and versions of relevant NumPy/pandas/scikit-learn/SciPy packages. Differences in the feature expression passed to the split are explicitly listed as a documented change rather than silently treated as identical; results remain descriptive and cannot isolate a causal effect when features change. Other setup differences or missing evidence withhold deltas. Classification rates in the 0–1 or percent scale are displayed as signed percentage-point differences. No score change proves repair correctness.

The group-overlap panel shows actual group membership in the two explicitly uploaded CSV split files using temporary aliases (up to 30 displayed per partition); it never returns raw identifiers. This is not a record of notebook execution assignments. CodeTrace does not synthesize a corrected group partition or rewrite notebook code from CSV overlap alone: the group column must be reliably tied to source and the evaluation objective established before a group-aware split can be safely changed. For true experiment assignments, the notebook must emit validated structured evidence; current runner records do not capture per-row partition membership.

The `Verification` UI supports links back to original finding, pipeline, and original cell views where the current analysis contains those references. Corrected cell numbers and changed source references are displayed; the original notebook remains unchanged. Verification reports and comparisons are append-only and do not overwrite earlier workflow records. This is not a comprehensive static or runtime proof of leakage absence.

### Phase 7 evidence reports and downloads

The **Reports** workspace explicitly generates a snapshot from the original notebook persisted during upload. The report service reuses the existing notebook parser/analyzer and reads only records associated with that original notebook: corrected notebook versions, persisted approved repair manifests, saved execution records/artifacts, and immutable verification/comparison records. Report generation never calls the execution manager, reruns a notebook, alters findings, or updates execution history. Each report receives a UUID, UTC generation timestamp, and schema version `1.0`; its JSON data, HTML, and PDF are stored together in SQLite so later downloads represent the same snapshot.

The report contains overview counts; original notebook metadata, cell types/source, imports and inferred dataset paths; the analyzer's operation list and existing pipeline graph nodes/edges; findings with source snippets, evidence classification, node links, confidence and limitations; proposals with actual approved-application manifests or an explicit note that approval/rejection was not persisted; each original/corrected execution and captured output/configuration; saved per-finding verification results; saved metric comparisons; a conclusion based on those recorded statuses; and a catalog of notebook artifacts that exist. Missing workflow records are labeled `not_performed`; static findings are labeled as inferences and are not represented as confirmed runtime defects. The graph is included from the existing trace output, not redrawn; no graph image export is currently supported.

Exports are HTML, PDF (ReportLab), and machine-readable JSON. HTML is escaped and preview responses set a restrictive Content Security Policy. Common credential fields, bearer tokens, and common API-key patterns are redacted; the report does not include associated dataset contents. This is best-effort redaction, not a guarantee that arbitrary secrets embedded in notebook text are detected; review exported source snippets before sharing. Downloads for original/corrected notebook bytes and stored executed notebooks require the same per-notebook bearer capability and are checked against the original notebook's version/execution associations. No missing artifact is synthesized.

Report APIs are listed above. Generate a report with `POST /api/notebooks/{notebook_id}/reports` and the notebook upload token in `Authorization: Bearer <access_token>`. Use the report ID for metadata and HTML/PDF/JSON retrieval; `GET /api/notebooks/{notebook_id}/reports` lists prior snapshots. The artifacts catalog and associated download routes also require the token. Associated CSVs are available as separate authorized downloads and are never embedded in reports. If experiment or verification records do not exist, the report remains `partially_available` and states which sections were not performed; `completed` means saved executions and verification records were present, not that all findings were resolved.

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

The frontend must be served from one of the configured local HTTP origins; `file://` origins are intentionally not allowed.

---

## Running Tests

```powershell
.\venv\Scripts\python.exe -m pytest tests\ -v
```

The tests cover root and health endpoints, upload validation, static notebook analysis, graph links, leakage/evaluation findings, dataset profiles/overlap, repair classification, positive and negative repair patterns, conflicts, notebook metadata/output handling, and repaired-notebook generation. Run the suite to see current results.

---

## Manual Verification

1. Start the backend with `uvicorn backend.app.main:app --reload`.
2. Open `http://127.0.0.1:8000/api/health` in a browser — you should see the JSON health response.
3. Open the frontend page in a browser.
4. Wait for the `</>` symbol in the header to turn green after the health check succeeds.
5. Upload `testing/sample_notebook.ipynb` or another valid notebook.
6. In Overview, optionally upload `testing/sample_dataset.csv` to review its measured row count, column types, missing values, and numeric summaries.
7. In Leakage & Evaluation Audit, optionally upload separate training/test CSV files and configure identifier/group columns for overlap checks.
8. Review Pipeline Trace, Leakage & Evaluation Audit, Repair Center, and Cell Explorer. Confirm graph links are labeled as inferred and source is shown as text.
9. In Repair Center, compare the proposed code and diff, reject or explicitly approve a proposal, and generate a separate corrected notebook. Confirm the original upload is unchanged.
10. In Experiments, explicitly attach any required CSV files, select **Original notebook**, and start execution. If a corrected notebook was generated, select it and start a second execution explicitly.
11. Review execution status, duration, cell outputs/errors, and download the executed notebook when an artifact is available.
12. Download the evidence report and inspect its notebook details, notebook and dataset findings, graph, definitions, and limitations.
13. Stop the backend — within the next health check, the symbol should turn red. An upload attempt should show a connection error.

---

## Limitations

- Only nbformat v4 JSON notebooks up to the configured size limit can be uploaded. Experiment notebook bytes, associated datasets, and execution artifacts are persisted in the configured SQLite store.
- AST analysis covers common Python syntax and selected patterns. Syntax-error cells receive a limited source-text fallback or remain unresolved.
- Variable-name matches do not prove value relationships. Control flow, branches, dynamic aliases, reassignment semantics, and target-derived feature leakage are not comprehensively analyzed.
- Audit results require human review. Exact row duplicates are not proof of same-entity overlap; identifier semantics depend on user configuration. No labeled benchmark or measured precision/recall is available.
- Repair templates support only simple source patterns. Target-derived features, group-aware splits, test-set-driven tuning, complex preprocessing, and multiple conflicting edits require manual changes. Syntax, static-rule, and nbformat validation do not prove a repair correct; Phase 5 does not automatically verify repairs or compare model metrics.
- Notebook-referenced datasets are not loaded automatically. CSV profiling is aggregate-only; overlap analysis compares only separately uploaded split files and does not infer notebook-to-file correspondence. For execution, datasets must be explicitly associated and selected; notebook execution uses Docker and is never performed on the API host.
- The frontend API base URL is configured in `frontend/js/app.js`.
- CORS origins are intended for local development and are not a production security policy. The per-notebook token is capability authorization, not account authentication.
- No multi-user identity system, distributed queue, or production hardening is provided.

## Research Evaluation

No benchmark dataset, annotation protocol, baseline comparison, or measured detection result has been produced yet. A future evaluation should use a documented, labeled set of notebooks, define annotation criteria for each target pattern, and report precision, recall, and F1 with error analysis. Any results should be compared with a stated baseline and should distinguish syntactic matches from cases requiring contextual interpretation. This is an evaluation recommendation, not a completed or implemented capability.

---

## License

To be decided at a later stage.
