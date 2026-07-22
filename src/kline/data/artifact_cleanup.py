from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Literal, Mapping

from kline.artifact_lineage import artifact_security_key, artifact_snapshot_version


CleanupMode = Literal["quarantine", "delete"]
_SNAPSHOT_VERSION = re.compile(r"^snapshot-[0-9a-f]{16}$")


def referenced_snapshot_versions(data_root: Path) -> set[str]:
    """Return snapshot versions explicitly referenced by research/model artifacts."""
    foundation = Path(data_root) / "data-foundation-v1"
    versions: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str) and _SNAPSHOT_VERSION.fullmatch(value):
            versions.add(value)

    for root_name in ("research-runs", "models"):
        for path in foundation.glob(f"{root_name}/**/*.json"):
            try:
                raw = path.read_text(encoding="utf-8")
                visit(json.loads(raw))
            except (OSError, ValueError, TypeError):
                # Preserve any explicit version still recoverable from a malformed entry.
                try:
                    versions.update(re.findall(r"snapshot-[0-9a-f]{16}", raw))
                except (OSError, UnboundLocalError):
                    continue
    return versions


@dataclass(frozen=True)
class ArtifactCleanupEntry:
    path: str
    layer: str
    reason: str
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class ArtifactCleanupPlan:
    version: str
    plan_id: str
    data_root: str
    snapshot_set_hash: str
    files: tuple[ArtifactCleanupEntry, ...]
    total_bytes: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ArtifactCleanupPlan:
        return cls(
            version=value["version"],
            plan_id=value["plan_id"],
            data_root=value["data_root"],
            snapshot_set_hash=value["snapshot_set_hash"],
            files=tuple(ArtifactCleanupEntry(**item) for item in value["files"]),
            total_bytes=int(value["total_bytes"]),
            created_at=value["created_at"],
        )


class ArtifactCleanupService:
    VERSION = "artifact-cleanup-v2"

    def __init__(
        self,
        data_root: Path,
        current_snapshots: Mapping[tuple[str, str], str],
        *,
        feature_version: str,
        score_version: str,
        protected_snapshot_versions: set[str] | None = None,
    ) -> None:
        self.root = Path(data_root).resolve()
        self.foundation = self.root / "data-foundation-v1"
        self.current_snapshots = dict(current_snapshots)
        self.feature_version = feature_version
        self.score_version = score_version
        self.protected_snapshot_versions = set(protected_snapshot_versions or ())

    def plan(self) -> ArtifactCleanupPlan:
        candidates: dict[Path, tuple[str, str]] = {}
        self._collect_snapshots(candidates)
        self._collect_layer(
            "labels",
            self.foundation.glob("labels/*/*/*.parquet"),
            candidates,
        )
        self._collect_layer(
            "features",
            self.foundation.glob("features/*/*/*/*.parquet"),
            candidates,
        )
        self._collect_layer(
            "scores",
            self.foundation.glob("scores/*/*/*/*.parquet"),
            candidates,
        )
        for layer, pattern in (
            ("features", "features/*/*/*/*.manifest.json"),
            ("scores", "scores/*/*/*/*.manifest.json"),
            ("labels", "labels/*/*/*.manifest.json"),
        ):
            for manifest in self.foundation.glob(pattern):
                parquet = manifest.with_name(
                    manifest.name.removesuffix(".manifest.json") + ".parquet"
                )
                if not parquet.exists():
                    candidates[manifest.resolve()] = (layer, "orphan-manifest")
        entries = []
        for path, (layer, reason) in sorted(candidates.items(), key=lambda item: str(item[0])):
            related = (
                (path,)
                if path.name.endswith(".manifest.json")
                else (path, path.with_suffix(".manifest.json"))
            )
            for candidate in related:
                if not candidate.exists():
                    continue
                safe = self._safe_path(candidate)
                stat = safe.stat()
                entries.append(
                    ArtifactCleanupEntry(
                        path=str(safe.relative_to(self.root)).replace("\\", "/"),
                        layer=layer,
                        reason=reason,
                        size=stat.st_size,
                        mtime_ns=stat.st_mtime_ns,
                    )
                )
        snapshot_set_hash = self._snapshot_set_hash()
        plan_id = self._plan_id(snapshot_set_hash, entries)
        return ArtifactCleanupPlan(
            version=self.VERSION,
            plan_id=plan_id,
            data_root=str(self.root),
            snapshot_set_hash=snapshot_set_hash,
            files=tuple(entries),
            total_bytes=sum(entry.size for entry in entries),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def _collect_snapshots(
        self,
        candidates: dict[Path, tuple[str, str]],
    ) -> None:
        """Collect obsolete raw/factor/derived files only when a current replacement exists."""
        for derived in self.foundation.glob("snapshots/*/derived/*/*.parquet"):
            version = derived.parents[2].name
            key = (derived.parent.name, derived.stem)
            current_version = self.current_snapshots.get(key)
            if (
                not current_version
                or version == current_version
                or version in self.protected_snapshot_versions
            ):
                continue
            replacement = (
                self.foundation
                / "snapshots"
                / current_version
                / "derived"
                / key[0]
                / f"{key[1]}.parquet"
            )
            if not replacement.exists():
                continue
            snapshot_root = self.foundation / "snapshots" / version
            for candidate in (
                derived,
                snapshot_root / "facts" / "raw_bars" / key[0] / f"{key[1]}.parquet",
                snapshot_root
                / "facts"
                / "adjustment_factors"
                / key[0]
                / f"{key[1]}.parquet",
            ):
                if candidate.exists():
                    candidates[candidate.resolve()] = ("snapshots", "superseded-snapshot")

    def execute(
        self,
        plan: ArtifactCleanupPlan,
        mode: CleanupMode,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if mode not in {"quarantine", "delete"}:
            raise ValueError("cleanup mode must be quarantine or delete")
        self._validate_plan(plan)
        current = self.plan()
        planned_entries = {item.path: item for item in plan.files}
        if any(planned_entries.get(item.path) != item for item in current.files):
            raise ValueError("stale or tampered artifact cleanup plan")
        quarantine_root = (
            self.foundation / "quarantine" / "artifact-lineage" / plan.plan_id
        )
        entries = []
        released_bytes = 0
        processed_bytes = 0
        for index, item in enumerate(plan.files, start=1):
            source = self._safe_path(self.root / item.path)
            if not source.exists():
                destination = quarantine_root / item.path
                already_processed = mode == "quarantine" and destination.exists()
                status = "already_quarantined" if already_processed else "missing"
                entries.append({"path": item.path, "status": status, "bytes": 0})
                if on_progress:
                    on_progress(
                        {
                            "done": index,
                            "total": len(plan.files),
                            "currentPath": item.path,
                            "processedBytes": processed_bytes,
                            "totalBytes": plan.total_bytes,
                            "mode": mode,
                        }
                    )
                continue
            stat = source.stat()
            if stat.st_size != item.size or stat.st_mtime_ns != item.mtime_ns:
                raise ValueError(f"stale or tampered artifact cleanup plan: {item.path}")
            if mode == "delete":
                source.unlink()
                released_bytes += item.size
                status = "deleted"
            else:
                destination = quarantine_root / item.path
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    raise ValueError(f"quarantine destination already exists: {item.path}")
                os.replace(source, destination)
                status = "quarantined"
            self._prune_empty_parents(source.parent)
            entries.append({"path": item.path, "status": status, "bytes": item.size})
            processed_bytes += item.size
            if on_progress:
                on_progress(
                    {
                        "done": index,
                        "total": len(plan.files),
                        "currentPath": item.path,
                        "processedBytes": processed_bytes,
                        "totalBytes": plan.total_bytes,
                        "mode": mode,
                    }
                )
        return {
            "version": self.VERSION,
            "planId": plan.plan_id,
            "mode": mode,
            "status": "completed",
            "files": len(plan.files),
            "processedBytes": sum(item.size for item in plan.files),
            "releasedBytes": released_bytes,
            "quarantinePath": str(quarantine_root) if mode == "quarantine" else None,
            "entries": entries,
            "completedAt": datetime.now(timezone.utc).isoformat(),
        }

    def _collect_layer(
        self,
        layer: str,
        paths,
        candidates: dict[Path, tuple[str, str]],
    ) -> None:
        grouped: dict[tuple[str, str], list[Path]] = {}
        for path in paths:
            grouped.setdefault(artifact_security_key(path), []).append(path.resolve())
        for key, artifacts in grouped.items():
            if key not in self.current_snapshots:
                for path in artifacts:
                    candidates[path] = (layer, "orphan-security")
                continue
            usable = [path for path in artifacts if self._is_current(layer, key, path)]
            if not usable:
                continue
            keep = max(usable, key=lambda path: path.stat().st_mtime_ns)
            for path in artifacts:
                if (
                    path != keep
                    and artifact_snapshot_version(path)
                    not in self.protected_snapshot_versions
                ):
                    candidates[path] = (layer, "superseded")

    def _is_current(self, layer: str, key: tuple[str, str], path: Path) -> bool:
        if artifact_snapshot_version(path) != self.current_snapshots[key]:
            return False
        if layer == "features":
            return path.parents[2].name == self.feature_version
        if layer == "scores":
            return path.parents[2].name == self.score_version
        return True

    def _snapshot_set_hash(self) -> str:
        payload = "\n".join(
            f"{exchange}:{code}:{snapshot}"
            for (exchange, code), snapshot in sorted(self.current_snapshots.items())
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:24]

    def _plan_id(self, snapshot_set_hash: str, entries: list[ArtifactCleanupEntry]) -> str:
        payload = {
            "version": self.VERSION,
            "dataRoot": str(self.root),
            "snapshotSetHash": snapshot_set_hash,
            "files": [asdict(item) for item in entries],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _validate_plan(self, plan: ArtifactCleanupPlan) -> None:
        if (
            plan.version != self.VERSION
            or Path(plan.data_root).resolve() != self.root
            or plan.snapshot_set_hash != self._snapshot_set_hash()
        ):
            raise ValueError("stale or tampered artifact cleanup plan")
        expected = self._plan_id(plan.snapshot_set_hash, list(plan.files))
        if expected != plan.plan_id:
            raise ValueError("stale or tampered artifact cleanup plan")
        for item in plan.files:
            self._safe_path(self.root / item.path)

    def _safe_path(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.foundation) or resolved == self.foundation:
            raise ValueError(f"path outside data foundation: {resolved}")
        return resolved

    def _prune_empty_parents(self, start: Path) -> None:
        current = start
        protected = {self.root, self.foundation}
        while current.is_relative_to(self.foundation) and current not in protected:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
