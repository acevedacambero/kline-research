# Private Tunnel Production Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the complete FastAPI, React, DuckDB and Parquet application to `154.53.75.101` and publish it privately at `skyland.us.ci` through Cloudflare Access and Tunnel.

**Architecture:** One user-level Uvicorn process listens only on `127.0.0.1:8800`, serves both `/api/*` and the built React application, and owns the single persistent DuckDB writer. A user-level Cloudflare Tunnel is the only public route; Access protects the hostname and the API additionally validates Cloudflare Access JWTs in production. Releases are immutable and selected through an atomic `current` symlink while data remains under `shared/data`.

**Tech Stack:** Python 3.12, FastAPI, PyJWT, React/Vite, uv, DuckDB, Parquet, systemd --user, cloudflared, Cloudflare Access.

---

### Task 1: Production HTTP boundary

**Files:**
- Create: `src/kline/access.py`
- Modify: `src/kline/config.py`
- Modify: `src/kline/api.py`
- Modify: `pyproject.toml`
- Test: `tests/test_access.py`
- Test: `tests/test_api.py`

- [ ] Write failing tests proving `/healthz` is public, production `/api/*` rejects missing/invalid Access JWTs with 403, valid issuer/AUD/email claims pass, and non-API static requests are not intercepted by API middleware.
- [ ] Run `pytest tests/test_access.py tests/test_api.py -q` and confirm failure because the verifier/settings do not exist.
- [ ] Add `PyJWT[crypto]`, settings for `frontend_dist_path`, `cloudflare_access_required`, team domain, audience and comma-separated email allowlist. Implement a cached JWKS verifier that validates signature, issuer, audience, expiry and normalized email.
- [ ] Add middleware only when Access is required, expose `/healthz`, and mount an existing Vite `dist` directory after all API routes so FastAPI serves the complete same-origin application.
- [ ] Run focused tests, full pytest and Ruff; commit `Add production HTTP boundary`.

### Task 2: Reproducible release and user services

**Files:**
- Create: `deploy/kline.service`
- Create: `deploy/cloudflared.service`
- Create: `deploy/healthcheck.sh`
- Create: `deploy/rollback.sh`
- Create: `deploy/README.md`
- Test: `tests/test_deploy_assets.py`

- [ ] Write failing tests that parse service files and assert one Uvicorn worker, localhost port 8800, shared environment/data paths, restart/resource hardening, user-level cloudflared token loading, and health/rollback scripts that never mutate shared data.
- [ ] Add service units with `NoNewPrivileges=true`, `MemoryMax=2800M`, `TasksMax=256`, restart policies and explicit working paths under `/home/guagua/apps/kline`.
- [ ] Add healthcheck and rollback scripts using exact symlink targets, bounded curl timeouts and atomic `ln -sfn`; document install/restart/log commands and 600/700 permissions.
- [ ] Run deployment-asset tests, ShellCheck-compatible syntax checks through `bash -n` on the VPS, full tests and Ruff; commit `Add private tunnel deployment assets`.

### Task 3: Build and stage an immutable release

**Files:**
- Create ignored artifacts: `artifacts/kline-release-<commit>.tar.gz`, `artifacts/deploy-manifest.json`

- [ ] Run the complete local backend/frontend verification and build `web/dist`; stop on failure.
- [ ] Archive the exact tracked commit plus `web/dist`, transfer it to a new `/home/guagua/apps/kline/releases/<timestamp>_<commit>` directory, and verify its SHA-256 before extraction.
- [ ] Create `shared/data`, `shared/logs`, `shared/tmp`, `shared/secrets` with 700 directories; upload the 0.71 GiB local data foundation to `shared/data` and compare file count/aggregate fingerprint.
- [ ] Use user-level uv to install Python 3.12 dependencies inside the release, run tests against `/tmp/kline_deploy_test_<timestamp>` only, and write a release manifest containing commit, Python, dependency, build and Gate versions.
- [ ] Do not switch `current` until all staging checks pass.

### Task 4: Start the private origin

**Files:**
- Create server-only: `/home/guagua/apps/kline/shared/.env`
- Create server-only: `/home/guagua/.config/systemd/user/kline.service`

- [ ] Write `.env` with shared data/jobs paths, DuckDB 2 GB/2 threads, Asia/Shanghai, one-process settings, frontend dist path and Access settings; keep it mode 600.
- [ ] Install the kline user unit, atomically point `current` to the staged release, reload user systemd and start `kline.service`.
- [ ] Verify one listening process on `127.0.0.1:8800`, no public 8800 listener, `/healthz` returns 200, unauthenticated `/api/*` returns 403 once Access is enabled, and existing Nginx 80/443 remains active.
- [ ] Exercise representative SH/SZ bars and P1/P2 audit through a local test mode or validated Access token without connecting tests to a separate production writer.
- [ ] Stop and roll back `current` if health or smoke checks fail.

### Task 5: Cloudflare Tunnel and Access cutover

**External state:** Cloudflare account `0b69f5eb8c422ea72818b56836a74f39`, hostname `skyland.us.ci`.

- [ ] Create a named Tunnel for the VPS, route only `skyland.us.ci` to `http://127.0.0.1:8800`, and store the generated token only in the server `shared/secrets` directory with mode 600.
- [ ] Create or update a self-hosted Access application for the entire hostname, allow only `acevedacambero@gmail.com`, record the application AUD and team domain, and place those non-secret identifiers in `.env`.
- [ ] Install/start the user cloudflared unit and verify it survives user-service restart; then enable backend Access validation and restart the app.
- [ ] Confirm unauthenticated public access is intercepted by Access, authenticated Chrome loads the React UI and `/api/system/health`, direct `154.53.75.101:8800` is unreachable, and Nginx remains unchanged.
- [ ] Run one SH and one SZ audit from the public UI. Preserve the prior DNS value and previous `current` target in the deployment manifest for rollback.

### Task 6: Final verification and handoff

**Files:**
- Modify: `README.md`
- Create ignored artifact: `artifacts/production-deploy-154.53.75.101.json`

- [ ] Re-run local tests/build, VPS `/healthz`, service status, provider G2-v2 summary, disk/memory checks, shared-data fingerprint and public authenticated smoke tests.
- [ ] Reboot-recovery test the user services with explicit user approval only; otherwise verify `linger=yes`, enabled units and restart recovery without rebooting the VPS.
- [ ] Exercise rollback to the prior release when one exists; for the first release, verify rollback refuses safely without changing shared data.
- [ ] Record release, service, Cloudflare, health, data and rollback evidence in the ignored deployment artifact without tokens or JWTs.
- [ ] Update README with production operations and commit `Document private tunnel production deployment`.
