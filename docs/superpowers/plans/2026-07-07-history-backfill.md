# Short History Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an authenticated asynchronous task that replaces only沪深 cached histories shorter than 250 trading days with long-history Sina/AKShare snapshots and exposes progress in the React UI.

**Architecture:** A focused `HistoryBackfillService` scans current Parquet snapshots and classifies candidates independently of FastAPI. `ProductionProviderPolicy` exposes an explicit Sina-only long-history bundle method, while a task facade runs candidates through the existing single heavy-job coordinator and `DatasetPipeline` atomic snapshot writer. The React client starts and polls the task without automatically launching P1 or P2 builds.

**Tech Stack:** Python 3.12, FastAPI, pandas, DuckDB, Parquet, pytest, React, TypeScript, Vitest.

---

### Task 1: Long-history source and candidate classification

**Files:**
- Modify: `src/kline/data/provider_policy.py`
- Create: `src/kline/data/history_backfill.py`
- Modify: `src/kline/data/pipeline.py`
- Test: `tests/test_provider_policy.py`
- Create: `tests/test_history_backfill.py`

- [ ] **Step 1: Write failing provider and scanner tests**

Add a provider test asserting `fetch_long_history_bundle("sh", "600000", start, end)` calls `sina_raw_history` and `sina_adjustment_factors`, never `tencent.fetch_history`, and adds provider metadata `sina-akshare` plus policy version `history-backfill-v1`.

Add scanner tests constructing three manifest snapshots: 90-day SH, 300-day SZ, and BJ. Assert `HistoryBackfillService.scan()` returns only SH with `before_count == 90`. Add an acknowledged-new-listing quality event with the current content hash and assert the same SH snapshot is skipped on the next scan.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_provider_policy.py tests/test_history_backfill.py -q
```

Expected: failure because the long-history method and service do not exist.

- [ ] **Step 3: Implement the minimal data boundaries**

Add `HISTORY_BACKFILL_VERSION = "history-backfill-v1"` and:

```python
def fetch_long_history_bundle(self, exchange, code, start_date, end_date):
    raw = self.sina.sina_raw_history(exchange, code, start_date, end_date)
    factors = self.sina.sina_adjustment_factors(exchange, code)
    self._validate_factors(factors)
    raw.attrs.update(provider="sina-akshare", provider_policy_version=HISTORY_BACKFILL_VERSION)
    factors.attrs.update(provider="sina-akshare", provider_policy_version=HISTORY_BACKFILL_VERSION)
    return raw, factors
```

Extract existing factor validation into `_validate_factors`. Add pipeline methods `dataset_manifest_rows()` and `record_quality_event(...)` so the service does not issue SQL itself. Implement immutable `BackfillCandidate(exchange, code, path, snapshot_version, content_hash, before_count)` and make `scan()` read only current SH/SZ derived Parquet dates, filter counts below the configurable threshold, and skip matching `listing-history-short` acknowledgements.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command and expect all tests to pass.

- [ ] **Step 5: Commit**

```powershell
git add src/kline/data/provider_policy.py src/kline/data/history_backfill.py src/kline/data/pipeline.py tests/test_provider_policy.py tests/test_history_backfill.py
git commit -m "Add short history candidate scanner"
```

### Task 2: Backfill execution, classification, and durable progress

**Files:**
- Modify: `src/kline/data/history_backfill.py`
- Modify: `src/kline/api.py`
- Modify: `tests/test_history_backfill.py`
- Modify: `tests/test_single_writer.py`

- [ ] **Step 1: Write failing execution and coordination tests**

Test these behaviors with real temporary Parquet/catalog files and fake providers:

- a 90-day candidate becomes a 400-day current snapshot and records `history-backfilled` with before/after counts;
- a 120-day response ending within ten natural days of `as_of_date` records `listing-history-short` with the current content hash and increments `listingHistoryShort`;
- a short response ending earlier than the freshness cutoff records `history-backfill-failed`, preserves the prior manifest path, and adds a stable `HISTORY_COVERAGE_INCOMPLETE` error;
- one failed security does not prevent the next candidate from completing;
- an active import/label/feature/backfill task makes every other heavy-task start endpoint return `409 HEAVY_JOB_ALREADY_RUNNING`.

- [ ] **Step 2: Run tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_history_backfill.py tests/test_single_writer.py -q
```

Expected: failures because execution and the task facade are absent.

- [ ] **Step 3: Implement execution and task facade**

Implement `HistoryBackfillService.backfill(candidate, as_of_date)` so it fetches from `1990-01-01`, validates non-empty unique dates and freshness, and calls `DatasetPipeline.import_security` only after coverage classification. Return `BackfillResult(status, before_count, after_count, snapshot_version)`.

Add `HistoryBackfillTaskStore` using the existing `_TaskFacade` and job type `history_backfill`. Its operation processes candidates sequentially, publishes:

```python
{
    "total": len(candidates), "done": 0, "completed": 0,
    "listingHistoryShort": 0, "errors": [],
    "currentSecurity": None, "speed": 0.0, "etaSeconds": None,
}
```

Catch per-security exceptions and append `{security, stage, code, message}`. Register the facade with the shared `HeavyTaskCoordinator`; do not create another worker or DuckDB connection owner.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command and expect all tests to pass.

- [ ] **Step 5: Commit**

```powershell
git add src/kline/data/history_backfill.py src/kline/api.py tests/test_history_backfill.py tests/test_single_writer.py
git commit -m "Add durable history backfill task"
```

### Task 3: API contract and quality summary

**Files:**
- Modify: `src/kline/api.py`
- Modify: `src/kline/config.py`
- Modify: `tests/test_api.py`
- Modify: `scripts/export_openapi.py`
- Regenerate: `web/openapi.json`
- Regenerate: `web/src/generated-api.d.ts`

- [ ] **Step 1: Write failing API tests**

Add tests asserting:

- `POST /api/datasets/backfill-history` returns `202`, `taskId`, `total`, and `threshold: 250`;
- no candidates still creates a completed zero-item task that is pollable;
- `GET /api/datasets/backfill-history/{id}` returns the specified progress fields;
- an unknown ID returns `404 TASK_NOT_FOUND`;
- quality response contains `shortHistoryCached`, `listingHistoryShort`, and `historyBackfillFailed` counts;
- settings reject `history_backfill_min_days < 1` and default to 250.

- [ ] **Step 2: Run tests and verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_api.py -q
```

Expected: 404/missing-field failures.

- [ ] **Step 3: Add API routes and settings**

Add `history_backfill_min_days: int = 250` and `history_backfill_freshness_days: int = 10` with positive validation. Wire the service/task facade during `create_app`, add the two routes, and extend `/api/datasets/quality` using service summary methods. Keep all routes under `/api/*` so existing Cloudflare middleware applies.

- [ ] **Step 4: Regenerate and verify the contract**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_api.py -q
pnpm generate:api
git diff --exit-code -- web/openapi.json web/src/generated-api.d.ts
```

Expected: API tests pass; a second generation produces no diff.

- [ ] **Step 5: Commit**

```powershell
git add src/kline/api.py src/kline/config.py tests/test_api.py web/openapi.json web/src/generated-api.d.ts
git commit -m "Expose history backfill API"
```

### Task 4: Frontend task controls and status

**Files:**
- Modify: `web/src/api.ts`
- Modify: `web/src/App.tsx`
- Modify: `web/src/App.test.tsx`

- [ ] **Step 1: Write failing UI tests**

Add a test that finds “补全短历史”, clicks it, verifies a POST to `/api/datasets/backfill-history`, returns a task ID, polls its status, and ultimately renders `已补全 3 · 新股 1 · 错误 1`. Assert the terminal message tells the user to inspect errors and then manually run P1/P2. Add an API unit test for the start/status paths and response typing.

- [ ] **Step 2: Run tests and verify RED**

```powershell
pnpm test:web
```

Expected: button/path assertions fail.

- [ ] **Step 3: Implement the client and UI**

Add `api.startHistoryBackfill()` and `api.historyBackfillTask(taskId)`. Add a status-panel button disabled by existing `busy`, reuse one-second polling, render candidate/progress/completed/new-listing/error/current/speed/ETA values, and leave P1/P2 buttons as separate user actions.

- [ ] **Step 4: Run frontend verification**

```powershell
pnpm test:web
pnpm build
```

Expected: all Vitest tests and the production build pass.

- [ ] **Step 5: Commit**

```powershell
git add web/src/api.ts web/src/App.tsx web/src/App.test.tsx
git commit -m "Add history backfill controls"
```

### Task 5: Full verification and production canary

**Files:**
- Modify: `README.md`
- Create ignored artifact: `artifacts/history-backfill-canary.json`

- [ ] **Step 1: Document operation and rollback**

Document that the task only targets SH/SZ snapshots below the threshold, uses Sina/AKShare long history, preserves old snapshots on failure, and requires manual P1/P2 generation afterward.

- [ ] **Step 2: Run the complete local gate**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
pnpm test:web
pnpm build
```

Expected: zero failures and a successful Vite build.

- [ ] **Step 3: Stage and verify a VPS release**

Build an immutable release, run the full VPS test suite against isolated temporary paths, switch `current`, and verify `/healthz`, user services, localhost-only port 8800, and unauthenticated API status 403.

- [ ] **Step 4: Run a bounded production canary**

Record the candidate count, run the task first against the existing representative Shanghai short caches, verify their before/after dates and quality events, then allow the full candidate list to continue. Store only task IDs, counts, snapshot versions, timings, and errors in `artifacts/history-backfill-canary.json`; do not store JWTs or provider response bodies.

- [ ] **Step 5: Verify public UI and rollback**

Through authenticated `https://skyland.us.ci/`, confirm the button, progress, terminal summary, SH historical audit, and unchanged manual P1/P2 flow. Exercise release rollback and restore the new release without modifying `shared/data`.

- [ ] **Step 6: Commit documentation**

```powershell
git add README.md
git commit -m "Document history backfill operation"
```
