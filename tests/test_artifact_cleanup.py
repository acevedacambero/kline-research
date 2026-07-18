from pathlib import Path

import pytest

from kline.data.artifact_cleanup import ArtifactCleanupService


def write(path: Path, value: bytes = b"artifact") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return path


def service(root: Path) -> ArtifactCleanupService:
    return ArtifactCleanupService(
        root,
        {("sh", "600000"): "snapshot-new", ("sh", "600001"): "snapshot-new"},
        feature_version="daily-features-v1",
        score_version="p3-rule-score-v1",
    )


def test_plan_removes_only_orphans_and_artifacts_with_current_replacements(tmp_path):
    root = tmp_path / "data"
    foundation = root / "data-foundation-v1"
    current = write(foundation / "labels/snapshot-new/sh/600000.parquet", b"current")
    old = write(foundation / "labels/snapshot-old/sh/600000.parquet", b"old")
    old_manifest = write(
        foundation / "labels/snapshot-old/sh/600000.manifest.json", b"{}"
    )
    stale_only = write(foundation / "labels/snapshot-old/sh/600001.parquet", b"stale")
    orphan = write(foundation / "labels/snapshot-old/sh/603124.parquet", b"orphan")
    orphan_manifest = write(
        foundation / "scores/p3-rule-score-v1/snapshot-old__f__r__v/sh/603125.manifest.json",
        b"{}",
    )
    current_feature = write(
        foundation
        / "features/daily-features-v1/snapshot-new__factor__rule/sh/600000.parquet",
        b"current-feature",
    )
    old_feature = write(
        foundation
        / "features/old-feature-version/snapshot-new__factor__rule/sh/600000.parquet",
        b"old-feature",
    )

    plan = service(root).plan()
    planned = {item.path: item.reason for item in plan.files}

    assert str(old.relative_to(root)).replace("\\", "/") in planned
    assert str(old_manifest.relative_to(root)).replace("\\", "/") in planned
    assert str(orphan.relative_to(root)).replace("\\", "/") in planned
    assert str(old_feature.relative_to(root)).replace("\\", "/") in planned
    assert str(orphan_manifest.relative_to(root)).replace("\\", "/") in planned
    assert str(current.relative_to(root)).replace("\\", "/") not in planned
    assert str(current_feature.relative_to(root)).replace("\\", "/") not in planned
    assert str(stale_only.relative_to(root)).replace("\\", "/") not in planned
    assert set(planned.values()) == {
        "orphan-manifest",
        "orphan-security",
        "superseded",
    }


def test_execute_quarantines_exact_plan_and_preserves_current_files(tmp_path):
    root = tmp_path / "data"
    foundation = root / "data-foundation-v1"
    current = write(foundation / "scores/p3-rule-score-v1/snapshot-new__f__r__v/sh/600000.parquet")
    old = write(foundation / "scores/p3-rule-score-v1/snapshot-old__f__r__v/sh/600000.parquet")
    cleanup = service(root)
    plan = cleanup.plan()

    receipt = cleanup.execute(plan, "quarantine")

    assert receipt["status"] == "completed"
    assert receipt["releasedBytes"] == 0
    assert current.exists()
    assert not old.exists()
    destination = Path(receipt["quarantinePath"]) / old.relative_to(root)
    assert destination.read_bytes() == b"artifact"


def test_execute_delete_releases_bytes_and_rejects_changed_plan(tmp_path):
    root = tmp_path / "data"
    orphan = write(
        root / "data-foundation-v1/features/daily-features-v1/snapshot-old__f__r/sh/603124.parquet"
    )
    cleanup = service(root)
    plan = cleanup.plan()
    orphan.write_bytes(b"changed")

    with pytest.raises(ValueError, match="stale or tampered"):
        cleanup.execute(plan, "delete")

    plan = cleanup.plan()
    receipt = cleanup.execute(plan, "delete")
    assert receipt["releasedBytes"] == len(b"changed")
    assert not orphan.exists()


def test_quarantine_execution_can_resume_after_partial_move(tmp_path):
    root = tmp_path / "data"
    first = write(
        root / "data-foundation-v1/labels/snapshot-old/sh/603124.parquet", b"first"
    )
    second = write(
        root / "data-foundation-v1/labels/snapshot-old/sh/603125.parquet", b"second"
    )
    cleanup = service(root)
    plan = cleanup.plan()
    destination = (
        root
        / "data-foundation-v1/quarantine/artifact-lineage"
        / plan.plan_id
        / first.relative_to(root)
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    first.replace(destination)

    receipt = cleanup.execute(plan, "quarantine")

    statuses = {item["path"]: item["status"] for item in receipt["entries"]}
    first_key = str(first.relative_to(root)).replace("\\", "/")
    second_key = str(second.relative_to(root)).replace("\\", "/")
    assert statuses[first_key] == "already_quarantined"
    assert statuses[second_key] == "quarantined"
    assert not second.exists()
