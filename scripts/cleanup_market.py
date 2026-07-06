from __future__ import annotations

import argparse
import json
from pathlib import Path

from kline.config import Settings
from kline.data.market_cleanup import CleanupPlan, MarketCleanup
from kline.data.pipeline import DatasetPipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or execute exact market cleanup")
    parser.add_argument("--exchange", required=True)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/bj-cleanup-plan.json"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--plan", type=Path)
    args = parser.parse_args()
    root = args.data_root or Settings().data_path
    cleanup = MarketCleanup(DatasetPipeline(root))
    args.output.parent.mkdir(parents=True, exist_ok=True)

    if args.execute:
        if args.exchange != "bj" or args.plan is None:
            parser.error("execution requires --exchange bj --plan <plan.json>")
        plan = CleanupPlan.from_dict(json.loads(args.plan.read_text(encoding="utf-8")))
        result = cleanup.execute(plan).to_dict()
    else:
        result = cleanup.plan_cleanup(args.exchange).to_dict()
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
