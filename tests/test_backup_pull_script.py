from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_server_backup_pull_verifies_before_remote_cleanup():
    script = (ROOT / "scripts" / "pull_server_backups.ps1").read_text(encoding="utf-8")

    verify_index = script.index("Get-FileHash -LiteralPath $localArchive")
    cleanup_index = script.index("rm -- '$remoteArchive' '$remoteChecksum'")
    assert verify_index < cleanup_index
    assert "SHA-256 mismatch" in script
    assert "remote copy was retained" in script
    assert "remoteDeleted = $true" in script
