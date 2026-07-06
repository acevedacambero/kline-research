from __future__ import annotations

import threading
import time

import pytest

from kline.jobs.coordinator import (
    CoordinatorShutdownError,
    DuplicateActiveJobError,
    HeavyTaskCoordinator,
)
from kline.jobs.store import JobStatus, JobStore


def test_jobs_are_serialized_on_one_worker_thread_and_sequence_is_persisted(tmp_path):
    store = JobStore(tmp_path / "jobs.duckdb")
    coordinator = HeavyTaskCoordinator(store)
    lock = threading.Lock()
    running = 0
    maximum_running = 0
    thread_ids: set[int] = set()

    def operation(payload, progress):
        nonlocal running, maximum_running
        value = payload["value"]
        with lock:
            running += 1
            maximum_running = max(maximum_running, running)
            thread_ids.add(threading.get_ident())
        progress({"stage": value})
        time.sleep(0.03)
        with lock:
            running -= 1
        return {"value": value}

    first = coordinator.submit("download", {"value": 1}, operation)
    second = coordinator.submit("features", {"value": 2}, operation)
    assert first.future.result(timeout=2) == {"value": 1}
    assert second.future.result(timeout=2) == {"value": 2}
    coordinator.shutdown()

    assert maximum_running == 1
    assert len(thread_ids) == 1
    assert store.get(first.job_id).status is JobStatus.COMPLETED
    assert store.get(first.job_id).progress == {"stage": 1}
    assert store.get(second.job_id).result == {"value": 2}
    store.close()


def test_duplicate_active_type_is_rejected(tmp_path):
    store = JobStore(tmp_path / "jobs.duckdb")
    coordinator = HeavyTaskCoordinator(store)
    release = threading.Event()

    def blocking(payload, progress):
        release.wait(timeout=2)
        return payload

    first = coordinator.submit("download", {}, blocking)
    with pytest.raises(DuplicateActiveJobError):
        coordinator.submit("download", {}, blocking)
    assert [job.id for job in coordinator.active()] == [first.job_id]
    release.set()
    first.future.result(timeout=2)
    coordinator.shutdown()
    store.close()


def test_shutdown_propagates_unobserved_failure_and_persists_it(tmp_path):
    store = JobStore(tmp_path / "jobs.duckdb")
    coordinator = HeavyTaskCoordinator(store)

    def failing(payload, progress):
        progress({"attempt": 1})
        raise RuntimeError("network exploded")

    submitted = coordinator.submit("download", {}, failing)
    with pytest.raises(CoordinatorShutdownError, match=submitted.job_id) as raised:
        coordinator.shutdown()

    job = store.get(submitted.job_id)
    assert job.status is JobStatus.FAILED
    assert job.error == "RuntimeError: network exploded"
    assert job.progress == {"attempt": 1}
    assert coordinator.active() == []
    assert raised.value.failures[submitted.job_id] == "RuntimeError: network exploded"
    with pytest.raises(CoordinatorShutdownError, match=submitted.job_id):
        coordinator.shutdown()
    store.close()


def test_shutdown_drains_work_and_rejects_new_submissions(tmp_path):
    store = JobStore(tmp_path / "jobs.duckdb")
    coordinator = HeavyTaskCoordinator(store)
    submitted = coordinator.submit("features", {"value": 7}, lambda payload, progress: payload)
    coordinator.shutdown()
    coordinator.shutdown()

    assert submitted.future.done()
    assert store.get(submitted.job_id).status is JobStatus.COMPLETED
    with pytest.raises(RuntimeError, match="shut down"):
        coordinator.submit("features", {}, lambda payload, progress: None)
    store.close()


def test_immediate_jobs_do_not_leave_stale_pending_state(tmp_path):
    store = JobStore(tmp_path / "jobs.duckdb")
    coordinator = HeavyTaskCoordinator(store)

    for index in range(200):
        submitted = coordinator.submit(
            f"immediate-{index}", {"index": index}, lambda payload, progress: payload
        )
        assert submitted.future.result(timeout=2) == {"index": index}

    assert coordinator.pending_count == 0
    assert coordinator.tracked_count == 0
    assert coordinator.active() == []
    coordinator.shutdown()
    store.close()


def test_unserializable_result_marks_job_failed(tmp_path):
    store = JobStore(tmp_path / "jobs.duckdb")
    coordinator = HeavyTaskCoordinator(store)
    submitted = coordinator.submit("features", {}, lambda payload, progress: {object()})

    with pytest.raises(TypeError):
        submitted.future.result(timeout=2)
    with pytest.raises(CoordinatorShutdownError):
        coordinator.shutdown()

    job = store.get(submitted.job_id)
    assert job.status is JobStatus.FAILED
    assert "TypeError" in job.error
    assert "JSON serializable" in job.error
    store.close()


def test_operation_receives_detached_persisted_payload(tmp_path):
    store = JobStore(tmp_path / "jobs.duckdb")
    coordinator = HeavyTaskCoordinator(store)
    release = threading.Event()
    blocker = coordinator.submit(
        "blocker", {}, lambda payload, progress: release.wait(timeout=2)
    )
    payload = {"symbols": ["000001"]}
    queued = coordinator.submit("download", payload, lambda received, progress: received)
    payload["symbols"].append("mutated")
    release.set()

    blocker.future.result(timeout=2)
    assert queued.future.result(timeout=2) == {"symbols": ["000001"]}
    coordinator.shutdown()
    store.close()


def test_concurrent_shutdown_callers_wait_and_receive_same_failure(tmp_path):
    store = JobStore(tmp_path / "jobs.duckdb")
    coordinator = HeavyTaskCoordinator(store)
    release = threading.Event()

    def failing(payload, progress):
        release.wait(timeout=2)
        raise RuntimeError("late failure")

    coordinator.submit("download", {}, failing)
    errors: list[BaseException] = []
    started = threading.Barrier(3)

    def shut_down():
        started.wait(timeout=2)
        try:
            coordinator.shutdown()
        except BaseException as exc:
            errors.append(exc)

    callers = [threading.Thread(target=shut_down) for _ in range(2)]
    for caller in callers:
        caller.start()
    started.wait(timeout=2)
    time.sleep(0.03)
    assert all(caller.is_alive() for caller in callers)
    release.set()
    for caller in callers:
        caller.join(timeout=2)

    assert len(errors) == 2
    assert isinstance(errors[0], CoordinatorShutdownError)
    assert errors[0] is errors[1]
    store.close()


def test_context_manager_preserves_body_exception(tmp_path):
    store = JobStore(tmp_path / "jobs.duckdb")
    with pytest.raises(ValueError, match="body failed") as raised:
        with HeavyTaskCoordinator(store) as coordinator:
            coordinator.submit(
                "download", {}, lambda payload, progress: (_ for _ in ()).throw(RuntimeError("job"))
            )
            raise ValueError("body failed")

    assert any("shutdown" in note for note in raised.value.__notes__)
    store.close()
