from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import uuid

from ..storage import atomic_write_text


class ManagementAuditLog:
    """Small durable audit ledger for state-changing management operations."""

    def __init__(self, path: Path, *, capacity: int = 1000) -> None:
        self.path = Path(path)
        self.capacity = max(1, capacity)
        self._lock = threading.Lock()

    def _read(self) -> list[dict]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, list) else []
        except (FileNotFoundError, OSError, ValueError, TypeError):
            return []

    def record(
        self,
        action: str,
        *,
        target: str | None = None,
        details: dict | None = None,
    ) -> dict:
        entry = {
            "id": uuid.uuid4().hex,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "target": target,
            "details": details or {},
        }
        with self._lock:
            entries = self._read()
            entries.append(entry)
            atomic_write_text(
                json.dumps(entries[-self.capacity :], ensure_ascii=False, indent=2),
                self.path,
            )
        return entry

    def list(self, *, limit: int = 100) -> list[dict]:
        bounded = max(1, min(self.capacity, limit))
        with self._lock:
            return list(reversed(self._read()))[:bounded]
