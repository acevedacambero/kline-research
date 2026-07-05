from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from .store import Job, JobStatus, JobStore

ProgressCallback = Callable[[Any], None]
Operation = Callable[[Any, ProgressCallback], Any]


class DuplicateActiveJobError(RuntimeError):
    pass


class CoordinatorShutdownError(RuntimeError):
    """One or more jobs failed before the coordinator finished shutting down."""

    def __init__(self, failures: dict[str, str]) -> None:
        self.failures = dict(failures)
        details = ", ".join(f"{job_id}: {error}" for job_id, error in failures.items())
        super().__init__(f"heavy jobs failed during shutdown ({details})")


@dataclass(frozen=True, slots=True)
class SubmittedJob:
    job_id: str
    future: Future[Any]


class HeavyTaskCoordinator:
    """Runs all heavy work through one process-local worker."""

    def __init__(self, store: JobStore) -> None:
        self._store = store
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kline-heavy-job")
        self._lock = threading.RLock()
        self._submitted: dict[str, Future[Any]] = {}
        self._job_types: dict[str, str] = {}
        self._shutdown = False
        self._shutdown_error: CoordinatorShutdownError | None = None

    def submit(self, job_type: str, payload: Any, operation: Operation) -> SubmittedJob:
        with self._lock:
            if self._shutdown:
                raise RuntimeError("coordinator has been shut down")
            self._prune_job_types()
            if job_type in self._job_types:
                raise DuplicateActiveJobError(f"active {job_type!r} job already exists")
            job = self._store.create(job_type, payload)
            self._job_types[job_type] = job.id
            try:
                future = self._executor.submit(self._run, job.id, payload, operation)
            except BaseException:
                del self._job_types[job_type]
                self._store.fail(job.id, "submission failed")
                raise
            self._submitted[job.id] = future
            return SubmittedJob(job.id, future)

    def _run(self, job_id: str, payload: Any, operation: Operation) -> Any:
        self._store.transition(job_id, JobStatus.RUNNING)
        try:
            result = operation(payload, lambda progress: self._store.update_progress(job_id, progress))
        except BaseException as exc:
            self._store.fail(job_id, f"{type(exc).__name__}: {exc}")
            raise
        self._store.complete(job_id, result)
        return result

    def _prune_job_types(self) -> None:
        for job_type, job_id in tuple(self._job_types.items()):
            future = self._submitted.get(job_id)
            if future is not None and future.done():
                del self._job_types[job_type]

    @property
    def pending_count(self) -> int:
        with self._lock:
            return sum(not future.done() for future in self._submitted.values())

    def active(self) -> list[Job]:
        with self._lock:
            active_ids = {job_id for job_id, future in self._submitted.items() if not future.done()}
            return [
                job
                for job in self._store.list()
                if job.id in active_ids and job.status in {JobStatus.QUEUED, JobStatus.RUNNING}
            ]

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                if self._shutdown_error is not None:
                    raise self._shutdown_error
                return
            self._shutdown = True
        self._executor.shutdown(wait=True, cancel_futures=False)
        failures: dict[str, str] = {}
        for job_id, future in self._submitted.items():
            try:
                future.result()
            except BaseException as exc:
                failures[job_id] = f"{type(exc).__name__}: {exc}"
        if failures:
            self._shutdown_error = CoordinatorShutdownError(failures)
            raise self._shutdown_error

    def __enter__(self) -> HeavyTaskCoordinator:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.shutdown()
