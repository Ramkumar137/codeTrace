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
from backend.app.models.verification import VerificationRequest
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
from backend.app.services.verification_engine import build_verification
from backend.app.services.report_service import (
    ReportGenerationError,
    generate_report_artifacts,
)


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
        "Docker-isolated notebook experiments with evidence-based repair verification."
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
    "https://codetrace-1.web.app",
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
            parsed_notebook = parse_notebook(filename, content)
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
            repairs_by_id = {
                repair["repair_id"]: repair
                for repair in parsed_notebook["analysis"]["repairs"]
            }
            findings_by_id = {
                finding["id"]: finding
                for finding in parsed_notebook["analysis"]["findings"]
            }
            approved_repairs = [
                {
                    "repair": repairs_by_id[repair_id],
                    "finding": findings_by_id[repairs_by_id[repair_id]["finding_id"]],
                }
                for repair_id in selected_ids
            ]
            corrected_id = _get_execution_store().create_corrected_notebook(
                original_record,
                corrected_filename,
                corrected_content,
                approved_repairs,
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


@app.get(
    "/api/notebooks/{notebook_id}/executions",
    tags=["executions"],
)
async def list_notebook_executions(
    notebook_id: str,
    authorization: str | None = Header(default=None),
):
    """List saved original/corrected runs without starting new experiments."""
    token = _require_access_token(authorization)
    executions = _get_execution_store().list_executions(notebook_id, token)
    if executions is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "notebook_not_found",
                "message": "The notebook was not found or is not accessible.",
            },
        )
    return {"executions": executions}


@app.post(
    "/api/notebooks/{notebook_id}/verifications",
    tags=["verification"],
)
async def verify_notebook_repairs(
    notebook_id: str,
    request: VerificationRequest,
    authorization: str | None = Header(default=None),
):
    """Verify approved corrections using existing execution records only."""
    token = _require_access_token(authorization)
    store = _get_execution_store()
    original_record = store.get_notebook_for_repair(notebook_id, token)
    if original_record is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "notebook_not_found",
                "message": "The original notebook was not found or is not accessible.",
            },
        )
    corrected_record = store.get_notebook(
        request.corrected_notebook_id, token
    )
    if (
        corrected_record is None
        or corrected_record["notebook_type"] != "corrected"
        or corrected_record["original_notebook_id"] != notebook_id
        or not corrected_record["approved"]
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "corrected_notebook_mismatch",
                "message": "The corrected notebook is not an approved version of this original.",
            },
        )
    approved_repairs = store.get_approved_repairs(
        request.corrected_notebook_id, token
    )
    if not approved_repairs:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "approved_repairs_unavailable",
                "message": "No persisted approved repair evidence is associated with this corrected notebook.",
            },
        )

    original_execution = store.get_execution(request.original_execution_id, token)
    corrected_execution = store.get_execution(request.corrected_execution_id, token)
    if original_execution is None or corrected_execution is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "execution_not_found",
                "message": "One or both execution records were not found or are not accessible.",
            },
        )
    if (
        original_execution["notebook_id"] != notebook_id
        or original_execution["notebook_type"] != "original"
        or corrected_execution["notebook_id"] != request.corrected_notebook_id
        or corrected_execution["notebook_type"] != "corrected"
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "execution_notebook_mismatch",
                "message": "Execution records must belong to the selected original and corrected notebook versions.",
            },
        )
    if any(
        execution["status"] in {"queued", "running"}
        for execution in (original_execution, corrected_execution)
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "execution_not_complete",
                "message": "Wait until both selected executions reach a terminal status before verification.",
            },
        )

    try:
        original_analysis = parse_notebook(
            original_record["filename"], bytes(original_record["content"])
        )
        corrected_analysis = parse_notebook(
            corrected_record["filename"], bytes(corrected_record["content"])
        )
        result = build_verification(
            original_notebook={
                **original_analysis,
                "notebook_id": notebook_id,
            },
            corrected_notebook={
                **corrected_analysis,
                "notebook_id": request.corrected_notebook_id,
            },
            approved_repairs=approved_repairs,
            original_execution=original_execution,
            corrected_execution=corrected_execution,
            selected_repair_ids=request.repair_ids,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_verification_request",
                "message": str(error),
            },
        ) from error
    store.create_verification(result)
    return result


@app.get(
    "/api/notebooks/{notebook_id}/verifications",
    tags=["verification"],
)
async def list_notebook_verifications(
    notebook_id: str,
    authorization: str | None = Header(default=None),
):
    """List immutable verification audit records for an authorized notebook."""
    token = _require_access_token(authorization)
    verifications = _get_execution_store().list_verifications(notebook_id, token)
    if verifications is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "notebook_not_found",
                "message": "The notebook was not found or is not accessible.",
            },
        )
    return {"verifications": verifications}


@app.post("/api/notebooks/{notebook_id}/reports", tags=["reports"])
async def generate_notebook_report(
    notebook_id: str,
    authorization: str | None = Header(default=None),
):
    """Generate an immutable report snapshot from saved notebook workflow records."""
    token = _require_access_token(authorization)
    store = _get_execution_store()
    if store.get_notebook_for_repair(notebook_id, token) is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "notebook_not_found",
                "message": "The original notebook was not found or is not accessible.",
            },
        )
    try:
        report, html_artifact, pdf_artifact = generate_report_artifacts(
            store, notebook_id, token
        )
    except ReportGenerationError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "report_generation_failed",
                "message": str(error),
            },
        ) from error
    store.create_report(report, html_artifact, pdf_artifact)
    return {
        "report_id": report["report_id"],
        "notebook_id": notebook_id,
        "generated_at": report["generated_at"],
        "status": report["status"],
        "schema_version": report["schema_version"],
        "formats": ["html", "pdf", "json"],
        "overview": report["overview"],
    }


@app.get("/api/notebooks/{notebook_id}/reports", tags=["reports"])
async def list_notebook_reports(
    notebook_id: str,
    authorization: str | None = Header(default=None),
):
    """List report snapshots belonging to an authorized original notebook."""
    token = _require_access_token(authorization)
    reports = _get_execution_store().list_reports(notebook_id, token)
    if reports is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "notebook_not_found",
                "message": "The notebook was not found or is not accessible.",
            },
        )
    return {"reports": reports}


@app.get("/api/reports/{report_id}", tags=["reports"])
async def get_report_metadata(
    report_id: str,
    authorization: str | None = Header(default=None),
):
    token = _require_access_token(authorization)
    report = _get_execution_store().get_report(report_id, token)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "report_not_found",
                "message": "The report was not found or is not accessible.",
            },
        )
    return {
        "report_id": report["report_id"],
        "notebook_id": report["notebook_id"],
        "generated_at": report["generated_at"],
        "status": report["status"],
        "schema_version": report["schema_version"],
        "overview": report["report_data"]["overview"],
        "formats": ["html", "pdf", "json"],
    }


@app.get("/api/reports/{report_id}/html", tags=["reports"])
async def preview_report_html(
    report_id: str,
    authorization: str | None = Header(default=None),
):
    token = _require_access_token(authorization)
    report = _get_execution_store().get_report(report_id, token)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "report_not_found",
                "message": "The report was not found or is not accessible.",
            },
        )
    return Response(
        content=report["html_artifact"],
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:;",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline; filename=\"codetrace-report.html\"",
        },
    )


@app.get("/api/reports/{report_id}/json", tags=["reports"])
async def download_report_json(
    report_id: str,
    authorization: str | None = Header(default=None),
):
    token = _require_access_token(authorization)
    report = _get_execution_store().get_report(report_id, token)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "report_not_found",
                "message": "The report was not found or is not accessible.",
            },
        )
    return Response(
        content=json.dumps(
            report["report_data"], ensure_ascii=False, indent=2
        ).encode("utf-8"),
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{report_id}.evidence.json\""
            )
        },
    )


@app.get("/api/reports/{report_id}/pdf", tags=["reports"])
async def download_report_pdf(
    report_id: str,
    authorization: str | None = Header(default=None),
):
    token = _require_access_token(authorization)
    report = _get_execution_store().get_report(report_id, token)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "report_not_found",
                "message": "The report was not found or is not accessible.",
            },
        )
    return Response(
        content=report["pdf_artifact"],
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{report_id}.evidence.pdf\""
            )
        },
    )


@app.get("/api/notebooks/{notebook_id}/artifacts", tags=["artifacts"])
async def list_notebook_artifacts(
    notebook_id: str,
    authorization: str | None = Header(default=None),
):
    """List stored notebook and executed-notebook artifacts without exposing content."""
    token = _require_access_token(authorization)
    store = _get_execution_store()
    versions = store.list_notebook_versions(notebook_id, token)
    if versions is None or not any(
        item["notebook_id"] == notebook_id
        and item["notebook_type"] == "original"
        for item in versions
    ):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "notebook_not_found",
                "message": "The original notebook was not found or is not accessible.",
            },
        )
    notebooks = [
        {
            "notebook_id": version["notebook_id"],
            "notebook_type": version["notebook_type"],
            "filename": version["filename"],
            "created_at": version["created_at"],
            "available": True,
            "download_path": (
                f"/api/notebooks/{notebook_id}/artifacts/notebooks/"
                f"{version['notebook_id']}"
            ),
        }
        for version in versions
    ]
    datasets = [
        {
            "dataset_id": dataset["dataset_id"],
            "filename": dataset["filename"],
            "created_at": dataset["created_at"],
            "available": True,
            "download_path": (
                f"/api/notebooks/{notebook_id}/artifacts/datasets/"
                f"{dataset['dataset_id']}"
            ),
        }
        for dataset in store.list_datasets(notebook_id)
    ]
    executions = store.list_executions(notebook_id, token) or []
    executed_notebooks = [
        {
            "execution_id": execution["execution_id"],
            "notebook_id": execution["notebook_id"],
            "filename": execution["notebook_filename"],
            "available": True,
            "download_path": (
                f"/api/notebooks/{notebook_id}/artifacts/executions/"
                f"{execution['execution_id']}"
            ),
        }
        for execution in executions
        if execution.get("artifact_available")
    ]
    return {
        "notebooks": notebooks,
        "datasets": datasets,
        "executed_notebooks": executed_notebooks,
    }


@app.get(
    "/api/notebooks/{notebook_id}/artifacts/notebooks/{artifact_notebook_id}",
    tags=["artifacts"],
)
async def download_notebook_version(
    notebook_id: str,
    artifact_notebook_id: str,
    authorization: str | None = Header(default=None),
):
    token = _require_access_token(authorization)
    artifact = _get_execution_store().get_notebook_artifact(
        notebook_id, artifact_notebook_id, token
    )
    if artifact is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "artifact_not_found",
                "message": "The notebook artifact was not found or is not accessible.",
            },
        )
    return Response(
        content=artifact["content"],
        media_type="application/x-ipynb+json",
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(artifact['filename'])}"
            )
        },
    )


@app.get(
    "/api/notebooks/{notebook_id}/artifacts/datasets/{dataset_id}",
    tags=["artifacts"],
)
async def download_associated_dataset(
    notebook_id: str,
    dataset_id: str,
    authorization: str | None = Header(default=None),
):
    token = _require_access_token(authorization)
    store = _get_execution_store()
    if store.get_notebook_for_repair(notebook_id, token) is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "artifact_not_found",
                "message": "The dataset artifact was not found or is not accessible.",
            },
        )
    datasets = store.get_datasets(notebook_id, [dataset_id])
    if datasets is None or not datasets:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "artifact_not_found",
                "message": "The dataset artifact was not found or is not accessible.",
            },
        )
    dataset = datasets[0]
    return Response(
        content=dataset["content"],
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(dataset['filename'])}"
            )
        },
    )


@app.get(
    "/api/notebooks/{notebook_id}/artifacts/executions/{execution_id}",
    tags=["artifacts"],
)
async def download_notebook_execution_artifact(
    notebook_id: str,
    execution_id: str,
    authorization: str | None = Header(default=None),
):
    token = _require_access_token(authorization)
    store = _get_execution_store()
    root = store.get_notebook_for_repair(notebook_id, token)
    execution = store.get_execution(execution_id, token)
    if root is None or execution is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "artifact_not_found",
                "message": "The execution artifact was not found or is not accessible.",
            },
        )
    execution_notebook = store.get_notebook(execution["notebook_id"], token)
    if (
        execution_notebook is None
        or (
            execution["notebook_id"] != notebook_id
            and execution_notebook["original_notebook_id"] != notebook_id
        )
        or not execution.get("artifact_available")
    ):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "artifact_not_found",
                "message": "The execution artifact was not found or is not accessible.",
            },
        )
    artifact = store.get_artifact(execution_id, token)
    if artifact is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "artifact_not_found",
                "message": "The execution artifact is no longer available.",
            },
        )
    filename = f"{Path(execution['notebook_filename']).stem}-executed.ipynb"
    return Response(
        content=artifact,
        media_type="application/x-ipynb+json",
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@app.get("/api/verifications/{verification_id}", tags=["verification"])
async def get_verification(
    verification_id: str,
    authorization: str | None = Header(default=None),
):
    token = _require_access_token(authorization)
    result = _get_execution_store().get_verification(verification_id, token)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "verification_not_found",
                "message": "The verification was not found or is not accessible.",
            },
        )
    return result


@app.get(
    "/api/verifications/{verification_id}/findings/{finding_id}",
    tags=["verification"],
)
async def get_finding_verification(
    verification_id: str,
    finding_id: str,
    authorization: str | None = Header(default=None),
):
    token = _require_access_token(authorization)
    result = _get_execution_store().get_verification(verification_id, token)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "verification_not_found",
                "message": "The verification was not found or is not accessible.",
            },
        )
    finding_result = next(
        (
            item
            for item in result["findings"]
            if item["finding_id"] == finding_id
        ),
        None,
    )
    if finding_result is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "finding_verification_not_found",
                "message": "The finding is not included in this verification record.",
            },
        )
    return finding_result


@app.get(
    "/api/verifications/{verification_id}/comparison",
    tags=["verification"],
)
async def get_verification_comparison(
    verification_id: str,
    authorization: str | None = Header(default=None),
):
    token = _require_access_token(authorization)
    result = _get_execution_store().get_verification(verification_id, token)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "verification_not_found",
                "message": "The verification was not found or is not accessible.",
            },
        )
    return result["comparison"]


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
    evaluation_objective: str = Form(default="unspecified"),
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
                evaluation_objective=evaluation_objective,
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
