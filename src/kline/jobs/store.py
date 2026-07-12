from __future__ import annotations

import copy
import json
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from os import PathLike
from typing import Any

import duckdb


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    job_type: str
    status: JobStatus
    progress: Any
    payload: Any
    result: Any
    error: str | None
    resumable: bool
    created_at: datetime
    updated_at: datetime


_MEMORY_LIMIT = re.compile(r"^[1-9][0-9]*(?:\.[0-9]+)?(?:KB|MB|GB|TB)$", re.IGNORECASE)
_TRANSITIONS = {
    JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.FAILED},
    JobStatus.RUNNING: {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.INTERRUPTED},
    JobStatus.INTERRUPTED: {JobStatus.QUEUED, JobStatus.FAILED},
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED: set(),
}


class JobStore:
    """Thread-safe owner of the sole DuckDB jobs connection."""

    def __init__(
        self,
        path: str | PathLike[str],
        *,
        memory_limit: str = "2GB",
        threads: int = 2,
    ) -> None:
        if not isinstance(memory_limit, str) or not _MEMORY_LIMIT.fullmatch(memory_limit):
            raise ValueError("memory_limit must be a positive number followed by KB, MB, GB, or TB")
        if isinstance(threads, bool) or not isinstance(threads, int) or not 1 <= threads <= 1024:
            raise ValueError("threads must be an integer between 1 and 1024")
        self._lock = threading.RLock()
        self._connection = duckdb.connect(str(path))
        try:
            # DuckDB does not accept parameters in SET statements. Values are strictly validated above.
            self._connection.execute(f"SET memory_limit='{memory_limit.upper()}'")
            self._connection.execute(f"SET threads={threads}")
            self._initialize_schema()
            self._recover_running_jobs()
        except BaseException:
            self._connection.close()
            raise

    def _initialize_schema(self) -> None:
        with self._lock:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_metadata (
                    key VARCHAR PRIMARY KEY,
                    value VARCHAR NOT NULL
                )
                """
            )
            self._connection.execute(
                "INSERT INTO schema_metadata VALUES (?, ?) ON CONFLICT (key) DO NOTHING",
                ["schema_version", "1"],
            )
            version_row = self._connection.execute(
                "SELECT value FROM schema_metadata WHERE key = ?", ["schema_version"]
            ).fetchone()
            if version_row != ("1",):
                found = version_row[0] if version_row else "missing"
                raise RuntimeError(f"unsupported jobs schema version {found}; expected 1")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id VARCHAR PRIMARY KEY,
                    job_type VARCHAR NOT NULL,
                    status VARCHAR NOT NULL,
                    progress JSON,
                    payload JSON NOT NULL,
                    result JSON,
                    error VARCHAR,
                    resumable BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
                    updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp
                )
                """
            )

    def _recover_running_jobs(self) -> None:
        with self._lock:
            self._connection.execute(
                "UPDATE jobs SET status = ?, updated_at = current_timestamp WHERE status = ?",
                [JobStatus.INTERRUPTED.value, JobStatus.RUNNING.value],
            )

    @property
    def schema_version(self) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT value FROM schema_metadata WHERE key = ?", ["schema_version"]
            ).fetchone()
            return int(row[0])

    def create(self, job_type: str, payload: Any, *, resumable: bool = False) -> Job:
        job_id = str(uuid.uuid4())
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO jobs (id, job_type, status, progress, payload, resumable)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [job_id, job_type, JobStatus.QUEUED.value, None, _json(payload), resumable],
            )
            return self._require(job_id)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT id, job_type, status, progress, payload, result, error, resumable,
                          created_at, updated_at FROM jobs WHERE id = ?""",
                [job_id],
            ).fetchone()
            return _job_from_row(row) if row else None

    def _require(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def list(self, *, status: JobStatus | None = None) -> list[Job]:
        with self._lock:
            sql = """SELECT id, job_type, status, progress, payload, result, error, resumable,
                            created_at, updated_at FROM jobs"""
            parameters: list[str] = []
            if status is not None:
                sql += " WHERE status = ?"
                parameters.append(status.value)
            sql += " ORDER BY created_at, id"
            return [_job_from_row(row) for row in self._connection.execute(sql, parameters).fetchall()]

    def transition(self, job_id: str, status: JobStatus) -> Job:
        status = JobStatus(status)
        with self._lock:
            current = self._require(job_id)
            if status not in _TRANSITIONS[current.status]:
                raise ValueError(f"invalid job transition: {current.status.value} -> {status.value}")
            self._connection.execute(
                "UPDATE jobs SET status = ?, updated_at = current_timestamp WHERE id = ?",
                [status.value, job_id],
            )
            return self._require(job_id)

    def requeue(self, job_id: str) -> Job:
        with self._lock:
            current = self._require(job_id)
            if current.status is not JobStatus.INTERRUPTED:
                raise ValueError(f"cannot requeue job in {current.status.value} state")
            if not current.resumable:
                raise ValueError("job is not resumable")
            self._connection.execute(
                "UPDATE jobs SET status = ?, error = NULL, updated_at = current_timestamp WHERE id = ?",
                [JobStatus.QUEUED.value, job_id],
            )
            return self._require(job_id)

    def update_progress(self, job_id: str, progress: Any) -> Job:
        with self._lock:
            self._require(job_id)
            self._connection.execute(
                "UPDATE jobs SET progress = ?, updated_at = current_timestamp WHERE id = ?",
                [_json(progress), job_id],
            )
            return self._require(job_id)

    def complete(self, job_id: str, result: Any) -> Job:
        with self._lock:
            current = self._require(job_id)
            if JobStatus.COMPLETED not in _TRANSITIONS[current.status]:
                raise ValueError(f"cannot complete job in {current.status.value} state")
            self._connection.execute(
                """UPDATE jobs SET status = ?, result = ?, error = NULL,
                       updated_at = current_timestamp WHERE id = ?""",
                [JobStatus.COMPLETED.value, _json(result), job_id],
            )
            return self._require(job_id)

    def fail(self, job_id: str, error: str) -> Job:
        with self._lock:
            current = self._require(job_id)
            if JobStatus.FAILED not in _TRANSITIONS[current.status]:
                raise ValueError(f"cannot fail job in {current.status.value} state")
            self._connection.execute(
                """UPDATE jobs SET status = ?, error = ?, updated_at = current_timestamp
                   WHERE id = ?""",
                [JobStatus.FAILED.value, error, job_id],
            )
            return self._require(job_id)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> JobStore:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode(value: Any) -> Any:
    if value is None:
        return None
    return copy.deepcopy(json.loads(value) if isinstance(value, str) else value)


def _job_from_row(row: tuple[Any, ...]) -> Job:
    return Job(
        id=row[0],
        job_type=row[1],
        status=JobStatus(row[2]),
        progress=_decode(row[3]),
        payload=_decode(row[4]),
        result=_decode(row[5]),
        error=row[6],
        resumable=row[7],
        created_at=row[8],
        updated_at=row[9],
    )
