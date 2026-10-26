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
| Source-linked operation graph with inferred variable links | Implemented; partial patterns only |
| Potential-risk audit for supported rules | Implemented; limited coverage |
| Cell Explorer and downloadable JSON evidence report | Implemented |
| Comprehensive leakage/data-flow detection | Not implemented |
| Runtime tracing, dataset inspection, and benchmark evaluation | Not implemented |

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
- **Notebook parser:** `backend/app/services/notebook_parser.py` checks JSON and nbformat v4 structure and extracts ordered cell source, type, saved execution count, and output presence.
- **Static analyzer:** `backend/app/services/notebook_analyzer.py` uses Python AST without executing source. It extracts recognizable imports, data-read paths, feature transformations, splits, model construction, fitting, prediction, and evaluation operations.
- **Audit rules:** `backend/app/services/audit_analyzer.py` applies independent, limited checks to the extracted source operations and attaches stable identifiers, evidence, source references, recommendations, severity/confidence, and caveats.
- **Response models:** `backend/app/models/notebook.py` documents the parsed notebook and nested analysis response.
- **Tests:** pytest tests exercise upload validation, AST extraction, graph links, findings, fallback behavior, and non-execution of untrusted source.

There is no database, permanent file storage, or notebook execution.

## End-to-End Workflow

**Available workflow:** start the API and serve the static frontend. The About page is the default landing page when opened without a route; choose Inspect Notebook when ready to upload. The top navigation stays visible while the rest of the page scrolls. The header symbol checks `/api/health` on load and every 15 seconds. Choose and upload a notebook; after successful validation, the upload form is replaced by a notebook summary and separate navigation buttons for Overview, Pipeline Trace, Leakage & Evaluation Audit, Cell Explorer, and Evidence Report. Each button opens its own focused view rather than appending every section to one long page. Overview shows imported library names, individual imports, dataset references, recognized operations, and every notebook cell's source in notebook order. Pipeline Trace presents recognized operations in workflow stages and shows variable-reference links where supported. The stage order reflects notebook source order, not runtime execution. Use Notebook summary to return to the summary, or Choose another notebook to start a fresh upload. The feature pages also show potential audit findings and their evidence, notebook source cells, or a downloadable JSON report.

### Static analysis coverage

The analyzer scans Python code cells independently with `ast.parse`. It recognizes common imports; data readers such as `read_csv` and `read_parquet`; common preprocessing constructors and transforms; common train/test split calls; estimator names ending in `Classifier`, `Regressor`, `Model`, or `Estimator` plus selected common names; `fit`, prediction, and common metric calls. It reports source locations and simple assignment-to-operation relationships where variable identifiers are visible. Markdown is parsed as content, not Python. A syntax-error cell receives limited regex fallback for split, fit, predict, and score calls and is marked as a limitation.

The current audit rules report:

| Rule ID | Trigger | Severity / confidence | Important caveat |
|---|---|---|---|
| `test_data_used_for_fit` | A recognizable `.fit(...)` call includes an identifier named like `X_test` or `y_test` | High / high | Identifiers do not prove variable contents. |
| `evaluation_on_training_data` | A recognizable metric/score call includes an identifier named like `X_train` or `y_train` | Medium / medium | Training-set scoring can be intentional; names and purpose are not verified. |
| `preprocessing_fit_before_split` | A recognized preprocessing fit on a common full-data identifier appears before a recognized split | Medium / medium | This is only a potential risk; later split execution and data relationships are not established. |

High severity means prioritize human review of a direct source pattern; medium means a recognizable but context-dependent concern; low is reserved for weak signals. Severity is not a probability or confirmation. High confidence means the source call and name pattern are explicit; medium means relevant semantics remain uncertain; low is reserved for fallback-only signals.

### Graph contract and interpretation

`notebook.analysis.pipeline_graph` contains:

- `nodes`: stable node ID, operation kind/label, cell index, line, source snippet, static evidence label, and source reference.
- `edges`: source and target node IDs, shared variable, `inferred_from_variable_reference` relationship, static-AST evidence, and source references.
- `unresolved_references`: input identifiers without an earlier recognized producer and an explicit reason/source reference.
- `limitations` and `trace_type: "static_inference_not_runtime_trace"`.

Edges indicate only that recognized source operations reference a variable produced by an earlier recognized operation. They are inferences, not observed runtime transfers. Nodes without links remain disconnected. Notebook order, saved execution counts, and output presence are not runtime tracing.

The Pipeline Trace section renders these nodes as an interactive, horizontally scrollable SVG map with distinct shapes for sources, transformations, splits, models, and model steps. Dashed arrows indicate inferred variable references. A red × marks a node whose source location is cited by a supported potential finding; it does not represent a runtime failure. Selecting a node opens its notebook cell. This is a lightweight visual presentation of the static graph, not an AWS X-Ray trace or a runtime service map.

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
        "Target-derived feature leakage and context-dependent test-set reuse are not automatically classified.",
        "No explicit variable-reference dependencies between recognized operations were established."
      ],
      "trace_type": "static_inference_not_runtime_trace"
    },
    "findings": []
  }
}
```

The actual response returns the complete parsed notebook and the analysis metadata, nodes, edges, findings, confidence/severity definitions, and limitations.

Notebook code is never executed, imported, or evaluated. Binary outputs are omitted. The frontend inserts notebook-controlled strings as text, not HTML, and does not persist notebook contents in browser storage. Findings are potential risks for human review. Static analysis cannot establish runtime execution, actual data values, target-derived feature leakage generally, dynamic aliases/control flow, indirect test-set reuse, generated code, or all library-specific behavior. False negatives are possible; no detection benchmark is provided.

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
│       ├── main.py         # FastAPI app and notebook upload endpoint
│       ├── services/
│       │   ├── notebook_parser.py # nbformat validation and extraction
│       │   ├── notebook_analyzer.py # AST metadata and pipeline graph
│       │   └── audit_analyzer.py # Supported source-pattern audit rules
│       ├── api/            # Package scaffold
│       ├── analyzers/      # Package scaffold
│       └── models/
│           └── notebook.py # Notebook upload response models
├── tests/
│   ├── test_main.py        # Health endpoint tests
│   ├── test_notebook_upload.py # Upload validation tests
│   └── test_notebook_analyzer.py # Static analysis tests
├── testing/
│   └── sample_notebook.ipynb # Local upload example
├── docs/                   # Currently empty
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

The upload endpoint does not authenticate callers and does not retain uploaded files. FastAPI's interactive documentation is available at `http://127.0.0.1:8000/docs` while the local server is running.

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

The tests cover the root and health endpoints, notebook upload validation, AST extraction, graph links, supported audit findings, clean and flawed examples, parse fallback, and non-execution of suspicious source. Run the suite to see current results.

---

## Manual Verification

1. Start the backend with `uvicorn backend.app.main:app --reload`.
2. Open `http://127.0.0.1:8000/api/health` in a browser — you should see the JSON health response.
3. Open the frontend page in a browser.
4. Wait for the `</>` symbol in the header to turn green after the health check succeeds.
5. Upload `testing/sample_notebook.ipynb` or another valid notebook.
6. Review Overview, Pipeline Trace, Leakage & Evaluation Audit, and Cell Explorer. Confirm graph links are labeled as inferred and source is shown as text.
7. Download the evidence report and inspect its notebook details, findings, definitions, and limitations.
8. Stop the backend — within the next health check, the symbol should turn red. An upload attempt should show a connection error.

---

## Limitations

- Only nbformat v4 JSON notebooks up to the configured size limit can be uploaded. Files are held in request memory and are not persisted.
- AST analysis covers common Python syntax and selected patterns. Syntax-error cells receive a limited source-text fallback or remain unresolved.
- Variable-name matches do not prove value relationships. Control flow, branches, dynamic aliases, reassignment semantics, and target-derived feature leakage are not comprehensively analyzed.
- Audit results are potential risks, not proof. No labeled benchmark or measured precision/recall is available.
- Referenced datasets are not loaded. Saved output payloads are omitted and notebook code is never executed.
- The frontend API base URL is configured in `frontend/js/app.js`.
- CORS origins are intended for local development, including the `null` origin for locally opened files; this configuration is not a production security policy.
- No database, authentication, deployment configuration, or production hardening is provided.

## Research Evaluation

No benchmark dataset, annotation protocol, baseline comparison, or measured detection result has been produced yet. A future evaluation should use a documented, labeled set of notebooks, define annotation criteria for each target pattern, and report precision, recall, and F1 with error analysis. Any results should be compared with a stated baseline and should distinguish syntactic matches from cases requiring contextual interpretation. This is an evaluation recommendation, not a completed or implemented capability.

---

## License

To be decided at a later stage.
