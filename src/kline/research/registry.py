from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from ..storage import atomic_write_text


RESEARCH_RUN_REGISTRY_VERSION = "research-run-registry-v1"
_SAFE_ID = re.compile(r"^[0-9a-f]{32}$")


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "version", "status", "labelColumn", "asOfDate", "sampleCount", "scannedCount",
        "trainCount", "testCount", "averageAuc", "averageAccuracy", "annualizedReturn",
        "sharpe", "maxDrawdown", "expectedCalibrationError", "brierScore", "logLoss",
    )
    summary = {key: result[key] for key in keys if key in result}
    quality = result.get("quality")
    if isinstance(quality, dict):
        for key in ("expectedCalibrationError", "brierScore", "logLoss"):
            if key in quality:
                summary[key] = quality[key]
    metrics = result.get("metrics")
    if isinstance(metrics, dict):
        for key in ("annualizedReturn", "sharpe", "calmar", "maxDrawdown"):
            if key in metrics:
                summary[key] = metrics[key]
    return summary


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    output = {}
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            output.update(_flatten(child, path))
    elif isinstance(value, (str, int, float, bool)) or value is None:
        output[prefix] = value
    return output


class ResearchRunRegistry:
    def __init__(self, output_root: Path):
        self.root = Path(output_root) / "data-foundation-v1" / "research-runs"

    def save(
        self,
        kind: str,
        result: dict[str, Any],
        *,
        parameters: dict[str, Any],
        dependencies: dict[str, Any],
        data_snapshot: dict[str, Any],
        code_version: str,
    ) -> dict[str, Any]:
        run_id = uuid4().hex
        path = self.root / kind / f"{run_id}.json"
        artifact = {
            "registryVersion": RESEARCH_RUN_REGISTRY_VERSION,
            "runId": run_id,
            "kind": kind,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "codeVersion": code_version,
            "parameters": parameters,
            "dependencies": dependencies,
            "dataSnapshot": data_snapshot,
            "summary": _summary(result),
            "result": result,
        }
        atomic_write_text(json.dumps(artifact, ensure_ascii=False, indent=2, default=str), path)
        return {"runId": run_id, "artifactPath": str(path)}

    def get(self, run_id: str) -> dict[str, Any] | None:
        if not _SAFE_ID.fullmatch(run_id):
            return None
        matches = list(self.root.glob(f"*/{run_id}.json"))
        if len(matches) != 1:
            return None
        try:
            return json.loads(matches[0].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def list(self, *, kind: str | None = None, limit: int = 100) -> dict[str, Any]:
        pattern = f"{kind}/*.json" if kind else "*/*.json"
        artifacts, unreadable = [], []
        for path in self.root.glob(pattern):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                artifacts.append({key: item.get(key) for key in (
                    "runId", "kind", "createdAt", "codeVersion", "parameters",
                    "dependencies", "dataSnapshot", "summary",
                )})
            except (OSError, ValueError, TypeError) as exc:
                unreadable.append(f"{path.name}: {exc}")
        artifacts.sort(key=lambda item: str(item.get("createdAt", "")), reverse=True)
        return {
            "version": RESEARCH_RUN_REGISTRY_VERSION,
            "runs": artifacts[: max(1, min(limit, 500))],
            "total": len(artifacts),
            "unreadableFiles": len(unreadable),
            "unreadableExamples": unreadable[:20],
        }

    def compare(self, left_id: str, right_id: str) -> dict[str, Any] | None:
        left, right = self.get(left_id), self.get(right_id)
        if left is None or right is None or left.get("kind") != right.get("kind"):
            return None
        left_values, right_values = _flatten(left.get("summary", {})), _flatten(right.get("summary", {}))
        left_parameters = _flatten(left.get("parameters", {}))
        right_parameters = _flatten(right.get("parameters", {}))
        metrics = []
        for key in sorted(set(left_values) | set(right_values)):
            a, b = left_values.get(key), right_values.get(key)
            delta = b - a if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None
            metrics.append({"metric": key, "left": a, "right": b, "delta": delta})
        return {
            "kind": left["kind"],
            "left": {"runId": left_id, "createdAt": left["createdAt"]},
            "right": {"runId": right_id, "createdAt": right["createdAt"]},
            "parameterChanges": [
                {"parameter": key, "left": left_parameters.get(key), "right": right_parameters.get(key)}
                for key in sorted(set(left_parameters) | set(right_parameters))
                if right_parameters.get(key) != left_parameters.get(key)
            ],
            "metrics": metrics,
        }
