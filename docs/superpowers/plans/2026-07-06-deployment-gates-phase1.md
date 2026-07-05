# Deployment Gates Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove provider reachability from the production server and enforce a persistent single-writer heavy-job model before any production deployment assets are created.

**Architecture:** A provider probe package executes explicit EastMoney, Tencent, Sina, index, and calendar checks and emits a machine-readable gate report. A process-local `HeavyTaskCoordinator` owns one serial executor and a DuckDB-backed job store; all import, label, and feature work submits through that coordinator while bounded network fetches remain concurrent inside one job.

**Tech Stack:** Python 3.12, requests, AkShare, pandas, DuckDB, FastAPI, pytest, SSH.

---

### Task 1: Provider probe contract and gate evaluation

**Files:**
- Create: `src/kline/ops/__init__.py`
- Create: `src/kline/ops/provider_probe.py`
- Test: `tests/test_provider_probe.py`

- [ ] **Step 1: Write failing result and threshold tests**

Define fixtures that produce observations with `provider`, `security`, `success`, `elapsed_seconds`, `rows`, `missing_fields`, and `error_type`. Assert that `evaluate_gate()` requires EastMoney 90%, Tencent 80%, at least one successful Sina observation, and successful index/calendar observations with complete OHLCV.

- [ ] **Step 2: Verify the tests fail because the module does not exist**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_provider_probe.py -q`

Expected: collection fails with `ModuleNotFoundError: kline.ops`.

- [ ] **Step 3: Implement the pure contract**

Add immutable `ProbeObservation` and `ProbeReport` dataclasses, `classify_error(exc)`, percentile calculation, and `evaluate_gate(observations)`. The report must contain per-provider success rate, mean/P95 latency, empty response count, missing-field count, error categories, `passed`, and explicit `reasons`.

- [ ] **Step 4: Verify contract tests pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_provider_probe.py -q`

- [ ] **Step 5: Commit**

```powershell
git add src/kline/ops tests/test_provider_probe.py
git commit -m "Add provider gate evaluation"
```

### Task 2: Explicit provider adapters and CLI probe

**Files:**
- Create: `src/kline/data/tencent_source.py`
- Create: `scripts/probe_providers.py`
- Modify: `src/kline/ops/provider_probe.py`
- Test: `tests/test_tencent_source.py`
- Test: `tests/test_provider_probe.py`

- [ ] **Step 1: Write a failing Tencent normalization test**

Mock the Tencent `fqkline/get` response for `sh600000` and assert normalized `date/open/close/high/low/volume` values, request timeout, and a clear empty-data error.

- [ ] **Step 2: Verify the Tencent test fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_tencent_source.py -q`

Expected: missing `kline.data.tencent_source`.

- [ ] **Step 3: Implement `TencentHttpSource`**

Use `https://web.ifzq.gtimg.cn/appstock/app/fqkline/get` with an injected requests session, bounded timeout, retries, and raw daily data only. Normalize the provider response without reusing or mixing adjusted bars.

- [ ] **Step 4: Write failing runner tests with injected adapters**

Provide fake EastMoney, Tencent, Sina, index, and calendar callables. Assert `ProviderProbeRunner.run()` executes exactly 10/10/3/1/1 checks, records every failure instead of aborting, and validates required fields.

- [ ] **Step 5: Implement the runner and CLI**

The CLI uses a fixed representative set spanning Shanghai, Shenzhen, Beijing, STAR and ChiNext; probes the most recent 90 calendar days; writes UTF-8 JSON to `--output`; prints a short table; and exits `0` only when the gate passes. `--quick` runs 3 EastMoney, 3 Tencent, 1 Sina, index, and calendar checks for diagnostics but never marks the production gate passed.

- [ ] **Step 6: Run provider unit tests and lint**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_provider_probe.py tests\test_tencent_source.py -q
.\.venv\Scripts\ruff.exe check src tests scripts
```

- [ ] **Step 7: Commit**

```powershell
git add src/kline/data/tencent_source.py src/kline/ops/provider_probe.py scripts/probe_providers.py tests
git commit -m "Add production provider probe"
```

### Task 3: Persistent single-writer job store

**Files:**
- Create: `src/kline/jobs/__init__.py`
- Create: `src/kline/jobs/store.py`
- Create: `src/kline/jobs/coordinator.py`
- Test: `tests/test_job_store.py`
- Test: `tests/test_job_coordinator.py`

- [ ] **Step 1: Write failing job persistence tests**

Assert `JobStore` creates `jobs` with ID, type, status, progress, payload, result, error, created/updated timestamps, and resumable flag. Reopening the store must preserve rows; startup recovery changes `running` to `interrupted`, never to `completed`.

- [ ] **Step 2: Verify the persistence tests fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_job_store.py -q`

Expected: missing `kline.jobs`.

- [ ] **Step 3: Implement `JobStore`**

Use one owned DuckDB connection, a re-entrant lock, parameterized SQL, additive schema initialization, `schema_version=1`, JSON payload/result columns, and explicit `close()`. On connection initialization execute `SET memory_limit='2GB'` and `SET threads=2`.

- [ ] **Step 4: Write failing coordinator serialization tests**

Submit import, label, and feature jobs that append start/end events. Assert no two heavy jobs overlap, only one executor thread performs work, duplicate active job types are rejected, and progress is persisted.

- [ ] **Step 5: Implement `HeavyTaskCoordinator`**

Own one `ThreadPoolExecutor(max_workers=1)`. `submit(job_type, payload, operation)` creates a queued job, transitions it through running to completed/failed, records progress, and exposes `active()` across all heavy job types. `shutdown()` drains and closes cleanly.

- [ ] **Step 6: Verify store and coordinator tests pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_job_store.py tests\test_job_coordinator.py -q`

- [ ] **Step 7: Commit**

```powershell
git add src/kline/jobs tests/test_job_store.py tests/test_job_coordinator.py
git commit -m "Add persistent single-writer job coordinator"
```

### Task 4: Route all API heavy work through one coordinator

**Files:**
- Modify: `src/kline/api.py`
- Modify: `src/kline/config.py`
- Modify: `src/kline/data/pipeline.py`
- Modify: `tests/test_api.py`
- Create: `tests/test_single_writer.py`

- [ ] **Step 1: Write failing global mutual-exclusion API tests**

Start a blocked import operation, then assert label and feature build requests return `409 HEAVY_JOB_ALREADY_RUNNING` with the active job ID. Assert all three status endpoints read the persistent store and retain their existing response fields.

- [ ] **Step 2: Write a failing single-writer instrumentation test**

Inject a pipeline connection factory that records thread IDs and concurrent write sections. Execute import followed by labels/features and assert maximum DuckDB write concurrency is one and all production writes occur through the coordinator thread.

- [ ] **Step 3: Verify the tests fail for the current independent task stores**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_api.py tests\test_single_writer.py -q`

Expected: label/feature jobs can start independently or instrumentation observes uncoordinated writes.

- [ ] **Step 4: Replace independent executors**

Create one `JobStore(settings.jobs_db_path)` and one `HeavyTaskCoordinator` in `create_app()`. Convert import, label, and feature task stores into operation adapters without their own executors. Keep per-import network fetch concurrency bounded by `min(settings.download_workers, 3)` and serialize every `pipeline.import_security()` call.

- [ ] **Step 5: Add production settings**

Add `jobs_db_path`, `duckdb_memory_limit='2GB'`, `duckdb_threads=2`, and `market_timezone='Asia/Shanghai'`. Configure every DatasetPipeline connection with the same DuckDB limits. Tests override all paths to temporary directories.

- [ ] **Step 6: Verify global mutual exclusion and regression suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_api.py tests\test_single_writer.py -q
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests scripts
```

- [ ] **Step 7: Commit**

```powershell
git add src/kline/api.py src/kline/config.py src/kline/data/pipeline.py tests
git commit -m "Enforce one persistent heavy job writer"
```

### Task 5: Run production-server gates without deploying

**Files:**
- Create locally ignored artifact: `artifacts/provider-gate-154.53.75.101.json`
- Create locally ignored artifact: `artifacts/single-writer-gate.json`
- Modify: `.gitignore`
- Modify: `README.md`

- [ ] **Step 1: Add artifact exclusion and gate instructions**

Ignore `/artifacts/`. Document that gate outputs contain operational metadata and are not committed. Document the exact server command and thresholds.

- [ ] **Step 2: Verify the full local suite before remote execution**

Run backend tests, Ruff, frontend tests, production build, and `git diff --check`. Stop if any command fails.

- [ ] **Step 3: Create an isolated remote gate workspace**

Over SSH, create `/tmp/kline_gate_<timestamp>`, clone the current branch, create a Python virtual environment, and install the project. Do not create `/home/guagua/apps/kline`, systemd units, Tunnel credentials, or shared production data.

- [ ] **Step 4: Execute the full provider gate on the server**

Run `python scripts/probe_providers.py --output provider-gate.json`, copy the JSON artifact back locally, and capture Python/AkShare versions and server timestamp. A nonzero exit means G2 failed and blocks deployment.

- [ ] **Step 5: Execute the single-writer gate on the server**

Run the coordinator/API concurrency tests with `KLINE_ENV=test` and all database/data paths under the temporary gate workspace. Emit JSON containing test command, commit, worker count, max observed write concurrency, and result.

- [ ] **Step 6: Clean only the temporary gate workspace**

Remove `/tmp/kline_gate_<timestamp>` after artifacts are copied. Verify `/home/guagua/apps/kline` and systemd remain untouched.

- [ ] **Step 7: Publish a gate decision**

Report G1 and G2 independently as `PASS` or `BLOCKED`, including provider success rates, P95, failures, and single-writer evidence. Do not continue to deployment implementation unless both pass and the user approves Phase 2.

- [ ] **Step 8: Commit documentation changes**

```powershell
git add .gitignore README.md
git commit -m "Document deployment gate execution"
```
