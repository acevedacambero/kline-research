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
        self._futures: dict[str, Future[Any]] = {}
        self._job_types: dict[str, str] = {}
        self._shutdown = False

    def submit(self, job_type: str, payload: Any, operation: Operation) -> SubmittedJob:
        with self._lock:
            if self._shutdown:
                raise RuntimeError("coordinator has been shut down")
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
            self._futures[job.id] = future
            future.add_done_callback(lambda completed, job_id=job.id: self._finished(job_id))
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

    def _finished(self, job_id: str) -> None:
        with self._lock:
            self._futures.pop(job_id, None)
            for job_type, active_id in tuple(self._job_types.items()):
                if active_id == job_id:
                    del self._job_types[job_type]
                    break

    def active(self) -> list[Job]:
        with self._lock:
            active_ids = set(self._futures)
            return [
                job
                for job in self._store.list()
                if job.id in active_ids and job.status in {JobStatus.QUEUED, JobStatus.RUNNING}
            ]

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
        self._executor.shutdown(wait=True, cancel_futures=False)

    def __enter__(self) -> HeavyTaskCoordinator:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.shutdown()
