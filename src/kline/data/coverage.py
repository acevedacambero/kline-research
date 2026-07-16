from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
import json
from pathlib import Path
from typing import Iterable

import pandas as pd
import pyarrow.parquet as pq

from ..storage import atomic_write_text


COVERAGE_REPORT_VERSION = "market-coverage-v2-suspension-aware"
REPAIRABLE_STATUSES = frozenset(
    {"missing", "unreadable", "short_history", "stale", "approximate_factor"}
)


class MarketCoverageService:
    """Build and persist an auditable SH/SZ security coverage ledger."""

    def __init__(
        self,
        pipeline,
        report_path: Path,
        *,
        min_history_rows: int = 250,
        freshness_days: int = 10,
        gap_days: int = 10,
    ) -> None:
        self.pipeline = pipeline
        self.report_path = Path(report_path)
        self.min_history_rows = min_history_rows
        self.freshness_days = freshness_days
        self.gap_days = gap_days

    def load(self) -> dict | None:
        if not self.report_path.exists():
            return None
        try:
            value = json.loads(self.report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return value if value.get("version") == COVERAGE_REPORT_VERSION else None

    def _date_column(self, path: Path) -> tuple[int, date, date, int]:
        parquet = pq.ParquetFile(path)
        if parquet.metadata.num_rows <= 0 or "date" not in parquet.schema.names:
            raise ValueError("empty file or missing date column")
        values = pd.to_datetime(parquet.read(columns=["date"])["date"].to_pandas()).dt.date
        if values.empty:
            raise ValueError("empty date column")
        ordered = values.sort_values().drop_duplicates()
        gaps = int(
            sum((right - left).days > self.gap_days for left, right in zip(ordered, ordered[1:]))
        )
        return int(parquet.metadata.num_rows), ordered.iloc[0], ordered.iloc[-1], gaps

    def build(
        self,
        universe: Iterable[dict[str, str]],
        *,
        approximate_securities: Iterable[str] = (),
        progress=None,
    ) -> dict:
        cached = {
            f"{item['exchange']}{item['code']}": item
            for item in self.pipeline.cached_securities()
            if item["exchange"] in {"sh", "sz"}
        }
        approximate = set(approximate_securities)
        securities = []
        seen = set()
        for item in universe:
            exchange, code = str(item.get("exchange", "")), str(item.get("code", "")).zfill(6)
            key = f"{exchange}{code}"
            if exchange not in {"sh", "sz"} or not code.isdigit() or key in seen:
                continue
            seen.add(key)
            securities.append({**item, "exchange": exchange, "code": code, "security": key})

        inspected = []
        market_latest: dict[str, date] = {}
        for index, item in enumerate(securities, 1):
            key = item["security"]
            cached_item = cached.get(key)
            row = {
                "security": key,
                "exchange": item["exchange"],
                "code": item["code"],
                "name": str(item.get("name", "")),
                "status": "missing",
                "rows": 0,
                "firstDate": None,
                "latestDate": None,
                "calendarGapCount": 0,
                "snapshotVersion": None,
                "reason": "本地尚无行情快照",
                "repairable": True,
            }
            if cached_item:
                row["snapshotVersion"] = cached_item.get("snapshot_version")
                try:
                    count, first, latest, gaps = self._date_column(Path(cached_item["derived_path"]))
                    row.update(
                        rows=count,
                        firstDate=first.isoformat(),
                        latestDate=latest.isoformat(),
                        calendarGapCount=gaps,
                        status="pending_classification",
                        reason="等待全市场新鲜度分类",
                    )
                    market_latest[item["exchange"]] = max(
                        market_latest.get(item["exchange"], latest), latest
                    )
                except Exception as exc:
                    row.update(status="unreadable", reason=str(exc))
            inspected.append(row)
            if progress:
                progress({"done": index, "total": len(securities), "currentSecurity": key})

        for row in inspected:
            if row["status"] != "pending_classification":
                continue
            latest = date.fromisoformat(row["latestDate"])
            latest_market_date = market_latest.get(row["exchange"], latest)
            if row["rows"] < self.min_history_rows:
                row.update(status="short_history", reason=f"有效日线少于 {self.min_history_rows} 条")
            elif (latest_market_date - latest).days > self.freshness_days:
                row.update(status="stale", reason=f"落后市场最新日期超过 {self.freshness_days} 天")
            elif row["security"] in approximate:
                row.update(status="approximate_factor", reason="当前快照使用近似复权因子")
            else:
                reason = "行情、历史长度与复权状态通过"
                if row["calendarGapCount"]:
                    reason += (
                        f"；{row['calendarGapCount']} 个长间隔按停牌或节假日处理，"
                        "不作为数据缺口"
                    )
                row.update(status="ready", reason=reason)
                row["repairable"] = False

        status_counts = Counter(item["status"] for item in inspected)
        exchange_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for item in inspected:
            exchange_counts[item["exchange"]][item["status"]] += 1
            exchange_counts[item["exchange"]]["total"] += 1
        ready = status_counts["ready"]
        report = {
            "version": COVERAGE_REPORT_VERSION,
            "generatedAt": datetime.now().astimezone().isoformat(),
            "universeSize": len(inspected),
            "cachedCount": len(inspected) - status_counts["missing"],
            "readyCount": ready,
            "repairableCount": sum(status_counts[item] for item in REPAIRABLE_STATUSES),
            "coverageRate": ready / len(inspected) if inspected else 0.0,
            "statusCounts": dict(sorted(status_counts.items())),
            "exchangeCounts": {key: dict(value) for key, value in exchange_counts.items()},
            "thresholds": {
                "minimumHistoryRows": self.min_history_rows,
                "freshnessDays": self.freshness_days,
                "calendarGapDays": self.gap_days,
            },
            "securities": inspected,
        }
        atomic_write_text(json.dumps(report, ensure_ascii=False, indent=2), self.report_path)
        return report

    def repair_queue(self, statuses: Iterable[str] | None = None) -> list[dict]:
        report = self.load()
        if not report:
            return []
        selected = set(statuses or REPAIRABLE_STATUSES) & REPAIRABLE_STATUSES
        return [
            item for item in report.get("securities", [])
            if item.get("repairable") and item.get("status") in selected
        ]
