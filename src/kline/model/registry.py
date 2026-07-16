from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from kline.storage import atomic_write_text


MODEL_REGISTRY_VERSION = "p7-model-registry-v1"
MODEL_ACTIVATION_VERSION = "p7-model-activation-v1"
_SAFE_MODEL_ID = re.compile(r"^[0-9a-f]{24}$")


class ModelPromotionError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ModelRegistry:
    def __init__(self, output_root: Path):
        self.root = Path(output_root) / "data-foundation-v1" / "models"
        self.activation_path = self.root / "active-models.json"

    def _read_activation(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.activation_path.read_text(encoding="utf-8"))
            if payload.get("version") != MODEL_ACTIVATION_VERSION:
                raise ValueError("activation version mismatch")
            payload.setdefault("activeModels", {})
            payload.setdefault("history", [])
            return payload
        except FileNotFoundError:
            return {
                "version": MODEL_ACTIVATION_VERSION,
                "activeModels": {},
                "history": [],
            }
        except (OSError, ValueError, TypeError) as exc:
            raise ModelPromotionError(
                "MODEL_ACTIVATION_UNREADABLE", f"当前模型状态不可读取：{exc}"
            ) from exc

    def get(self, model_id: str) -> dict[str, Any] | None:
        if not _SAFE_MODEL_ID.fullmatch(model_id):
            return None
        matches = list(self.root.glob(f"*/{model_id}.json"))
        if len(matches) != 1:
            return None
        try:
            return json.loads(matches[0].read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None

    def promote(
        self,
        model_id: str,
        *,
        expected_dependencies: dict[str, str],
    ) -> dict[str, Any]:
        artifact = self.get(model_id)
        if artifact is None:
            raise ModelPromotionError("MODEL_NOT_FOUND", "模型不存在或产物不可读取")
        result = artifact.get("result", {})
        if result.get("status") != "trained":
            raise ModelPromotionError("MODEL_NOT_PROMOTABLE", "只有训练通过的模型可以设为当前模型")
        dependencies = artifact.get("dependencies", {})
        required_keys = {"scoreDefinitionVersion", "labelDefinitionVersion"}
        if artifact.get("kind") == "multifeature":
            required_keys.add("featureDefinitionVersion")
        mismatches = {
            key: {"expected": expected, "actual": dependencies.get(key)}
            for key, expected in expected_dependencies.items()
            if key in required_keys and dependencies.get(key) != expected
        }
        if mismatches:
            raise ModelPromotionError(
                "MODEL_DEPENDENCY_MISMATCH",
                f"模型依赖版本已过期：{', '.join(sorted(mismatches))}",
            )

        activation = self._read_activation()
        kind = artifact["kind"]
        previous = activation["activeModels"].get(kind)
        promoted_at = datetime.now(timezone.utc).isoformat()
        active = {
            "modelId": model_id,
            "kind": kind,
            "promotedAt": promoted_at,
            "previousModelId": previous.get("modelId") if isinstance(previous, dict) else None,
        }
        activation["activeModels"][kind] = active
        activation["history"].append(active)
        atomic_write_text(
            json.dumps(activation, ensure_ascii=False, indent=2), self.activation_path
        )
        return active

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
        activation = self._read_activation()
        active_ids = {
            item.get("modelId")
            for item in activation["activeModels"].values()
            if isinstance(item, dict)
        }
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
                    "active": artifact["modelId"] in active_ids,
                })
            except (OSError, ValueError, KeyError, TypeError) as exc:
                unreadable.append(f"{path.name}: {exc}")
        artifacts.sort(key=lambda item: item["createdAt"], reverse=True)
        return {
            "version": MODEL_REGISTRY_VERSION,
            "activationVersion": MODEL_ACTIVATION_VERSION,
            "activeModels": activation["activeModels"],
            "artifacts": artifacts,
            "unreadableFiles": len(unreadable),
            "unreadableExamples": unreadable[:20],
        }
