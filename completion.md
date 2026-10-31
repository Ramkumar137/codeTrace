# CodeTrace – Development Activity Log

> This file records completed project work. Entries describe work performed and verified; proposed work belongs in README.md, not in this log.

---

## Repository Bootstrap

**Date completed:**

### Objective

Bootstrap the project repository with a clean, minimal structure that a student can understand and extend. No analysis logic was implemented in this initial work.

---

### Activities performed

1. Designed and created the directory structure (`frontend/`, `backend/app/`, `tests/`, `docs/`).
2. Created Python package markers (`__init__.py`) for all backend sub-packages and `tests/`.
3. Wrote the minimal FastAPI application (`backend/app/main.py`) with CORS middleware and two health-check endpoints.
4. Wrote the frontend scaffold: `index.html`, `css/style.css`, `js/app.js`.
5. Wrote `requirements.txt` with only the packages needed for FastAPI + testing.
6. Wrote `.gitignore`.
7. Wrote `README.md`.
8. Wrote this file (`completion.md`).
9. Created the Python virtual environment, installed dependencies, and ran the test suite.

---

### Files created

| Path | Purpose |
|---|---|
| `frontend/index.html` | Landing page with drop zone for `.ipynb` upload |
| `frontend/css/style.css` | Dark-theme stylesheet with design tokens |
| `frontend/js/app.js` | Drag-and-drop handling, file validation, API call |
| `backend/app/__init__.py` | Python package marker |
| `backend/app/main.py` | FastAPI app – CORS, `/` and `/health` endpoints |
| `backend/app/api/__init__.py` | Empty package marker |
| `backend/app/services/__init__.py` | Empty package marker |
| `backend/app/analyzers/__init__.py` | Empty package marker |
| `backend/app/models/__init__.py` | Empty package marker |
| `tests/__init__.py` | Package marker |
| `tests/test_main.py` | Smoke test: verifies `/` and `/health` return HTTP 200 |
| `docs/` | Empty directory |
| `.gitignore` | Excludes `venv/`, `__pycache__/`, `.env`, IDE files, OS files |
| `requirements.txt` | `fastapi`, `uvicorn[standard]`, `python-multipart`, `httpx`, `pytest`, `pytest-asyncio` |
| `README.md` | Full project documentation |
| `completion.md` | This file |

---

### Implementation decisions

- **No database introduced.** Persistent storage was not needed for the initial API and tests.
- **No ORM or ML libraries.** Only the minimum packages required for a running FastAPI app and a passing test were added to `requirements.txt`.
- **No placeholder detection logic.** The `api/`, `services/`, `analyzers/`, and `models/` packages were created as empty scaffolds.
- **CORS was initially set to `allow_origins=["*"]`** for local development; the current application uses an explicit local-origin list, which is not a production security configuration.
- **Vanilla stack.** No React, TypeScript, Docker, or additional frameworks were introduced.
- **`python-multipart`** was included for FastAPI multipart/form handling. The current application does not expose a notebook upload endpoint.

---

### Commands executed

```powershell
# Create and activate virtual environment (Windows PowerShell)
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Run the test suite
pytest tests/ -v

# Verify the API starts (manual check – Ctrl+C to stop)
uvicorn backend.app.main:app --reload
```

---

### Tests performed and results

| Test | Command | Result |
|---|---|---|
| `test_root_health` | `pytest tests/test_main.py -v` | PASSED |
| `test_health_endpoint` | `pytest tests/test_main.py -v` | PASSED |

Both tests confirmed the API returns HTTP 200 with the expected JSON payload.

---

### Issues encountered

| Issue | Resolution |
|---|---|
| PowerShell may block `Activate.ps1` on a fresh Windows install | README documents the `Set-ExecutionPolicy` fix |

---

### Recorded state at bootstrap

- Repository structure is in place.
- FastAPI backend starts and passes smoke tests.
- Frontend scaffold was in place; notebook analysis was not implemented.
- The initial repository structure and API smoke-test setup were recorded as completed.

---

## Frontend and Backend Skeleton

**Date completed:** 2026-10-16

### Objective

Implement the FastAPI backend skeleton with an explicit `GET /api/health` endpoint, rebuild the frontend landing page with the required project identity, subtitle, and API status panel, and wire the two together.

---

### Activities performed

1. Inspected the existing project files before making changes.
2. Rewrote `backend/app/main.py`:
   - Replaced `allow_origins=["*"]` with an explicit `ALLOWED_ORIGINS` list.
   - Added `GET /api/health` returning `{"status": "healthy", "service": "CodeTrace API"}`.
   - Kept `GET /` returning `{"status": "ok", "message": "CodeTrace API is running."}`.
3. Rewrote `tests/test_main.py` with six focused, per-assertion test functions covering both endpoints.
4. Rewrote `frontend/index.html` with the project name, subtitle, hero, API status panel, and project-status cards.
5. Rewrote `frontend/css/style.css` with a dark developer-tool theme, design tokens, sticky header, animated status dot, and response detail table.
6. Rewrote `frontend/js/app.js` with the `Check API Status` handler: calls `GET /api/health`, validates `status == "healthy"` and `service` fields, handles HTTP errors and network failures separately, escapes API text before DOM insertion.
7. Updated `README.md` with endpoint documentation, expected responses, frontend-serving instructions, and test information.
8. Updated `completion.md` (this entry).
9. Ran the full test suite to confirm all six tests pass.
10. Ran a 15-point frontend integrity check (paths, IDs, JS logic) — all passed.

---

### Files modified

| Path | Change |
|---|---|
| `backend/app/main.py` | Explicit CORS origins; added `GET /api/health` |
| `tests/test_main.py` | 6 focused tests covering `/` and `/api/health` |
| `frontend/index.html` | Full rebuild — hero, status panel, and project information cards |
| `frontend/css/style.css` | Full rebuild — dark theme with design tokens |
| `frontend/js/app.js` | Full rebuild — `Check API Status` handler with validation & error handling |
| `README.md` | Updated endpoints, frontend serving instructions, test output |
| `completion.md` | This entry |

---

### Implementation decisions

- **Explicit CORS origins** instead of wildcard. `"null"` is included so the page works when opened as a `file://` URL without a local server. The list is in one named constant (`ALLOWED_ORIGINS`) for easy modification.
- **`GET /api/health`** uses the `/api/` prefix to cleanly separate API routes from any future static-file serving on `/`.
- **Frontend validation** checks both `status == "healthy"` and that `service` is a non-empty string before reporting success — an HTTP 200 with an unexpected payload is treated as a failure.
- **`escapeHtml()`** in `app.js` prevents XSS when injecting API response text into the DOM.
- **No new Python packages** were added; all six tests passed with the existing dependency set.

---

### Commands executed

```powershell
# Run the full test suite in the existing virtual environment
.\venv\Scripts\python.exe -m pytest tests/ -v
```

---

### Tests performed and actual results

| Test | Result |
|---|---|
| `test_root_returns_200` | PASSED |
| `test_root_has_status_ok` | PASSED |
| `test_root_has_message` | PASSED |
| `test_api_health_returns_200` | PASSED |
| `test_api_health_status_is_healthy` | PASSED |
| `test_api_health_service_name` | PASSED |

**6 passed, 0 failed.** (1 cosmetic Starlette deprecation warning — not our code.)

Frontend integrity check: **15/15 checks passed** (CSS path, JS path, element IDs, `API_BASE`, `/api/health`, button disable/re-enable, validation logic, error handling).

---

### Issues encountered

| Issue | Resolution |
|---|---|
| PowerShell `-c` multiline string quoting breaks with embedded quotes | Moved verification logic to a temporary `.py` script instead |

---

### Current project status

- Backend: `GET /` and `GET /api/health` implemented and tested.
- Frontend: landing page with project identity, status panel, and project information cards.
- Frontend–backend integration: clicking **Check API Status** contacts `/api/health` and displays the result.
- No notebook upload, parsing, or analysis functionality was implemented in this recorded work.

---

## Project Rules Compliance Update

**Date completed:** 2026-10-16

### Activities performed

1. Removed phase labels and the development roadmap from the frontend, retaining its existing page structure and visual theme.
2. Reworded frontend project-status content to distinguish the existing API connectivity check from unavailable notebook-analysis functionality.
3. Expanded `README.md` to document current functionality, architecture, the available and intended workflows, analysis goals, API endpoints, limitations, testing, and research-evaluation status.
4. Revised this activity log to preserve completed history while removing planned-work lists and phase-based headings.
5. Opened the updated frontend in a browser and confirmed the rendered project-status content contains no phase labels or roadmap.

### Files changed

| Path | Change |
|---|---|
| `frontend/index.html` | Removed phase and roadmap UI; clarified implemented and unavailable features. |
| `frontend/css/style.css` | Removed only styles for the deleted badge and roadmap; retained the existing theme. |
| `frontend/js/app.js` | Replaced phase-specific comments with accurate functional description. |
| `README.md` | Expanded and corrected project documentation and feature-status descriptions. |
| `completion.md` | Removed future-work sections and phase-based log framing; recorded this completed update. |

### Dependencies

No dependency files or installed packages were changed.

### Verification performed

| Command | Result |
|---|---|
| `.\venv\Scripts\python.exe -m pytest tests/ -v` | **6 passed, 1 dependency deprecation warning.** |

The warning originated in the installed Starlette/AnyIO test-client integration; no test failed.

---

## Notebook Upload and Parsing

**Date completed:** 2026-10-22

### Completed work

1. Added `POST /api/notebooks/upload` with multipart file handling, filename and extension checks, empty-file rejection, and a configurable upload limit. The default limit is 10 MiB; `CODETRACE_MAX_UPLOAD_SIZE_BYTES` configures it in bytes.
2. Added a notebook parser service that decodes JSON, validates nbformat v4 structure with `nbformat`, and returns notebook counts and per-cell source metadata. It does not execute code, return saved output payloads, or persist uploaded notebooks.
3. Added typed Pydantic response models and structured API error details.
4. Added a minimal notebook upload form and summary to the existing frontend. The existing API status interaction and styling were retained.
5. Updated project documentation with endpoint behavior, response examples, validation statuses, dependencies, Windows PowerShell commands, and current limitations.
6. Added tests for health endpoints and notebook upload/parsing validation, including proof that suspicious source is not executed.

### Files changed

| Path | Change |
|---|---|
| `backend/app/main.py` | Added bounded notebook upload API and structured validation responses. |
| `backend/app/services/notebook_parser.py` | Added JSON/nbformat validation and cell metadata extraction. |
| `backend/app/models/notebook.py` | Added notebook upload response models. |
| `frontend/index.html` | Added notebook file input, upload action, status message, and summary panel. |
| `frontend/css/style.css` | Added minimal upload-form styles using the existing design tokens. |
| `frontend/js/app.js` | Added FormData upload, duplicate-submit protection, response validation, and result/error display. |
| `tests/test_notebook_upload.py` | Added 12 upload and parsing tests. |
| `requirements.txt` | Added `nbformat==5.10.4`; retained FastAPI, Uvicorn, python-multipart, and test dependencies. |
| `README.md` | Documented implemented upload behavior and project setup/workflow. |
| `completion.md` | Recorded this completed work and its verification. |

### Dependency changes

- Added `nbformat==5.10.4` to `requirements.txt` and installed it into the existing `venv` with its dependencies.
- `python-multipart` was already listed and installed; it was not reinstalled or changed.
- No database, analysis, graph, or ML dependencies were added.

### Commands executed

```powershell
.\venv\Scripts\python.exe -m pip install nbformat==5.10.4
.\venv\Scripts\python.exe -m pytest tests\ -v
node --check frontend\js\app.js
```

### Verification results

| Check | Actual result |
|---|---|
| Backend test suite, including root and health checks | **18 passed, 0 failed.** |
| Upload response structure and file validation tests | **Passed** as part of the 18-test suite. |
| Non-execution of suspicious notebook cell source | **Passed**; the marker file was not created. |
| Frontend JavaScript syntax (`node --check`) | **Passed**, exit code 0. |

The pytest run emitted one existing Starlette/AnyIO `BlockingPortal` deprecation warning; no tests failed.

### Issues resolved during verification

- Added explicit handling for `nbformat.ValidationError` so invalid notebook structures return the documented 422 response instead of an unhandled server error.
- Handled empty multipart filenames (which FastAPI receives as a text form field) and returned the structured 400 missing-filename error.

---

## Light UI and Header API Health Indicator

**Date completed:** 2026-10-22

### Completed work

1. Replaced the dark interface styling with a responsive light theme using readable text, subtle borders, restrained shadows, and visible keyboard focus.
2. Simplified the page to the notebook inspection and upload flow; removed the standalone API status panel and project-status sections.
3. Kept the `</> CodeTrace` brand in the header and wired the symbol to the existing API health endpoint. It starts neutral, checks at load, refreshes every 15 seconds without overlapping requests, and changes color and accessible label according to the response.
4. Retained notebook upload integration, validation messaging, and parsed notebook summary; replaced the footer with a neutral label.
5. Updated README workflow notes to match the visible health indicator and upload experience.

### Files changed

| Path | Change |
|---|---|
| `frontend/index.html` | Simplified page layout, retained notebook upload, and made the header symbol the accessible health indicator. |
| `frontend/css/style.css` | Replaced dark styling with responsive light-theme styles and keyboard focus treatment. |
| `frontend/js/app.js` | Added automatic periodic health checks and retained upload/summary behavior. |
| `README.md` | Updated the described frontend and manual verification steps. |
| `completion.md` | Recorded this completed work and verification. |

### Verification results

| Check | Actual result |
|---|---|
| Existing backend and notebook test suite (`.\venv\Scripts\python.exe -m pytest tests\ -v`) | **18 passed, 0 failed**, 1 existing Starlette/AnyIO deprecation warning. |
| Frontend JavaScript syntax (`node --check frontend\js\app.js`) | **Passed**, exit code 0. |
| Frontend health/upload behavior harness | **Passed** healthy, unsuccessful HTTP, invalid payload, network failure, overlap prevention, successful upload response, and multipart header behavior. |
| Browser page load | **Passed**; the page rendered with the header indicator reporting a healthy API. |

---

## Notebook Investigation Workspace and About Page

**Date completed:** 2026-10-22

### Completed work

1. Added the Inspect/About navigation and an About page with the requested evaluation-trust narrative, limitations, and return navigation.
2. Extended successful notebook responses with source-only AST extraction for imports, library names, dataset references, and recognizable ML operations. Existing upload metadata and validation remain in place.
3. Added a stable pipeline graph response with source references, inferred variable-reference edges, unresolved inputs, and explicit static-analysis limitations.
4. Added separate, limited audit rules for test-named data passed to fitting, train-named data passed to evaluation, and preprocessing fitted on a common full-data name before a later recognized split. Findings include source evidence, severity/confidence, recommendations, and caveats.
5. Added the Overview, Pipeline Trace, Leakage & Evaluation Audit, Cell Explorer, and downloadable JSON Evidence Report to the post-upload workspace. Notebook content is rendered as text and is not saved in browser storage.
6. Updated README API response documentation to include the `analysis` extension and clarified the implemented analysis scope and safety boundaries.
7. Added a guard against treating the `test_size` split parameter as test data. No dependencies or requirements were changed.

### Files changed

| Path | Change |
|---|---|
| `backend/app/services/notebook_analyzer.py` | Added conservative AST extraction, source references, inferred graph links, and analysis limitations. |
| `backend/app/services/audit_analyzer.py` | Added the supported potential-risk audit rules. |
| `backend/app/services/notebook_parser.py` | Attached static analysis to the existing validated upload response. |
| `backend/app/models/notebook.py` | Added the analysis field to the notebook response model. |
| `frontend/index.html` | Added navigation, About content, and post-upload investigation sections. |
| `frontend/css/style.css` | Styled the About page and workspace within the existing light design and responsive layout. |
| `frontend/js/app.js` | Added workspace rendering, cell/finding navigation, and JSON report generation/download. |
| `tests/test_notebook_analyzer.py` | Added clean/flawed static-analysis, graph, evidence, fallback, and false-positive guard tests. |
| `tests/test_notebook_upload.py` | Updated upload response assertions for the backward-compatible analysis extension. |
| `README.md` | Documented the current analysis response and behavior. |
| `completion.md` | Recorded this completed work and its verification. |

### Verification results

| Check | Actual result |
|---|---|
| `.\venv\Scripts\python.exe -m pytest tests\ -v` | **27 passed, 0 failed**; one existing Starlette/AnyIO `BlockingPortal` deprecation warning. |
| `node --check frontend\js\app.js` | **Passed.** |
| `.\venv\Scripts\python.exe -m compileall -q backend\app` | **Passed.** |
| Browser upload of `testing/sample_notebook.ipynb` | **Passed**; rendered the 6-cell summary and all five workspace sections. |
| Browser navigation and health indicator | **Passed**; About text and navigation worked, and the API indicator reported healthy after the health response. |
| Evidence report generation | **Passed**; the browser generated a JSON Blob with the notebook, findings, definitions, and limitations and a `.evidence.json` download filename. |
| Responsive layout | **Passed** at a 360px viewport with no horizontal overflow. |

### Scope limitations

Static analysis remains limited to recognizable source patterns; graph links are inferred rather than runtime observations. Findings are potential risks, not proof. Notebook code and referenced data are not executed or accessed, and comprehensive leakage detection and runtime tracing are not implemented.

---

## Visual Pipeline Trace

**Date completed:** 2026-10-22

### Completed work

1. Replaced the text-only primary pipeline listing with a horizontally scrollable, interactive SVG graph showing recognized operations as distinct source, transformation, split, model, and model-step shapes.
2. Added dashed directed links and variable labels for inferred relationships, a legend, and an expandable textual relationship/unresolved-reference detail.
3. Added red × markers only when a node's source cell and line match a supported potential finding reference. Selecting a node opens its source cell; choosing a finding highlights related graph nodes and edges.
4. Kept the X-Ray inspiration limited to visual presentation and explicitly distinguished static source inference from runtime trace data. No graph library or dependency was added.
5. Updated README graph documentation.

### Files changed

| Path | Change |
|---|---|
| `frontend/index.html` | Added graph legend, SVG viewport, explanatory cross-marker note, and expandable details. |
| `frontend/css/style.css` | Added responsive graph, shape, edge, selection, focus, and finding-marker styles. |
| `frontend/js/app.js` | Rendered SVG nodes and inferred edges, cross markers, keyboard/click node selection, and finding highlighting. |
| `README.md` | Documented the visual graph and the meaning and limits of its shapes, edges, and markers. |
| `completion.md` | Recorded this completed work and verification. |

### Verification results

| Check | Actual result |
|---|---|
| `node --check frontend\js\app.js` | **Passed.** |
| `.\venv\Scripts\python.exe -m compileall -q backend\app` | **Passed.** |
| `.\venv\Scripts\python.exe -m pytest tests\ -v` | **27 passed, 0 failed**; one existing Starlette/AnyIO `BlockingPortal` deprecation warning. |
| Browser upload of the sample notebook | **Passed**; rendered four operation nodes and three inferred edges. Node selection opened the corresponding code cell. |
| Browser upload of a synthetic notebook containing `model.fit(X_test, y_test)` | **Passed**; showed a cross at the matching source location, and selecting the finding highlighted its graph node and opened the cited source cell. |
| Browser responsive and keyboard checks | **Passed** at a 360px viewport; the page had no horizontal overflow, the graph scrolled internally as needed, and keyboard activation selected a node and opened its cell. |

This remains a static-source graph. Its links are inferred variable references, and the red cross indicates a potential source finding—not a runtime failure or confirmed leakage.

---

## Focused Notebook Feature Pages

**Date completed:** 2026-10-22

### Completed work

1. Kept the upload form as the initial step and hid it after a successful notebook response.
2. Added a dedicated notebook summary page with the filename, format version, and cell counts.
3. Added feature buttons for Overview, Pipeline Trace, Leakage & Evaluation Audit, Cell Explorer, and Evidence Report. Each button opens its own hash-routed view, with the other feature pages hidden.
4. Kept a concise feature navigation on each view, a return-to-summary action, and a Choose another notebook action that restores the initial upload form.
5. Updated README workflow documentation.

### Files changed

| Path | Change |
|---|---|
| `frontend/index.html` | Separated the upload stage from the summary and individual feature pages; added feature buttons. |
| `frontend/css/style.css` | Styled the focused summary navigation and feature-page controls. |
| `frontend/js/app.js` | Added summary/feature hash routing, upload-stage transitions, and upload reset behavior. |
| `README.md` | Documented the summary-first, feature-page workflow. |
| `completion.md` | Recorded the completed workflow and verification. |

### Verification results

| Check | Actual result |
|---|---|
| `node --check frontend\js\app.js` | **Passed.** |
| `.\venv\Scripts\python.exe -m pytest tests\ -v` | **27 passed, 0 failed**; one existing Starlette/AnyIO `BlockingPortal` deprecation warning. |
| Browser upload of `testing/sample_notebook.ipynb` | **Passed**; successful upload hid the upload stage and opened the summary page with all five feature buttons. |
| Browser feature navigation | **Passed**; Overview, Pipeline Trace, Leakage & Evaluation Audit, Cell Explorer, and Evidence Report each displayed their own route with the other pages hidden; returning to the summary worked. |
| Browser upload reset | **Passed**; Choose another notebook returned to the upload form and hid the investigation workspace. |

---

## Explicit CSV Dataset Profiling

**Date completed:** 2026-10-31

### Completed work

1. Added `POST /api/datasets/analyze` for CSV files explicitly selected by the user. It validates the `.csv` extension, UTF-8 encoding, upload size, header, and record widths; processing is in memory and does not save dataset rows.
2. Added aggregate dataset profiles with observed row and column counts, inferred boolean/integer/number/text/empty types, non-empty and missing-value counts, missing percentages, and numeric count/minimum/maximum/mean.
3. Added a CSV upload and profile table to the existing Overview page, retaining CodeTrace branding and the existing light theme.
4. Added `testing/sample_dataset.csv` and documented the CSV endpoint, its input constraints, output semantics, and manual workflow.
5. Added API tests for numeric/type/missingness results, BOM and quoted fields, blank rows, empty datasets, file validation, encoding errors, and malformed CSV structures.

### Existing functionality reused

- Reused the existing FastAPI app, multipart handling, structured validation-error pattern, and configured `MAX_UPLOAD_SIZE_BYTES`.
- Kept notebook upload and notebook parsing unchanged; dataset paths inferred from notebook source are not opened.
- Reused the existing Overview workspace, file-input/button/message styles, and responsive light-theme design.
- Used Python's standard-library `csv` and `decimal` modules; no dataset or ML package was added.

### Files created

| Path | Purpose |
|---|---|
| `backend/app/services/dataset_analyzer.py` | Bounded, in-memory CSV parsing and aggregate profiling. |
| `backend/app/models/dataset.py` | Typed CSV analysis response models. |
| `tests/test_dataset_analysis.py` | Dataset analysis and endpoint validation tests. |
| `testing/sample_dataset.csv` | Small manual-test CSV fixture. |

### Files modified

| Path | Change |
|---|---|
| `backend/app/main.py` | Added the CSV analysis endpoint, preserving existing endpoints. |
| `frontend/index.html` | Added CSV selection and aggregate profile UI to Overview. |
| `frontend/js/app.js` | Added CSV upload, response validation, and safe text rendering. |
| `frontend/css/style.css` | Styled the profile table and upload panel within the existing theme. |
| `README.md` | Documented dataset analysis, safety boundaries, API, and manual test steps. |
| `completion.md` | Recorded this completed work and actual validation results. |

### Dependencies

No dependencies were added, removed, or changed.

### Verification results

| Check | Actual result |
|---|---|
| `.\venv\Scripts\python.exe -m pytest tests\ -q` | **43 passed, 0 failed**; one existing Starlette/AnyIO `BlockingPortal` deprecation warning. Pytest exit code 0. |
| `.\venv\Scripts\python.exe -m pytest tests\test_dataset_analysis.py -q` | **13 passed, 0 failed**; same dependency deprecation warning. |
| `node --check frontend\js\app.js` | **Passed**, exit code 0. |
| `.\venv\Scripts\python.exe -m compileall -q backend\app` | **Passed**, exit code 0. |
| `git diff --check` | **Passed**, exit code 0. |
| Browser workflow: upload `testing/sample_notebook.ipynb`, open Overview, upload `testing/sample_dataset.csv` | **Passed**; the UI showed 3 rows, 3 columns, age/score/segment profiles, missing percentages, and calculated numeric summaries. |

### Known limitations

- Only comma-delimited UTF-8 CSV files are supported; uploads use the existing 10 MiB size limit.
- Type inference and missingness are simple heuristics; only blank or whitespace-only cells count as missing. No distributions, target detection, relational checks, or leakage conclusions are produced.
- The CSV profile is displayed in the current notebook workspace but is not yet included in the JSON evidence report.
- Notebook-referenced paths remain informational and are never opened; notebooks continue to be parsed without execution.

## Interactive Pipeline Trace Graph

**Date completed:** 2026-10-31

### Completed work

1. Added `analysis.pipeline_trace` to the existing notebook upload response. The separate graph builder consumes the Phase 1 extracted operations and findings without executing notebook code or duplicating analysis.
2. Generated stable source-referenced nodes for recognized ML operations and directed edges only for explicit variable references or AST-detected estimator composition. Unresolved inputs are recorded without guessed links.
3. Associated findings only with their exact source references and represented potential, confirmed, no-supported-issue, and insufficient-evidence states without propagating findings downstream.
4. Replaced the Pipeline Trace stage/list interface with an interactive SVG dependency graph in the existing CodeTrace workspace. Added operation/finding filters, zoom, pan, fit/reset, node and edge selection/details, connected-operation highlighting, finding-path highlighting, and a legend.
5. Documented the graph schema, dependency semantics, supported operation categories, interactions, and static-analysis limitations in README.md. Reset the finding filter when a newly uploaded notebook is rendered.
6. Added upload-response integration coverage proving that source operations and their dependency links are present in the returned graph.

### Existing functionality reused

- The existing upload endpoint and validated notebook parser.
- Phase 1 AST-extracted operations, cell/source references, and audit findings.
- The existing notebook workspace, navigation, evidence statuses, and source-cell viewer.
- The existing vanilla HTML/CSS/JavaScript frontend and light CodeTrace visual design.

### Files created

| Path | Purpose |
|---|---|
| `backend/app/services/pipeline_trace.py` | Builds the structured static dependency graph from existing analysis output. |
| `tests/test_pipeline_trace.py` | Tests operation nodes, supported dependencies, branches, composition, findings, and uncertainty. |

### Files modified

| Path | Change |
|---|---|
| `backend/app/services/notebook_analyzer.py` | Extracted supported cleaning/missing-value operations and explicit estimator composition metadata. |
| `backend/app/services/notebook_parser.py` | Added the graph to the existing upload analysis response. |
| `tests/test_notebook_upload.py` | Added graph response shape and upload-to-graph dependency integration assertions. |
| `frontend/index.html` | Added the graph controls, filters, legend, accessible graph viewport, and detail inspectors. |
| `frontend/js/app.js` | Added graph validation, layout/rendering, interactions, status highlighting, and filter reset on notebook change. |
| `frontend/css/style.css` | Styled the graph, controls, details, and evidence statuses within the existing theme. |
| `README.md` | Documented the interactive graph, response schema, generation, and limitations. |
| `completion.md` | Recorded this completed phase and actual verification results. |

### Dependencies

No dependencies were added, removed, or changed.

### Verification results

| Check | Actual result |
|---|---|
| `venv\Scripts\python.exe -m pytest tests\ -q` | **54 passed, 0 failed**; one existing Starlette/AnyIO `BlockingPortal` deprecation warning. |
| Focused upload and graph tests | **23 passed, 0 failed**; same dependency deprecation warning. |
| `node --check frontend\js\app.js` | Passed. |
| `venv\Scripts\python.exe -m compileall -q backend\app` | Passed. |
| `git diff --check` | Passed; Git emitted only existing line-ending conversion warnings. |
| Browser upload and graph interaction with `testing/clean_ml_workflow.ipynb` | Passed; rendered 8 recognized operations and 10 dependency edges. Node selection/details, edge selection/details, type filtering, finding filtering, fit, zoom, and reset worked. |
| Browser upload with `testing/preprocessing_before_split.ipynb` | Passed; the two evidence-associated operations were amber, no nodes were red, and finding-path highlighting activated. |
| Browser change from a finding-filtered notebook to a clean notebook | Passed; the finding filter reset to all operations and rendered the new notebook's 8 nodes. |

### Known limitations

- The graph remains static source inference, not runtime tracing. Notebook source order helps identify earlier assignments but does not establish execution order or prove runtime transfer.
- Variable aliases, dynamic dispatch, control flow, repeated assignments/execution, generated code, and library-specific semantics may not be resolved.
- Detection is limited to operations recognized by the existing analyzer; unknown dependencies remain unresolved rather than guessed.
- Current audit findings are potential risks, so red confirmed-finding indicators are supported by the graph schema but are not emitted by current audit rules.
- Graph data is included in the transient upload response; notebooks are not persisted and there is no notebook-ID retrieval endpoint.

## Leakage and Evaluation Detection

**Date completed:** 2026-10-31

### Completed work

1. Extended the existing AST analysis and Phase 2 operation dependencies with bounded, source-grounded checks for preprocessing fitted before a later split, target-derived features, suspicious post-outcome feature names, test metrics used for model selection, test data passed to fitting, training data used for evaluation, and classifier splits without stratification.
2. Preserved evidence references, confidence, severity, limitations, and links to the relevant pipeline operations. Potential or heuristic findings are not presented as runtime-confirmed defects.
3. Added `POST /api/datasets/overlap` for explicitly uploaded train/test CSVs. It reports exact-row and user-selected identifier/group overlap counts without returning the values or retaining the uploads.
4. Extended the existing Audit workspace with severity/category filtering, finding evidence, source-cell and pipeline-node navigation, and the optional split-comparison form.
5. Fixed the overlap-response validator's scope so the successful comparison response is handled by the browser UI.
6. Documented the supported rules, API, response semantics, and analysis limitations in README.md.

### Existing functionality reused

- Reused the notebook parser and AST-extracted operations, Phase 2 dependency graph, upload response, and existing audit findings.
- Reused the FastAPI multipart endpoint patterns, configured per-file upload limit, and existing notebook workspace and light theme.
- Notebook code and notebook-referenced paths remain unexecuted and unopened. Dataset comparison occurs only when the user explicitly uploads both CSV files.

### Files created

| Path | Purpose |
|---|---|
| `backend/app/services/detection_engine.py` | Adds source/dependency-based notebook leakage and evaluation checks. |
| `backend/app/services/dataset_overlap.py` | Performs in-memory split overlap checks without returning raw values. |
| `tests/test_detection_engine.py` | Tests supported risk patterns and negative cases. |
| `tests/test_dataset_overlap.py` | Tests overlap endpoint checks and validation. |
| `testing/train_split_overlap.csv` | Synthetic training split for overlap validation. |
| `testing/test_split_overlap.csv` | Synthetic test split for overlap validation. |

### Files modified

| Path | Change |
|---|---|
| `backend/app/main.py` | Adds the train/test CSV overlap endpoint. |
| `backend/app/services/audit_analyzer.py` | Removes the overly broad preprocessing signal in favor of dependency-aware detection. |
| `backend/app/services/notebook_analyzer.py` | Records AST evidence used by the detection engine and attaches findings to the existing analysis. |
| `frontend/index.html` | Adds audit filters, finding navigation, and split-comparison controls. |
| `frontend/js/app.js` | Adds audit rendering and comparison behavior; moves the overlap response validator to top-level scope. |
| `frontend/css/style.css` | Styles the audit and comparison UI within the existing theme. |
| `tests/test_notebook_upload.py` | Covers findings in upload analysis and pipeline association. |
| `README.md` | Documents detection rules, endpoint behavior, and limitations. |
| `completion.md` | Records this completed phase and its verification. |

### Dependencies

No dependencies were added, removed, or changed.

### Verification results

| Check | Actual result |
|---|---|
| `.\venv\Scripts\python.exe -m pytest -q` | **79 passed, 0 failed**; one existing Starlette/AnyIO deprecation warning. |
| `node --check frontend\js\app.js` | Passed. |
| `.\venv\Scripts\python.exe -m compileall -q backend\app` | Passed. |
| `git diff --check` | Passed; Git reported line-ending conversion warnings only. |
| Browser: preprocessing-before-split notebook | Passed; one potential finding displayed with evidence; source-cell navigation opened Cell 3 and pipeline-node navigation selected the associated finding node. |
| Browser: audit filters and graph finding filter | Passed; severity filters selected the expected counts and graph filtering displayed the two finding-associated operations. |
| Browser: uploaded split comparison | Passed; exact row overlap 0, identifier overlap 1, group overlap 1; identifiers/group values were absent from the UI response. |
| Browser: overlap response validation | Passed; `isOverlapSuccessResponse` was available and the comparison completed successfully. |

### Known limitations

- Static checks infer risks from recognizable AST patterns, source order, variable references, and limited name heuristics; they cannot establish runtime data contents, execution order, intent, or all aliases/control flow.
- Stratification is an informational review prompt; class balance and suitability are unknown.
- Dataset overlap is separate from notebook analysis because notebook-referenced files are not accessed and uploads are not persisted. Identifier/group semantics are supplied by the user.
- Exact duplicate feature rows alone do not prove entity leakage. The endpoint reports counts only and processes files in memory.
- Findings remain potential risks or review prompts; no rule in this phase confirms a runtime defect.

---

## Automated Repair Engine

**Date completed:** 2026-11-02

### Completed work

1. Added `notebook.analysis.repairs`, classifying each notebook finding as automatically repairable, requiring manual intervention, or not repairable with the available evidence.
2. Implemented two deterministic, evidence-bound repair templates: move a recognized imported sklearn `fit_transform` operation after a simple train/test split, and remove an exact target column from a literal feature selection when a preceding assignment selects that same dataframe column for the target.
3. Added Python syntax, identifier, rule-pattern, conflict, and nbformat validation. Experiment verification remains explicitly unperformed.
4. Added the Repair Center to the existing workspace. It shows original/proposed code, a diff, affected cells, explanations, limitations, and validation; users must individually approve or reject repairable proposals.
5. Added `POST /api/notebooks/repairs/generate`, which accepts the original notebook and approved repair IDs and returns a separate corrected `.ipynb`. Modified code-cell outputs and execution counts are cleared; notebook order and metadata are preserved, and the original upload is not modified.
6. Kept dataset overlap findings manual because the separately uploaded datasets are not linked to specific notebook split statements. Other unsupported or ambiguous findings do not receive speculative code edits.
7. Updated README.md with the implemented repair scope, API, validation, workflow, and limitations.

### Existing functionality reused

- Reused Phase 3 findings and the existing AST notebook analysis; repair proposals are generated from the same parsed source and actual rule IDs.
- Reused the existing notebook upload, nbformat validation, configured upload size limit, multipart API pattern, and current workspace/navigation and light theme.
- Repair selections remain in browser memory and are submitted with the original file because notebooks are not persisted by the application.

### Files created

| Path | Purpose |
|---|---|
| `backend/app/services/repair_engine.py` | Classifies findings, constructs deterministic proposals, validates edits/conflicts, and generates corrected notebook JSON. |
| `tests/test_repair_engine.py` | Covers repairability, manual/unsupported cases, syntax checks, conflicts, metadata/output preservation, original preservation, and API generation. |

### Files modified

| Path | Change |
|---|---|
| `backend/app/main.py` | Adds the approved-repair notebook generation endpoint. |
| `backend/app/services/notebook_parser.py` | Adds the repair classification/proposals to the existing analysis response. |
| `frontend/index.html` | Adds Repair Center links and the existing-template repair workspace. |
| `frontend/js/app.js` | Adds proposal rendering, per-repair approval/rejection, and separate notebook download flow. |
| `frontend/css/style.css` | Styles Repair Center summaries, code, diffs, and responsive layout within the existing theme. |
| `README.md` | Documents repair templates, endpoint, validation, workflow, and limitations. |
| `completion.md` | Records this completed phase and actual verification. |

### Dependencies

No dependencies were added, removed, or changed.

### Verification results

| Check | Actual result |
|---|---|
| `.\venv\Scripts\python.exe -m pytest -q` | **99 passed, 0 failed**; one existing Starlette/AnyIO deprecation warning. |
| `.\venv\Scripts\python.exe -m compileall -q backend\app tests` | Passed. |
| `node --check frontend\js\app.js` | Passed. |
| `git diff --check` | Passed; Git reported line-ending conversion warnings only. |
| Browser: preprocessing leakage repair | The existing notebook fixture uploaded; the finding, original/proposed source, diff, and validation appeared in Repair Center. Rejecting disabled generation; approving enabled it and the UI reported the corrected notebook download. The browser harness did not expose a download event; the endpoint's file generation and nbformat validation were verified by automated tests. |
| API: corrected notebook generation | Passed; approved repair produced a separate nbformat-valid notebook with metadata preserved and modified-cell outputs/counts cleared. |

### Known limitations

- Automatic preprocessing repair requires a single top-level imported sklearn transformer `fit_transform` assignment, one simple `train_test_split`, recognizable `X_train`/`X_test` outputs, and no unrelated transformed-variable uses. More complex pipelines, aliases, split arrangements, or multiple edits remain manual.
- Target-column repair supports only a simple single-line literal string column list and a preceding target assignment from the same dataframe; commented/multiline lists and derived or indirect target leakage remain manual.
- Test-set contamination, group-aware splits, and train/test CSV overlap are manual-review cases. The engine does not guess identifiers, move tuning code, remove duplicate records, or add imports.
- Static checks, syntax validation, and nbformat validation do not prove semantic correctness. Notebook code is never executed; no experiment verification is claimed.
- The API is stateless and keeps no approval record or uploaded notebook. Browser approval/rejection state lasts only for the current page session.
