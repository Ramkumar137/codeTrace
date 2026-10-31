"""
CodeTrace – FastAPI application entry point.

FastAPI application with health checks and validated notebook upload.
"""

import logging
import json
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from backend.app.models.dataset import DatasetAnalysisResponse
from backend.app.models.notebook import NotebookUploadResponse
from backend.app.services.dataset_analyzer import (
    DatasetAnalysisError,
    analyze_csv_dataset,
)
from backend.app.services.dataset_overlap import analyze_train_test_overlap
from backend.app.services.notebook_parser import NotebookParseError, parse_notebook
from backend.app.services.repair_engine import RepairError, generate_corrected_notebook


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
    description="Validates notebooks and analyzes explicitly uploaded CSV datasets for CodeTrace.",
    version="0.1.0",
)

# Origins allowed to call this API during local development.
# Add or remove entries here when the deployment origin changes.
ALLOWED_ORIGINS = [
    "http://127.0.0.1:5500",   # VS Code Live Server default
    "http://localhost:5500",
    "http://127.0.0.1:8080",   # common alternative dev-server port
    "http://localhost:8080",
    "null",                    # browsers send "null" when the page is opened as a local file
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
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
    """Validate and parse one notebook without storing or executing it."""
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

        return {"status": "success", "notebook": notebook}
    finally:
        await file.close()


@app.post(
    "/api/notebooks/repairs/generate",
    tags=["notebooks"],
)
async def generate_notebook_repairs(
    file: UploadFile | str | None = File(default=None),
    repair_ids: str = Form(default="[]"),
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

        return Response(
            content=corrected_content,
            media_type="application/x-ipynb+json",
            headers={
                "Content-Disposition": (
                    f"attachment; filename*=UTF-8''{quote(corrected_filename)}"
                )
            },
        )
    finally:
        await file.close()


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
