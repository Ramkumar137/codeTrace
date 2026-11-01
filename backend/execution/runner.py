"""Container-side nbclient entry point. This file only runs inside the runner image."""

import importlib.metadata
import json
import platform
import shutil
import sys
import time
import traceback
from pathlib import Path

import nbformat
from nbclient import NotebookClient


MAX_CELL_OUTPUT_BYTES = 256_000
MAX_ERROR_BYTES = 64_000
ARTIFACT_COLLECTION_WAIT_SECONDS = 30


def _encoded_size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _limit_output(output, limit):
    if _encoded_size(output) <= limit:
        return output
    output.clear()
    output.update(
        {
            "output_type": "stream",
            "name": "stderr",
            "text": "[CodeTrace truncated this output at the configured size limit.]",
        }
    )
    return output


def _output_text(output):
    output_type = output.get("output_type", "")
    if output_type == "stream":
        return str(output.get("text", ""))[:MAX_ERROR_BYTES]
    if output_type == "error":
        lines = output.get("traceback", [])
        return "\n".join(
            [str(output.get("ename", "Error")), str(output.get("evalue", "")), *lines]
        )[:MAX_ERROR_BYTES]
    data = output.get("data", {})
    text = data.get("text/plain", "")
    if isinstance(text, list):
        text = "".join(text)
    if text:
        return str(text)[:MAX_ERROR_BYTES]
    return "[Non-text cell output]"


def _package_versions():
    versions = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if name and len(versions) < 300:
            versions[name] = distribution.version
    return dict(sorted(versions.items(), key=lambda item: item[0].lower()))


def main():
    input_path, notebook_path, result_path = map(Path, sys.argv[1:4])
    output_limit = max(1, int(sys.argv[4]))
    timeout_seconds = max(1, int(sys.argv[5]))
    dataset_names = sys.argv[6:]
    notebook = nbformat.read(input_path, as_version=nbformat.NO_CONVERT)
    nbformat.validate(notebook)
    for filename in dataset_names:
        source = Path("/input") / filename
        if source.parent != Path("/input") or not source.is_file():
            raise ValueError("An explicitly associated dataset is missing.")
        shutil.copyfile(source, Path.cwd() / filename)

    completed_cells = []
    successful_cells = set()
    executed_cell_indices = set()
    successful_cell_indices = set()
    failed = {}
    active_cell_index = None
    used_output_bytes = 0
    used_summary_bytes = 0

    def retain_cell(cell, cell_index, succeeded):
        nonlocal used_output_bytes, used_summary_bytes
        budget = min(MAX_CELL_OUTPUT_BYTES, max(0, output_limit - used_output_bytes))
        outputs = cell.get("outputs", [])
        for output_index, output in enumerate(outputs):
            if budget < 96:
                del outputs[output_index:]
                break
            _limit_output(output, budget)
            size = _encoded_size(output)
            if size > budget:
                del outputs[output_index:]
                break
            used_output_bytes += size
            budget = max(0, output_limit - used_output_bytes)
        remaining_text = max(0, output_limit - used_summary_bytes)
        captured_outputs = []
        for output in outputs:
            text = _output_text(output)
            encoded = text.encode("utf-8")
            if len(encoded) > remaining_text:
                text = encoded[:remaining_text].decode("utf-8", errors="ignore")
            text_size = len(text.encode("utf-8"))
            remaining_text = max(0, remaining_text - text_size)
            used_summary_bytes += text_size
            captured_outputs.append(
                {
                    "output_type": output.get("output_type", ""),
                    "name": output.get("name"),
                    "text": text,
                }
            )
        completed_cells.append(
            {
                "cell_number": cell_index + 1,
                "outputs": captured_outputs,
            }
        )
        if succeeded:
            successful_cells.add(cell_index)

    def on_cell_complete(cell, cell_index):
        nonlocal active_cell_index
        del cell
        executed_cell_indices.add(cell_index)
        successful_cell_indices.add(cell_index)
        active_cell_index = None

    def on_cell_error(cell, cell_index, execute_reply):
        nonlocal active_cell_index
        del cell
        executed_cell_indices.add(cell_index)
        active_cell_index = None
        content = execute_reply.get("content", {})
        failed.update(
            {
                "cell_number": cell_index + 1,
                "ename": str(content.get("ename", "ExecutionError"))[:200],
                "evalue": str(content.get("evalue", ""))[:4000],
                "traceback": "\n".join(content.get("traceback", []))[:MAX_ERROR_BYTES],
            }
        )

    def on_cell_execute(cell, cell_index):
        nonlocal active_cell_index
        del cell
        active_cell_index = cell_index

    status = "completed"
    error_details = None
    timed_out_cell_number = None
    failed_cell_number = None
    try:
        client = NotebookClient(
            notebook,
            timeout=timeout_seconds,
            on_cell_execute=on_cell_execute,
            on_cell_complete=on_cell_complete,
            on_cell_error=on_cell_error,
            allow_errors=False,
            resources={"metadata": {"path": "/workspace"}},
        )
        client.execute()
    except TimeoutError as error:
        status = "timed_out"
        timed_out_cell_number = (
            active_cell_index + 1
            if active_cell_index is not None
            else failed.get("cell_number")
        )
        if timed_out_cell_number is not None and not any(
            item["cell_number"] == timed_out_cell_number for item in completed_cells
        ):
            executed_cell_indices.add(timed_out_cell_number - 1)
        error_details = failed or {
            "cell_number": timed_out_cell_number,
            "ename": type(error).__name__,
            "evalue": str(error)[:4000],
        }
    except Exception as error:
        status = "failed"
        if failed:
            error_details = failed
        else:
            if active_cell_index is not None:
                executed_cell_indices.add(active_cell_index)
                failed_cell_number = active_cell_index + 1
            error_details = {
                "ename": type(error).__name__,
                "evalue": str(error)[:4000],
                "traceback": "".join(
                    traceback.format_exception_only(type(error), error)
                )[:MAX_ERROR_BYTES],
            }

    for cell_index in sorted(executed_cell_indices):
        retain_cell(
            notebook.cells[cell_index],
            cell_index,
            cell_index in successful_cell_indices,
        )

    nbformat.write(notebook, notebook_path)
    result = {
        "status": status,
        "executed_cell_count": len(completed_cells),
        "successful_cell_count": len(successful_cells),
        "failed_cell_number": (
            failed.get("cell_number") or timed_out_cell_number or failed_cell_number
        ),
        "error_details": error_details,
        "python_version": platform.python_version(),
        "package_versions": _package_versions(),
        "outputs": completed_cells,
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    collection_deadline = time.monotonic() + ARTIFACT_COLLECTION_WAIT_SECONDS
    while time.monotonic() < collection_deadline:
        time.sleep(0.1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
