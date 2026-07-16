from pathlib import Path

from kline.ops.backup import DataBackupManager


def test_backup_verifies_and_restores_with_previous_data_preserved(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "catalog.duckdb").write_bytes(b"catalog-v1")
    (data / "nested").mkdir()
    (data / "nested" / "bars.parquet").write_bytes(b"bars-v1")
    manager = DataBackupManager(data, tmp_path / "backups")

    created = manager.create()
    verified = manager.verify(Path(created["archive"]))
    assert verified["valid"] is True
    assert verified["fileCount"] == 2

    (data / "catalog.duckdb").write_bytes(b"catalog-v2")
    restored = manager.restore(Path(created["archive"]))
    assert (data / "catalog.duckdb").read_bytes() == b"catalog-v1"
    assert (data / "nested" / "bars.parquet").read_bytes() == b"bars-v1"
    assert Path(restored["previousData"], "catalog.duckdb").read_bytes() == b"catalog-v2"


def test_backup_excludes_backup_directory_when_nested_in_data(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "value.txt").write_text("value", encoding="utf-8")
    manager = DataBackupManager(data, data / "backups")

    first = manager.create()
    second = manager.create()

    assert first["fileCount"] == 1
    assert second["fileCount"] == 1
