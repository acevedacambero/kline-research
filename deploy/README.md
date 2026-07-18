# Production operations

The application runs entirely as the `guagua` user. Install the unit files in
`~/.config/systemd/user/`, then run:

```bash
systemctl --user daemon-reload
systemctl --user enable --now kline.service
systemctl --user enable --now cloudflared.service
journalctl --user -u kline.service -f
```

`~/apps/kline/shared/.env` and `shared/secrets/cloudflared.env` must be mode 600;
the `shared/secrets` directory must be mode 700. The app listens only on
`127.0.0.1:8800`. Verify with `scripts/healthcheck.sh`.

Releases live under `releases/`. `current` selects the active release and
`previous` selects the rollback release. Run `scripts/rollback.sh`; it refuses
safely when no previous release exists and never modifies `shared/data`.

The Python environment is shared at `shared/runtime-venv`; releases should
symlink `.venv` to it instead of copying roughly 500 MB per release. After a
successful deployment, run `deploy/prune-releases.sh` to retain only `current`
and `previous`. The pruning script refuses targets outside `releases/` and does
not touch `shared/data` or the shared runtime.

Use `deploy/install-release.sh RELEASE_ID SOURCE_TAR WEB_DIST_TAR` for normal
deployments. It validates inputs, links the shared runtime, records the actual
previous release, runs the bounded health check, rolls back on failure, and
prunes obsolete releases after success.

For the final production rebuild, stop `kline.service` first and run
`python scripts/run_final_data_build.py`. The command owns the only job/data
writer while it completes history backfill, coverage rebuild and a full
P1→P2→P3 rebuild. Always restart the service afterward; use a shell trap in
unattended operation so a failed build cannot leave the web service stopped.
