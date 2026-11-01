"""Asynchronous orchestration and lifecycle management for notebook runs."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from backend.app.services.docker_runner import (
    DockerExecutionError,
    DockerRunner,
    DockerUnavailableError,
    safe_dataset_filename,
)
from backend.app.services.execution_store import ExecutionStore


logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExecutionRequestError(ValueError):
    """The execution request does not match stored notebook or dataset records."""


class ExecutionManager:
    MAX_ACTIVE_OR_QUEUED_EXECUTIONS = 8

    def __init__(
        self, store: ExecutionStore, runner: DockerRunner | None = None
    ) -> None:
        self.store = store
        self.runner = runner or DockerRunner()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._pending_starts = 0
        self._execution_slots = asyncio.Semaphore(2)

    async def start(
        self,
        notebook: dict[str, Any],
        dataset_ids: list[str],
        access_token: str,
    ) -> dict[str, Any]:
        if (
            len(self._tasks) + self._pending_starts
            >= self.MAX_ACTIVE_OR_QUEUED_EXECUTIONS
        ):
            raise ExecutionRequestError(
                "The local execution queue is full. Wait for a run to finish."
            )
        self._pending_starts += 1
        try:
            return await self._start_reserved(notebook, dataset_ids, access_token)
        finally:
            self._pending_starts -= 1

    async def start_pair(
        self,
        original: dict[str, Any],
        corrected: dict[str, Any],
        dataset_ids: list[str],
        access_token: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if (
            len(self._tasks) + self._pending_starts + 2
            > self.MAX_ACTIVE_OR_QUEUED_EXECUTIONS
        ):
            raise ExecutionRequestError(
                "The local execution queue does not have room for both experiments."
            )
        self._pending_starts += 2
        try:
            original_execution = await self._start_reserved(
                original, dataset_ids, access_token
            )
            corrected_execution = await self._start_reserved(
                corrected, dataset_ids, access_token
            )
            return original_execution, corrected_execution
        finally:
            self._pending_starts -= 2

    async def _start_reserved(
        self,
        notebook: dict[str, Any],
        dataset_ids: list[str],
        access_token: str,
    ) -> dict[str, Any]:
        if len(dataset_ids) != len(set(dataset_ids)):
            raise ExecutionRequestError("Dataset IDs must be distinct.")
        dataset_owner_id = (
            notebook["original_notebook_id"] or notebook["notebook_id"]
        )
        datasets = self.store.get_datasets(dataset_owner_id, dataset_ids)
        if datasets is None:
            raise ExecutionRequestError(
                "One or more datasets are not associated with this notebook."
            )
        filenames = [
            safe_dataset_filename(item["filename"]).casefold() for item in datasets
        ]
        if len(filenames) != len(set(filenames)):
            raise ExecutionRequestError(
                "Selected datasets must have distinct filenames after path normalization."
            )

        dataset_references = [
            {"dataset_id": item["dataset_id"], "filename": item["filename"]}
            for item in datasets
        ]
        execution_id = self.store.create_execution(
            notebook["notebook_id"],
            dataset_references,
            self.runner.environment,
        )
        availability_started = asyncio.get_running_loop().time()
        attempted_at = _now()
        if not await self.runner.is_available():
            completed_at = _now()
            self.store.update_execution(
                execution_id,
                status="unavailable",
                started_at=attempted_at,
                completed_at=completed_at,
                duration_seconds=round(
                    asyncio.get_running_loop().time() - availability_started, 3
                ),
                error_details={
                    "message": (
                        "Isolated execution is unavailable. Start Docker and build "
                        "the configured CodeTrace runner image."
                    )
                },
            )
            result = self.store.get_execution(execution_id, access_token)
            if result is None:
                raise RuntimeError("The newly created execution could not be loaded.")
            return result

        task = asyncio.create_task(
            self._run(execution_id, notebook, datasets),
            name=f"codetrace-execution-{execution_id}",
        )
        self._tasks[execution_id] = task
        result = self.store.get_execution(execution_id, access_token)
        if result is None:
            raise RuntimeError("The newly created execution could not be loaded.")
        return result

    async def _run(
        self,
        execution_id: str,
        notebook: dict[str, Any],
        datasets: list[dict[str, Any]],
    ) -> None:
        started: float | None = None
        try:
            async with self._execution_slots:
                started = asyncio.get_running_loop().time()
                self.store.update_execution(
                    execution_id, status="running", started_at=_now()
                )
                result = await self.runner.execute(
                    execution_id, bytes(notebook["content"]), datasets
                )
                self.store.update_execution(
                    execution_id,
                    status=result["status"],
                    completed_at=_now(),
                    duration_seconds=round(
                        asyncio.get_running_loop().time() - started, 3
                    ),
                    executed_cell_count=result.get("executed_cell_count", 0),
                    successful_cell_count=result.get("successful_cell_count", 0),
                    failed_cell_number=result.get("failed_cell_number"),
                    error_details=result.get("error_details"),
                    python_version=result.get("python_version"),
                    package_versions=result.get("package_versions", {}),
                    environment=result.get("environment", self.runner.environment),
                    outputs=result.get("outputs", []),
                    logs=result.get("logs", ""),
                    artifact=result.get("artifact"),
                )
        except asyncio.CancelledError:
            self.store.update_execution(
                execution_id,
                status="cancelled",
                completed_at=_now(),
                duration_seconds=(
                    round(asyncio.get_running_loop().time() - started, 3)
                    if started is not None
                    else None
                ),
                error_details={"message": "Execution was cancelled by the user."},
            )
            raise
        except DockerUnavailableError:
            self.store.update_execution(
                execution_id,
                status="unavailable",
                completed_at=_now(),
                duration_seconds=(
                    round(asyncio.get_running_loop().time() - started, 3)
                    if started is not None
                    else None
                ),
                error_details={
                    "message": (
                        "Docker became unavailable before the notebook could run."
                    )
                },
            )
        except DockerExecutionError as error:
            self.store.update_execution(
                execution_id,
                status="failed",
                completed_at=_now(),
                duration_seconds=(
                    round(asyncio.get_running_loop().time() - started, 3)
                    if started is not None
                    else None
                ),
                error_details={"message": str(error)},
            )
        except Exception:
            logger.exception(
                "Unexpected internal error while running execution %s",
                execution_id,
            )
            self.store.update_execution(
                execution_id,
                status="failed",
                completed_at=_now(),
                duration_seconds=(
                    round(asyncio.get_running_loop().time() - started, 3)
                    if started is not None
                    else None
                ),
                error_details={
                    "message": "Execution failed due to an internal runner error."
                },
            )
        finally:
            self._tasks.pop(execution_id, None)

    async def cancel(self, execution_id: str) -> bool:
        task = self._tasks.get(execution_id)
        if task is None or task.done():
            return False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self.store.mark_cancelled_if_active(
            execution_id,
            _now(),
            None,
        )
        return True
