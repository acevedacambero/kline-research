# Shanghai Shenzhen Provider Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the production market-data route with Tencent raw plus Sina factors/calendar, remove Beijing-market product support and cached data, and rerun a server-side G2 gate that can unblock deployment.

**Architecture:** A versioned provider policy selects Tencent for Shanghai/Shenzhen raw stock and index bars, with explicit Sina raw fallback and Sina-only factors/calendar. A manifest-driven cleanup service removes Beijing records and files safely; a revised gate separates required production checks from diagnostic EastMoney observations.

**Tech Stack:** Python 3.12, FastAPI, pandas, DuckDB, Parquet, React, TypeScript, pytest, Vitest, SSH.

---

### Task 1: Versioned Shanghai/Shenzhen production provider policy

**Files:**
- Create: `src/kline/data/provider_policy.py`
- Modify: `src/kline/data/tencent_source.py`
- Modify: `src/kline/data/akshare_source.py`
- Modify: `src/kline/config.py`
- Test: `tests/test_provider_policy.py`
- Test: `tests/test_tencent_source.py`

- [ ] **Step 1: Write failing policy-routing tests**

Use injected Tencent and Sina fakes. Assert `ProductionProviderPolicy.fetch_bundle("sh", ...)` and `("sz", ...)` use Tencent exactly once for raw and Sina exactly once for factors; Tencent failure invokes explicit Sina raw fallback; EastMoney is never called; `exchange="bj"` raises `MarketNotSupportedError` before any provider call.

- [ ] **Step 2: Verify RED**

Run `.\.venv\Scripts\python.exe -m pytest tests\test_provider_policy.py -q` and expect missing `kline.data.provider_policy`.

- [ ] **Step 3: Implement the production policy**

Define `SUPPORTED_EXCHANGES=("sh","sz")`, `PROVIDER_POLICY_VERSION="sh-sz-tencent-sina-v1"`, `MarketNotSupportedError`, and `ProductionProviderPolicy`. Keep raw/factor frames separate, require nonempty factors and complete factor coverage, and stamp actual raw/factor provider metadata. Add explicit AkShare methods for Sina raw and factors so no implicit EastMoney fallback is used.

- [ ] **Step 4: Write failing Tencent index tests**

Mock `sh000001` and `sz399001` raw day payloads and assert `index_history(exchange)` returns normalized OHLCV with provider=`tencent-http`; reject any other exchange/symbol mapping.

- [ ] **Step 5: Implement explicit Tencent index routing**

Reuse the raw response parser without adjusted fields. Add `providerPolicyVersion` to `VERSIONS` and data import metadata.

- [ ] **Step 6: Verify and commit**

Run focused tests, the full backend suite, and Ruff. Commit:

```powershell
git add src/kline/data src/kline/config.py tests
git commit -m "Add Shanghai Shenzhen provider policy"
```

### Task 2: Remove Beijing market from API and UI product scope

**Files:**
- Modify: `src/kline/api.py`
- Modify: `web/src/App.tsx`
- Modify: `web/src/api.ts`
- Modify: `tests/test_api.py`
- Modify: `web/src/App.test.tsx`
- Modify generated contracts: `web/openapi.json`, `web/src/generated-api.d.ts`

- [ ] **Step 1: Write failing API scope tests**

Assert securities responses filter `bj`, representative import contains only Shanghai/Shenzhen, full import filters Beijing, and bars/P1/P2 requests with `exchange=bj` return `422 MARKET_NOT_SUPPORTED` without invoking a provider.

- [ ] **Step 2: Verify RED**

Run the new API tests and confirm Beijing is currently returned or accepted.

- [ ] **Step 3: Apply the market policy in API composition**

Replace the runtime hybrid EastMoney-first source with `ProductionProviderPolicy`, filter cached/security-master results to supported exchanges, and validate exchange at every public market endpoint before cache/provider access. Preserve existing response contracts for Shanghai/Shenzhen.

- [ ] **Step 4: Write failing frontend scope tests**

Assert the exchange selector contains Shanghai and Shenzhen only, no Beijing option or text, and audit requests still use the selected supported exchange.

- [ ] **Step 5: Update UI and contracts**

Remove the Beijing option, expose provider policy version in status, regenerate OpenAPI types, and run Vitest/build.

- [ ] **Step 6: Verify and commit**

Run backend, Ruff, frontend tests, and build. Commit:

```powershell
git add src/kline/api.py web tests/test_api.py
git commit -m "Limit product scope to Shanghai and Shenzhen"
```

### Task 3: Manifest-safe Beijing cache cleanup service

**Files:**
- Create: `src/kline/data/market_cleanup.py`
- Create: `scripts/cleanup_market.py`
- Modify: `src/kline/data/pipeline.py`
- Test: `tests/test_market_cleanup.py`

- [ ] **Step 1: Write failing dry-run tests**

Build a temporary catalog/security master with SH/SZ/BJ records, raw/factor/derived files, labels and features. Assert `plan_cleanup("bj")` reports only Beijing records/files, exact bytes/counts, shared-reference protection, and performs no mutation. Assert unsupported/wildcard/empty exchange inputs are rejected.

- [ ] **Step 2: Verify RED**

Run `.\.venv\Scripts\python.exe -m pytest tests\test_market_cleanup.py -q` and expect missing cleanup module.

- [ ] **Step 3: Implement immutable cleanup planning**

Create typed cleanup plan/entry/receipt models. Query exact `stock:bj:*` rows, resolve and validate every path under the configured data root, detect references from non-Beijing manifest rows, enumerate only exchange-specific label/feature files, and calculate fingerprints before execution.

- [ ] **Step 4: Write failing execution tests**

Assert `execute(plan)` refuses a stale/tampered plan, removes Beijing manifest/security-master/files, prunes empty directories, preserves shared and SH/SZ files byte-for-byte, and emits deleted/skipped/missing/error receipt entries. A second execution must be idempotent and non-destructive.

- [ ] **Step 5: Implement transactional metadata-first cleanup**

Revalidate the plan, update a temporary security-master file atomically, delete exact catalog rows in a DuckDB transaction, then delete verified unreferenced files and prune empty directories. Never recursively delete the snapshots root. The CLI defaults to dry-run; execution requires `--execute --exchange bj --plan <receipt>` and writes JSON under `artifacts/`.

- [ ] **Step 6: Verify and commit**

Run cleanup tests, full pytest, and Ruff. Commit:

```powershell
git add src/kline/data/market_cleanup.py src/kline/data/pipeline.py scripts/cleanup_market.py tests/test_market_cleanup.py
git commit -m "Add auditable Beijing cache cleanup"
```

### Task 4: Revised required/diagnostic G2 probe

**Files:**
- Modify: `src/kline/ops/provider_probe.py`
- Modify: `scripts/probe_providers.py`
- Modify: `tests/test_provider_probe.py`
- Create: `tests/test_provider_gate_v2.py`

- [ ] **Step 1: Write failing G2-v2 evaluation tests**

Create observations for Tencent 10 SH/SZ stocks, Tencent two indexes, Sina factors for six securities, Sina raw fallback for SH/SZ, calendar, and failed EastMoney diagnostics. Assert required checks pass despite EastMoney failure; any required index/factor/calendar/coverage failure blocks. Assert no Beijing target appears.

- [ ] **Step 2: Verify RED**

Run the new tests and confirm the existing gate treats EastMoney as required and lacks factor/index-pair checks.

- [ ] **Step 3: Implement versioned gate sections**

Add `gateVersion="sh-sz-provider-g2-v2"`, separate immutable `requiredChecks` and `diagnosticChecks`, explicit factor observations with coverage/validity fields, two Tencent index targets, and warning-only EastMoney metrics. Keep per-target observations and detached JSON serialization.

- [ ] **Step 4: Update CLI targets and output**

Full mode must execute the exact revised sample counts and return exit 0 only when required checks pass. Quick remains diagnostic exit 2. Print required failures separately from warnings.

- [ ] **Step 5: Verify and commit**

Run focused/full backend tests and Ruff. Commit:

```powershell
git add src/kline/ops scripts/probe_providers.py tests
git commit -m "Revise G2 for Shanghai Shenzhen providers"
```

### Task 5: Execute local cleanup and authoritative server G2

**Files:**
- Create ignored artifacts: `artifacts/bj-cleanup-plan.json`, `artifacts/bj-cleanup-receipt.json`, `artifacts/provider-gate-154.53.75.101.json`
- Modify: `README.md`

- [ ] **Step 1: Run complete local verification**

Run backend tests, Ruff, frontend tests/build, and diff check. Record the exact commit SHA. Stop on any failure.

- [ ] **Step 2: Generate and inspect the Beijing dry-run**

Run `scripts/cleanup_market.py --exchange bj --output artifacts/bj-cleanup-plan.json`. Verify every planned manifest key starts `stock:bj:` and every file resolves under the project data root. Record pre-cleanup SH/SZ counts and fingerprints.

- [ ] **Step 3: Execute the approved cleanup plan**

Run the exact plan with `--execute`, save the receipt, and verify BJ catalog/security master/label/feature counts are zero. Verify SH/SZ counts and fingerprints are unchanged. Do not delete ignored gate/cleanup artifacts.

- [ ] **Step 4: Run the revised server G2 in isolation**

Transfer the exact committed tree to a fresh `/tmp/kline_gate_<timestamp>`, use user-scoped Python, run the full non-quick v2 probe, copy and validate the report, then remove the temp directory. Do not create production directories or services.

- [ ] **Step 5: Publish the gate decision**

Report required and diagnostic results separately. If G2 passes, Phase 2 remains pending explicit user approval; if blocked, identify the precise required check and do not deploy.

- [ ] **Step 6: Document and commit**

Update README with the production provider policy, market scope, cleanup command and revised gate. Commit only tracked documentation changes:

```powershell
git add README.md
git commit -m "Document Shanghai Shenzhen production gate"
```
