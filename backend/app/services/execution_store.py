"""SQLite persistence for notebook execution inputs, datasets, and results."""

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator


EXECUTION_STATUSES = {
    "queued",
    "running",
    "completed",
    "failed",
    "timed_out",
    "cancelled",
    "unavailable",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _access_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ExecutionStore:
    """Persist execution records without using client-supplied paths."""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        default_dir = Path.home() / ".codetrace"
        self.data_dir = Path(
            data_dir or os.environ.get("CODETRACE_DATA_DIR", default_dir)
        ).expanduser()
        self.database_path = self.data_dir / "executions.sqlite3"

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        self.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.data_dir, 0o700)
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        if os.name != "nt":
            os.chmod(self.database_path, 0o600)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS notebooks (
                notebook_id TEXT PRIMARY KEY,
                original_notebook_id TEXT,
                notebook_type TEXT NOT NULL,
                filename TEXT NOT NULL,
                content BLOB NOT NULL,
                access_token_hash TEXT NOT NULL,
                approved INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS datasets (
                dataset_id TEXT PRIMARY KEY,
                notebook_id TEXT NOT NULL REFERENCES notebooks(notebook_id),
                filename TEXT NOT NULL,
                content BLOB NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS executions (
                execution_id TEXT PRIMARY KEY,
                notebook_id TEXT NOT NULL REFERENCES notebooks(notebook_id),
                status TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                duration_seconds REAL,
                executed_cell_count INTEGER NOT NULL DEFAULT 0,
                successful_cell_count INTEGER NOT NULL DEFAULT 0,
                failed_cell_number INTEGER,
                error_details TEXT,
                python_version TEXT,
                package_versions TEXT NOT NULL DEFAULT '{}',
                environment TEXT NOT NULL DEFAULT '{}',
                dataset_references TEXT NOT NULL DEFAULT '[]',
                outputs TEXT NOT NULL DEFAULT '[]',
                logs TEXT NOT NULL DEFAULT '',
                artifact BLOB,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS corrected_repairs (
                corrected_notebook_id TEXT NOT NULL
                    REFERENCES notebooks(notebook_id),
                repair_id TEXT NOT NULL,
                manifest TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (corrected_notebook_id, repair_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS verifications (
                verification_id TEXT PRIMARY KEY,
                original_notebook_id TEXT NOT NULL
                    REFERENCES notebooks(notebook_id),
                corrected_notebook_id TEXT NOT NULL
                    REFERENCES notebooks(notebook_id),
                original_execution_id TEXT NOT NULL
                    REFERENCES executions(execution_id),
                corrected_execution_id TEXT NOT NULL
                    REFERENCES executions(execution_id),
                result TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.commit()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_original_notebook(
        self, filename: str, content: bytes
    ) -> tuple[str, str]:
        notebook_id = str(uuid.uuid4())
        access_token = secrets.token_urlsafe(32)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO notebooks
                    (notebook_id, notebook_type, filename, content,
                     access_token_hash, created_at)
                VALUES (?, 'original', ?, ?, ?, ?)
                """,
                (notebook_id, filename, content, _access_hash(access_token), _now()),
            )
        return notebook_id, access_token

    def get_notebook(self, notebook_id: str, access_token: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM notebooks WHERE notebook_id = ?", (notebook_id,)
            ).fetchone()
        if row is None or not hmac.compare_digest(
            row["access_token_hash"], _access_hash(access_token)
        ):
            return None
        return dict(row)

    def get_notebook_for_repair(
        self, notebook_id: str, access_token: str
    ) -> dict[str, Any] | None:
        notebook = self.get_notebook(notebook_id, access_token)
        if notebook is None or notebook["notebook_type"] != "original":
            return None
        return notebook

    def create_corrected_notebook(
        self,
        original: dict[str, Any],
        filename: str,
        content: bytes,
        approved_repairs: list[dict[str, Any]] | None = None,
    ) -> str:
        notebook_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO notebooks
                    (notebook_id, original_notebook_id, notebook_type, filename,
                     content, access_token_hash, approved, created_at)
                VALUES (?, ?, 'corrected', ?, ?, ?, 1, ?)
                """,
                (
                    notebook_id,
                    original["notebook_id"],
                    filename,
                    content,
                    original["access_token_hash"],
                    _now(),
                ),
            )
            for repair_manifest in approved_repairs or []:
                repair = repair_manifest["repair"]
                connection.execute(
                    """
                    INSERT INTO corrected_repairs
                        (corrected_notebook_id, repair_id, manifest, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        notebook_id,
                        repair["repair_id"],
                        json.dumps(repair_manifest),
                        _now(),
                    ),
                )
        return notebook_id

    def get_approved_repairs(
        self, corrected_notebook_id: str, access_token: str
    ) -> list[dict[str, Any]] | None:
        notebook = self.get_notebook(corrected_notebook_id, access_token)
        if (
            notebook is None
            or notebook["notebook_type"] != "corrected"
            or not notebook["approved"]
        ):
            return None
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT manifest FROM corrected_repairs
                WHERE corrected_notebook_id = ?
                ORDER BY created_at, repair_id
                """,
                (corrected_notebook_id,),
            ).fetchall()
        return [json.loads(row["manifest"]) for row in rows]

    def add_dataset(
        self, notebook_id: str, filename: str, content: bytes
    ) -> str:
        dataset_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO datasets (dataset_id, notebook_id, filename, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (dataset_id, notebook_id, filename, content, _now()),
            )
        return dataset_id

    def list_datasets(self, notebook_id: str) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT dataset_id, filename, created_at
                FROM datasets WHERE notebook_id = ? ORDER BY created_at
                """,
                (notebook_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_datasets(
        self, notebook_id: str, dataset_ids: list[str]
    ) -> list[dict[str, Any]] | None:
        if not dataset_ids:
            return []
        placeholders = ",".join("?" for _ in dataset_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT dataset_id, filename, content
                FROM datasets
                WHERE notebook_id = ? AND dataset_id IN ({placeholders})
                """,
                [notebook_id, *dataset_ids],
            ).fetchall()
        if len(rows) != len(dataset_ids):
            return None
        return [dict(row) for row in rows]

    def create_execution(
        self,
        notebook_id: str,
        dataset_references: list[dict[str, str]],
        environment: dict[str, Any],
    ) -> str:
        execution_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO executions
                    (execution_id, notebook_id, status, dataset_references,
                     environment, created_at)
                VALUES (?, ?, 'queued', ?, ?, ?)
                """,
                (
                    execution_id,
                    notebook_id,
                    json.dumps(dataset_references),
                    json.dumps(environment),
                    _now(),
                ),
            )
        return execution_id

    def update_execution(self, execution_id: str, **fields: Any) -> None:
        allowed = {
            "status",
            "started_at",
            "completed_at",
            "duration_seconds",
            "executed_cell_count",
            "successful_cell_count",
            "failed_cell_number",
            "error_details",
            "python_version",
            "package_versions",
            "environment",
            "dataset_references",
            "outputs",
            "logs",
            "artifact",
        }
        updates: dict[str, Any] = {}
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"Unsupported execution field: {key}")
            if key in {
                "error_details",
                "package_versions",
                "environment",
                "dataset_references",
                "outputs",
            }:
                value = json.dumps(value)
            updates[key] = value
        if "status" in updates and updates["status"] not in EXECUTION_STATUSES:
            raise ValueError("Unsupported execution status.")
        if not updates:
            return
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE executions SET {assignments} WHERE execution_id = ?",
                [*updates.values(), execution_id],
            )

    def mark_cancelled_if_active(
        self, execution_id: str, completed_at: str, duration_seconds: float | None
    ) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE executions
                SET status = 'cancelled',
                    completed_at = ?,
                    duration_seconds = COALESCE(?, duration_seconds),
                    error_details = ?
                WHERE execution_id = ? AND status IN ('queued', 'running')
                """,
                (
                    completed_at,
                    duration_seconds,
                    json.dumps(
                        {"message": "Execution was cancelled by the user."}
                    ),
                    execution_id,
                ),
            )
        return cursor.rowcount == 1

    def get_execution(
        self, execution_id: str, access_token: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT e.*, n.access_token_hash, n.filename AS notebook_filename,
                       n.notebook_type
                FROM executions e
                JOIN notebooks n ON n.notebook_id = e.notebook_id
                WHERE e.execution_id = ?
                """,
                (execution_id,),
            ).fetchone()
        if row is None or not hmac.compare_digest(
            row["access_token_hash"], _access_hash(access_token)
        ):
            return None
        return self._decode_execution(row)

    @staticmethod
    def _decode_execution(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        del result["access_token_hash"]
        for key in (
            "package_versions",
            "environment",
            "dataset_references",
            "outputs",
        ):
            result[key] = json.loads(result[key])
        result["error_details"] = (
            json.loads(result["error_details"]) if result["error_details"] else None
        )
        result["logs"] = result["logs"] or ""
        result["artifact_available"] = result["artifact"] is not None
        result.pop("artifact", None)
        return result

    def list_executions(
        self, notebook_id: str, access_token: str
    ) -> list[dict[str, Any]] | None:
        notebook = self.get_notebook(notebook_id, access_token)
        if notebook is None:
            return None
        original_notebook_id = (
            notebook["original_notebook_id"]
            if notebook["notebook_type"] == "corrected"
            else notebook_id
        )
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT e.*, n.access_token_hash,
                       n.filename AS notebook_filename, n.notebook_type
                FROM executions e
                JOIN notebooks n ON n.notebook_id = e.notebook_id
                WHERE n.notebook_id = ? OR n.original_notebook_id = ?
                ORDER BY e.created_at DESC
                """,
                (original_notebook_id, original_notebook_id),
            ).fetchall()
        token_hash = _access_hash(access_token)
        return [
            self._decode_execution(row)
            for row in rows
            if hmac.compare_digest(row["access_token_hash"], token_hash)
        ]

    def create_verification(self, result: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO verifications
                    (verification_id, original_notebook_id,
                     corrected_notebook_id, original_execution_id,
                     corrected_execution_id, result, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result["verification_id"],
                    result["original_notebook_id"],
                    result["corrected_notebook_id"],
                    result["original_execution_id"],
                    result["corrected_execution_id"],
                    json.dumps(result),
                    result["verified_at"],
                ),
            )

    def get_verification(
        self, verification_id: str, access_token: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT v.result, n.access_token_hash
                FROM verifications v
                JOIN notebooks n
                  ON n.notebook_id = v.original_notebook_id
                WHERE v.verification_id = ?
                """,
                (verification_id,),
            ).fetchone()
        if row is None or not hmac.compare_digest(
            row["access_token_hash"], _access_hash(access_token)
        ):
            return None
        return json.loads(row["result"])

    def list_verifications(
        self, notebook_id: str, access_token: str
    ) -> list[dict[str, Any]] | None:
        notebook = self.get_notebook(notebook_id, access_token)
        if notebook is None:
            return None
        original_notebook_id = (
            notebook["original_notebook_id"]
            if notebook["notebook_type"] == "corrected"
            else notebook_id
        )
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT result FROM verifications
                WHERE original_notebook_id = ?
                ORDER BY created_at DESC
                """,
                (original_notebook_id,),
            ).fetchall()
        return [json.loads(row["result"]) for row in rows]

    def get_artifact(self, execution_id: str, access_token: str) -> bytes | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT e.artifact, n.access_token_hash
                FROM executions e
                JOIN notebooks n ON n.notebook_id = e.notebook_id
                WHERE e.execution_id = ?
                """,
                (execution_id,),
            ).fetchone()
        if (
            row is None
            or row["artifact"] is None
            or not hmac.compare_digest(
                row["access_token_hash"], _access_hash(access_token)
            )
        ):
            return None
        return bytes(row["artifact"])
