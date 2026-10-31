"""Bounded analysis of explicitly uploaded CSV datasets."""

import csv
import io
import math
from decimal import Decimal
from typing import Any


class DatasetAnalysisError(Exception):
    """A user-correctable error in an uploaded CSV dataset."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _numeric_value(value: str) -> Decimal | None:
    try:
        number = Decimal(value)
        if not number.is_finite() or not math.isfinite(float(number)):
            return None
        return number
    except (ArithmeticError, ValueError):
        return None


def _column_type(column: dict[str, Any]) -> str:
    if column["non_empty_values"] == 0:
        return "empty"
    if column["all_boolean"]:
        return "boolean"
    if column["all_integer"]:
        return "integer"
    if column["all_numeric"]:
        return "number"
    return "text"


def _format_number(number: Decimal) -> str:
    return format(number, "f")


def analyze_csv_dataset(filename: str, content: bytes) -> dict[str, Any]:
    """Return CSV shape, inferred column types, missingness, and numeric summaries."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise DatasetAnalysisError(
            "invalid_csv_encoding",
            "The uploaded CSV must use UTF-8 text encoding.",
            400,
        ) from error

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        headers = next(reader, None)
    except csv.Error as error:
        raise DatasetAnalysisError(
            "invalid_csv_structure",
            "The uploaded file does not contain a valid CSV header.",
            422,
        ) from error

    if not headers or not any(header.strip() for header in headers):
        raise DatasetAnalysisError(
            "invalid_csv_structure",
            "The uploaded CSV must contain a header row.",
            422,
        )

    names = [header.strip() for header in headers]
    if any(not name for name in names) or len(set(names)) != len(names):
        raise DatasetAnalysisError(
            "invalid_csv_structure",
            "CSV column names must be non-empty and unique.",
            422,
        )

    columns = [
        {
            "name": name,
            "non_empty_values": 0,
            "missing_values": 0,
            "all_boolean": True,
            "all_integer": True,
            "all_numeric": True,
            "numeric_count": 0,
            "numeric_total": Decimal(0),
            "numeric_minimum": None,
            "numeric_maximum": None,
        }
        for name in names
    ]

    row_count = 0
    try:
        for row in reader:
            if not row or (len(row) == 1 and not row[0].strip()):
                continue
            row_count += 1
            if len(row) != len(columns):
                raise DatasetAnalysisError(
                    "invalid_csv_structure",
                    f"CSV record {row_count + 1} has {len(row)} fields; "
                    f"the header has {len(columns)}.",
                    422,
                )

            for column, raw_value in zip(columns, row):
                value = raw_value.strip()
                if not value:
                    column["missing_values"] += 1
                    continue

                column["non_empty_values"] += 1
                lowered = value.casefold()
                column["all_boolean"] &= lowered in {"true", "false"}

                try:
                    int(value)
                except ValueError:
                    column["all_integer"] = False

                number = _numeric_value(value)
                if number is None:
                    column["all_numeric"] = False
                else:
                    column["numeric_count"] += 1
                    column["numeric_total"] += number
                    if (
                        column["numeric_minimum"] is None
                        or number < column["numeric_minimum"]
                    ):
                        column["numeric_minimum"] = number
                    if (
                        column["numeric_maximum"] is None
                        or number > column["numeric_maximum"]
                    ):
                        column["numeric_maximum"] = number
    except csv.Error as error:
        raise DatasetAnalysisError(
            "invalid_csv_structure",
            "The uploaded file contains malformed CSV data.",
            422,
        ) from error

    summarized_columns = []
    for column in columns:
        inferred_type = _column_type(column)
        numeric_summary = None
        if inferred_type in {"integer", "number"}:
            count = column["numeric_count"]
            numeric_summary = {
                "count": count,
                "minimum": _format_number(column["numeric_minimum"]),
                "maximum": _format_number(column["numeric_maximum"]),
                "mean": _format_number(column["numeric_total"] / count),
            }
        missing_values = column["missing_values"]
        summarized_columns.append(
            {
                "name": column["name"],
                "inferred_type": inferred_type,
                "non_empty_values": column["non_empty_values"],
                "missing_values": missing_values,
                "missing_percentage": (
                    round(missing_values / row_count * 100, 2) if row_count else 0
                ),
                "numeric_summary": numeric_summary,
            }
        )

    return {
        "filename": filename,
        "row_count": row_count,
        "column_count": len(columns),
        "columns": summarized_columns,
    }
