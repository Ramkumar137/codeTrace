"""Validation and metadata extraction for Jupyter Notebook files."""

import json
from typing import Any

import nbformat

from backend.app.services.notebook_analyzer import analyze_notebook

class NotebookParseError(Exception):
    """A user-correctable error in an uploaded notebook."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def parse_notebook(filename: str, content: bytes) -> dict[str, Any]:
    """Validate an nbformat v4 notebook and return source-only metadata."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise NotebookParseError(
            "invalid_notebook_json",
            "The uploaded file must contain valid UTF-8 notebook JSON.",
            400,
        ) from error

    try:
        raw_notebook = json.loads(text)
    except json.JSONDecodeError as error:
        raise NotebookParseError(
            "invalid_notebook_json",
            "The uploaded file does not contain valid JSON.",
            400,
        ) from error

    if not isinstance(raw_notebook, dict):
        raise NotebookParseError(
            "invalid_notebook_structure",
            "The JSON document must be a Jupyter Notebook object.",
            422,
        )

    format_version = raw_notebook.get("nbformat")
    if isinstance(format_version, bool) or not isinstance(format_version, int):
        raise NotebookParseError(
            "invalid_notebook_structure",
            "The notebook must specify a valid nbformat version.",
            422,
        )
    if format_version != 4:
        raise NotebookParseError(
            "unsupported_notebook_version",
            "Only Jupyter Notebook format version 4 is supported.",
            422,
        )

    try:
        notebook = nbformat.reads(text, as_version=nbformat.NO_CONVERT)
        nbformat.validate(notebook)
    except (
        nbformat.NBFormatError,
        nbformat.ValidationError,
        TypeError,
        ValueError,
    ) as error:
        raise NotebookParseError(
            "invalid_notebook_structure",
            "The uploaded JSON does not have a valid Jupyter Notebook structure.",
            422,
        ) from error

    cells: list[dict[str, Any]] = []
    counts = {"code": 0, "markdown": 0, "raw": 0}

    for index, cell in enumerate(notebook.cells):
        cell_type = cell.cell_type
        counts[cell_type] += 1
        source = cell.source
        if isinstance(source, list):
            source = "".join(source)

        is_code = cell_type == "code"
        cells.append(
            {
                "index": index,
                "cell_type": cell_type,
                "source": source,
                "execution_count": cell.execution_count if is_code else None,
                "has_outputs": bool(cell.outputs) if is_code else False,
            }
        )

    result = {
        "filename": filename,
        "format_version": format_version,
        "total_cells": len(cells),
        "code_cells": counts["code"],
        "markdown_cells": counts["markdown"],
        "raw_cells": counts["raw"],
        "cells": cells,
    }
    result["analysis"] = analyze_notebook(cells)
    return result
