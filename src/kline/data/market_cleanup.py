from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from .pipeline import DatasetPipeline


@dataclass(frozen=True)
class CleanupFile:
    path: str
    size: int
    sha256: str
    action: str
    source: str


@dataclass(frozen=True)
class CleanupPlan:
    plan_id: str
    exchange: str
    data_root: str
    dataset_keys: tuple[str, ...]
    security_master_rows: int
    files: tuple[CleanupFile, ...]
    delete_bytes: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> CleanupPlan:
        return cls(
            plan_id=value["plan_id"],
            exchange=value["exchange"],
            data_root=value["data_root"],
            dataset_keys=tuple(value["dataset_keys"]),
            security_master_rows=int(value["security_master_rows"]),
            files=tuple(CleanupFile(**item) for item in value["files"]),
            delete_bytes=int(value["delete_bytes"]),
            created_at=value["created_at"],
        )


@dataclass(frozen=True)
class CleanupReceiptEntry:
    path: str
    status: str
    bytes: int = 0


@dataclass(frozen=True)
class CleanupReceipt:
    plan_id: str
    status: str
    deleted_dataset_rows: int
    deleted_security_master_rows: int
    entries: tuple[CleanupReceiptEntry, ...]
    completed_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MarketCleanup:
    def __init__(self, pipeline: DatasetPipeline) -> None:
        self.pipeline = pipeline
        self.root = pipeline.output_root.resolve()

    def plan_cleanup(self, exchange: str) -> CleanupPlan:
        if exchange != "bj":
            raise ValueError("cleanup requires exact exchange 'bj'")
        with self.pipeline.connection() as connection:
            rows = connection.execute(
                """select dataset_key, raw_path, factor_path, derived_path
                from dataset_manifest where dataset_key like 'stock:bj:%'
                order by dataset_key"""
            ).fetchall()
            other_paths = {
                str(Path(path).resolve())
                for row in connection.execute(
                    """select raw_path, factor_path, derived_path from dataset_manifest
                    where dataset_key not like 'stock:bj:%'"""
                ).fetchall()
                for path in row
                if path
            }

        candidates: dict[str, tuple[str, str]] = {}
        for dataset_key, raw_path, factor_path, derived_path in rows:
            for field, path in (
                ("raw_path", raw_path),
                ("factor_path", factor_path),
                ("derived_path", derived_path),
            ):
                if path:
                    candidates[str(Path(path).resolve())] = (field, dataset_key)
        foundation = self.root / "data-foundation-v1"
        for pattern, source in (
            ("labels/*/bj/*.parquet", "label"),
            ("features/*/*/bj/*.parquet", "feature"),
            ("features/*/*/bj/*.manifest.json", "feature_manifest"),
            ("scores/*/*/bj/*.parquet", "score"),
            ("scores/*/*/bj/*.manifest.json", "score_manifest"),
        ):
            for path in foundation.glob(pattern):
                candidates[str(path.resolve())] = (source, "exchange-file")

        files: list[CleanupFile] = []
        for path_text, (source, _owner) in sorted(candidates.items()):
            path = self._safe_path(path_text)
            action = "skip_shared" if path_text in other_paths else "delete"
            size, digest = self._fingerprint(path)
            files.append(CleanupFile(path_text, size, digest, action, source))
        master = self.pipeline.load_security_master()
        master_rows = sum(item.get("exchange") == "bj" for item in master)
        keys = tuple(row[0] for row in rows)
        plan_id = self._plan_id("bj", keys, master_rows, files)
        return CleanupPlan(
            plan_id=plan_id,
            exchange="bj",
            data_root=str(self.root),
            dataset_keys=keys,
            security_master_rows=master_rows,
            files=tuple(files),
            delete_bytes=sum(item.size for item in files if item.action == "delete"),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def execute(self, plan: CleanupPlan) -> CleanupReceipt:
        self._validate_plan(plan)
        current_keys = self._current_keys()
        master = self.pipeline.load_security_master()
        current_master_rows = sum(item.get("exchange") == "bj" for item in master)
        delete_entries = [entry for entry in plan.files if entry.action == "delete"]
        existing_targets = [entry for entry in delete_entries if Path(entry.path).exists()]
        already_clean = not current_keys and current_master_rows == 0 and not existing_targets

        entries: list[CleanupReceiptEntry] = []
        for entry in plan.files:
            path = self._safe_path(entry.path)
            if entry.action == "skip_shared":
                entries.append(CleanupReceiptEntry(entry.path, "skipped_shared"))
                continue
            if not path.exists():
                entries.append(CleanupReceiptEntry(entry.path, "missing"))
                continue
            size, digest = self._fingerprint(path)
            if size != entry.size or digest != entry.sha256:
                raise ValueError(f"stale or tampered cleanup plan: {entry.path}")

        if already_clean:
            return CleanupReceipt(
                plan.plan_id, "already_clean", 0, 0, tuple(entries),
                datetime.now(timezone.utc).isoformat(),
            )
        if set(current_keys) != set(plan.dataset_keys) or current_master_rows != plan.security_master_rows:
            raise ValueError("stale or tampered cleanup plan: metadata changed")

        remaining_master = [item for item in master if item.get("exchange") != "bj"]
        self._replace_security_master(remaining_master)
        with self.pipeline.connection() as connection:
            connection.execute("begin transaction")
            try:
                connection.execute(
                    "delete from data_quality_events where dataset_key like 'stock:bj:%'"
                )
                connection.execute(
                    "delete from dataset_manifest where dataset_key like 'stock:bj:%'"
                )
                connection.execute("commit")
            except Exception:
                connection.execute("rollback")
                raise

        final_entries: list[CleanupReceiptEntry] = []
        for entry in plan.files:
            path = self._safe_path(entry.path)
            if entry.action == "skip_shared":
                final_entries.append(CleanupReceiptEntry(entry.path, "skipped_shared"))
            elif path.exists():
                size = path.stat().st_size
                path.unlink()
                self._prune_empty_parents(path.parent)
                final_entries.append(CleanupReceiptEntry(entry.path, "deleted", size))
            else:
                final_entries.append(CleanupReceiptEntry(entry.path, "missing"))
        return CleanupReceipt(
            plan.plan_id,
            "completed",
            len(plan.dataset_keys),
            plan.security_master_rows,
            tuple(final_entries),
            datetime.now(timezone.utc).isoformat(),
        )

    def _validate_plan(self, plan: CleanupPlan) -> None:
        if plan.exchange != "bj" or Path(plan.data_root).resolve() != self.root:
            raise ValueError("stale or tampered cleanup plan")
        for entry in plan.files:
            self._safe_path(entry.path)
        expected = self._plan_id(
            plan.exchange, plan.dataset_keys, plan.security_master_rows, list(plan.files)
        )
        if expected != plan.plan_id:
            raise ValueError("stale or tampered cleanup plan")

    def _current_keys(self) -> tuple[str, ...]:
        with self.pipeline.connection() as connection:
            rows = connection.execute(
                "select dataset_key from dataset_manifest where dataset_key like 'stock:bj:%'"
                " order by dataset_key"
            ).fetchall()
        return tuple(row[0] for row in rows)

    def _safe_path(self, value: str | Path) -> Path:
        path = Path(value).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError(f"path outside data root: {path}")
        return path

    @staticmethod
    def _fingerprint(path: Path) -> tuple[int, str]:
        if not path.exists():
            return 0, "missing"
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return path.stat().st_size, digest.hexdigest()

    @staticmethod
    def _plan_id(
        exchange: str,
        keys: tuple[str, ...],
        master_rows: int,
        files: list[CleanupFile],
    ) -> str:
        payload = {
            "exchange": exchange,
            "dataset_keys": keys,
            "security_master_rows": master_rows,
            "files": [asdict(item) for item in files],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _replace_security_master(self, rows: list[dict[str, Any]]) -> None:
        target = self.pipeline.security_master_path
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(target.name + ".tmp.parquet")
        columns = list(pd.read_parquet(target).columns) if target.exists() else None
        pd.DataFrame(rows, columns=columns).to_parquet(temp, index=False)
        os.replace(temp, target)

    def _prune_empty_parents(self, start: Path) -> None:
        protected = {
            self.root,
            self.root / "data-foundation-v1",
            self.root / "data-foundation-v1" / "snapshots",
        }
        current = start
        while current.is_relative_to(self.root) and current not in protected:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
