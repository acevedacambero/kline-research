from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .pipeline import DatasetPipeline
from .provider_policy import SUPPORTED_EXCHANGES


@dataclass(frozen=True, slots=True)
class BackfillCandidate:
    exchange: str
    code: str
    path: Path
    snapshot_version: str
    content_hash: str
    before_count: int


@dataclass(frozen=True, slots=True)
class BackfillResult:
    status: str
    before_count: int
    after_count: int
    snapshot_version: str


class BackfillCoverageError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class HistoryBackfillService:
    def __init__(
        self,
        pipeline: DatasetPipeline,
        source,
        *,
        min_days: int = 250,
        freshness_days: int = 10,
    ) -> None:
        self.pipeline = pipeline
        self.source = source
        self.min_days = min_days
        self.freshness_days = freshness_days

    def scan(self) -> list[BackfillCandidate]:
        acknowledged = {
            (event["dataset_key"], event["content_hash"])
            for event in self.pipeline.quality_events(limit=100_000)
            if event["event_type"] == "listing-history-short" and event["content_hash"]
        }
        candidates = []
        for item in self.pipeline.dataset_manifest_rows():
            prefix, exchange, code = item["dataset_key"].split(":", 2)
            if prefix != "stock" or exchange not in SUPPORTED_EXCHANGES:
                continue
            if (item["dataset_key"], item["content_hash"]) in acknowledged:
                continue
            path = Path(item["derived_path"])
            frame = pd.read_parquet(path, columns=["date"])
            count = int(frame["date"].dropna().nunique())
            if count < self.min_days:
                candidates.append(
                    BackfillCandidate(
                        exchange=exchange,
                        code=code,
                        path=path,
                        snapshot_version=item["snapshot_version"],
                        content_hash=item["content_hash"],
                        before_count=count,
                    )
                )
        return candidates

    def backfill(
        self, candidate: BackfillCandidate, *, as_of_date: date
    ) -> BackfillResult:
        dataset_key = f"stock:{candidate.exchange}:{candidate.code}"
        try:
            raw, factors = self.source.fetch_long_history_bundle(
                candidate.exchange,
                candidate.code,
                date(1990, 1, 1),
                as_of_date,
            )
            if raw.empty or "date" not in raw:
                raise BackfillCoverageError(
                    "HISTORY_EMPTY", "long-history provider returned no dated rows"
                )
            dates = pd.to_datetime(raw["date"], errors="raise").dt.date
            after_count = int(dates.nunique())
            latest_date = max(dates)
            if after_count < self.min_days and latest_date < (
                as_of_date - timedelta(days=self.freshness_days)
            ):
                raise BackfillCoverageError(
                    "HISTORY_COVERAGE_INCOMPLETE",
                    f"long history has {after_count} rows and ends at {latest_date}",
                )
            report = self.pipeline.import_security(
                candidate.exchange, candidate.code, raw, factors
            )
            manifest = next(
                item
                for item in self.pipeline.dataset_manifest_rows()
                if item["dataset_key"] == dataset_key
            )
            if after_count < self.min_days:
                self.pipeline.record_quality_event(
                    dataset_key,
                    "listing-history-short",
                    "info",
                    f"listing history has {after_count} days through {latest_date}",
                    content_hash=manifest["content_hash"],
                )
                status = "listing_history_short"
            else:
                self.pipeline.record_quality_event(
                    dataset_key,
                    "history-backfilled",
                    "info",
                    f"history backfilled {candidate.before_count} -> {after_count} via sina-akshare",
                    content_hash=manifest["content_hash"],
                )
                status = "completed"
            return BackfillResult(
                status=status,
                before_count=candidate.before_count,
                after_count=after_count,
                snapshot_version=report.snapshot_version,
            )
        except Exception as exc:
            if not isinstance(exc, BackfillCoverageError):
                exc = BackfillCoverageError("HISTORY_BACKFILL_FAILED", str(exc))
            self.pipeline.record_quality_event(
                dataset_key,
                "history-backfill-failed",
                "error",
                f"{exc.code}: {exc}",
                content_hash=candidate.content_hash,
            )
            raise exc
