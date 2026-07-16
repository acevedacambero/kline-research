from __future__ import annotations

import argparse
import json
from pathlib import Path

from kline.config import Settings
from kline.data.identity_audit import IdentityAuditPlan, SecurityIdentityAudit
from kline.data.pipeline import DatasetPipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit exchange/code identity consistency")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/security-identity-audit.json")
    )
    parser.add_argument("--execute-event-cleanup", action="store_true")
    parser.add_argument("--plan", type=Path)
    args = parser.parse_args()
    root = args.data_root or Settings().data_path
    audit = SecurityIdentityAudit(DatasetPipeline(root))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.execute_event_cleanup:
        if args.plan is None:
            parser.error("event cleanup requires --plan <audit-plan.json>")
        plan = IdentityAuditPlan.from_dict(json.loads(args.plan.read_text(encoding="utf-8")))
        result = audit.purge_invalid_events(plan)
    else:
        result = audit.scan().to_dict()
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
