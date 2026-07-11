from pathlib import Path


ROOT = Path(__file__).parents[1]


def read(name: str) -> str:
    return (ROOT / "deploy" / name).read_text(encoding="utf-8")


def test_kline_user_service_is_single_worker_and_hardened():
    unit = read("kline.service")
    assert "127.0.0.1" in unit and "8800" in unit
    assert "--workers 1" in unit
    assert "EnvironmentFile=%h/apps/kline/shared/.env" in unit
    assert "WorkingDirectory=%h/apps/kline/current" in unit
    assert "NoNewPrivileges=true" in unit
    assert "MemoryMax=2800M" in unit
    assert "TasksMax=256" in unit
    assert "Restart=on-failure" in unit


def test_cloudflared_service_reads_token_from_private_environment():
    unit = read("cloudflared.service")
    assert "EnvironmentFile=%h/apps/kline/shared/secrets/cloudflared.env" in unit
    assert "--token ${TUNNEL_TOKEN}" in unit
    assert "Restart=always" in unit


def test_healthcheck_retries_during_bounded_service_startup_window():
    script = read("healthcheck.sh")
    assert "127.0.0.1:8800/healthz" in script
    assert "--max-time 10" in script
    assert "curl" in script
    assert "for attempt in {1..12}" in script
    assert "sleep 1" in script


def test_rollback_switches_release_symlink_without_touching_shared_data():
    script = read("rollback.sh")
    assert "readlink" in script
    assert "ln -sfn" in script
    assert "previous" in script
    assert "shared/data" not in script
    assert "rm -rf" not in script


def test_release_pruning_retains_current_previous_and_shared_data():
    script = read("prune-releases.sh")
    assert '"${current}"|"${previous}"' in script
    assert '"${releases}/"*' in script
    assert "shared/data" not in script


def test_release_install_uses_shared_runtime_healthcheck_and_rollback():
    script = read("install-release.sh")
    assert "shared/runtime-venv" in script
    assert "healthcheck.sh" in script
    assert "previous" in script
    assert "prune-releases.sh" in script
    assert "ln -sfn" in script
    assert "old_previous" in script
