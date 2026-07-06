from __future__ import annotations

from concurrent.futures import as_completed, ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date
import threading
import time

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import Settings, VERSIONS
from .data.akshare_source import AkShareSource
from .data.download_source import HybridDownloadSource
from .data.eastmoney_source import EastMoneyHttpSource
from .data.pipeline import DatasetPipeline
from .features import FEATURE_DEFINITION_VERSION, compute_daily_features
from .features.batch import BatchFeatureBuilder, FeatureDatasetStore
from .jobs import CoordinatorShutdownError, HeavyTaskCoordinator, Job, JobStatus, JobStore
from .p1 import (
    compute_drawdown_label,
    compute_forward_labels,
    compute_label_maturity_date,
    compute_path_label,
    resolve_executable_entry,
    sample_eligibility,
)
from .p1.batch import BatchLabelBuilder, LabelDatasetStore
from .p1.market_rules import status_from_name


class ImportRequest(BaseModel):
    scope: str = "representative"
    refresh: bool = False


class AuditRequest(BaseModel):
    exchange: str
    code: str
    signal_date: date


def _task_response(job: Job) -> dict:
    total = len(job.payload) if isinstance(job.payload, list) else 0
    defaults = {"total": total, "done": 0, "rows": 0, "errors": [],
                "currentSecurity": None}
    if job.job_type == "import":
        defaults.update({"stage": "queued", "speed": 0.0, "etaSeconds": None,
                         "directAvailable": None})
    progress = job.progress if isinstance(job.progress, dict) else {}
    result = job.result if isinstance(job.result, dict) else {}
    item = {"id": job.id, **defaults, **progress, **result}
    status = job.status.value
    if job.status is JobStatus.COMPLETED and item["errors"]:
        status = "completed_with_errors"
    item["status"] = status
    if job.error and not item["errors"]:
        item["errors"] = [{"message": job.error}]
    return item


class _DurableItems:
    def __init__(self, store: JobStore):
        self.store = store

    def __contains__(self, task_id: str) -> bool:
        return self.store.get(task_id) is not None

    def __getitem__(self, task_id: str) -> dict:
        job = self.store.get(task_id)
        if job is None:
            raise KeyError(task_id)
        return _task_response(job)


class _TaskFacade:
    def __init__(self, coordinator: HeavyTaskCoordinator, store: JobStore, lock: threading.Lock):
        self.coordinator = coordinator
        self.items = _DurableItems(store)
        self.lock = lock

    def active(self) -> dict | None:
        # Submission performs the atomic process-global conflict check.
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
            return self.coordinator.submit(job_type, payload, operation).job_id


class TaskStore(_TaskFacade):
    def __init__(self, coordinator, store, lock, workers: int):
        super().__init__(coordinator, store, lock)
        self.workers = max(1, min(workers, 3))

    def submit(self, pipeline, source, securities, start_date, end_date, timeout_seconds) -> str:
        initial = {"total": len(securities), "done": 0, "errors": [],
                   "currentSecurity": None, "stage": "queued", "speed": 0.0,
                   "etaSeconds": None, "directAvailable": source.direct_available}

        def operation(payload, progress):
            state = dict(initial)
            state["stage"] = "parallel-download"
            progress(state)
            started = time.monotonic()

            def fetch(security):
                return source.fetch_bundle(security["exchange"], security["code"],
                                           start_date, end_date)

            with ThreadPoolExecutor(max_workers=self.workers,
                                    thread_name_prefix="market-fetch") as executor:
                futures = {executor.submit(fetch, security): security for security in payload}
                for future in as_completed(futures):
                    security = futures[future]
                    key = f'{security["exchange"]}{security["code"]}'
                    state["currentSecurity"] = key
                    state["stage"] = "writing-snapshot"
                    try:
                        raw, factors = future.result(timeout=timeout_seconds)
                        pipeline.import_security(security["exchange"], security["code"], raw, factors)
                    except Exception as exc:
                        state["errors"].append({"security": key, "message": str(exc)})
                    finally:
                        state["done"] += 1
                        elapsed = max(time.monotonic() - started, 0.001)
                        state["speed"] = round(state["done"] / elapsed, 3)
                        remaining = state["total"] - state["done"]
                        state["etaSeconds"] = round(remaining / state["speed"]) if state["speed"] else None
                        state["directAvailable"] = source.direct_available
                        progress(state)
            state["currentSecurity"] = None
            state["stage"] = "finished"
            return state

        return self._submit("import", securities, operation)


class LabelTaskStore(_TaskFacade):
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
                        symbol = "000001" if exchange == "sh" else "399001"
                        frame = source.index_history(symbol, date(1990, 1, 1), date.today())
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


def _market_counts(securities: list[dict[str, str]]) -> dict[str, int]:
    return {market: sum(item["exchange"] == market for item in securities) for market in ("sh", "sz", "bj")}


def dataframe_records(frame: pd.DataFrame) -> list[dict]:
    return frame.astype(object).where(pd.notna(frame), None).to_dict("records")


def create_app(settings: Settings | None = None, source: AkShareSource | None = None) -> FastAPI:
    settings = settings or Settings()
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
    pipeline = DatasetPipeline(settings.data_path, memory_limit=settings.duckdb_memory_limit,
                               threads=settings.duckdb_threads)
    pipeline.initialize_catalog()
    download_source = HybridDownloadSource(
        EastMoneyHttpSource(retries=1), source
    )
    submission_lock = threading.Lock()
    tasks = TaskStore(coordinator, job_store, submission_lock, settings.download_workers)
    label_tasks = LabelTaskStore(coordinator, job_store, submission_lock)
    feature_tasks = FeatureTaskStore(coordinator, job_store, submission_lock)
    security_cache: list[dict[str, str]] | None = None

    def securities_list(refresh: bool = False) -> list[dict[str, str]]:
        nonlocal security_cache
        if security_cache is None and not refresh:
            security_cache = pipeline.load_security_master() or None
        if security_cache is None or refresh:
            security_cache = source.list_securities()
            pipeline.save_security_master(security_cache)
        return security_cache

    @app.get("/api/system/health")
    def health():
        return {
            "status": "ok",
            "dataSource": "AkShare",
            "cachePath": str(settings.data_path),
            "versions": VERSIONS,
        }

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

    @app.post("/api/datasets/import", status_code=202)
    def start_import(request: ImportRequest):
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
                {"exchange": "bj", "code": "920001", "name": "纬达光电"},
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
        cached = pipeline.cached_market_counts()
        return {
            "source": "AkShare",
            "cachedSecurities": cached,
            "totalCached": sum(cached.values()),
            "approximateRuleRatio": None,
            "qualityEvents": pipeline.quality_events(),
        }

    @app.post("/api/labels/build", status_code=202)
    def build_labels(request: ImportRequest):
        cached = pipeline.cached_securities()
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
            pipeline, source, cached, names, settings.data_path
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
        cached = pipeline.cached_securities()
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
        normalized = pipeline.latest_derived_path(exchange, code)
        if normalized is None or not normalized.exists():
            start = date.fromisoformat(f"{settings.history_start_date[:4]}-{settings.history_start_date[4:6]}-{settings.history_start_date[6:]}")
            try:
                raw = source.stock_history(code, start, date.today(), "")
                factors = source.adjustment_factors(code)
                pipeline.import_security(exchange, code, raw, factors)
            except Exception as exc:
                raise HTTPException(
                    503, detail={"code": "AKSHARE_FETCH_FAILED", "message": f"行情获取失败：{exc}"}
                ) from exc
            normalized = pipeline.latest_derived_path(exchange, code)
        if normalized is None:
            raise HTTPException(500, detail={"code": "CACHE_WRITE_FAILED", "message": "快照写入失败"})
        return pd.read_parquet(normalized)

    def benchmark_bars(exchange: str) -> list[dict]:
        symbol = "000001" if exchange == "sh" else "399001"
        start = date.fromisoformat(f"{settings.history_start_date[:4]}-{settings.history_start_date[4:6]}-{settings.history_start_date[6:]}")
        try:
            frame = source.index_history(symbol, start, date.today())
        except Exception:
            return []
        for column in ("open", "high", "low", "close"):
            frame[f"{column}_qfq"] = frame[column]
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
        eligibility = sample_eligibility(records, signal_index, rights_status="ok")
        entry = resolve_executable_entry(
            records, signal_index, code=request.code, exchange=request.exchange
        )
        output = {
            "eligibility": asdict(eligibility), "entry": asdict(entry), "labels": {},
            "path": None, "drawdown": None, "dataSource": "AkShare",
            "dataSnapshotVersion": pipeline.latest_snapshot_version(
                request.exchange, request.code
            ),
            "factorVersion": records[0].get("factor_version"),
        }
        if entry.executable and entry.entry_index is not None:
            benchmark = benchmark_bars(request.exchange)
            output["labels"] = {
                str(key): asdict(value)
                for key, value in compute_forward_labels(
                    records, benchmark, signal_index, entry.entry_index
                ).items()
            }
            path_start = records[entry.entry_index].get(
                "open_total_return", records[entry.entry_index]["open_qfq"]
            )
            output["path"] = asdict(
                compute_path_label(records, entry.entry_index, path_start)
            )
            output["drawdown"] = asdict(
                compute_drawdown_label(records, entry.entry_index, path_start, 20, 0.08)
            )
            output["maturityDate"] = compute_label_maturity_date(
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

    return app


app = create_app()
