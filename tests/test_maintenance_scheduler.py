from datetime import datetime
from zoneinfo import ZoneInfo

from kline.ops.maintenance import DailyMaintenanceScheduler


def test_scheduler_runs_once_per_weekday_and_persists_status(tmp_path):
    calls = []
    path = tmp_path / "schedule.json"
    scheduler = DailyMaintenanceScheduler(path, lambda: calls.append("run") or "task-1")
    scheduler.configure(enabled=True, hour=18, minute=30)
    due = datetime(2026, 7, 16, 18, 31, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert scheduler.tick(due) is True
    assert scheduler.tick(due) is False
    assert calls == ["run"]
    assert scheduler.status(due)["lastTaskId"] == "task-1"

    reopened = DailyMaintenanceScheduler(path, lambda: "task-2")
    assert reopened.status(due)["lastRunDate"] == "2026-07-16"


def test_scheduler_skips_weekends_and_records_callback_conflict(tmp_path):
    def conflict():
        raise RuntimeError("heavy task is active")

    scheduler = DailyMaintenanceScheduler(tmp_path / "schedule.json", conflict)
    scheduler.configure(enabled=True, hour=18, minute=30)
    saturday = datetime(2026, 7, 18, 19, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    monday = datetime(2026, 7, 20, 19, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert scheduler.tick(saturday) is False
    assert scheduler.tick(monday) is True
    assert scheduler.status(monday)["lastOutcome"] == "skipped"
    assert scheduler.status(monday)["lastError"] == "heavy task is active"
