from __future__ import annotations

import argparse
import json
import time

from fastapi.testclient import TestClient

from kline.api import create_app
from kline.config import Settings


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def run_task(
    client: TestClient,
    path: str,
    *,
    payload: dict | None = None,
    poll_seconds: float,
) -> dict:
    response = client.post(path, json=payload) if payload is not None else client.post(path)
    response.raise_for_status()
    submitted = response.json()
    task_id = submitted["taskId"]
    print(json.dumps({"event": "submitted", "path": path, **submitted}), flush=True)
    last_marker = None
    while True:
        task_response = client.get(f"/api/tasks/{task_id}")
        task_response.raise_for_status()
        task = task_response.json()
        marker = (
            task.get("status"),
            task.get("stage"),
            task.get("done"),
            task.get("total"),
            len(task.get("errors") or []),
        )
        if marker != last_marker:
            print(
                json.dumps(
                    {
                        "event": "progress",
                        "taskId": task_id,
                        "status": marker[0],
                        "stage": marker[1],
                        "done": marker[2],
                        "total": marker[3],
                        "errors": marker[4],
                    }
                ),
                flush=True,
            )
            last_marker = marker
        if task["status"] in TERMINAL_STATUSES:
            if task["status"] != "completed":
                raise RuntimeError(json.dumps(task, ensure_ascii=False, default=str))
            return task
        time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the final server-side data and P1-P3 build with one writer."
    )
    parser.add_argument("--skip-backfill", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    args = parser.parse_args()

    settings = Settings(cloudflare_access_required=False)
    with TestClient(create_app(settings)) as client:
        if not args.skip_backfill:
            run_task(
                client,
                "/api/datasets/backfill-history",
                poll_seconds=args.poll_seconds,
            )
        run_task(
            client,
            "/api/datasets/coverage/rebuild",
            payload={"refresh_security_master": False},
            poll_seconds=args.poll_seconds,
        )
        run_task(
            client,
            "/api/pipeline/research/build",
            payload={"scope": "all"},
            poll_seconds=args.poll_seconds,
        )
        acceptance = client.get("/api/system/research-acceptance")
        acceptance.raise_for_status()
        print(
            json.dumps(
                {"event": "acceptance", "report": acceptance.json()},
                ensure_ascii=False,
                default=str,
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
