# Setup and local development

This project is a Python + FastAPI application with a static frontend. It does not require Postman or external service integration for basic local use.

## Prerequisites

- Python 3.11 or newer
- A local virtual environment
- Optional: Docker for isolated experiment execution
- Optional: a local static file server for serving the frontend

## Installation

Create a virtual environment and install the dependencies:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On macOS/Linux, activate with `source venv/bin/activate`.

## Run the backend

```text
uvicorn backend.app.main:app --reload
```

The API is available at http://127.0.0.1:8000.

## Run the frontend

The frontend is static HTML and JavaScript. It can be opened directly from the frontend folder or served locally.

```text
python -m http.server 5500 --directory frontend
```
Alternatively, open `frontend/index.html` directly in a browser.


## Optional Docker execution

Docker is only required for the explicit isolated execution flow. If the configured image is unavailable, the execution API reports an unavailable status rather than running notebook code on the application host.

Build the versioned runner image from the repository root:

```powershell
docker build -t codetrace-notebook-runner:1.0.0 backend/execution
$env:CODETRACE_EXECUTION_IMAGE = "codetrace-notebook-runner:1.0.0"
uvicorn backend.app.main:app --reload
```

The runner is non-root, network-disabled, and resource-limited. It does not install arbitrary notebook dependencies. Add an allowed package by reviewing and pinning its exact version in `backend/execution/Dockerfile`, rebuilding and scanning the image, and configuring a fixed image tag or digest. Do not enable notebook-time network installation.

## Experiment history

The frontend can record and display explicit experiment records. API users can use the authenticated `POST` and `GET /api/notebooks/{notebook_id}/experiment-history` routes; see the request model in `backend/app/models/experiment.py`. Repeated test-driven selection is reported only from multiple persisted records tied to the same dataset fingerprint.

## Benchmark

Run the synthetic benchmark from the repository root:

```powershell
python -m backend.app.services.benchmark_evaluator --output-dir benchmark-results
```

It writes JSON metrics and a Markdown report. Fixture-set results are not production performance estimates; repair checks are source-only, and the verification metric only validates conservative behavior when execution is unavailable.

## Verification

Run the project test suite:

```text
python -m pytest tests -q
```

Use the result from the current checkout; earlier test counts are not evidence that subsequent changes pass.

## Troubleshooting

### API health check fails

- confirm the backend is running on the expected port
- check the /api/health route
- confirm the frontend is being served from a recognized local origin

### Notebook upload fails

- validate the file extension is .ipynb
- confirm the notebook is valid JSON and nbformat v4
- confirm the file size is below the configured limit

### CSV analysis fails

- use a valid UTF-8 CSV file
- ensure headers are non-empty and unique
- check the API validation message for the specific issue

### Docker execution is unavailable

- confirm Docker is installed and running
- verify the configured image name is valid
- check execution-manager and runner logs for startup failures

## Notes

- The project is designed around static analysis and explicit review.
- It does not execute notebook code during upload or analysis.
- It preserves the original notebook when generating a separate corrected copy.
