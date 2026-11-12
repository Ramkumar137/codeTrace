"""Docker-only execution runner for untrusted notebook code."""

import asyncio
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path, PureWindowsPath
from typing import Any


DEFAULT_EXECUTION_TIMEOUT_SECONDS = 300
MAX_NOTEBOOK_OUTPUT_BYTES = 1_000_000
MAX_CAPTURED_LOG_BYTES = 16_000
MAX_EXECUTED_NOTEBOOK_BYTES = 12 * 1024 * 1024
MAX_RESULT_FILE_BYTES = MAX_NOTEBOOK_OUTPUT_BYTES * 8 + 512 * 1024
RUNNER_IMAGE = os.environ.get(
    "CODETRACE_EXECUTION_IMAGE", "codetrace-notebook-runner:1.0.0"
)

RUNNER_LIMITS: dict[str, Any] = {
    "network": "none",
    "non_root": True,
    "cpu_limit": 1,
    "memory_limit_mb": 1024,
    "process_limit": 64,
    "writable_tmpfs_mb": 128,
    "output_limit_bytes": MAX_NOTEBOOK_OUTPUT_BYTES,
}


def safe_dataset_filename(filename: str) -> str:
    basename = PureWindowsPath(filename.replace("/", "\\")).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", basename).strip("._")
    return cleaned[:120] or "dataset.csv"


class DockerUnavailableError(RuntimeError):
    """Docker or the configured execution image is unavailable."""


class DockerExecutionError(RuntimeError):
    """A container could not be created or its result could not be collected."""


class DockerRunner:
    def __init__(
        self,
        image: str = RUNNER_IMAGE,
        timeout_seconds: int = DEFAULT_EXECUTION_TIMEOUT_SECONDS,
        docker_command: str = "docker",
    ) -> None:
        if image.endswith(":latest"):
            raise ValueError(
                "The CodeTrace runner image must use a pinned version tag or digest."
            )
        self.image = image
        self.timeout_seconds = timeout_seconds
        self.docker_command = docker_command

    @property
    def environment(self) -> dict[str, Any]:
        return {
            **RUNNER_LIMITS,
            "image": self.image,
            "timeout_seconds": self.timeout_seconds,
        }

    async def is_available(self) -> bool:
        try:
            process = await asyncio.create_subprocess_exec(
                self.docker_command,
                "image",
                "inspect",
                self.image,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                return await asyncio.wait_for(process.wait(), timeout=5) == 0
            except asyncio.TimeoutError:
                if process.returncode is None:
                    process.kill()
                await process.wait()
                return False
        except (FileNotFoundError, OSError):
            return False

    async def execute(
        self,
        execution_id: str,
        notebook_content: bytes,
        datasets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not await self.is_available():
            raise DockerUnavailableError(
                "Docker or the configured CodeTrace execution image is unavailable."
            )

        with tempfile.TemporaryDirectory(prefix="codetrace-execution-") as directory:
            root = Path(directory)
            input_dir = root / "input"
            input_dir.mkdir()
            (input_dir / "notebook.ipynb").write_bytes(notebook_content)
            dataset_names: list[str] = []
            seen_names: set[str] = {"notebook.ipynb"}
            for dataset in datasets:
                filename = self._safe_filename(str(dataset["filename"]))
                if filename in seen_names:
                    dataset_prefix = re.sub(
                        r"[^A-Za-z0-9]", "", str(dataset["dataset_id"])
                    )[:8]
                    filename = f"{dataset_prefix or 'dataset'}-{filename}"
                target = input_dir / filename
                if target.resolve().parent != input_dir.resolve() or target.is_symlink():
                    raise DockerExecutionError(
                        "An associated dataset resolved to an unsafe input path."
                    )
                seen_names.add(filename)
                target.write_bytes(bytes(dataset["content"]))
                dataset_names.append(filename)

            container_name = f"codetrace-{execution_id.replace('-', '')[:24]}"
            command = self._docker_run_command(
                container_name, input_dir, dataset_names
            )
            started_at = asyncio.get_running_loop().time()
            container_may_exist = False
            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                container_may_exist = True
                stdout_task = asyncio.create_task(
                    self._read_bounded(process.stdout)
                )
                stderr_task = asyncio.create_task(
                    self._read_bounded(process.stderr)
                )
                wait_task = asyncio.create_task(process.wait())
                try:
                    result_ready = await self._wait_for_result(
                        container_name, wait_task, self.timeout_seconds
                    )
                    if not result_ready:
                        if process.returncode not in {None, 0}:
                            raise DockerExecutionError(
                                "The isolated execution container exited unexpectedly."
                            )
                        raise DockerExecutionError(
                            "The isolated runner did not produce execution results."
                        )
                    result_data = await self._read_container_file(
                        container_name,
                        "/workspace/result.json",
                        MAX_RESULT_FILE_BYTES,
                    )
                    executed_notebook = await self._read_container_file(
                        container_name,
                        "/workspace/executed.ipynb",
                        MAX_EXECUTED_NOTEBOOK_BYTES,
                    )
                    await self._stop_container(container_name)
                    await wait_task
                    stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
                except asyncio.TimeoutError:
                    await self._stop_container(container_name)
                    if process.returncode is None:
                        process.kill()
                    await wait_task
                    await asyncio.gather(stdout_task, stderr_task)
                    return {
                        "status": "timed_out",
                        "error_details": {
                            "message": (
                                f"Notebook execution exceeded the "
                                f"{self.timeout_seconds}-second time limit."
                            )
                        },
                        "logs": "",
                        "duration_seconds": round(
                            asyncio.get_running_loop().time() - started_at, 3
                        ),
                        "environment": self.environment,
                    }
                except asyncio.CancelledError:
                    await self._stop_container(container_name)
                    if process.returncode is None:
                        process.kill()
                    await wait_task
                    await asyncio.gather(stdout_task, stderr_task)
                    raise
                result = json.loads(result_data.decode("utf-8"))
                status = result.get("status")
                if status not in {"completed", "failed", "timed_out"}:
                    raise DockerExecutionError(
                        "The isolated runner returned an invalid result."
                    )
                return {
                    **result,
                    "status": status,
                    "artifact": executed_notebook,
                    "artifact_checksum": hashlib.sha256(
                        executed_notebook
                    ).hexdigest(),
                    "logs": self._bounded_log(stdout, stderr),
                    "duration_seconds": round(
                        asyncio.get_running_loop().time() - started_at, 3
                    ),
                    "environment": self.environment,
                }
            except (FileNotFoundError, OSError) as error:
                raise DockerUnavailableError(
                    "Docker became unavailable before the notebook could run."
                ) from error
            finally:
                if container_may_exist:
                    await self._remove_container(container_name)

    async def _wait_for_result(
        self,
        container_name: str,
        wait_task: asyncio.Task[int],
        timeout_seconds: int,
    ) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        while loop.time() < deadline:
            if wait_task.done():
                await wait_task
                return False
            process = await asyncio.create_subprocess_exec(
                self.docker_command,
                "exec",
                container_name,
                "test",
                "-f",
                "/workspace/result.json",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                probe_timeout = min(5, max(0.1, deadline - loop.time()))
                return_code = await asyncio.wait_for(
                    process.wait(), timeout=probe_timeout
                )
            except asyncio.TimeoutError:
                if process.returncode is None:
                    process.kill()
                await process.wait()
                raise
            if return_code == 0:
                return True
            await asyncio.sleep(min(0.1, max(0, deadline - loop.time())))
        raise asyncio.TimeoutError

    def _docker_run_command(
        self, container_name: str, input_dir: Path, dataset_names: list[str]
    ) -> list[str]:
        input_dir = input_dir.resolve()
        if not input_dir.is_dir() or "," in str(input_dir) or "\n" in str(input_dir):
            raise DockerExecutionError(
                "The isolated execution input directory is invalid."
            )
        if any(
            not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", filename)
            or Path(filename).name != filename
            for filename in dataset_names
        ):
            raise DockerExecutionError(
                "An associated dataset has an unsafe mounted filename."
            )
        cpu_seconds = max(1, self.timeout_seconds)
        return [
            self.docker_command,
            "run",
            "--name",
            container_name,
            "--network",
            "none",
            "--user",
            "10001:10001",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            str(RUNNER_LIMITS["process_limit"]),
            "--memory",
            f"{RUNNER_LIMITS['memory_limit_mb']}m",
            "--memory-swap",
            f"{RUNNER_LIMITS['memory_limit_mb']}m",
            "--cpus",
            str(RUNNER_LIMITS["cpu_limit"]),
            "--ulimit",
            f"cpu={cpu_seconds}:{cpu_seconds}",
            "--mount",
            f"type=bind,source={input_dir},target=/input,readonly",
            "--tmpfs",
            "/workspace:rw,noexec,nosuid,nodev,size=128m,uid=10001,gid=10001",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
            "--workdir",
            "/workspace",
            "--env",
            "HOME=/tmp",
            "--env",
            "JUPYTER_RUNTIME_DIR=/tmp",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            self.image,
            "python",
            "/opt/codetrace/runner.py",
            "/input/notebook.ipynb",
            "/workspace/executed.ipynb",
            "/workspace/result.json",
            str(MAX_NOTEBOOK_OUTPUT_BYTES),
            str(self.timeout_seconds),
            *dataset_names,
        ]

    @staticmethod
    def _safe_filename(filename: str) -> str:
        return safe_dataset_filename(filename)

    async def _read_container_file(
        self, container_name: str, container_path: str, size_limit: int
    ) -> bytes:
        process = await asyncio.create_subprocess_exec(
            self.docker_command,
            "exec",
            container_name,
            "cat",
            container_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if process.stdout is None:
            raise DockerExecutionError(
                "The isolated execution artifact could not be collected."
            )
        content = bytearray()
        deadline = asyncio.get_running_loop().time() + min(
            self.timeout_seconds, 30
        )
        try:
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                chunk = await asyncio.wait_for(
                    process.stdout.read(
                        min(64 * 1024, size_limit + 1 - len(content))
                    ),
                    timeout=remaining,
                )
                if not chunk:
                    break
                content.extend(chunk)
                if len(content) > size_limit:
                    if process.returncode is None:
                        process.kill()
                    await process.wait()
                    raise DockerExecutionError(
                        "The isolated execution artifact exceeded its size limit."
                    )
            return_code = await asyncio.wait_for(
                process.wait(),
                timeout=max(0, deadline - asyncio.get_running_loop().time()),
            )
        except (asyncio.CancelledError, asyncio.TimeoutError):
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if return_code != 0:
            raise DockerExecutionError(
                "The isolated execution artifact could not be collected."
            )
        return bytes(content)

    async def _stop_container(self, container_name: str) -> None:
        process = await asyncio.create_subprocess_exec(
            self.docker_command,
            "stop",
            "--time",
            "1",
            container_name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    async def _remove_container(self, container_name: str) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                self.docker_command,
                "rm",
                "--force",
                container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return_code = await asyncio.wait_for(process.wait(), timeout=10)
        except (FileNotFoundError, OSError, asyncio.TimeoutError) as error:
            raise DockerExecutionError(
                "The isolated execution container could not be cleaned up."
            ) from error
        if return_code != 0:
            raise DockerExecutionError(
                "The isolated execution container could not be cleaned up."
            )

    @staticmethod
    def _bounded_log(stdout: bytes, stderr: bytes) -> str:
        combined = b"".join((stdout, b"\n", stderr))
        if len(combined) > MAX_CAPTURED_LOG_BYTES:
            combined = combined[-MAX_CAPTURED_LOG_BYTES:]
        return combined.decode("utf-8", errors="replace")

    @staticmethod
    async def _read_bounded(stream: asyncio.StreamReader | None) -> bytes:
        if stream is None:
            return b""
        retained = bytearray()
        per_stream_limit = MAX_CAPTURED_LOG_BYTES // 2
        while chunk := await stream.read(4096):
            retained.extend(chunk)
            if len(retained) > per_stream_limit:
                del retained[: len(retained) - per_stream_limit]
        return bytes(retained)
