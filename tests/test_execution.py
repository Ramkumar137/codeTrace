"""Tests for persisted, explicitly authorized isolated execution orchestration."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import nbformat
import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.main import app
from backend.app.services.docker_runner import DockerExecutionError, DockerRunner
from backend.app.services.execution_manager import (
    ExecutionManager,
    ExecutionRequestError,
)
from backend.app.services.execution_store import ExecutionStore


client = TestClient(app)


class MockDockerRunner:
    environment = {
        "network": "none",
        "non_root": True,
        "cpu_limit": 1,
        "memory_limit_mb": 1024,
        "process_limit": 64,
        "writable_tmpfs_mb": 128,
        "output_limit_bytes": 1_000_000,
        "image": "test-runner",
        "timeout_seconds": 30,
    }

    def __init__(self, result=None, available=True):
        self.result = result or {
            "status": "completed",
            "executed_cell_count": 1,
            "successful_cell_count": 1,
            "outputs": [
                {"cell_number": 1, "outputs": [{"output_type": "stream", "text": "safe"}]}
            ],
            "python_version": "3.12.0",
            "package_versions": {"nbclient": "0.10.2"},
            "artifact": b"executed notebook",
            "logs": "",
            "environment": self.environment,
            "duration_seconds": 0.02,
        }
        self.available = available
        self.calls = []

    async def is_available(self):
        return self.available

    async def execute(self, execution_id, notebook_content, datasets):
        self.calls.append((execution_id, notebook_content, datasets))
        return self.result


def stored_notebook(store, content=None):
    content = content or nbformat.writes(
        nbformat.v4.new_notebook(
            cells=[nbformat.v4.new_code_cell("value = 1")]
        )
    ).encode()
    notebook_id, token = store.create_original_notebook("example.ipynb", content)
    record = store.get_notebook(notebook_id, token)
    assert record is not None
    return record, token


async def wait_for_execution(store, execution_id, token):
    for _ in range(50):
        result = store.get_execution(execution_id, token)
        if result["status"] not in {"queued", "running"}:
            return result
        await asyncio.sleep(0.01)
    raise AssertionError("The mock execution did not finish.")


@pytest.mark.asyncio
async def test_successful_execution_captures_outputs_and_persists_metadata(tmp_path):
    store = ExecutionStore(tmp_path)
    record, token = stored_notebook(store)
    runner = MockDockerRunner()
    manager = ExecutionManager(store, runner)

    queued = await manager.start(record, [], token)
    result = await wait_for_execution(store, queued["execution_id"], token)
    reloaded = ExecutionStore(tmp_path).get_execution(result["execution_id"], token)

    assert result["status"] == "completed"
    assert result["outputs"][0]["outputs"][0]["text"] == "safe"
    assert result["successful_cell_count"] == 1
    assert result["python_version"] == "3.12.0"
    assert result["package_versions"] == {"nbclient": "0.10.2"}
    assert result["artifact_available"] is True
    assert reloaded["execution_id"] == result["execution_id"]


@pytest.mark.asyncio
async def test_original_and_approved_corrected_notebooks_run_independently(tmp_path):
    store = ExecutionStore(tmp_path)
    original, token = stored_notebook(store, b"original notebook")
    corrected_id = store.create_corrected_notebook(
        original, "example-repaired.ipynb", b"corrected notebook"
    )
    corrected = store.get_notebook(corrected_id, token)
    assert corrected is not None
    runner = MockDockerRunner()
    manager = ExecutionManager(store, runner)

    original_run = await manager.start(original, [], token)
    corrected_run = await manager.start(corrected, [], token)
    await wait_for_execution(store, original_run["execution_id"], token)
    await wait_for_execution(store, corrected_run["execution_id"], token)

    assert original_run["execution_id"] != corrected_run["execution_id"]
    assert runner.calls[0][1] == b"original notebook"
    assert runner.calls[1][1] == b"corrected notebook"
    assert runner.calls[0][0] != runner.calls[1][0]


@pytest.mark.asyncio
async def test_cell_exception_is_persisted_without_claiming_success(tmp_path):
    store = ExecutionStore(tmp_path)
    record, token = stored_notebook(store)
    runner = MockDockerRunner(
        {
            "status": "failed",
            "executed_cell_count": 1,
            "successful_cell_count": 0,
            "failed_cell_number": 1,
            "error_details": {"ename": "NameError", "evalue": "missing_name"},
            "outputs": [],
            "environment": MockDockerRunner.environment,
            "duration_seconds": 0.1,
        }
    )
    manager = ExecutionManager(store, runner)

    queued = await manager.start(record, [], token)
    result = await wait_for_execution(store, queued["execution_id"], token)

    assert result["status"] == "failed"
    assert result["failed_cell_number"] == 1
    assert result["error_details"]["ename"] == "NameError"
    assert result["artifact_available"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error"),
    [
        ("timed_out", {"message": "Execution time limit exceeded."}),
        ("failed", {"ename": "ModuleNotFoundError", "evalue": "package"}),
    ],
)
async def test_timeout_and_missing_dependency_statuses_are_recorded(
    tmp_path, status, error
):
    store = ExecutionStore(tmp_path)
    record, token = stored_notebook(store)
    runner = MockDockerRunner(
        {
            "status": status,
            "executed_cell_count": 1,
            "successful_cell_count": 0,
            "error_details": error,
            "environment": MockDockerRunner.environment,
            "duration_seconds": 0.3,
        }
    )
    manager = ExecutionManager(store, runner)

    queued = await manager.start(record, [], token)
    result = await wait_for_execution(store, queued["execution_id"], token)

    assert result["status"] == status
    assert result["error_details"] == error


@pytest.mark.asyncio
async def test_excessive_output_is_bounded_before_metadata_persistence(tmp_path):
    store = ExecutionStore(tmp_path)
    record, token = stored_notebook(store)
    runner = MockDockerRunner(
        {
            "status": "completed",
            "executed_cell_count": 1,
            "successful_cell_count": 1,
            "outputs": [{"cell_number": 1, "outputs": [{"text": "[output truncated]"}]}],
            "environment": MockDockerRunner.environment,
            "duration_seconds": 0.1,
        }
    )
    manager = ExecutionManager(store, runner)

    queued = await manager.start(record, [], token)
    result = await wait_for_execution(store, queued["execution_id"], token)

    assert result["outputs"][0]["outputs"][0]["text"] == "[output truncated]"


@pytest.mark.asyncio
async def test_missing_dataset_is_rejected_before_runner_starts(tmp_path):
    store = ExecutionStore(tmp_path)
    record, token = stored_notebook(store)
    runner = MockDockerRunner()
    manager = ExecutionManager(store, runner)

    with pytest.raises(ExecutionRequestError, match="not associated"):
        await manager.start(record, ["not-a-dataset"], token)
    assert runner.calls == []


@pytest.mark.asyncio
async def test_docker_unavailable_persists_explicit_unavailable_status(tmp_path):
    store = ExecutionStore(tmp_path)
    record, token = stored_notebook(store)
    manager = ExecutionManager(store, MockDockerRunner(available=False))

    result = await manager.start(record, [], token)

    assert result["status"] == "unavailable"
    assert "Docker" in result["error_details"]["message"]


@pytest.mark.asyncio
async def test_active_execution_can_be_cancelled(tmp_path):
    store = ExecutionStore(tmp_path)
    record, token = stored_notebook(store)
    started = asyncio.Event()

    class BlockingRunner(MockDockerRunner):
        async def execute(self, execution_id, notebook_content, datasets):
            started.set()
            await asyncio.Event().wait()

    manager = ExecutionManager(store, BlockingRunner())
    queued = await manager.start(record, [], token)
    await started.wait()

    assert await manager.cancel(queued["execution_id"]) is True
    result = store.get_execution(queued["execution_id"], token)
    assert result["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_does_not_hide_container_cleanup_failure(tmp_path):
    store = ExecutionStore(tmp_path)
    record, token = stored_notebook(store)
    started = asyncio.Event()

    class CleanupFailureRunner(MockDockerRunner):
        async def execute(self, execution_id, notebook_content, datasets):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                raise DockerExecutionError("Container cleanup failed.")

    manager = ExecutionManager(store, CleanupFailureRunner())
    queued = await manager.start(record, [], token)
    await started.wait()
    assert await manager.cancel(queued["execution_id"]) is True

    result = store.get_execution(queued["execution_id"], token)
    assert result["status"] == "failed"
    assert result["error_details"]["message"] == "Container cleanup failed."


def test_execution_request_requires_notebook_capability_token(tmp_path, monkeypatch):
    store = ExecutionStore(tmp_path)
    record, _ = stored_notebook(store)
    monkeypatch.setattr(main, "execution_store", store)
    monkeypatch.setattr(main, "execution_manager", None)

    response = client.post(
        f"/api/notebooks/{record['notebook_id']}/executions",
        json={"dataset_ids": []},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "unauthorized"


def test_execution_api_persists_dataset_and_authorizes_result_access(
    tmp_path, monkeypatch
):
    store = ExecutionStore(tmp_path)
    runner = MockDockerRunner(available=False)
    monkeypatch.setattr(main, "execution_store", store)
    monkeypatch.setattr(main, "execution_manager", ExecutionManager(store, runner))
    notebook_content = nbformat.writes(
        nbformat.v4.new_notebook(
            cells=[nbformat.v4.new_code_cell("value = 1")]
        )
    ).encode()

    upload = client.post(
        "/api/notebooks/upload",
        files={"file": ("sample.ipynb", notebook_content, "application/octet-stream")},
    )
    assert upload.status_code == 200
    notebook_id = upload.json()["notebook_id"]
    token = upload.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    attached = client.post(
        f"/api/notebooks/{notebook_id}/datasets",
        headers=headers,
        files={"file": ("data.csv", b"feature,label\n1,0\n", "text/csv")},
    )
    assert attached.status_code == 200
    dataset_id = attached.json()["dataset"]["dataset_id"]
    start = client.post(
        f"/api/notebooks/{notebook_id}/executions",
        headers=headers,
        json={"dataset_ids": [dataset_id]},
    )

    assert start.status_code == 503
    execution = start.json()["detail"]["execution"]
    assert execution["status"] == "unavailable"
    assert execution["dataset_references"] == [
        {"dataset_id": dataset_id, "filename": "data.csv"}
    ]
    result = client.get(
        f"/api/executions/{execution['execution_id']}", headers=headers
    )
    assert result.status_code == 200
    assert result.json()["artifact_available"] is False
    assert client.get(
        f"/api/executions/{execution['execution_id']}",
        headers={"Authorization": "Bearer wrong-token"},
    ).status_code == 404


def test_approved_corrected_notebook_requires_separate_explicit_run(
    tmp_path, monkeypatch
):
    store = ExecutionStore(tmp_path)
    runner = MockDockerRunner(available=False)
    monkeypatch.setattr(main, "execution_store", store)
    monkeypatch.setattr(main, "execution_manager", ExecutionManager(store, runner))
    notebook_content = nbformat.writes(
        nbformat.v4.new_notebook(
            cells=[
                nbformat.v4.new_code_cell(
                    "from sklearn.preprocessing import StandardScaler"
                ),
                nbformat.v4.new_code_cell(
                    "scaler = StandardScaler()\nX_scaled = scaler.fit_transform(X)"
                ),
                nbformat.v4.new_code_cell(
                    "X_train, X_test, y_train, y_test = "
                    "train_test_split(X_scaled, y)"
                ),
                nbformat.v4.new_code_cell("model.fit(X_train, y_train)"),
            ]
        )
    ).encode()
    uploaded = client.post(
        "/api/notebooks/upload",
        files={"file": ("sample.ipynb", notebook_content, "application/octet-stream")},
    )
    assert uploaded.status_code == 200
    data = uploaded.json()
    token = data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    repair = next(
        item
        for item in data["notebook"]["analysis"]["repairs"]
        if item["repair_status"] == "automatically_repairable"
    )

    generated = client.post(
        "/api/notebooks/repairs/generate",
        headers=headers,
        data={
            "repair_ids": json.dumps([repair["repair_id"]]),
            "notebook_id": data["notebook_id"],
        },
        files={
            "file": ("sample.ipynb", notebook_content, "application/octet-stream")
        },
    )
    assert generated.status_code == 200
    corrected_id = generated.headers["X-CodeTrace-Notebook-ID"]
    corrected = store.get_notebook(corrected_id, token)
    assert corrected["notebook_type"] == "corrected"
    assert corrected["approved"] == 1

    original_run = client.post(
        f"/api/notebooks/{data['notebook_id']}/executions",
        headers=headers,
        json={"dataset_ids": []},
    )
    corrected_run = client.post(
        f"/api/notebooks/{corrected_id}/executions",
        headers=headers,
        json={"dataset_ids": []},
    )

    assert original_run.status_code == 503
    assert corrected_run.status_code == 503
    assert (
        original_run.json()["detail"]["execution"]["execution_id"]
        != corrected_run.json()["detail"]["execution"]["execution_id"]
    )
    assert corrected_run.json()["detail"]["execution"]["notebook_type"] == "corrected"


def test_docker_command_enforces_isolation_without_host_output_mount(tmp_path):
    runner = DockerRunner(image="codetrace-test", timeout_seconds=30)
    command = runner._docker_run_command("codetrace-test", tmp_path, ["data.csv"])

    assert "--network" in command
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--user") + 1] == "10001:10001"
    assert "--read-only" in command
    assert "--cap-drop" in command
    assert "--pids-limit" in command
    assert "--memory" in command
    assert "--cpus" in command
    assert not any("docker.sock" in argument for argument in command)
    assert not any("type=bind" in argument and "target=/workspace" in argument for argument in command)


@pytest.mark.asyncio
async def test_container_artifact_reads_enforce_size_limit(monkeypatch):
    runner = DockerRunner(image="codetrace-test", timeout_seconds=30)
    killed = []

    class Process:
        def __init__(self):
            self.returncode = None
            self.stdout = asyncio.StreamReader()
            self.stdout.feed_data(b"oversized")
            self.stdout.feed_eof()

        async def wait(self):
            return self.returncode

        def kill(self):
            killed.append(True)
            self.returncode = -9

    async def create_process(*args, **kwargs):
        return Process()

    monkeypatch.setattr(
        "backend.app.services.docker_runner.asyncio.create_subprocess_exec",
        create_process,
    )

    with pytest.raises(DockerExecutionError, match="size limit"):
        await runner._read_container_file("codetrace-test", "/workspace/result.json", 4)
    assert killed


@pytest.mark.asyncio
@pytest.mark.parametrize("notebook_status", ["completed", "failed"])
async def test_docker_container_is_removed_after_completed_or_failed_run(
    tmp_path, monkeypatch, notebook_status
):
    runner = DockerRunner(image="codetrace-test", timeout_seconds=30)
    runner.is_available = AsyncMock(return_value=True)
    commands = []
    temporary_paths = []
    original_temporary_directory = __import__(
        "tempfile"
    ).TemporaryDirectory
    runner_result = {
        "status": notebook_status,
        "executed_cell_count": 1,
        "successful_cell_count": int(notebook_status == "completed"),
        "outputs": [],
        "python_version": "3.12.0",
        "package_versions": {},
        "environment": runner.environment,
    }

    class Process:
        def __init__(self, output=b"", returncode=0):
            self.returncode = returncode
            self.stdout = asyncio.StreamReader()
            self.stdout.feed_data(output)
            self.stdout.feed_eof()
            self.stderr = None

        async def communicate(self):
            return b"", b""

        async def wait(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

    async def create_process(*args, **kwargs):
        command = list(args)
        commands.append(command)
        if command[1] == "exec" and command[3] == "test":
            return Process()
        if command[1] == "exec" and command[3] == "cat":
            output = (
                json.dumps(runner_result).encode("utf-8")
                if command[4].endswith("/result.json")
                else b"executed notebook"
            )
            return Process(output)
        return Process()

    def temporary_directory(*, prefix):
        directory = original_temporary_directory(prefix=prefix, dir=tmp_path)
        temporary_paths.append(Path(directory.name))
        return directory

    monkeypatch.setattr(
        "backend.app.services.docker_runner.tempfile.TemporaryDirectory",
        temporary_directory,
    )
    monkeypatch.setattr(
        "backend.app.services.docker_runner.asyncio.create_subprocess_exec",
        create_process,
    )

    result = await runner.execute("execution-id", b"stored notebook", [])

    assert result["status"] == notebook_status
    assert any(command[1:3] == ["rm", "--force"] for command in commands)
    assert all(not directory.exists() for directory in temporary_paths)


@pytest.mark.asyncio
async def test_docker_timeout_stops_and_removes_container(monkeypatch, tmp_path):
    runner = DockerRunner(image="codetrace-test", timeout_seconds=0.01)
    runner.is_available = AsyncMock(return_value=True)
    commands = []

    class Process:
        def __init__(self, *, hanging=False, exit_code=0):
            self.returncode = None
            self.hanging = hanging
            self.exit_code = exit_code
            self.stdout = None
            self.stderr = None
            self.terminated = asyncio.Event()

        async def communicate(self):
            if self.hanging:
                await self.terminated.wait()
            return b"", b""

        async def wait(self):
            if self.hanging:
                await self.terminated.wait()
                return self.returncode
            self.returncode = self.exit_code
            return self.exit_code

        def kill(self):
            self.returncode = -9
            self.terminated.set()

    async def create_process(*args, **kwargs):
        command = list(args)
        commands.append(command)
        return Process(
            hanging=command[1] == "run",
            exit_code=1 if command[1] == "exec" else 0,
        )

    monkeypatch.setattr(
        "backend.app.services.docker_runner.asyncio.create_subprocess_exec",
        create_process,
    )

    result = await runner.execute("execution-timeout", b"stored notebook", [])

    assert result["status"] == "timed_out"
    assert any(command[1] == "stop" for command in commands)
    assert any(command[1:3] == ["rm", "--force"] for command in commands)


@pytest.mark.asyncio
async def test_missing_docker_cli_is_reported_as_unavailable(monkeypatch):
    runner = DockerRunner()

    async def missing_cli(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(
        "backend.app.services.docker_runner.asyncio.create_subprocess_exec",
        missing_cli,
    )

    assert await runner.is_available() is False
