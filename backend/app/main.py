"""
CodeTrace – FastAPI application entry point.

FastAPI application with health checks and validated notebook upload.
"""

import logging
import json
import hashlib
import hmac
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import (
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware

from backend.app.models.dataset import DatasetAnalysisResponse
from backend.app.models.execution import ExecutionRequest, ExecutionStatusResponse
from backend.app.models.notebook import NotebookUploadResponse
from backend.app.services.dataset_analyzer import (
    DatasetAnalysisError,
    analyze_csv_dataset,
)
from backend.app.services.dataset_overlap import analyze_train_test_overlap
from backend.app.services.notebook_parser import NotebookParseError, parse_notebook
from backend.app.services.repair_engine import RepairError, generate_corrected_notebook
from backend.app.services.execution_manager import (
    ExecutionManager,
    ExecutionRequestError,
)
from backend.app.services.execution_store import ExecutionStore


DEFAULT_MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_SIZE_BYTES = int(
    os.environ.get("CODETRACE_MAX_UPLOAD_SIZE_BYTES", DEFAULT_MAX_UPLOAD_SIZE_BYTES)
)
if MAX_UPLOAD_SIZE_BYTES <= 0:
    raise RuntimeError("CODETRACE_MAX_UPLOAD_SIZE_BYTES must be greater than zero.")


class HealthCheckAccessLogFilter(logging.Filter):
    """Hide successful health-check requests from Uvicorn's access log."""

    def filter(self, record: logging.LogRecord) -> bool:
        arguments = record.args
        if not isinstance(arguments, tuple) or len(arguments) < 5:
            return True
        _, method, path, _, status_code = arguments[:5]
        return not (
            method == "GET"
            and isinstance(path, str)
            and path.split("?", maxsplit=1)[0] == "/api/health"
            and status_code == 200
        )


logging.getLogger("uvicorn.access").addFilter(HealthCheckAccessLogFilter())

app = FastAPI(
    title="CodeTrace API",
    description=(
        "Validates and analyzes notebooks, and supports explicitly requested "
        "Docker-isolated notebook experiments."
    ),
    version="0.1.0",
)

execution_store: ExecutionStore | None = None
execution_manager: ExecutionManager | None = None


def _get_execution_store() -> ExecutionStore:
    global execution_store
    if execution_store is None:
        execution_store = ExecutionStore()
    return execution_store


def _get_execution_manager() -> ExecutionManager:
    global execution_manager
    if execution_manager is None:
        execution_manager = ExecutionManager(_get_execution_store())
    return execution_manager


def _require_access_token(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "unauthorized",
                "message": "A valid notebook access token is required.",
            },
        )
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "unauthorized",
                "message": "A valid notebook access token is required.",
            },
        )
    return token


def _authorized_notebook(notebook_id: str, token: str) -> dict:
    notebook = _get_execution_store().get_notebook(notebook_id, token)
    if notebook is None:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "unauthorized",
                "message": "A valid notebook access token is required.",
            },
        )
    return notebook


# Origins allowed to call this API during local development.
# Add or remove entries here when the deployment origin changes.
ALLOWED_ORIGINS = [
    "http://127.0.0.1:5500",   # VS Code Live Server default
    "http://localhost:5500",
    "http://127.0.0.1:8080",   # common alternative dev-server port
    "http://localhost:8080",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-CodeTrace-Notebook-ID"],
)


@app.get("/", tags=["health"])
def read_root():
    """Root endpoint – confirms the API is running."""
    return {"status": "ok", "message": "CodeTrace API is running."}


@app.get("/api/health", tags=["health"])
def api_health():
    """Health-check endpoint consumed by the frontend status panel."""
    return {"status": "healthy", "service": "CodeTrace API"}


@app.post(
    "/api/notebooks/upload",
    response_model=NotebookUploadResponse,
    tags=["notebooks"],
)
async def upload_notebook(file: UploadFile | str | None = File(default=None)):
    """Validate and statically analyze a notebook; retain it for explicit experiments."""
    if file is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "missing_file",
                "message": "Select a Jupyter Notebook file to upload.",
            },
        )
    if isinstance(file, str):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "missing_filename",
                "message": "The uploaded file must have a filename.",
            },
        )

    try:
        filename = file.filename
        if not filename or not filename.strip():
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "missing_filename",
                    "message": "The uploaded file must have a filename.",
                },
            )
        if Path(filename).suffix.lower() != ".ipynb":
            raise HTTPException(
                status_code=415,
                detail={
                    "code": "unsupported_file_type",
                    "message": "Only files with the .ipynb extension are accepted.",
                },
            )

        content = await file.read(MAX_UPLOAD_SIZE_BYTES + 1)
        if not content:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "empty_file",
                    "message": "The uploaded notebook file is empty.",
                },
            )
        if len(content) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "file_too_large",
                    "message": (
                        "The uploaded notebook exceeds the configured size limit of "
                        f"{MAX_UPLOAD_SIZE_BYTES} bytes."
                    ),
                },
            )

        try:
            notebook = parse_notebook(filename, content)
        except NotebookParseError as error:
            raise HTTPException(
                status_code=error.status_code,
                detail={"code": error.code, "message": error.message},
            ) from error

        notebook_id, access_token = _get_execution_store().create_original_notebook(
            filename, content
        )
        return {
            "status": "success",
            "notebook_id": notebook_id,
            "access_token": access_token,
            "notebook": notebook,
        }
    finally:
        await file.close()


@app.post(
    "/api/notebooks/repairs/generate",
    tags=["notebooks"],
)
async def generate_notebook_repairs(
    file: UploadFile | str | None = File(default=None),
    repair_ids: str = Form(default="[]"),
    notebook_id: str | None = Form(default=None),
    authorization: str | None = Header(default=None),
):
    """Generate a separate notebook from explicitly approved deterministic repairs."""
    if file is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "missing_file", "message": "Select the original notebook file."},
        )
    if isinstance(file, str):
        raise HTTPException(
            status_code=400,
            detail={"code": "missing_filename", "message": "The notebook file needs a filename."},
        )

    try:
        filename = file.filename
        if not filename or not filename.strip():
            raise HTTPException(
                status_code=400,
                detail={"code": "missing_filename", "message": "The notebook file needs a filename."},
            )
        if Path(filename).suffix.lower() != ".ipynb":
            raise HTTPException(
                status_code=415,
                detail={
                    "code": "unsupported_file_type",
                    "message": "Only files with the .ipynb extension are accepted.",
                },
            )
        content = await file.read(MAX_UPLOAD_SIZE_BYTES + 1)
        if not content:
            raise HTTPException(
                status_code=400,
                detail={"code": "empty_file", "message": "The uploaded notebook is empty."},
            )
        if len(content) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "file_too_large",
                    "message": (
                        "The uploaded notebook exceeds the configured size limit of "
                        f"{MAX_UPLOAD_SIZE_BYTES} bytes."
                    ),
                },
            )

        original_record = None
        if notebook_id:
            token = _require_access_token(authorization)
            original_record = _get_execution_store().get_notebook_for_repair(
                notebook_id, token
            )
            if original_record is None:
                raise HTTPException(
                    status_code=401,
                    detail={
                        "code": "unauthorized",
                        "message": "A valid original notebook access token is required.",
                    },
                )
            if not hmac.compare_digest(
                hashlib.sha256(content).digest(),
                hashlib.sha256(bytes(original_record["content"])).digest(),
            ):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "notebook_mismatch",
                        "message": (
                            "The repair input does not match the stored original notebook."
                        ),
                    },
                )

        try:
            selected_ids = json.loads(repair_ids)
        except json.JSONDecodeError as error:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_repair_ids", "message": "Repair selections must be valid JSON."},
            ) from error
        if (
            not isinstance(selected_ids, list)
            or not selected_ids
            or any(not isinstance(item, str) for item in selected_ids)
            or len(selected_ids) != len(set(selected_ids))
        ):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_repair_ids",
                    "message": "Approve one or more distinct repair IDs.",
                },
            )

        try:
            parse_notebook(filename, content)
            corrected_content, corrected_filename = generate_corrected_notebook(
                content, filename, selected_ids
            )
        except NotebookParseError as error:
            raise HTTPException(
                status_code=error.status_code,
                detail={"code": error.code, "message": error.message},
            ) from error
        except RepairError as error:
            raise HTTPException(
                status_code=error.status_code,
                detail={"code": error.code, "message": error.message},
            ) from error

        response_headers = {
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(corrected_filename)}"
            )
        }
        if original_record is not None:
            corrected_id = _get_execution_store().create_corrected_notebook(
                original_record, corrected_filename, corrected_content
            )
            response_headers["X-CodeTrace-Notebook-ID"] = corrected_id

        return Response(
            content=corrected_content,
            media_type="application/x-ipynb+json",
            headers=response_headers,
        )
    finally:
        await file.close()


@app.post("/api/notebooks/{notebook_id}/datasets", tags=["datasets"])
async def attach_execution_dataset(
    notebook_id: str,
    file: UploadFile | str | None = File(default=None),
    authorization: str | None = Header(default=None),
):
    """Persist one explicitly selected CSV for later isolated execution."""
    token = _require_access_token(authorization)
    notebook = _authorized_notebook(notebook_id, token)
    if notebook["notebook_type"] != "original":
        raise HTTPException(
            status_code=422,
            detail={
                "code": "dataset_owner_must_be_original",
                "message": "Execution datasets must be associated with the original notebook.",
            },
        )
    if file is None or isinstance(file, str):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "missing_file",
                "message": "Select a CSV dataset file to attach.",
            },
        )
    try:
        filename = file.filename
        if not filename or not filename.strip():
            raise HTTPException(
                status_code=400,
                detail={"code": "missing_filename", "message": "The dataset needs a filename."},
            )
        if Path(filename).suffix.lower() != ".csv":
            raise HTTPException(
                status_code=415,
                detail={
                    "code": "unsupported_file_type",
                    "message": "Only CSV datasets can be associated with an execution.",
                },
            )
        content = await file.read(MAX_UPLOAD_SIZE_BYTES + 1)
        if not content:
            raise HTTPException(
                status_code=400,
                detail={"code": "empty_file", "message": "The uploaded CSV is empty."},
            )
        if len(content) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "file_too_large",
                    "message": (
                        "The uploaded dataset exceeds the configured size limit of "
                        f"{MAX_UPLOAD_SIZE_BYTES} bytes."
                    ),
                },
            )
        try:
            analyze_csv_dataset(filename, content)
        except DatasetAnalysisError as error:
            raise HTTPException(
                status_code=error.status_code,
                detail={"code": error.code, "message": error.message},
            ) from error
        dataset_id = _get_execution_store().add_dataset(
            notebook["notebook_id"], filename, content
        )
        return {
            "status": "success",
            "dataset": {"dataset_id": dataset_id, "filename": filename},
        }
    finally:
        await file.close()


@app.get("/api/notebooks/{notebook_id}/datasets", tags=["datasets"])
async def list_execution_datasets(
    notebook_id: str,
    authorization: str | None = Header(default=None),
):
    """List datasets explicitly associated with an authorized notebook."""
    token = _require_access_token(authorization)
    notebook = _authorized_notebook(notebook_id, token)
    if notebook["notebook_type"] != "original":
        raise HTTPException(
            status_code=422,
            detail={
                "code": "dataset_owner_must_be_original",
                "message": "Execution datasets are listed from the original notebook.",
            },
        )
    return {
        "datasets": _get_execution_store().list_datasets(notebook_id),
    }


@app.post(
    "/api/notebooks/{notebook_id}/executions",
    response_model=ExecutionStatusResponse,
    status_code=202,
    tags=["executions"],
)
async def start_notebook_execution(
    notebook_id: str,
    request: ExecutionRequest,
    authorization: str | None = Header(default=None),
):
    """Explicitly enqueue this original or approved corrected notebook."""
    token = _require_access_token(authorization)
    notebook = _authorized_notebook(notebook_id, token)
    if notebook["notebook_type"] == "corrected" and not notebook["approved"]:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "corrected_notebook_not_approved",
                "message": "Only an approved corrected notebook can be executed.",
            },
        )
    try:
        execution = await _get_execution_manager().start(
            notebook, request.dataset_ids, token
        )
    except ExecutionRequestError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_execution_request", "message": str(error)},
        ) from error
    if execution["status"] == "unavailable":
        raise HTTPException(
            status_code=503,
            detail={
                "code": "execution_unavailable",
                "message": execution["error_details"]["message"],
                "execution": execution,
            },
        )
    return execution


@app.get(
    "/api/executions/{execution_id}",
    response_model=ExecutionStatusResponse,
    tags=["executions"],
)
async def get_notebook_execution(
    execution_id: str,
    authorization: str | None = Header(default=None),
):
    """Get persisted status, captured cell results, and environment metadata."""
    token = _require_access_token(authorization)
    execution = _get_execution_store().get_execution(execution_id, token)
    if execution is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "execution_not_found",
                "message": "The execution was not found or is not accessible.",
            },
        )
    return execution


@app.get("/api/executions/{execution_id}/notebook", tags=["executions"])
async def download_executed_notebook(
    execution_id: str,
    authorization: str | None = Header(default=None),
):
    """Download a generated notebook artifact only after an authorized run."""
    token = _require_access_token(authorization)
    execution = _get_execution_store().get_execution(execution_id, token)
    if execution is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "execution_not_found",
                "message": "The execution was not found or is not accessible.",
            },
        )
    artifact = _get_execution_store().get_artifact(execution_id, token)
    if artifact is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "execution_artifact_unavailable",
                "message": "No executed notebook artifact is available for this run.",
            },
        )
    filename = Path(execution["notebook_filename"]).stem + "-executed.ipynb"
    return Response(
        content=artifact,
        media_type="application/x-ipynb+json",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )


@app.post(
    "/api/executions/{execution_id}/cancel",
    response_model=ExecutionStatusResponse,
    tags=["executions"],
)
async def cancel_notebook_execution(
    execution_id: str,
    authorization: str | None = Header(default=None),
):
    """Cancel an active run by stopping its isolated Docker container."""
    token = _require_access_token(authorization)
    execution = _get_execution_store().get_execution(execution_id, token)
    if execution is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "execution_not_found",
                "message": "The execution was not found or is not accessible.",
            },
        )
    cancelled = await _get_execution_manager().cancel(execution_id)
    if not cancelled:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "execution_not_active",
                "message": "Only an active execution can be cancelled.",
            },
        )
    result = _get_execution_store().get_execution(execution_id, token)
    if result is None:
        raise RuntimeError("The cancelled execution could not be loaded.")
    return result


@app.post(
    "/api/datasets/analyze",
    response_model=DatasetAnalysisResponse,
    tags=["datasets"],
)
async def analyze_dataset(file: UploadFile | str | None = File(default=None)):
    """Analyze an explicitly uploaded CSV in memory without saving its contents."""
    if file is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "missing_file",
                "message": "Select a CSV dataset file to analyze.",
            },
        )
    if isinstance(file, str):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "missing_filename",
                "message": "The uploaded file must have a filename.",
            },
        )

    try:
        filename = file.filename
        if not filename or not filename.strip():
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "missing_filename",
                    "message": "The uploaded file must have a filename.",
                },
            )
        if Path(filename).suffix.lower() != ".csv":
            raise HTTPException(
                status_code=415,
                detail={
                    "code": "unsupported_file_type",
                    "message": "Only files with the .csv extension are accepted.",
                },
            )

        content = await file.read(MAX_UPLOAD_SIZE_BYTES + 1)
        if not content:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "empty_file",
                    "message": "The uploaded CSV file is empty.",
                },
            )
        if len(content) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "file_too_large",
                    "message": (
                        "The uploaded dataset exceeds the configured size limit of "
                        f"{MAX_UPLOAD_SIZE_BYTES} bytes."
                    ),
                },
            )

        try:
            dataset = analyze_csv_dataset(filename, content)
        except DatasetAnalysisError as error:
            raise HTTPException(
                status_code=error.status_code,
                detail={"code": error.code, "message": error.message},
            ) from error

        return {"status": "success", "dataset": dataset}
    finally:
        await file.close()


async def _read_overlap_upload(
    file: UploadFile | str | None, label: str
) -> tuple[str, bytes]:
    if file is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": f"missing_{label}_file",
                "message": f"Select a {label} CSV file.",
            },
        )
    if isinstance(file, str):
        raise HTTPException(
            status_code=400,
            detail={
                "code": f"missing_{label}_filename",
                "message": f"The {label} upload must have a filename.",
            },
        )
    if not file.filename or Path(file.filename).suffix.lower() != ".csv":
        raise HTTPException(
            status_code=415,
            detail={
                "code": "unsupported_file_type",
                "message": f"The {label} upload must be a .csv file.",
            },
        )
    content = await file.read(MAX_UPLOAD_SIZE_BYTES + 1)
    if not content:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "empty_file",
                "message": f"The {label} CSV file is empty.",
            },
        )
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "file_too_large",
                "message": (
                    f"The {label} CSV exceeds the configured size limit of "
                    f"{MAX_UPLOAD_SIZE_BYTES} bytes."
                ),
            },
        )
    return file.filename, content


@app.post("/api/datasets/overlap", tags=["datasets"])
async def compare_train_test_datasets(
    train_file: UploadFile | str | None = File(default=None),
    test_file: UploadFile | str | None = File(default=None),
    identifier_column: str | None = Form(default=None),
    group_column: str | None = Form(default=None),
):
    """Compare separately uploaded training and test CSVs without saving row values."""
    files = [file for file in (train_file, test_file) if isinstance(file, UploadFile)]
    try:
        train_filename, train_content = await _read_overlap_upload(
            train_file, "training"
        )
        test_filename, test_content = await _read_overlap_upload(test_file, "test")
        try:
            result = analyze_train_test_overlap(
                train_filename,
                train_content,
                test_filename,
                test_content,
                identifier_column=identifier_column,
                group_column=group_column,
            )
        except DatasetAnalysisError as error:
            raise HTTPException(
                status_code=error.status_code,
                detail={"code": error.code, "message": error.message},
            ) from error
        return {"status": "success", "overlap": result}
    finally:
        for file in files:
            await file.close()
