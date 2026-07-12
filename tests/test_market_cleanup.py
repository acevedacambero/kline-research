from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from kline.data.market_cleanup import MarketCleanup
from kline.data.pipeline import DatasetPipeline


def write(path: Path, value: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return path


def seeded_root(tmp_path: Path) -> tuple[DatasetPipeline, dict[str, Path]]:
    root = tmp_path / "data"
    pipeline = DatasetPipeline(root)
    pipeline.initialize_catalog()
    snapshot = root / "data-foundation-v1" / "snapshots" / "snapshot-test"
    paths = {
        "bj_raw": write(snapshot / "facts/raw_bars/bj/920001.parquet", b"bj-raw"),
        "shared": write(snapshot / "facts/adjustment_factors/shared.parquet", b"shared"),
        "bj_derived": write(snapshot / "derived/bj/920001.parquet", b"bj-derived"),
        "sh_raw": write(snapshot / "facts/raw_bars/sh/600000.parquet", b"sh-raw"),
        "sh_derived": write(snapshot / "derived/sh/600000.parquet", b"sh-derived"),
        "label": write(
            root / "data-foundation-v1/labels/snapshot-test/bj/920001.parquet",
            b"bj-label",
        ),
        "feature": write(
            root / "data-foundation-v1/features/v1/identity/bj/920001.parquet",
            b"bj-feature",
        ),
        "feature_manifest": write(
            root / "data-foundation-v1/features/v1/identity/bj/920001.manifest.json",
            b"{}",
        ),
        "score": write(
            root / "data-foundation-v1/scores/v1/identity/bj/920001.parquet",
            b"bj-score",
        ),
        "score_manifest": write(
            root / "data-foundation-v1/scores/v1/identity/bj/920001.manifest.json",
            b"{}",
        ),
    }
    with pipeline.connection() as connection:
        connection.execute(
            """insert into dataset_manifest values
            ('stock:bj:920001', 'bj-hash', 'v1', now(), ?, ?, ?, 'snapshot-test'),
            ('stock:sh:600000', 'sh-hash', 'v1', now(), ?, ?, ?, 'snapshot-test')""",
            [
                str(paths["bj_raw"]), str(paths["shared"]), str(paths["bj_derived"]),
                str(paths["sh_raw"]), str(paths["shared"]), str(paths["sh_derived"]),
            ],
        )
    pipeline.save_security_master([
        {"exchange": "sh", "code": "600000", "name": "SH"},
        {"exchange": "sz", "code": "000001", "name": "SZ"},
        {"exchange": "bj", "code": "920001", "name": "BJ"},
    ])
    return pipeline, paths


def test_dry_run_is_exact_and_does_not_mutate(tmp_path):
    pipeline, paths = seeded_root(tmp_path)
    cleanup = MarketCleanup(pipeline)
    before = {name: path.read_bytes() for name, path in paths.items()}

    plan = cleanup.plan_cleanup("bj")

    assert plan.exchange == "bj"
    assert plan.dataset_keys == ("stock:bj:920001",)
    assert plan.security_master_rows == 1
    assert {entry.path for entry in plan.files if entry.action == "delete"} == {
        str(paths[name].resolve())
        for name in (
            "bj_raw", "bj_derived", "label", "feature", "feature_manifest",
            "score", "score_manifest",
        )
    }
    shared = next(entry for entry in plan.files if entry.path == str(paths["shared"].resolve()))
    assert shared.action == "skip_shared"
    assert plan.delete_bytes == sum(
        len(before[name])
        for name in (
            "bj_raw", "bj_derived", "label", "feature", "feature_manifest",
            "score", "score_manifest",
        )
    )
    assert pipeline.cached_market_counts()["bj"] == 1
    assert pipeline.load_security_master()[-1]["exchange"] == "bj"
    assert all(path.read_bytes() == before[name] for name, path in paths.items())


@pytest.mark.parametrize("exchange", ["", "*", "all", "sh", "BJ "])
def test_cleanup_accepts_only_exact_beijing_exchange(tmp_path, exchange):
    pipeline, _ = seeded_root(tmp_path)
    with pytest.raises(ValueError, match="exact exchange 'bj'"):
        MarketCleanup(pipeline).plan_cleanup(exchange)


def test_execute_removes_only_beijing_data_and_is_idempotent(tmp_path):
    pipeline, paths = seeded_root(tmp_path)
    cleanup = MarketCleanup(pipeline)
    sh_before = {name: paths[name].read_bytes() for name in ("shared", "sh_raw", "sh_derived")}
    plan = cleanup.plan_cleanup("bj")

    receipt = cleanup.execute(plan)

    assert receipt.status == "completed"
    assert pipeline.cached_market_counts()["bj"] == 0
    assert {item["exchange"] for item in pipeline.load_security_master()} == {"sh", "sz"}
    assert all(not paths[name].exists() for name in (
        "bj_raw", "bj_derived", "label", "feature", "feature_manifest",
        "score", "score_manifest",
    ))
    assert all(paths[name].read_bytes() == value for name, value in sh_before.items())
    assert any(entry.status == "skipped_shared" for entry in receipt.entries)

    second = cleanup.execute(plan)
    assert second.status == "already_clean"
    assert all(paths[name].read_bytes() == value for name, value in sh_before.items())


def test_execute_refuses_stale_or_tampered_plan(tmp_path):
    pipeline, paths = seeded_root(tmp_path)
    cleanup = MarketCleanup(pipeline)
    plan = cleanup.plan_cleanup("bj")
    paths["bj_raw"].write_bytes(b"changed-after-plan")

    with pytest.raises(ValueError, match="stale or tampered"):
        cleanup.execute(plan)

    malicious = replace(
        plan,
        files=(replace(plan.files[0], path=str((tmp_path / "outside").resolve())),),
    )
    with pytest.raises(ValueError, match="stale or tampered|outside data root"):
        cleanup.execute(malicious)
