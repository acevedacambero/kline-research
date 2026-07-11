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
