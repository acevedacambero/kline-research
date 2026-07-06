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
        self._condition = threading.Condition(self._lock)
        self._futures: dict[str, Future[Any]] = {}
        self._job_types: dict[str, str] = {}
        self._failures: dict[str, str] = {}
        self._shutdown_state = "open"
        self._shutdown_error: CoordinatorShutdownError | None = None

    def submit(self, job_type: str, payload: Any, operation: Operation) -> SubmittedJob:
        with self._lock:
            if self._shutdown_state != "open":
                raise RuntimeError("coordinator has been shut down")
            if job_type in self._job_types:
                raise DuplicateActiveJobError(f"active {job_type!r} job already exists")
            job = self._store.create(job_type, payload)
            self._job_types[job_type] = job.id
            try:
                future = self._executor.submit(self._run, job.id, job.payload, operation)
            except BaseException:
                del self._job_types[job_type]
                self._store.fail(job.id, "submission failed")
                raise
            self._futures[job.id] = future
            future.add_done_callback(
                lambda completed, job_id=job.id, job_type=job_type: self._finished(
                    job_id, job_type, completed
                )
            )
            return SubmittedJob(job.id, future)

    def _run(self, job_id: str, payload: Any, operation: Operation) -> Any:
        try:
            self._store.transition(job_id, JobStatus.RUNNING)
            result = operation(payload, lambda progress: self._store.update_progress(job_id, progress))
            self._store.complete(job_id, result)
            return result
        except BaseException as exc:
            error = f"{type(exc).__name__}: {exc}"
            try:
                self._store.fail(job_id, error)
            except BaseException as persistence_error:
                exc.add_note(
                    f"could not persist failed state for job {job_id}: "
                    f"{type(persistence_error).__name__}: {persistence_error}"
                )
            raise

    def _finished(self, job_id: str, job_type: str, future: Future[Any]) -> None:
        with self._condition:
            if self._futures.pop(job_id, None) is None:
                return
            if self._job_types.get(job_type) == job_id:
                del self._job_types[job_type]
            if future.cancelled():
                self._failures[job_id] = "CancelledError: job was cancelled"
            else:
                exception = future.exception()
                if exception is not None:
                    self._failures[job_id] = f"{type(exception).__name__}: {exception}"
            self._condition.notify_all()

    def _prune_completed_locked(self) -> None:
        for job_id, future in tuple(self._futures.items()):
            if future.done():
                job = self._store.get(job_id)
                job_type = job.job_type if job is not None else ""
                self._finished(job_id, job_type, future)

    @property
    def pending_count(self) -> int:
        with self._lock:
            self._prune_completed_locked()
            return len(self._futures)

    @property
    def tracked_count(self) -> int:
        with self._lock:
            self._prune_completed_locked()
            return len(self._futures)

    def active(self) -> list[Job]:
        with self._lock:
            self._prune_completed_locked()
            active_ids = set(self._futures)
            return [
                job
                for job in self._store.list()
                if job.id in active_ids and job.status in {JobStatus.QUEUED, JobStatus.RUNNING}
            ]

    def shutdown(self) -> None:
        with self._condition:
            if self._shutdown_state == "draining":
                self._condition.wait_for(lambda: self._shutdown_state == "drained")
                self._raise_shutdown_error()
                return
            if self._shutdown_state == "drained":
                self._raise_shutdown_error()
                return
            self._shutdown_state = "draining"
        self._executor.shutdown(wait=True, cancel_futures=False)
        with self._condition:
            self._prune_completed_locked()
            if self._failures:
                self._shutdown_error = CoordinatorShutdownError(self._failures)
            self._shutdown_state = "drained"
            self._condition.notify_all()
            self._raise_shutdown_error()

    def _raise_shutdown_error(self) -> None:
        if self._shutdown_error is not None:
            raise self._shutdown_error

    def __enter__(self) -> HeavyTaskCoordinator:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        try:
            self.shutdown()
        except CoordinatorShutdownError as shutdown_error:
            if isinstance(exc, BaseException):
                exc.add_note(f"coordinator shutdown also failed: {shutdown_error}")
                return
            raise
