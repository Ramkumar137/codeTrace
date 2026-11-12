# Setup and local development

This project is a Python + FastAPI application with a static frontend. It does not require Postman or external service integration for basic local use.

## Prerequisites

- Python 3.11 or newer
- A local virtual environment
- Optional: Docker for isolated experiment execution
- Optional: a local static file server for serving the frontend

## Installation

Create a virtual environment and install the dependencies:

```text
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

On Windows PowerShell, activate the virtual environment in the shell before running the application.

## Local configuration

The main runtime settings are:

- CODETRACE_MAX_UPLOAD_SIZE_BYTES: notebook and CSV upload limit in bytes
- CODETRACE_DATA_DIR: SQLite data directory for persisted metadata and executions
- CODETRACE_EXECUTION_IMAGE: Docker image used for isolated execution

Example values:

```text
CODETRACE_MAX_UPLOAD_SIZE_BYTES = 20971520
CODETRACE_DATA_DIR = ~/.codetrace
CODETRACE_EXECUTION_IMAGE = codetrace-notebook-runner:latest
```

## Run the backend

```text
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

The API is available at http://127.0.0.1:8000.

## Run the frontend

The frontend is static HTML and JavaScript. It can be opened directly from the frontend folder or served locally.

```text
python -m http.server 5500 --directory frontend
```

Then open http://localhost:5500 in the browser.

## Optional Docker execution

Docker is only required for the explicit isolated execution flow. If the configured image is unavailable, the execution API reports an unavailable status rather than running notebook code on the application host.

## Verification

Run the project test suite:

```text
python -m pytest tests -q
```

Current repository status: 154 passed, 1 warning.

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
