from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import hashlib
from pathlib import Path
import re
import threading
from typing import Iterator

import duckdb
import pandas as pd

from .adjustment import DerivedAdjustmentEngine


@dataclass(frozen=True)
class CatalogReport:
    status: str
    catalog_path: str


@dataclass(frozen=True)
class ImportReport:
    status: str
    source_path: str
    parquet_path: str | None
    normalized_path: str | None = None
    factor_path: str | None = None
    snapshot_version: str = ""


class DatasetPipeline:
    _MEMORY_LIMIT = re.compile(r"^[1-9][0-9]*(?:\.[0-9]+)?(?:KB|MB|GB|TB)$", re.I)

    def __init__(self, output_root: Path, *, memory_limit: str = "2GB", threads: int = 2):
        if not isinstance(memory_limit, str) or not self._MEMORY_LIMIT.fullmatch(memory_limit):
            raise ValueError("memory_limit must be a positive number followed by KB, MB, GB, or TB")
        if isinstance(threads, bool) or not isinstance(threads, int) or not 1 <= threads <= 1024:
            raise ValueError("threads must be an integer between 1 and 1024")
        self.output_root = Path(output_root)
        self.memory_limit = memory_limit.upper()
        self.threads = threads
        self._connection_lock = threading.RLock()
        self.catalog_path = self.output_root / "catalog.duckdb"
        self.security_master_path = (
            self.output_root / "data-foundation-v1" / "facts" / "security_master.parquet"
        )

    def _resolve_manifest_path(self, value: str) -> Path:
        path = Path(value.replace("\\", "/"))
        if path.is_absolute():
            return path
        parts = path.parts
        if "data-foundation-v1" in parts:
            offset = parts.index("data-foundation-v1")
            return self.output_root.joinpath(*parts[offset:])
        return self.output_root / path

    @contextmanager
    def connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
        with self._connection_lock:
            connection = duckdb.connect(str(self.catalog_path))
            try:
                connection.execute(f"SET memory_limit='{self.memory_limit}'")
                connection.execute(f"SET threads={self.threads}")
                yield connection
            finally:
                connection.close()

    def save_security_master(self, securities: list[dict[str, str]]) -> None:
        self.security_master_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(securities).to_parquet(self.security_master_path, index=False)

    def load_security_master(self) -> list[dict[str, str]]:
        if not self.security_master_path.exists():
            return []
        return pd.read_parquet(self.security_master_path).to_dict("records")

    def initialize_catalog(self) -> CatalogReport:
        self.output_root.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute(
                """
                create table if not exists dataset_manifest (
                    dataset_key varchar primary key,
                    content_hash varchar not null,
                    dataset_version varchar not null,
                    imported_at timestamp default current_timestamp,
                    raw_path varchar,
                    factor_path varchar,
                    derived_path varchar,
                    snapshot_version varchar
                )
                """
            )
            connection.execute(
                """
                create table if not exists data_quality_events (
                    event_id varchar default uuid(),
                    dataset_key varchar not null,
                    event_type varchar not null,
                    severity varchar not null,
                    message varchar not null,
                    created_at timestamp default current_timestamp
                )
                """
            )
            for column in ("raw_path", "factor_path", "derived_path", "snapshot_version"):
                connection.execute(
                    f"alter table dataset_manifest add column if not exists {column} varchar"
                )
            connection.execute(
                "alter table data_quality_events add column if not exists content_hash varchar"
            )
        return CatalogReport("ready", str(self.catalog_path))

    @staticmethod
    def _hash_frames(*frames: pd.DataFrame) -> str:
        digest = hashlib.sha256()
        for frame in frames:
            digest.update(pd.util.hash_pandas_object(frame, index=True).values.tobytes())
        return digest.hexdigest()

    def import_security(
        self,
        exchange: str,
        code: str,
        raw: pd.DataFrame,
        factors: pd.DataFrame,
        dataset_version: str = "raw-factor-v1",
    ) -> ImportReport:
        if raw.empty or factors.empty:
            raise ValueError(f"AkShare returned empty raw/factor facts for {exchange}{code}")
        dataset_key = f"stock:{exchange}:{code}"
        content_hash = self._hash_frames(raw, factors)
        snapshot_version = "snapshot-" + content_hash[:16]
        root = self.output_root / "data-foundation-v1" / "snapshots" / snapshot_version
        raw_path = root / "facts" / "raw_bars" / exchange / f"{code}.parquet"
        factor_path = root / "facts" / "adjustment_factors" / exchange / f"{code}.parquet"
        normalized_path = root / "derived" / exchange / f"{code}.parquet"
        with self.connection() as connection:
            existing = connection.execute(
                "select content_hash from dataset_manifest where dataset_key = ?", [dataset_key]
            ).fetchone()
            if existing and existing[0] == content_hash and all(
                path.exists() for path in (raw_path, factor_path, normalized_path)
            ):
                return ImportReport(
                    "unchanged", dataset_key, str(raw_path), str(normalized_path),
                    str(factor_path), snapshot_version
                )
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw.to_parquet(raw_path, index=False)
            factor_path.parent.mkdir(parents=True, exist_ok=True)
            factors.to_parquet(factor_path, index=False)
            try:
                normalized = DerivedAdjustmentEngine().derive(raw, factors)
            except ValueError as exc:
                connection.execute(
                    """insert into data_quality_events(
                        dataset_key, event_type, severity, message
                    ) values (?, 'factor-coverage-error', 'error', ?)""",
                    [dataset_key, str(exc)],
                )
                raise
            if "fields_partial" in raw and raw["fields_partial"].fillna(False).any():
                connection.execute(
                    """insert into data_quality_events(
                        dataset_key, event_type, severity, message
                    ) values (?, 'fields-partial', 'warning', 'fallback rows have partial fields')""",
                    [dataset_key],
                )
            for length in (5, 10, 20, 60):
                normalized[f"ma{length}"] = normalized["close_qfq"].rolling(length).mean().round(6)
            normalized_path.parent.mkdir(parents=True, exist_ok=True)
            normalized.to_parquet(normalized_path, index=False)
            connection.execute(
                """
                insert into dataset_manifest(
                    dataset_key, content_hash, dataset_version, raw_path, factor_path,
                    derived_path, snapshot_version
                )
                values (?, ?, ?, ?, ?, ?, ?)
                on conflict(dataset_key) do update set
                    content_hash=excluded.content_hash,
                    dataset_version=excluded.dataset_version,
                    imported_at=now(),
                    raw_path=excluded.raw_path,
                    factor_path=excluded.factor_path,
                    derived_path=excluded.derived_path,
                    snapshot_version=excluded.snapshot_version
                """,
                [dataset_key, content_hash, dataset_version, str(raw_path), str(factor_path),
                 str(normalized_path), snapshot_version],
            )
        return ImportReport(
            "imported", dataset_key, str(raw_path), str(normalized_path), str(factor_path),
            snapshot_version
        )

    def latest_derived_path(self, exchange: str, code: str) -> Path | None:
        with self.connection() as connection:
            row = connection.execute(
                "select derived_path from dataset_manifest where dataset_key = ?",
                [f"stock:{exchange}:{code}"],
            ).fetchone()
        return self._resolve_manifest_path(row[0]) if row and row[0] else None

    def latest_snapshot_version(self, exchange: str, code: str) -> str | None:
        with self.connection() as connection:
            row = connection.execute(
                "select snapshot_version from dataset_manifest where dataset_key = ?",
                [f"stock:{exchange}:{code}"],
            ).fetchone()
        return row[0] if row and row[0] else None

    def cached_market_counts(self) -> dict[str, int]:
        with self.connection() as connection:
            rows = connection.execute(
                """select split_part(dataset_key, ':', 2) market, count(*)
                from dataset_manifest where dataset_key like 'stock:%'
                group by market"""
            ).fetchall()
        counts = {"sh": 0, "sz": 0, "bj": 0}
        counts.update({market: count for market, count in rows})
        return counts

    def cached_securities(self) -> list[dict[str, str]]:
        with self.connection() as connection:
            rows = connection.execute(
                """select split_part(dataset_key, ':', 2), split_part(dataset_key, ':', 3),
                derived_path, snapshot_version from dataset_manifest
                where dataset_key like 'stock:%' and derived_path is not null
                order by dataset_key"""
            ).fetchall()
        return [
            {
                "exchange": exchange,
                "code": code,
                "derived_path": str(self._resolve_manifest_path(derived_path)),
                "snapshot_version": snapshot_version,
            }
            for exchange, code, derived_path, snapshot_version in rows
        ]

    def dataset_manifest_rows(self) -> list[dict[str, str]]:
        with self.connection() as connection:
            rows = connection.execute(
                """select dataset_key, content_hash, derived_path, snapshot_version
                from dataset_manifest where derived_path is not null order by dataset_key"""
            ).fetchall()
        keys = ("dataset_key", "content_hash", "derived_path", "snapshot_version")
        items = [dict(zip(keys, row, strict=True)) for row in rows]
        for item in items:
            item["derived_path"] = str(self._resolve_manifest_path(item["derived_path"]))
        return items

    def record_quality_event(
        self,
        dataset_key: str,
        event_type: str,
        severity: str,
        message: str,
        *,
        content_hash: str | None = None,
    ) -> None:
        with self.connection() as connection:
            connection.execute(
                """insert into data_quality_events(
                    dataset_key, event_type, severity, message, content_hash
                ) values (?, ?, ?, ?, ?)""",
                [dataset_key, event_type, severity, message, content_hash],
            )

    def quality_events(self, limit: int = 100) -> list[dict[str, str]]:
        with self.connection() as connection:
            rows = connection.execute(
                """select dataset_key, event_type, severity, message, created_at, content_hash
                from data_quality_events order by created_at desc limit ?""",
                [limit],
            ).fetchall()
        keys = (
            "dataset_key", "event_type", "severity", "message", "created_at", "content_hash"
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def market_cleanup(self):
        from .market_cleanup import MarketCleanup

        return MarketCleanup(self)
