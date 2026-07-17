from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


SecurityKey = tuple[str, str]


@dataclass(frozen=True)
class ArtifactLineage:
    current_paths: dict[SecurityKey, Path]
    stale_paths: dict[SecurityKey, Path]
    missing_keys: set[SecurityKey]
    orphan_paths: list[Path]
    superseded_paths: list[Path]


def artifact_security_key(path: Path) -> SecurityKey:
    return path.parent.name, path.stem


def artifact_snapshot_version(path: Path) -> str:
    """Return the data snapshot encoded by P1, P2, and P3 artifact paths."""
    return path.parents[1].name.split("__", 1)[0]


def classify_artifacts(
    paths: Iterable[Path],
    current_snapshots: Mapping[SecurityKey, str],
) -> ArtifactLineage:
    paths = list(paths)
    if not current_snapshots:
        latest: dict[SecurityKey, Path] = {}
        superseded: list[Path] = []
        grouped: dict[SecurityKey, list[Path]] = {}
        for path in paths:
            grouped.setdefault(artifact_security_key(path), []).append(path)
        for key, candidates in grouped.items():
            ordered = sorted(candidates, key=lambda item: item.stat().st_mtime)
            latest[key] = ordered[-1]
            superseded.extend(ordered[:-1])
        return ArtifactLineage(latest, {}, set(), [], superseded)

    grouped: dict[SecurityKey, list[Path]] = {}
    orphan_paths: list[Path] = []
    for path in paths:
        key = artifact_security_key(path)
        if key not in current_snapshots:
            orphan_paths.append(path)
            continue
        grouped.setdefault(key, []).append(path)

    current_paths: dict[SecurityKey, Path] = {}
    stale_paths: dict[SecurityKey, Path] = {}
    superseded_paths: list[Path] = []
    for key, candidates in grouped.items():
        ordered = sorted(candidates, key=lambda item: item.stat().st_mtime)
        matching = [
            path
            for path in ordered
            if artifact_snapshot_version(path) == current_snapshots[key]
        ]
        if matching:
            current_paths[key] = matching[-1]
            superseded_paths.extend(path for path in ordered if path != matching[-1])
        else:
            stale_paths[key] = ordered[-1]
            superseded_paths.extend(ordered[:-1])

    return ArtifactLineage(
        current_paths=current_paths,
        stale_paths=stale_paths,
        missing_keys=set(current_snapshots) - set(grouped),
        orphan_paths=orphan_paths,
        superseded_paths=superseded_paths,
    )
