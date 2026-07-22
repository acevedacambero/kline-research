from __future__ import annotations

import argparse
import json
from pathlib import Path

from kline.config import VERSIONS
from kline.data.artifact_cleanup import (
    ArtifactCleanupService,
    referenced_snapshot_versions,
)
from kline.data.pipeline import DatasetPipeline
from kline.storage import atomic_write_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan and optionally delete superseded K-line artifacts."
    )
    parser.add_argument("--data-path", type=Path, required=True)
    parser.add_argument("--plan-output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--receipt-output", type=Path)
    parser.add_argument("--memory-limit", default="2GB")
    parser.add_argument("--threads", type=int, default=2)
    return parser.parse_args()


def summarize(plan) -> dict:
    layers: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for item in plan.files:
        layers[item.layer] = layers.get(item.layer, 0) + 1
        reasons[item.reason] = reasons.get(item.reason, 0) + 1
    return {
        "version": plan.version,
        "planId": plan.plan_id,
        "fileCount": len(plan.files),
        "totalBytes": plan.total_bytes,
        "layers": layers,
        "reasons": reasons,
        "protectedSnapshotVersions": len(referenced_snapshot_versions(Path(plan.data_root))),
    }


def main() -> int:
    args = parse_args()
    pipeline = DatasetPipeline(
        args.data_path,
        memory_limit=args.memory_limit,
        threads=args.threads,
    )
    current = {
        (item["exchange"], item["code"]): item["snapshot_version"]
        for item in pipeline.cached_securities()
    }
    service = ArtifactCleanupService(
        args.data_path,
        current,
        feature_version=VERSIONS["featureDefinitionVersion"],
        score_version=VERSIONS["scoreDefinitionVersion"],
        protected_snapshot_versions=referenced_snapshot_versions(args.data_path),
    )
    plan = service.plan()
    atomic_write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), args.plan_output
    )
    result: dict = {"status": "planned", "plan": summarize(plan)}
    if args.execute:
        if args.receipt_output is None:
            raise SystemExit("--receipt-output is required with --execute")
        receipt = service.execute(plan, "delete")
        atomic_write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2), args.receipt_output
        )
        result.update(
            status="completed",
            releasedBytes=receipt["releasedBytes"],
            deletedFiles=receipt["files"],
        )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
