from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from kline.ops.provider_probe import ProviderProbeRunner


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe production market-data providers")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/provider_probe.json"),
        help="UTF-8 JSON report path (default: data/provider_probe.json)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run a reduced diagnostic probe; never qualifies as a production pass",
    )
    return parser


def main(
    argv: Sequence[str] | None = None, *, runner: ProviderProbeRunner | None = None
) -> int:
    args = _parser().parse_args(argv)
    report = (runner or ProviderProbeRunner()).run(quick=args.quick)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print("provider    ok/total   success   mean(s)   p95(s)")
    for provider, summary in report.providers.items():
        print(
            f"{provider:<11} {summary.successes:>2}/{summary.observations:<7} "
            f"{summary.success_rate:>7.1%}   {summary.mean_latency_seconds:>7.3f}   "
            f"{summary.p95_latency_seconds:>6.3f}"
        )
    status = "DIAGNOSTIC" if args.quick else ("PASS" if report.passed else "FAIL")
    if report.reasons:
        print("required failures:")
        for reason in report.reasons:
            print(f"  - {reason}")
    if report.warnings:
        print("warnings:")
        for warning in report.warnings:
            print(f"  - {warning}")
    print(f"status: {status}; report: {args.output}")
    return 2 if args.quick else (0 if report.passed else 1)


if __name__ == "__main__":
    raise SystemExit(main())
