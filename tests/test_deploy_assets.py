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


def test_healthcheck_is_bounded_and_local_only():
    script = read("healthcheck.sh")
    assert "127.0.0.1:8800/healthz" in script
    assert "--max-time 10" in script
    assert "curl" in script


def test_rollback_switches_release_symlink_without_touching_shared_data():
    script = read("rollback.sh")
    assert "readlink" in script
    assert "ln -sfn" in script
    assert "previous" in script
    assert "shared/data" not in script
    assert "rm -rf" not in script
