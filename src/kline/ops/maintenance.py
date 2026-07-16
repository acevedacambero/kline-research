from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import threading
from zoneinfo import ZoneInfo

from ..storage import atomic_write_text


class DailyMaintenanceScheduler:
    """Small persistent weekday scheduler; the callback submits work to the single writer."""

    def __init__(
        self,
        state_path: Path,
        callback,
        *,
        timezone: str = "Asia/Shanghai",
        enabled: bool = False,
        hour: int = 18,
        minute: int = 30,
    ) -> None:
        self.state_path = Path(state_path)
        self.callback = callback
        self.timezone = ZoneInfo(timezone)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = {
            "version": "daily-maintenance-v1",
            "enabled": enabled,
            "hour": hour,
            "minute": minute,
            "lastRunDate": None,
            "lastAttemptAt": None,
            "lastTaskId": None,
            "lastOutcome": None,
            "lastError": None,
        }
        self._load()

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if saved.get("version") == self._state["version"]:
            self._state.update(saved)

    def _persist(self) -> None:
        atomic_write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2), self.state_path
        )

    def configure(self, *, enabled: bool, hour: int, minute: int) -> dict:
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("hour/minute outside valid range")
        with self._lock:
            self._state.update(enabled=enabled, hour=hour, minute=minute)
            self._persist()
            return self.status()

    def _next_run(self, now: datetime) -> datetime | None:
        if not self._state["enabled"]:
            return None
        candidate = now.replace(
            hour=int(self._state["hour"]),
            minute=int(self._state["minute"]),
            second=0,
            microsecond=0,
        )
        if candidate <= now:
            candidate += timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate

    def status(self, now: datetime | None = None) -> dict:
        with self._lock:
            local_now = (now or datetime.now(self.timezone)).astimezone(self.timezone)
            next_run = self._next_run(local_now)
            return {
                **self._state,
                "timezone": str(self.timezone),
                "running": bool(self._thread and self._thread.is_alive()),
                "nextRunAt": next_run.isoformat() if next_run else None,
            }

    def tick(self, now: datetime | None = None) -> bool:
        local_now = (now or datetime.now(self.timezone)).astimezone(self.timezone)
        with self._lock:
            scheduled = local_now.replace(
                hour=int(self._state["hour"]),
                minute=int(self._state["minute"]),
                second=0,
                microsecond=0,
            )
            today = local_now.date().isoformat()
            due = (
                self._state["enabled"]
                and local_now.weekday() < 5
                and local_now >= scheduled
                and self._state.get("lastRunDate") != today
            )
            if not due:
                return False
            self._state.update(lastRunDate=today, lastAttemptAt=local_now.isoformat())
            try:
                task_id = self.callback()
            except Exception as exc:
                self._state.update(lastOutcome="skipped", lastError=str(exc), lastTaskId=None)
            else:
                self._state.update(lastOutcome="submitted", lastError=None, lastTaskId=task_id)
            self._persist()
            return True

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop():
            while not self._stop.wait(30):
                self.tick()

        self._thread = threading.Thread(target=loop, name="maintenance-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

