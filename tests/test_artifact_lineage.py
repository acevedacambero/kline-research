import os
from pathlib import Path

from kline.artifact_lineage import classify_artifacts


def touch(path: Path, timestamp: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    path.chmod(0o666)
    os.utime(path, (timestamp, timestamp))
    return path


def test_classifies_current_stale_missing_orphan_and_superseded(tmp_path):
    current = touch(tmp_path / "snapshot-new" / "sh" / "600000.parquet", 3)
    old = touch(tmp_path / "snapshot-old" / "sh" / "600000.parquet", 1)
    stale = touch(tmp_path / "snapshot-old" / "sh" / "600001.parquet", 2)
    orphan = touch(tmp_path / "snapshot-old" / "sh" / "603124.parquet", 2)

    result = classify_artifacts(
        [old, current, stale, orphan],
        {
            ("sh", "600000"): "snapshot-new",
            ("sh", "600001"): "snapshot-new",
            ("sh", "600002"): "snapshot-new",
        },
    )

    assert result.current_paths == {("sh", "600000"): current}
    assert result.stale_paths == {("sh", "600001"): stale}
    assert result.missing_keys == {("sh", "600002")}
    assert result.orphan_paths == [orphan]
    assert result.superseded_paths == [old]


def test_uses_latest_artifact_when_no_manifest_is_available(tmp_path):
    old = touch(tmp_path / "snapshot-old" / "sh" / "600000.parquet", 1)
    latest = touch(tmp_path / "snapshot-new" / "sh" / "600000.parquet", 2)

    result = classify_artifacts([old, latest], {})

    assert result.current_paths == {("sh", "600000"): latest}
    assert result.superseded_paths == [old]
