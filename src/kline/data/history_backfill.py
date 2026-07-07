from __future__ import annotations

from dataclasses import dataclass
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


class HistoryBackfillService:
    def __init__(self, pipeline: DatasetPipeline, source, *, min_days: int = 250) -> None:
        self.pipeline = pipeline
        self.source = source
        self.min_days = min_days

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
