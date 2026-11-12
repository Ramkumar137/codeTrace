"""Build evidence reports from persisted CodeTrace notebook records."""

import html
import io
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from backend.app.services.execution_store import ExecutionStore
from backend.app.services.experiment_tracker import analyze_experiment_history
from backend.app.services.notebook_parser import NotebookParseError, parse_notebook


REPORT_SCHEMA_VERSION = "1.0"
_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|"
    r"credential|authorization)",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)
    (\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|
        client[_-]?secret|credential|authorization)\b\s*[:=]\s*)
    (\"[^\"\r\n]*\"|'[^'\r\n]*'|[^,\s;]+)
    """
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")
_GITHUB_TOKEN = re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")
_AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_URL_PASSWORD = re.compile(r"(?i)(https?://[^:/\s]+:)[^@\s]+@")


class ReportGenerationError(Exception):
    """Raised when persisted notebook evidence cannot produce a report."""


def redact_sensitive(value: Any, key: str = "") -> Any:
    """Redact common credential patterns and sensitive metadata fields."""
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): redact_sensitive(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive(item) for item in value]
    if not isinstance(value, str):
        return value
    cleaned = _SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", value)
    cleaned = _BEARER.sub("Bearer [REDACTED]", cleaned)
    cleaned = _OPENAI_KEY.sub("[REDACTED]", cleaned)
    cleaned = _GITHUB_TOKEN.sub("[REDACTED]", cleaned)
    cleaned = _AWS_KEY.sub("[REDACTED]", cleaned)
    return _URL_PASSWORD.sub(r"\1[REDACTED]@", cleaned)


def _finding_snippets(
    finding: dict[str, Any], cells: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    source_cells = {
        cell.get("index"): cell
        for cell in cells
        if isinstance(cell.get("index"), int)
    }
    references = finding.get("source_refs", [])
    snippets: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    if isinstance(references, list):
        for reference in references:
            if not isinstance(reference, dict):
                continue
            cell_index = reference.get("cell_index")
            line_number = reference.get("line")
            cell = source_cells.get(cell_index)
            if (
                cell is None
                or not isinstance(cell_index, int)
                or not isinstance(line_number, int)
                or (cell_index, line_number) in seen
            ):
                continue
            lines = str(cell.get("source", "")).splitlines()
            if line_number < 1 or line_number > len(lines):
                continue
            seen.add((cell_index, line_number))
            start = max(1, line_number - 1)
            end = min(len(lines), line_number + 1)
            snippets.append(
                {
                    "cell_index": cell_index,
                    "line_start": start,
                    "line_end": end,
                    "finding_line": line_number,
                    "code": "\n".join(lines[start - 1 : end]),
                }
            )
    if snippets:
        return snippets
    for cell_index in finding.get("cell_indices", []):
        cell = source_cells.get(cell_index)
        if cell is not None:
            snippets.append(
                {
                    "cell_index": cell_index,
                    "line_start": None,
                    "line_end": None,
                    "code": cell.get("source", ""),
                }
            )
    return snippets


def _section(status: str, data: Any, reason: str | None = None) -> dict[str, Any]:
    result = {"status": status, "data": data}
    if reason:
        result["reason"] = reason
    return result


def _analysis_report(
    original: dict[str, Any],
    parsed: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    analysis = parsed.get("analysis", {})
    trace = analysis.get("pipeline_trace", {})
    cells = parsed.get("cells", [])
    findings = []
    nodes_by_finding: dict[str, list[str]] = {}
    for node in trace.get("nodes", []):
        if not isinstance(node, dict):
            continue
        for finding_id in node.get("finding_ids", []):
            nodes_by_finding.setdefault(finding_id, []).append(node.get("id", ""))
    for finding in analysis.get("findings", []):
        findings.append(
            {
                **finding,
                "evidence_classification": "static_analysis_inference",
                "code_snippets": _finding_snippets(finding, cells),
                "pipeline_node_ids": sorted(
                    set(nodes_by_finding.get(finding.get("id"), []))
                ),
            }
        )
    analysis_section = {
        "notebook": {
            "filename": original["filename"],
            "notebook_id": original["notebook_id"],
            "notebook_type": original["notebook_type"],
            "created_at": original["created_at"],
            "nbformat": parsed.get("format_version"),
            "nbformat_minor": parsed.get("format_minor"),
            "metadata": parsed.get("metadata", {}),
        },
        "cell_counts": {
            "total": parsed.get("total_cells", 0),
            "code": parsed.get("code_cells", 0),
            "markdown": parsed.get("markdown_cells", 0),
            "raw": parsed.get("raw_cells", 0),
        },
        "cells": cells,
        "analysis_summary": analysis.get("analysis_summary", ""),
        "imports": analysis.get("imports", []),
        "libraries": analysis.get("libraries", []),
        "dataset_references": analysis.get("dataset_references", []),
        "operations": analysis.get("all_operations", []),
        "research_objective": analysis.get("temporal_analysis", {}).get(
            "objective", "unspecified"
        ),
        "temporal_analysis": analysis.get("temporal_analysis", {}),
        "variable_lineage": analysis.get("variable_lineage", {}),
        "analysis_limitations": analysis.get("limitations", []),
        "confidence_definitions": analysis.get("confidence_definitions", {}),
        "severity_definitions": analysis.get("severity_definitions", {}),
    }
    pipeline_section = {
        "status": "available" if trace else "not_performed",
        "trace_type": trace.get("metadata", {}).get("trace_type", "unavailable"),
        "metadata": trace.get("metadata", {}),
        "nodes": trace.get("nodes", []),
        "edges": trace.get("edges", []),
        "unresolved_references": trace.get("unresolved_references", []),
        "findings": trace.get("findings", []),
        "graph_image": {
            "available": False,
            "reason": "The existing pipeline trace provides graph data, but no server-side graph image export is implemented.",
        },
    }
    return analysis_section, findings, pipeline_section


def build_report_data(
    store: ExecutionStore,
    notebook_id: str,
    access_token: str,
) -> dict[str, Any]:
    """Assemble a versioned report from authorized, persisted workflow records."""
    versions = store.list_notebook_versions(notebook_id, access_token)
    if versions is None:
        raise ReportGenerationError("The notebook is not accessible.")
    original = next(
        (
            item
            for item in versions
            if item["notebook_id"] == notebook_id
            and item["notebook_type"] == "original"
        ),
        None,
    )
    if original is None:
        raise ReportGenerationError("Reports can only be generated for an original notebook.")

    try:
        parsed = parse_notebook(
            original["filename"],
            original["content"],
            original.get("research_objective"),
        )
    except NotebookParseError as error:
        raise ReportGenerationError(
            "The stored notebook could not be analyzed for reporting."
        ) from error
    notebook_document = json.loads(original["content"].decode("utf-8-sig"))
    parsed["metadata"] = notebook_document.get("metadata", {})
    parsed["format_minor"] = notebook_document.get("nbformat_minor")

    analysis_section, findings, pipeline_section = _analysis_report(original, parsed)
    executions = store.list_executions(notebook_id, access_token)
    verifications = store.list_verifications(notebook_id, access_token)
    experiment_history = store.list_experiment_history(notebook_id, access_token)
    if executions is None or verifications is None or experiment_history is None:
        raise ReportGenerationError("Persisted workflow records could not be loaded.")
    experiment_history_analysis = analyze_experiment_history(experiment_history)
    versions_by_id = {version["notebook_id"]: version for version in versions}
    executions_by_id = {
        execution["execution_id"]: execution for execution in executions
    }
    datasets = store.list_datasets(notebook_id)
    datasets_by_id = {dataset["dataset_id"]: dataset for dataset in datasets}
    version_ids = set(versions_by_id)
    for execution in executions:
        if execution.get("notebook_id") not in version_ids:
            raise ReportGenerationError(
                "A persisted execution is associated with a different notebook."
            )
        if any(
            reference.get("dataset_id") not in datasets_by_id
            or reference.get("filename")
            != datasets_by_id[reference.get("dataset_id")]["filename"]
            for reference in execution.get("dataset_references", [])
        ):
            raise ReportGenerationError(
                "A persisted execution refers to a dataset not associated with this notebook."
            )
    for verification in verifications:
        corrected_id = verification.get("corrected_notebook_id")
        original_run = executions_by_id.get(
            verification.get("original_execution_id")
        )
        corrected_run = executions_by_id.get(
            verification.get("corrected_execution_id")
        )
        if (
            verification.get("original_notebook_id") != notebook_id
            or corrected_id not in versions_by_id
            or versions_by_id[corrected_id].get("notebook_type") != "corrected"
            or original_run is None
            or original_run.get("notebook_id") != notebook_id
            or corrected_run is None
            or corrected_run.get("notebook_id") != corrected_id
        ):
            raise ReportGenerationError(
                "A persisted verification is associated with inconsistent notebook or execution records."
            )

    approved_by_repair: dict[str, list[dict[str, Any]]] = {}
    repairs_by_id = {
        item.get("repair_id"): item
        for item in parsed["analysis"].get("repairs", [])
        if isinstance(item, dict) and isinstance(item.get("repair_id"), str)
    }
    for version in versions:
        if version["notebook_type"] != "corrected":
            continue
        manifests = store.get_approved_repairs(version["notebook_id"], access_token)
        for manifest in manifests or []:
            repair = manifest.get("repair", {})
            repair_id = repair.get("repair_id")
            if repair_id:
                proposal = repairs_by_id.get(repair_id)
                finding_manifest = manifest.get("finding")
                if (
                    proposal is None
                    or repair.get("finding_id") != proposal.get("finding_id")
                    or not isinstance(finding_manifest, dict)
                    or finding_manifest.get("id") != proposal.get("finding_id")
                ):
                    raise ReportGenerationError(
                        "A persisted repair manifest does not match the stored original finding."
                    )
                approved_by_repair.setdefault(repair_id, []).append(
                    {
                        "corrected_notebook_id": version["notebook_id"],
                        "corrected_filename": version["filename"],
                        "repair": repair,
                        "finding": manifest.get("finding"),
                    }
                )

    original_finding_ids = {
        finding.get("id")
        for finding in parsed["analysis"].get("findings", [])
        if finding.get("id")
    }
    approved_repair_pairs = {
        (application["corrected_notebook_id"], repair_id)
        for repair_id, applications in approved_by_repair.items()
        for application in applications
    }
    for verification in verifications:
        for result in verification.get("findings", []):
            if (
                result.get("finding_id") not in original_finding_ids
                or (
                    verification.get("corrected_notebook_id"),
                    result.get("repair_id"),
                )
                not in approved_repair_pairs
            ):
                raise ReportGenerationError(
                    "A persisted verification does not match an original finding and approved repair."
                )

    repairs = []
    for proposal in parsed["analysis"].get("repairs", []):
        approvals = approved_by_repair.get(proposal.get("repair_id"), [])
        repairs.append(
            {
                **proposal,
                "approval_state": (
                    "approved_and_applied"
                    if approvals
                    else "decision_not_persisted"
                ),
                "approval_records": approvals,
                "application_note": (
                    "An approved corrected notebook and repair manifest are persisted."
                    if approvals
                    else "No persisted approved correction is associated with this proposal. The browser does not persist separate pending/rejected decisions."
                ),
            }
        )

    execution_records = []
    for execution in executions:
        record = {
            key: value
            for key, value in execution.items()
            if key != "artifact"
        }
        record["failed_cell_count"] = max(
            0,
            int(execution.get("executed_cell_count", 0))
            - int(execution.get("successful_cell_count", 0)),
        )
        execution_records.append(record)

    artifacts = [
        {
            "artifact_type": "notebook",
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
    artifacts.extend(
        {
            "artifact_type": "associated_dataset",
            "dataset_id": dataset["dataset_id"],
            "filename": dataset["filename"],
            "created_at": dataset["created_at"],
            "available": True,
            "download_path": (
                f"/api/notebooks/{notebook_id}/artifacts/datasets/"
                f"{dataset['dataset_id']}"
            ),
        }
        for dataset in datasets
    )
    artifacts.extend(
        {
            "artifact_type": "executed_notebook",
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
    )

    severity_counts: dict[str, int] = {}
    for finding in findings:
        severity = str(finding.get("severity", "unknown")).lower()
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
    verification_counts: dict[str, int] = {}
    for verification in verifications:
        for finding in verification.get("findings", []):
            status = finding.get("verification_status", "unknown")
            verification_counts[status] = verification_counts.get(status, 0) + 1

    executions_completed = sum(
        execution.get("status") == "completed" for execution in executions
    )
    execution_status_counts: dict[str, int] = {}
    for execution in executions:
        execution_status = execution.get("status", "unknown")
        execution_status_counts[execution_status] = (
            execution_status_counts.get(execution_status, 0) + 1
        )
    approved_repair_count = len(approved_by_repair)
    approved_applications = sum(len(items) for items in approved_by_repair.values())
    report_id = str(uuid.uuid4())
    generated_at = datetime.now(timezone.utc).isoformat()
    optional_phases_performed = bool(executions and verifications)
    status = "completed" if optional_phases_performed else "partially_available"
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "project": "CodeTrace",
        "report_id": report_id,
        "generated_at": generated_at,
        "status": status,
        "overview": {
            "notebook_id": notebook_id,
            "notebook_name": original["filename"],
            "notebook_version": (
                f"{parsed.get('format_version')}."
                f"{parsed.get('format_minor')}"
                if parsed.get("format_minor") is not None
                else str(parsed.get("format_version"))
            ),
            "analysis_summary": parsed["analysis"].get("analysis_summary", ""),
            "findings_count": len(findings),
            "findings_by_severity": severity_counts,
            "repair_proposals_count": len(repairs),
            "approved_repair_count": approved_repair_count,
            "approved_repair_applications_count": approved_applications,
            "completed_executions_count": executions_completed,
            "execution_status_summary": execution_status_counts,
            "recorded_experiments_count": len(experiment_history),
            "verification_status_summary": verification_counts,
        },
        "sections": {
            "notebook_analysis": _section(
                "available", analysis_section
            ),
            "pipeline_trace": _section(
                pipeline_section["status"], pipeline_section
            ),
            "findings": _section("available", findings),
            "repair_summary": _section("available", repairs),
            "experiment_execution_results": _section(
                "available" if executions else "not_performed",
                execution_records,
                None if executions else "No persisted experiment executions exist.",
            ),
            "experiment_history": _section(
                "available" if experiment_history else "not_performed",
                {
                    "records": experiment_history,
                    "analysis": experiment_history_analysis,
                },
                None
                if experiment_history
                else "No manually recorded experiment-history entries exist.",
            ),
            "repair_verification": _section(
                "available" if verifications else "not_performed",
                verifications,
                None if verifications else "No persisted verification records exist.",
            ),
            "experiment_comparison": _section(
                "available" if verifications else "not_performed",
                [
                    {
                        "verification_id": verification.get("verification_id"),
                        "comparison": verification.get("comparison"),
                    }
                    for verification in verifications
                ],
                None if verifications else "No persisted comparisons exist.",
            ),
            "available_artifacts": _section("available", artifacts),
        },
        "conclusion": {
            "static_findings": [
                finding.get("id") for finding in findings
            ],
            "static_findings_are_runtime_confirmed": False,
            "verified_findings": [
                finding.get("finding_id")
                for verification in verifications
                for finding in verification.get("findings", [])
                if finding.get("verification_status") == "verified"
            ],
            "partially_verified_findings": [
                finding.get("finding_id")
                for verification in verifications
                for finding in verification.get("findings", [])
                if finding.get("verification_status")
                in {"partially_verified", "inconclusive"}
            ],
            "unresolved_findings": [
                finding.get("finding_id")
                for verification in verifications
                for finding in verification.get("findings", [])
                if finding.get("verification_status")
                in {"not_verified", "execution_failed"}
            ],
            "unverified_static_findings": [
                finding.get("id")
                for finding in findings
                if finding.get("id")
                not in {
                    item.get("finding_id")
                    for verification in verifications
                    for item in verification.get("findings", [])
                }
            ],
            "failed_executions": [
                execution["execution_id"]
                for execution in executions
                if execution.get("status")
                in {"failed", "timed_out", "cancelled", "unavailable"}
            ],
            "limitations": parsed["analysis"].get("limitations", []),
        },
    }
    return redact_sensitive(report)


def _display_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    if value is None:
        return "Unavailable"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _html_value(value: Any) -> str:
    if isinstance(value, dict):
        if not value:
            return "<p class=\"empty\">No records.</p>"
        rows = "".join(
            f"<tr><th>{html.escape(str(key))}</th><td>{_html_value(item)}</td></tr>"
            for key, item in value.items()
        )
        return f"<table><tbody>{rows}</tbody></table>"
    if isinstance(value, list):
        if not value:
            return "<p class=\"empty\">No records.</p>"
        return "<ol>" + "".join(
            f"<li>{_html_value(item)}</li>" for item in value
        ) + "</ol>"
    text = html.escape(_display_value(value))
    if "\n" in str(value):
        return f"<pre>{text}</pre>"
    return f"<p>{text}</p>"


def render_html_report(report: dict[str, Any]) -> bytes:
    """Render a self-contained, escaped HTML report."""
    section_titles = (
        ("notebook_analysis", "Notebook Analysis"),
        ("pipeline_trace", "ML Pipeline Trace"),
        ("findings", "Findings and Evidence"),
        ("repair_summary", "Repair Summary"),
        ("experiment_execution_results", "Experiment Execution Results"),
        ("experiment_history", "Recorded Experiment History"),
        ("repair_verification", "Repair Verification"),
        ("experiment_comparison", "Experiment Comparison"),
        ("available_artifacts", "Available Artifacts"),
    )
    sections = []
    for key, title in section_titles:
        section = report["sections"][key]
        reason = (
            f"<p class=\"availability\">{html.escape(section['reason'])}</p>"
            if section.get("reason")
            else ""
        )
        sections.append(
            f"<section><h2>{html.escape(title)}</h2>"
            f"<p class=\"availability\">Status: {html.escape(section['status'])}</p>"
            f"{reason}{_html_value(section['data'])}</section>"
        )
    overview = _html_value(report["overview"])
    conclusion = _html_value(report["conclusion"])
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CodeTrace Evidence Report — {html.escape(report['overview']['notebook_name'])}</title>
<style>
body{{font:15px/1.55 Arial,sans-serif;color:#172b4d;background:#f4f7fb;margin:0}}
main{{max-width:1100px;margin:32px auto;padding:0 20px}}
header,section{{background:#fff;border:1px solid #dfe5ec;border-radius:10px;padding:24px;margin:0 0 18px}}
h1,h2,h3{{color:#16345a}}h1{{margin:0 0 6px}}h2{{border-bottom:1px solid #e6ebf1;padding-bottom:8px}}
.meta,.availability{{color:#52657d;font-size:.92em}}table{{border-collapse:collapse;width:100%;margin:12px 0}}
th,td{{border:1px solid #e1e7ef;padding:8px;text-align:left;vertical-align:top;overflow-wrap:anywhere}}
th{{background:#f4f7fb;width:23%}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;padding:12px;border-radius:5px}}
li{{margin:8px 0}}.empty{{color:#66758a}}.badge{{font-weight:700;color:#805600}}
@media print{{body{{background:#fff}}main{{max-width:none;margin:0;padding:0}}header,section{{break-inside:avoid;border-radius:0}}}}
</style></head><body><main>
<header><p class="meta">CodeTrace · Evidence report · schema {html.escape(report['schema_version'])}</p>
<h1>{html.escape(report['overview']['notebook_name'])}</h1>
<p class="meta">Report ID: {html.escape(report['report_id'])}<br>
Generated: {html.escape(report['generated_at'])}<br>
Availability: <span class="badge">{html.escape(report['status'])}</span></p>
<h2>Report Overview</h2>{overview}</header>
{''.join(sections)}
<section><h2>Conclusion and Limitations</h2>{conclusion}</section>
</main></body></html>"""
    return document.encode("utf-8")


def _pdf_safe_text(value: Any) -> str:
    return _display_value(value).encode("latin-1", "replace").decode("latin-1")


def _pdf_value(
    story: list[Any],
    value: Any,
    styles: dict[str, ParagraphStyle],
    depth: int = 0,
    key: str | None = None,
) -> None:
    if key is not None:
        story.append(
            Paragraph(
                html.escape(_pdf_safe_text(key)),
                styles["Heading3" if depth < 2 else "Heading4"],
            )
        )
    if isinstance(value, dict):
        if not value:
            story.append(Paragraph("No records.", styles["BodyText"]))
        for nested_key, nested_value in value.items():
            _pdf_value(story, nested_value, styles, depth + 1, str(nested_key))
        return
    if isinstance(value, list):
        if not value:
            story.append(Paragraph("No records.", styles["BodyText"]))
        for index, item in enumerate(value, start=1):
            story.append(
                Paragraph(f"Record {index}", styles["Heading4"])
            )
            _pdf_value(story, item, styles, depth + 1)
        return
    text = _pdf_safe_text(value)
    escaped = html.escape(text).replace("\n", "<br/>")
    story.append(Paragraph(escaped, styles["BodyText"]))
    story.append(Spacer(1, 2 * mm))


def render_pdf_report(report: dict[str, Any]) -> bytes:
    """Render a paginated technical report using ReportLab."""
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=17 * mm,
        leftMargin=17 * mm,
        topMargin=17 * mm,
        bottomMargin=17 * mm,
        title=f"CodeTrace Evidence Report — {report['overview']['notebook_name']}",
        author="CodeTrace",
        subject=f"Evidence report {report['report_id']}",
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            parent=styles["Title"],
            alignment=TA_CENTER,
            textColor=colors.HexColor("#16345a"),
            spaceAfter=5 * mm,
        )
    )
    story: list[Any] = [
        Paragraph("CodeTrace Evidence Report", styles["ReportTitle"]),
        Paragraph(
            html.escape(_pdf_safe_text(report["overview"]["notebook_name"])),
            styles["Heading2"],
        ),
        Paragraph(
            html.escape(
                _pdf_safe_text(
                    f"Report ID: {report['report_id']} · Generated: "
                    f"{report['generated_at']} · Status: {report['status']} · "
                    f"Schema: {report['schema_version']}"
                )
            ),
            styles["BodyText"],
        ),
        Spacer(1, 5 * mm),
        Paragraph("Report Overview", styles["Heading1"]),
    ]
    _pdf_value(story, report["overview"], styles)
    section_titles = (
        ("notebook_analysis", "Notebook Analysis"),
        ("pipeline_trace", "ML Pipeline Trace"),
        ("findings", "Findings and Evidence"),
        ("repair_summary", "Repair Summary"),
        ("experiment_execution_results", "Experiment Execution Results"),
        ("repair_verification", "Repair Verification"),
        ("experiment_comparison", "Experiment Comparison"),
        ("available_artifacts", "Available Artifacts"),
    )
    for key, title in section_titles:
        section = report["sections"][key]
        story.extend(
            [
                PageBreak(),
                Paragraph(html.escape(title), styles["Heading1"]),
                Paragraph(
                    html.escape(
                        _pdf_safe_text(
                            "Section status: "
                            f"{section['status']}"
                            + (
                                f" — {section['reason']}"
                                if section.get("reason")
                                else ""
                            )
                        )
                    ),
                    styles["BodyText"],
                ),
            ]
        )
        _pdf_value(story, section["data"], styles)
    story.extend(
        [
            PageBreak(),
            Paragraph("Conclusion and Limitations", styles["Heading1"]),
        ]
    )
    _pdf_value(story, report["conclusion"], styles)

    def add_page_number(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#52657d"))
        canvas.drawString(17 * mm, 10 * mm, f"CodeTrace · {report['report_id']}")
        canvas.drawRightString(
            A4[0] - 17 * mm, 10 * mm, f"Page {document.page}"
        )
        canvas.restoreState()

    document.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    return output.getvalue()


def generate_report_artifacts(
    store: ExecutionStore,
    notebook_id: str,
    access_token: str,
) -> tuple[dict[str, Any], bytes, bytes]:
    """Build and render a report without starting or changing notebook executions."""
    report = build_report_data(store, notebook_id, access_token)
    return report, render_html_report(report), render_pdf_report(report)
