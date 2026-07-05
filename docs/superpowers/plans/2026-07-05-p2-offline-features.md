# P2 Offline Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build versioned, look-ahead-safe daily P2 features with batch generation, audit APIs, and a grouped UI inspector.

**Architecture:** A pure pandas feature engine consumes one security's aligned raw/QFQ/total-return bars. A batch layer reads immutable local snapshots and writes version-keyed Parquet plus a manifest; FastAPI exposes asynchronous builds and point-in-time audits, while React only renders backend results.

**Tech Stack:** Python 3.12, pandas, Parquet, DuckDB, FastAPI, React, TypeScript, Vitest.

---

### Task 1: Feature calculation kernel

**Files:**
- Create: `src/kline/features/__init__.py`
- Create: `src/kline/features/core.py`
- Test: `tests/test_features.py`

- [ ] Write failing tests for MA values/alignment/slopes/deviation using only rows through the requested date.
- [ ] Run `python -m pytest tests/test_features.py -q` and verify missing-module failure.
- [ ] Implement `compute_daily_features(bars)` with deterministic date sorting and one output row per input row.
- [ ] Add failing tests for range position/high drawdown and 5/10/20/60/120-day total returns.
- [ ] Implement position and momentum fields, returning null when a complete window is unavailable.
- [ ] Add failing tests for volume ratio/percentile, return volatility, amplitude, gaps, suspension gaps, limit-up counts, and locked-board streaks.
- [ ] Implement the remaining fields plus `available_history`, `reasons`, and price-basis metadata.
- [ ] Run the feature tests and the complete Python suite.

### Task 2: Versioned feature dataset

**Files:**
- Create: `src/kline/features/batch.py`
- Test: `tests/test_feature_batch.py`
- Modify: `src/kline/config.py`

- [ ] Write failing tests proving the output path depends on snapshot, factor, rule, and feature-definition versions.
- [ ] Implement `FeatureDatasetStore` and its manifest/quality report.
- [ ] Write failing tests for successful multi-security build, reusable current output, and isolated security failure.
- [ ] Implement `BatchFeatureBuilder` over cached derived paths and corresponding raw facts.
- [ ] Set `featureDefinitionVersion` to `daily-features-v1` and run Python tests.

### Task 3: Feature task and audit API

**Files:**
- Modify: `src/kline/api.py`
- Modify: `tests/test_api.py`
- Modify generated contracts: `web/openapi.json`, `web/src/generated-api.d.ts`

- [ ] Add failing API tests for `POST /api/features/build`, task polling, duplicate-build rejection, and `POST /api/p2/audit`.
- [ ] Implement a single-worker `FeatureTaskStore` with progress, rows, errors, and terminal status.
- [ ] Implement build endpoints and point-in-time audit response grouped by trend, position, momentum, volume-price, and trading behavior.
- [ ] Export OpenAPI and regenerate TypeScript definitions.
- [ ] Run API and full backend tests.

### Task 4: P2 user interface

**Files:**
- Modify: `web/src/api.ts`
- Modify: `web/src/App.tsx`
- Modify: `web/src/styles.css`
- Modify: `web/src/App.test.tsx`
- Modify: `web/src/api.test.ts`

- [ ] Add failing frontend tests for starting/polling a feature task and rendering five audit groups with “历史不足” for null values.
- [ ] Add typed feature task/audit client methods.
- [ ] Add the P2 build button and grouped audit panel, sharing exchange/code/date inputs with P1.
- [ ] Run Vitest and production build.

### Task 5: Verification and publication

**Files:**
- Modify: `README.md`

- [ ] Document P2 generation, audit endpoints, versions, and price bases.
- [ ] Run `python -m pytest -q`, Ruff, frontend tests, production build, and `git diff --check`.
- [ ] Build features for representative cached securities and inspect row counts, missing rates, and audit output.
- [ ] Commit the implementation and push the feature branch.
