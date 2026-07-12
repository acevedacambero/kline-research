from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Literal
import json
import queue
import threading
import time

import pandas as pd
import pyarrow.parquet as pq
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings, VERSIONS
from .access import AccessDenied, CloudflareAccessVerifier
from .data.akshare_source import AkShareSource
from .data.history_backfill import (
    BackfillCandidate,
    BackfillCoverageError,
    HistoryBackfillService,
)
from .data.provider_policy import (
    ProductionProviderPolicy as HybridDownloadSource,
    SUPPORTED_EXCHANGES,
)
from .data.pipeline import DatasetPipeline
from .data.tencent_source import TencentHttpSource
from .features import FEATURE_DEFINITION_VERSION, compute_daily_features
from .features.batch import BatchFeatureBuilder, FeatureDatasetStore
from .jobs import CoordinatorShutdownError, HeavyTaskCoordinator, Job, JobStatus, JobStore
from .p1 import (
    compute_drawdown_label,
    compute_forward_labels,
    compute_label_maturity_date,
    compute_path_label,
    resolve_executable_entry,
    resolve_executable_exit,
    sample_eligibility,
)
from .p1.batch import BatchLabelBuilder, LabelDatasetStore
from .p1.market_rules import is_no_limit_session, status_from_name
from .score import SCORE_DEFINITION_VERSION, compute_rule_score
from .score.batch import BatchScoreBuilder, ScoreDatasetStore
from .validation import calibrate_score, validate_single_factor, validate_top_score_portfolio
from .model import train_multifeature_baseline, train_score_baseline, walk_forward_score_baseline


class _InjectedProviderAdapter:
    """Adapt an explicitly injected legacy source without making network calls."""

    def __init__(self, source) -> None:
        self.source = source

    def fetch_history(self, exchange, code, start_date, end_date):
        return self.source.stock_history(code, start_date, end_date, "")

    def index_history(self, exchange, start_date, end_date):
        symbol = "000001" if exchange == "sh" else "399001"
        return self.source.index_history(symbol, start_date, end_date)

    def sina_raw_history(self, exchange, code, start_date, end_date):
        method = getattr(self.source, "sina_raw_history", None)
        if method is not None:
            return method(exchange, code, start_date, end_date)
        return self.source.stock_history(code, start_date, end_date, "")

    def sina_adjustment_factors(self, exchange, code):
        method = getattr(self.source, "sina_adjustment_factors", None)
        if method is not None:
            return method(exchange, code)
        return self.source.adjustment_factors(code)


class ImportRequest(BaseModel):
    scope: str = "representative"
    refresh: bool = False


class AuditRequest(BaseModel):
    exchange: str
    code: str
    signal_date: date


LabelColumn = Literal[
    "p5_executable_return",
    "p5_delayed_executable_return",
    "p10_executable_return",
    "p10_delayed_executable_return",
    "p20_executable_return",
    "p20_delayed_executable_return",
    "p60_executable_return",
    "p60_delayed_executable_return",
]


class SingleFactorValidationRequest(BaseModel):
    factor_column: Literal["score"] = "score"
    label_column: LabelColumn = "p20_executable_return"
    buckets: int = 5
    as_of_date: date | None = None


class CalibrationRequest(BaseModel):
    label_column: LabelColumn = "p20_executable_return"
    buckets: int = 10
    as_of_date: date | None = None


class ScanRequest(BaseModel):
    as_of_date: date | None = None
    exchange: str | None = None
    min_score: float = Field(70, ge=0, le=100)
    limit: int = Field(50, ge=1, le=200)


class BaselineModelRequest(BaseModel):
    label_column: LabelColumn = "p20_executable_return"
    train_until: date | None = None


class WalkForwardRequest(BaseModel):
    label_column: LabelColumn = "p20_executable_return"
    folds: int = Field(3, ge=2, le=5)


class PortfolioValidationRequest(BaseModel):
    label_column: LabelColumn = "p20_executable_return"
    top_fraction: float = Field(0.1, ge=0.01, le=1)
    as_of_date: date | None = None
    non_overlapping: bool = False
    transaction_cost_bps: float = Field(0, ge=0, le=1000)
    slippage_bps: float = Field(0, ge=0, le=1000)


def _task_response(job: Job) -> dict:
    if isinstance(job.payload, list):
        total = len(job.payload)
    elif isinstance(job.payload, dict) and isinstance(job.payload.get("securities"), list):
        total = len(job.payload["securities"])
    elif isinstance(job.payload, dict) and isinstance(job.payload.get("candidates"), list):
        total = len(job.payload["candidates"])
    else:
        total = 0
    defaults = {"total": total, "done": 0, "rows": 0, "errors": [],
                "currentSecurity": None}
    if job.job_type == "import":
        defaults.update({"stage": "queued", "speed": 0.0, "etaSeconds": None,
                         "directAvailable": job.payload.get("directAvailable")
                         if isinstance(job.payload, dict) else None})
    elif job.job_type == "history_backfill":
        defaults.update({
            "completed": 0,
            "listingHistoryShort": 0,
            "speed": 0.0,
            "etaSeconds": None,
        })
    progress = job.progress if isinstance(job.progress, dict) else {}
    result = job.result if isinstance(job.result, dict) else {}
    item = {"id": job.id, "jobType": job.job_type, **defaults, **progress, **result}
    status = job.status.value
    if job.status is JobStatus.COMPLETED and item["errors"]:
        status = "completed_with_errors"
    item["status"] = status
    if job.error and not item["errors"]:
        item["errors"] = [{"message": job.error}]
    return item


class _DurableItems:
    def __init__(self, store: JobStore, job_types: set[str]):
        self.store = store
        self.job_types = job_types

    def __contains__(self, task_id: str) -> bool:
        job = self.store.get(task_id)
        return job is not None and job.job_type in self.job_types

    def __getitem__(self, task_id: str) -> dict:
        job = self.store.get(task_id)
        if job is None or job.job_type not in self.job_types:
            raise KeyError(task_id)
        return _task_response(job)


class _TaskFacade:
    def __init__(self, coordinator: HeavyTaskCoordinator, store: JobStore, lock: threading.Lock,
                 job_types: set[str]):
        self.coordinator = coordinator
        self.store = store
        self.items = _DurableItems(store, job_types)
        self.lock = lock

    def active(self) -> dict | None:
        active = self.coordinator.active()
        if active:
            task_id = active[0].id
            raise HTTPException(409, detail={
                "code": "HEAVY_JOB_ALREADY_RUNNING",
                "message": f"A heavy job is already running: {task_id}",
                "taskId": task_id,
            })
        return None

    def _submit(self, job_type, payload, operation) -> str:
        with self.lock:
            active = self.coordinator.active()
            if active:
                task_id = active[0].id
                raise HTTPException(409, detail={
                    "code": "HEAVY_JOB_ALREADY_RUNNING",
                    "message": f"A heavy job is already running: {task_id}",
                    "taskId": task_id,
                })
            interrupted = [
                job
                for job in self.store.list(status=JobStatus.INTERRUPTED)
                if job.job_type == job_type and job.resumable
            ]
            if interrupted:
                return self.coordinator.resume(interrupted[-1].id, operation).job_id
            return self.coordinator.submit(
                job_type, payload, operation, resumable=True
            ).job_id


class TaskStore(_TaskFacade):
    def __init__(self, coordinator, store, lock, workers: int):
        super().__init__(coordinator, store, lock, {"import"})
        self.workers = max(1, min(workers, 3))

    def submit(self, pipeline, source, securities, start_date, end_date, timeout_seconds) -> str:
        initial = {"total": len(securities), "done": 0, "errors": [],
                   "currentSecurity": None, "stage": "queued", "speed": 0.0,
                   "etaSeconds": None, "directAvailable": source.direct_available}

        payload = {"securities": securities, "directAvailable": source.direct_available}

        def operation(payload, progress):
            state = dict(initial)
            state["stage"] = "parallel-download"
            progress(state)
            started = time.monotonic()

            def fetch(security):
                return source.fetch_bundle(security["exchange"], security["code"],
                                           start_date, end_date)

            def record_finished():
                state["done"] += 1
                elapsed = max(time.monotonic() - started, 0.001)
                state["speed"] = round(state["done"] / elapsed, 3)
                remaining = state["total"] - state["done"]
                state["etaSeconds"] = (
                    round(remaining / state["speed"]) if state["speed"] else None
                )
                state["directAvailable"] = source.direct_available
                progress(state)

            securities = payload["securities"]
            for offset in range(0, len(securities), self.workers):
                batch = securities[offset:offset + self.workers]
                executor = ThreadPoolExecutor(max_workers=len(batch),
                                              thread_name_prefix="market-fetch")
                try:
                    futures = {
                        executor.submit(fetch, security): security for security in batch
                    }
                    completed, pending = wait(futures, timeout=timeout_seconds)
                    for future in completed:
                        security = futures[future]
                        key = f'{security["exchange"]}{security["code"]}'
                        state["currentSecurity"] = key
                        state["stage"] = "writing-snapshot"
                        try:
                            raw, factors = future.result()
                            pipeline.import_security(
                                security["exchange"], security["code"], raw, factors
                            )
                        except Exception as exc:
                            state["errors"].append({"security": key, "message": str(exc)})
                        finally:
                            record_finished()
                    for future in pending:
                        future.cancel()
                        security = futures[future]
                        key = f'{security["exchange"]}{security["code"]}'
                        state["errors"].append({
                            "security": key,
                            "message": f"fetch timed out after {timeout_seconds}s",
                        })
                        record_finished()
                finally:
                    executor.shutdown(wait=False, cancel_futures=True)
            state["currentSecurity"] = None
            state["stage"] = "finished"
            return state

        return self._submit("import", payload, operation)


class LabelTaskStore(_TaskFacade):
    def __init__(self, coordinator, store, lock):
        super().__init__(coordinator, store, lock, {"labels"})

    def submit(self, pipeline, source, securities, names, output_root) -> str:
        def operation(payload, progress):
            state = {"total": len(payload), "done": 0, "rows": 0, "errors": []}
            benchmarks = {}
            builder, output = BatchLabelBuilder(), LabelDatasetStore(output_root)
            for security in payload:
                key = f'{security["exchange"]}{security["code"]}'
                try:
                    exchange = security["exchange"]
                    if exchange not in benchmarks:
                        frame = source.index_history(exchange, date(1990, 1, 1), date.today())
                        for column in ("open", "high", "low", "close"):
                            frame[f"{column}_qfq"] = frame[column]
                            frame[f"{column}_total_return"] = frame[column]
                        benchmarks[exchange] = frame.to_dict("records")
                    bars = pd.read_parquet(security["derived_path"]).to_dict("records")
                    rows = builder.build(exchange, security["code"], bars, benchmarks[exchange],
                                         security["snapshot_version"],
                                         st_status=status_from_name(names.get(key, "")).is_st)
                    state["rows"] += output.write(exchange, security["code"], rows).rows
                except Exception as exc:
                    state["errors"].append({"security": key, "message": str(exc)})
                finally:
                    state["done"] += 1
                    progress(state)
            return state
        return self._submit("labels", securities, operation)


class FeatureTaskStore(_TaskFacade):
    def __init__(self, coordinator, store, lock):
        super().__init__(coordinator, store, lock, {"features"})

    def submit(self, securities, output_root) -> str:
        def operation(payload, progress):
            state = {"total": len(payload), "done": 0, "rows": 0, "errors": [],
                     "currentSecurity": None}
            builder = BatchFeatureBuilder(FeatureDatasetStore(output_root))
            def on_progress(security, report, error):
                state["currentSecurity"] = security
                state["done"] += 1
                if report:
                    state["rows"] += report.rows
                if error:
                    state["errors"].append({"security": security, "message": str(error)})
                progress(state)
            builder.build_many(payload, on_progress=on_progress)
            state["currentSecurity"] = None
            return state
        return self._submit("features", securities, operation)


class ScoreTaskStore(_TaskFacade):
    def __init__(self, coordinator, store, lock):
        super().__init__(coordinator, store, lock, {"scores"})

    def submit(self, securities, output_root) -> str:
        def operation(payload, progress):
            state = {"total": len(payload), "done": 0, "rows": 0, "errors": [],
                     "currentSecurity": None}
            builder = BatchScoreBuilder(ScoreDatasetStore(output_root))

            def on_progress(security, report, error):
                state["currentSecurity"] = security
                state["done"] += 1
                if report:
                    state["rows"] += report.rows
                if error:
                    state["errors"].append({"security": security, "message": str(error)})
                progress(state)

            builder.build_many(payload, on_progress=on_progress)
            state["currentSecurity"] = None
            return state

        return self._submit("scores", securities, operation)


class HistoryBackfillTaskStore(_TaskFacade):
    def __init__(self, coordinator, store, lock):
        super().__init__(coordinator, store, lock, {"history_backfill"})

    def submit(
        self, service, candidates, as_of_date: date, timeout_seconds: float | None = None
    ) -> str:
        payload = {
            "candidates": [
                {
                    **asdict(candidate),
                    "path": str(candidate.path),
                }
                for candidate in candidates
            ],
            "asOfDate": as_of_date.isoformat(),
        }

        def operation(payload, progress):
            state = {
                "total": len(payload["candidates"]),
                "done": 0,
                "completed": 0,
                "listingHistoryShort": 0,
                "errors": [],
                "currentSecurity": None,
                "speed": 0.0,
                "etaSeconds": None,
            }
            started = time.monotonic()

            def fetch_with_timeout(candidate, as_of_date):
                if timeout_seconds is None:
                    return service.fetch_history_bundle(
                        candidate, as_of_date=as_of_date
                    )
                result_queue = queue.Queue(maxsize=1)

                def fetch():
                    try:
                        result_queue.put_nowait(
                            (
                                "ok",
                                service.fetch_history_bundle(
                                    candidate, as_of_date=as_of_date
                                ),
                            )
                        )
                    except Exception as exc:
                        result_queue.put_nowait(("error", exc))

                thread = threading.Thread(
                    target=fetch,
                    name=f"history-fetch-{candidate.exchange}{candidate.code}",
                    daemon=True,
                )
                thread.start()
                thread.join(timeout_seconds)
                if thread.is_alive():
                    raise BackfillCoverageError(
                        "HISTORY_FETCH_TIMEOUT",
                        f"history fetch timed out after {timeout_seconds:g}s",
                    )
                status, result = result_queue.get_nowait()
                if status == "error":
                    raise result
                return result

            def run_backfill(candidate, as_of_date):
                if not all(
                    hasattr(service, name)
                    for name in (
                        "fetch_history_bundle",
                        "apply_history_bundle",
                        "record_failure",
                    )
                ):
                    return service.backfill(candidate, as_of_date=as_of_date)
                try:
                    raw, factors = fetch_with_timeout(candidate, as_of_date)
                    return service.apply_history_bundle(
                        candidate, raw, factors, as_of_date=as_of_date
                    )
                except Exception as exc:
                    service.record_failure(candidate, exc)
                    raise exc

            for item in payload["candidates"]:
                candidate = BackfillCandidate(
                    **{**item, "path": Path(item["path"])}
                )
                key = f"{candidate.exchange}{candidate.code}"
                state["currentSecurity"] = key
                try:
                    result = run_backfill(
                        candidate,
                        date.fromisoformat(payload["asOfDate"]),
                    )
                    if result.status == "listing_history_short":
                        state["listingHistoryShort"] += 1
                    else:
                        state["completed"] += 1
                except Exception as exc:
                    state["errors"].append(
                        {
                            "security": key,
                            "stage": "history-fetch",
                            "code": getattr(exc, "code", "HISTORY_BACKFILL_FAILED"),
                            "message": str(exc),
                        }
                    )
                finally:
                    state["done"] += 1
                    elapsed = max(time.monotonic() - started, 0.001)
                    state["speed"] = round(state["done"] / elapsed, 3)
                    remaining = state["total"] - state["done"]
                    state["etaSeconds"] = (
                        round(remaining / state["speed"]) if state["speed"] else None
                    )
                    progress(state)
            state["currentSecurity"] = None
            return state

        return self._submit("history_backfill", payload, operation)


def _market_counts(securities: list[dict[str, str]]) -> dict[str, int]:
    return {
        market: sum(item["exchange"] == market for item in securities)
        for market in SUPPORTED_EXCHANGES
    }


def dataframe_records(frame: pd.DataFrame) -> list[dict]:
    return frame.astype(object).where(pd.notna(frame), None).to_dict("records")


def create_app(
    settings: Settings | None = None,
    source: AkShareSource | None = None,
    *,
    access_verifier: CloudflareAccessVerifier | None = None,
) -> FastAPI:
    settings = settings or Settings()
    source_injected = source is not None
    source = source or AkShareSource(retries=settings.request_retries)
    jobs_db_path = settings.jobs_db_path or settings.data_path / "jobs.duckdb"
    jobs_db_path.parent.mkdir(parents=True, exist_ok=True)
    job_store = JobStore(jobs_db_path, memory_limit=settings.duckdb_memory_limit,
                         threads=settings.duckdb_threads)
    coordinator = HeavyTaskCoordinator(job_store)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        try:
            coordinator.shutdown()
        except CoordinatorShutdownError:
            pass
        finally:
            job_store.close()

    app = FastAPI(title="K-line Research API", version="0.2.0", lifespan=lifespan)
    app.state.jobs_db_path = jobs_db_path
    app.state.job_store = job_store
    app.state.heavy_coordinator = coordinator
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if settings.cloudflare_access_required:
        verifier = access_verifier or CloudflareAccessVerifier(settings)

        @app.middleware("http")
        async def require_cloudflare_access(request, call_next):
            if request.url.path.startswith("/api/"):
                token = request.headers.get("Cf-Access-Jwt-Assertion", "")
                if not token:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": {
                            "code": "ACCESS_DENIED",
                            "message": "Cloudflare Access token is required",
                        }},
                    )
                try:
                    verifier.verify(token)
                except AccessDenied as exc:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": {
                            "code": "ACCESS_DENIED", "message": str(exc),
                        }},
                    )
            return await call_next(request)
    pipeline = DatasetPipeline(settings.data_path, memory_limit=settings.duckdb_memory_limit,
                               threads=settings.duckdb_threads)
    pipeline.initialize_catalog()
    if source_injected:
        adapter = _InjectedProviderAdapter(source)
        download_source = HybridDownloadSource(adapter, adapter)
    else:
        download_source = HybridDownloadSource(
            TencentHttpSource(retries=settings.request_retries), source
        )
    app.state.download_source = download_source
    submission_lock = threading.Lock()
    tasks = TaskStore(coordinator, job_store, submission_lock, settings.download_workers)
    label_tasks = LabelTaskStore(coordinator, job_store, submission_lock)
    feature_tasks = FeatureTaskStore(coordinator, job_store, submission_lock)
    score_tasks = ScoreTaskStore(coordinator, job_store, submission_lock)
    history_backfill_service = HistoryBackfillService(
        pipeline,
        download_source,
        min_days=settings.history_backfill_min_days,
        freshness_days=settings.history_backfill_freshness_days,
    )
    history_backfill_tasks = HistoryBackfillTaskStore(
        coordinator, job_store, submission_lock
    )
    history_backfill_scan_lock = threading.Lock()
    history_backfill_candidate_count: int | None = None
    approximate_quality_lock = threading.Lock()
    approximate_quality_cache: dict[str, object] = {"expires": 0.0, "value": None}
    security_cache: list[dict[str, str]] | None = None

    def securities_list(refresh: bool = False) -> list[dict[str, str]]:
        nonlocal security_cache
        if security_cache is None and not refresh:
            security_cache = pipeline.load_security_master() or None
        if security_cache is None or refresh:
            security_cache = source.list_securities()
            pipeline.save_security_master(security_cache)
        security_cache = [
            item for item in security_cache
            if item.get("exchange") in SUPPORTED_EXCHANGES
        ]
        return security_cache

    def require_supported_market(exchange: str) -> str:
        normalized = exchange.lower().strip()
        if normalized not in SUPPORTED_EXCHANGES:
            raise HTTPException(
                422,
                detail={
                    "code": "MARKET_NOT_SUPPORTED",
                    "message": f"market not supported: {normalized or '<empty>'}",
                },
            )
        return normalized

    @app.get("/api/system/health")
    def health():
        return {
            "status": "ok",
            "dataSource": "AkShare",
            "cachePath": str(settings.data_path),
            "versions": VERSIONS,
            "recoverableTasks": sum(
                job.resumable for job in job_store.list(status=JobStatus.INTERRUPTED)
            ),
        }

    label_status_cache: dict[str, object] = {"expires": 0.0, "value": None}
    label_status_lock = threading.Lock()
    label_status_path = settings.data_path / ".label-status.json"

    @app.get("/api/labels/status")
    def label_dataset_status():
        with label_status_lock:
            if time.monotonic() < float(label_status_cache["expires"]):
                return label_status_cache["value"]
        current_version = VERSIONS["labelDefinitionVersion"]
        if label_status_path.exists():
            try:
                persisted = json.loads(label_status_path.read_text(encoding="utf-8"))
                if persisted.get("currentVersion") == current_version:
                    with label_status_lock:
                        label_status_cache.update(
                            value=persisted, expires=time.monotonic() + 60
                        )
                    return persisted
            except (OSError, ValueError, AttributeError):
                pass
        paths = sorted(settings.data_path.glob("data-foundation-v1/labels/*/*/*.parquet"))
        version_counts: dict[str, int] = {}
        rows = 0
        compatible_files = 0
        delayed_exit_files = 0
        for path in paths:
            parquet = pq.ParquetFile(path)
            file_rows = parquet.metadata.num_rows
            rows += file_rows
            columns = set(parquet.schema.names)
            if "label_definition_version" in columns and file_rows:
                column_index = parquet.schema.names.index("label_definition_version")
                file_versions: dict[str, int] = {}
                metadata_complete = True
                for index in range(parquet.metadata.num_row_groups):
                    row_group = parquet.metadata.row_group(index)
                    statistics = row_group.column(column_index).statistics
                    if not statistics or not statistics.has_min_max or statistics.min != statistics.max:
                        metadata_complete = False
                        break
                    version = str(statistics.min)
                    file_versions[version] = file_versions.get(version, 0) + row_group.num_rows
                if not metadata_complete:
                    versions = parquet.read(columns=["label_definition_version"]).to_pandas()[
                        "label_definition_version"
                    ].fillna("unknown").astype(str)
                    file_versions = {str(key): int(value) for key, value in versions.value_counts().items()}
                for version, count in file_versions.items():
                    version_counts[version] = version_counts.get(version, 0) + count
                if set(file_versions) == {current_version}:
                    compatible_files += 1
            else:
                version_counts["legacy-or-unknown"] = (
                    version_counts.get("legacy-or-unknown", 0) + file_rows
                )
            if "p20_delayed_executable_return" in columns:
                delayed_exit_files += 1
        result = {
            "currentVersion": current_version,
            "files": len(paths),
            "rows": rows,
            "versionCounts": version_counts,
            "compatibleFiles": compatible_files,
            "staleFiles": len(paths) - compatible_files,
            "delayedExitReady": bool(paths) and delayed_exit_files == len(paths),
        }
        with label_status_lock:
            label_status_cache.update(value=result, expires=time.monotonic() + 60)
            temporary = label_status_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            temporary.replace(label_status_path)
        return result

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok", "activeTasks": len(coordinator.active())}

    @app.get("/api/tasks/recent")
    def recent_tasks(limit: int = 10):
        bounded = max(1, min(50, limit))
        return [_task_response(job) for job in reversed(job_store.list())][:bounded]

    @app.get("/api/tasks/{task_id}")
    def generic_task_status(task_id: str):
        job = job_store.get(task_id)
        if job is None:
            raise HTTPException(
                404, detail={"code": "TASK_NOT_FOUND", "message": "任务不存在"}
            )
        return _task_response(job)

    @app.post("/api/datasets/validate")
    def validate_dataset():
        try:
            securities = securities_list(refresh=True)
        except Exception as exc:
            raise HTTPException(
                503,
                detail={"code": "AKSHARE_UNAVAILABLE", "message": f"AkShare 数据源不可用：{exc}"},
            ) from exc
        return {
            "valid": bool(securities),
            "source": "AkShare",
            "markets": _market_counts(securities),
            "securityCount": len(securities),
        }

    def submit_history_backfill():
        nonlocal history_backfill_candidate_count
        history_backfill_tasks.active()
        candidates = history_backfill_service.scan()
        with history_backfill_scan_lock:
            history_backfill_candidate_count = len(candidates)
        task_id = history_backfill_tasks.submit(
            history_backfill_service,
            candidates,
            date.today(),
            timeout_seconds=settings.security_fetch_timeout_seconds,
        )
        return {
            "taskId": task_id,
            "total": len(candidates),
            "threshold": settings.history_backfill_min_days,
        }

    @app.post("/api/datasets/import", status_code=202)
    def start_import(request: ImportRequest):
        if request.scope == "history_backfill":
            return submit_history_backfill()
        active = tasks.active()
        if active:
            raise HTTPException(
                409,
                detail={
                    "code": "IMPORT_ALREADY_RUNNING",
                    "message": f'已有导入任务运行中：{active["id"]}',
                    "taskId": active["id"],
                },
            )
        if request.scope == "representative":
            securities = [
                {"exchange": "sh", "code": "600000", "name": "浦发银行"},
                {"exchange": "sz", "code": "000001", "name": "平安银行"},
            ]
        elif request.scope == "all":
            try:
                securities = securities_list()
            except Exception as exc:
                raise HTTPException(
                    503, detail={"code": "AKSHARE_UNAVAILABLE", "message": str(exc)}
                ) from exc
        else:
            raise HTTPException(
                422,
                detail={"code": "INVALID_IMPORT_SCOPE", "message": "scope must be representative or all"},
            )
        requested_total = len(securities)
        if not request.refresh:
            cached_keys = {
                f'{item["exchange"]}{item["code"]}'
                for item in pipeline.cached_securities()
            }
            securities = [
                item
                for item in securities
                if f'{item["exchange"]}{item["code"]}' not in cached_keys
            ]
        skipped = requested_total - len(securities)
        start = date.fromisoformat(f"{settings.history_start_date[:4]}-{settings.history_start_date[4:6]}-{settings.history_start_date[6:]}")
        task_id = tasks.submit(
            pipeline, download_source, securities, start, date.today(),
            settings.security_fetch_timeout_seconds,
        )
        return {
            "taskId": task_id, "total": len(securities),
            "requested": requested_total, "skipped": skipped,
        }

    @app.get("/api/datasets/tasks/{task_id}")
    def task_status(task_id: str):
        if task_id not in tasks.items:
            raise HTTPException(404, detail={"code": "TASK_NOT_FOUND", "message": "任务不存在"})
        return tasks.items[task_id]

    @app.get("/api/datasets/quality")
    def quality():
        nonlocal history_backfill_candidate_count
        cached = pipeline.cached_market_counts()
        events = pipeline.quality_events(limit=100_000)
        with history_backfill_scan_lock:
            if history_backfill_candidate_count is None:
                history_backfill_candidate_count = len(history_backfill_service.scan())
        with approximate_quality_lock:
            approximate_quality = approximate_quality_cache["value"]
            if time.monotonic() >= float(approximate_quality_cache["expires"]):
                latest: dict[str, dict] = {}
                for path in sorted(
                    settings.data_path.glob(
                        "data-foundation-v1/features/*/*/*/*.manifest.json"
                    ),
                    key=lambda item: item.stat().st_mtime,
                ):
                    try:
                        manifest = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        continue
                    latest[str(manifest.get("security", path.stem))] = manifest
                feature_rows = 0
                approximate_rows = 0.0
                for manifest in latest.values():
                    rows = int(manifest.get("rows", 0))
                    ratio = manifest.get("approximateRuleRatio")
                    feature_rows += rows
                    if ratio is not None:
                        approximate_rows += rows * float(ratio)
                approximate_quality = {
                    "featureRows": feature_rows,
                    "approximateRuleRows": round(approximate_rows),
                    "approximateRuleRatio": (
                        approximate_rows / feature_rows if feature_rows else None
                    ),
                }
                approximate_quality_cache.update(
                    value=approximate_quality, expires=time.monotonic() + 60
                )
        return {
            "source": "AkShare",
            "cachedSecurities": cached,
            "totalCached": sum(cached.values()),
            "shortHistoryCached": history_backfill_candidate_count,
            "listingHistoryShort": sum(
                event["event_type"] == "listing-history-short" for event in events
            ),
            "historyBackfillFailed": sum(
                event["event_type"] == "history-backfill-failed" for event in events
            ),
            **approximate_quality,
            "qualityEvents": events[:100],
        }

    @app.post("/api/history-backfill", status_code=202)
    @app.post("/api/datasets/backfill-history", status_code=202)
    def start_history_backfill():
        return submit_history_backfill()

    @app.get("/api/datasets/backfill-history/{task_id}")
    def history_backfill_status(task_id: str):
        if task_id not in history_backfill_tasks.items:
            raise HTTPException(
                404,
                detail={"code": "TASK_NOT_FOUND", "message": "任务不存在"},
            )
        return history_backfill_tasks.items[task_id]

    @app.post("/api/labels/build", status_code=202)
    def build_labels(request: ImportRequest):
        label_tasks.active()
        cached = [
            item for item in pipeline.cached_securities()
            if item["exchange"] in SUPPORTED_EXCHANGES
        ]
        if request.scope == "representative":
            cached = cached[:3]
        elif request.scope != "all":
            raise HTTPException(
                422, detail={"code": "INVALID_LABEL_SCOPE", "message": "scope must be representative or all"}
            )
        try:
            names = {
                f'{item["exchange"]}{item["code"]}': item["name"]
                for item in securities_list()
            }
        except Exception:
            names = {}
        task_id = label_tasks.submit(
            pipeline, download_source, cached, names, settings.data_path
        )
        return {"taskId": task_id, "total": len(cached)}

    @app.get("/api/labels/tasks/{task_id}")
    def label_task_status(task_id: str):
        if task_id not in label_tasks.items:
            raise HTTPException(
                404, detail={"code": "TASK_NOT_FOUND", "message": "标签任务不存在"}
            )
        return label_tasks.items[task_id]

    @app.post("/api/features/build", status_code=202)
    def build_features(request: ImportRequest):
        active = feature_tasks.active()
        if active:
            raise HTTPException(
                409,
                detail={
                    "code": "FEATURE_BUILD_ALREADY_RUNNING",
                    "message": f'已有特征任务运行中：{active["id"]}',
                    "taskId": active["id"],
                },
            )
        cached = [
            item for item in pipeline.cached_securities()
            if item["exchange"] in SUPPORTED_EXCHANGES
        ]
        if request.scope == "representative":
            cached = cached[:3]
        elif request.scope != "all":
            raise HTTPException(
                422,
                detail={"code": "INVALID_FEATURE_SCOPE", "message": "scope must be representative or all"},
            )
        try:
            names = {
                f'{item["exchange"]}{item["code"]}': item["name"]
                for item in securities_list()
            }
        except Exception:
            names = {}
        cached = [
            {
                **item,
                "st_status": status_from_name(
                    names.get(f'{item["exchange"]}{item["code"]}', "")
                ).is_st,
            }
            for item in cached
        ]
        task_id = feature_tasks.submit(cached, settings.data_path)
        return {"taskId": task_id, "total": len(cached)}

    @app.get("/api/features/tasks/{task_id}")
    def feature_task_status(task_id: str):
        if task_id not in feature_tasks.items:
            raise HTTPException(
                404, detail={"code": "TASK_NOT_FOUND", "message": "特征任务不存在"}
            )
        return feature_tasks.items[task_id]

    @app.post("/api/scores/build", status_code=202)
    def build_scores(request: ImportRequest):
        active = score_tasks.active()
        if active:
            raise HTTPException(
                409,
                detail={
                    "code": "SCORE_BUILD_ALREADY_RUNNING",
                    "message": f'A score job is already running: {active["id"]}',
                    "taskId": active["id"],
                },
            )
        cached = [
            item for item in pipeline.cached_securities()
            if item["exchange"] in SUPPORTED_EXCHANGES
        ]
        if request.scope == "representative":
            cached = cached[:3]
        elif request.scope != "all":
            raise HTTPException(
                422,
                detail={
                    "code": "INVALID_SCORE_SCOPE",
                    "message": "scope must be representative or all",
                },
            )
        label_status_path.unlink(missing_ok=True)
        with label_status_lock:
            label_status_cache.update(value=None, expires=0.0)
        try:
            names = {
                f'{item["exchange"]}{item["code"]}': item["name"]
                for item in securities_list()
            }
        except Exception:
            names = {}
        cached = [
            {
                **item,
                "st_status": status_from_name(
                    names.get(f'{item["exchange"]}{item["code"]}', "")
                ).is_st,
            }
            for item in cached
        ]
        task_id = score_tasks.submit(cached, settings.data_path)
        return {"taskId": task_id, "total": len(cached)}

    @app.get("/api/scores/tasks/{task_id}")
    def score_task_status(task_id: str):
        if task_id not in score_tasks.items:
            raise HTTPException(
                404, detail={"code": "TASK_NOT_FOUND", "message": "score task not found"}
            )
        return score_tasks.items[task_id]

    def read_dataset_glob(
        pattern: str,
        unique_keys: list[str] | None = None,
        columns: list[str] | None = None,
    ) -> pd.DataFrame:
        frames = []
        paths = sorted(settings.data_path.glob(pattern), key=lambda path: path.stat().st_mtime)
        for path in paths:
            if path.name.endswith(".manifest.json"):
                continue
            selected = columns
            if columns is not None:
                parquet = pq.ParquetFile(path)
                available = set(parquet.schema.names)
                selected = [column for column in columns if column in available]
                frames.append(parquet.read(columns=selected).to_pandas())
            else:
                frames.append(pd.read_parquet(path))
        if not frames:
            return pd.DataFrame()
        result = pd.concat(frames, ignore_index=True)
        if unique_keys and set(unique_keys).issubset(result.columns):
            result = result.drop_duplicates(unique_keys, keep="last")
        return result

    @app.post("/api/validation/single-factor")
    def single_factor_validation(request: SingleFactorValidationRequest):
        scores = read_dataset_glob("data-foundation-v1/scores/*/*/*/*.parquet", ["exchange", "code", "date"], ["exchange", "code", "date", request.factor_column, "usable"])
        labels = read_dataset_glob("data-foundation-v1/labels/*/*/*.parquet", ["exchange", "code", "signal_date"], ["exchange", "code", "signal_date", request.label_column, "label_maturity_date", "path_success_p20", "max_drawdown_p20"])
        return validate_single_factor(
            scores,
            labels,
            factor_column=request.factor_column,
            label_column=request.label_column,
            buckets=request.buckets,
            as_of_date=request.as_of_date,
        )

    @app.post("/api/validation/calibration")
    def score_calibration(request: CalibrationRequest):
        scores = read_dataset_glob("data-foundation-v1/scores/*/*/*/*.parquet", ["exchange", "code", "date"], ["exchange", "code", "date", "score", "usable"])
        labels = read_dataset_glob("data-foundation-v1/labels/*/*/*.parquet", ["exchange", "code", "signal_date"], ["exchange", "code", "signal_date", request.label_column, "label_maturity_date"])
        return calibrate_score(scores, labels, label_column=request.label_column,
                               buckets=request.buckets, as_of_date=request.as_of_date)

    @app.post("/api/scan/p3")
    def scan_p3(request: ScanRequest):
        scores = read_dataset_glob("data-foundation-v1/scores/*/*/*/*.parquet", ["exchange", "code", "date"], ["exchange", "code", "date", "score", "grade", "usable"])
        if scores.empty:
            return {"version": SCORE_DEFINITION_VERSION, "asOfDate": request.as_of_date,
                    "minScore": request.min_score, "scannedCount": 0, "truncated": False, "rows": []}
        scores["date"] = pd.to_datetime(scores["date"]).dt.date
        if request.as_of_date is not None:
            scores = scores.loc[scores["date"] <= request.as_of_date]
        if request.exchange in {"sh", "sz"}:
            scores = scores.loc[scores["exchange"] == request.exchange]
        if "usable" in scores:
            scores = scores.loc[scores["usable"].fillna(False).astype(bool)]
        scores["score"] = pd.to_numeric(scores["score"], errors="coerce")
        scores = scores.dropna(subset=["score"])
        scores = scores.sort_values(["exchange", "code", "date"]).drop_duplicates(
            ["exchange", "code"], keep="last"
        )
        scores = scores.loc[scores["score"] >= request.min_score].sort_values(
            ["score", "date"], ascending=[False, False]
        )
        candidate_count = int(len(scores))
        scores = scores.head(request.limit)
        rows = [{"exchange": row.exchange, "code": row.code, "date": row.date,
                 "score": float(row.score), "grade": getattr(row, "grade", None)}
                for row in scores.itertuples(index=False)]
        return {"version": SCORE_DEFINITION_VERSION, "asOfDate": request.as_of_date,
                "exchange": request.exchange, "minScore": request.min_score,
                "scannedCount": candidate_count, "truncated": candidate_count > request.limit,
                "rows": rows}

    @app.post("/api/model/p7/baseline")
    def p7_baseline(request: BaselineModelRequest):
        scores = read_dataset_glob("data-foundation-v1/scores/*/*/*/*.parquet", ["exchange", "code", "date"], ["exchange", "code", "date", "score", "usable"])
        labels = read_dataset_glob("data-foundation-v1/labels/*/*/*.parquet", ["exchange", "code", "signal_date"], ["exchange", "code", "signal_date", request.label_column, "label_maturity_date"])
        return train_score_baseline(scores, labels, label_column=request.label_column,
                                    train_until=request.train_until)

    @app.get("/api/model/p7/features")
    def p7_feature_catalog():
        expected = ["bullish_alignment", "return_20", "volume_ratio_5", "volatility_20"]
        latest_paths: dict[tuple[str, str], Path] = {}
        for path in sorted(
            settings.data_path.glob("data-foundation-v1/features/*/*/*/*.parquet"),
            key=lambda item: item.stat().st_mtime,
        ):
            latest_paths[(path.parent.name, path.stem)] = path
        if not latest_paths:
            return {"version": "daily-features-v1", "featureColumns": [], "missingColumns": expected, "securityCount": 0, "rowCount": 0, "ready": False}
        ignored = {"exchange", "code", "date"}
        columns: set[str] = set()
        row_count = 0
        for path in latest_paths.values():
            parquet = pq.ParquetFile(path)
            columns.update(parquet.schema.names)
            row_count += parquet.metadata.num_rows
        columns = set(columns) - ignored
        missing = sorted(set(expected) - set(columns))
        security_count = len(latest_paths)
        return {"version": "daily-features-v1", "featureColumns": sorted(columns), "missingColumns": missing,
                "securityCount": security_count, "rowCount": row_count,
                "ready": bool(security_count and not missing)}

    @app.post("/api/model/p7/multifeature")
    def p7_multifeature(request: BaselineModelRequest):
        scores = read_dataset_glob("data-foundation-v1/scores/*/*/*/*.parquet", ["exchange", "code", "date"], ["exchange", "code", "date", "score", "usable"])
        labels = read_dataset_glob("data-foundation-v1/labels/*/*/*.parquet", ["exchange", "code", "signal_date"], ["exchange", "code", "signal_date", request.label_column, "label_maturity_date"])
        features = read_dataset_glob("data-foundation-v1/features/*/*/*/*.parquet", ["exchange", "code", "date"], ["exchange", "code", "date", "bullish_alignment", "return_20", "volume_ratio_5", "volatility_20"])
        return train_multifeature_baseline(scores, labels, features,
                                            label_column=request.label_column,
                                            train_until=request.train_until)

    @app.post("/api/model/p7/walk-forward")
    def p7_walk_forward(request: WalkForwardRequest):
        scores = read_dataset_glob("data-foundation-v1/scores/*/*/*/*.parquet", ["exchange", "code", "date"], ["exchange", "code", "date", "score", "usable"])
        labels = read_dataset_glob("data-foundation-v1/labels/*/*/*.parquet", ["exchange", "code", "signal_date"], ["exchange", "code", "signal_date", request.label_column, "label_maturity_date"])
        return walk_forward_score_baseline(scores, labels,
                                           label_column=request.label_column,
                                           folds=request.folds)

    @app.post("/api/validation/portfolio")
    def portfolio_validation(request: PortfolioValidationRequest):
        scores = read_dataset_glob("data-foundation-v1/scores/*/*/*/*.parquet", ["exchange", "code", "date"], ["exchange", "code", "date", "score", "usable"])
        labels = read_dataset_glob("data-foundation-v1/labels/*/*/*.parquet", ["exchange", "code", "signal_date"], ["exchange", "code", "signal_date", request.label_column, "label_maturity_date"])
        return validate_top_score_portfolio(scores, labels, label_column=request.label_column,
                                            top_fraction=request.top_fraction, as_of_date=request.as_of_date,
                                            non_overlapping=request.non_overlapping,
                                            transaction_cost_bps=request.transaction_cost_bps,
                                            slippage_bps=request.slippage_bps)

    @app.get("/api/securities")
    def securities(query: str = ""):
        try:
            rows = securities_list()
        except Exception as exc:
            raise HTTPException(503, detail={"code": "AKSHARE_UNAVAILABLE", "message": str(exc)}) from exc
        needle = query.strip().lower()
        if needle:
            rows = [row for row in rows if needle in row["code"].lower() or needle in row["name"].lower()]
        return rows[:50]

    def load_bars(exchange: str, code: str) -> pd.DataFrame:
        exchange = require_supported_market(exchange)
        normalized = pipeline.latest_derived_path(exchange, code)
        if normalized is None or not normalized.exists():
            if threading.current_thread().name.startswith("kline-heavy-job"):
                raise RuntimeError("lazy cache fill cannot run inside the heavy-job worker")
            start = date.fromisoformat(
                f"{settings.history_start_date[:4]}-{settings.history_start_date[4:6]}-"
                f"{settings.history_start_date[6:]}"
            )

            def operation(payload, progress):
                def fetch():
                    return download_source.fetch_bundle(
                        payload["exchange"], payload["code"], start, date.today()
                    )

                executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="market-fetch")
                future = executor.submit(fetch)
                try:
                    completed, _ = wait([future], timeout=settings.security_fetch_timeout_seconds)
                    if not completed:
                        future.cancel()
                        raise TimeoutError(
                            "fetch timed out after "
                            f"{settings.security_fetch_timeout_seconds}s"
                        )
                    raw, factors = future.result()
                finally:
                    executor.shutdown(wait=False, cancel_futures=True)
                report = pipeline.import_security(
                    payload["exchange"], payload["code"], raw, factors
                )
                return {"snapshotVersion": report.snapshot_version}

            with submission_lock:
                active = coordinator.active()
                if active:
                    task_id = active[0].id
                    raise HTTPException(409, detail={
                        "code": "HEAVY_JOB_ALREADY_RUNNING",
                        "message": f"A heavy job is already running: {task_id}",
                        "taskId": task_id,
                    })
                submitted = coordinator.submit(
                    "cache-security", {"exchange": exchange, "code": code}, operation
                )
            try:
                submitted.future.result(timeout=settings.security_fetch_timeout_seconds + 1)
            except Exception as exc:
                raise HTTPException(
                    503,
                    detail={
                        "code": "AKSHARE_FETCH_FAILED",
                        "message": f"行情获取失败：{exc}",
                    },
                ) from exc
            normalized = pipeline.latest_derived_path(exchange, code)
        if normalized is None:
            raise HTTPException(
                500, detail={"code": "CACHE_WRITE_FAILED", "message": "快照写入失败"}
            )
        return pd.read_parquet(normalized)

    benchmark_cache: dict[str, pd.DataFrame] = {}
    benchmark_cache_lock = threading.Lock()

    def benchmark_bars(exchange: str, required_end: date) -> list[dict]:
        exchange = require_supported_market(exchange)
        required_end = pd.Timestamp(required_end).date()
        cache_path = (
            settings.data_path / "data-foundation-v1" / "benchmarks" / f"{exchange}.parquet"
        )
        with benchmark_cache_lock:
            cached = benchmark_cache.get(exchange)
            if cached is None and cache_path.exists():
                cached = pd.read_parquet(cache_path)
                benchmark_cache[exchange] = cached
            if cached is not None and not cached.empty:
                cached_end = pd.to_datetime(cached["date"]).dt.date.max()
                if cached_end >= required_end:
                    return cached.to_dict("records")
        start = date.fromisoformat(f"{settings.history_start_date[:4]}-{settings.history_start_date[4:6]}-{settings.history_start_date[6:]}")
        try:
            frame = download_source.index_history(exchange, start, date.today())
        except Exception:
            return cached.to_dict("records") if cached is not None else []
        for column in ("open", "high", "low", "close"):
            frame[f"{column}_qfq"] = frame[column]
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(f".{threading.get_ident()}.tmp.parquet")
        frame.to_parquet(temporary, index=False)
        temporary.replace(cache_path)
        with benchmark_cache_lock:
            benchmark_cache[exchange] = frame
        return frame.to_dict("records")

    @app.get("/api/securities/{exchange}/{code}/bars")
    def bars(exchange: str, code: str):
        frame = load_bars(exchange, code)
        return dataframe_records(frame)

    @app.post("/api/p1/audit")
    def audit(request: AuditRequest):
        frame = load_bars(request.exchange, request.code)
        records = frame.to_dict("records")
        indices = {row["date"]: index for index, row in enumerate(records)}
        if request.signal_date not in indices:
            raise HTTPException(
                422,
                detail={"code": "SIGNAL_DATE_NOT_FOUND", "message": "信号日不是有效交易日"},
            )
        signal_index = indices[request.signal_date]
        try:
            name = next(
                (
                    item["name"]
                    for item in securities_list()
                    if item["exchange"] == request.exchange
                    and item["code"] == request.code
                ),
                "",
            )
        except Exception:
            name = ""
        security_status = status_from_name(name)
        listing_date = records[0]["date"]
        no_limit_indices = {
            index
            for index, bar in enumerate(records[:5])
            if is_no_limit_session(
                request.exchange,
                request.code,
                listing_date,
                index,
                bar["date"],
            )
        }
        eligibility = sample_eligibility(records, signal_index, rights_status="ok")
        entry = resolve_executable_entry(
            records,
            signal_index,
            code=request.code,
            exchange=request.exchange,
            st_status=security_status.is_st,
            no_limit_indices=no_limit_indices,
        )
        output = {
            "eligibility": asdict(eligibility), "entry": asdict(entry), "labels": {},
            "exits": {},
            "path": None, "drawdown": None, "dataSource": "AkShare",
            "dataSnapshotVersion": pipeline.latest_snapshot_version(
                request.exchange, request.code
            ),
            "factorVersion": records[0].get("factor_version"),
            "securityStatus": asdict(security_status),
        }
        if entry.executable and entry.entry_index is not None:
            benchmark = benchmark_bars(request.exchange, records[-1]["date"])
            labels = compute_forward_labels(
                records, benchmark, signal_index, entry.entry_index
            )
            entry_price = float(records[entry.entry_index].get(
                "open_total_return", records[entry.entry_index]["open_qfq"]
            ))
            exits = {
                horizon: resolve_executable_exit(
                    records,
                    entry.entry_index + horizon,
                    code=request.code,
                    exchange=request.exchange,
                    st_status=security_status.is_st,
                )
                for horizon in labels
            }
            output["exits"] = {
                str(horizon): asdict(exit_result)
                for horizon, exit_result in exits.items()
            }
            output["labels"] = {}
            for horizon, label in labels.items():
                label_record = asdict(label)
                planned_index = entry.entry_index + horizon
                label_record["planned_exit_date"] = (
                    records[planned_index]["date"]
                    if planned_index < len(records)
                    else None
                )
                exit_result = exits[horizon]
                label_record["delayed_executable_return"] = (
                    exit_result.exit_price / entry_price - 1
                    if exit_result.executable and exit_result.exit_price is not None
                    else None
                )
                output["labels"][str(horizon)] = label_record
            path_start = records[entry.entry_index].get(
                "open_total_return", records[entry.entry_index]["open_qfq"]
            )
            output["path"] = asdict(
                compute_path_label(records, entry.entry_index, path_start)
            )
            output["drawdown"] = asdict(
                compute_drawdown_label(records, entry.entry_index, path_start, 20, 0.08)
            )
            output["maturityDate"] = exits[20].exit_date or compute_label_maturity_date(
                [row["date"] for row in records], entry.entry_index, 20
            )
        return output

    @app.post("/api/p2/audit")
    def feature_audit(request: AuditRequest):
        frame = load_bars(request.exchange, request.code)
        try:
            name = next(
                (
                    item["name"]
                    for item in securities_list()
                    if item["exchange"] == request.exchange and item["code"] == request.code
                ),
                "",
            )
        except Exception:
            name = ""
        features = compute_daily_features(
            frame,
            exchange=request.exchange,
            code=request.code,
            st_status=status_from_name(name).is_st,
        )
        selected = features.loc[features["date"] == request.signal_date]
        if selected.empty:
            raise HTTPException(
                422,
                detail={"code": "SIGNAL_DATE_NOT_FOUND", "message": "审计日期不是有效交易日"},
            )
        row = dataframe_records(selected)[0]
        groups = {
            "trend": {
                key: row.get(key)
                for key in (
                    "ma5", "ma10", "ma20", "ma60", "ma5_slope", "ma10_slope",
                    "ma20_slope", "ma60_slope", "close_to_ma5", "close_to_ma10",
                    "close_to_ma20", "close_to_ma60", "bullish_alignment",
                    "bearish_alignment",
                )
            },
            "position": {
                key: row.get(key)
                for window in (20, 60, 120, 250)
                for key in (f"range_position_{window}", f"drawdown_from_high_{window}")
            },
            "momentum": {
                f"return_{window}": row.get(f"return_{window}")
                for window in (5, 10, 20, 60, 120)
            },
            "volumePrice": {
                key: row.get(key)
                for key in (
                    "volume_ratio_5", "volume_percentile_20", "amount",
                    "volatility_20", "amplitude",
                )
            },
            "tradingBehavior": {
                key: row.get(key)
                for key in (
                    "is_limit_up", "limit_up_count_20", "locked_limit_up_streak",
                    "gap_open", "suspension_gap_days", "is_approx", "rule_reason",
                )
            },
        }
        return {
            "exchange": request.exchange,
            "code": request.code,
            "date": request.signal_date,
            "availableHistory": row["available_history"],
            "groups": groups,
            "reasons": row["reasons"],
            "priceBasis": row["price_basis"],
            "versions": {
                "snapshotVersion": pipeline.latest_snapshot_version(
                    request.exchange, request.code
                ),
                "factorVersion": row.get("factor_version"),
                "limitRuleVersion": VERSIONS["limitRuleVersion"],
                "featureDefinitionVersion": FEATURE_DEFINITION_VERSION,
            },
        }

    @app.post("/api/p3/audit")
    def score_audit(request: AuditRequest):
        frame = load_bars(request.exchange, request.code)
        try:
            name = next(
                (
                    item["name"]
                    for item in securities_list()
                    if item["exchange"] == request.exchange and item["code"] == request.code
                ),
                "",
            )
        except Exception:
            name = ""
        features = compute_daily_features(
            frame,
            exchange=request.exchange,
            code=request.code,
            st_status=status_from_name(name).is_st,
        )
        selected = features.loc[features["date"] == request.signal_date]
        if selected.empty:
            raise HTTPException(
                422,
                detail={
                    "code": "SIGNAL_DATE_NOT_FOUND",
                    "message": "audit date is not a valid trading day",
                },
            )
        row = dataframe_records(selected)[0]
        return {
            "exchange": request.exchange,
            "code": request.code,
            "date": request.signal_date,
            "availableHistory": row["available_history"],
            "featureDefinitionVersion": FEATURE_DEFINITION_VERSION,
            "priceBasis": row["price_basis"],
            "score": compute_rule_score(row),
            "versions": {
                "snapshotVersion": pipeline.latest_snapshot_version(
                    request.exchange, request.code
                ),
                "factorVersion": row.get("factor_version"),
                "limitRuleVersion": VERSIONS["limitRuleVersion"],
                "featureDefinitionVersion": FEATURE_DEFINITION_VERSION,
                "scoreDefinitionVersion": SCORE_DEFINITION_VERSION,
            },
        }

    if settings.frontend_dist_path and settings.frontend_dist_path.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=settings.frontend_dist_path, html=True),
            name="frontend",
        )
    return app


app = create_app()
