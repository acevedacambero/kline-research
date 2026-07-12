from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from kline.storage import atomic_write_text


MODEL_REGISTRY_VERSION = "p7-model-registry-v1"


class ModelRegistry:
    def __init__(self, output_root: Path):
        self.root = Path(output_root) / "data-foundation-v1" / "models"

    def save(
        self,
        kind: str,
        result: dict[str, Any],
        *,
        dependencies: dict[str, Any],
    ) -> dict[str, Any]:
        identity_payload = {
            "registryVersion": MODEL_REGISTRY_VERSION,
            "kind": kind,
            "result": result,
            "dependencies": dependencies,
        }
        encoded = json.dumps(
            identity_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        model_id = hashlib.sha256(encoded).hexdigest()[:24]
        path = self.root / kind / f"{model_id}.json"
        artifact = {
            **identity_payload,
            "modelId": model_id,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        atomic_write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, default=str), path
        )
        return {"modelId": model_id, "artifactPath": str(path)}

    def list(self) -> dict[str, Any]:
        artifacts = []
        unreadable = []
        for path in sorted(self.root.glob("*/*.json")):
            try:
                artifact = json.loads(path.read_text(encoding="utf-8"))
                artifacts.append({
                    "modelId": artifact["modelId"],
                    "kind": artifact["kind"],
                    "createdAt": artifact["createdAt"],
                    "version": artifact["result"].get("version"),
                    "status": artifact["result"].get("status"),
                    "labelColumn": artifact["result"].get("labelColumn"),
                    "artifactPath": str(path),
                    "dependencies": artifact.get("dependencies", {}),
                })
            except (OSError, ValueError, KeyError, TypeError) as exc:
                unreadable.append(f"{path.name}: {exc}")
        artifacts.sort(key=lambda item: item["createdAt"], reverse=True)
        return {
            "version": MODEL_REGISTRY_VERSION,
            "artifacts": artifacts,
            "unreadableFiles": len(unreadable),
            "unreadableExamples": unreadable[:20],
        }
