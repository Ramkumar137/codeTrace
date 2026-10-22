"""
CodeTrace – FastAPI application entry point.

FastAPI application with health checks and validated notebook upload.
"""

import os
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from backend.app.models.notebook import NotebookUploadResponse
from backend.app.services.notebook_parser import NotebookParseError, parse_notebook


DEFAULT_MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_SIZE_BYTES = int(
    os.environ.get("CODETRACE_MAX_UPLOAD_SIZE_BYTES", DEFAULT_MAX_UPLOAD_SIZE_BYTES)
)
if MAX_UPLOAD_SIZE_BYTES <= 0:
    raise RuntimeError("CODETRACE_MAX_UPLOAD_SIZE_BYTES must be greater than zero.")

app = FastAPI(
    title="CodeTrace API",
    description="Validates and parses Jupyter Notebooks for CodeTrace.",
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
